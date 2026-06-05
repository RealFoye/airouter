"""测试 ModelSelector：硬约束过滤 + 评分。"""

import pytest

from airouter.config import ModelEntry
from airouter.engine.router.selector import ModelSelector
from airouter.models.enums import (
    ComplexityLevel,
    RiskLevel,
    SensitivityLevel,
    TaskCategory,
)
from airouter.models.schemas import TaskFeatures


@pytest.fixture
def selector() -> ModelSelector:
    return ModelSelector()


@pytest.fixture
def all_models() -> list[ModelEntry]:
    return [
        ModelEntry(
            name="tier1-a", tier=1, provider="test", api_base="http://x",
            input_price_per_1k=0.02, output_price_per_1k=0.06,
            max_context_window=131072,
            capabilities=["code_gen", "complex_reasoning", "architecture", "code_review", "security"],
            allow_sensitive_data=True, latency_estimate_ms=3000,
        ),
        ModelEntry(
            name="tier1-b", tier=1, provider="test", api_base="http://x",
            input_price_per_1k=0.015, output_price_per_1k=0.05,
            max_context_window=131072,
            capabilities=["code_gen", "complex_reasoning", "architecture"],
            allow_sensitive_data=True, latency_estimate_ms=3500,
        ),
        ModelEntry(
            name="tier2-a", tier=2, provider="test", api_base="http://x",
            input_price_per_1k=0.008, output_price_per_1k=0.02,
            max_context_window=131072,
            capabilities=["code_gen", "documentation", "test_generation"],
            allow_sensitive_data=True, latency_estimate_ms=2000,
        ),
        ModelEntry(
            name="tier3-a", tier=3, provider="test", api_base="http://x",
            input_price_per_1k=0.002, output_price_per_1k=0.005,
            max_context_window=65536,
            capabilities=["code_gen", "documentation", "formatting"],
            allow_sensitive_data=False, latency_estimate_ms=1000,
        ),
    ]


def _make_features(
    category=TaskCategory.CODE_GENERATION,
    complexity=ComplexityLevel.SIMPLE,
    risk=RiskLevel.LOW,
    sensitivity=SensitivityLevel.LOW,
    required_caps=None,
    input_tokens=1000,
) -> TaskFeatures:
    return TaskFeatures(
        category=category,
        complexity=complexity,
        risk_level=risk,
        sensitivity=sensitivity,
        required_capabilities=required_caps or {"code_gen"},
        preferred_capabilities=set(),
        estimated_input_tokens=input_tokens,
        estimated_output_tokens=200,
    )


# ── 硬约束过滤 ──────────────────────────────────────────────
def test_filter_simple_task_allows_tier3(selector: ModelSelector, all_models):
    features = _make_features()
    candidates = selector.filter_candidates(all_models, features)
    tier_names = [m.name for m in candidates]
    assert "tier3-a" in tier_names


def test_filter_complex_excludes_tier3(selector: ModelSelector, all_models):
    features = _make_features(
        complexity=ComplexityLevel.COMPLEX,
        required_caps={"code_gen", "complex_reasoning"},
    )
    candidates = selector.filter_candidates(all_models, features)
    tier_names = [m.name for m in candidates]
    assert "tier3-a" not in tier_names


def test_filter_sensitive_data_excludes_no_sensitive(selector: ModelSelector, all_models):
    features = _make_features(sensitivity=SensitivityLevel.HIGH)
    candidates = selector.filter_candidates(all_models, features)
    tier_names = [m.name for m in candidates]
    assert "tier3-a" not in tier_names  # allow_sensitive_data=False


def test_filter_context_window(selector: ModelSelector, all_models):
    features = _make_features(input_tokens=100000)
    candidates = selector.filter_candidates(all_models, features)
    tier_names = [m.name for m in candidates]
    assert "tier3-a" not in tier_names  # max_context=65536


def test_filter_capability_coverage(selector: ModelSelector, all_models):
    features = _make_features(
        complexity=ComplexityLevel.EXPERT,
        required_caps={"code_gen", "complex_reasoning", "architecture"},
    )
    candidates = selector.filter_candidates(all_models, features)
    # tier2-a 缺少 complex_reasoning 和 architecture，应该被过滤
    tier_names = [m.name for m in candidates]
    assert "tier2-a" not in tier_names
    assert "tier1-a" in tier_names


# ── 评分 ────────────────────────────────────────────────────
def test_score_models_returns_sorted(selector: ModelSelector, all_models):
    features = _make_features()
    candidates = selector.filter_candidates(all_models, features)
    scored = selector.score_models(candidates, features)
    assert len(scored) > 0
    # 验证得分递减
    for i in range(len(scored) - 1):
        assert scored[i].total_score >= scored[i + 1].total_score


def test_select_best_returns_model(selector: ModelSelector, all_models):
    features = _make_features()
    best = selector.select_best(all_models, features)
    assert best is not None
    assert best.model.name in [m.name for m in all_models]


def test_select_best_complex_task_prefers_tier1(selector: ModelSelector, all_models):
    features = _make_features(
        category=TaskCategory.ARCHITECTURE,
        complexity=ComplexityLevel.EXPERT,
        risk=RiskLevel.HIGH,
        required_caps={"architecture", "complex_reasoning"},
    )
    best = selector.select_best(all_models, features)
    assert best is not None
    assert best.model.tier == 1


def test_select_best_no_candidates(selector: ModelSelector):
    # 空模型列表
    features = _make_features()
    best = selector.select_best([], features)
    assert best is None
