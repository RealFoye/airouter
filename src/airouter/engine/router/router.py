"""Router facade：Analyzer → Classifier → Selector → Estimator → Gate 串联。

职责划分：
- Analyzer：任务特征提取
- Classifier：策略触发条件判断
- Selector：过滤 + 评分 + 策略级评分
- Estimator：成本预估
- Gate：管控门禁（决定能否自动执行）
"""

from __future__ import annotations

import hashlib

from airouter.config import load_all
from airouter.engine.complexity.analyzer import ComplexityAnalyzer
from airouter.engine.complexity.types import ComplexityAnalysis
from airouter.engine.router.analyzer import TaskAnalyzer
from airouter.engine.router.classifier import StrategyClassifier
from airouter.engine.router.estimator import CostEstimator
from airouter.engine.router.gate import GateInput, RoutingGate
from airouter.engine.router.selector import ModelSelector, StrategyScore
from airouter.models.enums import BudgetStatus, StrategyType
from airouter.models.model_registry import ModelRegistry
from airouter.models.schemas import (
    AlternativeStrategy,
    ComplexityDiagnostics,
    FallbackPolicy,
    ModelAssignment,
    RoutingDecision,
    TaskFeatures,
)


class Router:
    """路由引擎入口：任务描述 → 路由决策。"""

    def __init__(self):
        config = load_all()  # ComplexityConfig 在此一并加载
        self.rule_analyzer = TaskAnalyzer()
        self.analyzer = ComplexityAnalyzer(config.complexity, rule_analyzer=self.rule_analyzer)
        self.selector = ModelSelector()
        self.estimator = CostEstimator()
        self.registry = ModelRegistry(config.models)
        self.gate = RoutingGate()
        self.classifier = StrategyClassifier(
            human_review_required_tasks=self.selector._routing_rules.human_review_required_tasks,
        )
        self._routing_rules = self.selector._routing_rules
        self._config_version = "v1.1-ml-complexity"

    def route(self, task_description: str) -> RoutingDecision:
        """完整路由流程：分析 → 分类 → 过滤 → 策略评分 → 门禁 → 输出决策。"""
        # 第1层：任务画像（含复杂度诊断）
        eval_result = self.analyzer.analyze(task_description)
        features = eval_result.features
        complexity_analysis = eval_result.analysis
        diagnostics = self._to_diagnostics(complexity_analysis)

        # 策略分类
        classification = self.classifier.classify(features)

        # 第2-4层：策略级评分
        all_models = self.registry.all_models
        strategy_scores = self.selector.select_best_strategy(
            classification.strategies,
            all_models,
            features,
            self.estimator,
            classification.reasons,
        )

        if not strategy_scores:
            return self._escalate_to_human(features, "无候选策略满足条件", complexity_analysis=diagnostics)

        best = strategy_scores[0]

        # baseline 成本（全程 Tier 1）
        baseline_cost = self._calculate_baseline(features)
        savings = max(0.0, 1.0 - best.cost / baseline_cost) if baseline_cost > 0 else 0.0

        # quality baseline = 策略候选集中最高质量
        baseline_quality = max(s.quality for s in strategy_scores)
        quality_loss = round(max(0, baseline_quality - best.quality), 4)

        # 替代方案（不同策略类型）
        alternatives = self._build_strategy_alternatives(strategy_scores, best)

        # 第5层：管控门禁
        forced_review = features.category.value in self._routing_rules.human_review_required_tasks
        gate_input = GateInput(
            features=features,
            model_name=best.model_assignment.executor or "",
            model_tier=self._get_executor_tier(best),
            strategy=best.strategy,
            estimated_cost=best.cost,
            quality=best.quality,
            quality_loss_vs_baseline=quality_loss,
            budget_status=best.budget_status,
            forced_review_task=forced_review,
        )
        requires_review, review_reason = self.gate.check_human_review(gate_input)
        quality_gate = self.gate.build_quality_gate(features, requires_review)

        # 推荐理由
        reasons = self._build_reasons(features, best, savings)

        # Fallback
        fallback = self._build_fallback(strategy_scores)

        return RoutingDecision(
            task_hash=hashlib.md5(task_description.encode()).hexdigest()[:12],
            task_features=features,
            recommended_strategy=best.strategy,
            models=best.model_assignment,
            estimated_cost=round(best.cost, 4),
            baseline_cost=round(baseline_cost, 4),
            estimated_savings=round(savings, 4),
            estimated_quality=round(best.quality, 4),
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
            complexity_analysis=diagnostics,
        )

    def _escalate_to_human(
        self,
        features: TaskFeatures,
        reason: str,
        complexity_analysis: ComplexityDiagnostics | None = None,
    ) -> RoutingDecision:
        """条件5：无候选策略满足条件，兜底到人工。"""
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
            complexity_analysis=complexity_analysis,
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

    def _build_strategy_alternatives(
        self, scored: list[StrategyScore], best: StrategyScore
    ) -> list[AlternativeStrategy]:
        """构建替代策略列表（排除最优策略）。"""
        alternatives: list[AlternativeStrategy] = []
        seen_strategies = {best.strategy}
        for s in scored:
            if s.strategy in seen_strategies:
                continue
            if len(alternatives) >= 3:
                break
            seen_strategies.add(s.strategy)
            budget_note = ""
            if s.budget_status == BudgetStatus.OVER_HARD_BUDGET:
                budget_note = "（超硬预算，需审批）"
            elif s.budget_status == BudgetStatus.OVER_BUDGET:
                budget_note = "（超软预算）"
            alternatives.append(AlternativeStrategy(
                strategy=s.strategy,
                planner=s.model_assignment.planner,
                executor=s.model_assignment.executor,
                reviewer=s.model_assignment.reviewer,
                cost=round(s.cost, 4),
                quality=round(s.quality, 4),
                note=f"{s.strategy.value} 策略{budget_note}",
            ))
        return alternatives

    def _build_reasons(self, features, best: StrategyScore, savings) -> list[str]:
        reasons = [
            f"任务类别: {features.category.value}，复杂度: {features.complexity.value}",
            f"推荐策略: {best.strategy.value}",
        ]
        if best.model_assignment.planner:
            reasons.append(f"规划: {best.model_assignment.planner}")
        if best.model_assignment.executor:
            reasons.append(f"执行: {best.model_assignment.executor}")
        if best.model_assignment.reviewer:
            reasons.append(f"审查: {best.model_assignment.reviewer}")
        reasons.append(f"预估成本: ¥{best.cost:.4f}")
        if savings > 0.1:
            reasons.append(f"相比 Tier 1 基线节省 {savings*100:.0f}%")
        return reasons

    def _build_fallback(self, scored: list[StrategyScore]) -> list[FallbackPolicy]:
        policies = [
            FallbackPolicy(trigger="API_TIMEOUT", action="switch_to_same_tier_alternative"),
            FallbackPolicy(trigger="FORMAT_ERROR", action="retry_with_format_hint"),
            FallbackPolicy(trigger="QUALITY_BELOW", action="upgrade_tier"),
        ]
        if len(scored) <= 1:
            policies.append(FallbackPolicy(trigger="NO_CANDIDATE", action="escalate_to_human"))
        return policies

    def _get_executor_tier(self, best: StrategyScore) -> int:
        """从 StrategyScore 中提取 executor 的 tier。"""
        executor_name = best.model_assignment.executor
        if executor_name:
            model = self.registry.get_by_name(executor_name)
            if model:
                return int(model.tier)
        # fallback: 从 models_list 中找
        for m in best.models_list:
            if m.name == executor_name:
                return m.tier
        return 1

    @staticmethod
    def _to_diagnostics(analysis: ComplexityAnalysis) -> ComplexityDiagnostics:
        """将 ComplexityAnalysis dataclass 转换为 ComplexityDiagnostics Pydantic。"""
        ml = analysis.ml_prediction
        meta = analysis.backend_metadata
        return ComplexityDiagnostics(
            rule_complexity=analysis.rule_complexity.value,
            rule_category=analysis.rule_category.value,
            rule_risk=analysis.rule_risk.value,
            ml_raw_class=ml.raw_route_class if ml else None,
            ml_raw_confidence=ml.raw_confidence if ml else None,
            ml_final_class=ml.final_route_class if ml else None,
            ml_final_class_probability=ml.final_class_probability if ml else None,
            ml_probabilities=ml.probabilities if ml else None,
            ml_flags=ml.flags if ml else None,
            ml_margin=ml.margin if ml else None,
            ml_difficulty_score=ml.difficulty_score if ml else None,
            resolved=analysis.resolved.value,
            resolution_reason=analysis.resolution_reason,
            mode=analysis.mode,
            ml_available=analysis.ml_available,
            fallback_reason=meta.fallback_reason,
            ml_cold_start_ms=ml.cold_start_ms if ml else None,
            ml_latency_ms=ml.latency_ms if ml else None,
            ml_verification_ms=meta.verification_ms,
            ml_load_ms=meta.load_ms,
            ml_model_version=ml.model_version if ml else None,
            manifest_hash=meta.manifest_hash,
            config_version=meta.config_version,
        )
