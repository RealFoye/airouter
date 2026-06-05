"""Pydantic schemas：TaskFeatures、RoutingDecision、ExecutionFeedback、BenchmarkResult、ConfigSnapshot。"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from airouter.models.enums import (
    BudgetStatus,
    ComplexityLevel,
    ContextLevel,
    OutputStrictnessLevel,
    ReasoningLevel,
    RiskLevel,
    SensitivityLevel,
    StrategyType,
    TaskCategory,
    VerifiabilityLevel,
)


# ── TaskFeatures（13维特征） ─────────────────────────────────
class TaskFeatures(BaseModel):
    # 基础分类
    category: TaskCategory
    complexity: ComplexityLevel

    # 风险与约束
    risk_level: RiskLevel = RiskLevel.MEDIUM
    sensitivity: SensitivityLevel = SensitivityLevel.LOW
    verifiability: VerifiabilityLevel = VerifiabilityLevel.MEDIUM
    output_strictness: OutputStrictnessLevel = OutputStrictnessLevel.MEDIUM

    # 资源需求
    context_requirement: ContextLevel = ContextLevel.STANDARD
    reasoning_intensity: ReasoningLevel = ReasoningLevel.MEDIUM
    estimated_input_tokens: int = Field(default=2000, ge=0)
    estimated_output_tokens: int = Field(default=500, ge=0)

    # 结构特征
    subtasks: list[str] = Field(default_factory=list)
    required_capabilities: set[str] = Field(default_factory=set)
    preferred_capabilities: set[str] = Field(default_factory=set)


# ── CAPABILITY_REQUIREMENTS（10类别 × 4复杂度 = 40条） ──────
# (category, complexity) → (required_capabilities, preferred_capabilities)
CAPABILITY_REQUIREMENTS: dict[tuple[TaskCategory, ComplexityLevel], tuple[set[str], set[str]]] = {
    # CODE_GENERATION
    (TaskCategory.CODE_GENERATION, ComplexityLevel.SIMPLE): (
        {"code_gen"}, {"documentation"}
    ),
    (TaskCategory.CODE_GENERATION, ComplexityLevel.MODERATE): (
        {"code_gen"}, {"documentation", "test_generation"}
    ),
    (TaskCategory.CODE_GENERATION, ComplexityLevel.COMPLEX): (
        {"code_gen", "complex_reasoning"}, {"architecture", "test_generation"}
    ),
    (TaskCategory.CODE_GENERATION, ComplexityLevel.EXPERT): (
        {"code_gen", "complex_reasoning", "architecture"}, {"security", "scalability"}
    ),

    # CODE_REVIEW
    (TaskCategory.CODE_REVIEW, ComplexityLevel.SIMPLE): (
        {"code_review", "code_gen"}, set()
    ),
    (TaskCategory.CODE_REVIEW, ComplexityLevel.MODERATE): (
        {"code_review", "code_gen"}, {"security"}
    ),
    (TaskCategory.CODE_REVIEW, ComplexityLevel.COMPLEX): (
        {"code_review", "code_gen", "complex_reasoning"}, {"security", "architecture"}
    ),
    (TaskCategory.CODE_REVIEW, ComplexityLevel.EXPERT): (
        {"code_review", "code_gen", "complex_reasoning", "security"}, {"architecture"}
    ),

    # REFACTORING
    (TaskCategory.REFACTORING, ComplexityLevel.SIMPLE): (
        {"code_gen", "code_review"}, set()
    ),
    (TaskCategory.REFACTORING, ComplexityLevel.MODERATE): (
        {"code_gen", "code_review"}, {"complex_reasoning"}
    ),
    (TaskCategory.REFACTORING, ComplexityLevel.COMPLEX): (
        {"code_gen", "code_review", "complex_reasoning"}, {"architecture"}
    ),
    (TaskCategory.REFACTORING, ComplexityLevel.EXPERT): (
        {"code_gen", "code_review", "complex_reasoning", "architecture"}, {"scalability"}
    ),

    # BUG_ANALYSIS
    (TaskCategory.BUG_ANALYSIS, ComplexityLevel.SIMPLE): (
        {"code_gen"}, {"code_review"}
    ),
    (TaskCategory.BUG_ANALYSIS, ComplexityLevel.MODERATE): (
        {"code_gen", "complex_reasoning"}, {"code_review"}
    ),
    (TaskCategory.BUG_ANALYSIS, ComplexityLevel.COMPLEX): (
        {"code_gen", "complex_reasoning"}, {"code_review", "architecture"}
    ),
    (TaskCategory.BUG_ANALYSIS, ComplexityLevel.EXPERT): (
        {"code_gen", "complex_reasoning", "code_review"}, {"security", "architecture"}
    ),

    # DOCUMENTATION
    (TaskCategory.DOCUMENTATION, ComplexityLevel.SIMPLE): (
        {"documentation"}, set()
    ),
    (TaskCategory.DOCUMENTATION, ComplexityLevel.MODERATE): (
        {"documentation"}, {"code_gen"}
    ),
    (TaskCategory.DOCUMENTATION, ComplexityLevel.COMPLEX): (
        {"documentation", "code_gen"}, {"architecture"}
    ),
    (TaskCategory.DOCUMENTATION, ComplexityLevel.EXPERT): (
        {"documentation", "code_gen", "complex_reasoning"}, {"architecture"}
    ),

    # ARCHITECTURE
    (TaskCategory.ARCHITECTURE, ComplexityLevel.SIMPLE): (
        {"architecture"}, {"code_gen"}
    ),
    (TaskCategory.ARCHITECTURE, ComplexityLevel.MODERATE): (
        {"architecture", "code_gen"}, {"complex_reasoning"}
    ),
    (TaskCategory.ARCHITECTURE, ComplexityLevel.COMPLEX): (
        {"architecture", "complex_reasoning", "code_gen"}, {"scalability", "security"}
    ),
    (TaskCategory.ARCHITECTURE, ComplexityLevel.EXPERT): (
        {"architecture", "complex_reasoning"}, {"security", "scalability"}
    ),

    # TEST_GENERATION
    (TaskCategory.TEST_GENERATION, ComplexityLevel.SIMPLE): (
        {"test_generation", "code_gen"}, set()
    ),
    (TaskCategory.TEST_GENERATION, ComplexityLevel.MODERATE): (
        {"test_generation", "code_gen"}, {"code_review"}
    ),
    (TaskCategory.TEST_GENERATION, ComplexityLevel.COMPLEX): (
        {"test_generation", "code_gen", "complex_reasoning"}, {"code_review"}
    ),
    (TaskCategory.TEST_GENERATION, ComplexityLevel.EXPERT): (
        {"test_generation", "code_gen", "complex_reasoning"}, {"code_review", "architecture"}
    ),

    # DATA_PROCESSING
    (TaskCategory.DATA_PROCESSING, ComplexityLevel.SIMPLE): (
        {"data_processing"}, set()
    ),
    (TaskCategory.DATA_PROCESSING, ComplexityLevel.MODERATE): (
        {"data_processing", "code_gen"}, set()
    ),
    (TaskCategory.DATA_PROCESSING, ComplexityLevel.COMPLEX): (
        {"data_processing", "code_gen", "complex_reasoning"}, {"architecture"}
    ),
    (TaskCategory.DATA_PROCESSING, ComplexityLevel.EXPERT): (
        {"data_processing", "code_gen", "complex_reasoning"}, {"architecture", "scalability"}
    ),

    # DEVOPS
    (TaskCategory.DEVOPS, ComplexityLevel.SIMPLE): (
        {"data_processing"}, {"code_gen"}
    ),
    (TaskCategory.DEVOPS, ComplexityLevel.MODERATE): (
        {"data_processing", "code_gen"}, {"architecture"}
    ),
    (TaskCategory.DEVOPS, ComplexityLevel.COMPLEX): (
        {"data_processing", "code_gen", "architecture"}, {"scalability", "security"}
    ),
    (TaskCategory.DEVOPS, ComplexityLevel.EXPERT): (
        {"data_processing", "code_gen", "architecture", "complex_reasoning"}, {"security", "scalability"}
    ),

    # CONVERSATION
    (TaskCategory.CONVERSATION, ComplexityLevel.SIMPLE): (
        {"complex_reasoning"}, set()
    ),
    (TaskCategory.CONVERSATION, ComplexityLevel.MODERATE): (
        {"complex_reasoning"}, {"documentation"}
    ),
    (TaskCategory.CONVERSATION, ComplexityLevel.COMPLEX): (
        {"complex_reasoning"}, {"code_gen", "documentation"}
    ),
    (TaskCategory.CONVERSATION, ComplexityLevel.EXPERT): (
        {"complex_reasoning", "code_gen"}, {"architecture", "documentation"}
    ),
}


# ── RoutingDecision（路由决策输出） ──────────────────────────
class ModelAssignment(BaseModel):
    planner: Optional[str] = None
    executor: Optional[str] = None
    reviewer: Optional[str] = None


class AlternativeStrategy(BaseModel):
    strategy: StrategyType
    model: Optional[str] = None
    cost: float
    quality: float
    note: str


class FallbackPolicy(BaseModel):
    trigger: str
    action: str


class RoutingDecision(BaseModel):
    task_hash: str
    task_features: TaskFeatures
    recommended_strategy: StrategyType
    models: ModelAssignment
    estimated_cost: float
    baseline_cost: float
    estimated_savings: float
    estimated_quality: float
    quality_loss_vs_baseline: float
    risk_level: RiskLevel
    requires_human_review: bool
    human_review_reason: Optional[str] = None
    reasons: list[str]
    alternatives: list[AlternativeStrategy]
    budget_status: BudgetStatus
    quality_gate: list[str]
    fallback_policy: list[FallbackPolicy]
    config_version: str
    created_at: datetime = Field(default_factory=datetime.now)


# ── ExecutionFeedback（执行反馈） ────────────────────────────
class ExecutionFeedback(BaseModel):
    routing_decision_id: int
    executed_strategy: Optional[str] = None
    executed_models_json: Optional[list[str]] = None
    actual_input_tokens: int
    actual_output_tokens: int
    actual_cost_cny: float
    actual_latency_ms: int
    quality_score: Optional[float] = None
    quality_gate_passed: Optional[bool] = None
    user_accepted: Optional[bool] = None
    user_override_reason: Optional[str] = None
    user_override_note: Optional[str] = None
    actual_calls_json: Optional[list[dict]] = None
    error_type: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.now)


# ── BenchmarkResult（Benchmark 结果） ────────────────────────
class BenchmarkResult(BaseModel):
    suite_name: str  # level1_offline / level2_comparison / level3_strategy
    suite_version: Optional[str] = None
    case_id: str
    case_version: Optional[str] = None
    task_type: TaskCategory
    complexity: ComplexityLevel
    model_or_strategy: str
    models_json: Optional[list[str]] = None
    input_tokens: int
    output_tokens: int
    cost_cny: float
    actual_latency_ms: int
    quality_score: Optional[float] = None
    severe_failure: bool = False
    gate_passed: Optional[bool] = None
    score_detail_json: Optional[dict] = None
    raw_output_path: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.now)


# ── ConfigSnapshot（配置快照） ───────────────────────────────
class ConfigSnapshot(BaseModel):
    config_version: str
    models_config_hash: str
    routing_rules_hash: str
    budgets_hash: str
    quality_defaults_hash: str
    compression_policy_hash: str
    merged_config_json: dict
    created_at: datetime = Field(default_factory=datetime.now)
