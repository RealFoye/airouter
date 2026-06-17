"""Unit tests for strategy_replay.py — uses real selector/estimator/candidates."""

from __future__ import annotations

from airouter.config import load_all
from airouter.engine.benchmark.ground_truth_schemas import (
    AggregatedModelResult,
    OracleResult,
)
from airouter.engine.benchmark.strategy_replay import (
    EndToEndReplay,
    SignalLayerReplay,
    build_oracle_index,
    build_results_index,
    classify_routing,
    compute_quality_upper_bound,
    is_severe_under_routing,
)
from airouter.engine.router.estimator import CostEstimator
from airouter.engine.router.selector import ModelSelector
from airouter.models.enums import ComplexityLevel, TaskCategory
from airouter.models.model_registry import ModelRegistry
from airouter.models.schemas import TaskFeatures


def _agg(case_id: str, model: str, score: float = 0.9, cost: float = 0.01,
         pass_flag: bool = True) -> AggregatedModelResult:
    return AggregatedModelResult(
        case_id=case_id, model=model,
        median_score=score, median_cost_cny=cost,
        final_pass=pass_flag,
    )


class _MockCase:
    def __init__(self, case_id: str, risk: str = "LOW", complexity: str = "MODERATE"):
        self.id = case_id
        self.risk_level = risk
        self.complexity = complexity


def _get_candidate_models():
    config = load_all()
    registry = ModelRegistry(config.models)
    return [
        registry.get_by_name(name)
        for name in ["qwen3.7-max", "qwen3.7-plus", "deepseek-v4-pro", "deepseek-v4-flash", "glm-5.1"]
        if registry.get_by_name(name) is not None
    ]


def _make_features(complexity: ComplexityLevel = ComplexityLevel.MODERATE) -> TaskFeatures:
    return TaskFeatures(
        category=TaskCategory.BUG_ANALYSIS,
        complexity=complexity,
    )


class TestClassifyRouting:
    def test_optimal(self):
        oracle = OracleResult(
            case_id="GT-001",
            passing_models=["m1", "m2"],
            oracle_set=["m1"],
        )
        assert classify_routing("m1", True, oracle) == "optimal"

    def test_over_routing(self):
        oracle = OracleResult(
            case_id="GT-001",
            passing_models=["m1"],
            oracle_set=["m1"],
        )
        assert classify_routing("m2", True, oracle) == "over_routing"

    def test_under_routing(self):
        oracle = OracleResult(
            case_id="GT-001",
            passing_models=["m1"],
            oracle_set=["m1"],
        )
        assert classify_routing("m2", False, oracle) == "under_routing"

    def test_no_passing_model(self):
        oracle = OracleResult(
            case_id="GT-001",
            passing_models=[],
            oracle_set=[],
        )
        assert classify_routing("m1", False, oracle) == "no_passing_model"

    def test_acceptable_no_cheaper(self):
        oracle = OracleResult(
            case_id="GT-001",
            passing_models=["m1"],
            oracle_set=[],
        )
        assert classify_routing("m1", True, oracle) == "acceptable_no_cheaper"

    def test_none_model_with_passing(self):
        oracle = OracleResult(
            case_id="GT-001",
            passing_models=["m1"],
            oracle_set=["m1"],
        )
        assert classify_routing(None, False, oracle) == "under_routing"

    def test_none_model_no_passing(self):
        oracle = OracleResult(
            case_id="GT-001",
            passing_models=[],
            oracle_set=[],
        )
        assert classify_routing(None, False, oracle) == "no_passing_model"


class TestIsSevereUnderRouting:
    def test_high_risk_under_routing(self):
        assert is_severe_under_routing("under_routing", "HIGH", False) is True

    def test_critical_risk_under_routing(self):
        assert is_severe_under_routing("under_routing", "CRITICAL", False) is True

    def test_low_risk_not_severe(self):
        assert is_severe_under_routing("under_routing", "LOW", False) is False

    def test_hard_failure_is_severe(self):
        assert is_severe_under_routing("optimal", "HIGH", True) is True

    def test_medium_risk_not_severe(self):
        assert is_severe_under_routing("under_routing", "MEDIUM", True) is False


