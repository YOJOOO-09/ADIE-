from fastapi import FastAPI, BackgroundTasks, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import sys
import os
from pathlib import Path
import json
import subprocess

# Backend path configuration
BACKEND_DIR = Path(__file__).resolve().parent
ADIE_ROOT = BACKEND_DIR.parent
DATA_DIR = ADIE_ROOT / "data"

sys.path.insert(0, str(ADIE_ROOT))

app = FastAPI(title="ADIE Premium Dashboard API")

# Enable CORS for React frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # For local dev
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def read_json_file(path: Path):
    if not path.exists():
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        return {"error": str(e)}

@app.get("/api/rules")
def get_rules():
    return read_json_file(DATA_DIR / "rules.json")

@app.get("/api/violations")
def get_violations():
    return read_json_file(DATA_DIR / "violations.json")

@app.get("/api/audit")
def get_audit_log():
    return read_json_file(DATA_DIR / "audit_log.json")

@app.get("/api/scripts")
def get_scripts():
    scripts_dir = ADIE_ROOT / "validation_scripts"
    if not scripts_dir.exists():
        return []
    scripts = []
    for f in scripts_dir.glob("*.py"):
        scripts.append({"name": f.name, "path": str(f.resolve())})
    return scripts

@app.post("/api/run-analyst")
async def run_analyst(file: UploadFile = File(None)):
    """Triggers the analyst agent using python."""
    target_pdf = ADIE_ROOT / "standards" / "sample.pdf"
    if file:
        content = await file.read()
        target_pdf.parent.mkdir(parents=True, exist_ok=True)
        target_pdf.write_bytes(content)

    script_path = ADIE_ROOT / "setup" / "analyst_agent.py"
    
    # Run synchronously for simplicity in this prototype, or background
    # Here we run asynchronously but block on API request so UI can show loading
    try:
        result = subprocess.run(
            ["python", str(script_path), "--pdf", str(target_pdf)],
            cwd=str(ADIE_ROOT),
            capture_output=True,
            text=True,
            check=True
        )
        return {"status": "success", "output": result.stdout}
    except subprocess.CalledProcessError as e:
        return {"status": "error", "output": e.stdout, "error": e.stderr}

@app.post("/api/run-synthesizer")
def run_synthesizer():
    """Triggers the synthesizer agent."""
    script_path = ADIE_ROOT / "setup" / "synthesizer_agent.py"
    try:
        result = subprocess.run(
            ["python", str(script_path)],
            cwd=str(ADIE_ROOT),
            capture_output=True,
            text=True,
            check=True
        )
        return {"status": "success", "output": result.stdout}
    except subprocess.CalledProcessError as e:
        return {"status": "error", "output": e.stdout, "error": e.stderr}

@app.post("/api/run-monitor-sim")
def run_monitor_sim():
    """Triggers the E2E E2E Simulation."""
    script_path = ADIE_ROOT / "e2e_simulate_fusion.py"
    try:
        result = subprocess.run(
            ["python", str(script_path)],
            cwd=str(ADIE_ROOT),
            capture_output=True,
            text=True,
            check=True
        )
        return {"status": "success", "output": result.stdout}
    except subprocess.CalledProcessError as e:
        return {"status": "error", "output": e.stdout, "error": e.stderr}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
