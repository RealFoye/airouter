"""共享 Agent 循环：从 AgentExecutor._run_single_agent 抽取。

ai-router run 和 ai-router agent 都走这套循环，避免逻辑分叉。
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from airouter.adapters.base import AdapterResponse, BaseAdapter
from airouter.config import ModelEntry
from airouter.engine.agent.report import CostSummary
from airouter.engine.agent.safety import SafetyGate
from airouter.engine.agent.text_parser import TextToolParser
from airouter.engine.agent.tools import TOOL_DEFINITIONS, ToolCallRecord, ToolExecutor

logger = logging.getLogger(__name__)


@dataclass
class LoopConfig:
    """Agent 循环配置。"""

    max_turns: int = 10
    max_cost_cny: float = 1.0


@dataclass
class LoopResult:
    """Agent 循环结果。"""

    final_response: str
    messages: list[dict]
    tool_history: list[ToolCallRecord]
    new_tool_history: list[ToolCallRecord]
    cost: CostSummary
    cost_delta_cny: float
    turns: int
    elapsed_seconds: float


def _extract_tool_calls(response: AdapterResponse) -> list[dict] | None:
    """提取工具调用：优先 function calling，fallback 到文本解析。"""
    if response.tool_calls:
        return response.tool_calls

    if response.content:
        parser = TextToolParser()
        text_calls = parser.parse(response.content)
        if text_calls:
            logger.info("使用文本解析 fallback，提取到 %d 个工具调用", len(text_calls))
            return text_calls

    return None


def run_agent_loop(
    *,
    adapter: BaseAdapter,
    model_entry: ModelEntry,
    messages: list[dict[str, Any]],
    workdir: Path,
    allowed_tools: list[str] | None,
    config: LoopConfig,
    existing_tool_exec: ToolExecutor | None = None,
    existing_cost: CostSummary | None = None,
    on_tool_call: Callable[[ToolCallRecord], None] | None = None,
    on_turn_start: Callable[[int], Callable[[], None]] | None = None,
) -> LoopResult:
    """共享 Agent 循环：chat → 提取 tool_calls → 执行 → 追加结果 → 重复。

    - 支持 function calling + TextToolParser fallback
    - 支持 CostSummary 累计
    - 支持 allowed_tools 过滤
    - 支持 max_cost / max_turns 上限
    - 每轮工具调用后触发 on_tool_call 回调（如果提供）
    - 每轮模型调用前触发 on_turn_start 回调（如果提供），返回 stop 函数

    Args:
        adapter: 模型适配器。
        model_entry: 模型配置。
        messages: 已构建好的消息列表（含 system + history + 当前 user）。会被原地修改。
        workdir: 工作目录。
        allowed_tools: 允许的工具列表，None 表示全部。
        config: 循环配置。
        existing_tool_exec: REPL 续接时传入已有的 ToolExecutor。
        existing_cost: REPL 续接时传入已有的 CostSummary。
        on_tool_call: 每次工具调用完成后的回调。
        on_turn_start: 每轮模型调用前的回调，接收 turn 编号，返回 stop 函数。
    """
    start_time = time.time()

    # 过滤工具定义：模型不该看到不允许的工具
    if allowed_tools is not None:
        filtered_tools = [
            t for t in TOOL_DEFINITIONS
            if t["function"]["name"] in allowed_tools
        ]
    else:
        filtered_tools = TOOL_DEFINITIONS

    # 创建或复用 ToolExecutor
    if existing_tool_exec is not None:
        tool_exec = existing_tool_exec
        # 关键：每轮更新 allowed_tools，确保本轮工具权限正确
        tool_exec.allowed_tools = allowed_tools
    else:
        safety = SafetyGate(workdir)
        tool_exec = ToolExecutor(workdir, safety, allowed_tools=allowed_tools)

    # 创建或复用 CostSummary
    cost = existing_cost if existing_cost is not None else CostSummary()
    cost_before = cost.total_cost_cny

    # 记录工具历史起点，用于切分 new_tool_history
    initial_history_len = len(tool_exec.history)
    callback_cursor = initial_history_len

    final_response = ""
    last_content = ""
    turns = 0

    for turn in range(config.max_turns):
        # 进入循环前先检查成本上限（避免已超限时仍调用一次 API）
        if cost.total_cost_cny >= config.max_cost_cny:
            final_response = (
                f"[成本上限] 已消耗 ¥{cost.total_cost_cny:.4f}，"
                f"超过上限 ¥{config.max_cost_cny:.4f}，停止执行。"
            )
            break

        turns = turn + 1
        logger.info("Turn %d/%d, 调用 %s", turns, config.max_turns, model_entry.name)

        # 触发 turn start 回调（用于 UI spinner）
        stop_spinner = on_turn_start(turns) if on_turn_start else None

        try:
            response = adapter.chat(
                model_entry.name,
                messages,
                tools=filtered_tools,
                tool_choice="auto",
            )
        finally:
            # API 抛错时也必须停止 spinner，否则终端会一直显示“思考中”。
            if stop_spinner:
                stop_spinner()

        cost.record(model_entry, response)

        # 始终记录最新的 content
        if response.content:
            last_content = response.content

        # 提取工具调用（支持 function calling 和文本 fallback）
        tool_calls = _extract_tool_calls(response)

        # 构建 assistant message
        msg: dict[str, Any] = {"role": "assistant", "content": response.content or ""}
        if tool_calls:
            msg["tool_calls"] = tool_calls
        messages.append(msg)

        # 没有 tool_calls → 任务完成
        if not tool_calls:
            final_response = response.content or ""
            break

        # 检查成本上限
        if cost.total_cost_cny >= config.max_cost_cny:
            # 成本超限时：执行当前 tool_calls 的 dummy result 避免孤立 tool_calls
            # 然后停止
            dummy_results = [
                {
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": "[成本上限] 未执行：已超限",
                }
                for tc in tool_calls
            ]
            messages.extend(dummy_results)
            final_response = (
                f"[成本上限] 已消耗 ¥{cost.total_cost_cny:.4f}，"
                f"超过上限 ¥{config.max_cost_cny:.4f}，停止执行。\n\n"
                f"{response.content or '(无输出)'}"
            )
            break

        # 执行工具
        tool_results = tool_exec.execute(tool_calls)
        messages.extend(tool_results)

        # 触发回调（只对本轮新增的记录触发）
        if on_tool_call:
            for record in tool_exec.history[callback_cursor:]:
                on_tool_call(record)
            callback_cursor = len(tool_exec.history)
    else:
        # max_turns 耗尽：用最后记录的 content 作为输出
        final_response = (
            f"[最大轮次] 已达到 {config.max_turns} 轮上限，停止执行。\n\n"
            f"{last_content or '(无输出)'}"
        )

    elapsed = time.time() - start_time
    cost_delta_cny = cost.total_cost_cny - cost_before

    return LoopResult(
        final_response=final_response,
        messages=messages,
        tool_history=tool_exec.history,
        new_tool_history=tool_exec.history[initial_history_len:],
        cost=cost,
        cost_delta_cny=cost_delta_cny,
        turns=turns,
        elapsed_seconds=elapsed,
    )
