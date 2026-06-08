"""测试 StrategyClassifier：策略触发条件的逐条验证。"""

from __future__ import annotations

import pytest

from airouter.engine.router.classifier import StrategyClassifier
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
def classifier() -> StrategyClassifier:
    return StrategyClassifier(human_review_required_tasks=["ARCHITECTURE"])


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


# ── SINGLE_MODEL 始终存在 ────────────────────────────────────
class TestSingleModelAlwaysPresent:
    def test_single_model_always_included(self, classifier):
        result = classifier.classify(_make_features(complexity=ComplexityLevel.SIMPLE))
        assert StrategyType.SINGLE_MODEL in result.strategies


# ── Plan-Execute（5 个结构条件） ─────────────────────────────
class TestPlanExecute:
    def test_all_conditions_met(self, classifier):
        """COMPLEX + output>=500 + HIGH reasoning + subtasks>=2 + verifiability>=MEDIUM。"""
        result = classifier.classify(_make_features())
        assert StrategyType.PLAN_EXECUTE in result.strategies

    def test_expert_complexity(self, classifier):
        result = classifier.classify(_make_features(complexity=ComplexityLevel.EXPERT))
        assert StrategyType.PLAN_EXECUTE in result.strategies

    def test_moderate_complexity_rejected(self, classifier):
        result = classifier.classify(_make_features(complexity=ComplexityLevel.MODERATE))
        assert StrategyType.PLAN_EXECUTE not in result.strategies
        assert "complexity" in result.reasons[StrategyType.PLAN_EXECUTE.value]

    def test_simple_complexity_rejected(self, classifier):
        result = classifier.classify(_make_features(complexity=ComplexityLevel.SIMPLE))
        assert StrategyType.PLAN_EXECUTE not in result.strategies

    def test_output_too_small_rejected(self, classifier):
        result = classifier.classify(_make_features(estimated_output_tokens=499))
        assert StrategyType.PLAN_EXECUTE not in result.strategies
        assert "output_tokens" in result.reasons[StrategyType.PLAN_EXECUTE.value]

    def test_output_exactly_500_accepted(self, classifier):
        result = classifier.classify(_make_features(estimated_output_tokens=500))
        assert StrategyType.PLAN_EXECUTE in result.strategies

    def test_low_reasoning_rejected(self, classifier):
        result = classifier.classify(_make_features(reasoning_intensity=ReasoningLevel.MEDIUM))
        assert StrategyType.PLAN_EXECUTE not in result.strategies
        assert "reasoning" in result.reasons[StrategyType.PLAN_EXECUTE.value]

    def test_very_high_reasoning_accepted(self, classifier):
        result = classifier.classify(_make_features(reasoning_intensity=ReasoningLevel.VERY_HIGH))
        assert StrategyType.PLAN_EXECUTE in result.strategies

    def test_one_subtask_rejected(self, classifier):
        result = classifier.classify(_make_features(subtasks=["only one"]))
        assert StrategyType.PLAN_EXECUTE not in result.strategies
        assert "subtasks" in result.reasons[StrategyType.PLAN_EXECUTE.value]

    def test_no_subtasks_rejected(self, classifier):
        result = classifier.classify(_make_features(subtasks=[]))
        assert StrategyType.PLAN_EXECUTE not in result.strategies

    def test_low_verifiability_high_risk_rejected(self, classifier):
        """条件5: verifiability < MEDIUM 且 risk != LOW → 拒绝。"""
        result = classifier.classify(_make_features(
            verifiability=VerifiabilityLevel.LOW,
            risk_level=RiskLevel.HIGH,
        ))
        assert StrategyType.PLAN_EXECUTE not in result.strategies
        assert "verifiability" in result.reasons[StrategyType.PLAN_EXECUTE.value]

    def test_low_verifiability_low_risk_accepted(self, classifier):
        """条件5: verifiability < MEDIUM 但 risk == LOW → 接受。"""
        result = classifier.classify(_make_features(
            verifiability=VerifiabilityLevel.LOW,
            risk_level=RiskLevel.LOW,
        ))
        assert StrategyType.PLAN_EXECUTE in result.strategies

    def test_high_verifiability_accepted(self, classifier):
        result = classifier.classify(_make_features(verifiability=VerifiabilityLevel.HIGH))
        assert StrategyType.PLAN_EXECUTE in result.strategies