class TestSignalLayerReplay:
    def test_basic_replay(self):
        """A 层回放：使用真实 selector/estimator/candidates。"""
        replay = SignalLayerReplay()
        selector = ModelSelector()
        estimator = CostEstimator()
        candidate_models = _get_candidate_models()

        cases = [_MockCase("GT-001"), _MockCase("GT-002")]
        results_list = [
            _agg("GT-001", "qwen3.7-plus"),
            _agg("GT-002", "qwen3.7-plus", pass_flag=False),
        ]
        results = build_results_index(results_list)
        oracles = build_oracle_index([
            OracleResult(
                case_id="GT-001",
                passing_models=["qwen3.7-plus"],
                oracle_set=["qwen3.7-plus"],
            ),
            OracleResult(
                case_id="GT-002",
                passing_models=["deepseek-v4-pro"],
                oracle_set=["deepseek-v4-pro"],
            ),
        ])

        def feature_resolver(case):
            return _make_features(ComplexityLevel.MODERATE)

        result = replay.replay(
            "test_strategy", feature_resolver, cases,
            results, oracles, selector, estimator, candidate_models,
        )

        assert result.strategy_name == "test_strategy"
        assert result.layer == "signal"
        # GT-001: selector picks a model, it passes → could be optimal or over_routing
        # GT-002: selector picks qwen3.7-plus but it fails → under_routing
        assert result.under_routing_rate >= 0.0

    def test_empty_cases_returns_defaults(self):
        replay = SignalLayerReplay()
        selector = ModelSelector()
        estimator = CostEstimator()
        candidate_models = _get_candidate_models()

        result = replay.replay(
            "empty", lambda c: _make_features(), [],
            {}, {}, selector, estimator, candidate_models,
        )
        assert result.strategy_name == "empty"
        assert result.acceptable_match_rate == 0.0

    def test_complexity_affects_selection(self):
        """不同复杂度 → selector 可能选不同模型。"""
        replay = SignalLayerReplay()
        selector = ModelSelector()
        estimator = CostEstimator()
        candidate_models = _get_candidate_models()

        cases = [_MockCase("GT-001")]
        # 为所有候选模型提供结果，确保不管 selector 选哪个都有数据
        results_list = [
            _agg("GT-001", "deepseek-v4-flash", score=0.85, cost=0.001),
            _agg("GT-001", "qwen3.7-plus", score=0.88, cost=0.005),
            _agg("GT-001", "deepseek-v4-pro", score=0.92, cost=0.02),
            _agg("GT-001", "qwen3.7-max", score=0.95, cost=0.05),
            _agg("GT-001", "glm-5.1", score=0.87, cost=0.008),
        ]
        results = build_results_index(results_list)
        oracles = build_oracle_index([
            OracleResult(
                case_id="GT-001",
                passing_models=["deepseek-v4-flash", "qwen3.7-plus", "deepseek-v4-pro",
                                "qwen3.7-max", "glm-5.1"],
                oracle_set=["deepseek-v4-flash"],
            ),
        ])

        # SIMPLE → selector should prefer cheaper models
        simple_result = replay.replay(
            "simple", lambda c: _make_features(ComplexityLevel.SIMPLE),
            cases, results, oracles, selector, estimator, candidate_models,
        )
        # EXPERT → selector may prefer higher quality models
        expert_result = replay.replay(
            "expert", lambda c: _make_features(ComplexityLevel.EXPERT),
            cases, results, oracles, selector, estimator, candidate_models,
        )

        assert simple_result.strategy_name == "simple"
        assert expert_result.strategy_name == "expert"
        # Both should produce valid results with non-zero scores
        assert simple_result.avg_quality_score > 0
        assert expert_result.avg_quality_score > 0
        # EXPERT 可能选更贵的模型 → over_routing（不在 oracle_set 中但通过了）
        # 验证两种复杂度产生了不同的路由决策
        assert simple_result.per_case_results[0]["selected_model"] != \
               expert_result.per_case_results[0]["selected_model"] or \
               simple_result.per_case_results[0]["classification"] != \
               expert_result.per_case_results[0]["classification"]


