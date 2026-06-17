"""AgentExecutor 单元测试（使用 MockAdapter）。"""

from unittest.mock import MagicMock

from airouter.adapters.base import AdapterResponse
from airouter.engine.agent.executor import AgentConfig, AgentExecutor
from airouter.engine.agent.report import CostSummary, ExecutionReport
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
    strategy=StrategyType.SINGLE_MODEL,
    executor_name="deepseek-v4-flash",
    planner_name=None,
) -> RoutingDecision:
    features = TaskFeatures(
        category=TaskCategory.CODE_GENERATION,
        complexity=ComplexityLevel.SIMPLE,
        risk_level=RiskLevel.LOW,
    )
    return RoutingDecision(
        task_hash="test123",
        task_features=features,
        recommended_strategy=strategy,
        models=ModelAssignment(planner=planner_name, executor=executor_name),
        estimated_cost=0.001,
        baseline_cost=0.01,
        estimated_savings=0.9,
        estimated_quality=0.85,
        quality_loss_vs_baseline=0.0,
        risk_level=RiskLevel.LOW,
        requires_human_review=False,
        reasons=["test"],
        alternatives=[],
        budget_status="OK",
        quality_gate=[],
        fallback_policy=[],
        config_version="v1.1",
    )


class TestAgentExecutorDryRun:
    def test_dry_run_returns_analysis(self, tmp_path):
        router = MagicMock()
        decision = _make_decision()
        router.route.return_value = decision

        factory = MagicMock()
        registry = MagicMock()
        config = AgentConfig(dry_run=True)

        executor = AgentExecutor(router, factory, registry, config)
        report = executor.run("写个函数", tmp_path)

        assert "Dry Run" in report.final_response
        assert report.turns == 0
        assert report.cost.total_cost_cny == 0.0
        router.route.assert_called_once_with("写个函数")


class TestCostSummary:
    def test_record_cost(self):
        cost = CostSummary()
        model_entry = MagicMock()
        model_entry.name = "test-model"
        model_entry.input_price_per_1k = 0.01
        model_entry.output_price_per_1k = 0.02

        response = AdapterResponse(
            content="hello",
            input_tokens=1000,
            output_tokens=500,
            latency_ms=100,
            model="test-model",
        )
        cost.record(model_entry, response)

        assert cost.total_input_tokens == 1000
        assert cost.total_output_tokens == 500
        assert cost.total_cost_cny > 0
        assert "test-model" in cost.model_costs


class TestExecutionReport:
    def test_savings_calculation(self):
        decision = _make_decision()
        from airouter.engine.agent.goal import ExecutionGoal, GoalConstraints
        goal = ExecutionGoal(
            task="test",
            category=TaskCategory.CODE_GENERATION,
            complexity=ComplexityLevel.SIMPLE,
            risk_level=RiskLevel.LOW,
            strategy=StrategyType.SINGLE_MODEL,
            success_criteria=["test"],
            constraints=GoalConstraints(),
        )
        cost = CostSummary(total_cost_cny=0.005)
        report = ExecutionReport(
            goal=goal,
            decision=decision,
            final_response="done",
            tool_history=[],
            cost=cost,
            turns=1,
            elapsed_seconds=1.0,
            baseline_cost=0.01,
        )
        assert report.savings_vs_baseline == 0.5

    def test_success_with_output(self):
        decision = _make_decision()
        from airouter.engine.agent.goal import ExecutionGoal, GoalConstraints
        goal = ExecutionGoal(
            task="test",
            category=TaskCategory.CODE_GENERATION,
            complexity=ComplexityLevel.SIMPLE,
            risk_level=RiskLevel.LOW,
            strategy=StrategyType.SINGLE_MODEL,
            success_criteria=["test"],
            constraints=GoalConstraints(),
        )
        report = ExecutionReport(
            goal=goal,
            decision=decision,
            final_response="done",
            tool_history=[],
            cost=CostSummary(),
            turns=1,
            elapsed_seconds=1.0,
            baseline_cost=0.01,
        )
        assert report.success is True

    def test_cancelled_report(self):
        decision = _make_decision()
        report = ExecutionReport.make_cancelled(decision, "task")
        assert "取消" in report.final_response
        assert report.turns == 0
        assert report.cancelled is True
        assert report.success is False

    def test_render_text(self):
        decision = _make_decision()
        from airouter.engine.agent.goal import ExecutionGoal, GoalConstraints
        goal = ExecutionGoal(
            task="test",
            category=TaskCategory.CODE_GENERATION,
            complexity=ComplexityLevel.SIMPLE,
            risk_level=RiskLevel.LOW,
            strategy=StrategyType.SINGLE_MODEL,
            success_criteria=["test"],
            constraints=GoalConstraints(),
        )
        report = ExecutionReport(
            goal=goal,
            decision=decision,
            final_response="done",
            tool_history=[],
            cost=CostSummary(total_cost_cny=0.003),
            turns=1,
            elapsed_seconds=1.0,
            baseline_cost=0.01,
        )
        text = report.render_text()
        assert "AirRouter Agent" in text
        assert "CODE_GENERATION" in text


