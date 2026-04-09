"""
ADIE Unit Tests — test_analyst.py

Tests for analyst_agent.py that run outside Fusion 360 (no adsk required).
Uses mock Gemini responses to validate the parsing and normalisation pipeline.

Run:
    conda activate adie
    python -m pytest tests/test_analyst.py -v
"""

import json
import sys
import os
from pathlib import Path
import pytest

# Make adie root and setup/ importable
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "setup"))

from analyst_agent import (
    try_parse_json,
    normalise_rule,
    chunk_pages,
    _strip_markdown_fences,
    _extract_json_array,
)


# ─────────────────────────────────────────────────────────────────────────────
# JSON parsing tests
# ─────────────────────────────────────────────────────────────────────────────

class TestTryParseJson:
    def test_clean_json_array(self):
        raw = '[{"rule_id":"R001","rule":"min_wall_thickness","value":2.0,"unit":"mm","condition":"","source_page":4,"severity":"critical"}]'
        data, err = try_parse_json(raw)
        assert err is None
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["rule_id"] == "R001"

    def test_json_with_markdown_fence(self):
        raw = '```json\n[{"rule": "min_edge", "value": 0.5, "unit": "mm", "condition": "", "source_page": 1, "severity": "warning"}]\n```'
        data, err = try_parse_json(raw)
        assert err is None
        assert isinstance(data, list)

    def test_json_with_preamble(self):
        raw = 'Here are the rules I found:\n[{"rule": "test", "value": 1, "unit": "mm", "condition": "", "source_page": 1, "severity": "info"}]'
        data, err = try_parse_json(raw)
        assert err is None
        assert isinstance(data, list)

    def test_empty_array(self):
        data, err = try_parse_json("[]")
        assert err is None
        assert data == []

    def test_invalid_json(self):
        data, err = try_parse_json("{not valid json}")
        assert data is None
        assert err is not None

    def test_dict_not_list(self):
        data, err = try_parse_json('{"rule": "test"}')
        assert data is None
        assert "list" in err.lower()

    def test_empty_string(self):
        data, err = try_parse_json("")
        assert data is None


class TestStripMarkdownFences:
    def test_with_json_fence(self):
        result = _strip_markdown_fences("```json\n[1,2,3]\n```")
        assert result == "[1,2,3]"

    def test_plain_fence(self):
        result = _strip_markdown_fences("```\n[1,2]\n```")
        assert result == "[1,2]"

    def test_no_fence(self):
        result = _strip_markdown_fences("[1,2,3]")
        assert result == "[1,2,3]"


class TestExtractJsonArray:
    def test_extracts_array(self):
        text = "Some text [1, 2, 3] more text"
        result = _extract_json_array(text)
        assert result == "[1, 2, 3]"

    def test_no_array(self):
        text = "No array here"
        result = _extract_json_array(text)
        assert result == "No array here"   # unchanged when no brackets


# ─────────────────────────────────────────────────────────────────────────────
# Rule normalisation tests
# ─────────────────────────────────────────────────────────────────────────────

