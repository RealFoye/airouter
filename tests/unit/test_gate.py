"""测试 RoutingGate：管控门禁的 7 条人工审核规则 + 质量门禁构建。

这些是"政策验证"测试，不是"通路验证"测试。
它们证明企业管控规则正确实现了。
"""

import pytest

from airouter.engine.router.gate import GateInput, RoutingGate
from airouter.models.enums import (
    BudgetStatus,
    ComplexityLevel,
    ContextLevel,
    OutputStrictnessLevel,
    ReasoningLevel,
    RiskLevel,
    SensitivityLevel,
    StrategyType,
    TaskCategory,
    VerifiabilityLevel,
)
from airouter.models.schemas import TaskFeatures


@pytest.fixture
def gate() -> RoutingGate:
    return RoutingGate()


def _make_features(
    category=TaskCategory.CODE_GENERATION,
    complexity=ComplexityLevel.COMPLEX,
    risk=RiskLevel.HIGH,
    sensitivity=SensitivityLevel.LOW,
    verifiability=VerifiabilityLevel.HIGH,
    output_strictness=OutputStrictnessLevel.MEDIUM,
) -> TaskFeatures:
    return TaskFeatures(
        category=category,
        complexity=complexity,
        risk_level=risk,
        sensitivity=sensitivity,
        verifiability=verifiability,
        output_strictness=output_strictness,
        context_requirement=ContextLevel.STANDARD,
        reasoning_intensity=ReasoningLevel.HIGH,
    )


def _make_input(
    features=None,
    model_tier=1,
    strategy=StrategyType.SINGLE_MODEL,
    budget_status=BudgetStatus.OK,
    quality_loss=0.05,
    forced_review=False,
) -> GateInput:
    if features is None:
        features = _make_features()
    return GateInput(
        features=features,
        model_name="test-model",
        model_tier=model_tier,
        strategy=strategy,
        estimated_cost=0.10,
        quality=0.85 - quality_loss,
        quality_loss_vs_baseline=quality_loss,
        budget_status=budget_status,
        forced_review_task=forced_review,
    )


# ── 条件1: 敏感数据 ─────────────────────────────────────────
class TestCondition1_SensitiveData:
    def test_high_sensitivity_with_business_risk_triggers_review(self, gate):
        features = _make_features(
            sensitivity=SensitivityLevel.HIGH,
            risk=RiskLevel.HIGH,
        )
        result, reason = gate.check_human_review(_make_input(features=features))
        assert result is True
        assert "高敏数据" in reason

    def test_high_sensitivity_medium_risk_no_review(self, gate):
        features = _make_features(
            sensitivity=SensitivityLevel.HIGH,
            risk=RiskLevel.MEDIUM,
        )
        result, _ = gate.check_human_review(_make_input(features=features))
        assert result is False

    def test_high_sensitivity_low_risk_no_review(self, gate):
        features = _make_features(
            sensitivity=SensitivityLevel.HIGH,
            risk=RiskLevel.LOW,
        )
        result, _ = gate.check_human_review(_make_input(features=features))
        assert result is False

    def test_low_sensitivity_no_trigger(self, gate):
        features = _make_features(
            sensitivity=SensitivityLevel.LOW,
            risk=RiskLevel.LOW,
        )
        result, _ = gate.check_human_review(_make_input(features=features))
        assert result is False


# ── 条件2: 高风险 + 降级执行 ────────────────────────────────
class TestCondition2_HighRiskDowngrade:
    def test_high_risk_tier2_triggers_review(self, gate):
        """核心测试：高风险 + Tier 2 → 必须人工审核。"""
        result, reason = gate.check_human_review(_make_input(model_tier=2))
        assert result is True
        assert "降级" in reason or "拆分" in reason

    def test_high_risk_tier1_no_trigger(self, gate):
        """高风险 + Tier 1 → 不触发（条件2）。"""
        features = _make_features(risk=RiskLevel.HIGH)
        result, _ = gate.check_human_review(_make_input(
            features=features, model_tier=1, quality_loss=0.05,
        ))
        assert result is False

    def test_high_risk_plan_execute_triggers_review(self, gate):
        """高风险 + Plan-Execute 策略 → 触发。"""
        result, reason = gate.check_human_review(_make_input(
            model_tier=1,
            strategy=StrategyType.PLAN_EXECUTE,
        ))
        assert result is True
        assert "拆分" in reason or "降级" in reason

    def test_low_risk_tier2_no_trigger(self, gate):
        """低风险 + Tier 2 → 不触发条件2。"""
        features = _make_features(risk=RiskLevel.LOW)
        result, _ = gate.check_human_review(_make_input(
            features=features, model_tier=2, quality_loss=0.05,
        ))
        assert result is False


# ── 条件3: 超硬预算 ─────────────────────────────────────────
class TestCondition3_HardBudget:
    def test_over_hard_budget_triggers_review(self, gate):
        result, reason = gate.check_human_review(_make_input(
            budget_status=BudgetStatus.OVER_HARD_BUDGET,
        ))
        assert result is True
        assert "硬预算" in reason

    def test_over_soft_budget_no_trigger(self, gate):
        """OVER_BUDGET 只 warning，不触发审核。"""
        features = _make_features(risk=RiskLevel.LOW)
        result, _ = gate.check_human_review(_make_input(
            features=features, budget_status=BudgetStatus.OVER_BUDGET,
        ))
        assert result is False

    def test_warning_budget_no_trigger(self, gate):
        features = _make_features(risk=RiskLevel.LOW)
        result, _ = gate.check_human_review(_make_input(
            features=features, budget_status=BudgetStatus.WARNING, quality_loss=0.05,
        ))
        assert result is False


