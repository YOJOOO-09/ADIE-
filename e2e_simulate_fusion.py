"""
ADIE — End-to-End Simulation Run
This script simulates what happens inside Fusion 360 when a CAD design is saved.
Because we don't have Fusion 360 running in this terminal, we construct a
"dummy CAD file" using our API stubs to simulate a block with thin sliver edges
and an oversized volume violating ISO 2768 tolerances.
"""

import os
import sys
import json
from pathlib import Path

# Add paths so we can import the agents
_ADIE_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(_ADIE_ROOT))
sys.path.insert(0, str(_ADIE_ROOT / "fusion_addin"))
sys.path.insert(0, str(_ADIE_ROOT / "tests"))

from config import CONFIG, ensure_data_dirs
from fusion_addin.monitor_agent import MonitorAgent
from fusion_addin.mitigation_agent import MitigationAgent
import fusion_addin.mitigation_agent as mitig_mod

# ── 1. Import our mock CAD engine from unit tests ───────────────────────────
try:
    from tests.test_monitor import _DesignStub, _BodyStub, _EdgeStub, Circle3D
except ImportError:
    print("Test stubs not found. Please ensure adie/tests/test_monitor.py exists.")
    sys.exit(1)

# ── 2. Mock the HITL UI for this terminal test ──────────────────────────────
# We trick the Mitigation agent into thinking adsk is available and "yes" was typed.
mitig_mod._ADSK_AVAILABLE = True

class MockUI:
    def inputBox(self, prompt, title, default):
        print(f"\n[FUSION 360 POPUP] {title}")
        print(f"{prompt}")
        print(">> Auto-typing: 'yes'\n")
        return ("yes", False)

def mock_get_ui():
    return MockUI()

mitig_mod._get_ui = mock_get_ui
mitig_mod._palette_write = lambda msg: print(f"[FUSION CONSOLE] {msg}")

# ── 3. Construct a "Sample CAD File" (Violation heavy) ──────────────────────
print("\n" + "═"*60)
print("  🛠️  CONSTRUCTING SAMPLE CAD FILE (Memory Representation)")
print("═"*60)

# We create a CAD body that severely violates rules:
# 1. Edge length of 0.1mm (Violates R002 - Min Edge Length 0.5mm)
# 2. Volume of 5,000,000 mm³ (Violates R004 - Max Body Volume 1,000,000 mm³)
# 3. Tiny hole (radius 0.2mm = diameter 0.4 mm) (Violates R003 - Min Hole Diameter 1.0mm)
bad_geom = Circle3D(radius_cm=0.02) # radius 0.02cm = 0.2mm
bad_body = _BodyStub(
    name="Bracket_V1_Overengineered",
    is_solid=True,
    volume_cm3=5000.0, # 5,000 cm³ = 5,000,000 mm³
    edges=[
        _EdgeStub(length_cm=0.01),              # 0.1mm length
        _EdgeStub(length_cm=0.12, geom=bad_geom) # tiny hole perimeter
    ]
)

mock_design = _DesignStub(bodies=[bad_body])
print(f"Loaded Body: '{bad_body.name}'")
print(f" - Volume: 5,000,000 mm³")
print(f" - Edges: Contains 0.1mm sliver edge")
print(f" - Features: Contains 0.4mm diameter drilled hole\n")

# ── 4. Initialize Data Dirs and Agents ──────────────────────────────────────
ensure_data_dirs()

print("Initializing Monitor Agent...")
monitor = MonitorAgent(
    scripts_dir=CONFIG["validation_scripts_dir"],
    violations_path=CONFIG["violations_json"],
    script_errors_log=CONFIG["script_errors_log"],
    rules_path=CONFIG["rules_json"],
    config=CONFIG,
)
monitor.load()

print(f"Initializing Mitigation Agent (AI Fixes {'Enabled' if CONFIG.get('gemini_api_key') else 'Disabled'})...")
mitigation = MitigationAgent(
    api_key=CONFIG.get("gemini_api_key", ""),
    audit_log_path=CONFIG["audit_log_json"],
    pending_path=CONFIG["pending_suggestion"],
    model_name=CONFIG["gemini_model"],
)

# Connect them (Monitor calls Mitigation when done)
monitor.on_violations_ready = mitigation.process_violations

# ── 5. Execute End-to-End Run ───────────────────────────────────────────────
print("\n" + "═"*60)
print("  🚀 TRIGGERING 'documentSaved' EVENT...")
print("═"*60)

# Simulate Fusion triggering the event with our design
violations = monitor._run_all_scripts(mock_design)
monitor._write_violations(violations)

# Output summary based on what was detected
print(f"\n[MONITOR REPORT] Found {len(violations)} rule violations in CAD model:")
for v in violations:
    passed_mark = '✅' if v['passed'] else '❌'
    print(f"  {passed_mark} {v['rule_id']} [{v['severity'].upper()}]: {v['violation_detail']}")

# Trigger the HTML report generation explicitly so it writes to disk
from fusion_addin.report_generator import generate_html_report
from fusion_addin.monitor_agent import load_rules_index
rules_index = load_rules_index(CONFIG["rules_json"])
html_path = generate_html_report(violations, rules_index, CONFIG["html_report"], "Bracket_V1_Overengineered")
print(f"\n[REPORT] Saved stylized HTML Violations report: {html_path.resolve()}")

# Process violations through mitigation (AI auto-fix pipeline)
print("\n" + "═"*60)
print("  ⚙️  TRIGGERING MITIGATION AGENT (HITL & AI Fixes)")
print("═"*60)

mitigation.process_violations(violations)

# ── 6. Check Audit Logs ─────────────────────────────────────────────────────
print("\n" + "═"*60)
print("  📝 CHECKING AUDIT LOGS (Immutable record)")
print("═"*60)
audit_path = CONFIG["audit_log_json"]
if audit_path.exists():
    with open(audit_path, "r") as f:
        logs = json.load(f)
        print(f"Audit log contains {len(logs)} records.")
        latest = logs[-1] if logs else {}
        print(f"Last record stored for Rule: {latest.get('rule_id')}")
        print(f"Engineer Action: {latest.get('engineer_action')}")
else:
    print("No audit log written.")

print("\n🎉 End-to-End Test complete.")
