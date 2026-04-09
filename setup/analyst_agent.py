"""
ADIE — Autonomous Design Integrity Engine
Agent 1: analyst_agent.py  (runs ONCE at setup, outside Fusion 360)

PURPOSE:
    Reads an engineering standards PDF (e.g. ISO 2768, DIN tolerances),
    chunks the text into ~2000-token segments, sends each to Gemini 1.5 Flash
    with a strict JSON-only prompt, validates every response with json.loads(),
    retries once on parse failure, and writes a consolidated rules.json.

USAGE:
    conda activate adie
    python analyst_agent.py --pdf standards/ISO_2768.pdf --output data/rules.json

    Optional flags:
      --api-key   YOUR_GEMINI_API_KEY  (or set GEMINI_API_KEY env var)
      --chunk-tokens  2000             (tokens-per-chunk, default 2000)
      --sleep     2.0                  (seconds between Gemini calls, default 2)
      --model     gemini-1.5-flash     (Gemini model, default gemini-1.5-flash)
      --verbose                        (print chunk previews and raw responses)

OUTPUT FILES:
    data/rules.json           — array of validated rule objects
    data/failed_chunks.log    — chunks that failed json.loads() twice

RULE SCHEMA (each object in the JSON array):
    {
      "rule_id":     "R001",           // auto-assigned if Gemini omits it
      "rule":        "min_wall_thickness",
      "value":       2.0,
      "unit":        "mm",
      "condition":   "material == Aluminum",
      "source_page": 4,
      "severity":    "critical"        // "critical" | "warning" | "info"
    }

AUTHOR: Aryn Gahlot | ADIE Project | Day 2
"""

# ─────────────────────────────────────────────────────────────────────────────
# Standard library
# ─────────────────────────────────────────────────────────────────────────────
import argparse
import json
import logging
import os
import re
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ─────────────────────────────────────────────────────────────────────────────
# Third-party (must be installed in conda env)
# ─────────────────────────────────────────────────────────────────────────────
try:
    import fitz  # PyMuPDF
except ImportError:
    sys.exit(
        "ERROR: PyMuPDF not found. Run:  pip install pymupdf\n"
        "Make sure your conda env is active."
    )

try:
    import google.generativeai as genai
except ImportError:
    sys.exit(
        "ERROR: google-generativeai not found. Run:  pip install google-generativeai\n"
        "Make sure your conda env is active."
    )


# ─────────────────────────────────────────────────────────────────────────────
# Logging configuration
# ─────────────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("ADIE.Analyst")


# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────
# Approximate chars-per-token for English technical text (~4 chars/token)
CHARS_PER_TOKEN = 4

VALID_SEVERITIES = {"critical", "warning", "info"}

# Fields that MUST be present in every rule object
REQUIRED_RULE_FIELDS = {"rule", "value", "unit", "source_page", "severity"}

ANALYST_SYSTEM_PROMPT = """\
You are a mechanical engineering standards extraction engine.
You extract engineering rules from the provided text exactly as stated — \
no interpretation, no invention.
Return ONLY a valid JSON array. No markdown, no preamble, no explanation. \
If there are no extractable rules in the text, return an empty array: []\
"""

ANALYST_USER_PROMPT_TEMPLATE = """\
Extract all engineering rules from the following text that specify measurable \
constraints (tolerances, dimensions, limits, surface finish grades, \
material requirements, etc.).

Return ONLY a valid JSON array where every element has exactly these fields \
(no extras, no nesting):
{{
  "rule_id": "R###",
  "rule": "snake_case_rule_name",
  "value": <numeric value>,
  "unit": "unit_string",
  "condition": "condition_string_or_empty_string",
  "source_page": <integer page number>,
  "severity": "critical" | "warning" | "info"
}}

Severity guidelines:
- "critical"  → safety-critical or load-bearing constraints
- "warning"   → recommended tolerances or fit grades
- "info"      → notes, references, or material suggestions

TEXT (pages {page_start}–{page_end}):
---
{chunk_text}
---

Return ONLY the JSON array. Nothing else.\
"""

