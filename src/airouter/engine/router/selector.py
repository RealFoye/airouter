"""Selector：硬约束过滤 + 单模型评分。"""

from __future__ import annotations

import math
from dataclasses import dataclass

from airouter.config import ModelEntry, load_budgets, load_quality_defaults, load_routing_rules
from airouter.models.enums import ComplexityLevel, RiskLevel, SensitivityLevel, TaskCategory
from airouter.models.schemas import TaskFeatures

# ── 最低覆盖率阈值（按复杂度） ──────────────────────────────
MIN_COVERAGE_BY_COMPLEXITY: dict[ComplexityLevel, float] = {
    ComplexityLevel.SIMPLE: 0.50,
    ComplexityLevel.MODERATE: 0.70,
    ComplexityLevel.COMPLEX: 0.85,
    ComplexityLevel.EXPERT: 1.00,
}

# ── 能力权重 ────────────────────────────────────────────────
CAPABILITY_WEIGHTS: dict[str, float] = {
    "code_gen": 0.30,
    "complex_reasoning": 0.30,
    "architecture": 0.20,
    "code_review": 0.20,
    "security": 0.15,
    "scalability": 0.15,
    "documentation": 0.10,
    "test_generation": 0.10,
    "data_processing": 0.10,
    "formatting": 0.05,
}

MAX_LATENCY_MS = 5000


@dataclass
class CandidateScore:
    model: ModelEntry
    capability: float
    cost: float
    quality: float
    latency: float
    total_score: float


