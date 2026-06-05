"""测试 ModelRegistry。"""


import pytest

from airouter.config import ModelsConfig
from airouter.models.model_registry import ModelRegistry

MINIMAL_MODELS = {
    "models": [
        {
            "name": "tier1-model-a",
            "tier": 1,
            "provider": "test",
            "api_base": "https://api.test.com",
            "input_price_per_1k": 0.02,
            "output_price_per_1k": 0.06,
            "max_context_window": 131072,
            "capabilities": ["code_gen", "complex_reasoning", "architecture"],
        },
        {
            "name": "tier1-model-b",
            "tier": 1,
            "provider": "test",
            "api_base": "https://api.test.com",
            "input_price_per_1k": 0.015,
            "output_price_per_1k": 0.05,
            "max_context_window": 131072,
            "capabilities": ["code_gen", "complex_reasoning"],
        },
        {
            "name": "tier2-model",
            "tier": 2,
            "provider": "test",
            "api_base": "https://api.test.com",
            "input_price_per_1k": 0.008,
            "output_price_per_1k": 0.02,
            "max_context_window": 131072,
            "capabilities": ["code_gen", "documentation"],
        },
        {
            "name": "tier2-model-b",
            "tier": 2,
            "provider": "test",
            "api_base": "https://api.test.com",
            "input_price_per_1k": 0.01,
            "output_price_per_1k": 0.025,
            "max_context_window": 128000,
            "capabilities": ["code_gen", "documentation", "test_generation"],
        },
        {
            "name": "tier3-model",
            "tier": 3,
            "provider": "test",
            "api_base": "https://api.test.com",
            "input_price_per_1k": 0.002,
            "output_price_per_1k": 0.005,
            "max_context_window": 65536,
            "capabilities": ["code_gen", "formatting"],
        },
    ]
}


@pytest.fixture
def registry() -> ModelRegistry:
    config = ModelsConfig(**MINIMAL_MODELS)
    return ModelRegistry(config)


def test_registry_loads_5_models(registry: ModelRegistry):
    assert len(registry) == 5


def test_registry_all_models(registry: ModelRegistry):
    assert len(registry.all_models) == 5


def test_registry_get_by_name(registry: ModelRegistry):
    model = registry.get_by_name("tier2-model")
    assert model is not None
    assert model.tier == 2
    assert model.name == "tier2-model"


def test_registry_get_by_name_not_found(registry: ModelRegistry):
    assert registry.get_by_name("nonexistent") is None


def test_registry_get_by_tier(registry: ModelRegistry):
    tier1 = registry.get_by_tier(1)
    assert len(tier1) == 2
    assert all(m.tier == 1 for m in tier1)


def test_registry_get_tier_shortcuts(registry: ModelRegistry):
    assert len(registry.get_tier1_models()) == 2
    assert len(registry.get_tier2_models()) == 2
    assert len(registry.get_tier3_models()) == 1


def test_registry_get_all_tiers(registry: ModelRegistry):
    assert registry.get_all_tiers() == [1, 2, 3]


def test_registry_contains(registry: ModelRegistry):
    assert "tier1-model-a" in registry
    assert "nonexistent" not in registry


def test_registry_real_data():
    """验证实际 models.yaml 能加载 5 个模型。"""
    from airouter.config import load_models
    config = load_models()
    registry = ModelRegistry(config)
    assert len(registry) == 5
    assert len(registry.get_tier1_models()) == 2
    assert len(registry.get_tier2_models()) == 2
    assert len(registry.get_tier3_models()) == 1