class TestNormaliseRule:
    def _valid_rule(self, **overrides):
        base = {
            "rule_id":     "R001",
            "rule":        "min_wall_thickness",
            "value":       2.0,
            "unit":        "mm",
            "condition":   "material == Aluminum",
            "source_page": 4,
            "severity":    "critical",
        }
        base.update(overrides)
        return base

    def test_valid_rule_passes(self):
        existing = set()
        result = normalise_rule(self._valid_rule(), existing, 1)
        assert result is not None
        assert result["rule_id"] == "R001"
        assert result["value"] == 2.0
        assert result["severity"] == "critical"

    def test_missing_required_field_returns_none(self):
        raw = {"rule_id": "R001", "rule": "test", "unit": "mm"}   # missing value, source_page, severity
        result = normalise_rule(raw, set(), 1)
        assert result is None

    def test_non_numeric_value_returns_none(self):
        result = normalise_rule(self._valid_rule(value="not_a_number"), set(), 1)
        assert result is None

    def test_non_dict_returns_none(self):
        assert normalise_rule("string", set(), 1) is None
        assert normalise_rule(42, set(), 1) is None
        assert normalise_rule(None, set(), 1) is None

    def test_invalid_severity_clamped_to_info(self):
        result = normalise_rule(self._valid_rule(severity="unknown"), set(), 1)
        assert result["severity"] == "info"

    def test_duplicate_rule_id_gets_new_id(self):
        existing = {"R001"}
        result = normalise_rule(self._valid_rule(rule_id="R001"), existing, 1)
        assert result["rule_id"] != "R001"
        assert result["rule_id"] in existing

    def test_rule_name_snake_cased(self):
        result = normalise_rule(self._valid_rule(rule="Min Wall Thickness"), set(), 1)
        assert result["rule"] == "min_wall_thickness"

    def test_source_page_fallback_to_chunk_start(self):
        result = normalise_rule(self._valid_rule(source_page="bad"), set(), 7)
        assert result["source_page"] == 7


# ─────────────────────────────────────────────────────────────────────────────
# Chunking tests
# ─────────────────────────────────────────────────────────────────────────────

class TestChunkPages:
    def _make_pages(self, count: int, chars_per_page: int = 1000):
        return [{"page": i + 1, "text": "x" * chars_per_page} for i in range(count)]

    def test_single_chunk_for_small_pdf(self):
        pages = self._make_pages(3, chars_per_page=500)
        chunks = chunk_pages(pages, max_tokens=2000)
        # 3 × 500 chars / 4 chars_per_token = 375 tokens → should be 1 chunk
        assert len(chunks) == 1
        assert chunks[0]["page_start"] == 1
        assert chunks[0]["page_end"]   == 3

    def test_multiple_chunks_for_large_pdf(self):
        # 20 pages × 4000 chars = 20000 chars → ~5000 tokens; max 2000 → ~3+ chunks
        pages = self._make_pages(20, chars_per_page=4000)
        chunks = chunk_pages(pages, max_tokens=2000)
        assert len(chunks) > 1

    def test_empty_pages_gives_no_chunks(self):
        chunks = chunk_pages([], max_tokens=2000)
        assert chunks == []

    def test_chunk_page_ranges_are_correct(self):
        pages = self._make_pages(5, chars_per_page=5000)  # force one page per chunk
        chunks = chunk_pages(pages, max_tokens=500)        # 500 tokens = 2000 chars
        for i, chunk in enumerate(chunks):
            assert chunk["page_start"] <= chunk["page_end"]

    def test_all_pages_covered(self):
        pages = self._make_pages(10, chars_per_page=3000)
        chunks = chunk_pages(pages, max_tokens=2000)
        covered = set()
        for chunk in chunks:
            for p in range(chunk["page_start"], chunk["page_end"] + 1):
                covered.add(p)
        expected = {p["page"] for p in pages}
        assert expected.issubset(covered)


# ─────────────────────────────────────────────────────────────────────────────
# Config tests
# ─────────────────────────────────────────────────────────────────────────────

class TestConfig:
    def test_config_importable(self):
        from config import CONFIG, ADIE_ROOT
        assert isinstance(CONFIG, dict)
        assert ADIE_ROOT.exists()

    def test_required_keys_present(self):
        from config import CONFIG
        for key in [
            "gemini_api_key", "gemini_model",
            "validation_scripts_dir", "rules_json", "violations_json",
            "audit_log_json", "sdf_enabled", "monitor_debounce_seconds",
        ]:
            assert key in CONFIG, f"Missing config key: {key}"

    def test_paths_are_path_objects(self):
        from config import CONFIG
        path_keys = [
            "validation_scripts_dir", "rules_json", "violations_json",
            "audit_log_json", "pending_suggestion",
        ]
        for key in path_keys:
            assert isinstance(CONFIG[key], Path), f"CONFIG['{key}'] should be a Path"
