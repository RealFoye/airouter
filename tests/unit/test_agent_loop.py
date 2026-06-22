"""run_agent_loop() 单元测试。"""

from unittest.mock import MagicMock

import pytest

from airouter.adapters.base import AdapterResponse
from airouter.engine.agent.loop import LoopConfig, run_agent_loop


def _make_model_entry(name="test-model"):
    entry = MagicMock()
    entry.name = name
    entry.input_price_per_1k = 0.01
    entry.output_price_per_1k = 0.02
    return entry


def _text_response(content="done", input_tokens=100, output_tokens=50):
    return AdapterResponse(
        content=content,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        latency_ms=100,
        model="test-model",
    )


def _tool_call_response(
    tool_name="read_file", tool_args=None, call_id="call_1",
    input_tokens=100, output_tokens=50,
):
    import json

    return AdapterResponse(
        content="",
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        latency_ms=100,
        model="test-model",
        tool_calls=[
            {
                "id": call_id,
                "type": "function",
                "function": {
                    "name": tool_name,
                    "arguments": json.dumps(tool_args or {"path": "test.py"}),
                },
            }
        ],
        finish_reason="tool_calls",
    )


class TestNormalCompletion:
    def test_no_tool_calls_returns_text(self, tmp_path):
        adapter = MagicMock()
        adapter.chat.return_value = _text_response("任务完成")

        messages = [
            {"role": "system", "content": "you are helper"},
            {"role": "user", "content": "hello"},
        ]

        result = run_agent_loop(
            adapter=adapter,
            model_entry=_make_model_entry(),
            messages=messages,
            workdir=tmp_path,
            allowed_tools=None,
            config=LoopConfig(max_turns=3),
        )

        assert result.final_response == "任务完成"
        assert result.turns == 1
        assert result.cost.total_cost_cny > 0
        adapter.chat.assert_called_once()

    def test_messages_appended(self, tmp_path):
        adapter = MagicMock()
        adapter.chat.return_value = _text_response("done")

        messages = [{"role": "user", "content": "hi"}]

        result = run_agent_loop(
            adapter=adapter,
            model_entry=_make_model_entry(),
            messages=messages,
            workdir=tmp_path,
            allowed_tools=None,
            config=LoopConfig(),
        )

        # user + assistant
        assert len(result.messages) == 2
        assert result.messages[1]["role"] == "assistant"

    def test_spinner_stops_when_adapter_raises(self, tmp_path):
        adapter = MagicMock()
        adapter.chat.side_effect = RuntimeError("upstream rejected request")
        stop_spinner = MagicMock()
        on_turn_start = MagicMock(return_value=stop_spinner)

        with pytest.raises(RuntimeError, match="upstream rejected request"):
            run_agent_loop(
                adapter=adapter,
                model_entry=_make_model_entry(),
                messages=[{"role": "user", "content": "hello"}],
                workdir=tmp_path,
                allowed_tools=None,
                config=LoopConfig(),
                on_turn_start=on_turn_start,
            )

        on_turn_start.assert_called_once_with(1)
        stop_spinner.assert_called_once_with()


class TestToolCallsExecution:
    def test_tool_calls_executed_and_continued(self, tmp_path):
        """模型返回 tool_calls → 执行 → 继续 → 最终文本回复。"""
        adapter = MagicMock()
        adapter.chat.side_effect = [
            _tool_call_response("read_file", {"path": "test.py"}),
            _text_response("文件内容是..."),
        ]

        messages = [{"role": "user", "content": "read test.py"}]

        result = run_agent_loop(
            adapter=adapter,
            model_entry=_make_model_entry(),
            messages=messages,
            workdir=tmp_path,
            allowed_tools=["read_file"],
            config=LoopConfig(),
        )

        assert result.final_response == "文件内容是..."
        assert result.turns == 2
        assert len(result.new_tool_history) >= 1
        assert adapter.chat.call_count == 2

    def test_new_tool_history_only_current_turn(self, tmp_path):
        """传入 existing_tool_exec 时，new_tool_history 只含本轮新增。"""
        from airouter.engine.agent.safety import SafetyGate
        from airouter.engine.agent.tools import ToolCallRecord, ToolExecutor

        existing_exec = ToolExecutor(tmp_path, SafetyGate(tmp_path))
        existing_exec.history.append(
            ToolCallRecord(name="read_file", args={"path": "old.py"}, result="old content", success=True)
        )

        adapter = MagicMock()
        adapter.chat.side_effect = [
            _tool_call_response("read_file", {"path": "new.py"}, call_id="call_2"),
            _text_response("done"),
        ]

        messages = [{"role": "user", "content": "read new.py"}]

        result = run_agent_loop(
            adapter=adapter,
            model_entry=_make_model_entry(),
            messages=messages,
            workdir=tmp_path,
            allowed_tools=["read_file"],
            config=LoopConfig(),
            existing_tool_exec=existing_exec,
        )

        # 原有 1 条 + 本轮新增 1 条 = 总共 2 条
        assert len(result.tool_history) == 2
        # 本轮新增只有 1 条
        assert len(result.new_tool_history) == 1


