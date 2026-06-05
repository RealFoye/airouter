"""测试配置加载器。"""

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from airouter.config import (
    ModelEntry,
    load_budgets,
    load_compression_policy,
    load_models,
    load_quality_defaults,
    load_routing_rules,
)

# ── models.yaml ─────────────────────────────────────────────
MINIMAL_MODELS = {
    "models": [
        {
            "name": "test-model",
            "tier": 2,
            "provider": "test",
            "api_base": "https://api.test.com",
            "input_price_per_1k": 0.01,
            "output_price_per_1k": 0.02,
            "max_context_window": 32000,
        }
    ]
}


def test_load_models_valid(tmp_path: Path):
    p = tmp_path / "models.yaml"
    p.write_text(yaml.dump(MINIMAL_MODELS))
    cfg = load_models(tmp_path)
    assert len(cfg.models) == 1
    assert cfg.models[0].name == "test-model"
    assert cfg.models[0].tier == 2


def test_models_missing_field(tmp_path: Path):
    bad = {"models": [{"name": "x"}]}  # missing tier, provider, etc.
    p = tmp_path / "models.yaml"
    p.write_text(yaml.dump(bad))
    with pytest.raises(ValidationError):
        load_models(tmp_path)


def test_models_empty_list(tmp_path: Path):
    p = tmp_path / "models.yaml"
    p.write_text(yaml.dump({"models": []}))
    with pytest.raises(ValidationError, match="must not be empty"):
        load_models(tmp_path)


def test_models_invalid_tier():
    with pytest.raises(ValidationError):
        ModelEntry(
            name="x", tier=5, provider="p", api_base="http://x",
            input_price_per_1k=0.01, output_price_per_1k=0.01,
            max_context_window=1000,
        )


def test_models_file_not_found(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        load_models(tmp_path)


def test_models_caching_unknown():
    """supports_prompt_caching 支持 unknown，按 false 处理。"""
    entry = ModelEntry(
        name="x", tier=1, provider="p", api_base="http://x",
        input_price_per_1k=0.01, output_price_per_1k=0.01,
        max_context_window=1000,
        cache={"supports_prompt_caching": "unknown"},
    )
    assert entry.cache.supports_prompt_caching == "unknown"


# ── routing_rules.yaml ──────────────────────────────────────
MINIMAL_RULES = {
    "routing_weights": {
        "default": {"capability": 0.35, "cost": 0.30, "quality": 0.20, "latency": 0.15},
    },
    "allowed_tiers": {
        "SIMPLE": {"default": [3], "high_risk": [2, 3]},
    },
    "top_k_by_tier": {
        "tier1": {"k": 2, "pre_score": {"capability": 0.5, "quality": 0.35, "cost": 0.15}},
    },
    "strategy_quality_weights": {
        "PLAN_EXECUTE": {"plan": 0.55, "execute": 0.45, "review": 0.0},
    },
}


def test_load_routing_rules_valid(tmp_path: Path):
    p = tmp_path / "routing_rules.yaml"
    p.write_text(yaml.dump(MINIMAL_RULES))
    cfg = load_routing_rules(tmp_path)
    assert "default" in cfg.routing_weights
    assert cfg.routing_weights["default"].capability == 0.35


def test_routing_rules_missing_section(tmp_path: Path):
    p = tmp_path / "routing_rules.yaml"
    p.write_text(yaml.dump({"routing_weights": {}}))
    with pytest.raises(ValidationError):
        load_routing_rules(tmp_path)


# ── budgets.yaml ────────────────────────────────────────────
MINIMAL_BUDGETS = {
    "projects": {
        "test-project": {
            "monthly_budget_cny": 1000,
            "task_budget_default_cny": 0.50,
        }
    },
    "task_type_limits": {
        "SIMPLE": {"max_cost_cny": 0.05},
    },
}


def test_load_budgets_valid(tmp_path: Path):
    p = tmp_path / "budgets.yaml"
    p.write_text(yaml.dump(MINIMAL_BUDGETS))
    cfg = load_budgets(tmp_path)
    assert "test-project" in cfg.projects
    assert cfg.projects["test-project"].monthly_budget_cny == 1000


def test_budgets_missing_field(tmp_path: Path):
    p = tmp_path / "budgets.yaml"
    p.write_text(yaml.dump({"projects": {}, "task_type_limits": {}}))
    cfg = load_budgets(tmp_path)  # empty dicts are valid at this level
    assert len(cfg.projects) == 0


# ── quality_defaults.yaml ──────────────────────────────────
MINIMAL_QUALITY = {
    "default_quality": {"tier1": {"code_generation": 0.80}},
    "default_failure_rates": {"tier1": 0.03},
}


def test_load_quality_defaults_valid(tmp_path: Path):
    p = tmp_path / "quality_defaults.yaml"
    p.write_text(yaml.dump(MINIMAL_QUALITY))
    cfg = load_quality_defaults(tmp_path)
    assert cfg.default_quality["tier1"]["code_generation"] == 0.80


def test_quality_defaults_missing_section(tmp_path: Path):
    p = tmp_path / "quality_defaults.yaml"
    p.write_text(yaml.dump({"default_quality": {}}))
    with pytest.raises(ValidationError):
        load_quality_defaults(tmp_path)


# ── compression_policy.yaml ─────────────────────────────────
def test_load_compression_policy_valid(tmp_path: Path):
    data = {
        "strategies": {
            "conservative": {"target_reduction_min": 0.05, "target_reduction_max": 0.15},
        },
        "quality_drop_threshold": 0.15,
        "context_length_thresholds": [
            {"max_tokens": 5000, "strategy": "none"},
        ],
    }
    p = tmp_path / "compression_policy.yaml"
    p.write_text(yaml.dump(data))
    cfg = load_compression_policy(tmp_path)
    assert cfg.quality_drop_threshold == 0.15
    assert len(cfg.context_length_thresholds) == 1
