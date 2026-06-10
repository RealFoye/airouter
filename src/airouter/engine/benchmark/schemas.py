"""Benchmark schemas for Level 1 offline rule validation, Level 2 model quality, and Level 3 backtest."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, Field


class BenchmarkCase(BaseModel):
    """Single benchmark test case."""

    id: str
    prompt: str
    expected_task_type: str
    expected_complexity: str
    expected_risk: str
    expected_strategy: str
    expected_executor_tier: int | None = None
    expected_planner_tier: int | None = None
    expected_reviewer_tier: int | None = None
    expected_requires_human_review: bool | None = None
    expected_quality_gate_contains: list[str] | None = None
    expected_budget_status: str | None = None
    expected_no_candidate: bool | None = None
    expected_fallback_contains: list[str] | None = None
    tags: list[str] = Field(default_factory=list)
    notes: str = ""


class CaseResult(BaseModel):
    """Result of running a single benchmark case."""

    case_id: str
    passed: bool
    failures: list[str] = Field(default_factory=list)
    actual_task_type: str = ""
    actual_complexity: str = ""
    actual_risk: str = ""
    actual_strategy: str = ""
    actual_executor: str | None = None
    actual_executor_tier: int | None = None
    actual_planner: str | None = None
    actual_planner_tier: int | None = None
    actual_reviewer: str | None = None
    actual_reviewer_tier: int | None = None
    actual_requires_human_review: bool = False
    actual_quality_gate: list[str] = Field(default_factory=list)
    actual_estimated_cost: float = 0.0
    actual_budget_status: str = ""
    actual_sensitivity: str = ""
    actual_task_hash: str = ""
    actual_fallback_triggers: list[str] = Field(default_factory=list)


class BenchmarkSummary(BaseModel):
    """Summary of benchmark run."""

    level: int = 1
    total_cases: int
    passed_cases: int
    failed_cases: int
    pass_rate: float
    metrics: dict[str, float] = Field(default_factory=dict)
    metric_targets: dict[str, float] = Field(default_factory=dict)
    metric_passed: dict[str, bool] = Field(default_factory=dict)
    failed_case_ids: list[str] = Field(default_factory=list)
    case_results: list[CaseResult] = Field(default_factory=list)
    all_passed: bool = False


# ── Level 2 schemas ──────────────────────────────────────────


class EvaluationCriterion(BaseModel):
    """Single evaluation criterion with any_of alias group."""

    id: str
    any_of: list[str] = Field(default_factory=list)


class L2Case(BaseModel):
    """Level 2 benchmark test case for real model quality evaluation."""

    id: str
    task_type: str
    complexity: str
    prompt: str
    scoring_type: str
    input_context: str = ""
    test_code: str = ""
    allow_execution: bool = False
    max_tokens: int | None = None
    evaluation_criteria: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)
    expected_issues: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    notes: str = ""


class ExecutorResult(BaseModel):
    """Executor return value with call metadata."""

    response_content: str
    input_tokens: int
    output_tokens: int
    latency_ms: int
    cost_cny: float
    attempts: int
    api_params: dict[str, Any] = Field(default_factory=dict)
    raw_usage: dict[str, Any] | None = None


class L2CaseResult(BaseModel):
    """Result of a single (case, model) pair in Level 2."""

    case_id: str
    model: str
    status: Literal["success", "failed", "skipped"]
    scoring_type: str
    overall_score: float = 0.0
    dimension_scores: dict[str, float] = Field(default_factory=dict)
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    cost_cny: float = 0.0
    raw_output_path: str = ""
    api_params: dict[str, Any] = Field(default_factory=dict)
    error_type: str | None = None
    error_message: str | None = None
    attempts: int = 1
    started_at: str = ""
    completed_at: str = ""
    details: dict[str, Any] = Field(default_factory=dict)
    response_metadata: dict[str, Any] = Field(default_factory=dict)


class L2Summary(BaseModel):
    """Summary of a Level 2 benchmark run."""

    level: int = 2
    run_id: str
    total_cases: int
    total_models: int
    total_api_calls: int
    total_input_tokens: int
    total_output_tokens: int
    total_cost_cny: float
    total_latency_ms: int
    model_scores: dict[str, float] = Field(default_factory=dict)
    task_type_scores: dict[str, float] = Field(default_factory=dict)
    complexity_scores: dict[str, float] = Field(default_factory=dict)
    task_model_matrix: dict[str, dict[str, float]] = Field(default_factory=dict)
    completed_pairs: int
    failed_pairs: int
    case_results: list[L2CaseResult] = Field(default_factory=list)
    run_completed: bool = False
    quality_passed: bool = False
    quality_threshold: float = 0.5


class FailedPair(BaseModel):
    """Record of a failed (case, model) pair."""

    pair: str
    error: str
    attempts: int = 1


class RunState(BaseModel):
    """Persistent state for Level 2 benchmark resume."""

    version: str = "2.0"
    run_id: str
    cases_path: str
    cases_hash: str
    started_at: str
    last_updated_at: str
    status: str = "running"
    models: list[str] = Field(default_factory=list)
    api_params: dict[str, Any] = Field(default_factory=dict)
    total_pairs: int = 0
    completed_pairs: int = 0
    failed_pairs: int = 0
    completed: list[str] = Field(default_factory=list)
    failed: list[FailedPair] = Field(default_factory=list)


@dataclass
class ScoreResult:
    """Auto-score result for a single (case, model_output) pair."""

    scoring_type: str
    overall_score: float
    dimension_scores: dict[str, float] = field(default_factory=dict)
    details: dict[str, Any] = field(default_factory=dict)


# ── Level 3 schemas ──────────────────────────────────────────


class BacktestCase(BaseModel):
    """Single case for Level 3 backtest, sourced from L1 or L2."""

    id: str
    source: Literal["L1", "L2"]
    prompt: str
    input_context: str = ""
    task_type: str = ""
    complexity: str = ""


class BacktestResult(BaseModel):
    """Result of backtesting a single case: Router cost vs baseline cost."""

    case_id: str
    source: str
    result_id: str
    prompt_hash: str
    has_executable_model: bool = True
    task_type: str = ""
    complexity: str = ""

    # Router recommendation
    router_strategy: str
    router_executor: str | None = None
    router_executor_tier: int | None = None
    router_planner: str | None = None
    router_reviewer: str | None = None
    raw_router_cost: float = 0.0
    effective_router_cost: float = 0.0
    router_quality_prior: float = 0.0
    router_quality_loss_prior: float = 0.0

    # Baseline
    baseline_model: str
    baseline_cost: float = 0.0

    # Comparison (can be negative, based on effective_router_cost)
    savings_cny: float = 0.0
    savings_rate: float = 0.0

    # Risk annotation
    risk_level: str = ""
    requires_human_review: bool = False
    downgrade_type: str = "none"
    downgrade_reason: str = ""
    exclusion_reason: str = ""


class BacktestSummary(BaseModel):
    """Summary of a Level 3 backtest run."""

    level: int = 3
    total_cases: int
    l1_cases: int
    l2_cases: int
    baseline_model: str
    quality_mode: str = "routing_prior"

    # Overview (all based on effective_router_cost)
    baseline_total_cost: float = 0.0
    router_total_cost: float = 0.0
    savings_total_cny: float = 0.0
    savings_rate: float = 0.0
    overspend_count: int = 0
    non_executable_count: int = 0
    approval_required_count: int = 0
    safe_downgrade_count: int = 0
    risky_downgrade_count: int = 0

    # Distributions
    strategy_distribution: dict[str, int] = Field(default_factory=dict)
    tier_distribution: dict[str, dict[str, int]] = Field(default_factory=dict)

    # Breakdowns
    by_source: dict[str, dict[str, Any]] = Field(default_factory=dict)
    by_task_type: dict[str, dict[str, Any]] = Field(default_factory=dict)

    # Downgrade suggestions
    safe_downgrades: list[dict[str, Any]] = Field(default_factory=list)
    risky_downgrades: list[dict[str, Any]] = Field(default_factory=list)

    # Overspend cases
    overspend_cases: list[dict[str, Any]] = Field(default_factory=list)

    # Non-executable cases
    non_executable_cases: list[dict[str, Any]] = Field(default_factory=list)

    # Per-case results
    case_results: list[BacktestResult] = Field(default_factory=list)

    disclaimer: str = (
        "Level 3 MVP uses routing priors and cost simulation only. "
        "Quality is risk-estimated, not measured. "
        "Measured quality can be attached from Level 2 results later. "
        "Savings for approval-required cases are potential savings assuming approval is granted."
    )


# ── LLM Judge schemas ────────────────────────────────────────


class JudgeResult(BaseModel):
    """Result of a single LLM judge evaluation."""

    case_id: str
    model: str
    judge_model: str
    task_type: str
    dimensions: dict[str, float] = Field(default_factory=dict)
    weighted_score: float = 0.0
    normalized_score: float = 0.0
    comment: str = ""
    model_truncated: bool = False
    judge_context_truncated: bool = False
    reasoning_starved: bool = False
    usage: dict[str, int] = Field(default_factory=dict)
    # Finance judge extensions
    rule_score: float | None = None
    rule_score_disagreement: str | None = None  # "agree" | "rule_too_high" | "rule_too_low" | "unclear"
    red_flags: list[str] = Field(default_factory=list)


class JudgeSummary(BaseModel):
    """Summary of an LLM judge run."""

    judge_model: str
    total_evaluations: int
    successful: int
    failed: int
    total_lines: int = 0
    duplicate_count: int = 0
    dedupe_strategy: str = "last_entry"
    model_truncated_count: int = 0
    judge_context_truncated_count: int = 0
    starved_count: int = 0
    by_model: dict[str, dict[str, float]] = Field(default_factory=dict)
    by_task_type: dict[str, dict[str, float]] = Field(default_factory=dict)
    estimated_cost_cny: float = 0.0
    results: list[JudgeResult] = Field(default_factory=list)


class PairwiseResult(BaseModel):
    """Result of a single pairwise A/B comparison."""

    case_id: str
    model_a: str
    model_b: str
    judge_model: str
    winner_label: str = ""
    winner_model: str | None = None
    reason: str = ""
    dimension_winners: dict[str, str] = Field(default_factory=dict)
    a_was_first: bool = True
    usage: dict[str, int] = Field(default_factory=dict)


class PairwiseSummary(BaseModel):
    """Summary of a pairwise judge run."""

    total_pairs: int
    total_judges: int
    total_calls: int
    successful: int = 0
    failed: int = 0
    total_lines: int = 0
    duplicate_count: int = 0
    dedupe_strategy: str = "last_entry"
    win_rates: dict[str, dict[str, float]] = Field(default_factory=dict)
    overall_ranking: list[dict[str, Any]] = Field(default_factory=list)
    agreement_rate: float = 0.0
    judge_agreement_detail: dict[str, int] = Field(default_factory=dict)
    estimated_cost_cny: float = 0.0
    results: list[PairwiseResult] = Field(default_factory=list)