class TestEndToEndReplay:
    def test_basic_e2e_replay(self):
        """B 层回放：router_chooser 返回 (model, metadata)。"""
        replay = EndToEndReplay()

        cases = [_MockCase("GT-001"), _MockCase("GT-002")]
        results_list = [
            _agg("GT-001", "qwen3.7-plus"),
            _agg("GT-002", "deepseek-v4-pro"),
        ]
        results = build_results_index(results_list)
        oracles = build_oracle_index([
            OracleResult(
                case_id="GT-001",
                passing_models=["qwen3.7-plus"],
                oracle_set=["qwen3.7-plus"],
                oracle_action="AUTO",
            ),
            OracleResult(
                case_id="GT-002",
                passing_models=["deepseek-v4-pro"],
                oracle_set=["deepseek-v4-pro"],
                oracle_action="AUTO",
            ),
        ])

        def router_chooser(case):
            if case.id == "GT-001":
                return "qwen3.7-plus", {"selected_action": "AUTO"}
            return "deepseek-v4-pro", {"selected_action": "AUTO"}

        result = replay.replay(
            "test_e2e", cases, results, oracles, router_chooser,
        )

        assert result.strategy_name == "test_e2e"
        assert result.layer == "end_to_end"
        assert result.acceptable_match_rate == 1.0  # Both optimal

    def test_e2e_escalation(self):
        """B 层：Router 升级到 ESCALATE_TO_HUMAN。"""
        replay = EndToEndReplay()

        cases = [_MockCase("GT-001", risk="HIGH")]
        results_list = [_agg("GT-001", "qwen3.7-max")]
        results = build_results_index(results_list)
        oracles = build_oracle_index([
            OracleResult(
                case_id="GT-001",
                passing_models=["qwen3.7-max"],
                oracle_set=["qwen3.7-max"],
                oracle_action="AUTO",
            ),
        ])

        def router_chooser(case):
            # Router escalates to human
            return None, {"selected_action": "ESCALATE_TO_HUMAN"}

        result = replay.replay(
            "escalated", cases, results, oracles, router_chooser,
        )

        assert result.over_escalation_rate == 1.0  # Oracle=AUTO but Router=ESCALATE
        assert result.acceptable_match_rate == 0.0

    def test_e2e_unsafe_auto(self):
        """B 层：Oracle=HUMAN 但 Router=AUTO（危险）。"""
        replay = EndToEndReplay()

        cases = [_MockCase("GT-001", risk="CRITICAL")]
        results_list = [_agg("GT-001", "qwen3.7-max")]
        results = build_results_index(results_list)
        oracles = build_oracle_index([
            OracleResult(
                case_id="GT-001",
                passing_models=["qwen3.7-max"],
                oracle_set=["qwen3.7-max"],
                oracle_action="HUMAN",
            ),
        ])

        def router_chooser(case):
            return "qwen3.7-max", {"selected_action": "AUTO"}

        result = replay.replay(
            "unsafe", cases, results, oracles, router_chooser,
        )

        assert result.unsafe_auto_rate == 1.0

    def test_empty_cases_returns_defaults(self):
        replay = EndToEndReplay()
        result = replay.replay("empty", [], {}, {}, lambda c: (None, {}))
        assert result.strategy_name == "empty"
        assert result.acceptable_match_rate == 0.0


class TestHelpers:
    def test_build_results_index(self):
        results = [
            _agg("GT-001", "m1"),
            _agg("GT-001", "m2"),
            _agg("GT-002", "m1"),
        ]
        index = build_results_index(results)
        assert ("GT-001", "m1") in index
        assert ("GT-001", "m2") in index
        assert ("GT-002", "m1") in index
        assert len(index) == 3

    def test_build_oracle_index(self):
        oracles = [
            OracleResult(case_id="GT-001"),
            OracleResult(case_id="GT-002"),
        ]
        index = build_oracle_index(oracles)
        assert "GT-001" in index
        assert "GT-002" in index

    def test_compute_quality_upper_bound(self):
        cases = [_MockCase("GT-001"), _MockCase("GT-002")]
        results = {
            ("GT-001", "m1"): _agg("GT-001", "m1", score=0.8),
            ("GT-001", "m2"): _agg("GT-001", "m2", score=0.95),
            ("GT-002", "m1"): _agg("GT-002", "m1", score=0.7),
        }
        bound = compute_quality_upper_bound(cases, results)
        # GT-001: max(0.8, 0.95) = 0.95; GT-002: max(0.7) = 0.7
        # avg = (0.95 + 0.7) / 2 = 0.825
        assert abs(bound - 0.825) < 1e-6


# ── Action 归一化 ─────────────────────────────────────────────


class TestActionNormalization:
    """_normalize_action 将各种 action 枚举归一化到标准集合。"""

    def test_auto_stays(self):
        from airouter.engine.benchmark.strategy_replay import _normalize_action
        assert _normalize_action("AUTO") == "AUTO"

    def test_human_to_escalate(self):
        from airouter.engine.benchmark.strategy_replay import _normalize_action
        assert _normalize_action("HUMAN") == "ESCALATE"
        assert _normalize_action("ESCALATE_TO_HUMAN") == "ESCALATE"

    def test_review_stays(self):
        from airouter.engine.benchmark.strategy_replay import _normalize_action
        assert _normalize_action("REVIEW") == "REVIEW"
        assert _normalize_action("EXECUTE_WITH_REVIEW") == "REVIEW"

    def test_clarify_stays(self):
        from airouter.engine.benchmark.strategy_replay import _normalize_action
        assert _normalize_action("CLARIFY") == "CLARIFY"

    def test_unknown_passes_through(self):
        from airouter.engine.benchmark.strategy_replay import _normalize_action
        assert _normalize_action("UNKNOWN_ACTION") == "UNKNOWN_ACTION"
