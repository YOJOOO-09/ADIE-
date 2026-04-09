"""
ADIE Unit Tests — test_monitor.py

Tests for monitor_agent.py and validation scripts that run outside Fusion 360.
Uses stub/mock design objects to simulate the Fusion 360 API.

Run:
    conda activate adie
    python -m pytest tests/test_monitor.py -v
"""

import ast
import json
import sys
import importlib.util
import math
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "fusion_addin"))


# ─────────────────────────────────────────────────────────────────────────────
# Fusion 360 API Stubs
# ─────────────────────────────────────────────────────────────────────────────

class Circle3D:
    """Mimics adsk.core.Circle3D"""
    def __init__(self, radius_cm: float):
        self.radius = radius_cm

class _EdgeStub:
    def __init__(self, length_cm: float, geom=None):
        self.length   = length_cm
        self.geometry = geom or MagicMock()
        self.vertices = MagicMock()
        self.vertices.count = 0

class _FaceStub:
    def __init__(self, area_cm2: float = 1.0):
        self.area = area_cm2

class _PhysProps:
    def __init__(self, volume_cm3: float = 100.0):
        self.volume = volume_cm3
        self.mass   = volume_cm3 * 0.0027  # aluminum density ~2.7 g/cm³
        bb = MagicMock()
        bb.minPoint.x, bb.minPoint.y, bb.minPoint.z = 0, 0, 0
        bb.maxPoint.x, bb.maxPoint.y, bb.maxPoint.z = 5, 2, 1  # 50×20×10 mm
        self.boundingBox = bb

class _BodyStub:
    """Mimics adsk.fusion.BRepBody"""
    def __init__(
        self,
        name: str = "Body1",
        is_solid: bool = True,
        edges: list | None = None,
        volume_cm3: float = 100.0,
        material_name: str = "Aluminum",
    ):
        self.name     = name
        self.isSolid  = is_solid
        self._edges   = edges or []

        # edges as collection
        self.edges         = MagicMock()
        self.edges.count   = len(self._edges)
        self.edges.item    = lambda i: self._edges[i]

        self.faces       = MagicMock()
        self.faces.count = 0

        self.physicalProperties = _PhysProps(volume_cm3)

        mat = MagicMock()
        mat.name = material_name
        self.material = mat

class _BodiesCollection:
    def __init__(self, bodies: list):
        self._bodies = bodies
        self.count   = len(bodies)

    def item(self, i):
        return self._bodies[i]

class _RootComponentStub:
    def __init__(self, bodies: list | None = None):
        self._bodies = bodies or []
        self.bRepBodies = _BodiesCollection(self._bodies)
        self.allBRepBodies = _BodiesCollection(self._bodies)
        self.name = "root"

class _DesignStub:
    def __init__(self, bodies: list | None = None):
        self.rootComponent = _RootComponentStub(bodies)
        self.unitsManager  = MagicMock()


# ─────────────────────────────────────────────────────────────────────────────
# Helper: load validation script with adsk injection
# ─────────────────────────────────────────────────────────────────────────────

def _load_script(script_path: Path) -> object:
    """Load a validation script, injecting math and mock adsk."""
    spec   = importlib.util.spec_from_file_location(script_path.stem, script_path)
    module = importlib.util.module_from_spec(spec)

    # Inject dependencies (same as MonitorAgent does)
    module.__dict__["math"] = math

    # Mock adsk namespace
    adsk_mock            = MagicMock()
    adsk_mock.core.Circle3D = Circle3D
    module.__dict__["adsk"] = adsk_mock

    spec.loader.exec_module(module)
    return module


# ─────────────────────────────────────────────────────────────────────────────
# Validation scripts — AST checks
# ─────────────────────────────────────────────────────────────────────────────

class TestValidationScriptAST:
    """All scripts in validation_scripts/ must parse with ast.parse()."""

    @pytest.fixture(params=list((_ROOT / "validation_scripts").glob("*.py")))
    def script_path(self, request):
        return request.param

    def test_script_parses(self, script_path):
        with open(script_path, encoding="utf-8") as f:
            source = f.read()
        # Should not raise
        tree = ast.parse(source)
        assert tree is not None

    def test_script_has_validate_function(self, script_path):
        with open(script_path, encoding="utf-8") as f:
            source = f.read()
        tree = ast.parse(source)
        func_names = [
            node.name for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef)
        ]
        has_validate = any(n.startswith("validate_") for n in func_names)
        assert has_validate, f"{script_path.name}: no validate_*() function found"


