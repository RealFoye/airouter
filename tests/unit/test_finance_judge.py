"""Unit tests for finance_judge module."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from airouter.adapters.base import AdapterResponse
from airouter.engine.benchmark.finance_judge import (
    _finance_judge_one,
    _load_artifact_contents,
    _load_completed_keys,
    _parse_finance_judge_json,
    build_finance_judge_context,
)
from airouter.engine.benchmark.judge_prompts import VALID_RED_FLAGS

# ── _parse_finance_judge_json ─────────────────────────────────


class TestParseFinanceJudgeJson:
    """Test 3-tier JSON parsing."""

    def test_direct_json(self):
        data = {"numeric_policy_correctness": 4, "comment": "good"}
        result = _parse_finance_judge_json(json.dumps(data))
        assert result is not None
        assert result["numeric_policy_correctness"] == 4

    def test_markdown_code_block(self):
        data = {"numeric_policy_correctness": 3}
        content = f"```json\n{json.dumps(data)}\n```"
        result = _parse_finance_judge_json(content)
        assert result is not None
        assert result["numeric_policy_correctness"] == 3

    def test_regex_extract(self):
        data = {"comment": "ok"}
        content = f"Here is my assessment: {json.dumps(data)} and some trailing text."
        result = _parse_finance_judge_json(content)
        assert result is not None
        assert result["comment"] == "ok"

    def test_single_quote_fix(self):
        content = "{'numeric_policy_correctness': 4, 'comment': 'good'}"
        result = _parse_finance_judge_json(content)
        assert result is not None
        assert result["numeric_policy_correctness"] == 4

    def test_completely_invalid(self):
        result = _parse_finance_judge_json("this is not json at all")
        assert result is None

    def test_empty_string(self):
        result = _parse_finance_judge_json("")
        assert result is None

    def test_red_flags_list(self):
        data = {"red_flags": ["hallucinated_data", "weak_evidence"]}
        result = _parse_finance_judge_json(json.dumps(data))
        assert result is not None
        assert result["red_flags"] == ["hallucinated_data", "weak_evidence"]


# ── build_finance_judge_context ───────────────────────────────


class TestBuildFinanceJudgeContext:
    """Test context building with all sections."""

    def test_includes_category(self):
        case = {"category": "TABLE_CALCULATION", "prompt": "Calculate total"}
        ctx, truncated = build_finance_judge_context(
            case, "model output", 0.75, {"amount_accuracy": 0.8}, ""
        )
        assert "表格计算" in ctx
        assert "TABLE_CALCULATION" in ctx
        assert not truncated

    def test_includes_prompt(self):
        case = {"category": "REIMBURSEMENT_AUDIT", "prompt": "审核报销单据"}
        ctx, _ = build_finance_judge_context(
            case, "output", 0.5, {}, ""
        )
        assert "审核报销单据" in ctx

    def test_includes_input_context(self):
        case = {"category": "TABLE_CALCULATION", "input_context": "Department A budget data"}
        ctx, _ = build_finance_judge_context(
            case, "output", 0.5, {}, ""
        )
        assert "Department A budget data" in ctx

    def test_includes_artifact_contents(self):
        case = {"category": "TABLE_CALCULATION"}
        ctx, _ = build_finance_judge_context(
            case, "output", 0.5, {}, "CSV content: col1,col2\n1,2"
        )
        assert "CSV content: col1,col2" in ctx

    def test_includes_expected_answer(self):
        case = {"category": "TABLE_CALCULATION", "expected_answer": {"total": 1000}}
        ctx, _ = build_finance_judge_context(
            case, "output", 0.5, {}, ""
        )
        assert "1000" in ctx
        assert "参考答案" in ctx

    def test_includes_required_findings(self):
        case = {
            "category": "REIMBURSEMENT_AUDIT",
            "evaluation": {"required_findings": ["duplicate_invoice", "over_limit"]},
        }
        ctx, _ = build_finance_judge_context(
            case, "output", 0.5, {}, ""
        )
        assert "duplicate_invoice" in ctx
        assert "over_limit" in ctx

    def test_includes_forbidden_findings(self):
        case = {
            "category": "REIMBURSEMENT_AUDIT",
            "evaluation": {"forbidden_findings": ["fabricated_policy"]},
        }
        ctx, _ = build_finance_judge_context(
            case, "output", 0.5, {}, ""
        )
        assert "fabricated_policy" in ctx
        assert "禁止出现" in ctx

    def test_includes_rule_score(self):
        case = {"category": "TABLE_CALCULATION"}
        ctx, _ = build_finance_judge_context(
            case, "output", 0.85, {"amount_accuracy": 0.9, "finding_recall": 0.8}, ""
        )
        assert "0.850" in ctx
        assert "amount_accuracy" in ctx

    def test_includes_model_output(self):
        case = {"category": "TABLE_CALCULATION"}
        ctx, _ = build_finance_judge_context(
            case, "This is the model answer with details.", 0.5, {}, ""
        )
        assert "This is the model answer with details." in ctx

    def test_truncation(self):
        case = {"category": "TABLE_CALCULATION"}
        long_output = "x" * 40000
        ctx, truncated = build_finance_judge_context(
            case, long_output, 0.5, {}, ""
        )
        assert truncated
        assert "[truncated]" in ctx

    def test_no_truncation_under_limit(self):
        case = {"category": "TABLE_CALCULATION"}
        ctx, truncated = build_finance_judge_context(
            case, "short answer", 0.5, {}, ""
        )
        assert not truncated


# ── _load_artifact_contents ───────────────────────────────────


class TestLoadArtifactContents:
    """Test artifact file loading."""

    def test_no_artifacts(self, tmp_path: Path):
        case = {"artifacts": []}
        result = _load_artifact_contents(case, tmp_path / "cases.yaml")
        assert result == ""

    def test_missing_file(self, tmp_path: Path):
        case = {"artifacts": ["nonexistent.csv"]}
        result = _load_artifact_contents(case, tmp_path / "cases.yaml")
        assert result == ""

    def test_loads_existing_file(self, tmp_path: Path):
        artifact = tmp_path / "data.csv"
        artifact.write_text("col1,col2\n1,2", encoding="utf-8")
        case = {"artifacts": ["data.csv"]}
        result = _load_artifact_contents(case, tmp_path / "cases.yaml")
        assert "col1,col2" in result
        assert "data.csv" in result

    def test_truncates_large_file(self, tmp_path: Path):
        artifact = tmp_path / "large.csv"
        artifact.write_text("x" * 30000, encoding="utf-8")
        case = {"artifacts": ["large.csv"]}
        result = _load_artifact_contents(case, tmp_path / "cases.yaml")
        assert "[truncated]" in result

    def test_multiple_artifacts(self, tmp_path: Path):
        (tmp_path / "a.csv").write_text("data_a", encoding="utf-8")
        (tmp_path / "b.csv").write_text("data_b", encoding="utf-8")
        case = {"artifacts": ["a.csv", "b.csv"]}
        result = _load_artifact_contents(case, tmp_path / "cases.yaml")
        assert "data_a" in result
        assert "data_b" in result


# ── _load_completed_keys ─────────────────────────────────────


class TestLoadCompletedKeys:
    """Test JSONL resume functionality."""

    def test_empty_file(self, tmp_path: Path):
        jsonl = tmp_path / "judge.jsonl"
        result = _load_completed_keys(jsonl)
        assert result == set()

    def test_loads_completed(self, tmp_path: Path):
        jsonl = tmp_path / "judge.jsonl"
        jsonl.write_text(
            json.dumps({"case_id": "F01", "model": "m1", "judge_model": "MiniMax-M3", "weighted_score": 3.5})
            + "\n"
        )
        result = _load_completed_keys(jsonl)
        assert "F01:m1:MiniMax-M3" in result

    def test_skips_failed(self, tmp_path: Path):
        jsonl = tmp_path / "judge.jsonl"
        jsonl.write_text(
            json.dumps({"case_id": "F01", "model": "m1", "judge_model": "MiniMax-M3", "weighted_score": 0})
            + "\n"
        )
        result = _load_completed_keys(jsonl)
        assert "F01:m1:MiniMax-M3" not in result

    def test_handles_malformed_lines(self, tmp_path: Path):
        jsonl = tmp_path / "judge.jsonl"
        jsonl.write_text(
            "not json\n"
            + json.dumps({"case_id": "F02", "model": "m1", "judge_model": "MiniMax-M3", "weighted_score": 2.0})
            + "\n"
        )
        result = _load_completed_keys(jsonl)
        assert "F02:m1:MiniMax-M3" in result


# ── _finance_judge_one ────────────────────────────────────────


class TestFinanceJudgeOne:
    """Test single pair judging with mock adapter."""

    def _make_adapter(self, response_content: str) -> MagicMock:
        adapter = MagicMock()
        adapter.chat.return_value = AdapterResponse(
            model="MiniMax-M3",
            content=response_content,
            input_tokens=100,
            output_tokens=50,
            latency_ms=1000,
        )
        return adapter

    def test_successful_evaluation(self):
        judge_response = json.dumps({
            "numeric_policy_correctness": 4,
            "evidence_grounding": 3,
            "hallucination_control": 5,
            "business_usability": 4,
            "json_structure_quality": 4,
            "rule_score_disagreement": "agree",
            "red_flags": [],
            "comment": "Good analysis",
        })
        adapter = self._make_adapter(judge_response)
        case = {"id": "F01", "category": "TABLE_CALCULATION"}

        result = _finance_judge_one(
            adapter, "MiniMax-M3", case, "deepseek-v4-flash",
            "model output", False, 0.75, {"amount_accuracy": 0.8}, "",
        )

        assert result.case_id == "F01"
        assert result.model == "deepseek-v4-flash"
        assert result.judge_model == "MiniMax-M3"
        assert result.task_type == "FINANCE_DATA_PROCESSING"
        assert result.dimensions["numeric_policy_correctness"] == 4.0
        assert result.normalized_score > 0
        assert result.rule_score == 0.75
        assert result.rule_score_disagreement == "agree"
        assert result.red_flags == []
        assert result.comment == "Good analysis"

    def test_policy_qa_uses_correct_task_type(self):
        judge_response = json.dumps({
            "policy_accuracy": 4,
            "evidence_grounding": 3,
            "hallucination_control": 5,
            "business_usability": 4,
            "json_structure_quality": 4,
            "comment": "ok",
        })
        adapter = self._make_adapter(judge_response)
        case = {"id": "F10", "category": "POLICY_QA"}

        result = _finance_judge_one(
            adapter, "MiniMax-M3", case, "model1",
            "output", False, 0.5, {}, "",
        )

        assert result.task_type == "FINANCE_POLICY_QA"
        assert "policy_accuracy" in result.dimensions

    def test_invalid_red_flags_filtered(self):
        judge_response = json.dumps({
            "numeric_policy_correctness": 3,
            "evidence_grounding": 3,
            "hallucination_control": 3,
            "business_usability": 3,
            "json_structure_quality": 3,
            "red_flags": ["hallucinated_data", "invalid_flag", "weak_evidence"],
            "comment": "has issues",
        })
        adapter = self._make_adapter(judge_response)
        case = {"id": "F02", "category": "TABLE_CALCULATION"}

        result = _finance_judge_one(
            adapter, "MiniMax-M3", case, "model1",
            "output", False, 0.5, {}, "",
        )

        assert "hallucinated_data" in result.red_flags
        assert "weak_evidence" in result.red_flags
        assert "invalid_flag" not in result.red_flags

    def test_invalid_disagreement_defaults_to_unclear(self):
        judge_response = json.dumps({
            "numeric_policy_correctness": 3,
            "evidence_grounding": 3,
            "hallucination_control": 3,
            "business_usability": 3,
            "json_structure_quality": 3,
            "rule_score_disagreement": "invalid_value",
            "comment": "ok",
        })
        adapter = self._make_adapter(judge_response)
        case = {"id": "F03", "category": "TABLE_CALCULATION"}

        result = _finance_judge_one(
            adapter, "MiniMax-M3", case, "model1",
            "output", False, 0.5, {}, "",
        )

        assert result.rule_score_disagreement == "unclear"

    def test_empty_response_returns_failure(self):
        adapter = self._make_adapter("")
        case = {"id": "F04", "category": "TABLE_CALCULATION"}

        # Patch MAX_RETRIES to 1 to speed up test
        with patch("airouter.engine.benchmark.finance_judge.MAX_RETRIES", 1):
            result = _finance_judge_one(
                adapter, "MiniMax-M3", case, "model1",
                "output", False, 0.5, {}, "",
            )

        assert result.weighted_score == 0
        assert "empty response" in result.comment or "starvation" in result.comment

    def test_json_parse_failure_returns_failure(self):
        adapter = self._make_adapter("this is not json at all")
        case = {"id": "F05", "category": "TABLE_CALCULATION"}

        with patch("airouter.engine.benchmark.finance_judge.MAX_RETRIES", 1):
            result = _finance_judge_one(
                adapter, "MiniMax-M3", case, "model1",
                "output", False, 0.5, {}, "",
            )

        assert result.weighted_score == 0
        assert "JSON parse failed" in result.comment

    def test_model_truncated_flag_passed_through(self):
        judge_response = json.dumps({
            "numeric_policy_correctness": 3,
            "evidence_grounding": 3,
            "hallucination_control": 3,
            "business_usability": 3,
            "json_structure_quality": 3,
            "comment": "ok",
        })
        adapter = self._make_adapter(judge_response)
        case = {"id": "F06", "category": "TABLE_CALCULATION"}

        result = _finance_judge_one(
            adapter, "MiniMax-M3", case, "model1",
            "output", True, 0.5, {}, "",
        )

        assert result.model_truncated is True

    def test_usage_populated(self):
        judge_response = json.dumps({
            "numeric_policy_correctness": 4,
            "evidence_grounding": 4,
            "hallucination_control": 4,
            "business_usability": 4,
            "json_structure_quality": 4,
            "comment": "ok",
        })
        adapter = self._make_adapter(judge_response)
        case = {"id": "F07", "category": "TABLE_CALCULATION"}

        result = _finance_judge_one(
            adapter, "MiniMax-M3", case, "model1",
            "output", False, 0.5, {}, "",
        )

        assert result.usage["prompt_tokens"] == 100
        assert result.usage["completion_tokens"] == 50


# ── Finance rubric tests (judge_prompts) ──────────────────────


class TestFinanceRubric:
    """Test finance-specific rubric in judge_prompts."""

    def test_data_processing_weights_sum_to_one(self):
        from airouter.engine.benchmark.judge_prompts import get_dimensions
        dims = get_dimensions("FINANCE_DATA_PROCESSING")
        assert abs(sum(dims.values()) - 1.0) < 1e-6

    def test_policy_qa_weights_sum_to_one(self):
        from airouter.engine.benchmark.judge_prompts import get_dimensions
        dims = get_dimensions("FINANCE_POLICY_QA")
        assert abs(sum(dims.values()) - 1.0) < 1e-6

    def test_data_processing_has_all_rubric_text(self):
        from airouter.engine.benchmark.judge_prompts import _RUBRIC_TEXT, get_dimensions
        dims = get_dimensions("FINANCE_DATA_PROCESSING")
        for dim in dims:
            assert dim in _RUBRIC_TEXT, f"Missing rubric for {dim}"

    def test_policy_qa_has_all_rubric_text(self):
        from airouter.engine.benchmark.judge_prompts import _RUBRIC_TEXT, get_dimensions
        dims = get_dimensions("FINANCE_POLICY_QA")
        for dim in dims:
            assert dim in _RUBRIC_TEXT, f"Missing rubric for {dim}"

    def test_finance_json_format_contains_disagreement(self):
        from airouter.engine.benchmark.judge_prompts import get_finance_json_format
        fmt = get_finance_json_format("FINANCE_DATA_PROCESSING")
        assert "rule_score_disagreement" in fmt

    def test_finance_json_format_contains_red_flags(self):
        from airouter.engine.benchmark.judge_prompts import get_finance_json_format
        fmt = get_finance_json_format("FINANCE_DATA_PROCESSING")
        assert "red_flags" in fmt

    def test_valid_red_flags_not_empty(self):
        assert len(VALID_RED_FLAGS) > 0

    def test_get_finance_judge_task_type_policy_qa(self):
        from airouter.engine.benchmark.judge_prompts import get_finance_judge_task_type
        assert get_finance_judge_task_type("POLICY_QA") == "FINANCE_POLICY_QA"

    def test_get_finance_judge_task_type_other(self):
        from airouter.engine.benchmark.judge_prompts import get_finance_judge_task_type
        assert get_finance_judge_task_type("TABLE_CALCULATION") == "FINANCE_DATA_PROCESSING"
        assert get_finance_judge_task_type("REIMBURSEMENT_AUDIT") == "FINANCE_DATA_PROCESSING"
