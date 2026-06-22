"""AgentExecutor: Router → Goal → Agent 执行循环。"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from airouter.adapters.base import AdapterResponse, BaseAdapter
from airouter.adapters.factory import AdapterFactory
from airouter.config import ModelEntry
from airouter.engine.agent.goal import ExecutionGoal, GoalBuilder
from airouter.engine.agent.loop import LoopConfig, run_agent_loop
from airouter.engine.agent.report import CostSummary, ExecutionReport
from airouter.engine.agent.safety import SafetyGate
from airouter.engine.agent.text_parser import TEXT_TOOL_SYSTEM_PROMPT, TextToolParser
from airouter.engine.agent.tools import TOOL_DEFINITIONS, ToolExecutor
from airouter.engine.router.router import Router
from airouter.models.enums import StrategyType
from airouter.models.model_registry import ModelRegistry
from airouter.models.schemas import RoutingDecision

logger = logging.getLogger(__name__)


# ── Agent 配置 ───────────────────────────────────────────────


@dataclass
class AgentConfig:
    """Agent 运行配置。"""

    max_cost_cny: float = 1.0
    max_turns: int = 10
    skip_approval: bool = False
    dry_run: bool = False


# ── System Prompts ───────────────────────────────────────────

AGENT_SYSTEM_PROMPT = """你是 AirRouter 智能执行助手。你通过工具来完成开发任务。

## 可用工具
- read_file(path, offset?, limit?): 读取文件内容。修改前必须先读取。
- write_file(path, content): 创建或覆盖文件（自动备份）。
- edit_file(path, old_text, new_text): 精确替换文件中的文本。
- run_command(command): 执行受控开发命令，支持 Python/Node 测试、依赖安装、构建、lint、类型检查和只读诊断。

## 工具调用边界（必须遵守）
- 工具已经在工作目录中运行，所有文件路径必须使用相对路径；查看当前目录用 `ls -la`，不要重复写工作目录的绝对路径。
- 不要使用 `python -c` / `python3 -c`、Shell 重定向或 `&&` / `||` / `;` / `|` 串联命令。
- 需要多个检查时，分别调用多次 run_command；不要把它们拼成一条命令。
- 不允许删除文件、危险 Git 操作、系统权限修改或启动长期运行服务。

## 高效探索（节省轮次，非常重要）
- 第一步：用 run_command("find . -name '*.py' -not -path './.venv/*'") 快速列出所有 Python 文件
- 第二步：根据任务关键词，只 read_file 直接相关的文件，不要逐个读目录下的所有文件
- 如果任务提到具体文件名（如 auth.py），直接 read_file 该文件，不要先探索目录
- 不要读测试文件，除非任务明确要求修改测试

## 工作原则
1. 先探索再修改：用 find 命令了解结构，只读必要文件
2. 先读后改：修改任何文件前必须先 read_file 查看完整内容
3. 改完验证：修改代码后使用项目已有的测试、lint、类型检查或构建命令验证
4. 精确修改：优先使用 edit_file（只改需要改的），避免 write_file 覆盖全文件
5. 不做超出范围的事：只完成用户要求的任务
6. 不确定就停：如果遇到不确定的情况，说明原因并停止

## 项目结构提示
常见项目结构：src/ 目录下是源码，tests/ 目录下是测试。
如果不确定文件位置，先 run_command("find . -name '*.py'") 快速定位。

## 任务信息
- 任务类型: {category}
- 复杂度: {complexity}
- 风险等级: {risk_level}
- 工作目录: {workdir}

## 完成标准
{success_criteria}

当你认为任务已完成时，直接输出总结，不要再调用工具。"""

# 追加 TextToolParser fallback 格式说明（Fix 4a）
AGENT_SYSTEM_PROMPT += "\n\n" + TEXT_TOOL_SYSTEM_PROMPT

PLANNER_SYSTEM_PROMPT = """你是一个高级技术规划师。你的任务是分析开发任务并输出执行计划。

你不需要调用工具，只需要：
1. 分析任务要求
2. 识别需要修改的文件和关键改动点
3. 输出分步执行计划
4. 标注风险点和验证方法

输出格式：
## 分析
（任务分析）

## 执行计划
1. （步骤1：做什么、改哪个文件、怎么改）
2. （步骤2...）

## 验证
（如何验证修改正确）

## 风险
（潜在风险和注意事项）"""

REVIEWER_SYSTEM_PROMPT = """你是一个代码审查专家。你的任务是审查执行结果是否符合要求。

请审查以下内容：
1. 最终输出是否满足原始任务要求
2. 代码修改是否正确、安全
3. 测试是否充分

输出格式：
## 审查结论
PASS 或 NEEDS_FIX