RETRY_PROMPT_SUFFIX_TEMPLATE = """\


The previous response was not valid JSON. Parse error: {error}
Try again. Return ONLY the raw JSON array, no markdown fences, \
no explanation, just the array starting with [ and ending with ].\
"""


# ─────────────────────────────────────────────────────────────────────────────
# PDF utilities
# ─────────────────────────────────────────────────────────────────────────────

def extract_pages(pdf_path: Path) -> list[dict]:
    """
    Extract text from every page of the PDF.

    Returns:
        [{"page": int (1-indexed), "text": str}, ...]
    """
    log.info("Opening PDF: %s", pdf_path)
    doc = fitz.open(str(pdf_path))
    pages = []
    for i, page in enumerate(doc, start=1):
        text = page.get_text("text")
        if text.strip():                    # skip blank / image-only pages
            pages.append({"page": i, "text": text})
    doc.close()
    log.info("Extracted text from %d pages (skipped blank/image pages)", len(pages))
    return pages


def chunk_pages(
    pages: list[dict],
    max_tokens: int = 2000,
) -> list[dict]:
    """
    Group consecutive pages into chunks whose total character count stays
    within max_tokens * CHARS_PER_TOKEN.

    Returns:
        [{"page_start": int, "page_end": int, "text": str}, ...]
    """
    max_chars = max_tokens * CHARS_PER_TOKEN
    chunks = []
    current_text = ""
    current_start = None
    current_end = None

    for p in pages:
        page_num = p["page"]
        page_text = p["text"]

        if current_start is None:
            current_start = page_num

        # If adding this page would exceed the limit, flush the current chunk first.
        if current_text and (len(current_text) + len(page_text) > max_chars):
            chunks.append({
                "page_start": current_start,
                "page_end": current_end,
                "text": current_text,
            })
            current_text = ""
            current_start = page_num

        current_text += f"\n[Page {page_num}]\n" + page_text
        current_end = page_num

    # Flush remainder
    if current_text:
        chunks.append({
            "page_start": current_start,
            "page_end": current_end,
            "text": current_text,
        })

    log.info("Split into %d chunks (max ~%d tokens each)", len(chunks), max_tokens)
    return chunks


# ─────────────────────────────────────────────────────────────────────────────
# JSON repair utilities
# ─────────────────────────────────────────────────────────────────────────────

def _strip_markdown_fences(text: str) -> str:
    """Remove ```json ... ``` or plain ``` fences if Gemini ignores the prompt."""
    text = text.strip()
    # Remove opening fence
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    # Remove closing fence
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _extract_json_array(text: str) -> str:
    """
    Best-effort extraction of the outermost JSON array from raw text.
    Handles cases where Gemini adds a sentence before/after the JSON.
    """
    # Try to find array boundaries
    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end != -1 and end > start:
        return text[start: end + 1]
    return text


def try_parse_json(raw: str) -> tuple[list | None, str | None]:
    """
    Attempt to parse Gemini's response as a JSON array.

    Returns (parsed_list, None) on success.
    Returns (None, error_message) on failure.
    """
    cleaned = _strip_markdown_fences(raw)
    cleaned = _extract_json_array(cleaned)

    try:
        data = json.loads(cleaned)
        if not isinstance(data, list):
            return None, f"Parsed JSON is type {type(data).__name__}, expected list"
        return data, None
    except json.JSONDecodeError as exc:
        return None, str(exc)


# ─────────────────────────────────────────────────────────────────────────────
# Rule normalisation / validation
# ─────────────────────────────────────────────────────────────────────────────

def _next_rule_id(existing_ids: set[str]) -> str:
    """Generate the next available R### id."""
    n = 1
    while True:
        rid = f"R{n:03d}"
        if rid not in existing_ids:
            return rid
        n += 1


