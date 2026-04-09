"""
ADIE — Autonomous Design Integrity Engine
Agent 4: mitigation_agent.py  (runs inside Fusion 360)

PURPOSE:
    Receives violations from the Monitor Agent.
    For each critical/warning violation: calls Gemini 1.5 Flash for a
    2-sentence actionable fix suggestion.
    MANDATORY HITL gate: uses Fusion's inputBox so the engineer must
    TYPE "yes" (case-insensitive) to see the AI suggestion.
    All decisions are appended to audit_log.json (append-only, never overwrite).

AUTHOR: Aryn Gahlot | ADIE Project | Day 3 (production)
"""

# ─────────────────────────────────────────────────────────────────────────────
# Standard library
# ─────────────────────────────────────────────────────────────────────────────
import json
import logging
import traceback
from datetime import datetime, timezone
from pathlib import Path

# ─────────────────────────────────────────────────────────────────────────────
# Third-party
# ─────────────────────────────────────────────────────────────────────────────
try:
    import google.generativeai as genai
    _GENAI_AVAILABLE = True
except ImportError:
    _GENAI_AVAILABLE = False

# ─────────────────────────────────────────────────────────────────────────────
# adsk guard
# ─────────────────────────────────────────────────────────────────────────────
try:
    import adsk.core
    import adsk.fusion
    _ADSK_AVAILABLE = True
except ImportError:
    _ADSK_AVAILABLE = False

log = logging.getLogger("ADIE.Mitigation")

ACTIONABLE_SEVERITIES = {"critical", "warning"}
PALETTE_ID            = "TextCommands"

MITIGATION_SYSTEM_PROMPT = """\
You are an expert mechanical engineer reviewing Fusion 360 CAD design violations.
Provide ONE specific, actionable fix in plain English. Maximum 2 sentences.
No preamble, no bullet points, no markdown.\
"""

MITIGATION_PROMPT_TEMPLATE = """\
A Fusion 360 CAD model has a design violation.

Rule      : {rule_id}
Body      : {body_name}
Actual    : {actual_value} {unit}
Required  : {required_value} {unit}
Detail    : {violation_detail}
Severity  : {severity}

ONE specific actionable fix, maximum 2 sentences, no preamble:\
"""


# ─────────────────────────────────────────────────────────────────────────────
# Gemini client
# ─────────────────────────────────────────────────────────────────────────────

class _GeminiMitigationClient:
    def __init__(self, api_key: str, model_name: str = "gemini-1.5-flash"):
        genai.configure(api_key=api_key)
        self._model = genai.GenerativeModel(
            model_name=model_name,
            system_instruction=MITIGATION_SYSTEM_PROMPT,
        )

    def get_fix(self, violation: dict) -> str:
        prompt = MITIGATION_PROMPT_TEMPLATE.format(**{
            "rule_id":          violation.get("rule_id", ""),
            "body_name":        violation.get("body_name", ""),
            "actual_value":     violation.get("actual_value", ""),
            "unit":             violation.get("unit", ""),
            "required_value":   violation.get("required_value", ""),
            "violation_detail": violation.get("violation_detail", ""),
            "severity":         violation.get("severity", "warning"),
        })
        response = self._model.generate_content(
            prompt,
            generation_config=genai.types.GenerationConfig(
                temperature=0.3,
                max_output_tokens=256,
            ),
        )
        try:
            return response.text.strip()
        except ValueError as exc:
            raise RuntimeError(f"Gemini blocked: {exc}") from exc


# ─────────────────────────────────────────────────────────────────────────────
# Fusion UI helpers
# ─────────────────────────────────────────────────────────────────────────────

def _get_ui():
    """Return adsk ui or None."""
    if not _ADSK_AVAILABLE:
        return None
    try:
        app = adsk.core.Application.get()
        return app.userInterface if app else None
    except Exception:
        return None


