"""Unit tests for finance_report module."""

from __future__ import annotations

import pytest

from airouter.engine.benchmark.finance_report import (
    _interpret_low_score_case,
    _summarize_expected_answer,
)
from airouter.engine.benchmark.finance_schemas import FinanceCaseResult, FinanceSummary


@pytest.fixture
def mock_summary() -> FinanceSummary:
    """Create a minimal FinanceSummary for testing."""
    return FinanceSummary(
        run_id="test_run",
        total_cases=10,
        total_models=2,
        total_api_calls=20,
        total_input_tokens=1000,
        total_output_tokens=500,
        total_cost_cny=1.0,
        total_latency_ms=5000,
        model_scores={"model1": 0.8, "model2": 0.7},
        category_model_matrix={},
        category_summaries=[],
        completed_pairs=20,
        failed_pairs=0,
        case_results=[],
        case_catalog=[
            {
                "id": "FIN-001",
                "category": "REIMBURSEMENT_AUDIT",
                "expected_answer": {
                    "amounts": {"approved_amount_cny": 550, "rejected_amount_cny": 52},
                    "decision": "partial_approve",
                    "required_findings": ["hotel_over_limit"],
                },
                "amount_applicable": True,
            }
        ],
    )


def _make_result(
    case_id: str = "FIN-001",
    overall_score: float = 0.5,
    dimension_scores: dict | None = None,
    response_metadata: dict | None = None,
) -> FinanceCaseResult:
    """Helper to create a FinanceCaseResult."""
    return FinanceCaseResult(
        case_id=case_id,
        model="model1",
        status="success",
        category="REIMBURSEMENT_AUDIT",
        scoring_type="finance_reimbursement",
        overall_score=overall_score,
        dimension_scores=dimension_scores or {},
        response_metadata=response_metadata or {},
    )


class TestSummarizeExpectedAnswer:
    """Test _summarize_expected_answer function."""

    def test_with_amounts(self):
        expected = {"amounts": {"approved_amount_cny": 550, "rejected_amount_cny": 52}}
        result = _summarize_expected_answer(expected)
        assert "approved_amount_cny=550" in result
        assert "rejected_amount_cny=52" in result

    def test_with_decision(self):
        expected = {"decision": "partial_approve"}
        result = _summarize_expected_answer(expected)
        assert "decision=partial_approve" in result

    def test_with_required_findings(self):
        expected = {"required_findings": ["hotel_over_limit", "meal_over_limit"]}
        result = _summarize_expected_answer(expected)
        assert "hotel_over_limit" in result
        assert "meal_over_limit" in result

    def test_with_top_item(self):
        expected = {"top_item": {"dept": "Sales", "amount_cny": 500}}
        result = _summarize_expected_answer(expected)
        assert "top_item" in result
        assert "Sales" in result

    def test_with_top_items(self):
        expected = {"top_items": [{"dept": "A", "total": 100}, {"dept": "B", "total": 50}]}
        result = _summarize_expected_answer(expected)
        assert "top_items" in result

    def test_empty(self):
        result = _summarize_expected_answer({})
        assert result == ""

    def test_combined(self):
        expected = {
            "decision": "approve",
            "amounts": {"total_cny": 1000},
            "required_findings": ["valid_receipt"],
        }
        result = _summarize_expected_answer(expected)
        assert "decision=approve" in result
        assert "total_cny=1000" in result
        assert "valid_receipt" in result