# ── Guided Execute（4 个结构条件） ───────────────────────────
class TestGuidedExecute:
    def _ge_features(self, **kwargs):
        """构造满足 Guided Execute 基础条件的 features。"""
        defaults = {
            "complexity": ComplexityLevel.MODERATE,
            "estimated_output_tokens": 1000,
            "risk_level": RiskLevel.MEDIUM,
            "verifiability": VerifiabilityLevel.HIGH,
        }
        defaults.update(kwargs)
        return _make_features(**defaults)

    def test_all_conditions_met_moderate(self, classifier):
        result = classifier.classify(self._ge_features())
        assert StrategyType.GUIDED_EXECUTE in result.strategies

    def test_all_conditions_met_complex(self, classifier):
        result = classifier.classify(self._ge_features(complexity=ComplexityLevel.COMPLEX))
        assert StrategyType.GUIDED_EXECUTE in result.strategies

    def test_simple_complexity_rejected(self, classifier):
        result = classifier.classify(self._ge_features(complexity=ComplexityLevel.SIMPLE))
        assert StrategyType.GUIDED_EXECUTE not in result.strategies

    def test_expert_complexity_rejected(self, classifier):
        result = classifier.classify(self._ge_features(complexity=ComplexityLevel.EXPERT))
        assert StrategyType.GUIDED_EXECUTE not in result.strategies

    def test_output_too_small_rejected(self, classifier):
        result = classifier.classify(self._ge_features(estimated_output_tokens=799))
        assert StrategyType.GUIDED_EXECUTE not in result.strategies
        assert "output_tokens" in result.reasons[StrategyType.GUIDED_EXECUTE.value]

    def test_output_exactly_800_accepted(self, classifier):
        result = classifier.classify(self._ge_features(estimated_output_tokens=800))
        assert StrategyType.GUIDED_EXECUTE in result.strategies

    def test_low_risk_rejected(self, classifier):
        result = classifier.classify(self._ge_features(risk_level=RiskLevel.LOW))
        assert StrategyType.GUIDED_EXECUTE not in result.strategies
        assert "risk" in result.reasons[StrategyType.GUIDED_EXECUTE.value]

    def test_high_risk_accepted(self, classifier):
        result = classifier.classify(self._ge_features(risk_level=RiskLevel.HIGH))
        assert StrategyType.GUIDED_EXECUTE in result.strategies

    def test_low_verifiability_high_risk_rejected(self, classifier):
        """条件5: verifiability=LOW + risk=HIGH → 不可同时。"""
        result = classifier.classify(self._ge_features(
            verifiability=VerifiabilityLevel.LOW,
            risk_level=RiskLevel.HIGH,
        ))
        assert StrategyType.GUIDED_EXECUTE not in result.strategies

    def test_low_verifiability_medium_risk_accepted(self, classifier):
        """verifiability=LOW + risk=MEDIUM → 可以。"""
        result = classifier.classify(self._ge_features(
            verifiability=VerifiabilityLevel.LOW,
            risk_level=RiskLevel.MEDIUM,
        ))
        assert StrategyType.GUIDED_EXECUTE in result.strategies