class TestAdapterResponseToolCalls:
    def test_tool_calls_field(self):
        response = AdapterResponse(
            content="",
            input_tokens=100,
            output_tokens=50,
            latency_ms=200,
            model="test",
            tool_calls=[{"id": "call_1", "type": "function", "function": {"name": "read_file", "arguments": "{}"}}],
            finish_reason="tool_calls",
        )
        assert response.tool_calls is not None
        assert len(response.tool_calls) == 1
        assert response.tool_calls[0]["function"]["name"] == "read_file"
        assert response.finish_reason == "tool_calls"

    def test_no_tool_calls_default(self):
        response = AdapterResponse(
            content="hello",
            input_tokens=100,
            output_tokens=50,
            latency_ms=200,
            model="test",
        )
        assert response.tool_calls is None
        assert response.finish_reason is None


class TestDryRunAndCancelled:
    def test_dry_run_has_dry_run_flag(self, tmp_path):
        router = MagicMock()
        router.route.return_value = _make_decision()
        config = AgentConfig(dry_run=True)
        executor = AgentExecutor(router, MagicMock(), MagicMock(), config)
        report = executor.run("test task", tmp_path)
        assert report.dry_run is True
        assert report.success is False

    def test_cancelled_has_cancelled_flag(self):
        decision = _make_decision()
        report = ExecutionReport.make_cancelled(decision, "task")
        assert report.cancelled is True
        assert report.success is False
        assert report.dry_run is False


class TestReviewParsing:
    def test_parse_pass_english(self):
        result = AgentExecutor._parse_review_result(
            "## 审查结论\nPASS\n\n## 审查详情\n一切正常"
        )
        assert result is True

    def test_parse_needs_fix_english(self):
        result = AgentExecutor._parse_review_result(
            "## 审查结论\nNEEDS_FIX\n\n## 审查详情\n缺少测试"
        )
        assert result is False

    def test_parse_pass_chinese(self):
        result = AgentExecutor._parse_review_result(
            "## 审查结论\n通过\n\n## 审查详情\n代码正确"
        )
        assert result is True

    def test_parse_needs_fix_chinese(self):
        result = AgentExecutor._parse_review_result(
            "## 审查结论\n需要修复\n\n## 审查详情\n逻辑错误"
        )
        assert result is False

    def test_parse_not_pass_chinese(self):
        result = AgentExecutor._parse_review_result(
            "## 审查结论\n不通过\n\n## 审查详情\n问题太多"
        )
        assert result is False

    def test_parse_unparseable(self):
        result = AgentExecutor._parse_review_result("这段代码看起来不错")
        assert result is None

    def test_parse_empty(self):
        result = AgentExecutor._parse_review_result("")
        assert result is None


class TestReviewAffectsSuccess:
    def _make_report(self, review=None, review_passed=None):
        from airouter.engine.agent.goal import ExecutionGoal, GoalConstraints
        decision = _make_decision()
        goal = ExecutionGoal(
            task="test",
            category=TaskCategory.CODE_GENERATION,
            complexity=ComplexityLevel.SIMPLE,
            risk_level=RiskLevel.LOW,
            strategy=StrategyType.SINGLE_MODEL,
            success_criteria=["test"],
            constraints=GoalConstraints(),
        )
        return ExecutionReport(
            goal=goal,
            decision=decision,
            final_response="done",
            tool_history=[],
            cost=CostSummary(),
            turns=1,
            elapsed_seconds=1.0,
            baseline_cost=0.01,
            review=review,
            review_passed=review_passed,
        )

    def test_review_pass_success(self):
        report = self._make_report(review="PASS", review_passed=True)
        assert report.success is True

    def test_review_needs_fix_failure(self):
        report = self._make_report(review="NEEDS_FIX", review_passed=False)
        assert report.success is False

    def test_review_none_still_success(self):
        report = self._make_report(review="unknown format", review_passed=None)
        assert report.success is True

    def test_no_review_success(self):
        report = self._make_report()
        assert report.success is True
