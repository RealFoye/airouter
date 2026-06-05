"""测试 CostEstimator。"""

import pytest

from airouter.config import ModelEntry
from airouter.engine.router.estimator import CostEstimator


@pytest.fixture
def estimator() -> CostEstimator:
    return CostEstimator()


@pytest.fixture
def tier1_model() -> ModelEntry:
    return ModelEntry(
        name="tier1-model",
        tier=1,
        provider="test",
        api_base="https://api.test.com",
        input_price_per_1k=0.02,
        output_price_per_1k=0.06,
        max_context_window=131072,
    )


@pytest.fixture
def tier3_model() -> ModelEntry:
    return ModelEntry(
        name="tier3-model",
        tier=3,
        provider="test",
        api_base="https://api.test.com",
        input_price_per_1k=0.002,
        output_price_per_1k=0.005,
        max_context_window=65536,
    )


def test_basic_cost_calculation(estimator: CostEstimator, tier1_model: ModelEntry):
    """基础成本 = input_tokens/1000 * input_price + output_tokens/1000 * output_price"""
    est = estimator.estimate(tier1_model, input_tokens=1000, output_tokens=1000)
    assert est.input_cost == pytest.approx(0.02)
    assert est.output_cost == pytest.approx(0.06)
    assert est.total_cost == pytest.approx(0.08)


def test_cost_scales_with_tokens(estimator: CostEstimator, tier1_model: ModelEntry):
    est = estimator.estimate(tier1_model, input_tokens=5000, output_tokens=2000)
    assert est.input_cost == pytest.approx(0.10)
    assert est.output_cost == pytest.approx(0.12)
    assert est.total_cost == pytest.approx(0.22)


def test_tier3_cheaper_than_tier1(
    estimator: CostEstimator, tier1_model: ModelEntry, tier3_model: ModelEntry
):
    est1 = estimator.estimate(tier1_model, input_tokens=1000, output_tokens=1000)
    est3 = estimator.estimate(tier3_model, input_tokens=1000, output_tokens=1000)
    assert est3.total_cost < est1.total_cost


def test_zero_tokens_zero_cost(estimator: CostEstimator, tier1_model: ModelEntry):
    est = estimator.estimate(tier1_model, input_tokens=0, output_tokens=0)
    assert est.total_cost == 0.0


def test_strategy_cost_multi_model(
    estimator: CostEstimator, tier1_model: ModelEntry, tier3_model: ModelEntry
):
    total = estimator.estimate_strategy_cost(
        models=[tier1_model, tier3_model],
        input_tokens=1000,
        output_tokens=1000,
    )
    # tier1: 0.08, tier3: 0.007 → total ≈ 0.087
    assert total == pytest.approx(0.08 + 0.007)


def test_strategy_cost_with_multiple_calls(
    estimator: CostEstimator, tier1_model: ModelEntry
):
    total = estimator.estimate_strategy_cost(
        models=[tier1_model],
        input_tokens=1000,
        output_tokens=1000,
        num_calls=3,
    )
    assert total == pytest.approx(0.08 * 3)
