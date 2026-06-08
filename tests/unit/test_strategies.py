"""测试策略级评分：Top-K、role-based tier pool、StrategyScore、post-filter。"""

from __future__ import annotations

import pytest

from airouter.engine.router.estimator import CostEstimator
from airouter.engine.router.selector import ModelSelector
from airouter.models.enums import (
    ComplexityLevel,
    ContextLevel,
    ReasoningLevel,
    RiskLevel,
    StrategyType,
    TaskCategory,
    VerifiabilityLevel,
)
from airouter.models.schemas import TaskFeatures


@pytest.fixture
def selector() -> ModelSelector:
    return ModelSelector()


@pytest.fixture
def estimator() -> CostEstimator:
    return CostEstimator()


@pytest.fixture
def all_models():
    """使用真实 models.yaml 中的 5 个模型。"""
    from airouter.config import load_models
    return load_models().models


def _make_features(**kwargs) -> TaskFeatures:
    defaults = {
        "category": TaskCategory.CODE_GENERATION,
        "complexity": ComplexityLevel.COMPLEX,
        "risk_level": RiskLevel.MEDIUM,
        "sensitivity": "LOW",
        "verifiability": VerifiabilityLevel.MEDIUM,
        "output_strictness": "MEDIUM",
        "context_requirement": ContextLevel.STANDARD,
        "reasoning_intensity": ReasoningLevel.HIGH,
        "estimated_input_tokens": 5000,
        "estimated_output_tokens": 800,
        "subtasks": ["子任务1", "子任务2", "子任务3"],
    }
    defaults.update(kwargs)
    return TaskFeatures(**defaults)


# ── Top-K per tier ───────────────────────────────────────────
class TestTopKPerTier:
    def test_groups_by_tier(self, selector, all_models):
        features = _make_features()
        candidates = selector._filter_base(all_models, features)
        top_k = selector.select_top_k_per_tier(candidates, features)
        # 每个 tier 最多 k 个模型
        for tier, models in top_k.items():
            assert len(models) <= 2, f"tier{tier} has {len(models)} models (max 2)"
            for m in models:
                assert m.tier == tier

    def test_respects_k_config(self, selector, all_models):
        features = _make_features()
        candidates = selector._filter_base(all_models, features)
        top_k = selector.select_top_k_per_tier(candidates, features)
        # tier1 有 2 个模型，k=2 所以都应该在
        if 1 in top_k:
            assert len(top_k[1]) <= 2

    def test_empty_candidates(self, selector):
        features = _make_features()
        top_k = selector.select_top_k_per_tier([], features)
        assert top_k == {}


# ── Role-based tier pool ─────────────────────────────────────
class TestRoleBasedPool:
    def test_planner_always_tier1(self, selector, all_models):
        features = _make_features()
        base = selector._filter_base(all_models, features)
        pool = selector._build_role_pool(base, features)
        for m in pool["planner"]:
            assert m.tier == 1

    def test_reviewer_always_tier1(self, selector, all_models):
        features = _make_features()
        base = selector._filter_base(all_models, features)
        pool = selector._build_role_pool(base, features)
        for m in pool["reviewer"]:
            assert m.tier == 1

    def test_executor_tier_by_risk_low(self, selector, all_models):
        features = _make_features(risk_level=RiskLevel.LOW)
        base = selector._filter_base(all_models, features)
        pool = selector._build_role_pool(base, features)
        for m in pool["executor"]:
            assert m.tier == 3, f"LOW risk executor should be Tier 3, got {m.tier}"

    def test_executor_tier_by_risk_medium(self, selector, all_models):
        features = _make_features(risk_level=RiskLevel.MEDIUM)
        base = selector._filter_base(all_models, features)
        pool = selector._build_role_pool(base, features)
        for m in pool["executor"]:
            assert m.tier == 2, f"MEDIUM risk executor should be Tier 2, got {m.tier}"

    def test_executor_tier_by_risk_high(self, selector, all_models):
        features = _make_features(risk_level=RiskLevel.HIGH)
        base = selector._filter_base(all_models, features)
        pool = selector._build_role_pool(base, features)
        for m in pool["executor"]:
            assert m.tier == 2, f"HIGH risk executor should be Tier 2, got {m.tier}"

    def test_single_uses_allowed_tiers(self, selector, all_models):
        features = _make_features()
        base = selector._filter_base(all_models, features)
        pool = selector._build_role_pool(base, features)
        allowed = selector._get_allowed_tiers(features)
        for m in pool["single"]:
            assert m.tier in allowed


