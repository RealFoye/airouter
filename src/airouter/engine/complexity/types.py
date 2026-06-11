"""复杂度分析数据类型。"""

from __future__ import annotations

from dataclasses import dataclass

from airouter.models.enums import ComplexityLevel, RiskLevel, TaskCategory
from airouter.models.schemas import TaskFeatures

# ── OpenSquilla route class → AirRouter 复杂度映射 ──────────
ROUTE_TO_COMPLEXITY: dict[str, ComplexityLevel] = {
    "R0": ComplexityLevel.SIMPLE,
    "R1": ComplexityLevel.MODERATE,
    "R2": ComplexityLevel.COMPLEX,
    "R3": ComplexityLevel.EXPERT,
}

COMPLEXITY_ORDER: dict[ComplexityLevel, int] = {
    ComplexityLevel.SIMPLE: 0,
    ComplexityLevel.MODERATE: 1,
    ComplexityLevel.COMPLEX: 2,
    ComplexityLevel.EXPERT: 3,
}


@dataclass(frozen=True)
class MLPrediction:
    """ML 后端结构化返回值——完整区分 raw/final 语义。"""

    raw_route_class: str
    final_route_class: str
    raw_confidence: float
    final_class_probability: float
    probabilities: dict[str, float]
    margin: float
    difficulty_score: float
    flags: dict[str, bool]
    latency_ms: float
    cold_start_ms: float | None = None
    model_version: str = "unknown"


@dataclass(frozen=True)
class BackendMetadata:
    """后端运行时元数据——供 Diagnostics 使用。"""

    verification_ms: float | None = None
    load_ms: float | None = None
    manifest_hash: str | None = None
    fallback_reason: str | None = None
    config_version: str | None = None


@dataclass(frozen=True)
class ComplexityAnalysis:
    """统一分析结果。"""

    rule_complexity: ComplexityLevel
    rule_category: TaskCategory
    rule_risk: RiskLevel
    ml_prediction: MLPrediction | None
    backend_metadata: BackendMetadata
    resolved: ComplexityLevel
    resolution_reason: str
    mode: str
    ml_available: bool


@dataclass(frozen=True)
class ComplexityEvaluation:
    """Router 使用的完整返回值——同时包含 features 和 analysis。"""

    features: TaskFeatures
    analysis: ComplexityAnalysis
