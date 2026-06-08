"""Level 1 benchmark runner: offline rule-based validation."""

from __future__ import annotations

from pathlib import Path

from airouter.config import load_models
from airouter.engine.benchmark.loader import load_cases
from airouter.engine.benchmark.schemas import BenchmarkSummary, CaseResult
from airouter.engine.benchmark.scorer import METRIC_TARGETS, compute_case_failures, compute_metrics
from airouter.engine.router.router import Router
from airouter.models.model_registry import ModelRegistry


class Level1BenchmarkRunner:
    """Run Level 1 offline benchmark against Router."""

    def __init__(self, cases_path: Path | None = None):
        self.cases_path = cases_path
        self.router = Router()
        self.registry = ModelRegistry(load_models())

    def run(self, fail_fast: bool = False) -> BenchmarkSummary:
        """Run all cases and return summary."""
        cases = load_cases(self.cases_path)
        results: list[CaseResult] = []

        for case in cases:
            result = self._run_case(case)
            results.append(result)
            if fail_fast and not result.passed:
                break

        # fail_fast 可能截断 results，metrics 分母应与执行的 case 数一致
        executed_cases = cases[: len(results)]
        return self._build_summary(executed_cases, results)

    def _run_case(self, case) -> CaseResult:
        """Run a single case through Router and score it."""
        decision = self.router.route(case.prompt)

        # Extract typed values from decision (avoid dict union-type issues)
        task_type: str = decision.task_features.category.value
        complexity: str = decision.task_features.complexity.value
        risk: str = decision.risk_level.value
        strategy: str = decision.recommended_strategy.value
        executor: str | None = decision.models.executor
        executor_tier: int | None = self._get_tier(decision.models.executor)
        planner: str | None = decision.models.planner
        planner_tier: int | None = self._get_tier(decision.models.planner)
        reviewer: str | None = decision.models.reviewer
        reviewer_tier: int | None = self._get_tier(decision.models.reviewer)
        requires_human_review: bool = decision.requires_human_review
        quality_gate: list[str] = decision.quality_gate
        estimated_cost: float = decision.estimated_cost
        budget_status: str = decision.budget_status.value
        sensitivity: str = decision.task_features.sensitivity.value
        task_hash: str = decision.task_hash
        fallback_triggers: list[str] = [p.trigger for p in decision.fallback_policy]

        actuals: dict[str, object] = {
            "task_type": task_type,
            "complexity": complexity,
            "risk": risk,
            "strategy": strategy,
            "executor": executor,
            "executor_tier": executor_tier,
            "planner": planner,
            "planner_tier": planner_tier,
            "reviewer": reviewer,
            "reviewer_tier": reviewer_tier,
            "requires_human_review": requires_human_review,
            "quality_gate": quality_gate,
            "estimated_cost": estimated_cost,
            "budget_status": budget_status,
            "sensitivity": sensitivity,
            "task_hash": task_hash,
            "fallback_triggers": fallback_triggers,
        }

        failures = compute_case_failures(case, actuals)

        return CaseResult(
            case_id=case.id,
            passed=len(failures) == 0,
            failures=failures,
            actual_task_type=task_type,
            actual_complexity=complexity,
            actual_risk=risk,
            actual_strategy=strategy,
            actual_executor=executor,
            actual_executor_tier=executor_tier,
            actual_planner=planner,
            actual_planner_tier=planner_tier,
            actual_reviewer=reviewer,
            actual_reviewer_tier=reviewer_tier,
            actual_requires_human_review=requires_human_review,
            actual_quality_gate=quality_gate,
            actual_estimated_cost=estimated_cost,
            actual_budget_status=budget_status,
            actual_sensitivity=sensitivity,
            actual_task_hash=task_hash,
            actual_fallback_triggers=fallback_triggers,
        )

    def _get_tier(self, model_name: str | None) -> int | None:
        """Look up model tier by name."""
        if not model_name:
            return None
        entry = self.registry.get_by_name(model_name)
        return entry.tier if entry else None

    def _build_summary(self, cases, results: list[CaseResult]) -> BenchmarkSummary:
        """Build summary with metrics."""
        passed = sum(1 for r in results if r.passed)
        failed = len(results) - passed
        failed_ids = [r.case_id for r in results if not r.passed]

        metrics = compute_metrics(cases, results)

        # Check if all metrics pass targets
        metric_passed = {}
        for name, value in metrics.items():
            target = METRIC_TARGETS.get(name, 0.0)
            metric_passed[name] = value >= target

        all_metrics_pass = all(metric_passed.values())
        all_cases_pass = failed == 0

        return BenchmarkSummary(
            level=1,
            total_cases=len(results),
            passed_cases=passed,
            failed_cases=failed,
            pass_rate=passed / len(results) if results else 0.0,
            metrics=metrics,
            metric_targets=dict(METRIC_TARGETS),
            metric_passed=metric_passed,
            failed_case_ids=failed_ids,
            case_results=results,
            all_passed=all_metrics_pass and all_cases_pass,
        )
