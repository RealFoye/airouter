"""GoalBuilder 单元测试。"""

from airouter.engine.agent.goal import GoalBuilder
from airouter.models.enums import (
    ComplexityLevel,
    RiskLevel,
    StrategyType,
    TaskCategory,
)
from airouter.models.schemas import (
    ModelAssignment,
    RoutingDecision,
    TaskFeatures,
)


def _make_decision(
    category=TaskCategory.CODE_GENERATION,
    complexity=ComplexityLevel.SIMPLE,
    risk_level=RiskLevel.LOW,
    strategy=StrategyType.SINGLE_MODEL,
    requires_review=False,
) -> RoutingDecision:
    features = TaskFeatures(
        category=category,
        complexity=complexity,
        risk_level=risk_level,
    )
    return RoutingDecision(
        task_hash="test123",
        task_features=features,
        recommended_strategy=strategy,
        models=ModelAssignment(executor="deepseek-v4-flash"),
        estimated_cost=0.001,
        baseline_cost=0.01,
        estimated_savings=0.9,
        estimated_quality=0.85,
        quality_loss_vs_baseline=0.0,
        risk_level=risk_level,
        requires_human_review=requires_review,
        reasons=["test"],
        alternatives=[],
        budget_status="OK",
        quality_gate=[],
        fallback_policy=[],
        config_version="v1.1",
    )


class TestGoalBuilder:
    def test_basic_build(self, tmp_path):
        decision = _make_decision()
        goal = GoalBuilder.build(decision, "写个函数", tmp_path)
        assert goal.task == "写个函数"
        assert goal.category == TaskCategory.CODE_GENERATION
        assert goal.complexity == ComplexityLevel.SIMPLE

    def test_workdir_resolved(self, tmp_path):
        decision = _make_decision()
        goal = GoalBuilder.build(decision, "task", tmp_path)
        assert goal.constraints.workdir == tmp_path.resolve()

    def test_requires_approval_when_review_needed(self, tmp_path):
        decision = _make_decision(requires_review=True)
        goal = GoalBuilder.build(decision, "task", tmp_path)
        assert goal.constraints.requires_approval is True

    def test_skip_approval(self, tmp_path):
        decision = _make_decision(requires_review=True)
        goal = GoalBuilder.build(decision, "task", tmp_path, skip_approval=True)
        assert goal.constraints.requires_approval is False

    def test_max_cost_from_config(self, tmp_path):
        decision = _make_decision()
        goal = GoalBuilder.build(decision, "task", tmp_path, max_cost=5.0)
        assert goal.constraints.max_cost_cny == 5.0

    def test_max_turns_from_config(self, tmp_path):
        decision = _make_decision()
        goal = GoalBuilder.build(decision, "task", tmp_path, max_turns=20)
        assert goal.constraints.max_turns == 20


class TestSuccessCriteria:
    def test_code_generation(self, tmp_path):
        decision = _make_decision(category=TaskCategory.CODE_GENERATION)
        goal = GoalBuilder.build(decision, "task", tmp_path)
        assert any("语法正确" in c for c in goal.success_criteria)

    def test_code_review(self, tmp_path):
        decision = _make_decision(category=TaskCategory.CODE_REVIEW)
        goal = GoalBuilder.build(decision, "task", tmp_path)
        assert any("问题列表" in c for c in goal.success_criteria)

    def test_bug_analysis(self, tmp_path):
        decision = _make_decision(category=TaskCategory.BUG_ANALYSIS)
        goal = GoalBuilder.build(decision, "task", tmp_path)
        assert any("根因" in c for c in goal.success_criteria)

    def test_test_generation(self, tmp_path):
        decision = _make_decision(category=TaskCategory.TEST_GENERATION)
        goal = GoalBuilder.build(decision, "task", tmp_path)
        assert any("pytest" in c for c in goal.success_criteria)

    def test_high_risk_extra_criteria(self, tmp_path):
        decision = _make_decision(risk_level=RiskLevel.HIGH)
        goal = GoalBuilder.build(decision, "task", tmp_path)
        assert any("git diff" in c for c in goal.success_criteria)


class TestToolSelection:
    def test_simple_low_risk_no_run_command(self, tmp_path):
        decision = _make_decision(
            category=TaskCategory.CODE_REVIEW,
            complexity=ComplexityLevel.SIMPLE,
            risk_level=RiskLevel.LOW,
        )
        goal = GoalBuilder.build(decision, "task", tmp_path)
        assert "run_command" not in goal.constraints.allowed_tools

    def test_code_gen_has_write_file(self, tmp_path):
        decision = _make_decision(
            category=TaskCategory.CODE_GENERATION,
            complexity=ComplexityLevel.MODERATE,
        )
        goal = GoalBuilder.build(decision, "task", tmp_path)
        assert "write_file" in goal.constraints.allowed_tools

    def test_refactoring_has_write_file(self, tmp_path):
        decision = _make_decision(
            category=TaskCategory.REFACTORING,
            complexity=ComplexityLevel.MODERATE,
        )
        goal = GoalBuilder.build(decision, "task", tmp_path)
        assert "write_file" in goal.constraints.allowed_tools

    def test_complex_has_run_command(self, tmp_path):
        decision = _make_decision(
            category=TaskCategory.BUG_ANALYSIS,
            complexity=ComplexityLevel.COMPLEX,
            risk_level=RiskLevel.MEDIUM,
        )
        goal = GoalBuilder.build(decision, "task", tmp_path)
        assert "run_command" in goal.constraints.allowed_tools
