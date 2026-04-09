"""
ADIE — Autonomous Design Integrity Engine
Agent 3: monitor_agent.py  (runs inside Fusion 360 as event handler)

PURPOSE:
    Hooks into Fusion 360's documentSaved and documentActivated events.
    On each trigger (with 5-second debounce), dynamically imports every
    .py file in /validation_scripts/, injects adsk into each module's
    globals, executes its validate_* function, collects results, and
    writes violations.json.

    ZERO Gemini API calls — this agent is purely deterministic Python.

CRITICAL FIX vs Day-3 draft:
    - adsk is now injected into each loaded module before exec, so
      scripts can use adsk.core.Circle3D etc. without import statements.
    - Event handler classes use clean if/else pattern (not conditional
      metaclass inheritance) for reliability.

AUTHOR: Aryn Gahlot | ADIE Project | Day 3
"""

# ─────────────────────────────────────────────────────────────────────────────
# Standard library
# ─────────────────────────────────────────────────────────────────────────────
import importlib.util
import json
import logging
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

# ─────────────────────────────────────────────────────────────────────────────
# adsk guard
# ─────────────────────────────────────────────────────────────────────────────
try:
    import adsk.core
    import adsk.fusion
    import adsk
    _ADSK_AVAILABLE = True
except ImportError:
    _ADSK_AVAILABLE = False

log = logging.getLogger("ADIE.Monitor")

DEBOUNCE_SECONDS = 5.0


# ─────────────────────────────────────────────────────────────────────────────
# Script loader — injects adsk into each module before execution
# ─────────────────────────────────────────────────────────────────────────────

def load_validation_scripts(scripts_dir: Path) -> list[tuple[str, object]]:
    """
    Dynamically import every .py in scripts_dir.

    Key: before exec_module(), we inject 'adsk', 'adsk.core', 'adsk.fusion'
    into the module's __dict__ so Synthesizer-generated scripts that
    reference adsk.core.* without import statements will work correctly.

    Returns list of (rule_id, validate_function) tuples.
    Import/execution errors are caught and logged — never halt the Monitor.
    """
    results = []
    py_files = sorted(scripts_dir.glob("*.py"))

    if not py_files:
        log.warning("No .py files found in %s", scripts_dir)
        return results

    for script_path in py_files:
        module_name = script_path.stem
        try:
            spec = importlib.util.spec_from_file_location(module_name, script_path)
            if spec is None or spec.loader is None:
                log.warning("Cannot create module spec for %s — skipping.", script_path.name)
                continue

            module = importlib.util.module_from_spec(spec)

            # ── Inject adsk so scripts don't need import statements ───────────
            if _ADSK_AVAILABLE:
                module.__dict__["adsk"] = adsk
            # Also expose math (commonly used in validation scripts)
            import math
            module.__dict__["math"] = math

            spec.loader.exec_module(module)

            # Collect validate_* functions
            found = False
            for attr_name in dir(module):
                if attr_name.startswith("validate_") and callable(getattr(module, attr_name)):
                    func     = getattr(module, attr_name)
                    rule_id  = attr_name.replace("validate_", "", 1)
                    results.append((rule_id, func))
                    found = True

            if not found:
                log.warning("No validate_*() in %s — skipping.", script_path.name)

        except Exception:
            log.error("Import error: %s\n%s", script_path.name, traceback.format_exc())

    log.info("Loaded %d validation function(s) from %s", len(results), scripts_dir)
    return results


# ─────────────────────────────────────────────────────────────────────────────
# Rules index for severity lookup
# ─────────────────────────────────────────────────────────────────────────────

def load_rules_index(rules_path: Path) -> dict[str, dict]:
    if not rules_path.exists():
        log.warning("rules.json not found at %s", rules_path)
        return {}
    try:
        with open(rules_path, encoding="utf-8") as fh:
            rules = json.load(fh)
        return {r["rule_id"]: r for r in rules if "rule_id" in r}
    except Exception as exc:
        log.error("Cannot load rules.json: %s", exc)
        return {}


# ─────────────────────────────────────────────────────────────────────────────
# SDF integration (optional, Day 4)
# ─────────────────────────────────────────────────────────────────────────────

