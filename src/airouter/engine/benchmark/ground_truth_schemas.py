"""Routing Ground Truth Benchmark schemas.

数据结构覆盖：Case 定义、单次评分结果、多次运行聚合、Oracle、策略回放、人工抽检。
complexity 仅做描述字段，不参与真值判定。真值来自模型实际输出质量。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

# ── 常量 ─────────────────────────────────────────────────────

CANDIDATE_MODELS: list[str] = [
    "qwen3.7-max",
    "qwen3.7-plus",
    "deepseek-v4-pro",
    "deepseek-v4-flash",
    "glm-5.1",
]

JUDGE_MODELS: list[str] = ["MiniMax-M3"]

PASS_THRESHOLDS: dict[str, float] = {
    "LOW": 0.80,
    "MEDIUM": 0.80,
    "HIGH": 0.85,
    "CRITICAL": 0.90,
}

# 评分维度默认权重（归一化到 1.0）
DEFAULT_DIMENSION_WEIGHTS: dict[str, float] = {
    "action_correctness": 0.15,
    "task_completion": 0.15,
    "risk_identified": 0.10,
    "evidence_quality": 0.10,
    "instruction_following": 0.15,
    "no_hallucination": 0.10,
    "clarification": 0.05,
    "human_approval": 0.05,
    "no_unrelated_changes": 0.10,
    "structured_compliance": 0.05,
}

# 按 category 覆盖维度权重
CATEGORY_WEIGHT_OVERRIDES: dict[str, dict[str, float]] = {
    "CODE_DEBUG": {"task_completion": 0.25, "structured_compliance": 0.03},
    "CODE_REVIEW": {"risk_identified": 0.20, "task_completion": 0.05},
    "LOG_OPS": {"evidence_quality": 0.20, "task_completion": 0.05},
    "TABLE_DATA": {"task_completion": 0.25, "risk_identified": 0.05},
    "DOC_UNDERSTANDING": {"evidence_quality": 0.20, "task_completion": 0.10},
    "PLANNING": {"evidence_quality": 0.15, "task_completion": 0.20},
    "TOOL_CALLING": {"instruction_following": 0.20, "risk_identified": 0.05},
    "INSTRUCTION_ANTIHALLU": {"no_hallucination": 0.25, "action_correctness": 0.20},
}

VALID_HOLDOUT_CATEGORIES: frozenset[str] = frozenset({
    "DOC_UNDERSTANDING",
    "TABLE_DATA",
    "CODE_DEBUG",
    "LOG_OPS",
    "MULTI_TURN",
    "TOOL_CALLING",
    "PLANNING",
    "INSTRUCTION_ANTIHALLU",
})

# 安全类 hard failure：一票否决（不受 2/3 多数投票保护）
SAFETY_HARD_FAILURES: frozenset[str] = frozenset({
    "modified_forbidden_file",
    "skipped_approval",
})
# 注意：harness_validation_failed 不在此集合中（使用 2/3 多数投票）

# ML raw class → 最便宜模型（独立基线，非 A 层策略）
CLASS_TO_CHEAPEST: dict[str, str] = {
    "R0": "deepseek-v4-flash",
    "R1": "qwen3.7-plus",
    "R2": "deepseek-v4-pro",
    "R3": "deepseek-v4-pro",
}


# ── 模型结构化输出 ──────────────────────────────────────────


class StructuredOutput(BaseModel):
    """被测模型应输出的 JSON 结构（通过 system prompt 要求）。

    action 取值：answer | propose_change | clarify | refuse
    """

    action: Literal["answer", "propose_change", "clarify", "refuse"] = "answer"
    summary: str = ""
    findings: list[str] = Field(default_factory=list)
    evidence: list[dict[str, str]] = Field(default_factory=list)
    modified_files: list[str] = Field(default_factory=list)
    patch: str = ""
    validation: dict[str, Any] = Field(default_factory=dict)
    clarification_questions: list[str] = Field(default_factory=list)
    approval_required: bool = False
    review_required: bool = False
    claims: list[str] = Field(default_factory=list)


# ── Case 内部块 ──────────────────────────────────────────────


class RoutingMessage(BaseModel):
    """多轮对话消息。"""

    role: Literal["user", "assistant"] = "user"
    content: str = ""


class RoutingMetadata(BaseModel):
    """Router/OpenSquilla 可见的上下文元数据。不含评分标准信息。"""

    history_messages: list[RoutingMessage] = Field(default_factory=list)
    prev_assistant_text: str | None = None
    prev_assistant_usage: dict[str, Any] | None = None
    n_tools: int = 0
    tool_result_length: int = 0


class EvaluationSpec(BaseModel):
    """评分器私有字段。不暴露给被测模型或 Router。"""

    primary: str = "rule_based"
    required_findings: list[str] = Field(default_factory=list)
    forbidden_findings: list[str] = Field(default_factory=list)
    required_outputs: list[str] = Field(default_factory=list)
    forbidden_outputs: list[str] = Field(default_factory=list)
    must_not_modify: list[str] = Field(default_factory=list)
    should_ask_clarification: bool = False
    requires_human_approval: bool = False


class TestFile(BaseModel):
    """沙箱测试文件（YAML 提供完整内容）。"""

    filename: str
    content: str


class GroundTruthData(BaseModel):
    """领域特定真值，用于确定性验证（L2）。"""

    expected_values: dict[str, Any] = Field(default_factory=dict)
    expected_fact_ids: list[str] = Field(default_factory=list)
    hidden_tests: list[str] = Field(default_factory=list)  # 旧字段保留但弃用
    test_files: list[TestFile] = Field(default_factory=list)  # 新字段
    allowed_root_causes: list[str] = Field(default_factory=list)
    evidence_line_ids: list[str] = Field(default_factory=list)
    expected_tools: list[dict[str, Any]] = Field(default_factory=list)
    required_history_refs: list[str] = Field(default_factory=list)
    allowed_claims: list[str] = Field(default_factory=list)
    forbidden_claims: list[str] = Field(default_factory=list)


class HarnessValidation(BaseModel):
    """沙箱验证配置（隐藏，不暴露给被测模型）。

    只执行 commands 中预定义的命令，绝不执行模型输出的 validation.commands。
    """

    commands: list[str] = Field(default_factory=list)
    timeout_s: int = 10
    expected_exit_code: int = 0


class StructuredOutputSpec(BaseModel):
    """Case 级结构化输出字段要求。"""

    required_fields: list[str] = Field(default_factory=lambda: ["action", "summary", "findings"])
    optional_fields: list[str] = Field(default_factory=lambda: ["patch", "validation", "modified_files"])


# ── Case 定义 ────────────────────────────────────────────────


class GroundTruthCase(BaseModel):
    """Ground Truth 测试用例。

    complexity / risk_level 仅描述性，不参与真值判定。
    routing_metadata 仅 Router 可见，evaluation_spec / ground_truth / harness_validation 仅评分器可见。
    """

    id: str
    domain: str = "GENERAL"
    category: str
    task_type: str = "ANALYSIS_ONLY"
    complexity: str = "MODERATE"
    risk_level: str = "LOW"
    prompt: str
    input_context: str = ""
    routing_metadata: RoutingMetadata = Field(default_factory=RoutingMetadata)
    expected_behavior: list[str] = Field(default_factory=list)
    forbidden_behavior: list[str] = Field(default_factory=list)
    evaluation: EvaluationSpec = Field(default_factory=EvaluationSpec)
    ground_truth: GroundTruthData = Field(default_factory=GroundTruthData)
    workspace_files: dict[str, str] = Field(default_factory=dict)
    harness_validation: HarnessValidation = Field(default_factory=HarnessValidation)
    structured_output: StructuredOutputSpec = Field(default_factory=StructuredOutputSpec)
    max_tokens: int = 4096
    tags: list[str] = Field(default_factory=list)
    notes: str = ""

    @property
    def pass_threshold(self) -> float:
        """按 risk_level 获取通过阈值。"""
        return PASS_THRESHOLDS.get(self.risk_level, 0.80)

    @property
    def is_high_risk(self) -> bool:
        return self.risk_level in ("HIGH", "CRITICAL")


# ── 单次评分结果 ─────────────────────────────────────────────


class GroundTruthCaseResult(BaseModel):
    """单次 (case, model) 评分结果。

    status 语义：
    - success: API 调用完成（模型输出可能质量差，但 API 成功了）
    - failed: API 层面失败（认证错误、网络超时、5xx）
    - incomplete: API 成功但沙箱不可用
    """

    case_id: str
    model: str
    run_index: int = 0
    dataset: Literal["dev", "holdout"] = "dev"
    status: Literal["success", "failed", "incomplete"] = "success"
    # ── 评分链 ──
    deterministic_passed: bool = False
    deterministic_score: float = 0.0
    rule_score: float = 0.0
    judge_score: float | None = None
    judge_model: str | None = None
    human_status: Literal["pending", "approved", "rejected", "skipped"] = "pending"
    final_score: float = 0.0
    # ── 硬失败 ──
    hard_failure_ids: list[str] = Field(default_factory=list)
    # ── 软违规 ──
    soft_violation_ids: list[str] = Field(default_factory=list)
    # ── 通过判定 ──
    pass_threshold: float = 0.80
    final_pass: bool = False
    # ── 维度明细 ──
    dimension_scores: dict[str, float] = Field(default_factory=dict)
    # ── 沙箱 ──
    sandbox_executed: bool = False
    sandbox_passed: bool | None = None
    sandbox_unavailable: bool = False
    # ── 成本 ──
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    estimated_cost_cny: float = 0.0
    billed_cost_cny: float | None = None
    cost_source: Literal["models.yaml", "cch_csv", "fallback"] = "models.yaml"
    # ── 原始输出 ──
    raw_output_path: str | None = None
    response_metadata: dict[str, Any] = Field(default_factory=dict)
    error_type: str | None = None
    error_message: str | None = None


# ── 多次运行聚合 ─────────────────────────────────────────────


class AggregatedModelResult(BaseModel):
    """多次运行聚合结果（每个 case×model pair 一条）。

    策略回放只读取聚合结果，不直接读 JSONL 中的单次结果。
    """

    case_id: str
    model: str
    run_count: int = 1
    median_score: float = 0.0
    median_cost_cny: float = 0.0
    pass_count: int = 0
    aggregated_pass: bool = False
    hard_failure_ids: list[str] = Field(default_factory=list)
    dimension_median_scores: dict[str, float] = Field(default_factory=dict)
    judge_median_score: float | None = None
    human_verdict: str | None = None
    final_pass: bool = False
    incomplete: bool = False


# ── Oracle ────────────────────────────────────────────────────


class OracleResult(BaseModel):
    """每个 case 的 Oracle 结果。

    oracle_model = 中位成本最低的及格模型。
    oracle_set = 成本距最低 ≤ max(5%, ¥0.005) 的及格模型集合。
    """

    case_id: str
    dataset: Literal["dev", "holdout"] = "dev"
    pass_threshold: float = 0.80
    # ── 通过模型（按中位成本升序）──
    passing_models: list[str] = Field(default_factory=list)
    passing_median_scores: dict[str, float] = Field(default_factory=dict)
    passing_pass_counts: dict[str, int] = Field(default_factory=dict)
    # ── Oracle 模型 ──
    oracle_model: str | None = None
    oracle_model_provisional: str | None = None
    oracle_model_final: str | None = None
    oracle_median_score: float | None = None
    # ── Oracle 集合 ──
    oracle_set: list[str] = Field(default_factory=list)
    oracle_set_cost_ceiling: float = 0.0
    # ── 全量数据 ──
    all_model_median_scores: dict[str, float] = Field(default_factory=dict)
    all_model_pass_counts: dict[str, int] = Field(default_factory=dict)
    hard_failure_models: list[str] = Field(default_factory=list)
    n_runs: int = 1
    # ── Oracle action ──
    oracle_action: str = "AUTO"


# ── 策略回放 ──────────────────────────────────────────────────


class StrategyReplayResult(BaseModel):
    """策略回放结果。

    layer: signal (A 层) 或 end_to_end (B 层)。
    主要指标：acceptable_match_rate, cost_regret, quality_regret。
    """

    strategy_name: str
    layer: Literal["signal", "end_to_end"] = "signal"
    dataset: Literal["dev", "holdout", "all"] = "all"
    ml_unavailable: bool = False
    # ── 主要指标 ──
    acceptable_match_rate: float = 0.0
    cost_regret: float = 0.0
    quality_regret: float = 0.0
    # ── 辅助指标 ──
    oracle_model_match_rate: float = 0.0
    avg_quality_score: float = 0.0
    quality_retention: float = 0.0
    total_estimated_cost_cny: float = 0.0
    total_billed_cost_cny: float | None = None
    # ── 安全指标 ──
    safety_violation_rate: float = 0.0
    high_risk_pass_rate: float = 0.0
    under_routing_rate: float = 0.0
    over_routing_rate: float = 0.0
    severe_under_routing_rate: float = 0.0
    # ── 路由行为 ──
    oracle_action_accuracy: float = 0.0
    over_escalation_rate: float = 0.0
    unsafe_auto_rate: float = 0.0
    per_case_results: list[dict[str, Any]] = Field(default_factory=list)


# ── 人工抽检 ──────────────────────────────────────────────────


class HumanAuditEntry(BaseModel):
    """人工抽检记录。

    human_verdict 语义：
    - PASS: 确认自动评分为通过
    - FAIL: 确认自动评分为失败
    - SCORER_FALSE_POSITIVE: 自动通过但人工认为应失败 → 覆盖 final_pass=False
    - SCORER_FALSE_NEGATIVE: 自动失败但人工认为应通过 → 覆盖 final_pass=True
    """

    case_id: str
    model: str
    run_indices: list[int] = Field(default_factory=list)
    human_verdict: Literal["PASS", "FAIL", "SCORER_FALSE_POSITIVE", "SCORER_FALSE_NEGATIVE"] = "PASS"
    human_comment: str | None = None
    auditor: str | None = None
    audited_at: str | None = None
    selection_reason: Literal[
        "high_risk", "hard_failure", "boundary", "disagreement", "random_20pct",
    ] = "random_20pct"


# ── 总体摘要 ──────────────────────────────────────────────────


class GroundTruthSummary(BaseModel):
    """Ground Truth Benchmark 总体摘要。

    API 调用量字段互斥，不重复计算：
    total_physical_api_calls = candidate_initial + candidate_rerun + judge_initial + judge_rerun + retry_attempts
    """

    run_id: str
    eval_frozen_at: str | None = None
    holdout_hash: str | None = None
    evaluation_manifest: dict[str, Any] | None = None
    total_cases: int = 0
    dev_cases: int = 0
    holdout_cases: int = 0
    models: list[str] = Field(default_factory=lambda: list(CANDIDATE_MODELS))
    judge_models: list[str] = Field(default_factory=lambda: list(JUDGE_MODELS))
    n_runs_per_case: int = 1
    oracle_results: list[OracleResult] = Field(default_factory=list)
    signal_strategy_results: list[StrategyReplayResult] = Field(default_factory=list)
    end_to_end_strategy_results: list[StrategyReplayResult] = Field(default_factory=list)
    dev_signal_results: list[StrategyReplayResult] = Field(default_factory=list)
    dev_e2e_results: list[StrategyReplayResult] = Field(default_factory=list)
    holdout_signal_results: list[StrategyReplayResult] = Field(default_factory=list)
    holdout_e2e_results: list[StrategyReplayResult] = Field(default_factory=list)
    # ── API 调用明细（互斥字段）──
    is_mock_run: bool = True
    mock_evaluations: int = 0
    candidate_initial_calls: int = 0
    candidate_rerun_calls: int = 0
    judge_initial_calls: int = 0
    judge_rerun_calls: int = 0
    retry_attempts: int = 0
    total_physical_api_calls: int = 0
    total_estimated_cost_cny: float = 0.0
    total_billed_cost_cny: float | None = None
    conclusions: list[str] = Field(default_factory=list)
    # ── 执行进度（--limit / resume）──
    expected_pairs: int = 0
    completed_before: int = 0
    new_pairs_this_run: int = 0
    completed_after: int = 0
    remaining_pairs: int = 0
    complete_cases: int = 0
    run_completed: bool = False
    analysis_deferred: bool = False
    # ── Judge 统计 ──
    mock_judge_evaluations: int = 0
    judge_calls: int = 0
    judge_retry_attempts: int = 0
    judge_degraded: bool = False
