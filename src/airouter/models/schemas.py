"""Pydantic schemas：TaskFeatures、RoutingDecision、ExecutionFeedback、BenchmarkResult、ConfigSnapshot。"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, model_validator

from airouter.models.enums import (
    BudgetStatus,
    ComplexityLevel,
    CompressionStrategy,
    ContentType,
    ContextLayer,
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


# ── ComplexityDiagnostics（ML 复杂度诊断） ─────────────────
class ComplexityDiagnostics(BaseModel):
    rule_complexity: str
    rule_category: str
    rule_risk: str
    ml_raw_class: Optional[str] = None
    ml_raw_confidence: Optional[float] = None
    ml_final_class: Optional[str] = None
    ml_final_class_probability: Optional[float] = None
    ml_probabilities: Optional[dict[str, float]] = None
    ml_flags: Optional[dict[str, bool]] = None
    ml_margin: Optional[float] = None
    ml_difficulty_score: Optional[float] = None
    resolved: str
    resolution_reason: str
    mode: str
    ml_available: bool
    fallback_reason: Optional[str] = None
    ml_cold_start_ms: Optional[float] = None
    ml_latency_ms: Optional[float] = None
    ml_verification_ms: Optional[float] = None
    ml_load_ms: Optional[float] = None
    ml_model_version: Optional[str] = None
    manifest_hash: Optional[str] = None
    config_version: Optional[str] = None


# ── RoutingDecision（路由决策输出） ──────────────────────────
class ModelAssignment(BaseModel):
    planner: Optional[str] = None
    executor: Optional[str] = None
    reviewer: Optional[str] = None


class AlternativeStrategy(BaseModel):
    strategy: StrategyType
    planner: Optional[str] = None
    executor: Optional[str] = None
    reviewer: Optional[str] = None
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
    complexity_analysis: Optional[ComplexityDiagnostics] = None


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
    latency_ms: int
    quality_score: Optional[float] = None
    severe_failure: bool = False
    gate_passed: Optional[bool] = None
    score_detail_json: Optional[dict] = None
    raw_output_path: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.now)


# ── ConfigSnapshot（配置快照） ───────────────────────────────
class ConfigSnapshot(BaseModel):
    config_version: str
    models_hash: str
    routing_rules_hash: str
    budgets_hash: str
    quality_defaults_hash: str
    compression_policy_hash: str
    merged_config_json: dict
    created_at: datetime = Field(default_factory=datetime.now)


# ── Audit Schemas（审计领域） ─────────────────────────────
class CostBreakdown(BaseModel):
    """消费分组项：用于 by_user / by_model / by_project 等维度。"""

    key: str
    total_cost: float
    total_calls: int
    percentage: float


class WastePattern(BaseModel):
    """浪费模式识别结果。"""

    pattern_type: str  # HIGH_TIER_ABUSE / DUPLICATE_CALLS / OVERLONG_CONTEXT / DOWNGRADABLE_NOT_DOWNGRADED / CACHE_OPPORTUNITY_MISSED
    scope: str  # user / project / department
    scope_value: str
    occurrence_count: int
    current_cost: float
    estimated_savings: float
    severity: str  # High / Medium / Low
    suggestion: str
    evidence_json: Optional[dict] = None  # 样例 task_hash、模型名、平均 input tokens 等


class AuditSummary(BaseModel):
    """审计查询结果汇总。"""

    start_date: datetime
    end_date: datetime
    total_cost: float
    total_calls: int
    total_input_tokens: int
    total_output_tokens: int
    daily_average: float
    by_user: list[CostBreakdown]
    by_model: list[CostBreakdown]
    by_project: list[CostBreakdown]
    by_department: list[CostBreakdown]
    by_task_type: list[CostBreakdown]
    top_waste_patterns: list[WastePattern]
    total_estimated_savings: float


# ── Token 估算 ──────────────────────────────────────────────


def estimate_tokens(text: str) -> int:
    """粗估 token 数：len(text)/3，非空文本至少 1。"""
    if not text:
        return 0
    return max(1, math.ceil(len(text) / 3))


# ── 上下文工程 Schema ─────────────────────────────────────


class ContextBlock(BaseModel):
    """上下文块：优先级层 + 内容类型 + Token 预算。"""

    layer: ContextLayer
    content_type: ContentType
    content: str
    token_count: int = 0
    protected: bool = False
    metadata: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def _auto_fill(self) -> ContextBlock:
        """SYSTEM_PROMPT/TASK_DESCRIPTION 天然受保护；token_count 非正数时自动计算。"""
        if self.layer in (ContextLayer.SYSTEM_PROMPT, ContextLayer.TASK_DESCRIPTION):
            self.protected = True
        if self.token_count <= 0:
            self.token_count = estimate_tokens(self.content)
        return self


class InputBreakdown(BaseModel):
    """Token 组成分析（对应设计文档 7.3 节）。"""

    system_prompt_tokens: int = 0
    tool_definitions_tokens: int = 0
    fixed_context_tokens: int = 0
    conversation_history_tokens: int = 0
    dynamic_query_tokens: int = 0

    @property
    def stable_prefix(self) -> int:
        """稳定前缀 = system_prompt + tool_definitions。"""
        return self.system_prompt_tokens + self.tool_definitions_tokens

    @property
    def total(self) -> int:
        return (
            self.system_prompt_tokens
            + self.tool_definitions_tokens
            + self.fixed_context_tokens
            + self.conversation_history_tokens
            + self.dynamic_query_tokens
        )


class OptimizationSuggestion(BaseModel):
    """单条优化建议。"""

    category: str  # "缓存" / "压缩" / "降级" / "裁剪" / "分层"
    title: str
    description: str
    estimated_savings: float  # 预估节省金额 (CNY)
    savings_percentage: float  # 占当前成本百分比
    details: dict = Field(default_factory=dict)


class OptimizeResult(BaseModel):
    """优化分析结果。"""

    current_strategy: StrategyType
    current_models: ModelAssignment
    current_cost: float
    estimated_output_tokens: int
    input_breakdown: InputBreakdown
    suggestions: list[OptimizationSuggestion]
    total_estimated_savings: float
    optimized_cost: float
    total_savings_percentage: float
    warnings: list[str] = Field(default_factory=list)


class CompressionResult(BaseModel):
    """压缩结果：前后对比 + 解释字段。"""

    strategy: CompressionStrategy
    original_tokens: int
    compressed_tokens: int
    reduction_rate: float
    blocks: list[ContextBlock]
    per_layer_tokens: dict[str, dict[str, int]]
    # 解释字段（支撑 optimize CLI）
    applied_actions: list[str] = Field(default_factory=list)
    dropped_blocks: list[ContextBlock] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
