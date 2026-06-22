"""ExecutionGoal + GoalBuilder: 从 RoutingDecision 构建执行目标。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from airouter.models.enums import (
    ComplexityLevel,
    RiskLevel,
    StrategyType,
    TaskCategory,
)
from airouter.models.schemas import RoutingDecision


@dataclass
class GoalConstraints:
    """Agent 执行约束。"""

    max_cost_cny: float = 1.0
    max_turns: int = 10
    allowed_tools: list[str] = field(
        default_factory=lambda: ["read_file", "edit_file", "write_file", "run_command"]
    )
    workdir: Path = field(default_factory=lambda: Path("."))
    requires_approval: bool = False
    dangerous_commands: list[str] = field(default_factory=list)


@dataclass
class ExecutionGoal:
    """Agent 执行目标。"""

    task: str
    category: TaskCategory
    complexity: ComplexityLevel
    risk_level: RiskLevel
    strategy: StrategyType
    success_criteria: list[str]
    constraints: GoalConstraints


# ── GoalBuilder ──────────────────────────────────────────────


class GoalBuilder:
    """从 RoutingDecision 构建 ExecutionGoal。"""

    @staticmethod
    def build(
        decision: RoutingDecision,
        task: str,
        workdir: Path,
        max_cost: float = 1.0,
        max_turns: int = 10,
        skip_approval: bool = False,
    ) -> ExecutionGoal:
        features = decision.task_features

        # 高风险或复杂任务自动增加 max_turns
        effective_max_turns = max_turns
        if features.risk_level == RiskLevel.HIGH:
            effective_max_turns = max(max_turns, 15)
        elif features.complexity in (ComplexityLevel.COMPLEX, ComplexityLevel.EXPERT):
            effective_max_turns = max(max_turns, 12)

        success_criteria = GoalBuilder._derive_success_criteria(features.category, features.risk_level)
        allowed_tools = GoalBuilder._select_tools(features.category, features.complexity, features.risk_level)

        requires_approval = (
            decision.requires_human_review and not skip_approval
        )

        constraints = GoalConstraints(
            max_cost_cny=max_cost,
            max_turns=effective_max_turns,
            allowed_tools=allowed_tools,
            workdir=workdir.resolve(),
            requires_approval=requires_approval,
        )

        return ExecutionGoal(
            task=task,
            category=features.category,
            complexity=features.complexity,
            risk_level=features.risk_level,
            strategy=decision.recommended_strategy,
            success_criteria=success_criteria,
            constraints=constraints,
        )

    @staticmethod
    def _derive_success_criteria(category: TaskCategory, risk_level: RiskLevel) -> list[str]:
        """根据任务类型推导成功标准。"""
        criteria: list[str] = []

        if category == TaskCategory.CODE_GENERATION:
            criteria.append("生成的代码语法正确且可运行")
            criteria.append("包含必要的错误处理")
        elif category == TaskCategory.CODE_REVIEW:
            criteria.append("输出发现的问题列表")
            criteria.append("每个问题标注行号和严重度")
        elif category == TaskCategory.REFACTORING:
            criteria.append("重构后代码功能不变")
            criteria.append("通过相关测试")
        elif category == TaskCategory.BUG_ANALYSIS:
            criteria.append("定位到 bug 根因")
            criteria.append("修复后通过相关测试")
        elif category == TaskCategory.TEST_GENERATION:
            criteria.append("测试可运行（pytest exit code 0）")
            criteria.append("覆盖目标函数/类")
        elif category == TaskCategory.DOCUMENTATION:
            criteria.append("文档内容准确完整")
        elif category == TaskCategory.ARCHITECTURE:
            criteria.append("输出架构设计方案")
        elif category == TaskCategory.DEVOPS:
            criteria.append("配置或脚本可执行")

        # 高风险任务额外标准
        if risk_level == RiskLevel.HIGH:
            criteria.append("所有修改在 git diff 中可追溯")

        if not criteria:
            criteria.append("任务完成且输出可用")

        return criteria

    @staticmethod
    def _select_tools(
        category: TaskCategory,
        complexity: ComplexityLevel,
        risk_level: RiskLevel,
    ) -> list[str]:
        """根据任务特征选择可用工具。"""
        base = ["read_file", "edit_file", "run_command"]

        # 代码生成/重构允许创建新文件
        if category in (TaskCategory.CODE_GENERATION, TaskCategory.REFACTORING):
            base.append("write_file")

        # 测试生成也需要创建文件
        if category == TaskCategory.TEST_GENERATION:
            base.append("write_file")

        # run_command 始终作为可选工具提供。真正的执行边界由 SafetyGate 负责：
        # ls 等只读命令直接运行，未列出的操作询问用户，不可逆操作仍硬拦截。
        # 这样即使“查看目录”被分类为 CONVERSATION，Agent 也能完成任务。

        return base