def _run_sdf_checks_if_enabled(
    design,
    violations: list[dict],
    config: dict,
    rules_index: dict[str, dict],
    script_errors_log: Path,
) -> None:
    """
    If sdf_enabled, export each solid body to STEP and run SDF wall thickness.
    Appends any new violations to the violations list in-place.
    """
    if not config.get("sdf_enabled", False):
        return

    try:
        # Local import — OCC only available if conda env is set up
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from wall_thickness_sdf import validate_wall_thickness_sdf, export_body_to_step
    except ImportError:
        log.warning("SDF: wall_thickness_sdf could not be imported — skipping.")
        return

    # Find the min_thickness rule
    min_thickness_mm = 2.0
    for rule in rules_index.values():
        if rule.get("rule") == "min_wall_thickness":
            min_thickness_mm = float(rule.get("value", 2.0))
            break

    step_export_dir = Path(config.get("step_export_dir", "data/step_exports"))
    timestamp = datetime.now(tz=timezone.utc).isoformat()

    try:
        bodies = design.rootComponent.bRepBodies
        for bi in range(bodies.count):
            body = bodies.item(bi)
            if not body.isSolid:
                continue

            try:
                step_path = export_body_to_step(body, step_export_dir)
                if step_path is None:
                    continue

                result = validate_wall_thickness_sdf(
                    step_filepath=step_path,
                    min_thickness_mm=min_thickness_mm,
                    grid_n=int(config.get("sdf_grid_n", 20)),
                )

                if not result["passed"]:
                    violations.append({
                        "rule_id":          "R001_SDF",
                        "body_name":        body.name,
                        "passed":           False,
                        "violation_detail": result["violation_detail"],
                        "actual_value":     result["min_thickness_mm"],
                        "required_value":   result["required_mm"],
                        "unit":             "mm",
                        "severity":         "critical",
                        "timestamp":        timestamp,
                    })

            except Exception:
                log.error("SDF error on body %s:\n%s", body.name, traceback.format_exc())

    except Exception as exc:
        log.error("SDF outer loop error: %s", exc)


# ─────────────────────────────────────────────────────────────────────────────
# Monitor Agent core
# ─────────────────────────────────────────────────────────────────────────────

