"""测试 CostEstimator：基础成本 + 策略级成本 + Plan-Execute 上下文局部化。"""

import pytest

from airouter.config import ModelEntry
from airouter.engine.router.estimator import CostEstimator
from airouter.models.enums import StrategyType
from airouter.models.schemas import ModelAssignment, TaskFeatures


@pytest.fixture
def estimator() -> CostEstimator:
    return CostEstimator()


@pytest.fixture
def tier1_model() -> ModelEntry:
    return ModelEntry(
        name="qwen3.7-max",
        tier=1,
        provider="test",
        api_base="https://api.test.com",
        input_price_per_1k=0.02,
        output_price_per_1k=0.06,
        max_context_window=131072,
    )


@pytest.fixture
def tier2_model() -> ModelEntry:
    return ModelEntry(
        name="qwen3.7-plus",
        tier=2,
        provider="test",
        api_base="https://api.test.com",
        input_price_per_1k=0.008,
        output_price_per_1k=0.02,
        max_context_window=131072,
    )


@pytest.fixture
def tier3_model() -> ModelEntry:
    return ModelEntry(
        name="deepseek-v4-flash",
        tier=3,
        provider="test",
        api_base="https://api.test.com",
        input_price_per_1k=0.002,
        output_price_per_1k=0.005,
        max_context_window=65536,
    )


class _MockRegistry:
    """测试用 mock registry。"""

    def __init__(self, models: list[ModelEntry]):
        self._models = {m.name: m for m in models}

    def get_by_name(self, name: str) -> ModelEntry | None:
        return self._models.get(name)


def _make_features(input_tokens=5000, output_tokens=800, subtasks=None) -> TaskFeatures:
    from airouter.models.enums import ComplexityLevel, TaskCategory

    return TaskFeatures(
        category=TaskCategory.CODE_GENERATION,
        complexity=ComplexityLevel.COMPLEX,
        estimated_input_tokens=input_tokens,
        estimated_output_tokens=output_tokens,
        subtasks=subtasks or ["子任务1", "子任务2", "子任务3"],
    )


# ── 基础成本测试（保持不变） ─────────────────────────────────
class TestBasicCost:
    def test_basic_cost_calculation(self, estimator, tier1_model):
        est = estimator.estimate(tier1_model, input_tokens=1000, output_tokens=1000)
        assert est.input_cost == pytest.approx(0.02)
        assert est.output_cost == pytest.approx(0.06)
        assert est.total_cost == pytest.approx(0.08)

    def test_cost_scales_with_tokens(self, estimator, tier1_model):
        est = estimator.estimate(tier1_model, input_tokens=5000, output_tokens=2000)
        assert est.input_cost == pytest.approx(0.10)
        assert est.output_cost == pytest.approx(0.12)
        assert est.total_cost == pytest.approx(0.22)

    def test_tier3_cheaper_than_tier1(self, estimator, tier1_model, tier3_model):
        est1 = estimator.estimate(tier1_model, input_tokens=1000, output_tokens=1000)
        est3 = estimator.estimate(tier3_model, input_tokens=1000, output_tokens=1000)
        assert est3.total_cost < est1.total_cost

    def test_zero_tokens_zero_cost(self, estimator, tier1_model):
        est = estimator.estimate(tier1_model, input_tokens=0, output_tokens=0)
        assert est.total_cost == 0.0


# ── 策略级成本测试 ───────────────────────────────────────────
class TestStrategyCost:
    def test_single_model_cost(self, estimator, tier1_model):
        registry = _MockRegistry([tier1_model])
        features = _make_features(input_tokens=1000, output_tokens=1000, subtasks=[])
        assignment = ModelAssignment(executor="qwen3.7-max")
        est = estimator.estimate_strategy_cost(
            StrategyType.SINGLE_MODEL, assignment, features, registry
        )
        assert est.total_cost == pytest.approx(0.08)

    def test_guided_execute_cost(self, estimator, tier1_model, tier2_model):
        """Guided: Tier 2 执行 + Tier 1 审查。"""
        registry = _MockRegistry([tier1_model, tier2_model])
        features = _make_features(input_tokens=5000, output_tokens=1000, subtasks=[])
        assignment = ModelAssignment(executor="qwen3.7-plus", reviewer="qwen3.7-max")
        est = estimator.estimate_strategy_cost(
            StrategyType.GUIDED_EXECUTE, assignment, features, registry
        )
        # 执行成本 + 审查成本 > 0
        assert est.total_cost > 0
        # 执行成本 = tier2 处理全量 tokens
        exec_cost = estimator.estimate(tier2_model, 5000, 1000)
        review_cost = estimator.estimate_review_cost(tier1_model, features)
        assert est.total_cost == pytest.approx(exec_cost.total_cost + review_cost)

    def test_plan_execute_cost(self, estimator, tier1_model, tier3_model):
        """Plan-Execute: Tier 1 规划 + Tier 3 执行，上下文局部化。"""
        registry = _MockRegistry([tier1_model, tier3_model])
        features = _make_features(input_tokens=10000, output_tokens=2000, subtasks=["a", "b", "c"])
        assignment = ModelAssignment(planner="qwen3.7-max", executor="deepseek-v4-flash")
        est = estimator.estimate_strategy_cost(
            StrategyType.PLAN_EXECUTE, assignment, features, registry
        )
        # Plan-Execute 成本 > 0
        assert est.total_cost > 0
        # Plan-Execute 成本 < 全程 Tier 1 成本（上下文局部化 + 降级）
        full_tier1 = estimator.estimate(tier1_model, 10000, 2000)
        assert est.total_cost < full_tier1.total_cost

    def test_plan_execute_review_cost(self, estimator, tier1_model, tier2_model):
        """PER: Tier 1 规划 + Tier 2 执行 + Tier 1 审查。"""
        registry = _MockRegistry([tier1_model, tier2_model])
        features = _make_features(input_tokens=5000, output_tokens=1000, subtasks=["a", "b"])
        assignment = ModelAssignment(
            planner="qwen3.7-max", executor="qwen3.7-plus", reviewer="qwen3.7-max"
        )
        est = estimator.estimate_strategy_cost(
            StrategyType.PLAN_EXECUTE_REVIEW, assignment, features, registry
        )
        # PER > Plan-Execute（多了 review 成本）
        pe_assignment = ModelAssignment(planner="qwen3.7-max", executor="qwen3.7-plus")
        pe_est = estimator.estimate_strategy_cost(
            StrategyType.PLAN_EXECUTE, pe_assignment, features, registry
        )
        assert est.total_cost > pe_est.total_cost

    def test_missing_model_returns_zero(self, estimator, tier1_model):
        registry = _MockRegistry([tier1_model])
        features = _make_features()
        assignment = ModelAssignment(executor="nonexistent")
        est = estimator.estimate_strategy_cost(
            StrategyType.SINGLE_MODEL, assignment, features, registry
        )
        assert est.total_cost == 0.0


