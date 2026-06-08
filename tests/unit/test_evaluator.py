"""Evaluator unit tests: scoring functions, extract_code, any_of matching."""

import pytest

from airouter.engine.benchmark.evaluator import (
    auto_score,
    extract_code,
    score_architecture,
    score_bug_analysis,
    score_code_generation,
    score_code_review,
    score_documentation,
    score_refactoring,
)
from airouter.engine.benchmark.schemas import L2Case


def _make_case(**overrides) -> L2Case:
    defaults = {
        "id": "TEST-001",
        "task_type": "CODE_GENERATION",
        "complexity": "SIMPLE",
        "prompt": "test prompt",
        "scoring_type": "code_generation",
        "evaluation_criteria": {},
        "expected_issues": [],
    }
    defaults.update(overrides)
    return L2Case(**defaults)


# ── extract_code ──────────────────────────────────────────


class TestExtractCode:
    def test_python_block_preferred(self):
        text = """Some text
```python
def hello():
    pass
```
More text
```js
console.log("hi")
```"""
        assert "def hello" in extract_code(text)

    def test_any_fenced_block(self):
        text = """
```java
public class Main {}
```"""
        assert "public class" in extract_code(text)

    def test_no_fenced_block_returns_full_text(self):
        text = "def hello():\n    pass"
        assert extract_code(text) == text.strip()

    def test_empty_string(self):
        assert extract_code("") == ""


# ── score_code_generation ─────────────────────────────────


class TestScoreCodeGeneration:
    def test_perfect_code(self):
        case = _make_case(
            evaluation_criteria={
                "must_have": [
                    {"id": "function_def", "any_of": ["def "]},
                    {"id": "return", "any_of": ["return"]},
                ]
            }
        )
        output = """```python
def palindrome(s: str) -> bool:
    \"\"\"Check if string is palindrome.\"\"\"
    s = s.lower()
    return s == s[::-1]
```"""
        result = score_code_generation(case, output)
        assert result.scoring_type == "code_generation"
        assert result.overall_score > 0.5
        assert result.dimension_scores["syntax"] == 1.0

    def test_empty_output(self):
        case = _make_case(
            evaluation_criteria={"must_have": [{"id": "func", "any_of": ["def "]}]}
        )
        result = score_code_generation(case, "")
        assert result.overall_score < 0.5

    def test_syntax_error_code(self):
        case = _make_case(
            evaluation_criteria={"must_have": [{"id": "func", "any_of": ["def "]}]}
        )
        output = "```python\ndef broken(:\n    pass\n```"
        result = score_code_generation(case, output)
        assert result.dimension_scores["syntax"] == 0.0


# ── any_of matching ──────────────────────────────────────


class TestAnyOfMatching:
    def test_case_insensitive(self):
        case = _make_case(
            evaluation_criteria={
                "must_have": [{"id": "sql", "any_of": ["SQL Injection", "sql注入"]}]
            }
        )
        output = "This code has a sql injection vulnerability."
        result = score_code_generation(case, output)
        assert result.dimension_scores["requirement_coverage"] == 1.0

    def test_alias_match(self):
        case = _make_case(
            evaluation_criteria={
                "must_have": [
                    {"id": "reverse", "any_of": ["[::-1]", "reversed", "双指针"]}
                ]
            }
        )
        output = "```python\ndef check(s):\n    return reversed(s)\n```"
        result = score_code_generation(case, output)
        assert result.dimension_scores["requirement_coverage"] == 1.0

    def test_no_match(self):
        case = _make_case(
            evaluation_criteria={
                "must_have": [{"id": "feature", "any_of": ["specific_keyword_xyz"]}]
            }
        )
        result = score_code_generation(case, "unrelated output")
        assert result.dimension_scores["requirement_coverage"] == 0.0

    def test_plain_string_criteria_in_normalize(self):
        """_normalize_criteria handles plain strings — but L2Case requires dict format.
        Test the normalize function directly instead of through L2Case.
        """
        from airouter.engine.benchmark.evaluator import _check_any_of, _normalize_criteria

        raw = {"must_have": ["return"]}
        normalized = _normalize_criteria(raw)
        hits, total = _check_any_of(normalized["must_have"], "def f():\n    return 1")
        assert hits == 1
        assert total == 1


# ── score_code_review ─────────────────────────────────────


class TestScoreCodeReview:
    def test_detects_issues(self):
        case = _make_case(
            scoring_type="code_review",
            expected_issues=["sql_injection", "hardcoded_secret"],
        )
        output = (
            "This code has a SQL injection vulnerability due to string concatenation. "
            "The hardcoded API key should be moved to environment variables. "
            "Fix: use parameterized queries and os.environ for secrets."
        )
        result = score_code_review(case, output)
        assert result.dimension_scores["issue_detection_rate"] == 1.0
        assert result.dimension_scores["explanation"] == 1.0
        assert result.dimension_scores["suggestion"] == 1.0

    def test_short_output_no_suggestion(self):
        case = _make_case(
            scoring_type="code_review",
            expected_issues=["sql_injection"],
        )
        output = "SQL injection found."
        result = score_code_review(case, output)
        assert result.dimension_scores["explanation"] == 0.0

    def test_no_expected_issues(self):
        case = _make_case(scoring_type="code_review", expected_issues=[])
        result = score_code_review(case, "some long review output " * 10)
        assert result.dimension_scores["issue_detection_rate"] == 0.0


