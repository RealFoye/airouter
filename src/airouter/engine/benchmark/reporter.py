"""Level 3 backtest reporter: cost simulation comparing Router vs baseline Tier 1."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from airouter.engine.benchmark.schemas import BacktestResult, BacktestSummary
from airouter.engine.router.estimator import CostEstimator
from airouter.models.model_registry import ModelRegistry

_SAFE_COMPLEXITIES = {"SIMPLE", "MODERATE"}
_MAX_QUALITY_LOSS_FOR_SAFE = 0.15
_OVERSPEND_EPSILON = 1e-9


class Level3BacktestReporter:
    """Builds Level 3 backtest report: baseline cost vs Router cost."""

    def __init__(self, registry: ModelRegistry, baseline_model: str = "qwen3.7-max"):
        self._registry = registry
        self._baseline_model_name = baseline_model

        entry = registry.get_by_name(baseline_model)
        if entry is None:
            available = [m.name for m in registry.all_models]
            raise ValueError(
                f"Unknown baseline model: {baseline_model}. "
                f"Available models: {', '.join(available)}"
            )
        if entry.tier != 1:
            t1_models = [m.name for m in registry.all_models if m.tier == 1]
            raise ValueError(
                f"Baseline model must be Tier 1, got {baseline_model} (tier={entry.tier}). "
                f"Available Tier 1 models: {', '.join(t1_models)}"
            )
        self._baseline_entry = entry
        self._estimator = CostEstimator()

    @property
    def baseline_model(self) -> str:
        return self._baseline_model_name

    def compute_baseline_cost(self, features: Any) -> float:
        """Compute baseline cost using the Tier 1 model for given task features."""
        estimate = self._estimator.estimate(
            self._baseline_entry,
            features.estimated_input_tokens,
            features.estimated_output_tokens,
        )
        return estimate.total_cost

    def classify_downgrade(self, decision: Any) -> tuple[str, str]:
        """Classify a routing decision as safe / risky / none downgrade.

        Returns (downgrade_type, reason).
        """
        executor = decision.models.executor
        if executor is None:
            return "none", "no executable model"

        entry = self._registry.get_by_name(executor)
        if entry is None:
            return "none", f"unknown executor: {executor}"

        tier = entry.tier
        if tier <= 1:
            return "none", "executor is Tier 1, no downgrade"

        # Tier > 1: classify as safe or risky
        risk = decision.risk_level.value if hasattr(decision.risk_level, "value") else str(decision.risk_level)
        complexity = (
            decision.task_features.complexity.value
            if hasattr(decision.task_features.complexity, "value")
            else str(decision.task_features.complexity)
        )
        requires_review = decision.requires_human_review
        quality_loss = decision.quality_loss_vs_baseline

        reasons: list[str] = []
        is_safe = True

        if risk != "LOW":
            is_safe = False
            reasons.append(f"risk={risk}")
        if requires_review:
            is_safe = False
            reasons.append("requires_human_review")
        if complexity not in _SAFE_COMPLEXITIES:
            is_safe = False
            reasons.append(f"complexity={complexity}")
        if quality_loss > _MAX_QUALITY_LOSS_FOR_SAFE:
            is_safe = False
            reasons.append(f"quality_loss={quality_loss:.2f}")

        if is_safe:
            return "safe", f"tier={tier}, low risk, no review needed"
        else:
            return "risky", f"tier={tier}, " + ", ".join(reasons)

    def build_summary(self, results: list[BacktestResult]) -> BacktestSummary:
        """Build BacktestSummary from a list of BacktestResult."""
        l1_results = [r for r in results if r.source == "L1"]
        l2_results = [r for r in results if r.source == "L2"]

        # Aggregate totals (all based on effective_router_cost)
        baseline_total = sum(r.baseline_cost for r in results)
        router_total = sum(r.effective_router_cost for r in results)
        savings_total = baseline_total - router_total
        savings_rate = savings_total / baseline_total if baseline_total > 0 else 0.0

        # Counts
        overspend_count = sum(1 for r in results if r.savings_cny < -_OVERSPEND_EPSILON)
        non_executable_count = sum(1 for r in results if not r.has_executable_model)
        approval_required_count = sum(
            1 for r in results if r.has_executable_model and r.requires_human_review
        )
        safe_count = sum(1 for r in results if r.downgrade_type == "safe")
        risky_count = sum(1 for r in results if r.downgrade_type == "risky")

        # Strategy distribution
        strategy_dist: dict[str, int] = defaultdict(int)
        for r in results:
            strategy_dist[r.router_strategy] += 1

        # Tier distribution (executor tier)
        tier_dist: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for r in results:
            tier_label = f"tier_{r.router_executor_tier}" if r.router_executor_tier else "none"
            tier_dist[r.source][tier_label] += 1
        tier_dist_serializable = {k: dict(v) for k, v in tier_dist.items()}

        # By source
        by_source = self._build_by_source(results)

        # By task type
        by_task_type = self._build_by_task_type(results)

        # Downgrade lists
        safe_downgrades = [
            {
                "case_id": r.case_id,
                "source": r.source,
                "strategy": r.router_strategy,
                "executor": r.router_executor,
                "tier": r.router_executor_tier,
                "reason": r.downgrade_reason,
            }
            for r in results
            if r.downgrade_type == "safe"
        ]
        risky_downgrades = [
            {
                "case_id": r.case_id,
                "source": r.source,
                "strategy": r.router_strategy,
                "executor": r.router_executor,
                "tier": r.router_executor_tier,
                "reason": r.downgrade_reason,
            }
            for r in results
            if r.downgrade_type == "risky"
        ]

        # Overspend list
        overspend_cases = [
            {
                "case_id": r.case_id,
                "source": r.source,
                "baseline_cost": r.baseline_cost,
                "router_cost": r.effective_router_cost,
                "savings_cny": r.savings_cny,
            }
            for r in results
            if r.savings_cny < -_OVERSPEND_EPSILON
        ]

        # Non-executable list
        non_executable_cases = [
            {
                "case_id": r.case_id,
                "source": r.source,
                "reason": r.exclusion_reason,
                "baseline_cost": r.baseline_cost,
            }
            for r in results
            if not r.has_executable_model
        ]

        return BacktestSummary(
            total_cases=len(results),
            l1_cases=len(l1_results),
            l2_cases=len(l2_results),
            baseline_model=self._baseline_model_name,
            baseline_total_cost=baseline_total,
            router_total_cost=router_total,
            savings_total_cny=savings_total,
            savings_rate=savings_rate,
            overspend_count=overspend_count,
            non_executable_count=non_executable_count,
            approval_required_count=approval_required_count,
            safe_downgrade_count=safe_count,
            risky_downgrade_count=risky_count,
            strategy_distribution=dict(strategy_dist),
            tier_distribution=tier_dist_serializable,
            by_source=by_source,
            by_task_type=by_task_type,
            safe_downgrades=safe_downgrades,
            risky_downgrades=risky_downgrades,
            overspend_cases=overspend_cases,
            non_executable_cases=non_executable_cases,
            case_results=results,
        )

    def _build_by_source(self, results: list[BacktestResult]) -> dict[str, dict[str, Any]]:
        """Build per-source breakdown."""
        sources: dict[str, list[BacktestResult]] = defaultdict(list)
        for r in results:
            sources[r.source].append(r)

        by_source: dict[str, dict[str, Any]] = {}
        for source, source_results in sources.items():
            baseline = sum(r.baseline_cost for r in source_results)
            router = sum(r.effective_router_cost for r in source_results)
            savings = baseline - router
            rate = savings / baseline if baseline > 0 else 0.0
            by_source[source] = {
                "cases": len(source_results),
                "baseline_cost": baseline,
                "router_cost": router,
                "savings_cny": savings,
                "savings_rate": rate,
            }
        return by_source

    def _build_by_task_type(self, results: list[BacktestResult]) -> dict[str, dict[str, Any]]:
        """Build per-task-type breakdown."""
        task_types: dict[str, list[BacktestResult]] = defaultdict(list)
        for r in results:
            key = r.task_type or "UNKNOWN"
            task_types[key].append(r)

        by_task: dict[str, dict[str, Any]] = {}
        for task, task_results in task_types.items():
            baseline = sum(r.baseline_cost for r in task_results)
            router = sum(r.effective_router_cost for r in task_results)
            savings = baseline - router
            rate = savings / baseline if baseline > 0 else 0.0
            by_task[task] = {
                "cases": len(task_results),
                "baseline_cost": baseline,
                "router_cost": router,
                "savings_cny": savings,
                "savings_rate": rate,
            }
        return by_task
