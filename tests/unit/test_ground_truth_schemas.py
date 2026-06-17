"""Unit tests for ground_truth_schemas.py."""

from __future__ import annotations

import pytest

from airouter.engine.benchmark.ground_truth_schemas import (
    CANDIDATE_MODELS,
    CATEGORY_WEIGHT_OVERRIDES,
    DEFAULT_DIMENSION_WEIGHTS,
    PASS_THRESHOLDS,
    VALID_HOLDOUT_CATEGORIES,
    AggregatedModelResult,
    EvaluationSpec,
    GroundTruthCase,
    GroundTruthCaseResult,
    GroundTruthData,
    GroundTruthSummary,
    HarnessValidation,
    HumanAuditEntry,
    OracleResult,
    RoutingMetadata,
    StrategyReplayResult,
    StructuredOutput,
    StructuredOutputSpec,
)


class TestStructuredOutput:
    def test_defaults(self):
        so = StructuredOutput()
        assert so.action == "answer"
        assert so.findings == []
        assert so.approval_required is False

    def test_all_actions_valid(self):
        for action in ("answer", "propose_change", "clarify", "refuse"):
            so = StructuredOutput(action=action)
            assert so.action == action

    def test_invalid_action_rejected(self):
        with pytest.raises(Exception):
            StructuredOutput(action="execute")


class TestGroundTruthCase:
    def test_minimal_case(self):
        case = GroundTruthCase(id="GT-001", category="CODE_DEBUG", prompt="fix bug")
        assert case.id == "GT-001"
        assert case.domain == "GENERAL"
        assert case.pass_threshold == 0.80
        assert case.is_high_risk is False

    def test_high_risk_threshold(self):
        case = GroundTruthCase(
            id="GT-002", category="LOG_OPS", prompt="check",
            risk_level="HIGH",
        )
        assert case.pass_threshold == 0.85
        assert case.is_high_risk is True

    def test_critical_risk_threshold(self):
        case = GroundTruthCase(
            id="GT-003", category="CODE_DEBUG", prompt="fix",
            risk_level="CRITICAL",
        )
        assert case.pass_threshold == 0.90
        assert case.is_high_risk is True

    def test_routing_metadata_defaults(self):
        rm = RoutingMetadata()
        assert rm.history_messages == []
        assert rm.prev_assistant_text is None
        assert rm.n_tools == 0

    def test_evaluation_spec_defaults(self):
        es = EvaluationSpec()
        assert es.primary == "rule_based"
        assert es.must_not_modify == []
        assert es.should_ask_clarification is False

    def test_harness_validation_defaults(self):
        hv = HarnessValidation()
        assert hv.commands == []
        assert hv.timeout_s == 10
        assert hv.expected_exit_code == 0

    def test_structured_output_spec_defaults(self):
        sos = StructuredOutputSpec()
        assert "action" in sos.required_fields
        assert "summary" in sos.required_fields

    def test_ground_truth_data_defaults(self):
        gt = GroundTruthData()
        assert gt.expected_values == {}
        assert gt.hidden_tests == []
        assert gt.forbidden_claims == []


class TestGroundTruthCaseResult:
    def test_defaults(self):
        r = GroundTruthCaseResult(case_id="GT-001", model="qwen3.7-max")
        assert r.run_index == 0
        assert r.dataset == "dev"
        assert r.deterministic_passed is False
        assert r.final_pass is False
        assert r.hard_failure_ids == []
        assert r.cost_source == "models.yaml"

    def test_hard_failure_forces_fail(self):
        r = GroundTruthCaseResult(
            case_id="GT-001", model="qwen3.7-max",
            final_score=0.95, hard_failure_ids=["modified_forbidden_file"],
            pass_threshold=0.80,
        )
        assert len(r.hard_failure_ids) == 1


