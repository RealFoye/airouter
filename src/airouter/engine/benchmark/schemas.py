"""Benchmark schemas for Level 1 offline rule validation."""

from __future__ import annotations

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