class TestCostLimit:
    def test_cost_limit_prevents_api_call(self, tmp_path):
        """成本已超限时，进入循环前即停止，不调用 API。"""
        from airouter.engine.agent.report import CostSummary

        existing_cost = CostSummary(total_cost_cny=1.0)  # 已消耗 1.0
        adapter = MagicMock()

        messages = [{"role": "user", "content": "read"}]

        result = run_agent_loop(
            adapter=adapter,
            model_entry=_make_model_entry(),
            messages=messages,
            workdir=tmp_path,
            allowed_tools=["read_file"],
            config=LoopConfig(max_cost_cny=0.5),  # 上限 0.5 < 已消耗 1.0
            existing_cost=existing_cost,
        )

        assert "成本上限" in result.final_response
        assert result.turns == 0
        adapter.chat.assert_not_called()

    def test_cost_limit_after_first_turn(self, tmp_path):
        """第一轮调用后成本超限，第二轮不再调用。"""
        from airouter.engine.agent.report import CostSummary

        adapter = MagicMock()
        # 第一轮返回 tool_call，第二轮如果调用也返回 tool_call（但不应被调用）
        adapter.chat.return_value = _tool_call_response(
            "read_file", {"path": "test.py"}, input_tokens=5000, output_tokens=2000,
        )

        existing_cost = CostSummary(total_cost_cny=0.0)

        messages = [{"role": "user", "content": "read"}]

        result = run_agent_loop(
            adapter=adapter,
            model_entry=_make_model_entry(),
            messages=messages,
            workdir=tmp_path,
            allowed_tools=["read_file"],
            config=LoopConfig(max_cost_cny=0.05),  # 一轮调用后会超过
            existing_cost=existing_cost,
        )

        assert "成本上限" in result.final_response
        # 只调了一次 API（第一轮），第二轮因 pre-loop 成本检查未调用
        assert adapter.chat.call_count == 1


class TestMaxTurns:
    def test_max_turns_stops(self, tmp_path):
        adapter = MagicMock()
        adapter.chat.return_value = _tool_call_response("read_file", {"path": "test.py"})

        messages = [{"role": "user", "content": "read"}]

        result = run_agent_loop(
            adapter=adapter,
            model_entry=_make_model_entry(),
            messages=messages,
            workdir=tmp_path,
            allowed_tools=["read_file"],
            config=LoopConfig(max_turns=2),
        )

        assert "最大轮次" in result.final_response
        assert result.turns == 2


class TestExistingCost:
    def test_existing_cost_accumulates(self, tmp_path):
        from airouter.engine.agent.report import CostSummary

        existing_cost = CostSummary(total_cost_cny=0.05)

        adapter = MagicMock()
        adapter.chat.return_value = _text_response("done")

        messages = [{"role": "user", "content": "hi"}]

        result = run_agent_loop(
            adapter=adapter,
            model_entry=_make_model_entry(),
            messages=messages,
            workdir=tmp_path,
            allowed_tools=None,
            config=LoopConfig(),
            existing_cost=existing_cost,
        )

        assert result.cost.total_cost_cny > 0.05
        assert result.cost_delta_cny > 0
        assert result.cost is existing_cost


class TestOnToolCallCallback:
    def test_callback_fires_per_tool(self, tmp_path):
        records = []

        adapter = MagicMock()
        adapter.chat.side_effect = [
            _tool_call_response("read_file", {"path": "test.py"}),
            _text_response("done"),
        ]

        messages = [{"role": "user", "content": "read"}]

        run_agent_loop(
            adapter=adapter,
            model_entry=_make_model_entry(),
            messages=messages,
            workdir=tmp_path,
            allowed_tools=["read_file"],
            config=LoopConfig(),
            on_tool_call=lambda r: records.append(r),
        )

        assert len(records) == 1
        assert records[0].name == "read_file"


class TestAllowedToolsFiltering:
    def test_tools_filtered(self, tmp_path):
        adapter = MagicMock()
        adapter.chat.return_value = _text_response("done")

        messages = [{"role": "user", "content": "hi"}]

        run_agent_loop(
            adapter=adapter,
            model_entry=_make_model_entry(),
            messages=messages,
            workdir=tmp_path,
            allowed_tools=["read_file"],
            config=LoopConfig(),
        )

        # 检查传给 adapter.chat 的 tools 参数
        call_kwargs = adapter.chat.call_args
        tools = call_kwargs.kwargs.get("tools") or call_kwargs[1].get("tools")
        tool_names = [t["function"]["name"] for t in tools]
        assert "read_file" in tool_names
        assert "write_file" not in tool_names
