"""Router facade：Analyzer → Selector → Estimator → Gate 串联。

职责划分：
- Analyzer：任务特征提取
- Selector：过滤 + 评分（推荐最优候选）
- Estimator：成本预估
- Gate：管控门禁（决定能否自动执行）
"""

from __future__ import annotations

import hashlib

from airouter.config import ModelEntry, load_all
from airouter.engine.router.analyzer import TaskAnalyzer
from airouter.engine.router.estimator import CostEstimator
from airouter.engine.router.gate import GateInput, RoutingGate
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
        self.gate = RoutingGate()
        self._routing_rules = self.selector._routing_rules
        self._config_version = "v1.0"

    def route(self, task_description: str) -> RoutingDecision:
        """完整路由流程：分析 → 过滤 → 评分 → 预估 → 门禁 → 输出决策。"""
        # 第1层：任务画像
        features = self.analyzer.extract_features(task_description)

        # 第2层 + 第4层：硬约束过滤 + 评分
        all_models = self.registry.all_models
        best = self.selector.select_best(all_models, features)

        if best is None:
            return self._escalate_to_human(features, "无候选模型满足硬约束")

        # 成本预估（用 Estimator 的精细成本，而非 Selector 的原始成本）
        cost_est = self.estimator.estimate(
            best.model, features.estimated_input_tokens, features.estimated_output_tokens
        )

        # baseline 成本（用同 tier 最贵模型）
        baseline_cost = self._calculate_baseline(features)
        savings = max(0.0, 1.0 - cost_est.total_cost / baseline_cost) if baseline_cost > 0 else 0.0

        # 质量估计
        quality = best.quality

        # 替代方案（带预算标签）
        scored = self.selector.score_models(
            self.selector.filter_candidates(all_models, features), features
        )
        alternatives = self._build_alternatives(scored, features, best.model)

        # quality baseline = 候选集中最高质量（通过硬约束后的所有候选）
        # 注意：cost baseline 和 quality baseline 使用不同基准（见 pitfalls.md 坑6）
        baseline_quality = max(cs.quality for cs in scored) if scored else quality
        quality_loss = round(max(0, baseline_quality - quality), 4)

        # 第5层：管控门禁
        # 预算状态来自 Selector 的候选级标签
        forced_review = features.category.value in self._routing_rules.human_review_required_tasks
        gate_input = GateInput(
            features=features,
            model_name=best.model.name,
            model_tier=best.model.tier,
            strategy=StrategyType.SINGLE_MODEL,
            estimated_cost=cost_est.total_cost,
            quality=quality,
            quality_loss_vs_baseline=quality_loss,
            budget_status=best.budget_status,
            forced_review_task=forced_review,
        )
        requires_review, review_reason = self.gate.check_human_review(gate_input)
        quality_gate = self.gate.build_quality_gate(features, requires_review)

        # 推荐理由
        reasons = self._build_reasons(features, best, cost_est, savings)

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
            quality_loss_vs_baseline=quality_loss,
            risk_level=features.risk_level,
            requires_human_review=requires_review,
            human_review_reason=review_reason,
            reasons=reasons,
            alternatives=alternatives,
            budget_status=best.budget_status,
            quality_gate=quality_gate,
            fallback_policy=fallback,
            config_version=self._config_version,
        )

    def _escalate_to_human(self, features: TaskFeatures, reason: str) -> RoutingDecision:
        """条件5：无候选模型满足硬约束，兜底到人工。"""
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
            budget_note = ""
            if cs.budget_status == BudgetStatus.OVER_HARD_BUDGET:
                budget_note = "（超硬预算，需审批）"
            elif cs.budget_status == BudgetStatus.OVER_BUDGET:
                budget_note = "（超软预算）"
            alternatives.append(AlternativeStrategy(
                strategy=StrategyType.SINGLE_MODEL,
                model=cs.model.name,
                cost=round(est.total_cost, 4),
                quality=round(cs.quality, 4),
                note=f"Tier {cs.model.tier} 模型{budget_note}",
            ))
        return alternatives[:3]

    def _build_reasons(self, features, best, cost_est, savings) -> list[str]:
        reasons = [
            f"任务类别: {features.category.value}，复杂度: {features.complexity.value}",
            f"推荐模型: {best.model.name} (Tier {best.model.tier})",
            f"预估成本: ¥{cost_est.total_cost:.4f}",
        ]
        if savings > 0.1:
            reasons.append(f"相比 Tier 1 基线节省 {savings*100:.0f}%")
        return reasons

    def _build_fallback(self, scored, best_model) -> list[FallbackPolicy]:
        policies = [
            FallbackPolicy(trigger="API_TIMEOUT", action="switch_to_same_tier_alternative"),
            FallbackPolicy(trigger="FORMAT_ERROR", action="retry_with_format_hint"),
            FallbackPolicy(trigger="QUALITY_BELOW", action="upgrade_tier"),
        ]
        if len(scored) <= 1:
            policies.append(FallbackPolicy(trigger="NO_CANDIDATE", action="escalate_to_human"))
        return policies
