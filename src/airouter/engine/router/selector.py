"""Selector：硬约束过滤 + 单模型评分 + 策略级评分。"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from airouter.config import (
    ModelEntry,
    load_budgets,
    load_quality_defaults,
    load_routing_rules,
)
from airouter.models.enums import (
    BudgetStatus,
    ComplexityLevel,
    RiskLevel,
    SensitivityLevel,
    StrategyType,
    TaskCategory,
)
from airouter.models.schemas import ModelAssignment, TaskFeatures

# ── 执行级能力需求（executor 角色专用，不要求 architecture 等全局能力） ──
EXECUTOR_CAPABILITY_REQUIREMENTS: dict[TaskCategory, set[str]] = {
    TaskCategory.CODE_GENERATION: {"code_gen"},
    TaskCategory.CODE_REVIEW: {"code_gen"},
    TaskCategory.REFACTORING: {"code_gen"},
    TaskCategory.BUG_ANALYSIS: {"code_gen"},
    TaskCategory.DOCUMENTATION: {"documentation"},
    TaskCategory.ARCHITECTURE: {"code_gen"},
    TaskCategory.TEST_GENERATION: {"test_generation"},
    TaskCategory.DATA_PROCESSING: {"data_processing"},
    TaskCategory.DEVOPS: {"data_processing"},
    TaskCategory.CONVERSATION: set(),
}

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
    budget_status: BudgetStatus = BudgetStatus.OK
    requires_approval: bool = False


@dataclass
class StrategyScore:
    """策略级评分：Router/Gate 消费的对象。"""

    strategy: StrategyType
    model_assignment: ModelAssignment
    models_list: list[ModelEntry] = field(default_factory=list)
    capability: float = 0.0
    cost: float = 0.0
    quality: float = 0.0
    latency: float = 0.0
    total_score: float = 0.0
    budget_status: BudgetStatus = BudgetStatus.OK
    trigger_reasons: dict[str, str] = field(default_factory=dict)


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

            # 5. 预算约束（soft/hard 两层，标记但不排除）
            # 设计 4.2.3：每个候选都应带预算状态
            # 此处仅标记，实际 budget_status 在 score_models 中写入 CandidateScore
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

            # 候选级预算标签（设计 4.2.3 第 5 项）
            budget_status, requires_approval = self._compute_budget_status(cost, features)

            scored.append(CandidateScore(
                model=model,
                capability=capability,
                cost=cost_score,
                quality=quality,
                latency=latency,
                total_score=total,
                budget_status=budget_status,
                requires_approval=requires_approval,
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

    # ── 策略级方法 ────────────────────────────────────────────

    def select_top_k_per_tier(
        self, candidates: list[ModelEntry], features: TaskFeatures
    ) -> dict[int, list[ModelEntry]]:
        """按 top_k_by_tier 配置，每个 tier 取 pre_score 最高的 K 个。"""
        # 按 tier 分组
        by_tier: dict[int, list[ModelEntry]] = {}
        for m in candidates:
            by_tier.setdefault(m.tier, []).append(m)

        result: dict[int, list[ModelEntry]] = {}
        for tier_key in ("tier1", "tier2", "tier3"):
            tier_num = int(tier_key[-1])
            tier_models = by_tier.get(tier_num, [])
            if not tier_models:
                continue

            top_k_cfg = self._routing_rules.top_k_by_tier.get(tier_key)
            k = top_k_cfg.k if top_k_cfg else 2
            pre_weights = top_k_cfg.pre_score if top_k_cfg else {
                "capability": 0.40, "quality": 0.30, "cost": 0.30
            }

            # 计算 pre_score 并排序
            scored = []
            for m in tier_models:
                cap = self._capability_score(m, features)
                qual = self._quality_score(m, features)
                cost = self._estimate_single_cost(m, features)
                # cost 归一化：越小越好
                cost_score = 1.0 / (1.0 + cost) if cost > 0 else 1.0
                pre = (
                    pre_weights.get("capability", 0) * cap
                    + pre_weights.get("quality", 0) * qual
                    + pre_weights.get("cost", 0) * cost_score
                )
                scored.append((pre, m))

            scored.sort(key=lambda x: x[0], reverse=True)
            result[tier_num] = [m for _, m in scored[:k]]

        return result

    def select_best_strategy(
        self,
        strategy_types: list[StrategyType],
        all_models: list[ModelEntry],
        features: TaskFeatures,
        estimator,
        classifier_reasons: dict[str, str] | None = None,
    ) -> list[StrategyScore]:
        """生成并评分所有策略候选，返回按 total_score 排序的列表。

        包含 post-filter：quality_loss > 15% 排除，非 SINGLE 且 savings < 15% 排除。
        savings baseline 使用 Tier 1 单模型成本（与 Router baseline 一致）。
        """
        # 基础过滤（上下文 + 敏感性，不过滤 tier）
        base_candidates = self._filter_base(all_models, features)

        # 按角色取模型池（含角色级能力过滤）
        role_pool = self._build_role_pool(base_candidates, features)

        # Top-K per tier（在每个角色池内做 Top-K）
        for role in role_pool:
            if role_pool[role]:
                top_k = self.select_top_k_per_tier(role_pool[role], features)
                role_pool[role] = [m for models in top_k.values() for m in models]

        # Tier 1 baseline 成本（用于 savings 计算）
        tier1_baseline = self._compute_tier1_baseline(all_models, features, estimator)

        # 生成策略候选
        candidates: list[StrategyScore] = []
        for st in strategy_types:
            scores = self._build_strategy_candidates(
                st, role_pool, features, estimator, classifier_reasons or {}
            )
            candidates.extend(scores)

        if not candidates:
            return []

        # Post-filter（硬性排除）
        baseline_quality = max(c.quality for c in candidates)

        filtered = []
        for c in candidates:
            # quality_loss > 15% → 排除
            quality_loss = baseline_quality - c.quality
            if quality_loss > 0.15:
                continue
            # 非 SINGLE 且 savings < 15% → 排除（使用 Tier 1 baseline）
            if c.strategy != StrategyType.SINGLE_MODEL and tier1_baseline > 0:
                savings = (tier1_baseline - c.cost) / tier1_baseline
                if savings < 0.15:
                    continue
            filtered.append(c)

        # 硬性过滤：如果全被排除，返回空列表（让 Router 走 escalate_to_human）
        if not filtered:
            return []

        # 归一化成本并计算最终分数
        min_cost = min(c.cost for c in filtered)
        cost_sensitivity = self._get_cost_sensitivity(features.category)
        weights = self._get_weights(features.category)

        for c in filtered:
            cost_score = self._normalize_cost(c.cost, min_cost, cost_sensitivity)
            c.total_score = (
                weights["capability"] * c.capability
                + weights["cost"] * cost_score
                + weights["quality"] * c.quality
                + weights["latency"] * c.latency
            )
            # 预算标签
            c.budget_status, _ = self._compute_budget_status(c.cost, features)

        filtered.sort(key=lambda x: x.total_score, reverse=True)
        return filtered

    # ── 内部策略方法 ──────────────────────────────────────────

    def _filter_base(
        self, all_models: list[ModelEntry], features: TaskFeatures
    ) -> list[ModelEntry]:
        """基础过滤：只保留通用硬约束（上下文窗口 + 敏感性）。

        能力过滤下沉到 _build_role_pool()，按角色做差异化。
        """
        result = []
        for m in all_models:
            if m.max_context_window < features.estimated_input_tokens:
                continue
            if features.sensitivity == SensitivityLevel.HIGH and not m.allow_sensitive_data:
                continue
            result.append(m)
        return result

    def _build_role_pool(
        self, base_candidates: list[ModelEntry], features: TaskFeatures
    ) -> dict[str, list[ModelEntry]]:
        """按角色构建模型池，包含角色级能力过滤。

        planner/reviewer/single：用任务级 _capability_score()
        executor：用执行级能力（不要求 architecture 等全局能力）
        """
        allowed_tiers = self._get_allowed_tiers(features)
        executor_tier = self._get_executor_tier(features.risk_level)

        # 任务级能力过滤（planner/reviewer/single）
        task_capable = [m for m in base_candidates if self._capability_score(m, features) > 0.0]

        # 执行级能力过滤（executor）
        executor_required = EXECUTOR_CAPABILITY_REQUIREMENTS.get(features.category, set())
        if executor_required:
            exec_capable = [m for m in base_candidates if executor_required.issubset(set(m.capabilities))]
        else:
            exec_capable = base_candidates

        pool: dict[str, list[ModelEntry]] = {
            "planner": [m for m in task_capable if m.tier == 1],
            "reviewer": [m for m in task_capable if m.tier == 1],
            "executor": [m for m in exec_capable if m.tier in executor_tier],
            "single": [m for m in task_capable if m.tier in allowed_tiers],
        }
        return pool

    def _get_executor_tier(self, risk_level: RiskLevel) -> list[int]:
        """Plan-Execute 执行模型 tier 选择（设计文档 4.3.1）。"""
        if risk_level == RiskLevel.LOW:
            return [3]
        return [2]  # MEDIUM 和 HIGH 都用 Tier 2

    def _build_strategy_candidates(
        self,
        strategy: StrategyType,
        pool: dict[str, list[ModelEntry]],
        features: TaskFeatures,
        estimator,
        classifier_reasons: dict[str, str],
    ) -> list[StrategyScore]:
        """为一种策略类型生成候选评分。"""

        if strategy == StrategyType.SINGLE_MODEL:
            return self._build_single_model_candidates(pool, features, estimator, classifier_reasons)

        if strategy == StrategyType.GUIDED_EXECUTE:
            return self._build_guided_candidates(pool, features, estimator, classifier_reasons)

        if strategy == StrategyType.PLAN_EXECUTE:
            return self._build_plan_execute_candidates(pool, features, estimator, classifier_reasons)

        if strategy == StrategyType.PLAN_EXECUTE_REVIEW:
            return self._build_per_candidates(pool, features, estimator, classifier_reasons)

        return []

    def _build_single_model_candidates(
        self, pool, features, estimator, classifier_reasons
    ) -> list[StrategyScore]:
        singles = pool["single"]
        if not singles:
            return []
        scored = self.score_models(singles, features)
        results = []
        for cs in scored[:3]:  # 最多 3 个 SINGLE 候选
            est = estimator.estimate(cs.model, features.estimated_input_tokens, features.estimated_output_tokens)
            results.append(StrategyScore(
                strategy=StrategyType.SINGLE_MODEL,
                model_assignment=ModelAssignment(executor=cs.model.name),
                models_list=[cs.model],
                capability=cs.capability,
                cost=est.total_cost,
                quality=cs.quality,
                latency=cs.latency,
                total_score=cs.total_score,
                budget_status=cs.budget_status,
                trigger_reasons=classifier_reasons,
            ))
        return results

    def _build_guided_candidates(
        self, pool, features, estimator, classifier_reasons
    ) -> list[StrategyScore]:
        executors = [m for m in pool["executor"] if m.tier == 2]
        reviewers = pool["reviewer"]
        if not executors or not reviewers:
            return []

        # 遍历 Top-K 组合
        results = []
        for executor in executors:
            for reviewer in reviewers:
                est = estimator.estimate_strategy_cost(
                    StrategyType.GUIDED_EXECUTE,
                    ModelAssignment(executor=executor.name, reviewer=reviewer.name),
                    features,
                    self._make_simple_registry(executor, reviewer),
                )

                executor_q = self._quality_score(executor, features)
                reviewer_q = self._quality_score(reviewer, features)
                quality = self._strategy_quality(StrategyType.GUIDED_EXECUTE, 0.0, executor_q, reviewer_q, 0)
                cap = self._capability_score(executor, features)
                lat = self._latency_score(executor)

                results.append(StrategyScore(
                    strategy=StrategyType.GUIDED_EXECUTE,
                    model_assignment=ModelAssignment(executor=executor.name, reviewer=reviewer.name),
                    models_list=[executor, reviewer],
                    capability=cap,
                    cost=est.total_cost,
                    quality=quality,
                    latency=lat,
                    trigger_reasons=classifier_reasons,
                ))
        return results

    def _build_plan_execute_candidates(
        self, pool, features, estimator, classifier_reasons
    ) -> list[StrategyScore]:
        planners = pool["planner"]
        executors = pool["executor"]
        if not planners or not executors:
            return []

        # 遍历 Top-K 组合
        results = []
        for planner in planners:
            for executor in executors:
                cost = estimator.estimate_plan_execute_cost(planner, executor, features)

                planner_q = self._quality_score(planner, features)
                executor_q = self._executor_quality_score(executor, features)
                quality = self._strategy_quality(
                    StrategyType.PLAN_EXECUTE, planner_q, executor_q, 0.0, len(features.subtasks)
                )
                cap = min(self._capability_score(planner, features), self._executor_capability(executor, features))
                lat = self._latency_score(executor)

                results.append(StrategyScore(
                    strategy=StrategyType.PLAN_EXECUTE,
                    model_assignment=ModelAssignment(planner=planner.name, executor=executor.name),
                    models_list=[planner, executor],
                    capability=cap,
                    cost=cost,
                    quality=quality,
                    latency=lat,
                    trigger_reasons=classifier_reasons,
                ))
        return results

    def _build_per_candidates(
        self, pool, features, estimator, classifier_reasons
    ) -> list[StrategyScore]:
        planners = pool["planner"]
        executors = pool["executor"]
        reviewers = pool["reviewer"]
        if not planners or not executors or not reviewers:
            return []

        # 遍历 Top-K 组合
        results = []
        for planner in planners:
            for executor in executors:
                for reviewer in reviewers:
                    pe_cost = estimator.estimate_plan_execute_cost(planner, executor, features)
                    review_cost = estimator.estimate_review_cost(reviewer, features)
                    total_cost = pe_cost + review_cost

                    planner_q = self._quality_score(planner, features)
                    executor_q = self._executor_quality_score(executor, features)
                    reviewer_q = self._quality_score(reviewer, features)
                    quality = self._strategy_quality(
                        StrategyType.PLAN_EXECUTE_REVIEW, planner_q, executor_q, reviewer_q, len(features.subtasks)
                    )
                    cap = min(self._capability_score(planner, features), self._executor_capability(executor, features))
                    lat = self._latency_score(executor)

                    results.append(StrategyScore(
                        strategy=StrategyType.PLAN_EXECUTE_REVIEW,
                        model_assignment=ModelAssignment(
                            planner=planner.name, executor=executor.name, reviewer=reviewer.name
                        ),
                        models_list=[planner, executor, reviewer],
                        capability=cap,
                        cost=total_cost,
                        quality=quality,
                        latency=lat,
                        trigger_reasons=classifier_reasons,
                    ))
        return results

    def _compute_tier1_baseline(
        self, all_models: list[ModelEntry], features: TaskFeatures, estimator
    ) -> float:
        """Tier 1 单模型成本基线（与 Router._calculate_baseline 一致）。"""
        tier1 = [m for m in all_models if m.tier == 1]
        if not tier1:
            return 0.0
        max_cost = 0.0
        for m in tier1:
            est = estimator.estimate(m, features.estimated_input_tokens, features.estimated_output_tokens)
            max_cost = max(max_cost, est.total_cost)
        return max_cost

    def _executor_quality_score(self, model: ModelEntry, features: TaskFeatures) -> float:
        """Executor 角色质量得分（与 _quality_score 相同，但语义明确）。"""
        return self._quality_score(model, features)

    def _executor_capability(self, model: ModelEntry, features: TaskFeatures) -> float:
        """Executor 角色能力得分：使用 executor 级能力需求而非全局需求。"""
        executor_required = EXECUTOR_CAPABILITY_REQUIREMENTS.get(features.category, set())
        if not executor_required:
            return 1.0
        model_caps = set(model.capabilities)
        matched = executor_required & model_caps
        return len(matched) / len(executor_required) if executor_required else 1.0

    def _strategy_quality(
        self,
        strategy: StrategyType,
        planner_q: float,
        executor_q: float,
        reviewer_q: float,
        num_subtasks: int,
    ) -> float:
        """策略质量 = 加权组合 - decomposition_penalty。"""
        weights = self._routing_rules.strategy_quality_weights.get(strategy.value, {})
        if not weights:
            # SINGLE_MODEL fallback
            return executor_q

        decomposition_penalty = min(0.10, 0.02 * max(0, num_subtasks - 1))

        quality = (
            weights.get("plan", 0.0) * planner_q
            + weights.get("execute", 0.0) * executor_q
            + weights.get("review", 0.0) * reviewer_q
            - decomposition_penalty
        )
        return float(max(0.0, quality))

    def _make_simple_registry(self, *models: ModelEntry):
        """创建测试用的简单 registry（从模型列表）。"""
        class _SimpleRegistry:
            def __init__(self, models):
                self._models = {m.name: m for m in models}
            def get_by_name(self, name):
                return self._models.get(name)
        return _SimpleRegistry(models)

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
            tiers = list(tier_rule.high_risk)
        else:
            tiers = list(tier_rule.default)

        # SIMPLE 默认只允许 Tier 3，但 Tier 3 可能因 allow_sensitive_data=false 被过滤。
        # 高敏任务需要允许 Tier 2 兜底，否则会误报“无候选模型”。
        if features.sensitivity == SensitivityLevel.HIGH and 3 in tiers and 2 not in tiers:
            tiers = [2, *tiers]
        return tiers

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

    def _compute_budget_status(
        self, raw_cost: float, features: TaskFeatures
    ) -> tuple[BudgetStatus, bool]:
        """计算单个候选模型的预算状态（设计 4.2.3 第 5 项）。

        Args:
            raw_cost: 预估原始成本（CNY）
            features: 任务特征

        Returns:
            (budget_status, requires_approval)
        """
        complexity_key = features.complexity.value
        task_limit = self._budgets.task_type_limits.get(complexity_key)
        if not task_limit:
            return BudgetStatus.OK, False

        # soft_budget = min(task_budget_default, max_cost_cny)
        project = self._budgets.projects.get(
            "ai-router", self._budgets.projects.get("default")
        )
        soft_budget = min(project.task_budget_default_cny, task_limit.max_cost_cny)
        hard_budget = soft_budget * project.task_budget_hard_limit_multiplier

        if raw_cost > hard_budget:
            return BudgetStatus.OVER_HARD_BUDGET, True
        if raw_cost > soft_budget:
            return BudgetStatus.OVER_BUDGET, False
        if raw_cost > soft_budget * 0.8:
            return BudgetStatus.WARNING, False
        return BudgetStatus.OK, False
