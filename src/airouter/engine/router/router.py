"""Router facade：Analyzer → Selector → Estimator 串联。"""

from __future__ import annotations

import hashlib

from airouter.config import ModelEntry, load_all
from airouter.engine.router.analyzer import TaskAnalyzer
from airouter.engine.router.estimator import CostEstimator
from airouter.engine.router.selector import ModelSelector
from airouter.models.enums import BudgetStatus, StrategyType
from airouter.models.model_registry import ModelRegistry
from airouter.models.schemas import (
    AlternativeStrategy,
    FallbackPolicy,
    ModelAssignment,
    RoutingDecision,
    TaskFeatures,
)


class Router:
    """路由引擎入口：任务描述 → 路由决策。"""

    def __init__(self):
        self.analyzer = TaskAnalyzer()
        self.selector = ModelSelector()
        self.estimator = CostEstimator()
        config = load_all()
        self.registry = ModelRegistry(config.models)
        self._config_version = "v1.0"

    def route(self, task_description: str) -> RoutingDecision:
        """完整路由流程：分析 → 过滤 → 评分 → 预估 → 输出决策。"""
        # 第1层：任务画像
        features = self.analyzer.extract_features(task_description)

        # 第2层 + 第4层：硬约束过滤 + 评分
        all_models = self.registry.all_models
        best = self.selector.select_best(all_models, features)

        if best is None:
            return self._escalate_to_human(features, "无候选模型满足硬约束")

        # 成本预估
        cost_est = self.estimator.estimate(
            best.model, features.estimated_input_tokens, features.estimated_output_tokens
        )

        # baseline 成本（用同 tier 最贵模型）
        baseline_cost = self._calculate_baseline(features)
        savings = max(0.0, 1.0 - cost_est.total_cost / baseline_cost) if baseline_cost > 0 else 0.0

        # 质量估计
        quality = best.quality

        # 替代方案
        scored = self.selector.score_models(
            self.selector.filter_candidates(all_models, features), features
        )
        alternatives = self._build_alternatives(scored, features, best.model)

        # 预算状态
        budget_status = self._check_budget(features, cost_est.total_cost)

        # 人工审核
        requires_review, review_reason = self._check_human_review(
            features, best.model, budget_status, quality
        )

        # 推荐理由
        reasons = self._build_reasons(features, best, cost_est, savings)

        # 质量门禁
        quality_gate = self._build_quality_gate(features)

        # Fallback
        fallback = self._build_fallback(scored, best.model)

        return RoutingDecision(
            task_hash=hashlib.md5(task_description.encode()).hexdigest()[:12],
            task_features=features,
            recommended_strategy=StrategyType.SINGLE_MODEL,
            models=ModelAssignment(executor=best.model.name),
            estimated_cost=round(cost_est.total_cost, 4),
            baseline_cost=round(baseline_cost, 4),
            estimated_savings=round(savings, 4),
            estimated_quality=round(quality, 4),
            quality_loss_vs_baseline=round(max(0, 0.90 - quality), 4),
            risk_level=features.risk_level,
            requires_human_review=requires_review,
            human_review_reason=review_reason,
            reasons=reasons,
            alternatives=alternatives,
            budget_status=budget_status,
            quality_gate=quality_gate,
            fallback_policy=fallback,
            config_version=self._config_version,
        )

    def _escalate_to_human(self, features: TaskFeatures, reason: str) -> RoutingDecision:
        return RoutingDecision(
            task_hash="escalate",
            task_features=features,
            recommended_strategy=StrategyType.SINGLE_MODEL,
            models=ModelAssignment(),
            estimated_cost=0.0,
            baseline_cost=0.0,
            estimated_savings=0.0,
            estimated_quality=0.0,
            quality_loss_vs_baseline=0.0,
            risk_level=features.risk_level,
            requires_human_review=True,
            human_review_reason=reason,
            reasons=[reason],
            alternatives=[],
            budget_status=BudgetStatus.OK,
            quality_gate=["human_review"],
            fallback_policy=[FallbackPolicy(trigger="NO_CANDIDATE", action="escalate_to_human")],
            config_version=self._config_version,
        )

    def _calculate_baseline(self, features: TaskFeatures) -> float:
        """Baseline = 最贵 Tier 1 模型的成本。"""
        tier1_models = self.registry.get_tier1_models()
        if not tier1_models:
            return 0.0
        max_cost = 0.0
        for m in tier1_models:
            est = self.estimator.estimate(m, features.estimated_input_tokens, features.estimated_output_tokens)
            max_cost = max(max_cost, est.total_cost)
        return max_cost

    def _build_alternatives(
        self,
        scored: list,
        features: TaskFeatures,
        best_model: ModelEntry,
    ) -> list[AlternativeStrategy]:
        alternatives = []
        for cs in scored:
            if cs.model.name == best_model.name:
                continue
            est = self.estimator.estimate(
                cs.model, features.estimated_input_tokens, features.estimated_output_tokens
            )
            alternatives.append(AlternativeStrategy(
                strategy=StrategyType.SINGLE_MODEL,
                model=cs.model.name,
                cost=round(est.total_cost, 4),
                quality=round(cs.quality, 4),
                note=f"Tier {cs.model.tier} 模型",
            ))
        return alternatives[:3]

    def _check_budget(self, features: TaskFeatures, cost: float) -> BudgetStatus:
        budgets = self.selector._budgets
        complexity_key = features.complexity.value
        task_limit = budgets.task_type_limits.get(complexity_key)
        if task_limit and cost > task_limit.max_cost_cny:
            return BudgetStatus.OVER_BUDGET
        if task_limit and cost > task_limit.max_cost_cny * 0.8:
            return BudgetStatus.WARNING
        return BudgetStatus.OK

    def _check_human_review(
        self,
        features: TaskFeatures,
        model: ModelEntry,
        budget_status: BudgetStatus,
        quality: float,
    ) -> tuple[bool, str | None]:
        reasons = []

        if features.sensitivity.value == "HIGH":
            reasons.append("任务涉及敏感数据")

        if budget_status == BudgetStatus.OVER_BUDGET:
            reasons.append("预估成本超过任务预算上限")

        if features.category.value in self.selector._routing_rules.human_review_required_tasks:
            reasons.append(f"{features.category.value} 类型任务需要人工审核")

        if reasons:
            return True, "；".join(reasons)
        return False, None

    def _build_reasons(self, features, best, cost_est, savings) -> list[str]:
        reasons = [
            f"任务类别: {features.category.value}，复杂度: {features.complexity.value}",
            f"推荐模型: {best.model.name} (Tier {best.model.tier})",
            f"预估成本: ¥{cost_est.total_cost:.4f}",
        ]
        if savings > 0.1:
            reasons.append(f"相比 Tier 1 基线节省 {savings*100:.0f}%")
        return reasons

    def _build_quality_gate(self, features: TaskFeatures) -> list[str]:
        base_gates = {
            "CODE_GENERATION": ["syntax_check", "ast_parse"],
            "DATA_PROCESSING": ["json_schema_check"],
            "CODE_REVIEW": ["issue_coverage_check"],
            "BUG_ANALYSIS": ["fix_verification"],
            "DOCUMENTATION": ["completeness_check"],
            "ARCHITECTURE": ["human_review"],
            "TEST_GENERATION": ["syntax_check"],
            "REFACTORING": ["syntax_check", "ast_parse"],
            "DEVOPS": ["syntax_check"],
            "CONVERSATION": [],
        }
        gates = list(base_gates.get(features.category.value, []))
        if features.risk_level.value == "HIGH":
            gates.append("human_review")
        return list(set(gates))

    def _build_fallback(self, scored, best_model) -> list[FallbackPolicy]:
        policies = [
            FallbackPolicy(trigger="API_TIMEOUT", action="switch_to_same_tier_alternative"),
            FallbackPolicy(trigger="FORMAT_ERROR", action="retry_with_format_hint"),
            FallbackPolicy(trigger="QUALITY_BELOW", action="upgrade_tier"),
        ]
        # 如果有其他候选，加 NO_CANDIDATE fallback
        if len(scored) <= 1:
            policies.append(FallbackPolicy(trigger="NO_CANDIDATE", action="escalate_to_human"))
        return policies