class TestInterpretLowScoreCase:
    """Test _interpret_low_score_case multi-label classification."""

    def test_structural_non_compliance(self, mock_summary):
        """Test JSON validity < 0.7 triggers structural non-compliance."""
        result = _make_result(
            dimension_scores={"json_validity": 0.5, "amount_accuracy": 0.8},
        )
        interpretation = _interpret_low_score_case(mock_summary, result)
        assert interpretation["primary_type"] == "结构化输出不合规"
        assert "JSON 格式" in interpretation["explanation"]

    def test_amount_accuracy_with_high_findings(self, mock_summary):
        """Test amount_accuracy < 0.5 but high findings = schema mismatch."""
        result = _make_result(
            dimension_scores={
                "amount_accuracy": 0.3,
                "finding_recall": 0.8,
                "evidence_quality": 0.7,
            },
        )
        interpretation = _interpret_low_score_case(mock_summary, result)
        # Should be schema mismatch, not real business error
        assert interpretation["primary_type"] in ["结构化输出不合规", "汇总口径不匹配"]
        assert "输出口径与评分 schema 不一致" in interpretation["explanation"]

    def test_real_business_error(self, mock_summary):
        """Test all dimensions low = real business error."""
        result = _make_result(
            dimension_scores={
                "amount_accuracy": 0.2,
                "finding_recall": 0.3,
                "evidence_quality": 0.3,
                "decision_accuracy": 0.4,
            },
        )
        interpretation = _interpret_low_score_case(mock_summary, result)
        assert interpretation["primary_type"] == "真实业务错误"
        assert "多维度表现均较差" in interpretation["explanation"]

    def test_finding_recall_low(self, mock_summary):
        """Test finding_recall < 0.5 triggers finding missing (when decision/evidence are also low)."""
        result = _make_result(
            dimension_scores={
                "finding_recall": 0.4,
                "decision_accuracy": 0.5,  # Low enough to not trigger cross-reference
                "evidence_quality": 0.5,
            },
        )
        interpretation = _interpret_low_score_case(mock_summary, result)
        assert "关键发现遗漏" in interpretation["primary_type"] or "关键发现遗漏" in interpretation["secondary_types"]

    def test_finding_recall_cross_reference(self, mock_summary):
        """Test finding_recall < 0.5 with high decision/evidence triggers matcher review."""
        result = _make_result(
            dimension_scores={
                "finding_recall": 0.4,
                "decision_accuracy": 0.9,
                "evidence_quality": 0.8,
            },
        )
        interpretation = _interpret_low_score_case(mock_summary, result)
        assert "评分器疑似偏严" in interpretation["primary_type"] or "评分器疑似偏严" in interpretation["secondary_types"]
        assert "finding matcher 需复核" in interpretation["secondary_types"]
        assert "identifier 与自然语言表达不一致" in interpretation["explanation"]

    def test_decision_accuracy_low(self, mock_summary):
        """Test decision_accuracy < 0.5 triggers decision error."""
        result = _make_result(
            dimension_scores={"decision_accuracy": 0.3},
        )
        interpretation = _interpret_low_score_case(mock_summary, result)
        assert "决策判断错误" in interpretation["primary_type"] or "决策判断错误" in interpretation["secondary_types"]

    def test_evidence_quality_low(self, mock_summary):
        """Test evidence_quality < 0.5 triggers evidence weak."""
        result = _make_result(
            dimension_scores={"evidence_quality": 0.3},
        )
        interpretation = _interpret_low_score_case(mock_summary, result)
        assert "证据不足" in interpretation["primary_type"] or "证据不足" in interpretation["secondary_types"]

    def test_reasoning_starved(self, mock_summary):
        """Test reasoning_starved flag triggers token starvation."""
        result = _make_result(
            dimension_scores={},
            response_metadata={"reasoning_starved": True},
        )
        interpretation = _interpret_low_score_case(mock_summary, result)
        assert "推理 token 饥饿" in interpretation["primary_type"] or "推理 token 饥饿" in interpretation["secondary_types"]

    def test_multi_label(self, mock_summary):
        """Test multiple issues are captured."""
        result = _make_result(
            dimension_scores={
                "json_validity": 0.6,
                "finding_recall": 0.4,
                "evidence_quality": 0.3,
            },
        )
        interpretation = _interpret_low_score_case(mock_summary, result)
        # Should have multiple labels
        total_labels = 1 + len(interpretation["secondary_types"])
        assert total_labels >= 2

    def test_moderate_amount_accuracy(self, mock_summary):
        """Test amount_accuracy 0.5-0.8 triggers lenient scorer."""
        result = _make_result(
            dimension_scores={"amount_accuracy": 0.6},
        )
        interpretation = _interpret_low_score_case(mock_summary, result)
        assert "评分器疑似偏严" in interpretation["primary_type"] or "评分器疑似偏严" in interpretation["secondary_types"]

    def test_fallback_type(self, mock_summary):
        """Test default fallback when no clear issue."""
        result = _make_result(
            dimension_scores={"json_validity": 0.9, "amount_accuracy": 0.9},
        )
        interpretation = _interpret_low_score_case(mock_summary, result)
        assert interpretation["primary_type"] == "题目口径需澄清"


class TestJudgeAppendixUsesRescoredScores:
    """Regression test: Judge appendix must use rescored scores from summary,
    not embedded jr.rule_score."""

    def test_rule_too_high_uses_rescored_not_embedded(self):
        """summary rescored=0.85, Judge embedded=0.60, Judge score=0.55.

        With rescored: rule=0.85 >= 0.8, judge=0.55 < 0.6 → rule_too_high.
        With embedded: rule=0.60, judge=0.55, |delta|=0.05 → agree (WRONG).

        Report must show rule_too_high and display 0.850.
        """
        from airouter.engine.benchmark.finance_report import generate_finance_report
        from airouter.engine.benchmark.finance_schemas import (
            FinanceCaseResult,
            FinanceSummary,
        )
        from airouter.engine.benchmark.schemas import JudgeResult, JudgeSummary

        # Build summary with rescored score = 0.85
        case_result = FinanceCaseResult(
            case_id="FIN-001",
            model="model-a",
            status="success",
            category="REIMBURSEMENT_AUDIT",
            scoring_type="finance_reimbursement",
            overall_score=0.85,  # rescored
            dimension_scores={},
            response_metadata={},
        )
        summary = FinanceSummary(
            run_id="test",
            total_cases=1,
            total_models=1,
            total_api_calls=1,
            total_input_tokens=100,
            total_output_tokens=50,
            total_cost_cny=0.01,
            total_latency_ms=1000,
            model_scores={"model-a": 0.85},
            category_model_matrix={},
            category_summaries=[],
            completed_pairs=1,
            failed_pairs=0,
            case_results=[case_result],
            case_catalog=[],
        )

        # Build JudgeResult with embedded rule_score=0.60, normalized_score=0.55
        jr = JudgeResult(
            case_id="FIN-001",
            model="model-a",
            judge_model="TestJudge",
            task_type="finance_reimbursement",
            dimensions={"numeric_policy_correctness": 3.0},
            weighted_score=2.75,
            normalized_score=0.55,
            comment="test comment",
            rule_score=0.60,  # embedded — would give "agree"
            red_flags=[],
        )
        js = JudgeSummary(
            judge_model="TestJudge",
            total_evaluations=1,
            successful=1,
            failed=0,
            results=[jr],
        )

        report = generate_finance_report(summary, judge_results=js)

        # Must classify as rule_too_high (using rescored 0.85, not embedded 0.60)
        assert "规则评分偏高" in report
        # Must display rescored score 0.850, not embedded 0.600
        assert "0.850" in report
        # Must NOT show the embedded score as the rule score
        assert "0.600" not in report