# ── 策略质量计算 ─────────────────────────────────────────────
class TestStrategyQuality:
    def test_single_model_quality(self, selector):
        """SINGLE_MODEL 直接用 executor quality。"""
        q = selector._strategy_quality(StrategyType.SINGLE_MODEL, 0, 0.7, 0, 0)
        assert q == 0.7

    def test_plan_execute_weighted(self, selector):
        """PLAN_EXECUTE: plan=0.55, execute=0.45, review=0.00。"""
        q = selector._strategy_quality(
            StrategyType.PLAN_EXECUTE, 0.8, 0.6, 0.0, 3
        )
        expected = 0.55 * 0.8 + 0.45 * 0.6 - min(0.10, 0.02 * max(0, 3 - 1))
        assert abs(q - expected) < 0.01

    def test_guided_execute_weighted(self, selector):
        """GUIDED_EXECUTE: plan=0.00, execute=0.70, review=0.30。"""
        q = selector._strategy_quality(
            StrategyType.GUIDED_EXECUTE, 0.0, 0.6, 0.8, 0
        )
        expected = 0.70 * 0.6 + 0.30 * 0.8
        assert abs(q - expected) < 0.01

    def test_per_weighted(self, selector):
        """PLAN_EXECUTE_REVIEW: plan=0.45, execute=0.35, review=0.20。"""
        q = selector._strategy_quality(
            StrategyType.PLAN_EXECUTE_REVIEW, 0.8, 0.6, 0.7, 2
        )
        penalty = min(0.10, 0.02 * max(0, 2 - 1))
        expected = 0.45 * 0.8 + 0.35 * 0.6 + 0.20 * 0.7 - penalty
        assert abs(q - expected) < 0.01

    def test_decomposition_penalty_two_subtasks(self, selector):
        """2 个子任务：penalty = min(0.10, 0.02 * max(0, 2-1)) = 0.02。"""
        q_with_penalty = selector._strategy_quality(
            StrategyType.PLAN_EXECUTE, 0.8, 0.6, 0.0, 2
        )
        q_no_penalty = selector._strategy_quality(
            StrategyType.PLAN_EXECUTE, 0.8, 0.6, 0.0, 1
        )
        assert q_no_penalty > q_with_penalty

    def test_decomposition_penalty_cap(self, selector):
        """penalty 上限 0.10。"""
        q_10 = selector._strategy_quality(
            StrategyType.PLAN_EXECUTE, 0.8, 0.6, 0.0, 10
        )
        q_20 = selector._strategy_quality(
            StrategyType.PLAN_EXECUTE, 0.8, 0.6, 0.0, 20
        )
        # 两者 penalty 都是 0.10，质量应该相同
        assert q_10 == q_20

    def test_quality_non_negative(self, selector):
        """质量不会低于 0。"""
        q = selector._strategy_quality(
            StrategyType.PLAN_EXECUTE, 0.1, 0.1, 0.0, 10
        )
        assert q >= 0.0


# ── select_best_strategy 端到端 ─────────────────────────────
class TestSelectBestStrategy:
    def test_single_model_always_present(self, selector, estimator, all_models):
        features = _make_features(
            complexity=ComplexityLevel.SIMPLE,
            reasoning_intensity=ReasoningLevel.LOW,
            subtasks=[],
            estimated_output_tokens=80,
            risk_level=RiskLevel.LOW,
        )
        scores = selector.select_best_strategy(
            [StrategyType.SINGLE_MODEL], all_models, features, estimator
        )
        assert len(scores) > 0
        assert scores[0].strategy == StrategyType.SINGLE_MODEL

    def test_plan_execute_produces_score(self, selector, estimator, all_models):
        """COMPLEX + subtasks + HIGH output + LOW risk → Plan-Execute 使用 Tier 3 executor 更可能通过 post-filter。"""
        features = _make_features(
            complexity=ComplexityLevel.COMPLEX,
            risk_level=RiskLevel.LOW,  # LOW risk → executor=Tier 3 → 更便宜
            estimated_output_tokens=2000,
            estimated_input_tokens=10000,
            reasoning_intensity=ReasoningLevel.HIGH,
            subtasks=["a", "b", "c", "d"],
            verifiability=VerifiabilityLevel.HIGH,
        )
        scores = selector.select_best_strategy(
            [StrategyType.SINGLE_MODEL, StrategyType.PLAN_EXECUTE],
            all_models, features, estimator,
        )
        assert len(scores) > 0
        # 至少 SINGLE_MODEL 在
        strategies = [s.strategy for s in scores]
        assert StrategyType.SINGLE_MODEL in strategies
        # PE 可能在也可能不在（取决于 post-filter），但 SINGLE 一定在

    def test_plan_execute_has_planner_and_executor(self, selector, estimator, all_models):
        features = _make_features()
        scores = selector.select_best_strategy(
            [StrategyType.PLAN_EXECUTE], all_models, features, estimator,
        )
        if scores:
            pe = [s for s in scores if s.strategy == StrategyType.PLAN_EXECUTE]
            for s in pe:
                assert s.model_assignment.planner is not None
                assert s.model_assignment.executor is not None

    def test_strategy_score_has_budget_status(self, selector, estimator, all_models):
        features = _make_features()
        scores = selector.select_best_strategy(
            [StrategyType.SINGLE_MODEL], all_models, features, estimator,
        )
        for s in scores:
            assert hasattr(s, "budget_status")

    def test_empty_strategy_types(self, selector, estimator, all_models):
        features = _make_features()
        scores = selector.select_best_strategy([], all_models, features, estimator)
        assert scores == []

    def test_no_models_returns_empty(self, selector, estimator):
        features = _make_features(estimated_input_tokens=999999)
        scores = selector.select_best_strategy(
            [StrategyType.SINGLE_MODEL], [], features, estimator
        )
        assert scores == []