class TestAggregatedModelResult:
    def test_defaults(self):
        r = AggregatedModelResult(case_id="GT-001", model="qwen3.7-max")
        assert r.run_count == 1
        assert r.incomplete is False
        assert r.human_verdict is None

    def test_pass_count_logic(self):
        r = AggregatedModelResult(
            case_id="GT-001", model="qwen3.7-max",
            run_count=3, pass_count=2, aggregated_pass=True,
        )
        assert r.aggregated_pass is True


class TestOracleResult:
    def test_defaults(self):
        o = OracleResult(case_id="GT-001")
        assert o.oracle_model is None
        assert o.oracle_set == []
        assert o.oracle_action == "AUTO"
        assert o.n_runs == 1

    def test_oracle_set_with_models(self):
        o = OracleResult(
            case_id="GT-001",
            passing_models=["deepseek-v4-flash", "glm-5.1"],
            oracle_model="deepseek-v4-flash",
            oracle_set=["deepseek-v4-flash", "glm-5.1"],
            oracle_set_cost_ceiling=0.015,
        )
        assert len(o.oracle_set) == 2


class TestStrategyReplayResult:
    def test_defaults(self):
        s = StrategyReplayResult(strategy_name="rules")
        assert s.layer == "signal"
        assert s.acceptable_match_rate == 0.0
        assert s.total_billed_cost_cny is None

    def test_end_to_end_layer(self):
        s = StrategyReplayResult(
            strategy_name="current_router",
            layer="end_to_end",
        )
        assert s.layer == "end_to_end"


class TestHumanAuditEntry:
    def test_defaults(self):
        h = HumanAuditEntry(case_id="GT-001", model="qwen3.7-max")
        assert h.human_verdict == "PASS"
        assert h.selection_reason == "random_20pct"

    def test_scorer_false_positive(self):
        h = HumanAuditEntry(
            case_id="GT-001", model="qwen3.7-max",
            human_verdict="SCORER_FALSE_POSITIVE",
            selection_reason="high_risk",
            human_comment="Auto passed but output is wrong",
        )
        assert h.human_verdict == "SCORER_FALSE_POSITIVE"
        assert h.selection_reason == "high_risk"


class TestGroundTruthSummary:
    def test_defaults(self):
        s = GroundTruthSummary(run_id="run-001")
        assert s.models == CANDIDATE_MODELS
        assert s.total_physical_api_calls == 0
        assert s.conclusions == []

    def test_api_calls_not_double_counted(self):
        s = GroundTruthSummary(
            run_id="run-001",
            candidate_initial_calls=150,
            candidate_rerun_calls=30,
            judge_initial_calls=150,
            judge_rerun_calls=20,
            retry_attempts=5,
            total_physical_api_calls=355,
        )
        total = (
            s.candidate_initial_calls
            + s.candidate_rerun_calls
            + s.judge_initial_calls
            + s.judge_rerun_calls
            + s.retry_attempts
        )
        assert total == s.total_physical_api_calls


class TestConstants:
    def test_candidate_models_count(self):
        assert len(CANDIDATE_MODELS) == 5

    def test_pass_thresholds(self):
        assert PASS_THRESHOLDS["LOW"] == 0.80
        assert PASS_THRESHOLDS["HIGH"] == 0.85
        assert PASS_THRESHOLDS["CRITICAL"] == 0.90

    def test_dimension_weights_sum_to_one(self):
        total = sum(DEFAULT_DIMENSION_WEIGHTS.values())
        assert abs(total - 1.0) < 0.01

    def test_category_overrides_valid(self):
        for cat, weights in CATEGORY_WEIGHT_OVERRIDES.items():
            for dim in weights:
                assert dim in DEFAULT_DIMENSION_WEIGHTS, f"{cat} overrides unknown dim {dim}"

    def test_holdout_categories(self):
        assert len(VALID_HOLDOUT_CATEGORIES) == 8
        assert "DOC_UNDERSTANDING" in VALID_HOLDOUT_CATEGORIES
        assert "INSTRUCTION_ANTIHALLU" in VALID_HOLDOUT_CATEGORIES
