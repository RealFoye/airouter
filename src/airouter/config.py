"""配置管理：Pydantic Settings + YAML 加载器。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional, Union

import yaml
from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# ── 项目根目录 ──────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


# ── 环境变量级配置 ──────────────────────────────────────────
class AppSettings(BaseSettings):
    data_dir: Path = Field(default=PROJECT_ROOT / "data")
    db_url: str = Field(default="sqlite:///./airouter.db")
    debug: bool = False

    # 模型 API keys（通过环境变量 AIROUTER_DASHSCOPE_API_KEY 等设置）
    dashscope_api_key: str = ""
    deepseek_api_key: str = ""
    zhipu_api_key: str = ""
    kimi_api_key: str = ""
    minimax_api_key: str = ""

    model_config = SettingsConfigDict(
        env_prefix="AIROUTER_",
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = AppSettings()


# ── models.yaml ─────────────────────────────────────────────
class ModelCacheConfig(BaseModel):
    supports_prompt_caching: Union[bool, str] = False
    cache_mode: str = "none"
    cache_write_price_multiplier: float = 1.0
    cache_read_price_ratio: float = 0.0
    cache_min_prefix_tokens: int = 0
    cache_ttl_seconds: int = 0

    @field_validator("supports_prompt_caching", mode="before")
    @classmethod
    def normalize_caching(cls, v: Any) -> Union[bool, str]:
        if isinstance(v, bool):
            return v
        if isinstance(v, str):
            low = v.lower()
            if low == "unknown":
                return "unknown"
            if low == "true":
                return True
            if low == "false":
                return False
        raise ValueError(f"supports_prompt_caching must be true/false/unknown, got {v!r}")

    @property
    def is_caching_effective(self) -> bool:
        """unknown 按 false 处理，保守成本估算。"""
        return self.supports_prompt_caching is True


class ModelEntry(BaseModel):
    name: str
    tier: int
    provider: str
    api_base: str
    input_price_per_1k: float
    output_price_per_1k: float
    max_context_window: int
    capabilities: list[str] = Field(default_factory=list)
    allow_sensitive_data: bool = False
    latency_estimate_ms: int = 2000
    cache: ModelCacheConfig = Field(default_factory=ModelCacheConfig)

    @field_validator("tier")
    @classmethod
    def tier_range(cls, v: int) -> int:
        if v not in (1, 2, 3):
            raise ValueError(f"tier must be 1, 2, or 3, got {v}")
        return v


class ModelsConfig(BaseModel):
    models: list[ModelEntry]

    @field_validator("models")
    @classmethod
    def at_least_one(cls, v: list[ModelEntry]) -> list[ModelEntry]:
        if not v:
            raise ValueError("models list must not be empty")
        return v


# ── routing_rules.yaml ──────────────────────────────────────
class RoutingWeights(BaseModel):
    capability: float
    cost: float
    quality: float
    latency: float

    @field_validator("capability", "cost", "quality", "latency")
    @classmethod
    def weight_range(cls, v: float) -> float:
        if not (0.0 <= v <= 1.0):
            raise ValueError(f"weight must be in [0, 1], got {v}")
        return v


class AllowedTierRule(BaseModel):
    default: list[int]
    high_risk: list[int]


class TopKConfig(BaseModel):
    k: int
    pre_score: dict[str, float]


class Constraints(BaseModel):
    min_capability_coverage: float = 0.5


class RoutingRulesConfig(BaseModel):
    routing_weights: dict[str, RoutingWeights]
    allowed_tiers: dict[str, AllowedTierRule]
    top_k_by_tier: dict[str, TopKConfig]
    strategy_quality_weights: dict[str, dict[str, float]]
    constraints: Constraints = Field(default_factory=Constraints)
    human_review_required_tasks: list[str] = Field(default_factory=list)
    cost_sensitivity_by_task_type: dict[str, str] = Field(default_factory=dict)


# ── budgets.yaml ────────────────────────────────────────────
class ProjectBudget(BaseModel):
    monthly_budget_cny: float
    task_budget_default_cny: float
    task_budget_hard_limit_multiplier: float = 3.0


class TaskTypeLimit(BaseModel):
    max_cost_cny: float


class BudgetsConfig(BaseModel):
    projects: dict[str, ProjectBudget]
    task_type_limits: dict[str, TaskTypeLimit]


# ── quality_defaults.yaml ───────────────────────────────────
class QualityDefaultsConfig(BaseModel):
    default_quality: dict[str, dict[str, float]]
    default_failure_rates: dict[str, float]


# ── compression_policy.yaml ─────────────────────────────────
class CompressionLevel(BaseModel):
    target_reduction_min: float = 0.0
    target_reduction_max: float = 0.0
    description: str = ""
    apply_when: str = ""


class ContextLengthThreshold(BaseModel):
    max_tokens: int
    strategy: str
    target_reduction: str = ""
    description: str = ""
    note: str = ""


class CompressionPolicyConfig(BaseModel):
    strategies: dict[str, CompressionLevel] = Field(default_factory=dict)
    context_length_thresholds: list[ContextLengthThreshold] = Field(default_factory=list)
    quality_drop_threshold: float = 0.15


# ── YAML 加载工具 ───────────────────────────────────────────
def _load_yaml(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(f"Config file must contain a YAML mapping: {path}")
    return data


def load_models(data_dir: Path | None = None) -> ModelsConfig:
    d = data_dir or settings.data_dir
    return ModelsConfig(**_load_yaml(d / "models.yaml"))


def load_routing_rules(data_dir: Path | None = None) -> RoutingRulesConfig:
    d = data_dir or settings.data_dir
    return RoutingRulesConfig(**_load_yaml(d / "routing_rules.yaml"))


def load_budgets(data_dir: Path | None = None) -> BudgetsConfig:
    d = data_dir or settings.data_dir
    return BudgetsConfig(**_load_yaml(d / "budgets.yaml"))


def load_quality_defaults(data_dir: Path | None = None) -> QualityDefaultsConfig:
    d = data_dir or settings.data_dir
    return QualityDefaultsConfig(**_load_yaml(d / "quality_defaults.yaml"))


def load_compression_policy(data_dir: Path | None = None) -> CompressionPolicyConfig:
    d = data_dir or settings.data_dir
    return CompressionPolicyConfig(**_load_yaml(d / "compression_policy.yaml"))


# ── 聚合配置 ────────────────────────────────────────────────
class AppConfig(BaseModel):
    """所有配置聚合到一个对象，方便引擎层一次性获取。"""
    models: ModelsConfig
    routing_rules: RoutingRulesConfig
    budgets: BudgetsConfig
    quality_defaults: QualityDefaultsConfig
    compression_policy: Optional[CompressionPolicyConfig] = None


def load_all(data_dir: Path | None = None) -> AppConfig:
    d = data_dir or settings.data_dir
    return AppConfig(
        models=load_models(d),
        routing_rules=load_routing_rules(d),
        budgets=load_budgets(d),
        quality_defaults=load_quality_defaults(d),
        compression_policy=load_compression_policy(d),
    )