def normalise_rule(raw_rule: dict, existing_ids: set[str], chunk_page_start: int) -> dict | None:
    """
    Validate and normalise a single rule dict received from Gemini.

    - Returns None if the rule is fundamentally invalid (missing mandatory data).
    - Auto-assigns rule_id if missing.
    - Clamps severity to allowed values.
    - Coerces value to float.
    """
    if not isinstance(raw_rule, dict):
        return None

    # Check required fields
    missing = REQUIRED_RULE_FIELDS - raw_rule.keys()
    if missing:
        log.debug("Skipping rule with missing fields %s: %s", missing, raw_rule)
        return None

    # Coerce value
    try:
        value = float(raw_rule["value"])
    except (TypeError, ValueError):
        log.debug("Skipping rule with non-numeric value: %s", raw_rule)
        return None

    # Severity
    severity = str(raw_rule.get("severity", "info")).lower()
    if severity not in VALID_SEVERITIES:
        severity = "info"

    # rule_id
    rid = str(raw_rule.get("rule_id", "")).strip()
    if not rid or rid in existing_ids:
        rid = _next_rule_id(existing_ids)
    existing_ids.add(rid)

    # source_page
    try:
        source_page = int(raw_rule["source_page"])
    except (TypeError, ValueError):
        source_page = chunk_page_start

    return {
        "rule_id": rid,
        "rule": str(raw_rule.get("rule", "unnamed_rule")).strip().lower().replace(" ", "_"),
        "value": value,
        "unit": str(raw_rule.get("unit", "")).strip(),
        "condition": str(raw_rule.get("condition", "")).strip(),
        "source_page": source_page,
        "severity": severity,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Gemini API interaction
# ─────────────────────────────────────────────────────────────────────────────

class GeminiClient:
    """Thin wrapper around google-generativeai with retry logic."""

    def __init__(self, api_key: str, model_name: str = "gemini-1.5-flash"):
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel(
            model_name=model_name,
            system_instruction=ANALYST_SYSTEM_PROMPT,
        )
        self.model_name = model_name
        log.info("Gemini client initialised: %s", model_name)

    def call(self, prompt: str, verbose: bool = False) -> str:
        """Send a prompt and return the response text. Raises on API error."""
        if verbose:
            log.debug("─── Prompt (first 300 chars) ───\n%s\n───", prompt[:300])

        response = self.model.generate_content(
            prompt,
            generation_config=genai.types.GenerationConfig(
                temperature=0.0,        # deterministic extraction
                max_output_tokens=4096,
            ),
        )

        # Safely extract text (handles blocked responses)
        try:
            text = response.text
        except ValueError as exc:
            raise RuntimeError(f"Gemini response blocked or empty: {exc}") from exc

        if verbose:
            log.debug("─── Response (first 300 chars) ───\n%s\n───", text[:300])

        return text


# ─────────────────────────────────────────────────────────────────────────────
# Analyst Agent core
# ─────────────────────────────────────────────────────────────────────────────

class AnalystAgent:
    """
    Orchestrates the full PDF → rules.json pipeline.
    """

    def __init__(
        self,
        gemini: GeminiClient,
        output_path: Path,
        failed_log_path: Path,
        sleep_seconds: float = 2.0,
        verbose: bool = False,
    ):
        self.gemini = gemini
        self.output_path = output_path
        self.failed_log_path = failed_log_path
        self.sleep_seconds = sleep_seconds
        self.verbose = verbose

        self._all_rules: list[dict] = []
        self._existing_ids: set[str] = set()
        self._stats = {
            "chunks_total": 0,
            "chunks_ok": 0,
            "chunks_retry_ok": 0,
            "chunks_failed": 0,
            "rules_extracted": 0,
            "rules_normalised": 0,
        }

    # ── public API ────────────────────────────────────────────────────────────

    def run(self, pdf_path: Path, max_tokens_per_chunk: int = 2000) -> Path:
        """
        Full pipeline: PDF → chunks → Gemini → validate → rules.json

        Returns the path to rules.json.
        """
        log.info("═══ ADIE Analyst Agent starting ═══")
        log.info("PDF  : %s", pdf_path)
        log.info("Output: %s", self.output_path)

        # 1. Extract pages
        pages = extract_pages(pdf_path)
        if not pages:
            log.error("No text extracted from PDF. Is it a scanned image PDF?")
            sys.exit(1)

        # 2. Chunk
        chunks = chunk_pages(pages, max_tokens=max_tokens_per_chunk)
        self._stats["chunks_total"] = len(chunks)

        # 3. Send each chunk to Gemini
        for idx, chunk in enumerate(chunks, start=1):
            log.info(
                "Processing chunk %d/%d  (pages %d–%d, ~%d chars)",
                idx,
                len(chunks),
                chunk["page_start"],
                chunk["page_end"],
                len(chunk["text"]),
            )
            self._process_chunk(chunk, chunk_index=idx)

            # Rate-limit sleep (skip after last chunk)
            if idx < len(chunks):
                time.sleep(self.sleep_seconds)

        # 4. Write rules.json
        self._write_output()

        # 5. Print summary
        self._print_summary()

        return self.output_path

    # ── internals ────────────────────────────────────────────────────────────

    def _process_chunk(self, chunk: dict, chunk_index: int) -> None:
        """Send one chunk to Gemini, parse the response, retry once on failure."""
        prompt = ANALYST_USER_PROMPT_TEMPLATE.format(
            page_start=chunk["page_start"],
            page_end=chunk["page_end"],
            chunk_text=chunk["text"],
        )

        # ── First attempt ─────────────────────────────────────────────────────
        try:
            raw_response = self.gemini.call(prompt, verbose=self.verbose)
        except Exception as exc:
            log.error("Gemini API error on chunk %d: %s", chunk_index, exc)
            self._log_failed_chunk(chunk, f"API error: {exc}")
            self._stats["chunks_failed"] += 1
            return

        parsed, error = try_parse_json(raw_response)

        if parsed is not None:
            self._stats["chunks_ok"] += 1
            self._ingest_rules(parsed, chunk["page_start"])
            return

        # ── Retry once ────────────────────────────────────────────────────────
        log.warning("JSON parse failed on chunk %d: %s — retrying once.", chunk_index, error)
        time.sleep(self.sleep_seconds)   # extra sleep before retry

        retry_prompt = prompt + RETRY_PROMPT_SUFFIX_TEMPLATE.format(error=error)
        try:
            raw_response2 = self.gemini.call(retry_prompt, verbose=self.verbose)
        except Exception as exc:
            log.error("Gemini API error on chunk %d retry: %s", chunk_index, exc)
            self._log_failed_chunk(chunk, f"API error on retry: {exc}")
            self._stats["chunks_failed"] += 1
            return

        parsed2, error2 = try_parse_json(raw_response2)

        if parsed2 is not None:
            self._stats["chunks_retry_ok"] += 1
            self._ingest_rules(parsed2, chunk["page_start"])
            return

        # ── Both attempts failed ──────────────────────────────────────────────
        log.error(
            "Chunk %d failed after retry. Second error: %s. Written to %s",
            chunk_index,
            error2,
            self.failed_log_path,
        )
        self._log_failed_chunk(chunk, f"First: {error} | Retry: {error2}")
        self._stats["chunks_failed"] += 1

    def _ingest_rules(self, raw_rules: list, chunk_page_start: int) -> None:
        """Normalise and collect rules from a parsed Gemini array."""
        self._stats["rules_extracted"] += len(raw_rules)
        for raw in raw_rules:
            normed = normalise_rule(raw, self._existing_ids, chunk_page_start)
            if normed:
                self._all_rules.append(normed)
                self._stats["rules_normalised"] += 1

    def _write_output(self) -> None:
        """Serialise all_rules to rules.json (pretty-printed, UTF-8)."""
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.output_path, "w", encoding="utf-8") as fh:
            json.dump(self._all_rules, fh, indent=2, ensure_ascii=False)
        log.info("Wrote %d rules to %s", len(self._all_rules), self.output_path)

    def _log_failed_chunk(self, chunk: dict, reason: str) -> None:
        """Append a failed chunk record to failed_chunks.log."""
        self.failed_log_path.parent.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(tz=timezone.utc).isoformat()
        entry = (
            f"[{timestamp}]  Pages {chunk['page_start']}–{chunk['page_end']}  "
            f"Reason: {reason}\n"
            f"Chunk text (first 500 chars):\n{chunk['text'][:500]}\n"
            + ("─" * 60) + "\n"
        )
        with open(self.failed_log_path, "a", encoding="utf-8") as fh:
            fh.write(entry)

    def _print_summary(self) -> None:
        s = self._stats
        log.info("═══ Analyst Agent complete ═══")
        log.info("  Chunks  total  : %d", s["chunks_total"])
        log.info("  Chunks  ok (1st try) : %d", s["chunks_ok"])
        log.info("  Chunks  ok (retry)   : %d", s["chunks_retry_ok"])
        log.info("  Chunks  failed       : %d", s["chunks_failed"])
        log.info("  Rules   extracted    : %d", s["rules_extracted"])
        log.info("  Rules   normalised   : %d", s["rules_normalised"])
        if s["chunks_failed"] > 0:
            log.warning(
                "  %d chunks failed — check %s for manual review.",
                s["chunks_failed"],
                self.failed_log_path,
            )


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="analyst_agent",
        description="ADIE Agent 1 — Extract engineering rules from a PDF into rules.json",
    )
    parser.add_argument(
        "--pdf",
        required=True,
        metavar="PATH",
        help="Path to the engineering standards PDF (e.g. standards/ISO_2768.pdf)",
    )
    parser.add_argument(
        "--output",
        default="data/rules.json",
        metavar="PATH",
        help="Output path for rules.json  (default: data/rules.json)",
    )
    parser.add_argument(
        "--failed-log",
        default="data/failed_chunks.log",
        metavar="PATH",
        help="Path to write failed chunk records  (default: data/failed_chunks.log)",
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
        help="Gemini model name  (default: gemini-1.5-flash)",
    )
    parser.add_argument(
        "--chunk-tokens",
        type=int,
        default=2000,
        metavar="N",
        help="Target tokens per chunk  (default: 2000)",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=2.0,
        metavar="SECS",
        help="Seconds to sleep between Gemini calls  (default: 2.0)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print prompt/response previews for debugging",
    )
    return parser


