"""Stdlib-only backend for preview environments — no FastAPI/uvicorn required."""
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent
ADIE_ROOT = BACKEND_DIR.parent
DATA_DIR = ADIE_ROOT / "data"
SCRIPTS_DIR = ADIE_ROOT / "validation_scripts"

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "*",
}

def read_json(path):
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        return {"error": str(e)}

ROUTES = {
    "/api/rules":      lambda: read_json(DATA_DIR / "rules.json"),
    "/api/violations": lambda: read_json(DATA_DIR / "violations.json"),
    "/api/audit":      lambda: read_json(DATA_DIR / "audit_log.json"),
    "/api/scripts":    lambda: [
        {"name": f.name, "path": str(f.resolve())}
        for f in SCRIPTS_DIR.glob("*.py")
    ] if SCRIPTS_DIR.exists() else [],
}

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"[backend] {self.address_string()} - {fmt % args}")

    def send_cors(self):
        for k, v in CORS_HEADERS.items():
            self.send_header(k, v)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_cors()
        self.end_headers()

    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ROUTES:
            data = json.dumps(ROUTES[path]()).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.send_cors()
            self.end_headers()
            self.wfile.write(data)
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        body = json.dumps({"status": "ok", "message": "Stub — run agents manually"}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_cors()
        self.end_headers()
        self.wfile.write(body)

if __name__ == "__main__":
    host, port = "127.0.0.1", 8000
    server = HTTPServer((host, port), Handler)
    print(f"ADIE backend running at http://{host}:{port}")
    server.serve_forever()