def _palette_write(text: str) -> None:
    """Write to Fusion TextCommandPalette (console)."""
    ui = _get_ui()
    if ui:
        try:
            p = ui.palettes.itemById(PALETTE_ID)
            if p:
                p.isVisible = True
                p.writeText(text)
        except Exception:
            pass
    log.info("[CONSOLE] %s", text)


def _get_fusion_username() -> str:
    if not _ADSK_AVAILABLE:
        return "unknown"
    try:
        app = adsk.core.Application.get()
        return app.currentUser.name if app and app.currentUser else "unknown"
    except Exception:
        return "unknown"


def _hitl_prompt(violation: dict) -> bool:
    """
    MANDATORY HITL gate.
    Uses inputBox so engineer must physically type 'yes'.
    Returns True if approved, False if dismissed or errored.
    """
    rule_id   = violation.get("rule_id", "?")
    body_name = violation.get("body_name", "?")
    severity  = violation.get("severity", "warning").upper()
    detail    = violation.get("violation_detail", "")

    if not _ADSK_AVAILABLE:
        log.info("HITL: adsk unavailable — auto-dismissing for safety.")
        return False

    ui = _get_ui()
    if ui is None:
        return False

    try:
        prompt_msg = (
            f"ADIE [{severity}] — {rule_id} in '{body_name}'\n\n"
            f"{detail}\n\n"
            f"Type 'yes' to view AI fix suggestion, or leave blank to dismiss:"
        )

        # inputBox returns (value, cancelled)
        result = ui.inputBox(
            prompt_msg,
            "ADIE — Design Violation",
            "",                           # default text
        )

        # inputBox returns a tuple: (inputValue, cancelled)
        if isinstance(result, (list, tuple)) and len(result) >= 2:
            value, cancelled = result[0], result[1]
            if cancelled:
                return False
            return str(value).strip().lower() == "yes"
        else:
            # Some Fusion versions return just the string
            return str(result).strip().lower() == "yes"

    except Exception:
        log.error("HITL input box error:\n%s", traceback.format_exc())
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Audit log
# ─────────────────────────────────────────────────────────────────────────────

def append_audit(audit_path: Path, entry: dict) -> None:
    """Append one record to audit_log.json. NEVER overwrites existing entries."""
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    existing: list = []

    if audit_path.exists():
        try:
            with open(audit_path, encoding="utf-8") as fh:
                existing = json.load(fh)
            if not isinstance(existing, list):
                existing = []
        except Exception:
            backup = audit_path.with_suffix(".json.bak")
            try:
                audit_path.rename(backup)
            except Exception:
                pass
            log.warning("audit_log.json corrupted — backed up to %s", backup)
            existing = []

    existing.append(entry)

    # Write atomically via temp file
    tmp = audit_path.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(existing, fh, indent=2, ensure_ascii=False)
    tmp.replace(audit_path)


# ─────────────────────────────────────────────────────────────────────────────
# Mitigation Agent core
# ─────────────────────────────────────────────────────────────────────────────

