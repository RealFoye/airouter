"""Level 3 backtest reporter unit tests."""

import pytest

from airouter.config import ModelEntry
from airouter.engine.benchmark.reporter import Level3BacktestReporter
from airouter.engine.benchmark.schemas import BacktestResult
from airouter.models.enums import ComplexityLevel, RiskLevel, TaskCategory
from airouter.models.schemas import ModelAssignment, TaskFeatures

# ── Fixtures ─────────────────────────────────────────────────


@pytest.fixture
def t1_model() -> ModelEntry:
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
def t2_model() -> ModelEntry:
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
def t3_model() -> ModelEntry:
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
    def __init__(self, models: list[ModelEntry]):
        self._models = {m.name: m for m in models}
        self.all_models = models

    def get_by_name(self, name: str):
        return self._models.get(name)


@pytest.fixture
def registry(t1_model, t2_model, t3_model) -> _MockRegistry:
    return _MockRegistry([t1_model, t2_model, t3_model])


@pytest.fixture
def reporter(registry) -> Level3BacktestReporter:
    return Level3BacktestReporter(registry, baseline_model="qwen3.7-max")


@pytest.fixture
def features() -> TaskFeatures:
    return TaskFeatures(
        category=TaskCategory.CODE_GENERATION,
        complexity=ComplexityLevel.MODERATE,
        estimated_input_tokens=1000,
        estimated_output_tokens=500,
        subtasks=["task1"],
    )


class _MockDecision:
    """Lightweight mock for RoutingDecision."""

    def __init__(self, *, executor=None, tier=None, risk="LOW",
                 complexity="MODERATE", requires_review=False,
                 quality_loss=0.0):
        self.models = ModelAssignment(executor=executor)
        self.risk_level = RiskLevel(risk)
        self.requires_human_review = requires_review
        self.quality_loss_vs_baseline = quality_loss
        self.human_review_reason = None
        # task_features stub
        self.task_features = type("F", (), {
            "complexity": ComplexityLevel(complexity),
            "category": TaskCategory.CODE_GENERATION,
        })()


# ── Tests ────────────────────────────────────────────────────


class TestBaselineValidation:
    def test_unknown_model_raises(self, registry):
        with pytest.raises(ValueError, match="Unknown baseline model"):
            Level3BacktestReporter(registry, baseline_model="nonexistent")

    def test_non_tier1_raises(self, registry):
        with pytest.raises(ValueError, match="Baseline model must be Tier 1"):
            Level3BacktestReporter(registry, baseline_model="qwen3.7-plus")

    def test_baseline_model_property(self, reporter):
        assert reporter.baseline_model == "qwen3.7-max"


class TestComputeBaselineCost:
    def test_baseline_cost_calculation(self, reporter, features):
        cost = reporter.compute_baseline_cost(features)
        # 1000 tokens * 0.02/1k + 500 tokens * 0.06/1k = 0.02 + 0.03 = 0.05
        assert cost == pytest.approx(0.05)

    def test_zero_tokens(self, reporter):
        features = TaskFeatures(
            category=TaskCategory.CODE_GENERATION,
            complexity=ComplexityLevel.SIMPLE,
            estimated_input_tokens=0,
            estimated_output_tokens=0,
            subtasks=[],
        )
        assert reporter.compute_baseline_cost(features) == 0.0


class TestClassifyDowngrade:
    def test_no_executor_is_none(self, reporter):
        decision = _MockDecision(executor=None)
        dtype, reason = reporter.classify_downgrade(decision)
        assert dtype == "none"
        assert "no executable model" in reason

    def test_tier1_executor_is_none(self, reporter):
        decision = _MockDecision(executor="qwen3.7-max")
        dtype, _ = reporter.classify_downgrade(decision)
        assert dtype == "none"

    def test_safe_downgrade(self, reporter):
        decision = _MockDecision(
            executor="qwen3.7-plus",  # tier 2
            risk="LOW",
            complexity="SIMPLE",
            requires_review=False,
            quality_loss=0.05,
        )
        dtype, reason = reporter.classify_downgrade(decision)
        assert dtype == "safe"
        assert "low risk" in reason

    def test_risky_due_to_high_risk(self, reporter):
        decision = _MockDecision(
            executor="qwen3.7-plus",
            risk="HIGH",
            complexity="SIMPLE",
            requires_review=False,
            quality_loss=0.05,
        )
        dtype, reason = reporter.classify_downgrade(decision)
        assert dtype == "risky"
        assert "risk=HIGH" in reason

    def test_risky_due_to_human_review(self, reporter):
        decision = _MockDecision(
            executor="deepseek-v4-flash",  # tier 3
            risk="LOW",
            complexity="MODERATE",
            requires_review=True,
            quality_loss=0.05,
        )
        dtype, reason = reporter.classify_downgrade(decision)
        assert dtype == "risky"
        assert "requires_human_review" in reason

    def test_risky_due_to_complexity(self, reporter):
        decision = _MockDecision(
            executor="qwen3.7-plus",
            risk="LOW",
            complexity="COMPLEX",
            requires_review=False,
            quality_loss=0.05,
        )
        dtype, reason = reporter.classify_downgrade(decision)
        assert dtype == "risky"
        assert "complexity=COMPLEX" in reason

    def test_risky_due_to_quality_loss(self, reporter):
        decision = _MockDecision(
            executor="qwen3.7-plus",
            risk="LOW",
            complexity="MODERATE",
            requires_review=False,
            quality_loss=0.20,
        )
        dtype, reason = reporter.classify_downgrade(decision)
        assert dtype == "risky"
        assert "quality_loss" in reason

    def test_safe_at_boundary(self, reporter):
        """quality_loss exactly 0.15 should be safe."""
        decision = _MockDecision(
            executor="qwen3.7-plus",
            risk="LOW",
            complexity="MODERATE",
            requires_review=False,
            quality_loss=0.15,
        )
        dtype, _ = reporter.classify_downgrade(decision)
        assert dtype == "safe"


