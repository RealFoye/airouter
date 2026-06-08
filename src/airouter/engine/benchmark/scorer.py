"""Benchmark scoring: case failure detection and metric computation."""

from __future__ import annotations

import math

from airouter.engine.benchmark.schemas import BenchmarkCase, CaseResult

METRIC_TARGETS = {
    "classification_accuracy": 0.90,
    "complexity_accuracy": 0.85,
    "role_tier_accuracy": 0.95,
    "strategy_selection_accuracy": 0.85,
    "cost_estimation_reasonableness": 0.90,
    "constraint_satisfaction": 1.00,
}

# Cost upper bounds by complexity (lenient, only catches outliers)
COST_UPPER_BOUNDS = {
    "SIMPLE": 0.50,
    "MODERATE": 2.00,
    "COMPLEX": 10.00,
    "EXPERT": 50.00,
}

# Tasks that always require human review
HUMAN_REVIEW_REQUIRED_TASKS = {"ARCHITECTURE"}


def compute_case_failures(case: BenchmarkCase, actuals: dict) -> list[str]:
    """Compare expected vs actual for a single case, return list of failure descriptions."""
    failures: list[str] = []

    # Exact match fields
    _check_exact(failures, "task_type", case.expected_task_type, actuals.get("task_type", ""))
    _check_exact(failures, "complexity", case.expected_complexity, actuals.get("complexity", ""))
    _check_exact(failures, "risk", case.expected_risk, actuals.get("risk", ""))
    _check_exact(failures, "strategy", case.expected_strategy, actuals.get("strategy", ""))

    # Tier checks (only if expected is set)
    if case.expected_executor_tier is not None:
        actual = actuals.get("executor_tier")
        if actual != case.expected_executor_tier:
            failures.append(f"executor_tier: expected {case.expected_executor_tier}, got {actual}")

    if case.expected_planner_tier is not None:
        actual = actuals.get("planner_tier")
        if actual != case.expected_planner_tier:
            failures.append(f"planner_tier: expected {case.expected_planner_tier}, got {actual}")

    if case.expected_reviewer_tier is not None:
        actual = actuals.get("reviewer_tier")
        if actual != case.expected_reviewer_tier:
            failures.append(f"reviewer_tier: expected {case.expected_reviewer_tier}, got {actual}")

    # requires_human_review (only if expected is set)
    if case.expected_requires_human_review is not None:
        actual = actuals.get("requires_human_review", False)
        if actual != case.expected_requires_human_review:
            failures.append(
                f"requires_human_review: expected {case.expected_requires_human_review}, got {actual}"
            )

    # quality_gate_contains (subset check)
    if case.expected_quality_gate_contains:
        actual_gates = set(actuals.get("quality_gate", []))
        for gate in case.expected_quality_gate_contains:
            if gate not in actual_gates:
                failures.append(f"quality_gate missing '{gate}' (expected to contain {case.expected_quality_gate_contains})")

    # budget_status (exact match, optional)
    if case.expected_budget_status:
        _check_exact(failures, "budget_status", case.expected_budget_status, actuals.get("budget_status", ""))

    # no_candidate (check task_hash == "escalate")
    if case.expected_no_candidate is not None:
        task_hash = actuals.get("task_hash", "")
        is_escalate = task_hash == "escalate"
        if case.expected_no_candidate and not is_escalate:
            failures.append(f"expected no candidate (task_hash='escalate'), got task_hash='{task_hash}'")
        elif not case.expected_no_candidate and is_escalate:
            failures.append("expected candidate available, but got escalate")

    # fallback_contains (subset check on triggers)
    if case.expected_fallback_contains:
        actual_triggers = set(actuals.get("fallback_triggers", []))
        for trigger in case.expected_fallback_contains:
            if trigger not in actual_triggers:
                failures.append(
                    f"fallback_policy missing trigger '{trigger}' (expected {case.expected_fallback_contains})"
                )

    return failures