# ── Plan-Execute-Review ──────────────────────────────────────
class TestPlanExecuteReview:
    def _per_base_features(self, **kwargs):
        """满足 base_decomposable 的 features。"""
        defaults = {
            "complexity": ComplexityLevel.COMPLEX,
            "estimated_output_tokens": 800,
            "reasoning_intensity": ReasoningLevel.HIGH,
            "subtasks": ["a", "b"],
            "risk_level": RiskLevel.HIGH,
        }
        defaults.update(kwargs)
        return _make_features(**defaults)

    def test_base_plus_high_risk_triggers(self, classifier):
        result = classifier.classify(self._per_base_features())
        assert StrategyType.PLAN_EXECUTE_REVIEW in result.strategies
        assert "risk=HIGH" in result.reasons[StrategyType.PLAN_EXECUTE_REVIEW.value]

    def test_base_plus_low_verifiability_triggers(self, classifier):
        result = classifier.classify(self._per_base_features(
            risk_level=RiskLevel.MEDIUM,
            verifiability=VerifiabilityLevel.LOW,
        ))
        assert StrategyType.PLAN_EXECUTE_REVIEW in result.strategies

    def test_base_plus_forced_review_category_triggers(self, classifier):
        """ARCHITECTURE 在 human_review_required_tasks 中。"""
        result = classifier.classify(self._per_base_features(
            category=TaskCategory.ARCHITECTURE,
            risk_level=RiskLevel.MEDIUM,
            verifiability=VerifiabilityLevel.MEDIUM,
        ))
        assert StrategyType.PLAN_EXECUTE_REVIEW in result.strategies
        assert "ARCHITECTURE" in result.reasons[StrategyType.PLAN_EXECUTE_REVIEW.value]

    def test_no_review_need_rejected(self, classifier):
        """base_decomposable 满足，但 review_need 全部不满足 → 拒绝。"""
        result = classifier.classify(self._per_base_features(
            risk_level=RiskLevel.MEDIUM,
            verifiability=VerifiabilityLevel.MEDIUM,
            category=TaskCategory.CODE_GENERATION,
        ))
        assert StrategyType.PLAN_EXECUTE_REVIEW not in result.strategies
        assert "review_need" in result.reasons[StrategyType.PLAN_EXECUTE_REVIEW.value]

    def test_base_decomposable_fails_simple(self, classifier):
        """SIMPLE complexity → base_decomposable 失败。"""
        result = classifier.classify(self._per_base_features(
            complexity=ComplexityLevel.SIMPLE,
            risk_level=RiskLevel.HIGH,
        ))
        assert StrategyType.PLAN_EXECUTE_REVIEW not in result.strategies
        assert "base_decomposable" in result.reasons[StrategyType.PLAN_EXECUTE_REVIEW.value]

    def test_base_decomposable_fails_no_subtasks(self, classifier):
        result = classifier.classify(self._per_base_features(
            subtasks=[],
            risk_level=RiskLevel.HIGH,
        ))
        assert StrategyType.PLAN_EXECUTE_REVIEW not in result.strategies

    def test_base_decomposable_fails_low_output(self, classifier):
        result = classifier.classify(self._per_base_features(
            estimated_output_tokens=100,
            risk_level=RiskLevel.HIGH,
        ))
        assert StrategyType.PLAN_EXECUTE_REVIEW not in result.strategies


# ── ClassificationResult 结构 ────────────────────────────────
class TestClassificationResult:
    def test_result_has_all_four_reasons(self, classifier):
        result = classifier.classify(_make_features())
        for st in StrategyType:
            assert st.value in result.reasons

    def test_simple_task_only_single_model(self, classifier):
        result = classifier.classify(_make_features(
            complexity=ComplexityLevel.SIMPLE,
            reasoning_intensity=ReasoningLevel.LOW,
            subtasks=[],
            estimated_output_tokens=80,
            risk_level=RiskLevel.LOW,
        ))
        assert result.strategies == [StrategyType.SINGLE_MODEL]

    def test_multiple_strategies_possible(self, classifier):
        """COMPLEX + HIGH risk + HIGH output + subtasks → 可能同时触发多个策略。"""
        result = classifier.classify(_make_features(
            complexity=ComplexityLevel.COMPLEX,
            risk_level=RiskLevel.HIGH,
            estimated_output_tokens=1000,
            reasoning_intensity=ReasoningLevel.HIGH,
            subtasks=["a", "b", "c"],
            verifiability=VerifiabilityLevel.HIGH,
        ))
        # SINGLE_MODEL 始终存在
        assert StrategyType.SINGLE_MODEL in result.strategies
        # PE: 5 条件全满足
        assert StrategyType.PLAN_EXECUTE in result.strategies
        # GE: MODERATE/COMPLEX + output>=800 + risk!=LOW + verif/risk 不冲突
        assert StrategyType.GUIDED_EXECUTE in result.strategies
        # PER: base_decomposable + risk=HIGH
        assert StrategyType.PLAN_EXECUTE_REVIEW in result.strategies