def main() -> None:
    parser = _build_arg_parser()
    args = parser.parse_args()

    # ── Validate inputs ───────────────────────────────────────────────────────
    pdf_path = Path(args.pdf)
    if not pdf_path.exists():
        log.error("PDF not found: %s", pdf_path)
        sys.exit(1)
    if not pdf_path.suffix.lower() == ".pdf":
        log.warning("File does not have .pdf extension: %s", pdf_path)

    if not args.api_key:
        log.error(
            "No Gemini API key provided. Set GEMINI_API_KEY env var "
            "or pass --api-key YOUR_KEY"
        )
        sys.exit(1)

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # ── Initialise and run ────────────────────────────────────────────────────
    try:
        gemini = GeminiClient(api_key=args.api_key, model_name=args.model)
        agent = AnalystAgent(
            gemini=gemini,
            output_path=Path(args.output),
            failed_log_path=Path(args.failed_log),
            sleep_seconds=args.sleep,
            verbose=args.verbose,
        )
        output_file = agent.run(
            pdf_path=pdf_path,
            max_tokens_per_chunk=args.chunk_tokens,
        )
        print(f"\n✅  rules.json written to: {output_file.resolve()}")
    except KeyboardInterrupt:
        log.warning("Interrupted by user.")
        sys.exit(130)
    except Exception:
        log.error("Fatal error:\n%s", traceback.format_exc())
        sys.exit(1)


if __name__ == "__main__":
    main()