# ─────────────────────────────────────────────────────────────────────────────
# R001 — min wall thickness
# ─────────────────────────────────────────────────────────────────────────────

class TestR001MinWallThickness:

    @pytest.fixture
    def fn(self):
        path = _ROOT / "validation_scripts" / "R001_min_wall_thickness.py"
        if not path.exists():
            pytest.skip("R001 script not found")
        m = _load_script(path)
        return m.validate_R001

    def test_passes_when_all_edges_long_enough(self, fn):
        body = _BodyStub("Body1", edges=[
            _EdgeStub(0.5),  # 5mm — above 2mm threshold
            _EdgeStub(1.0),  # 10mm
        ])
        design = _DesignStub([body])
        result = fn(design)
        assert result["passed"] is True
        assert result["actual_value"] >= 2.0
        assert result["unit"] == "mm"

    def test_fails_when_edge_too_short(self, fn):
        body = _BodyStub("Body1", edges=[
            _EdgeStub(0.05),  # 0.5mm — below 2mm threshold
            _EdgeStub(1.0),
        ])
        design = _DesignStub([body])
        result = fn(design)
        assert result["passed"] is False
        assert result["actual_value"] < 2.0

    def test_no_solid_bodies_skipped(self, fn):
        body = _BodyStub("Body1", is_solid=False, edges=[_EdgeStub(0.01)])
        design = _DesignStub([body])
        result = fn(design)
        # Should pass (non-solid bodies are skipped)
        assert result["passed"] is True

    def test_empty_design_returns_valid_dict(self, fn):
        design = _DesignStub([])
        result = fn(design)
        assert isinstance(result, dict)
        assert "passed" in result
        assert "violation_detail" in result
        assert "actual_value" in result
        assert "required_value" in result
        assert "unit" in result


# ─────────────────────────────────────────────────────────────────────────────
# R002 — min edge length
# ─────────────────────────────────────────────────────────────────────────────

class TestR002MinEdgeLength:

    @pytest.fixture
    def fn(self):
        path = _ROOT / "validation_scripts" / "R002_min_edge_length.py"
        if not path.exists():
            pytest.skip("R002 script not found")
        m = _load_script(path)
        return m.validate_R002

    def test_passes_when_all_edges_long_enough(self, fn):
        body = _BodyStub("B", edges=[_EdgeStub(0.1), _EdgeStub(0.2)])  # 1mm, 2mm
        result = fn(_DesignStub([body]))
        assert result["passed"] is True

    def test_fails_for_sliver_edge(self, fn):
        body = _BodyStub("B", edges=[_EdgeStub(0.01)])  # 0.1mm — below 0.5mm
        result = fn(_DesignStub([body]))
        assert result["passed"] is False

    def test_contract_keys_all_present(self, fn):
        result = fn(_DesignStub([]))
        required_keys = {"passed", "violation_detail", "actual_value", "required_value", "unit"}
        assert required_keys.issubset(result.keys())


# ─────────────────────────────────────────────────────────────────────────────
# R003 — min hole diameter
# ─────────────────────────────────────────────────────────────────────────────

class TestR003MinHoleDiameter:

    @pytest.fixture
    def fn(self):
        path = _ROOT / "validation_scripts" / "R003_min_hole_diameter.py"
        if not path.exists():
            pytest.skip("R003 script not found")
        m = _load_script(path)
        return m.validate_R003

    def test_no_circular_edges_passes(self, fn):
        # Edges with non-Circle3D geometry → no holes found → skip → pass
        body = _BodyStub("B", edges=[_EdgeStub(0.5)])
        result = fn(_DesignStub([body]))
        assert result["passed"] is True

    def test_large_hole_passes(self, fn):
        # radius = 0.5cm = 5mm → diameter = 10mm > 1mm  ✅
        circle_geom = Circle3D(radius_cm=0.5)
        body = _BodyStub("B", edges=[_EdgeStub(length_cm=3.14, geom=circle_geom)])
        result = fn(_DesignStub([body]))
        assert result["passed"] is True
        assert abs(result["actual_value"] - 10.0) < 0.01

    def test_tiny_hole_fails(self, fn):
        # radius = 0.03cm = 0.3mm → diameter = 0.6mm < 1mm  ❌
        circle_geom = Circle3D(radius_cm=0.03)
        body = _BodyStub("B", edges=[_EdgeStub(length_cm=0.19, geom=circle_geom)])
        result = fn(_DesignStub([body]))
        assert result["passed"] is False


# ─────────────────────────────────────────────────────────────────────────────
# R004 — max body volume
# ─────────────────────────────────────────────────────────────────────────────

