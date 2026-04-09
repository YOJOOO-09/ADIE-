"""
ADIE — Autonomous Design Integrity Engine
Agent 2: synthesizer_agent.py  (runs ONCE at setup, outside Fusion 360)

PURPOSE:
    Reads rules.json produced by the Analyst Agent.
    For each rule, sends a structured prompt to Gemini 1.5 Flash requesting
    a single validate_{rule_id}(design) Python function.
    Validates each response with ast.parse().
    Retries once on SyntaxError.
    Writes one .py file per rule to /validation_scripts/.

USAGE:
    conda activate adie
    python synthesizer_agent.py --rules data/rules.json --output validation_scripts/

    Optional flags:
      --api-key   YOUR_GEMINI_API_KEY  (or set GEMINI_API_KEY env var)
      --sleep     2.0                  (seconds between Gemini calls)
      --model     gemini-1.5-flash
      --verbose

OUTPUT:
    validation_scripts/{rule_id}_{rule_name}.py  — one file per rule
    data/uncompiled_rules.log                    — AST failures after retry

GENERATED FUNCTION CONTRACT:
    def validate_{rule_id}(design) -> dict:
        # design: adsk.fusion.Design (injected by Fusion runtime)
        return {
            "passed":           bool,
            "violation_detail": str,
            "actual_value":     float,
            "required_value":   float,
            "unit":             str,
        }

AUTHOR: Aryn Gahlot | ADIE Project | Day 2
"""

# ─────────────────────────────────────────────────────────────────────────────
# Standard library
# ─────────────────────────────────────────────────────────────────────────────
import argparse
import ast
import json
import logging
import os
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

# ─────────────────────────────────────────────────────────────────────────────
# Third-party
# ─────────────────────────────────────────────────────────────────────────────
try:
    import google.generativeai as genai