def compute_metrics(cases: list[BenchmarkCase], results: list[CaseResult]) -> dict[str, float]:
    """Compute 6 benchmark metrics."""
    if not cases or not results:
        return {k: 0.0 for k in METRIC_TARGETS}

    metrics: dict[str, float] = {}

    # classification_accuracy
    correct = sum(1 for c, r in zip(cases, results) if r.actual_task_type == c.expected_task_type)
    metrics["classification_accuracy"] = correct / len(cases)

    # complexity_accuracy
    correct = sum(1 for c, r in zip(cases, results) if r.actual_complexity == c.expected_complexity)
    metrics["complexity_accuracy"] = correct / len(cases)

    # role_tier_accuracy: all expected tier assertions across all three roles
    total_tier_assertions = 0
    correct_tier_assertions = 0
    for c, r in zip(cases, results):
        if c.expected_executor_tier is not None:
            total_tier_assertions += 1
            if r.actual_executor_tier == c.expected_executor_tier:
                correct_tier_assertions += 1
        if c.expected_planner_tier is not None:
            total_tier_assertions += 1
            if r.actual_planner_tier == c.expected_planner_tier:
                correct_tier_assertions += 1
        if c.expected_reviewer_tier is not None:
            total_tier_assertions += 1
            if r.actual_reviewer_tier == c.expected_reviewer_tier:
                correct_tier_assertions += 1
    metrics["role_tier_accuracy"] = (
        correct_tier_assertions / total_tier_assertions if total_tier_assertions > 0 else 1.0
    )

    # strategy_selection_accuracy
    correct = sum(1 for c, r in zip(cases, results) if r.actual_strategy == c.expected_strategy)
    metrics["strategy_selection_accuracy"] = correct / len(cases)

    # cost_estimation_reasonableness: skip expected_no_candidate=true cases
    cost_cases = [(c, r) for c, r in zip(cases, results) if not c.expected_no_candidate]
    if cost_cases:
        reasonable = 0
        for c, r in cost_cases:
            cost = r.actual_estimated_cost
            if cost <= 0 or math.isnan(cost):
                continue
            upper = COST_UPPER_BOUNDS.get(r.actual_complexity, 50.0)
            if cost <= upper:
                reasonable += 1
        metrics["cost_estimation_reasonableness"] = reasonable / len(cost_cases)
    else:
        metrics["cost_estimation_reasonableness"] = 1.0

    # constraint_satisfaction (hard constraints, per-case binary)
    violated_cases = 0
    for c, r in zip(cases, results):
        if _count_constraint_violations(c, r) > 0:
            violated_cases += 1
    total_constraint_checks = len(cases)
    metrics["constraint_satisfaction"] = (
        (total_constraint_checks - violated_cases) / total_constraint_checks
        if total_constraint_checks > 0
        else 1.0
    )

    return metrics


def _check_exact(failures: list[str], field: str, expected: str, actual: str) -> None:
    if expected != actual:
        failures.append(f"{field}: expected '{expected}', got '{actual}'")


def _count_constraint_violations(case: BenchmarkCase, result: CaseResult) -> int:
    """Count hard constraint violations for a single case.

    Constraints:
    1. EXPERT task must not use Tier 3 executor
    2. SIMPLE + LOW risk + sensitivity != HIGH + category not in forced review → must NOT have requires_human_review
    3. requires_human_review=true → quality_gate must contain "human_review"
    """
    violations = 0

    # Constraint 1: EXPERT + Tier 3 executor
    if result.actual_complexity == "EXPERT" and result.actual_executor_tier == 3:
        violations += 1

    # Constraint 2: SIMPLE + LOW + sensitivity != HIGH + not forced review → no human review
    is_simple_low = (
        result.actual_complexity == "SIMPLE" and result.actual_risk == "LOW"
    )
    sensitivity_not_high = result.actual_sensitivity != "HIGH"
    not_forced_review = result.actual_task_type not in HUMAN_REVIEW_REQUIRED_TASKS
    if (
        is_simple_low
        and sensitivity_not_high
        and not_forced_review
        and result.actual_requires_human_review
    ):
        violations += 1

    # Constraint 3: requires_human_review=true → quality_gate contains "human_review"
    if result.actual_requires_human_review and "human_review" not in result.actual_quality_gate:
        violations += 1

    return violations