def _make_result(**kwargs) -> BacktestResult:
    """Helper to create a BacktestResult with sensible defaults."""
    defaults = {
        "case_id": "C1",
        "source": "L1",
        "result_id": "L1:C1",
        "prompt_hash": "abc123",
        "has_executable_model": True,
        "task_type": "CODE_GENERATION",
        "complexity": "SIMPLE",
        "router_strategy": "SINGLE_MODEL",
        "router_executor": "qwen3.7-plus",
        "router_executor_tier": 2,
        "raw_router_cost": 0.03,
        "effective_router_cost": 0.03,
        "baseline_model": "qwen3.7-max",
        "baseline_cost": 0.05,
        "savings_cny": 0.02,
        "savings_rate": 0.4,
        "risk_level": "LOW",
        "downgrade_type": "safe",
    }
    defaults.update(kwargs)
    return BacktestResult(**defaults)


class TestBuildSummary:
    def test_basic_summary(self, reporter):
        results = [
            _make_result(case_id="C1"),
            _make_result(case_id="C2"),
        ]
        summary = reporter.build_summary(results)
        assert summary.total_cases == 2
        assert summary.baseline_model == "qwen3.7-max"
        assert summary.quality_mode == "routing_prior"
        assert summary.baseline_total_cost == pytest.approx(0.10)
        assert summary.router_total_cost == pytest.approx(0.06)
        assert summary.savings_total_cny == pytest.approx(0.04)
        assert summary.savings_rate == pytest.approx(0.4)

    def test_overspend_detected(self, reporter):
        results = [
            _make_result(
                case_id="C1",
                raw_router_cost=0.08,
                effective_router_cost=0.08,
                savings_cny=-0.03,
                savings_rate=-0.6,
            ),
        ]
        summary = reporter.build_summary(results)
        assert summary.overspend_count == 1
        assert len(summary.overspend_cases) == 1
        assert summary.overspend_cases[0]["case_id"] == "C1"

    def test_non_executable_counted(self, reporter):
        results = [
            _make_result(
                case_id="C1",
                has_executable_model=False,
                effective_router_cost=0.05,  # = baseline_cost
                savings_cny=0.0,
                savings_rate=0.0,
                exclusion_reason="no executable model",
            ),
        ]
        summary = reporter.build_summary(results)
        assert summary.non_executable_count == 1
        assert len(summary.non_executable_cases) == 1

    def test_by_source(self, reporter):
        results = [
            _make_result(case_id="C1", source="L1", result_id="L1:C1", baseline_cost=0.05, effective_router_cost=0.03, savings_cny=0.02),
            _make_result(case_id="C2", source="L2", result_id="L2:C2", baseline_cost=0.10, effective_router_cost=0.06, savings_cny=0.04),
        ]
        summary = reporter.build_summary(results)
        assert "L1" in summary.by_source
        assert "L2" in summary.by_source
        assert summary.by_source["L1"]["cases"] == 1
        assert summary.by_source["L2"]["cases"] == 1
        assert summary.l1_cases == 1
        assert summary.l2_cases == 1

    def test_approval_required_count(self, reporter):
        results = [
            _make_result(case_id="C1", requires_human_review=True),
            _make_result(case_id="C2", requires_human_review=False),
        ]
        summary = reporter.build_summary(results)
        assert summary.approval_required_count == 1

    def test_downgrade_lists(self, reporter):
        results = [
            _make_result(case_id="C1", downgrade_type="safe", downgrade_reason="safe reason"),
            _make_result(case_id="C2", downgrade_type="risky", downgrade_reason="risky reason"),
            _make_result(case_id="C3", downgrade_type="none"),
        ]
        summary = reporter.build_summary(results)
        assert summary.safe_downgrade_count == 1
        assert summary.risky_downgrade_count == 1
        assert len(summary.safe_downgrades) == 1
        assert len(summary.risky_downgrades) == 1
        assert summary.safe_downgrades[0]["case_id"] == "C1"
        assert summary.risky_downgrades[0]["case_id"] == "C2"

    def test_disclaimer_present(self, reporter):
        results = [_make_result()]
        summary = reporter.build_summary(results)
        assert "routing priors" in summary.disclaimer
        assert "approval-required" in summary.disclaimer