# ── score_bug_analysis ────────────────────────────────────


class TestScoreBugAnalysis:
    def test_root_cause_and_fix(self):
        case = _make_case(
            scoring_type="bug_analysis",
            expected_issues=["none_type"],
        )
        output = (
            "The root cause is a NoneType error because profile is None. "
            "Fix: add a check `if user_dict.get('profile') is None` before accessing."
        )
        result = score_bug_analysis(case, output)
        assert result.dimension_scores["root_cause"] == 1.0
        assert result.dimension_scores["fix_suggested"] == 1.0

    def test_short_output(self):
        case = _make_case(scoring_type="bug_analysis", expected_issues=["none_type"])
        result = score_bug_analysis(case, "short")
        assert result.dimension_scores["explanation_quality"] == 0.0


# ── score_documentation ───────────────────────────────────


class TestScoreDocumentation:
    def test_good_docs(self):
        case = _make_case(
            scoring_type="documentation",
            evaluation_criteria={
                "must_have": [
                    {"id": "endpoint", "any_of": ["POST", "GET"]},
                    {"id": "params", "any_of": ["parameter", "参数"]},
                ]
            },
        )
        output = (
            "# API Documentation\n\n"
            "## POST /users\n\n"
            "- Parameter: `name` (string)\n"
            "- Response: 200 OK\n\n"
            "```json\n{\"id\": 1}\n```\n\n"
            "This endpoint creates a new user."
        )
        result = score_documentation(case, output)
        assert result.dimension_scores["structure"] >= 0.75
        assert result.dimension_scores["requirement_coverage"] == 1.0

    def test_short_docs(self):
        case = _make_case(scoring_type="documentation")
        result = score_documentation(case, "very short")
        assert result.dimension_scores["length_adequate"] == 0.0


# ── score_refactoring ─────────────────────────────────────


class TestScoreRefactoring:
    def test_code_changed(self):
        case = _make_case(
            scoring_type="refactoring",
            input_context="def old():\n    return 1",
            evaluation_criteria={
                "must_have": [{"id": "func", "any_of": ["def "]}]
            },
        )
        output = "```python\ndef new_func() -> int:\n    \"\"\"Refactored.\"\"\"\n    return 1\n```"
        result = score_refactoring(case, output)
        assert result.dimension_scores["code_changed"] == 1.0
        assert result.dimension_scores["syntax"] == 1.0

    def test_unchanged_code(self):
        original = "def old():\n    return 1"
        case = _make_case(
            scoring_type="refactoring",
            input_context=original,
        )
        output = f"```python\n{original}\n```"
        result = score_refactoring(case, output)
        assert result.dimension_scores["code_changed"] == 0.0


# ── score_architecture ────────────────────────────────────


class TestScoreArchitecture:
    def test_good_architecture(self):
        case = _make_case(
            scoring_type="architecture",
            evaluation_criteria={
                "must_have": [
                    {"id": "sharding", "any_of": ["一致性哈希", "sharding", "分片"]},
                    {"id": "replication", "any_of": ["replication", "复制", "主从"]},
                ]
            },
        )
        output = (
            "# Architecture Design\n\n"
            "## Data Distribution\n\n"
            "- 一致性哈希分片策略：使用虚拟节点保证数据均匀分布\n"
            "- 主从复制保证高可用：每个主节点有两个从节点作为备份\n\n"
            "## Components\n\n"
            "```text\n"
            "+-- Client --+-- Load Balancer --+\n"
            "|            |                   |\n"
            "+-- Node A --+-- Node B --+-- Node C --+\n"
            "```\n\n"
            "This design supports horizontal scaling and fault tolerance. "
            "The sharding strategy uses consistent hashing to distribute data "
            "evenly across nodes. When a node fails, the replica takes over "
            "automatically. The system supports adding new nodes without data "
            "migration of existing keys. Cache eviction follows LRU policy. "
            "Persistence uses both RDB snapshots and AOF logs for durability."
        )
        result = score_architecture(case, output)
        assert result.dimension_scores["requirement_coverage"] == 1.0
        assert result.dimension_scores["structure"] >= 0.66
        assert result.dimension_scores["depth"] == 1.0


# ── auto_score dispatcher ─────────────────────────────────


class TestAutoScore:
    def test_dispatches_correctly(self):
        case = _make_case(scoring_type="code_generation")
        output = "```python\ndef f():\n    return 1\n```"
        result = auto_score(case, output)
        assert result.scoring_type == "code_generation"

    def test_unknown_scoring_type_raises(self):
        case = _make_case(scoring_type="unknown_type")
        with pytest.raises(ValueError, match="Unknown scoring_type"):
            auto_score(case, "output")
