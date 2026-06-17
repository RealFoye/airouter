"""CostTracker + ExecutionReport: Agent 执行的成本追踪和报告生成。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from airouter.adapters.base import AdapterResponse
from airouter.config import ModelEntry
from airouter.engine.agent.goal import ExecutionGoal
from airouter.engine.agent.tools import ToolCallRecord
from airouter.models.enums import StrategyType
from airouter.models.schemas import RoutingDecision


@dataclass
class CostSummary:
    """成本汇总。"""

    total_cost_cny: float = 0.0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    model_costs: dict[str, float] = field(default_factory=dict)
    model_tokens: dict[str, dict[str, int]] = field(default_factory=dict)

    def record(self, model_entry: ModelEntry, response: AdapterResponse) -> None:
        """记录一次模型调用的成本。"""
        cost = (
            response.input_tokens * model_entry.input_price_per_1k / 1000
            + response.output_tokens * model_entry.output_price_per_1k / 1000
        )
        self.total_cost_cny += cost
        self.total_input_tokens += response.input_tokens
        self.total_output_tokens += response.output_tokens

        name = model_entry.name
        self.model_costs[name] = self.model_costs.get(name, 0.0) + cost
        if name not in self.model_tokens:
            self.model_tokens[name] = {"input": 0, "output": 0}
        self.model_tokens[name]["input"] += response.input_tokens
        self.model_tokens[name]["output"] += response.output_tokens


@dataclass
class ExecutionReport:
    """Agent 执行报告。"""

    goal: ExecutionGoal
    decision: RoutingDecision
    final_response: str
    tool_history: list[ToolCallRecord]
    cost: CostSummary
    turns: int
    elapsed_seconds: float
    baseline_cost: float
    plan: str | None = None  # Plan-Execute 模式的计划文本
    review: str | None = None  # Reviewer 审查结果
    review_passed: bool | None = None  # True=PASS, False=NEEDS_FIX, None=无法解析
    dry_run: bool = False  # 是否仅分析未执行
    cancelled: bool = False  # 是否用户取消

    @property
    def savings_vs_baseline(self) -> float:
        """相比 baseline 的节省率。"""
        if self.baseline_cost <= 0:
            return 0.0
        return max(0.0, 1.0 - self.cost.total_cost_cny / self.baseline_cost)

    @property
    def success(self) -> bool:
        """判断执行是否成功。"""
        if self.dry_run or self.cancelled:
            return False
        if not self.final_response:
            return False
        if self.tool_history and all(not t.success for t in self.tool_history):
            return False
        if self.review_passed is False:
            return False
        return True

    @property
    def is_plan_execute(self) -> bool:
        return self.goal.strategy in (StrategyType.PLAN_EXECUTE, StrategyType.PLAN_EXECUTE_REVIEW)

    def render_text(self) -> str:
        """纯文本报告（用于 CLI）。"""
        lines = []
        lines.append("=" * 60)
        lines.append("AirRouter Agent 执行报告")
        lines.append("=" * 60)

        # 任务描述
        lines.append("")
        lines.append("[任务]")
        lines.append(f"  {self.goal.task}")

        # 路由分析
        lines.append("")
        lines.append("[路由分析]")
        lines.append(f"  任务类型: {self.goal.category.value}")
        lines.append(f"  复杂度:   {self.goal.complexity.value}")
        lines.append(f"  风险等级: {self.goal.risk_level.value}")
        lines.append(f"  执行策略: {self.goal.strategy.value}")

        diag = self.decision.complexity_analysis
        if diag and diag.ml_final_class:
            lines.append(f"  ML 复杂度: {diag.ml_final_class} (mode={diag.mode})")

        if self.decision.models.planner:
            lines.append(f"  规划模型: {self.decision.models.planner}")
        if self.decision.models.executor:
            lines.append(f"  执行模型: {self.decision.models.executor}")
        if self.decision.models.reviewer:
            lines.append(f"  审查模型: {self.decision.models.reviewer}")

        # 计划（Plan-Execute）
        if self.plan:
            lines.append("")
            lines.append("[执行计划]")
            for line in self.plan.splitlines():
                lines.append(f"  {line}")

        # 工具调用
        if self.tool_history:
            lines.append("")
            lines.append(f"[工具调用] ({len(self.tool_history)} 次)")
            for i, record in enumerate(self.tool_history, 1):
                status = "OK" if record.success else "FAIL"
                args_short = str(record.args)
                if len(args_short) > 60:
                    args_short = args_short[:57] + "..."
                lines.append(f"  {i}. [{status}] {record.name}({args_short})")

        # 成本
        lines.append("")
        lines.append("[成本]")
        lines.append(f"  实际成本: ¥{self.cost.total_cost_cny:.4f}")
        lines.append(f"  基线成本: ¥{self.baseline_cost:.4f}")
        lines.append(f"  节省率:   {self.savings_vs_baseline*100:.1f}%")
        lines.append(f"  输入 Token: {self.cost.total_input_tokens}")
        lines.append(f"  输出 Token: {self.cost.total_output_tokens}")
        lines.append(f"  执行轮次: {self.turns}")
        lines.append(f"  耗时: {self.elapsed_seconds:.1f}s")

        if self.cost.model_costs:
            lines.append("")
            lines.append("  模型分布:")
            for model, cost in sorted(self.cost.model_costs.items(), key=lambda x: -x[1]):
                tokens = self.cost.model_tokens.get(model, {})
                lines.append(
                    f"    {model}: ¥{cost:.4f} "
                    f"(in={tokens.get('input', 0)}, out={tokens.get('output', 0)})"
                )

        # 审查结果
        if self.review:
            lines.append("")
            if self.review_passed is True:
                lines.append("[审查结果] 审查通过")
            elif self.review_passed is False:
                lines.append("[审查结果] 需修复")
            else:
                lines.append("[审查结果] 审查结果需要人工判断")
            for line in self.review.splitlines():
                lines.append(f"  {line}")

        # 最终输出
        lines.append("")
        lines.append("[最终输出]")
        lines.append(self.final_response)

        # Verdict
        lines.append("")
        if self.dry_run:
            lines.append("[结果] 仅分析，未执行")
        elif self.cancelled:
            lines.append("[结果] 用户取消执行")
        elif self.success:
            lines.append("[结果] 执行成功")
        else:
            lines.append("[结果] 执行失败")

        lines.append("=" * 60)
        return "\n".join(lines)

    @staticmethod
    def make_cancelled(decision: RoutingDecision, task: str = "") -> ExecutionReport:
        """用户取消执行时的空报告。"""
        from airouter.engine.agent.goal import GoalConstraints

        constraints = GoalConstraints(
            max_cost_cny=0.0,
            max_turns=0,
            allowed_tools=[],
            workdir=Path("."),
            requires_approval=False,
        )

        goal = ExecutionGoal(
            task=task,
            category=decision.task_features.category,
            complexity=decision.task_features.complexity,
            risk_level=decision.task_features.risk_level,
            strategy=decision.recommended_strategy,
            success_criteria=[],
            constraints=constraints,
        )
        return ExecutionReport(
            goal=goal,
            decision=decision,
            final_response="[用户取消执行]",
            tool_history=[],
            cost=CostSummary(),
            turns=0,
            elapsed_seconds=0.0,
            baseline_cost=decision.baseline_cost,
            cancelled=True,
        )