## 审查详情
（具体问题列表，如果 NEEDS_FIX 则说明需要修复什么）"""


# ── AgentExecutor ────────────────────────────────────────────


class AgentExecutor:
    """Agent 执行器：路由分析 → 构建目标 → 工具执行 → 生成报告。"""

    def __init__(
        self,
        router: Router,
        factory: AdapterFactory,
        registry: ModelRegistry,
        config: AgentConfig | None = None,
    ):
        self.router = router
        self.factory = factory
        self.registry = registry
        self.config = config or AgentConfig()

    def run(self, task: str, workdir: Path) -> ExecutionReport:
        """完整的 Agent 执行流程。"""
        start_time = time.time()

        # 1. 路由分析
        decision = self._route(task)

        # 2. 构建执行目标
        goal = GoalBuilder.build(
            decision,
            task,
            workdir,
            max_cost=self.config.max_cost_cny,
            max_turns=self.config.max_turns,
            skip_approval=self.config.skip_approval,
        )

        # 3. Dry run: 只分析不执行
        if self.config.dry_run:
            return self._dry_run_report(goal, decision, start_time)

        # 4. 人工确认
        if goal.constraints.requires_approval:
            print(self._render_approval_prompt(decision, goal))
            answer = input("是否继续执行? [y/N]: ").strip().lower()
            if answer not in ("y", "yes"):
                return ExecutionReport.make_cancelled(decision, task)

        # 5. 执行
        if decision.recommended_strategy in (
            StrategyType.PLAN_EXECUTE,
            StrategyType.PLAN_EXECUTE_REVIEW,
        ):
            report = self._run_plan_execute(goal, decision, start_time)
        else:
            report = self._run_single_agent(goal, decision, start_time)

        return report

    def _route(self, task: str) -> RoutingDecision:
        """调用 Router 进行路由分析。"""
        logger.info("Router 分析中...")
        return self.router.route(task)

    def _get_adapter(self, model_name: str) -> tuple[BaseAdapter, ModelEntry]:
        """获取模型适配器和模型配置。"""
        model_entry = self.registry.get_by_name(model_name)
        if not model_entry:
            raise ValueError(f"模型不存在: {model_name}")
        adapter = self.factory.get_adapter(model_entry)
        return adapter, model_entry

    def _extract_tool_calls(self, response: AdapterResponse) -> list[dict] | None:
        """提取工具调用：优先 function calling，fallback 到文本解析。"""
        # 优先使用原生 function calling
        if response.tool_calls:
            return response.tool_calls

        # Fallback: 尝试从文本内容解析工具调用
        if response.content:
            parser = TextToolParser()
            text_calls = parser.parse(response.content)
            if text_calls:
                logger.info("使用文本解析 fallback，提取到 %d 个工具调用", len(text_calls))
                return text_calls

        return None

    def _run_single_agent(
        self, goal: ExecutionGoal, decision: RoutingDecision, start_time: float
    ) -> ExecutionReport:
        """单模型 Agent 执行循环（委托给共享 run_agent_loop）。"""
        executor_name = decision.models.executor
        if not executor_name:
            raise ValueError("RoutingDecision 未指定 executor 模型")

        adapter, model_entry = self._get_adapter(executor_name)

        messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": self._build_system_prompt(goal),
            },
            {"role": "user", "content": goal.task},
        ]

        result = run_agent_loop(
            adapter=adapter,
            model_entry=model_entry,
            messages=messages,
            workdir=goal.constraints.workdir,
            allowed_tools=goal.constraints.allowed_tools,
            config=LoopConfig(
                max_turns=goal.constraints.max_turns,
                max_cost_cny=goal.constraints.max_cost_cny,
            ),
        )

        elapsed = time.time() - start_time
        agent_baseline = self._compute_agent_baseline(result.cost)

        return ExecutionReport(
            goal=goal,
            decision=decision,
            final_response=result.final_response,
            tool_history=result.tool_history,
            cost=result.cost,
            turns=result.turns,
            elapsed_seconds=elapsed,
            baseline_cost=agent_baseline,
        )

    def _compute_agent_baseline(self, cost: CostSummary) -> float:
        """计算 Agent 基线成本：假设用 Tier 1 最贵模型处理相同 token 量。"""
        tier1_models = self.registry.get_tier1_models()
        if not tier1_models:
            return cost.total_cost_cny

        # 找最贵的 Tier 1 模型
        max_input_price = max(m.input_price_per_1k for m in tier1_models)
        max_output_price = max(m.output_price_per_1k for m in tier1_models)

        baseline = (
            cost.total_input_tokens * max_input_price / 1000
            + cost.total_output_tokens * max_output_price / 1000
        )
        return round(baseline, 4)

    def _run_plan_execute(
        self, goal: ExecutionGoal, decision: RoutingDecision, start_time: float
    ) -> ExecutionReport:
        """Plan-Execute 多模型 Agent。"""
        planner_name = decision.models.planner
        executor_name = decision.models.executor
        reviewer_name = decision.models.reviewer

        if not planner_name or not executor_name:
            logger.warning("Plan-Execute 缺少 planner 或 executor，回退到单模型")
            return self._run_single_agent(goal, decision, start_time)

        cost = CostSummary()  # 统一成本追踪

        # Phase 1: Planner 规划
        logger.info("Phase 1: Planner (%s) 分析规划中...", planner_name)
        plan = self._planning_phase(goal, planner_name, cost)

        # Phase 2: Executor 执行
        logger.info("Phase 2: Executor (%s) 执行中...", executor_name)
        report = self._execution_phase(goal, decision, executor_name, plan, start_time, cost)

        # Phase 3: Reviewer 审查（仅 PER 策略）
        if decision.recommended_strategy == StrategyType.PLAN_EXECUTE_REVIEW and reviewer_name:
            logger.info("Phase 3: Reviewer (%s) 审查中...", reviewer_name)
            review_text = self._review_phase(
                goal, reviewer_name, report.final_response, report.tool_history, cost,
            )
            report.review = review_text
            report.review_passed = self._parse_review_result(review_text)

        # 全部阶段完成后重新计算 baseline
        report.baseline_cost = self._compute_agent_baseline(cost)

        return report

    def _planning_phase(self, goal: ExecutionGoal, planner_name: str, cost: CostSummary) -> str:
        """Planner 阶段：分析任务，输出执行计划。"""
        adapter, model_entry = self._get_adapter(planner_name)

        messages = [
            {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
            {"role": "user", "content": goal.task},
        ]

        response = adapter.chat(model_entry.name, messages)
        cost.record(model_entry, response)
        return response.content or "(Planner 未输出计划)"

    def _execution_phase(
        self,
        goal: ExecutionGoal,
        decision: RoutingDecision,
        executor_name: str,
        plan: str,
        start_time: float,
        cost: CostSummary,
    ) -> ExecutionReport:
        """Executor 阶段：按计划执行工具调用。"""
        adapter, model_entry = self._get_adapter(executor_name)
        safety = SafetyGate(goal.constraints.workdir)
        tool_exec = ToolExecutor(
            goal.constraints.workdir,
            safety,
            allowed_tools=goal.constraints.allowed_tools,
        )
        # 不再创建 CostSummary()，使用传入的 cost

        # 过滤工具定义：模型不该看到不允许的工具
        if goal.constraints.allowed_tools is not None:
            filtered_tools = [
                t for t in TOOL_DEFINITIONS
                if t["function"]["name"] in goal.constraints.allowed_tools
            ]
        else:
            filtered_tools = TOOL_DEFINITIONS

        system_prompt = self._build_system_prompt(goal)
        system_prompt += f"\n\n## 执行计划（由 Planner 生成）\n请严格按照以下计划执行：\n\n{plan}"

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"请按照执行计划完成以下任务：\n\n{goal.task}"},
        ]

        final_response = ""
        last_content = ""
        turns = 0

        for turn in range(goal.constraints.max_turns):
            turns = turn + 1

            response = adapter.chat(
                model_entry.name,
                messages,
                tools=filtered_tools,
                tool_choice="auto",
            )

            cost.record(model_entry, response)

            if response.content:
                last_content = response.content

            # 提取工具调用（支持 function calling 和文本 fallback）
            tool_calls = self._extract_tool_calls(response)

            msg: dict[str, Any] = {"role": "assistant", "content": response.content or ""}
            if tool_calls:
                msg["tool_calls"] = tool_calls
            messages.append(msg)

            if not tool_calls:
                final_response = response.content or ""
                break

            if cost.total_cost_cny >= goal.constraints.max_cost_cny:
                final_response = (
                    f"[成本上限] 已消耗 ¥{cost.total_cost_cny:.4f}，停止执行。\n\n"
                    f"{response.content or '(无输出)'}"
                )
                break

            tool_results = tool_exec.execute(tool_calls)
            messages.extend(tool_results)
        else:
            final_response = (
                f"[最大轮次] 已达到 {goal.constraints.max_turns} 轮上限。\n\n"
                f"{last_content or '(无输出)'}"
            )

        elapsed = time.time() - start_time

        return ExecutionReport(
            goal=goal,
            decision=decision,
            final_response=final_response,
            tool_history=tool_exec.history,
            cost=cost,
            turns=turns,
            elapsed_seconds=elapsed,
            baseline_cost=0.0,  # 将在 _run_plan_execute 中重新计算
            plan=plan,
        )

    def _review_phase(
        self,
        goal: ExecutionGoal,
        reviewer_name: str,
        final_response: str,
        tool_history: list,
        cost: CostSummary,
    ) -> str:
        """Reviewer 阶段：审查执行结果。"""
        adapter, model_entry = self._get_adapter(reviewer_name)

        tool_summary = "\n".join(
            f"- [{'OK' if t.success else 'FAIL'}] {t.name}({str(t.args)[:80]})"
            for t in tool_history
        )

        messages = [
            {"role": "system", "content": REVIEWER_SYSTEM_PROMPT},
            {"role": "user", "content": (
                f"## 原始任务\n{goal.task}\n\n"
                f"## 执行的工具调用\n{tool_summary}\n\n"
                f"## 最终输出\n{final_response}\n\n"
                f"## 成功标准\n" +
                "\n".join(f"- {c}" for c in goal.success_criteria)
            )},
        ]

        response = adapter.chat(model_entry.name, messages)
        cost.record(model_entry, response)
        return response.content or "(Reviewer 未输出审查结果)"

    @staticmethod
    def _parse_review_result(review_text: str) -> bool | None:
        """解析审查结论：PASS/通过 → True, NEEDS_FIX/需要修复/不通过 → False, 解析不到 → None。"""
        lines = review_text.split("\n")
        found_header = False
        for line in lines:
            if "审查结论" in line:
                found_header = True
                continue
            if found_header:
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                if stripped.startswith("PASS") or stripped.startswith("通过"):
                    return True
                if stripped.startswith("NEEDS_FIX") or stripped.startswith("需要修复") or stripped.startswith("不通过"):
                    return False
                break
        return None

    def _build_system_prompt(self, goal: ExecutionGoal) -> str:
        """构建 Agent system prompt。"""
        criteria_text = "\n".join(f"  - {c}" for c in goal.success_criteria)
        return AGENT_SYSTEM_PROMPT.format(
            category=goal.category.value,
            complexity=goal.complexity.value,
            risk_level=goal.risk_level.value,
            workdir=str(goal.constraints.workdir),
            success_criteria=criteria_text,
        )

    def _dry_run_report(
        self, goal: ExecutionGoal, decision: RoutingDecision, start_time: float
    ) -> ExecutionReport:
        """Dry run: 只输出路由分析，不执行。"""
        elapsed = time.time() - start_time
        lines = [
            "[Dry Run] 仅展示路由分析结果，不执行。",
            "",
            f"任务类型: {goal.category.value}",
            f"复杂度:   {goal.complexity.value}",
            f"风险等级: {goal.risk_level.value}",
            f"执行策略: {goal.strategy.value}",
        ]
        if decision.models.planner:
            lines.append(f"规划模型: {decision.models.planner}")
        if decision.models.executor:
            lines.append(f"执行模型: {decision.models.executor}")
        lines.append(f"预估成本: ¥{decision.estimated_cost:.4f}")
        lines.append(f"基线成本: ¥{decision.baseline_cost:.4f}")
        lines.append(f"预估节省: {decision.estimated_savings*100:.1f}%")

        diag = decision.complexity_analysis
        if diag and diag.ml_final_class:
            lines.append(f"ML 复杂度: {diag.ml_final_class} (mode={diag.mode})")

        lines.append("")
        lines.append("成功标准:")
        for c in goal.success_criteria:
            lines.append(f"  - {c}")

        return ExecutionReport(
            goal=goal,
            decision=decision,
            final_response="\n".join(lines),
            tool_history=[],
            cost=CostSummary(),
            turns=0,
            elapsed_seconds=elapsed,
            baseline_cost=decision.baseline_cost,
            dry_run=True,
        )

    def _render_approval_prompt(self, decision: RoutingDecision, goal: ExecutionGoal) -> str:
        """渲染人工确认提示。"""
        lines = [
            "",
            "=" * 50,
            "[需要确认] 此任务需要人工审批",
            "=" * 50,
            f"原因: {decision.human_review_reason or '高风险任务'}",
            f"任务类型: {goal.category.value}",
            f"复杂度:   {goal.complexity.value}",
            f"风险等级: {goal.risk_level.value}",
            f"执行策略: {goal.strategy.value}",
        ]
        if decision.models.planner:
            lines.append(f"规划模型: {decision.models.planner}")
        if decision.models.executor:
            lines.append(f"执行模型: {decision.models.executor}")
        lines.append(f"预估成本: ¥{decision.estimated_cost:.4f}")
        lines.append("=" * 50)
        return "\n".join(lines)
