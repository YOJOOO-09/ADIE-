"""
ADIE — Autonomous Design Integrity Engine
config.py — Single source of truth for all paths, settings, and constants.

All agents import from this module. Edit here to change global behaviour.

USAGE:
    from config import CONFIG, ADIE_ROOT
    rules_path = CONFIG["rules_json"]

AUTHOR: Aryn Gahlot | ADIE Project
"""

import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


# ─────────────────────────────────────────────────────────────────────────────
# Root detection — works whether imported from setup/, fusion_addin/, or adie/
# ─────────────────────────────────────────────────────────────────────────────
# config.py lives at: adie/config.py
# All paths are relative to this file's directory.
ADIE_ROOT: Path = Path(__file__).resolve().parent


# ─────────────────────────────────────────────────────────────────────────────
# Configuration dictionary
# ─────────────────────────────────────────────────────────────────────────────
CONFIG: dict = {

    # ── Gemini API ───────────────────────────────────────────────────────────
    # Prefer env var; fall back to placeholder (will error loudly at runtime).
    "gemini_api_key":   os.environ.get("GEMINI_API_KEY", ""),
    "gemini_model":     os.environ.get("ADIE_MODEL", "gemini-2.0-flash"),

    # ── Paths ────────────────────────────────────────────────────────────────
    "validation_scripts_dir":   ADIE_ROOT / "validation_scripts",
    "standards_dir":            ADIE_ROOT / "standards",
    "step_export_dir":          ADIE_ROOT / "data" / "step_exports",

    # Data files
    "rules_json":               ADIE_ROOT / "data" / "rules.json",
    "violations_json":          ADIE_ROOT / "data" / "violations.json",
    "audit_log_json":           ADIE_ROOT / "data" / "audit_log.json",
    "pending_suggestion":       ADIE_ROOT / "data" / "pending_suggestion.json",

    # Log files
    "failed_chunks_log":        ADIE_ROOT / "data" / "failed_chunks.log",
    "uncompiled_rules_log":     ADIE_ROOT / "data" / "uncompiled_rules.log",
    "script_errors_log":        ADIE_ROOT / "data" / "script_errors.log",
    "adie_log":                 ADIE_ROOT / "data" / "adie.log",

    # HTML report
    "html_report":              ADIE_ROOT / "data" / "violations_report.html",

    # ── Analyst Agent ────────────────────────────────────────────────────────
    "analyst_chunk_tokens":     2000,
    "analyst_sleep_seconds":    2.0,

    # ── Synthesizer Agent ────────────────────────────────────────────────────
    "synthesizer_sleep_seconds": 2.0,

    # ── Monitor Agent ────────────────────────────────────────────────────────
    "monitor_debounce_seconds": 5.0,

    # ── SDF Wall Thickness ───────────────────────────────────────────────────
    # Set True after: conda install -c conda-forge pythonocc-core
    "sdf_enabled":  False,
    "sdf_grid_n":   20,         # 20^3 = 8000 sample points

    # ── Mitigation Agent ─────────────────────────────────────────────────────
    "mitigation_max_suggestions_per_run": 5,   # cap Gemini calls per Monitor run
}


# ─────────────────────────────────────────────────────────────────────────────
# Convenience helpers
# ─────────────────────────────────────────────────────────────────────────────

def ensure_data_dirs() -> None:
    """Create all required data directories if they don't exist."""
    dirs = [
        ADIE_ROOT / "data",
        ADIE_ROOT / "data" / "step_exports",
        ADIE_ROOT / "validation_scripts",
        ADIE_ROOT / "standards",
    ]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)


def get_api_key() -> str:
    """Return the Gemini API key or raise if not set."""
    key = CONFIG["gemini_api_key"]
    if not key:
        raise EnvironmentError(
            "GEMINI_API_KEY not set.\n"
            "  Option 1: set environment variable:  set GEMINI_API_KEY=your_key\n"
            "  Option 2: edit adie/config.py → CONFIG['gemini_api_key'] = 'your_key'\n"
            "  Get a free key at: https://aistudio.google.com/apikey"
        )
    return key


def summary() -> str:
    """Return a human-readable config summary for logging."""
    lines = [
        "═" * 54,
        "  ADIE Configuration",
        "═" * 54,
        f"  Root          : {ADIE_ROOT}",
        f"  Model         : {CONFIG['gemini_model']}",
        f"  API Key       : {'SET ✓' if CONFIG['gemini_api_key'] else 'NOT SET ✗'}",
        f"  SDF enabled   : {CONFIG['sdf_enabled']}",
        f"  Debounce      : {CONFIG['monitor_debounce_seconds']}s",
        f"  Scripts dir   : {CONFIG['validation_scripts_dir']}",
        f"  Rules JSON    : {CONFIG['rules_json']}",
        f"  Violations    : {CONFIG['violations_json']}",
        f"  Audit log     : {CONFIG['audit_log_json']}",
        "═" * 54,
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    ensure_data_dirs()
    print(summary())