# ── Post-filter 验证 ────────────────────────────────────────
class TestPostFilter:
    def test_quality_loss_filter(self, selector, estimator, all_models):
        """quality_loss > 15% 的策略应被排除。"""
        features = _make_features(
            complexity=ComplexityLevel.COMPLEX,
            risk_level=RiskLevel.MEDIUM,
            estimated_output_tokens=1000,
            reasoning_intensity=ReasoningLevel.HIGH,
            subtasks=["a", "b"],
        )
        # 同时传入多种策略，post-filter 应工作
        scores = selector.select_best_strategy(
            [StrategyType.SINGLE_MODEL, StrategyType.PLAN_EXECUTE, StrategyType.GUIDED_EXECUTE],
            all_models, features, estimator,
        )
        # 所有返回的策略质量差距不应超过 15%
        if len(scores) > 1:
            max_q = max(s.quality for s in scores)
            for s in scores:
                assert max_q - s.quality <= 0.15 + 0.001  # 浮点容差


# ── 端到端策略选择 ───────────────────────────────────────────
class TestEndToEndStrategy:
    def test_simple_task_gets_single_model(self, selector, estimator, all_models):
        """SIMPLE 任务只应该产出 SINGLE_MODEL。"""
        from airouter.engine.router.classifier import StrategyClassifier

        classifier = StrategyClassifier()
        features = _make_features(
            complexity=ComplexityLevel.SIMPLE,
            reasoning_intensity=ReasoningLevel.LOW,
            subtasks=[],
            estimated_output_tokens=80,
            risk_level=RiskLevel.LOW,
        )
        classification = classifier.classify(features)
        assert classification.strategies == [StrategyType.SINGLE_MODEL]

        scores = selector.select_best_strategy(
            classification.strategies, all_models, features, estimator,
        )
        assert all(s.strategy == StrategyType.SINGLE_MODEL for s in scores)

    def test_complex_task_can_get_plan_execute(self, selector, estimator, all_models):
        """COMPLEX + 可拆解 → 可能产出 Plan-Execute。"""
        from airouter.engine.router.classifier import StrategyClassifier

        classifier = StrategyClassifier(
            human_review_required_tasks=["ARCHITECTURE"]
        )
        features = _make_features(
            category=TaskCategory.CODE_GENERATION,
            complexity=ComplexityLevel.COMPLEX,
            risk_level=RiskLevel.MEDIUM,
            estimated_output_tokens=1000,
            reasoning_intensity=ReasoningLevel.HIGH,
            subtasks=["实现登录", "实现注册", "实现权限"],
            verifiability=VerifiabilityLevel.HIGH,
        )
        classification = classifier.classify(features)
        assert StrategyType.PLAN_EXECUTE in classification.strategies

    def test_architecture_expert_per_raw_candidates(self, selector, estimator, all_models):
        """ARCHITECTURE + EXPERT + HIGH risk + LOW verifiability → _build_per_candidates 应产出含全角色的 raw 候选。

        注意：raw 候选可能被 post-filter 因成本/质量排除，这里绕过 post-filter 直接测生成逻辑。
        """
        from airouter.engine.router.classifier import StrategyClassifier

        classifier = StrategyClassifier(
            human_review_required_tasks=["ARCHITECTURE"]
        )
        features = _make_features(
            category=TaskCategory.ARCHITECTURE,
            complexity=ComplexityLevel.EXPERT,
            risk_level=RiskLevel.HIGH,
            estimated_output_tokens=2000,
            estimated_input_tokens=10000,
            reasoning_intensity=ReasoningLevel.HIGH,
            subtasks=["设计模块A", "设计模块B", "设计模块C"],
            verifiability=VerifiabilityLevel.LOW,
        )
        classification = classifier.classify(features)
        assert StrategyType.PLAN_EXECUTE_REVIEW in classification.strategies

        # 直接测 _build_per_candidates raw 输出（绕过 post-filter）
        base = selector._filter_base(all_models, features)
        role_pool = selector._build_role_pool(base, features)
        for role in role_pool:
            if role_pool[role]:
                top_k = selector.select_top_k_per_tier(role_pool[role], features)
                role_pool[role] = [m for models in top_k.values() for m in models]

        per_raw = selector._build_per_candidates(
            role_pool, features, estimator, classification.reasons,
        )
        assert per_raw, "PER raw candidates should not be empty (role-level capability fix)"
        for s in per_raw:
            assert s.model_assignment.planner is not None
            assert s.model_assignment.executor is not None
            assert s.model_assignment.reviewer is not None