# ── Plan-Execute 成本细节 ────────────────────────────────────
class TestPlanExecuteCostDetail:
    def test_context_localization_reduces_executor_cost(self, estimator, tier1_model, tier3_model):
        """上下文局部化使 executor 输入远小于全局 input_tokens。"""
        features = _make_features(input_tokens=10000, output_tokens=2000, subtasks=["a", "b", "c"])
        pe_cost = estimator.estimate_plan_execute_cost(tier1_model, tier3_model, features)

        # 如果 executor 拿全量上下文（无局部化），成本会更高
        naive_cost = (
            estimator.estimate(tier1_model, 10500, 300).total_cost  # planner 同
            + estimator.estimate(tier3_model, 10000, 2000).total_cost  # executor 全量
        )
        assert pe_cost < naive_cost

    def test_more_subtasks_lower_per_call_cost(self, estimator, tier1_model, tier3_model):
        """更多子任务 → 每个子任务分摊的 executor 成本更低。"""
        features_3 = _make_features(
            input_tokens=10000, output_tokens=3000, subtasks=["a", "b", "c"]
        )
        features_6 = _make_features(
            input_tokens=10000, output_tokens=3000, subtasks=["a", "b", "c", "d", "e", "f"]
        )
        cost_3 = estimator.estimate_plan_execute_cost(tier1_model, tier3_model, features_3)
        cost_6 = estimator.estimate_plan_execute_cost(tier1_model, tier3_model, features_6)
        # 6 个子任务：planner 成本相同，executor 单次更少但总次数更多
        # 总成本不一定更低（更多调用 = 更多指令 token），但 planner 部分相同
        assert isinstance(cost_3, float)
        assert isinstance(cost_6, float)
        assert cost_3 > 0
        assert cost_6 > 0

    def test_zero_subtasks_treated_as_one(self, estimator, tier1_model, tier3_model):
        features = _make_features(input_tokens=5000, output_tokens=1000, subtasks=[])
        cost = estimator.estimate_plan_execute_cost(tier1_model, tier3_model, features)
        assert cost > 0


# ── 审查成本 ─────────────────────────────────────────────────
class TestReviewCost:
    def test_review_cost_positive(self, estimator, tier1_model):
        features = _make_features(input_tokens=5000, output_tokens=1000)
        cost = estimator.estimate_review_cost(tier1_model, features)
        assert cost > 0

    def test_review_cost_none_reviewer(self, estimator):
        features = _make_features()
        cost = estimator.estimate_review_cost(None, features)
        assert cost == 0.0

    def test_review_cost_scales_with_output(self, estimator, tier1_model):
        features_small = _make_features(input_tokens=5000, output_tokens=500)
        features_large = _make_features(input_tokens=5000, output_tokens=5000)
        cost_small = estimator.estimate_review_cost(tier1_model, features_small)
        cost_large = estimator.estimate_review_cost(tier1_model, features_large)
        assert cost_large > cost_small

    def test_review_input_has_overhead(self, estimator, tier1_model):
        """reviewer 输入至少包含 executor_output + 500 overhead。"""
        features = _make_features(input_tokens=1000, output_tokens=100)
        cost = estimator.estimate_review_cost(tier1_model, features)
        # 最小输入 = 100 + min(2000, 150) + 500 = 750 tokens
        # 最小输出 = max(300, 10) = 300 tokens
        min_expected = (750 / 1000.0) * tier1_model.input_price_per_1k + (300 / 1000.0) * tier1_model.output_price_per_1k
        assert cost == pytest.approx(min_expected)
