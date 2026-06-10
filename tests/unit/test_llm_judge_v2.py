"""Tests for llm_judge_v2: context building, JSONL resume, JSON parsing."""

from __future__ import annotations

import json
from pathlib import Path

from airouter.engine.benchmark.llm_judge_v2 import (
    OUTPUT_CHAR_LIMIT,
    _build_judge_context,
    _load_completed_keys,
    _parse_judge_json,
)

# ── JSON parsing ──────────────────────────────────────────────


class TestParseJudgeJson:
    def test_direct_parse(self):
        content = '{"correctness": 4, "code_quality": 3, "comment": "good"}'
        result = _parse_judge_json(content)
        assert result is not None
        assert result["correctness"] == 4

    def test_markdown_code_block(self):
        content = '```json\n{"correctness": 4}\n```'
        result = _parse_judge_json(content)
        assert result is not None
        assert result["correctness"] == 4

    def test_regex_extract(self):
        content = 'Here is the result: {"correctness": 4} and some text after.'
        result = _parse_judge_json(content)
        assert result is not None
        assert result["correctness"] == 4

    def test_single_quotes(self):
        content = "{'correctness': 4, 'comment': 'ok'}"
        result = _parse_judge_json(content)
        assert result is not None
        assert result["correctness"] == 4

    def test_invalid_json(self):
        content = "This is not JSON at all"
        result = _parse_judge_json(content)
        assert result is None


# ── Context building ──────────────────────────────────────────


class TestBuildContext:
    def test_basic_context(self):
        case = {"id": "CG-001", "prompt": "Write a function", "task_type": "CODE_GENERATION"}
        output = "def foo(): return 42"
        context, truncated = _build_judge_context(case, output)
        assert "Write a function" in context
        assert "def foo(): return 42" in context
        assert truncated is False

    def test_includes_input_context(self):
        case = {
            "id": "CG-001",
            "prompt": "Write a function",
            "input_context": "This is a Flask project",
        }
        context, _ = _build_judge_context(case, "output")
        assert "项目上下文" in context
        assert "Flask project" in context

    def test_includes_evaluation_criteria(self):
        case = {
            "id": "CG-001",
            "prompt": "test",
            "evaluation_criteria": {"must_have": [{"id": "func", "any_of": ["def "]}]},
        }
        context, _ = _build_judge_context(case, "output")
        assert "评分标准" in context

    def test_includes_expected_issues(self):
        case = {
            "id": "CR-001",
            "prompt": "review this code",
            "expected_issues": ["sql_injection", "hardcoded_secret"],
        }
        context, _ = _build_judge_context(case, "output")
        assert "预期应发现的问题" in context
        assert "sql_injection" in context

    def test_output_truncation_at_limit(self):
        case = {"id": "CG-001", "prompt": "test"}
        long_output = "x" * (OUTPUT_CHAR_LIMIT + 1000)
        context, truncated = _build_judge_context(case, long_output)
        assert truncated is True
        # Output in context should be truncated
        assert len(context) < len(long_output) + 1000

    def test_output_within_limit_not_truncated(self):
        case = {"id": "CG-001", "prompt": "test"}
        short_output = "x" * 100
        _, truncated = _build_judge_context(case, short_output)
        assert truncated is False


# ── JSONL resume ──────────────────────────────────────────────


class TestJsonlResume:
    def test_load_completed_keys(self, tmp_path: Path):
        jsonl = tmp_path / "results.jsonl"
        lines = [
            json.dumps({"case_id": "CG-001", "model": "m1", "judge_model": "j1", "weighted_score": 3.5}),
            json.dumps({"case_id": "CG-002", "model": "m1", "judge_model": "j1", "weighted_score": 4.0}),
        ]
        jsonl.write_text("\n".join(lines))
        keys = _load_completed_keys(jsonl)
        assert "CG-001:m1:j1" in keys
        assert "CG-002:m1:j1" in keys

    def test_skip_zero_score(self, tmp_path: Path):
        jsonl = tmp_path / "results.jsonl"
        lines = [
            json.dumps({"case_id": "CG-001", "model": "m1", "judge_model": "j1", "weighted_score": 0}),
        ]
        jsonl.write_text("\n".join(lines))
        keys = _load_completed_keys(jsonl)
        assert "CG-001:m1:j1" not in keys

    def test_include_error_comments(self, tmp_path: Path):
        """Error entries (weighted_score=0) should NOT be marked completed, so they get retried."""
        jsonl = tmp_path / "results.jsonl"
        lines = [
            json.dumps({"case_id": "CG-001", "model": "m1", "judge_model": "j1", "weighted_score": 0, "comment": "error: timeout"}),
        ]
        jsonl.write_text("\n".join(lines))
        keys = _load_completed_keys(jsonl)
        assert "CG-001:m1:j1" not in keys

    def test_empty_file(self, tmp_path: Path):
        jsonl = tmp_path / "results.jsonl"
        jsonl.write_text("")
        keys = _load_completed_keys(jsonl)
        assert len(keys) == 0

    def test_nonexistent_file(self, tmp_path: Path):
        jsonl = tmp_path / "nonexistent.jsonl"
        keys = _load_completed_keys(jsonl)
        assert len(keys) == 0