class ModelSelector:
    """模型选择器：硬约束过滤 + 多目标评分。"""

    def __init__(self):
        self._routing_rules = load_routing_rules()
        self._budgets = load_budgets()
        self._quality_defaults = load_quality_defaults()

    def filter_candidates(
        self, all_models: list[ModelEntry], features: TaskFeatures
    ) -> list[ModelEntry]:
        """硬约束过滤：排除不可用模型。"""
        allowed_tiers = self._get_allowed_tiers(features)

        candidates = []
        for model in all_models:
            # 1. 能力覆盖率（score == 0 表示不通过）
            if self._capability_score(model, features) == 0.0:
                continue

            # 2. 允许 Tier
            if model.tier not in allowed_tiers:
                continue

            # 3. 上下文窗口
            if model.max_context_window < features.estimated_input_tokens:
                continue

            # 4. 数据敏感性
            if features.sensitivity == SensitivityLevel.HIGH and not model.allow_sensitive_data:
                continue

            candidates.append(model)

        return candidates

    def score_models(
        self, candidates: list[ModelEntry], features: TaskFeatures
    ) -> list[CandidateScore]:
        """多目标评分：对候选模型计算综合得分。"""
        if not candidates:
            return []

        # 计算每个模型的基础成本
        costs = []
        for model in candidates:
            cost = self._estimate_single_cost(model, features)
            costs.append(cost)

        min_cost = min(costs) if costs else 1.0
        cost_sensitivity = self._get_cost_sensitivity(features.category)

        # 获取权重
        weights = self._get_weights(features.category)

        scored = []
        for model, cost in zip(candidates, costs):
            capability = self._capability_score(model, features)
            cost_score = self._normalize_cost(cost, min_cost, cost_sensitivity)
            quality = self._quality_score(model, features)
            latency = self._latency_score(model)

            total = (
                weights["capability"] * capability
                + weights["cost"] * cost_score
                + weights["quality"] * quality
                + weights["latency"] * latency
            )

            scored.append(CandidateScore(
                model=model,
                capability=capability,
                cost=cost_score,
                quality=quality,
                latency=latency,
                total_score=total,
            ))

        return sorted(scored, key=lambda x: x.total_score, reverse=True)

    def select_best(
        self, all_models: list[ModelEntry], features: TaskFeatures
    ) -> CandidateScore | None:
        """过滤 + 评分，返回最优候选。"""
        candidates = self.filter_candidates(all_models, features)
        if not candidates:
            return None
        scored = self.score_models(candidates, features)
        return scored[0] if scored else None

    def _capability_score(self, model: ModelEntry, features: TaskFeatures) -> float:
        """计算模型对任务的能力覆盖率。"""
        required = features.required_capabilities
        preferred = features.preferred_capabilities
        model_caps = set(model.capabilities)

        if not required:
            return 1.0

        # required 覆盖率（带权重）
        matched_required = model_caps & required
        total_weight = sum(CAPABILITY_WEIGHTS.get(c, 0.1) for c in required)
        matched_weight = sum(CAPABILITY_WEIGHTS.get(c, 0.1) for c in matched_required)
        required_coverage = matched_weight / total_weight if total_weight > 0 else 0.0

        # 高风险任务必须 100% 覆盖 required
        min_coverage = MIN_COVERAGE_BY_COMPLEXITY.get(features.complexity, 0.5)
        if required_coverage < min_coverage:
            return 0.0

        # preferred bonus（上限 0.05）
        matched_preferred = model_caps & preferred
        preferred_bonus = min(0.05, len(matched_preferred) * 0.01)
        preferred_coverage = (
            len(matched_preferred) / len(preferred) if preferred else 0.0
        )

        # 评分：required 占 85%，preferred 占 15%
        score = 0.85 * required_coverage + 0.15 * preferred_coverage + preferred_bonus
        return score

    def _estimate_single_cost(self, model: ModelEntry, features: TaskFeatures) -> float:
        """估算单模型成本。"""
        input_cost = (features.estimated_input_tokens / 1000.0) * model.input_price_per_1k
        output_cost = (features.estimated_output_tokens / 1000.0) * model.output_price_per_1k
        return input_cost + output_cost

    def _normalize_cost(
        self, cost: float, min_cost: float, sensitivity: str
    ) -> float:
        """成本归一化：3 种方式（linear/sqrt/log）。"""
        if cost <= 0 or min_cost <= 0:
            return 1.0

        ratio = min_cost / cost

        if sensitivity == "HIGH":
            return ratio  # linear
        elif sensitivity == "MEDIUM":
            return math.sqrt(ratio)  # sqrt
        else:
            return 1.0 / (1.0 + math.log(cost / min_cost)) if cost > min_cost else 1.0

    def _quality_score(self, model: ModelEntry, features: TaskFeatures) -> float:
        """质量先验得分。"""
        tier_key = f"tier{model.tier}"
        tier_quality = self._quality_defaults.default_quality.get(tier_key, {})
        category_key = features.category.value.lower()

        # 查找该 tier + category 的质量先验
        quality = tier_quality.get(category_key, 0.65)

        # 严重错误率惩罚
        failure_rates = self._quality_defaults.default_failure_rates
        failure_rate = failure_rates.get(tier_key, 0.10)

        return float(quality * (1.0 - failure_rate))

    def _latency_score(self, model: ModelEntry) -> float:
        """延迟得分：越低越好，归一化到 [0, 1]。"""
        latency = model.latency_estimate_ms
        return max(0.0, 1.0 - latency / MAX_LATENCY_MS)

    def _get_allowed_tiers(self, features: TaskFeatures) -> list[int]:
        """获取允许的 Tier 列表。"""
        complexity_key = features.complexity.value
        tier_rule = self._routing_rules.allowed_tiers.get(complexity_key)
        if not tier_rule:
            return [1, 2, 3]

        if features.risk_level == RiskLevel.HIGH:
            return list(tier_rule.high_risk)
        return list(tier_rule.default)

    def _get_weights(self, category: TaskCategory) -> dict[str, float]:
        """获取评分权重（按任务类型）。"""
        cat_key = category.value
        w = self._routing_rules.routing_weights.get(cat_key)
        if not w:
            w = self._routing_rules.routing_weights.get("default")

        if w:
            return {
                "capability": w.capability,
                "cost": w.cost,
                "quality": w.quality,
                "latency": w.latency,
            }
        return {"capability": 0.35, "cost": 0.30, "quality": 0.20, "latency": 0.15}

    def _get_cost_sensitivity(self, category: TaskCategory) -> str:
        """获取成本敏感度。"""
        result = self._routing_rules.cost_sensitivity_by_task_type.get(
            category.value, "MEDIUM"
        )
        return str(result)