# ── 条件6: 质量损失超阈值（仅非 LOW risk） ──────────────────
class TestCondition6_QualityLoss:
    def test_quality_loss_above_threshold(self, gate):
        """非 LOW risk + quality_loss > 0.20 → 触发审核。"""
        result, reason = gate.check_human_review(_make_input(quality_loss=0.25))
        assert result is True
        assert "质量损失" in reason
        assert "25%" in reason

    def test_quality_loss_low_risk_no_trigger(self, gate):
        """LOW risk + quality_loss > 0.20 → 不触发（省钱路径不锁死）。"""
        features = _make_features(risk=RiskLevel.LOW)
        result, reason = gate.check_human_review(_make_input(
            features=features, quality_loss=0.40,
        ))
        # quality_loss=0.40 > 0.20 但 risk=LOW，不应触发条件6
        assert result is False

    def test_quality_loss_at_threshold(self, gate):
        """quality_loss == 0.20（等于，不是大于） → 不触发。"""
        features = _make_features(risk=RiskLevel.MEDIUM)
        result, _ = gate.check_human_review(_make_input(
            features=features, quality_loss=0.20,
        ))
        assert result is False

    def test_quality_loss_below_threshold(self, gate):
        features = _make_features(risk=RiskLevel.MEDIUM)
        result, _ = gate.check_human_review(_make_input(
            features=features, quality_loss=0.10,
        ))
        assert result is False


# ── 条件7: 任务类型强制审核 ─────────────────────────────────
class TestCondition7_ForcedReview:
    def test_forced_review_task(self, gate):
        features = _make_features(
            category=TaskCategory.ARCHITECTURE,
            risk=RiskLevel.LOW,
        )
        result, reason = gate.check_human_review(_make_input(
            features=features, quality_loss=0.05, forced_review=True,
        ))
        assert result is True
        assert "ARCHITECTURE" in reason


# ── 质量门禁构建 ────────────────────────────────────────────
class TestQualityGate:
    def test_code_generation_gates(self, gate):
        features = _make_features(
            category=TaskCategory.CODE_GENERATION,
            risk=RiskLevel.LOW,
        )
        gates = gate.build_quality_gate(features, requires_human_review=False)
        assert "syntax_check" in gates
        assert "ast_parse" in gates

    def test_high_risk_adds_human_review(self, gate):
        features = _make_features(risk=RiskLevel.HIGH)
        gates = gate.build_quality_gate(features, requires_human_review=False)
        assert "human_review" in gates

    def test_requires_review_adds_human_review(self, gate):
        """如果 requires_human_review=true，quality_gate 必须包含 human_review。"""
        features = _make_features(
            category=TaskCategory.CODE_GENERATION,
            risk=RiskLevel.LOW,
        )
        gates = gate.build_quality_gate(features, requires_human_review=True)
        assert "human_review" in gates

    def test_low_verifiability_uses_llm_judge(self, gate):
        features = _make_features(
            category=TaskCategory.ARCHITECTURE,
            verifiability=VerifiabilityLevel.LOW,
            risk=RiskLevel.LOW,
        )
        gates = gate.build_quality_gate(features, requires_human_review=False)
        assert "llm_judge" in gates

    def test_low_verifiability_high_risk(self, gate):
        features = _make_features(
            category=TaskCategory.ARCHITECTURE,
            verifiability=VerifiabilityLevel.LOW,
            risk=RiskLevel.HIGH,
        )
        gates = gate.build_quality_gate(features, requires_human_review=False)
        assert "llm_judge" in gates
        assert "human_review" in gates

    def test_high_output_strictness_adds_format_check(self, gate):
        features = _make_features(
            category=TaskCategory.CODE_GENERATION,
            risk=RiskLevel.LOW,
            output_strictness=OutputStrictnessLevel.HIGH,
        )
        gates = gate.build_quality_gate(features, requires_human_review=False)
        assert "format_check" in gates


# ── quality_gate 与 requires_human_review 联动 ──────────────
class TestGateConsistency:
    """确保 quality_gate 和 requires_human_review 不矛盾。"""

    def test_review_true_gate_has_human_review(self, gate):
        """核心一致性：requires_human_review=true → human_review 在 quality_gate 中。"""
        features = _make_features(
            category=TaskCategory.CODE_GENERATION,
            risk=RiskLevel.HIGH,
        )
        gate_input = _make_input(features=features, model_tier=2)
        requires_review, _ = gate.check_human_review(gate_input)
        assert requires_review is True

        gates = gate.build_quality_gate(features, requires_review)
        assert "human_review" in gates

    def test_review_false_gate_may_not_have_human_review(self, gate):
        """requires_human_review=false → quality_gate 不一定有 human_review。"""
        features = _make_features(
            category=TaskCategory.CODE_GENERATION,
            risk=RiskLevel.LOW,
        )
        gate_input = _make_input(features=features, model_tier=1, quality_loss=0.05)
        requires_review, _ = gate.check_human_review(gate_input)
        assert requires_review is False

        gates = gate.build_quality_gate(features, requires_review)
        # CODE_GENERATION + LOW risk 不应该有 human_review
        assert "human_review" not in gates