class TestR004MaxBodyVolume:

    @pytest.fixture
    def fn(self):
        path = _ROOT / "validation_scripts" / "R004_max_body_volume.py"
        if not path.exists():
            pytest.skip("R004 script not found")
        m = _load_script(path)
        return m.validate_R004

    def test_small_body_passes(self, fn):
        # 100 cm³ = 100_000 mm³ < 1_000_000 mm³ limit
        body = _BodyStub(volume_cm3=100.0)
        result = fn(_DesignStub([body]))
        assert result["passed"] is True

    def test_huge_body_fails(self, fn):
        # 2000 cm³ = 2_000_000 mm³ > 1_000_000 mm³
        body = _BodyStub(volume_cm3=2000.0)
        result = fn(_DesignStub([body]))
        assert result["passed"] is False


# ─────────────────────────────────────────────────────────────────────────────
# Monitor: load_rules_index
# ─────────────────────────────────────────────────────────────────────────────

class TestLoadRulesIndex:
    def test_loads_real_rules_json(self):
        from monitor_agent import load_rules_index
        rules_path = _ROOT / "data" / "rules.json"
        if not rules_path.exists():
            pytest.skip("rules.json not found")
        index = load_rules_index(rules_path)
        assert isinstance(index, dict)
        assert len(index) > 0
        for rid, rule in index.items():
            assert "rule_id" in rule
            assert rule["rule_id"] == rid

    def test_missing_file_returns_empty(self):
        from monitor_agent import load_rules_index
        index = load_rules_index(Path("nonexistent_rules.json"))
        assert index == {}


# ─────────────────────────────────────────────────────────────────────────────
# Report generator
# ─────────────────────────────────────────────────────────────────────────────

class TestReportGenerator:
    def test_generates_html_with_violations(self, tmp_path):
        from report_generator import generate_html_report
        violations = [
            {
                "rule_id": "R001", "body_name": "Body1", "passed": False,
                "violation_detail": "Wall 1.0mm < 2.0mm",
                "actual_value": 1.0, "required_value": 2.0, "unit": "mm",
                "severity": "critical", "timestamp": "2026-01-01T00:00:00+00:00",
            }
        ]
        rules_index = {"R001": {"rule_id": "R001", "rule": "min_wall_thickness",
                                "value": 2.0, "unit": "mm", "severity": "critical"}}
        out = generate_html_report(violations, rules_index, tmp_path / "report.html", "TestDesign")
        assert out.exists()
        html = out.read_text(encoding="utf-8")
        assert "ADIE" in html
        assert "R001" in html
        assert "CRITICAL" in html
        assert "violations_report" in str(out) or out.name == "report.html"

    def test_generates_html_no_violations(self, tmp_path):
        from report_generator import generate_html_report
        out = generate_html_report([], {}, tmp_path / "report.html", "CleanDesign")
        html = out.read_text(encoding="utf-8")
        assert "compliant" in html.lower()

    def test_output_is_valid_html_structure(self, tmp_path):
        from report_generator import generate_html_report
        out = generate_html_report([], {}, tmp_path / "report.html", "Test")
        html = out.read_text(encoding="utf-8")
        assert html.startswith("<!DOCTYPE html>")
        assert "</html>" in html

# ─────────────────────────────────────────────────────────────────────────────
# Mitigation: audit log
# ─────────────────────────────────────────────────────────────────────────────

class TestAuditLog:
    def test_append_creates_file(self, tmp_path):
        from mitigation_agent import append_audit
        path = tmp_path / "audit_log.json"
        entry = {"timestamp": "2026-01-01", "rule_id": "R001", "engineer_action": "approved"}
        append_audit(path, entry)
        assert path.exists()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert isinstance(data, list)
        assert len(data) == 1

    def test_append_never_overwrites(self, tmp_path):
        from mitigation_agent import append_audit
        path = tmp_path / "audit_log.json"
        for i in range(5):
            append_audit(path, {"seq": i, "engineer_action": "approved"})
        data = json.loads(path.read_text(encoding="utf-8"))
        assert len(data) == 5
        assert [e["seq"] for e in data] == list(range(5))

    def test_handles_corrupted_file(self, tmp_path):
        from mitigation_agent import append_audit
        path = tmp_path / "audit_log.json"
        path.write_text("{corrupted json{{", encoding="utf-8")
        # Should not raise — should backup and continue
        append_audit(path, {"rule_id": "R001", "engineer_action": "dismissed"})
        data = json.loads(path.read_text(encoding="utf-8"))
        assert len(data) == 1