class MonitorAgent:
    """
    Stateful monitor — instantiated once in ADIE.py, reused across events.
    """

    def __init__(
        self,
        scripts_dir: Path,
        violations_path: Path,
        script_errors_log: Path,
        rules_path: Path,
        config: dict | None = None,
    ):
        self.scripts_dir        = scripts_dir
        self.violations_path    = violations_path
        self.script_errors_log  = script_errors_log
        self.rules_path         = rules_path
        self.config             = config or {}

        self._last_run: float           = 0.0
        self._validation_fns: list      = []
        self._rules_index: dict         = {}
        self._loaded: bool              = False

        # Wired by ADIE.py → calls MitigationAgent.process_violations
        self.on_violations_ready = None

    def load(self) -> None:
        """Load scripts and rules. Call once at startup."""
        self._validation_fns = load_validation_scripts(self.scripts_dir)
        self._rules_index    = load_rules_index(self.rules_path)
        self._loaded         = True
        log.info(
            "Monitor loaded: %d functions | %d rules in index",
            len(self._validation_fns),
            len(self._rules_index),
        )

    def trigger(self, design=None) -> list[dict]:
        """
        Called by event handlers.  Respects 5-s debounce.
        Returns list of violation dicts (may be empty).
        """
        now = time.monotonic()
        debounce = self.config.get("monitor_debounce_seconds", DEBOUNCE_SECONDS)
        if (now - self._last_run) < debounce:
            log.debug("Monitor debounced — skipping.")
            return []

        self._last_run = now

        if not self._loaded:
            self.load()

        if design is None:
            design = self._get_active_design()
            if design is None:
                log.warning("No active Fusion design — cannot validate.")
                return []

        design_name = ""
        try:
            design_name = design.rootComponent.name
        except Exception:
            pass
        log.info("Monitor run: design='%s'", design_name)

        violations = self._run_all_scripts(design)

        # Optional SDF check
        _run_sdf_checks_if_enabled(
            design, violations, self.config, self._rules_index, self.script_errors_log
        )

        self._write_violations(violations)

        # Generate HTML report
        try:
            html_path = self.config.get("html_report")
            if html_path:
                _generate_html_report(violations, self._rules_index, Path(html_path), design_name)
        except Exception:
            log.debug("HTML report error:\n%s", traceback.format_exc())

        critical_count = sum(1 for v in violations if v.get("severity") in ("critical", "warning"))
        if violations:
            log.info(
                "Monitor: %d violation(s) found (%d critical/warning).",
                len(violations), critical_count,
            )
            if callable(self.on_violations_ready):
                try:
                    self.on_violations_ready(violations)
                except Exception:
                    log.error("on_violations_ready callback failed:\n%s", traceback.format_exc())
        else:
            log.info("Monitor: design is compliant ✅")

        return violations

    # ── internals ─────────────────────────────────────────────────────────────

    def _get_active_design(self):
        if not _ADSK_AVAILABLE:
            return None
        try:
            app = adsk.core.Application.get()
            if app is None:
                return None
            product = app.activeProduct
            if product is None or not isinstance(product, adsk.fusion.Design):
                return None
            return product
        except Exception:
            return None

    def _run_all_scripts(self, design) -> list[dict]:
        violations = []
        timestamp  = datetime.now(tz=timezone.utc).isoformat()

        for rule_id, validate_fn in self._validation_fns:
            try:
                result = validate_fn(design)

                if not isinstance(result, dict):
                    raise TypeError(f"Expected dict, got {type(result).__name__}")

                passed   = bool(result.get("passed", True))
                severity = self._rules_index.get(rule_id, {}).get("severity", "info")
                body_name = result.get("body_name", "design")

                if not passed:
                    violations.append({
                        "rule_id":          rule_id,
                        "body_name":        str(body_name),
                        "passed":           False,
                        "violation_detail": str(result.get("violation_detail", "")),
                        "actual_value":     float(result.get("actual_value", 0.0)),
                        "required_value":   float(result.get("required_value", 0.0)),
                        "unit":             str(result.get("unit", "")),
                        "severity":         severity,
                        "timestamp":        timestamp,
                    })

            except Exception:
                err = traceback.format_exc()
                log.error("Script error in validate_%s:\n%s", rule_id, err)
                self._log_script_error(rule_id, err)
                # NEVER halt — continue to next script

        return violations

    def _write_violations(self, violations: list[dict]) -> None:
        self.violations_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.violations_path, "w", encoding="utf-8") as fh:
            json.dump(violations, fh, indent=2, ensure_ascii=False)
        log.info("violations.json written (%d entries).", len(violations))

    def _log_script_error(self, rule_id: str, error: str) -> None:
        self.script_errors_log.parent.mkdir(parents=True, exist_ok=True)
        ts    = datetime.now(tz=timezone.utc).isoformat()
        entry = f"[{ts}]  {rule_id}\n{error}\n{'─' * 60}\n"
        with open(self.script_errors_log, "a", encoding="utf-8") as fh:
            fh.write(entry)


# ─────────────────────────────────────────────────────────────────────────────
# HTML report helper
# ─────────────────────────────────────────────────────────────────────────────

def _generate_html_report(violations: list[dict], rules_index: dict, path: Path, design_name: str) -> None:
    """Write a minimal HTML violations report."""
    from report_generator import generate_html_report
    generate_html_report(violations, rules_index, path, design_name)


# ─────────────────────────────────────────────────────────────────────────────
# Fusion 360 event handlers — clean if/else pattern (no conditional metaclass)
# ─────────────────────────────────────────────────────────────────────────────

if _ADSK_AVAILABLE:

    class DocumentSavedHandler(adsk.core.DocumentEventHandler):
        def __init__(self, monitor: MonitorAgent):
            super().__init__()
            self._monitor = monitor

        def notify(self, args):
            try:
                log.info("Event: documentSaved — triggering Monitor.")
                self._monitor.trigger()
            except Exception:
                log.error("DocumentSavedHandler.notify:\n%s", traceback.format_exc())

    class DocumentActivatedHandler(adsk.core.DocumentEventHandler):
        def __init__(self, monitor: MonitorAgent):
            super().__init__()
            self._monitor = monitor

        def notify(self, args):
            try:
                log.info("Event: documentActivated — triggering Monitor.")
                self._monitor.trigger()
            except Exception:
                log.error("DocumentActivatedHandler.notify:\n%s", traceback.format_exc())

else:
    # Stub classes for syntax checking / testing outside Fusion

    class DocumentSavedHandler:
        def __init__(self, monitor: MonitorAgent):
            self._monitor = monitor

        def notify(self, args):
            self._monitor.trigger()

    class DocumentActivatedHandler:
        def __init__(self, monitor: MonitorAgent):
            self._monitor = monitor

        def notify(self, args):
            self._monitor.trigger()