class MitigationAgent:
    """
    Processes violations from Monitor. HITL gate required before showing AI fix.
    """

    def __init__(
        self,
        api_key: str,
        audit_log_path: Path,
        pending_path: Path,
        model_name: str = "gemini-1.5-flash",
        max_suggestions_per_run: int = 5,
    ):
        self.audit_log_path         = audit_log_path
        self.pending_path           = pending_path
        self.max_suggestions_per_run = max_suggestions_per_run

        self._gemini: _GeminiMitigationClient | None = None
        if api_key and _GENAI_AVAILABLE:
            try:
                self._gemini = _GeminiMitigationClient(api_key=api_key, model_name=model_name)
                log.info("Mitigation Gemini client ready: %s", model_name)
            except Exception as exc:
                log.error("Gemini client init failed: %s", exc)
        else:
            log.warning("Gemini unavailable — AI fix suggestions disabled.")

    def process_violations(self, violations: list[dict]) -> None:
        """Entry point from Monitor's on_violations_ready callback."""
        actionable = [
            v for v in violations
            if v.get("severity", "") in ACTIONABLE_SEVERITIES
        ]

        if not actionable:
            log.info("Mitigation: no actionable violations.")
            return

        log.info("Mitigation processing %d violation(s).", len(actionable))

        processed = 0
        for violation in actionable:
            if processed >= self.max_suggestions_per_run:
                log.info("Mitigation: max suggestions/run reached (%d). Stopping.", self.max_suggestions_per_run)
                break
            self._handle_one(violation)
            processed += 1

    # ── internals ─────────────────────────────────────────────────────────────

    def _handle_one(self, violation: dict) -> None:
        rule_id   = violation.get("rule_id", "?")
        body_name = violation.get("body_name", "?")
        severity  = violation.get("severity", "warning").upper()

        log.info("Handling: %s in %s [%s]", rule_id, body_name, severity)

        # ── Step 1: Fetch AI suggestion (before HITL to minimize latency) ─────
        ai_suggestion = self._fetch_suggestion(violation)

        # ── Step 2: Stage in pending_suggestion.json ──────────────────────────
        self._write_pending(violation, ai_suggestion or "[unavailable]")

        # ── Step 3: Announce in console ───────────────────────────────────────
        _palette_write("─" * 64)
        _palette_write(
            f"  ADIE [{severity}]  {rule_id} → '{body_name}'"
        )
        _palette_write(
            f"  {violation.get('violation_detail','')}"
        )

        # ── Step 4: MANDATORY HITL gate ───────────────────────────────────────
        if ai_suggestion is None:
            _palette_write("  ⚠  AI suggestion unavailable (Gemini not configured).")
            self._record_audit(violation, suggestion="[unavailable]", action="dismissed")
            return

        approved = _hitl_prompt(violation)

        # ── Step 5: Act on decision ───────────────────────────────────────────
        if approved:
            _palette_write(f"\n  ✅  AI Fix Suggestion ({rule_id}):")
            _palette_write(f"  {ai_suggestion}")
            _palette_write("─" * 64)
            self._record_audit(violation, suggestion=ai_suggestion, action="approved")
        else:
            _palette_write(f"  ➡  Dismissed: {rule_id}.")
            _palette_write("─" * 64)
            self._record_audit(violation, suggestion=ai_suggestion, action="dismissed")

    def _fetch_suggestion(self, violation: dict) -> str | None:
        if self._gemini is None:
            return None
        try:
            return self._gemini.get_fix(violation)
        except Exception:
            log.error(
                "Gemini call failed for %s:\n%s",
                violation.get("rule_id"), traceback.format_exc(),
            )
            return None

    def _write_pending(self, violation: dict, suggestion: str) -> None:
        self.pending_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "rule_id":          violation.get("rule_id"),
            "body_name":        violation.get("body_name"),
            "violation_detail": violation.get("violation_detail"),
            "severity":         violation.get("severity"),
            "ai_suggestion":    suggestion,
            "staged_at":        datetime.now(tz=timezone.utc).isoformat(),
        }
        with open(self.pending_path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)

    def _record_audit(self, violation: dict, suggestion: str, action: str) -> None:
        entry = {
            "timestamp":        datetime.now(tz=timezone.utc).isoformat(),
            "rule_id":          violation.get("rule_id"),
            "body_name":        violation.get("body_name"),
            "violation_detail": violation.get("violation_detail"),
            "actual_value":     violation.get("actual_value"),
            "required_value":   violation.get("required_value"),
            "unit":             violation.get("unit"),
            "severity":         violation.get("severity"),
            "ai_suggestion":    suggestion,
            "engineer_action":  action,
            "engineer_id":      _get_fusion_username(),
        }
        try:
            append_audit(self.audit_log_path, entry)
        except Exception:
            log.error("Audit write failed:\n%s", traceback.format_exc())
