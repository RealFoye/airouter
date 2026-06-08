"""Benchmark schemas for Level 1 offline rule validation and Level 2 model quality."""

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
