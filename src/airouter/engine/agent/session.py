"""AgentSession: 交互式 REPL 会话管理器。

ai-router agent 命令的核心：多轮对话、上下文续接、session 持久化。
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from rich.console import Console
from rich.prompt import Confirm, Prompt
from rich.table import Table

from airouter.adapters.base import AdapterAuthError
from airouter.adapters.factory import AdapterFactory
from airouter.config import AppSettings, load_all
from airouter.engine.agent.goal import GoalBuilder
from airouter.engine.agent.loop import LoopConfig, run_agent_loop
from airouter.engine.agent.report import CostSummary
from airouter.engine.agent.safety import SafetyGate
from airouter.engine.agent.tools import ApprovalDecision, ToolCallRecord, ToolExecutor
from airouter.engine.complexity.analyzer import ComplexityAnalyzer
from airouter.engine.complexity.types import ComplexityContext
from airouter.engine.router.analyzer import TaskAnalyzer
from airouter.engine.router.estimator import CostEstimator
from airouter.engine.router.router import Router
from airouter.models.enums import StrategyType
from airouter.models.model_registry import ModelRegistry

logger = logging.getLogger(__name__)
console = Console()

# Session 根目录
SESSION_ROOT = Path(".airouter/sessions")


class AgentSession:
    """交互式 Agent 会话。"""

    def __init__(
        self,
        workdir: Path,
        model_override: str | None = None,
        skip_approval: bool = False,
        max_cost: float = 5.0,
        max_turns: int = 10,
    ):
        self.workdir = workdir.resolve()
        self.model_override = model_override
        self.skip_approval = skip_approval
        self.max_cost = max_cost
        self.max_turns = max_turns

        # 初始化组件（同 cli/run.py，强制 OpenSquilla 模式）
        config = load_all()
        settings = AppSettings()
        self.registry = ModelRegistry(config.models)
        # 交互式 Agent 必须真实调用模型；缺少 Key 时应明确失败，不能静默 Mock。
        self.factory = AdapterFactory(settings, allow_mock_fallback=False)

        agent_complexity = config.complexity.model_copy(update={"mode": "opensquilla"})
        if agent_complexity.bundle_dir is None:
            project_root = Path(__file__).resolve().parents[4]
            default_bundle = (
                project_root
                / "opensquilla/src/opensquilla/squilla_router/models/v4.2_phase3_inference"
            )
            if default_bundle.exists():
                agent_complexity = agent_complexity.model_copy(
                    update={"bundle_dir": default_bundle}
                )

        complexity_analyzer = ComplexityAnalyzer(
            agent_complexity,
            rule_analyzer=TaskAnalyzer(),
        )
        self.router = Router(
            config=config,
            complexity_analyzer=complexity_analyzer,
            model_registry=self.registry,
        )

        # Session 状态（延迟创建目录，resume 时不创建新目录）
        self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        self.session_dir = SESSION_ROOT / self.session_id
        # 不在此处 mkdir，由 save() 或 _ensure_session_dir() 按需创建

        # 累积状态
        self.history_messages: list[dict[str, Any]] = []  # 不含 system prompt
        self.cost = CostSummary()
        self.tool_exec = ToolExecutor(
            self.workdir,
            SafetyGate(self.workdir),
            approval_callback=self._approve_tool_call,
        )
        self.touched_files: set[str] = set()
        self.last_turn_summary: str = ""
        self.context_summary: str = ""
        self.turn_count: int = 0
        self.route_decisions: list[str] = []

    def print_banner(self):
        """打印欢迎信息。"""
        model_text = (
            f"{self.model_override} (手动固定，/model auto 恢复智能推荐)"
            if self.model_override
            else "auto (OpenSquilla + Router 智能推荐)"
        )
        console.print("[bold cyan]AirRouter Agent[/bold cyan] (interactive mode)")
        console.print(f"  workdir: {self.workdir}")
        console.print(f"  model:   {model_text}")
        console.print(f"  session: {self.session_id}")
        console.print(f"  max_cost: ¥{self.max_cost}")
        console.print("[dim]输入 /help 查看可用命令，/exit 退出[/dim]\n")

    def execute_turn(self, user_input: str) -> None:
        """执行单轮对话。"""
        self._ensure_session_dir()

        # 1. 当前任务和历史上下文分开传递，避免上一轮长任务文本污染本轮分类。
        complexity_context = self._build_complexity_context(user_input)

        # 2. 路由分析
        try:
            route_started = time.perf_counter()
            with console.status("[bold cyan]分析任务中...[/bold cyan]"):
                decision = self.router.route(
                    user_input,
                    complexity_context=complexity_context,
                )
            route_elapsed_ms = (time.perf_counter() - route_started) * 1000
        except Exception as e:
            console.print(f"[red]路由分析失败: {e}[/red]")
            return

        # 3. 构建 goal（用 user_input 原话，不是 routing_text）
        goal = GoalBuilder.build(
            decision,
            user_input,
            self.workdir,
            max_cost=self.max_cost,
            max_turns=self.max_turns,
            skip_approval=self.skip_approval,
        )

        # 4. 保留 Router 原始推荐，再应用用户的持久模型覆盖。
        router_recommended_model = decision.models.executor
        decision = self._apply_model_override(decision)

        # 5. 显示路由分析面板（让用户在确认前看到完整分析）
        self._print_routing_panel(
            decision,
            route_elapsed_ms,
            router_recommended_model=router_recommended_model,
        )

        # 5.1 PE/PER 策略提示
        if decision.recommended_strategy in (
            StrategyType.PLAN_EXECUTE,
            StrategyType.PLAN_EXECUTE_REVIEW,
        ):
            console.print(
                f"[yellow]ℹ 路由建议 {decision.recommended_strategy.value} 策略，"
                f"交互式模式当前使用单执行模型继续处理[/yellow]"
            )

        # 5.2 每轮确认模型。恢复会话或手动固定模型时也不能静默执行。
        executor_name = decision.models.executor
        if not self._confirm_execution_model(executor_name):
            console.print("[dim]已取消。输入 /model 选择模型，或 /model auto 恢复智能推荐。[/dim]")
            return

        # 6. 人工确认（如果高风险且未跳过）
        if goal.constraints.requires_approval and not self.skip_approval:
            if not Confirm.ask("[yellow]⚠ 此任务需要人工确认，继续执行？[/yellow]"):
                console.print("[dim]已取消本轮执行[/dim]")
                return

        # 7. 获取执行模型
        if not executor_name:
            console.print("[red]路由未指定执行模型[/red]")
            return

        model_entry = self.registry.get_by_name(executor_name)
        if not model_entry:
            console.print(f"[red]模型不存在: {executor_name}[/red]")
            return

        adapter = self.factory.get_adapter(model_entry)

        # 8. 构建运行时消息（临时构造，不存入 self）
        runtime_messages = self._build_runtime_messages(goal, user_input)

        # 9. 调用共享 agent loop
        try:
            result = run_agent_loop(
                adapter=adapter,
                model_entry=model_entry,
                messages=runtime_messages,
                workdir=self.workdir,
                allowed_tools=goal.constraints.allowed_tools,
                config=LoopConfig(
                    max_turns=self.max_turns,
                    max_cost_cny=self.max_cost,
                ),
                existing_tool_exec=self.tool_exec,
                existing_cost=self.cost,
                on_tool_call=self._on_tool_call,
                on_turn_start=self._on_turn_start,
            )
        except Exception as e:
            console.print(f"[red]执行失败: {e}[/red]")
            logger.exception("Agent loop failed")
            return

        # 10. 只持久化厂商无关的对话历史。
        # 同一轮内部仍使用原生 tool_calls/tool_call_id 完成工具循环；跨用户轮次时
        # 只保留 user 与最终 assistant 文本，避免切换模型后重新校验其他厂商的
        # function calling 历史而失败。完整工具轨迹另存于 tools.jsonl。
        self.history_messages = self._project_conversation_history(
            result.messages[1:],
            final_response=result.final_response,
        )

        # 11. 更新 last_turn_summary
        self._update_last_turn_summary(result.final_response, user_input)

        # 12. 持久化
        self._append_tool_records(result.new_tool_history)
        self._append_event({
            "turn": self.turn_count + 1,
            "timestamp": datetime.now().isoformat(),
            "user_input": user_input[:200],
            "decision_strategy": decision.recommended_strategy.value,
            "model": executor_name,
            "tool_calls_count": len(result.new_tool_history),
            "cost_this_turn": result.cost_delta_cny,
            "final_response_preview": result.final_response[:150],
        })
        self.turn_count += 1
        diag = decision.complexity_analysis
        route_class = (
            diag.ml_final_class
            if diag and diag.ml_final_class
            else decision.task_features.complexity.value
        )
        self.route_decisions.append(route_class)

        # 13. 输出结果
        self._print_turn_result(result, decision)

    def _build_complexity_context(self, user_input: str) -> ComplexityContext:
        """构造 OpenSquilla 结构化多轮上下文，不改变当前任务原文。"""
        user_history = tuple(
            message["content"]
            for message in self.history_messages
            if message.get("role") == "user" and message.get("content")
        )[-8:]
        prev_assistant = next(
            (
                message["content"]
                for message in reversed(self.history_messages)
                if message.get("role") == "assistant" and message.get("content")
            ),
            None,
        )
        recent_tools = self.tool_exec.history[-20:]
        return ComplexityContext.from_task(
            user_input,
            history=user_history,
            prev_assistant=prev_assistant,
            prev_decisions=tuple(self.route_decisions[-8:]),
            turn_index=self.turn_count,
            n_tools=len(recent_tools),
            tool_result_length=sum(len(record.result or "") for record in recent_tools),
        )

    def _apply_model_override(self, decision):
        """应用手动模型并按实际执行方案重算展示成本。

        Router 的原始成本属于自动推荐方案。若用户手动切换模型，只替换模型名
        却沿用原成本，会出现“qwen3.7-max 比自身节省成本”的错误展示。
        风险、审批和策略仍沿用 Router 结论，只有模型相关成本重新计算。
        """
        if not self.model_override:
            return decision
        decision = decision.model_copy(deep=True)
        decision.models.executor = self.model_override

        estimate = CostEstimator().estimate_strategy_cost(
            decision.recommended_strategy,
            decision.models,
            decision.task_features,
            self.registry,
        )
        estimated_cost = estimate.total_cost
        baseline_cost = decision.baseline_cost
        decision.estimated_cost = round(estimated_cost, 4)
        decision.estimated_savings = (
            max(0.0, 1.0 - estimated_cost / baseline_cost)
            if baseline_cost > 0
            else 0.0
        )
        decision.reasons.append(
            f"用户手动选择 {self.model_override}，成本已按该模型重新估算"
        )
        return decision

    def _confirm_execution_model(self, executor_name: str | None) -> bool:
        """每轮确认实际执行模型；--yes 明确表示跳过此确认。"""
        if self.skip_approval:
            return True
        if not executor_name:
            return False
        source = "手动固定模型" if self.model_override else "Router 推荐模型"
        return Confirm.ask(f"使用{source} {executor_name} 执行？", default=True)

    def _build_runtime_messages(self, goal, user_input: str) -> list[dict[str, Any]]:
        """临时构建本轮运行时消息。不存入 self。"""
        system = self._build_system_prompt(goal)
        history = self._get_history_messages()  # Phase 4 加压缩
        return (
            [{"role": "system", "content": system}]
            + history
            + [{"role": "user", "content": user_input}]
        )

    def _build_system_prompt(self, goal) -> str:
        """构建 Agent system prompt。"""
        from airouter.engine.agent.executor import AGENT_SYSTEM_PROMPT

        criteria_text = "\n".join(f"  - {c}" for c in goal.success_criteria)
        return AGENT_SYSTEM_PROMPT.format(
            category=goal.category.value,
            complexity=goal.complexity.value,
            risk_level=goal.risk_level.value,
            workdir=str(goal.constraints.workdir),
            success_criteria=criteria_text,
        )

    def _get_history_messages(self) -> list[dict[str, Any]]:
        """返回可注入的历史消息，必要时自动压缩。"""
        # 兼容旧会话：旧版本曾保存原生 tool_calls，其中可能包含损坏参数或
        # 某个供应商专属字段。每次注入前都投影一次，保证任意模型可安全接续。
        history = self._project_conversation_history(self.history_messages)
        self.history_messages = history
        total_tokens = self._estimate_tokens(history)

        # 阈值：保守估计 60k tokens（约 60% of 100k context window）
        compression_threshold = 60000

        if total_tokens > compression_threshold:
            history = self._compress_history(history)

        return history

    @staticmethod
    def _project_conversation_history(
        messages: list[dict[str, Any]],
        final_response: str | None = None,
    ) -> list[dict[str, Any]]:
        """将内部执行轨迹投影为跨模型兼容的对话历史。

        工具调用协议只在当前 Agent loop 内有效。跨轮历史仅保留用户消息和
        不含 tool_calls 的助手文本，避免不同供应商对 function arguments、
        tool_call_id 以及消息配对规则的差异导致请求被拒绝。
        """
        projected: list[dict[str, Any]] = []
        for message in messages:
            role = message.get("role")
            content = message.get("content")
            if role == "user" and isinstance(content, str) and content:
                projected.append({"role": "user", "content": content})
            elif (
                role == "assistant"
                and not message.get("tool_calls")
                and isinstance(content, str)
                and content
            ):
                projected.append({"role": "assistant", "content": content})

        if final_response and (
            not projected
            or projected[-1].get("role") != "assistant"
            or projected[-1].get("content") != final_response
        ):
            projected.append({"role": "assistant", "content": final_response})

        return projected

    def _estimate_tokens(self, messages: list[dict[str, Any]]) -> int:
        """粗略估算 token 数：1 token ≈ 4 characters for English, 2 for Chinese."""
        total_chars = 0
        for msg in messages:
            content = msg.get("content", "")
            if content:
                total_chars += len(content)
            # tool_calls 也占 token
            if msg.get("tool_calls"):
                total_chars += len(str(msg["tool_calls"]))
        return total_chars // 3  # 混合中英文估算

    def _compress_history(self, history: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """压缩历史消息：保留最近 4 个 turn blocks，旧 blocks 生成摘要。"""
        blocks = self._split_into_blocks(history)

        # 保留最近 4 个 blocks
        recent_blocks = blocks[-4:]
        old_blocks = blocks[:-4]

        if not old_blocks:
            return history

        # 检查第一个 block 是否已经是 summary
        existing_summary_text = None
        if old_blocks and old_blocks[0].get("is_summary"):
            summary_block = old_blocks.pop(0)
            if summary_block["messages"]:
                raw = summary_block["messages"][0].get("content", "")
                existing_summary_text = raw.replace("[Summary]\n", "", 1) if raw.startswith("[Summary]") else raw

        # 生成新摘要
        new_summary = self._summarize_blocks(old_blocks, existing_summary_text)

        # 组装结果
        result = []
        if new_summary:
            result.append({"role": "assistant", "content": f"[Summary]\n{new_summary}"})
            # 更新 context_summary 供 routing_text 使用
            self.context_summary = new_summary

        for block in recent_blocks:
            result.extend(block["messages"])

        # 安全检查：移除孤立 tool message
        result = self._remove_orphan_tool_messages(result)

        return result

    def _split_into_blocks(self, history: list[dict[str, Any]]) -> list[dict]:
        """将 history 分割为 turn blocks。

        一个 block = 一条 user message + 后续所有 assistant/tool messages 直到下一条 user。
        """
        blocks = []
        current_block: dict = {"messages": [], "is_summary": False}

        for msg in history:
            # 检查是否是已有的 summary
            if msg["role"] == "assistant" and msg.get("content", "").startswith("[Summary]"):
                if current_block["messages"]:
                    blocks.append(current_block)
                current_block = {"messages": [msg], "is_summary": True}
                blocks.append(current_block)
                current_block = {"messages": [], "is_summary": False}
                continue

            if msg["role"] == "user":
                if current_block["messages"]:
                    blocks.append(current_block)
                current_block = {"messages": [], "is_summary": False}

            current_block["messages"].append(msg)

        if current_block["messages"]:
            blocks.append(current_block)

        return blocks

    def _summarize_blocks(self, blocks: list[dict], existing_summary: str | None) -> str:
        """用轻量模型生成摘要。"""
        if not blocks:
            return existing_summary or ""

        content_parts = []
        if existing_summary:
            content_parts.append(f"之前的摘要:\n{existing_summary}")

        for block in blocks:
            for msg in block["messages"]:
                if msg["role"] == "user":
                    content_parts.append(f"用户请求: {msg['content'][:200]}")
                elif msg["role"] == "assistant" and not msg.get("tool_calls"):
                    content_parts.append(f"助手回复: {msg['content'][:300]}")
                elif msg["role"] == "tool":
                    content_parts.append(f"工具结果: {msg['content'][:150]}")

        if not content_parts:
            return existing_summary or ""

        # 尝试获取最便宜的模型
        adapter, model_entry = self._get_cheapest_adapter()
        if not adapter:
            # fallback: 简单拼接
            return "\n".join(content_parts)[:500]

        try:
            messages = [
                {
                    "role": "system",
                    "content": "请用简洁的中文总结以下开发会话历史，重点保留：修改了哪些文件、做了什么改动、当前状态。200字以内。",
                },
                {"role": "user", "content": "\n".join(content_parts)},
            ]
            response = adapter.chat(model_entry.name, messages)
            self.cost.record(model_entry, response)
            return response.content or ""
        except Exception as e:
            logger.warning("摘要生成失败: %s", e)
            return "\n".join(content_parts)[:500]

    def _get_cheapest_adapter(self):
        """获取最便宜的模型和适配器。"""
        candidates = sorted(
            self.registry.all_models,
            key=lambda model: model.input_price_per_1k + model.output_price_per_1k,
        )
        for model_entry in candidates:
            try:
                adapter = self.factory.get_adapter(model_entry)
            except AdapterAuthError:
                continue
            return adapter, model_entry
        return None, None

    def _remove_orphan_tool_messages(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """移除孤立的 tool message（没有对应 assistant tool_calls 的 tool result）。"""
        result = []
        pending_tool_ids: set[str] = set()

        for msg in messages:
            if msg["role"] == "assistant" and msg.get("tool_calls"):
                for tc in msg["tool_calls"]:
                    pending_tool_ids.add(tc["id"])
                result.append(msg)
            elif msg["role"] == "tool":
                tool_call_id = msg.get("tool_call_id", "")
                if tool_call_id in pending_tool_ids:
                    pending_tool_ids.discard(tool_call_id)
                    result.append(msg)
                # 否则丢弃孤立 tool message
            else:
                result.append(msg)

        return result

    def _update_last_turn_summary(self, final_response: str, user_input: str) -> None:
        """记录本轮摘要，供下一轮 routing_text 使用。"""
        preview = final_response[:150].replace("\n", " ")
        self.last_turn_summary = f"用户要求: {user_input[:80]} → {preview}"

    def _on_turn_start(self, turn: int) -> Callable[[], None]:
        """模型调用前回调：显示 thinking spinner。返回 stop 函数。"""
        status = console.status(f"[bold magenta]思考中...[/bold magenta] (turn {turn})")
        status.start()
        return status.stop

    def _on_tool_call(self, record: ToolCallRecord) -> None:
        """工具调用回调：实时显示状态 + 追踪 touched_files。"""
        args_short = str(record.args)
        if len(args_short) > 60:
            args_short = args_short[:57] + "..."
        if record.retryable:
            console.print(
                f"  [yellow]↻[/yellow] {record.name}()\n"
                "    [yellow]→ 工具参数或命令格式需要调整，正在自动请求重试[/yellow]"
            )
            return

        status = "✓" if record.success else "✗"
        style = "green" if record.success else "red"
        console.print(f"  [{style}]{status}[/{style}] {record.name}({args_short})")

        # 失败时显示错误原因
        if not record.success and record.result:
            # result 包含完整错误信息（如 "安全拦截: 命令不能为空"）
            err_msg = record.result[:120]
            console.print(f"    [red]→ {err_msg}[/red]")

        if record.success and record.name in ("write_file", "edit_file"):
            path = record.args.get("path", "")
            if path:
                self.touched_files.add(path)

    def _approve_tool_call(
        self,
        tool_name: str,
        args: dict[str, Any],
        reason: str,
    ) -> ApprovalDecision:
        """交互式批准白名单外但可授权的工具调用。"""
        if self.skip_approval:
            return "session"

        from rich.panel import Panel

        target = args.get("command") or str(args)
        console.print(
            Panel(
                f"[bold]{target}[/bold]\n\n[dim]{reason}[/dim]",
                title="[yellow]需要你的许可[/yellow]",
                border_style="yellow",
            )
        )
        choice = Prompt.ask(
            "允许执行？ [y] 本次 / [a] 本会话 / [n] 拒绝",
            choices=["y", "a", "n"],
            default="n",
            show_choices=False,
        )
        if choice == "y":
            return "once"
        if choice == "a":
            return "session"
        return "deny"

    def _print_routing_panel(
        self,
        decision,
        route_elapsed_ms: float,
        router_recommended_model: str | None = None,
    ) -> None:
        """显示路由分析面板（执行前展示，让用户看到完整分析）。"""
        from rich.panel import Panel
        from rich.text import Text

        route_text = Text()
        route_text.append("任务类型: ", style="bold")
        route_text.append(f"{decision.task_features.category.value}\n")
        route_text.append("复杂度: ", style="bold")
        route_text.append(f"{decision.task_features.complexity.value}\n")
        route_text.append("风险等级: ", style="bold")
        route_text.append(f"{decision.task_features.risk_level.value}\n")
        route_text.append("执行策略: ", style="bold")
        route_text.append(f"{decision.recommended_strategy.value}\n")

        diag = decision.complexity_analysis
        if diag and diag.ml_final_class:
            route_text.append("ML 复杂度: ", style="bold")
            route_text.append(f"{diag.ml_final_class} (mode={diag.mode})\n")
            if diag.ml_final_class_probability is not None:
                route_text.append("ML 置信度: ", style="bold")
                route_text.append(f"{diag.ml_final_class_probability * 100:.1f}%\n")
            if diag.ml_latency_ms is not None:
                route_text.append("ML 推理耗时: ", style="bold")
                route_text.append(f"{diag.ml_latency_ms:.1f} ms（本地）\n")
        elif diag:
            route_text.append("ML 状态: ", style="bold")
            route_text.append(
                f"不可用，已回退规则 ({diag.fallback_reason or 'unknown'})\n"
            )

        route_text.append("路由总耗时: ", style="bold")
        route_text.append(f"{route_elapsed_ms:.1f} ms（不调用大模型 API）\n")

        if decision.models.planner:
            route_text.append("规划模型: ", style="bold")
            route_text.append(f"{decision.models.planner}\n")
        if self.model_override:
            route_text.append("Router 自动推荐: ", style="bold")
            route_text.append(f"{router_recommended_model or '-'}\n")
        if decision.models.executor:
            route_text.append("实际执行模型: ", style="bold")
            model_suffix = "（手动固定）" if self.model_override else "（智能推荐）"
            route_text.append(f"{decision.models.executor}{model_suffix}\n")
        if decision.models.reviewer:
            route_text.append("审查模型: ", style="bold")
            route_text.append(f"{decision.models.reviewer}\n")

        route_text.append("单次调用预估: ", style="bold")
        route_text.append(f"¥{decision.estimated_cost:.4f}\n")
        route_text.append("最贵模型单次基线: ", style="bold")
        route_text.append(f"¥{decision.baseline_cost:.4f}\n")
        route_text.append("单次调用预计节省: ", style="bold")
        route_text.append(f"{decision.estimated_savings*100:.1f}%")
        if self.model_override and decision.estimated_savings <= 1e-12:
            route_text.append("（已是基线方案）", style="dim")
        route_text.append("\n会话成本上限: ", style="bold")
        route_text.append(f"¥{self.max_cost:.2f}\n")
        route_text.append(
            "说明: Agent 可能进行多轮模型调用，最终费用以本轮实际成本为准。",
            style="dim",
        )

        console.print(Panel(route_text, title="[bold blue]路由分析[/bold blue]", border_style="blue"))

    def _print_turn_result(self, result, decision) -> None:
        """打印本轮执行结果（路由面板已在执行前展示，此处只显示回复和成本）。"""

        # 工具调用已在执行期间通过 _on_tool_call 实时显示，此处不再重复

        # 最终回复
        if result.final_response:
            console.print(f"\n{result.final_response}\n")

        # 本轮成本
        console.print(
            f"[dim]本轮: ¥{result.cost_delta_cny:.4f} | "
            f"会话累计: ¥{self.cost.total_cost_cny:.4f}[/dim]\n"
        )

    # ── Slash Commands ────────────────────────────────────────

    SLASH_COMMANDS = {
        "/help": "显示帮助",
        "/model": "打开模型选择菜单（/model auto 恢复智能选模）",
        "/cost": "查看当前会话成本",
        "/files": "查看本会话修改的文件",
        "/summary": "查看上下文摘要",
        "/compact": "手动压缩上下文",
        "/reset": "清空当前会话上下文",
        "/exit": "退出",
    }

    def handle_slash(self, input_str: str) -> bool:
        """处理 slash command。返回 True 表示应退出 REPL。"""
        parts = input_str.strip().split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else None

        if cmd == "/exit":
            self.save()
            console.print("[dim]会话已保存，再见！[/dim]")
            return True
        elif cmd == "/help":
            self._cmd_help()
        elif cmd == "/model":
            self._cmd_model(arg)
        elif cmd == "/cost":
            self._cmd_cost()
        elif cmd == "/files":
            self._cmd_files()
        elif cmd == "/summary":
            self._cmd_summary()
        elif cmd == "/compact":
            self._cmd_compact()
        elif cmd == "/reset":
            self._cmd_reset()
        else:
            console.print(f"[red]未知命令: {cmd}，输入 /help 查看可用命令[/red]")
        return False

    def _cmd_help(self):
        console.print("\n[bold]可用命令:[/bold]")
        for cmd, desc in self.SLASH_COMMANDS.items():
            console.print(f"  {cmd:<12} {desc}")
        console.print()

    def _cmd_model(self, arg: str | None):
        if not arg:
            models = self.registry.all_models
            current = self.model_override or "auto"
            table = Table(title="选择执行模型", show_header=True, header_style="bold cyan")
            table.add_column("编号", justify="right", style="cyan", no_wrap=True)
            table.add_column("模型")
            table.add_column("档位", justify="center")
            table.add_column("供应商")
            table.add_column("当前", justify="center", no_wrap=True)
            table.add_row("0", "自动选择（推荐）", "-", "AirRouter", "✓" if current == "auto" else "")

            current_index = 0
            for index, model in enumerate(models, start=1):
                is_current = model.name == current
                if is_current:
                    current_index = index
                table.add_row(
                    str(index),
                    model.name,
                    f"Tier {model.tier}",
                    model.provider,
                    "✓" if is_current else "",
                )

            console.print()
            console.print(table)
            console.print("[dim]0 表示恢复 OpenSquilla + Router 智能推荐。[/dim]")

            # 非交互环境（例如日志重放或测试）只展示列表，避免阻塞 stdin。
            if not console.is_terminal:
                console.print("[dim]也可使用 /model <名称> 直接切换。[/dim]\n")
                return

            selected = Prompt.ask(
                "选择编号",
                choices=[str(i) for i in range(len(models) + 1)],
                default=str(current_index),
                show_choices=False,
            )
            if selected == "0":
                self.model_override = None
                console.print("[green]已恢复智能选模[/green]")
            else:
                self.model_override = models[int(selected) - 1].name
                console.print(f"[green]已切换到模型: {self.model_override}[/green]")
            return

        if arg.lower() == "auto":
            self.model_override = None
            console.print("[green]已恢复智能选模[/green]")
            return

        # 验证模型名
        model_entry = self.registry.get_by_name(arg)
        if not model_entry:
            console.print(f"[red]模型不存在: {arg}[/red]")
            return

        self.model_override = arg
        console.print(f"[green]已切换到模型: {arg}[/green]")

    def _cmd_cost(self):
        console.print("\n[bold]会话成本:[/bold]")
        console.print(f"  总成本: ¥{self.cost.total_cost_cny:.4f}")
        console.print(f"  输入 Token: {self.cost.total_input_tokens}")
        console.print(f"  输出 Token: {self.cost.total_output_tokens}")
        if self.cost.model_costs:
            console.print("  模型分布:")
            for model, cost in sorted(
                self.cost.model_costs.items(), key=lambda x: -x[1]
            ):
                tokens = self.cost.model_tokens.get(model, {})
                console.print(
                    f"    {model}: ¥{cost:.4f} "
                    f"(in={tokens.get('input', 0)}, out={tokens.get('output', 0)})"
                )
        console.print()

    def _cmd_files(self):
        files = self.touched_files | {
            r.args.get("path", "")
            for r in self.tool_exec.history
            if r.success and r.name in ("write_file", "edit_file")
        }
        files = {f for f in files if f}  # 过滤空字符串

        if not files:
            console.print("[dim]本会话尚未修改任何文件[/dim]")
            return

        console.print(f"\n[bold]已修改文件 ({len(files)} 个):[/bold]")
        for f in sorted(files):
            console.print(f"  {f}")
        console.print()

    def _cmd_summary(self):
        if not self.context_summary:
            console.print("[dim]尚未生成摘要（输入 /compact 生成）[/dim]")
            return

        console.print("\n[bold]上下文摘要:[/bold]")
        console.print(self.context_summary)
        console.print()

    def _cmd_compact(self):
        if len(self.history_messages) < 6:
            console.print("[dim]历史消息不足，无需压缩[/dim]")
            return

        compressed = self._compress_history(self.history_messages)
        self.history_messages = compressed

        # 从压缩结果中提取 context_summary
        for msg in self.history_messages:
            if msg.get("content", "").startswith("[Summary]"):
                self.context_summary = msg["content"].replace("[Summary]\n", "", 1)
                break

        console.print(f"[green]上下文已压缩：{len(self.history_messages)} 条消息[/green]")
        self._cmd_summary()

    def _cmd_reset(self):
        if not Confirm.ask("确定要清空当前会话上下文？（成本、历史文件保留）"):
            return

        self.history_messages = []
        self.last_turn_summary = ""
        self.context_summary = ""
        self.route_decisions = []
        self.tool_exec = ToolExecutor(
            self.workdir,
            SafetyGate(self.workdir),
            approval_callback=self._approve_tool_call,
        )
        console.print("[yellow]上下文已重置，成本和文件历史保留[/yellow]")

    # ── 持久化 ────────────────────────────────────────────────

    def save(self):
        """保存当前会话状态。"""
        self._ensure_session_dir()
        self._save_session_json()
        self._save_messages_current()
        self._save_cost()
        self._save_touched_files()

    def _ensure_session_dir(self):
        """确保 session 目录存在（延迟创建）。"""
        self.session_dir.mkdir(parents=True, exist_ok=True)

    def _save_session_json(self):
        meta = {
            "session_id": self.session_id,
            "workdir": str(self.workdir),
            "model_override": self.model_override,
            "skip_approval": self.skip_approval,
            "max_cost_cny": self.max_cost,
            "max_turns": self.max_turns,
            "created_at": self.session_id,  # 简化：用 session_id 作为创建时间
            "last_active_at": datetime.now().isoformat(),
            "turn_count": self.turn_count,
            "status": "active",
            "last_turn_summary": self.last_turn_summary,
            "context_summary": self.context_summary,
            "route_decisions": self.route_decisions,
        }
        (self.session_dir / "session.json").write_text(
            json.dumps(meta, indent=2, ensure_ascii=False)
        )

    def _save_messages_current(self):
        """保存 history_messages（不含 system prompt）。"""
        (self.session_dir / "messages.current.json").write_text(
            json.dumps(self.history_messages, indent=2, ensure_ascii=False)
        )

    def _save_cost(self):
        cost_data = {
            "total_cost_cny": self.cost.total_cost_cny,
            "total_input_tokens": self.cost.total_input_tokens,
            "total_output_tokens": self.cost.total_output_tokens,
            "model_costs": self.cost.model_costs,
            "model_tokens": self.cost.model_tokens,
        }
        (self.session_dir / "cost.json").write_text(
            json.dumps(cost_data, indent=2, ensure_ascii=False)
        )

    def _save_touched_files(self):
        files_data = {
            "files": sorted(self.touched_files),
            "last_updated": datetime.now().isoformat(),
        }
        (self.session_dir / "touched_files.json").write_text(
            json.dumps(files_data, indent=2, ensure_ascii=False)
        )

    def _append_event(self, event_data: dict):
        """追加审计事件到 events.jsonl。"""
        with open(self.session_dir / "events.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(event_data, ensure_ascii=False) + "\n")

    def _append_tool_records(self, records: list[ToolCallRecord]):
        """追加工具调用记录到 tools.jsonl。"""
        if not records:
            return
        with open(self.session_dir / "tools.jsonl", "a", encoding="utf-8") as f:
            for record in records:
                data = {
                    "name": record.name,
                    "args": record.args,
                    "success": record.success,
                    "error": record.error,
                    "retryable": record.retryable,
                    "result_preview": record.result[:500] if record.result else None,
                }
                f.write(json.dumps(data, ensure_ascii=False) + "\n")

    def restore(self, resume_id: str) -> bool:
        """恢复会话。返回 True 成功，False 失败。"""
        if resume_id == "latest":
            session_dir = self._find_latest_session()
        else:
            session_dir = SESSION_ROOT / resume_id

        if not session_dir or not (session_dir / "session.json").exists():
            console.print(f"[red]会话不存在: {resume_id}[/red]")
            return False

        try:
            # 读取 session.json
            meta = json.loads((session_dir / "session.json").read_text())
            restored_workdir = Path(meta["workdir"])
            restored_session_id = meta["session_id"]

            messages_file = session_dir / "messages.current.json"
            restored_messages = (
                json.loads(messages_file.read_text()) if messages_file.exists() else []
            )

            cost_file = session_dir / "cost.json"
            cost_data = json.loads(cost_file.read_text()) if cost_file.exists() else {}

            tools_file = session_dir / "tools.jsonl"
            restored_tools: list[ToolCallRecord] = []
            if tools_file.exists():
                for line in tools_file.read_text().splitlines():
                    if line.strip():
                        data = json.loads(line)
                        restored_tools.append(
                            ToolCallRecord(
                                name=data["name"],
                                args=data["args"],
                                result=data.get("result_preview") or "",
                                success=data["success"],
                                error=data.get("error"),
                                retryable=data.get("retryable", False),
                            )
                        )

            touched_file = session_dir / "touched_files.json"
            touched_data = (
                json.loads(touched_file.read_text()) if touched_file.exists() else {}
            )
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            console.print(f"[red]会话数据损坏，无法恢复: {resume_id} ({exc})[/red]")
            return False

        # 全部读取成功后再更新当前对象，避免恢复失败留下半成品状态。
        self.workdir = restored_workdir
        self.model_override = meta.get("model_override")
        self.session_id = restored_session_id
        self.session_dir = session_dir
        self.turn_count = meta.get("turn_count", 0)
        self.last_turn_summary = meta.get("last_turn_summary", "")
        self.context_summary = meta.get("context_summary", "")
        self.route_decisions = list(meta.get("route_decisions", []))
        # 旧会话可能包含供应商专属或损坏的 tool_calls。恢复时立即清洗，
        # 后续即使切换模型也只会发送厂商无关的 user/assistant 文本历史。
        self.history_messages = self._project_conversation_history(restored_messages)
        self.cost = CostSummary(
            total_cost_cny=cost_data.get("total_cost_cny", 0.0),
            total_input_tokens=cost_data.get("total_input_tokens", 0),
            total_output_tokens=cost_data.get("total_output_tokens", 0),
            model_costs=cost_data.get("model_costs", {}),
            model_tokens=cost_data.get("model_tokens", {}),
        )
        self.tool_exec = ToolExecutor(
            self.workdir,
            SafetyGate(self.workdir),
            approval_callback=self._approve_tool_call,
        )
        self.tool_exec.history.extend(restored_tools)
        self.touched_files = set(touched_data.get("files", []))

        console.print(f"[green]已恢复会话: {self.session_id} ({self.turn_count} 轮)[/green]")
        return True

    def _find_latest_session(self) -> Path | None:
        """查找最新的 session 目录（必须包含 session.json）。"""
        if not SESSION_ROOT.exists():
            return None

        sessions = sorted(
            [d for d in SESSION_ROOT.iterdir() if d.is_dir() and (d / "session.json").exists()],
            key=lambda d: d.name,
            reverse=True,
        )
        for session_dir in sessions:
            try:
                meta = json.loads((session_dir / "session.json").read_text())
                if meta.get("session_id") and meta.get("workdir"):
                    return session_dir
            except (OSError, json.JSONDecodeError, TypeError):
                continue
        return None