except ImportError:
    sys.exit(
        "ERROR: google-generativeai not found. Run:  pip install google-generativeai"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("ADIE.Synthesizer")


# ─────────────────────────────────────────────────────────────────────────────
# Prompt templates
# ─────────────────────────────────────────────────────────────────────────────
SYNTHESIZER_SYSTEM_PROMPT = """\
You are a Fusion 360 Python API expert who writes validation functions \
for CAD design rules.
Return ONLY the requested Python function definition — no import statements, \
no markdown fences, no explanation, no preamble.
The function body must be syntactically valid Python 3.10.\
"""

SYNTHESIZER_USER_PROMPT_TEMPLATE = """\
Write a single Python function called validate_{rule_id}(design) that \
takes a Fusion 360 adsk.fusion.Design object as its only argument and \
returns a dict with exactly these keys:
  {{
    "passed":           bool,      # True = rule is satisfied
    "violation_detail": str,       # human-readable description of the violation
    "actual_value":     float,     # measured value from the design
    "required_value":   float,     # threshold from the rule
    "unit":             str        # unit string
  }}

The function must check the following engineering rule:
  Rule name : {rule}
  Value     : {value} {unit}
  Condition : {condition}
  Severity  : {severity}
  Source    : ISO/DIN standard, page {source_page}

Allowed adsk.fusion API (all already in scope — do NOT add import statements):
  - design.rootComponent
  - design.rootComponent.bRepBodies  (BRepBodyList)
  - body.physicalProperties          (PhysicalProperties, call .volume for cm³)
  - body.physicalProperties.mass     (kg)
  - design.rootComponent.allBRepBodies
  - body.edges                       (BRepEdgeList)
  - edge.length                      (cm — convert to mm if rule unit is mm)
  - body.faces                       (BRepFaceList)
  - face.area                        (cm²)
  - body.isSolid                     (bool)
  - design.unitsManager              (for unit conversion)
  - body.material                    (Material object, .name for material name)

Unit convention: Fusion stores ALL geometry in cm. \
If rule value is in mm, multiply Fusion measurement by 10.

Iteration pattern:
  for i in range(design.rootComponent.bRepBodies.count):
      body = design.rootComponent.bRepBodies.item(i)
      ...

Return exactly the function. No imports. No class wrapper. \
First line must be: def validate_{rule_id}(design):\
"""

RETRY_AST_SUFFIX_TEMPLATE = """\


The previous response had a Python syntax error: {error}
Fix it and return ONLY the corrected function definition. \
First line must be: def validate_{rule_id}(design):
No markdown, no explanation.\
"""


# ─────────────────────────────────────────────────────────────────────────────
# File header template (prepended to every generated script)
# ─────────────────────────────────────────────────────────────────────────────
SCRIPT_HEADER_TEMPLATE = '''\
"""
ADIE — Auto-generated Validation Script
Rule ID  : {rule_id}
Rule     : {rule}
Value    : {value} {unit}
Condition: {condition}
Severity : {severity}
Source   : page {source_page}
Generated: {timestamp}

CONTRACT:
    validate_{rule_id}(design) -> dict
        design : adsk.fusion.Design   (injected by Fusion runtime)
        returns:
            passed           : bool
            violation_detail : str
            actual_value     : float
            required_value   : float
            unit             : str

DO NOT EDIT — regenerate via synthesizer_agent.py if rule changes.
"""

'''


# ─────────────────────────────────────────────────────────────────────────────
# Gemini client (identical to analyst — keep standalone for import safety)
# ─────────────────────────────────────────────────────────────────────────────

class GeminiClient:
    def __init__(self, api_key: str, model_name: str = "gemini-1.5-flash"):
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel(
            model_name=model_name,
            system_instruction=SYNTHESIZER_SYSTEM_PROMPT,
        )
        self.model_name = model_name
        log.info("Gemini client initialised: %s", model_name)

    def call(self, prompt: str, verbose: bool = False) -> str:
        if verbose:
            log.debug("─── Prompt (first 400 chars) ───\n%s\n───", prompt[:400])
        response = self.model.generate_content(
            prompt,
            generation_config=genai.types.GenerationConfig(
                temperature=0.15,       # low temp, allow slight variation for retry
                max_output_tokens=2048,
            ),
        )
        try:
            text = response.text
        except ValueError as exc:
            raise RuntimeError(f"Gemini response blocked or empty: {exc}") from exc
        if verbose:
            log.debug("─── Response (first 400 chars) ───\n%s\n───", text[:400])
        return text


# ─────────────────────────────────────────────────────────────────────────────
# AST validation
# ─────────────────────────────────────────────────────────────────────────────

def clean_code(raw: str) -> str:
    """Strip markdown fences if Gemini includes them despite instructions."""
    import re
    s = raw.strip()
    s = re.sub(r"^```(?:python)?\s*", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s*```$", "", s)
    return s.strip()


def ast_validate(code: str) -> tuple[bool, str | None]:
    """
    Return (True, None) if code parses cleanly, else (False, error_message).
    Also checks that the code contains at least one FunctionDef node.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return False, str(exc)

    func_defs = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
    if not func_defs:
        return False, "No function definition found in generated code."

    return True, None


# ─────────────────────────────────────────────────────────────────────────────
# Synthesizer Agent core
# ─────────────────────────────────────────────────────────────────────────────

class SynthesizerAgent:
    def __init__(
        self,
        gemini: GeminiClient,
        output_dir: Path,
        uncompiled_log: Path,
        sleep_seconds: float = 2.0,
        verbose: bool = False,
    ):
        self.gemini = gemini
        self.output_dir = output_dir
        self.uncompiled_log = uncompiled_log
        self.sleep_seconds = sleep_seconds
        self.verbose = verbose

        self._stats = {
            "rules_total": 0,
            "scripts_ok_first": 0,
            "scripts_ok_retry": 0,
            "scripts_failed": 0,
        }

    def run(self, rules_path: Path) -> None:
        log.info("═══ ADIE Synthesizer Agent starting ═══")
        log.info("Rules : %s", rules_path)
        log.info("Output: %s", self.output_dir)

        # Load rules
        with open(rules_path, encoding="utf-8") as fh:
            rules = json.load(fh)

        if not isinstance(rules, list) or not rules:
            log.error("rules.json is empty or not a list. Run analyst_agent first.")
            sys.exit(1)

        self._stats["rules_total"] = len(rules)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        for idx, rule in enumerate(rules, start=1):
            log.info(
                "Synthesising %d/%d  rule_id=%s  rule=%s",
                idx,
                len(rules),
                rule.get("rule_id", "?"),
                rule.get("rule", "?"),
            )
            self._synthesise_rule(rule)

            if idx < len(rules):
                time.sleep(self.sleep_seconds)

        self._print_summary()

    # ── internals ────────────────────────────────────────────────────────────

    def _synthesise_rule(self, rule: dict) -> None:
        rule_id = rule.get("rule_id", "R000")
        rule_name = rule.get("rule", "unnamed")

        prompt = SYNTHESIZER_USER_PROMPT_TEMPLATE.format(
            rule_id=rule_id,
            rule=rule_name,
            value=rule.get("value", 0),
            unit=rule.get("unit", ""),
            condition=rule.get("condition", "none"),
            severity=rule.get("severity", "info"),
            source_page=rule.get("source_page", 0),
        )

        # ── First attempt ─────────────────────────────────────────────────────
        try:
            raw = self.gemini.call(prompt, verbose=self.verbose)
        except Exception as exc:
            log.error("Gemini API error for %s: %s", rule_id, exc)
            self._log_uncompiled(rule_id, f"API error: {exc}")
            self._stats["scripts_failed"] += 1
            return

        code = clean_code(raw)
        ok, err = ast_validate(code)

        if ok:
            self._write_script(rule, code)
            self._stats["scripts_ok_first"] += 1
            return

        # ── Retry once ────────────────────────────────────────────────────────
        log.warning("AST validation failed for %s: %s — retrying.", rule_id, err)
        time.sleep(self.sleep_seconds)

        retry_prompt = prompt + RETRY_AST_SUFFIX_TEMPLATE.format(
            error=err, rule_id=rule_id
        )
        try:
            raw2 = self.gemini.call(retry_prompt, verbose=self.verbose)
        except Exception as exc:
            log.error("Gemini API error on retry for %s: %s", rule_id, exc)
            self._log_uncompiled(rule_id, f"API error on retry: {exc}")
            self._stats["scripts_failed"] += 1
            return

        code2 = clean_code(raw2)
        ok2, err2 = ast_validate(code2)

        if ok2:
            self._write_script(rule, code2)
            self._stats["scripts_ok_retry"] += 1
            return

        # ── Double failure ────────────────────────────────────────────────────
        log.error("Script for %s failed AST twice. Logged to %s", rule_id, self.uncompiled_log)
        self._log_uncompiled(rule_id, f"First: {err} | Retry: {err2}")
        self._stats["scripts_failed"] += 1

    def _write_script(self, rule: dict, func_code: str) -> None:
        rule_id = rule["rule_id"]
        rule_name = rule.get("rule", "unnamed")
        filename = f"{rule_id}_{rule_name}.py"
        filepath = self.output_dir / filename

        header = SCRIPT_HEADER_TEMPLATE.format(
            rule_id=rule_id,
            rule=rule_name,
            value=rule.get("value", 0),
            unit=rule.get("unit", ""),
            condition=rule.get("condition", ""),
            severity=rule.get("severity", "info"),
            source_page=rule.get("source_page", 0),
            timestamp=datetime.now(tz=timezone.utc).isoformat(),
        )

        full_source = header + func_code + "\n"

        with open(filepath, "w", encoding="utf-8") as fh:
            fh.write(full_source)

        log.info("  ✅  Written: %s", filepath)

    def _log_uncompiled(self, rule_id: str, reason: str) -> None:
        self.uncompiled_log.parent.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(tz=timezone.utc).isoformat()
        entry = f"[{timestamp}]  {rule_id}  {reason}\n"
        with open(self.uncompiled_log, "a", encoding="utf-8") as fh:
            fh.write(entry)

    def _print_summary(self) -> None:
        s = self._stats
        log.info("═══ Synthesizer Agent complete ═══")
        log.info("  Rules total           : %d", s["rules_total"])
        log.info("  Scripts ok (1st try)  : %d", s["scripts_ok_first"])
        log.info("  Scripts ok (retry)    : %d", s["scripts_ok_retry"])
        log.info("  Scripts failed        : %d", s["scripts_failed"])
        if s["scripts_failed"] > 0:
            log.warning("  Check %s for failed rules.", self.uncompiled_log)


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="synthesizer_agent",
        description="ADIE Agent 2 — Generate validation scripts from rules.json",
    )
    parser.add_argument(
        "--rules",
        default="data/rules.json",
        metavar="PATH",
        help="Path to rules.json (default: data/rules.json)",
    )
    parser.add_argument(
        "--output",
        default="validation_scripts",
        metavar="DIR",
        help="Output directory for generated scripts (default: validation_scripts/)",
    )
    parser.add_argument(
        "--uncompiled-log",
        default="data/uncompiled_rules.log",
        metavar="PATH",
        help="Log file for rules that fail AST validation",
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("GEMINI_API_KEY", ""),
        metavar="KEY",
        help="Gemini API key (default: reads GEMINI_API_KEY env var)",
    )
    parser.add_argument(
        "--model",
        default="gemini-1.5-flash",
        metavar="MODEL",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=2.0,
        metavar="SECS",
    )
    parser.add_argument("--verbose", action="store_true")
    return parser


def main() -> None:
    parser = _build_arg_parser()
    args = parser.parse_args()

    if not args.api_key:
        log.error(
            "No Gemini API key. Set GEMINI_API_KEY env var or pass --api-key."
        )
        sys.exit(1)

    rules_path = Path(args.rules)
    if not rules_path.exists():
        log.error("rules.json not found at %s. Run analyst_agent.py first.", rules_path)
        sys.exit(1)

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    try:
        gemini = GeminiClient(api_key=args.api_key, model_name=args.model)
        agent = SynthesizerAgent(
            gemini=gemini,
            output_dir=Path(args.output),
            uncompiled_log=Path(args.uncompiled_log),
            sleep_seconds=args.sleep,
            verbose=args.verbose,
        )
        agent.run(rules_path=rules_path)
        print(f"\n✅  Validation scripts written to: {Path(args.output).resolve()}")
    except KeyboardInterrupt:
        log.warning("Interrupted.")
        sys.exit(130)
    except Exception:
        log.error("Fatal error:\n%s", traceback.format_exc())
        sys.exit(1)


if __name__ == "__main__":
    main()
