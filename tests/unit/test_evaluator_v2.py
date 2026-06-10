"""Tests for evaluator v2: truncation penalty, architecture depth, test_code execution."""

from __future__ import annotations

import pytest

from airouter.engine.benchmark.evaluator import (
    _ast_denylist_check,
    _execute_test_code,
    _score_architecture_depth,
    auto_score,
)
from airouter.engine.benchmark.schemas import L2Case

# ── Architecture depth scoring ────────────────────────────────


class TestArchitectureDepth:
    def test_empty_output(self):
        assert _score_architecture_depth("") == 0.0

    def test_short_output_no_keywords(self):
        score = _score_architecture_depth("hello world")
        assert score == 0.0  # 0 dimensions hit, length < 100

    def test_all_seven_dimensions(self):
        output = (
            "service gateway middleware "
            "pipeline queue event "
            "failover retry circuit_breaker "
            "horizontal_scaling load_balancing "
            "tradeoff vs pros cons "
            "logging monitoring metrics "
            "auth encryption rbac "
            + "x" * 500  # ensure length >= 500
        )
        score = _score_architecture_depth(output)
        # 7/7 dimensions = 1.0, length >= 500 = 1.0
        assert score == pytest.approx(0.7 * 1.0 + 0.3 * 1.0)

    def test_partial_dimensions(self):
        output = "service module " + "x" * 500  # only components hit
        score = _score_architecture_depth(output)
        # 1/7 dimensions, length >= 500
        expected = 0.7 * (1 / 7.0) + 0.3 * 1.0
        assert score == pytest.approx(expected, abs=0.01)

    def test_medium_length(self):
        output = "service " + "x" * 200  # components hit, length 100-500
        score = _score_architecture_depth(output)
        expected = 0.7 * (1 / 7.0) + 0.3 * 0.5
        assert score == pytest.approx(expected, abs=0.01)


# ── AST denylist ──────────────────────────────────────────────


class TestAstDenylist:
    def test_safe_code(self):
        assert _ast_denylist_check("def foo():\n    return 42") is None

    def test_import_os(self):
        assert _ast_denylist_check("import os") == "os"

    def test_from_subprocess(self):
        assert _ast_denylist_check("from subprocess import run") == "subprocess"

    def test_import_socket(self):
        assert _ast_denylist_check("import socket") == "socket"

    def test_import_requests(self):
        assert _ast_denylist_check("import requests") == "requests"

    def test_syntax_error_returns_none(self):
        assert _ast_denylist_check("def foo(") is None

    def test_safe_imports_allowed(self):
        assert _ast_denylist_check("import json\nimport math\nfrom typing import Any") is None

    def test_nested_module(self):
        assert _ast_denylist_check("import os.path") == "os"


# ── Test code execution ───────────────────────────────────────


class TestExecuteTestCode:
    def test_simple_passing_test(self):
        model_output = '```python\ndef add(a, b):\n    return a + b\n```'
        test_code = 'assert add(1, 2) == 3\nprint("1 passed")'
        result = _execute_test_code(model_output, test_code)
        assert result["error"] is None
        assert result["pass_rate"] > 0

    def test_failing_test(self):
        model_output = '```python\ndef add(a, b):\n    return a * b\n```'
        test_code = 'assert add(1, 2) == 3\nprint("1 failed")'
        result = _execute_test_code(model_output, test_code)
        # Should have some failure indication
        assert result["pass_rate"] < 1.0 or result["error"] is not None

    def test_denied_code(self):
        model_output = '```python\nimport os\ndef foo():\n    os.system("ls")\n```'
        test_code = 'assert True'
        result = _execute_test_code(model_output, test_code)
        assert result["error"] is not None
        assert "denied" in result["error"]
        assert result["pass_rate"] == 0.0

    def test_syntax_error_in_model_output(self):
        model_output = '```python\ndef foo(\n```'
        test_code = 'assert True'
        result = _execute_test_code(model_output, test_code)
        assert result["error"] is not None
        assert result["pass_rate"] == 0.0

    def test_no_code_block(self):
        model_output = "This is just text with no code blocks."
        test_code = 'assert True'
        result = _execute_test_code(model_output, test_code)
        # Will try to execute plain text as Python — should fail
        assert result["error"] is not None or result["pass_rate"] == 0.0


# ── Auto-score truncation penalty ─────────────────────────────


def _make_case(scoring_type: str = "code_generation", **kwargs) -> L2Case:
    return L2Case(
        id="TEST-001",
        task_type="CODE_GENERATION",
        complexity="SIMPLE",
        prompt="test prompt",
        scoring_type=scoring_type,
        **kwargs,
    )


class TestAutoScoreTruncation:
    def test_no_truncation_no_penalty(self):
        case = _make_case()
        output = '```python\ndef foo():\n    return 42\n```'
        result = auto_score(case, output)
        assert result.details.get("model_truncated") is not True

    def test_model_truncated_caps_score(self):
        case = _make_case()
        # Generate a high-quality output that would score > 0.65
        output = (
            '```python\ndef is_palindrome(s: str) -> bool:\n'
            '    """Check if string is palindrome."""\n'
            '    s = s.lower().replace(" ", "")\n'
            '    return s == s[::-1]\n```\n'
            + "This is a good implementation with type hints and docstring. " * 10
        )
        result_normal = auto_score(case, output)
        result_truncated = auto_score(case, output, response_metadata={"model_truncated": True})

        assert result_truncated.overall_score <= 0.65
        assert result_truncated.details.get("model_truncated") is True
        # Normal score should be >= truncated score
        assert result_normal.overall_score >= result_truncated.overall_score

    def test_judge_context_truncated_no_penalty(self):
        """judge_context_truncated should NOT affect score."""
        case = _make_case()
        output = '```python\ndef foo():\n    return 42\n```'
        result = auto_score(case, output, response_metadata={"judge_context_truncated": True})
        assert result.details.get("model_truncated") is not True
        # Score should not be capped
        assert result.overall_score >= 0.0


# ── Auto-score test_code execution ────────────────────────────


class TestAutoScoreTestCode:
    def test_allow_execution_runs_tests(self):
        case = _make_case(
            allow_execution=True,
            test_code='assert add(1, 2) == 3\nprint("1 passed")',
        )
        output = '```python\ndef add(a, b):\n    return a + b\n```'
        result = auto_score(case, output)
        assert "test_results" in result.details

    def test_no_execution_without_flag(self):
        case = _make_case(
            allow_execution=False,
            test_code='assert add(1, 2) == 3',
        )
        output = '```python\ndef add(a, b):\n    return a + b\n```'
        result = auto_score(case, output)
        assert "test_results" not in result.details
