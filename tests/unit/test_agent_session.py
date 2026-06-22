"""AgentSession 单元测试。"""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from airouter.adapters.base import AdapterAuthError, AdapterResponse
from airouter.engine.agent.report import CostSummary


def _text_response(content="done"):
    return AdapterResponse(
        content=content,
        input_tokens=100,
        output_tokens=50,
        latency_ms=100,
        model="test-model",
    )


def _make_session(tmp_path, **kwargs):
    """Create an AgentSession with mocked dependencies and isolated session root."""
    session_root = tmp_path / "sessions"
    with patch("airouter.engine.agent.session.load_all"), \
         patch("airouter.engine.agent.session.AppSettings"), \
         patch("airouter.engine.agent.session.ModelRegistry") as mock_registry, \
         patch("airouter.engine.agent.session.AdapterFactory"), \
         patch("airouter.engine.agent.session.ComplexityAnalyzer"), \
         patch("airouter.engine.agent.session.TaskAnalyzer"), \
         patch("airouter.engine.agent.session.Router") as mock_router, \
         patch("airouter.engine.agent.session.SESSION_ROOT", session_root):

        mock_registry_inst = MagicMock()
        flash_model = SimpleNamespace(
            name="deepseek-v4-flash",
            tier=3,
            provider="deepseek",
            input_price_per_1k=0.01,
            output_price_per_1k=0.02,
        )
        pro_model = SimpleNamespace(
            name="deepseek-v4-pro",
            tier=1,
            provider="deepseek",
            input_price_per_1k=0.02,
            output_price_per_1k=0.04,
        )
        mock_registry_inst.all_models = [pro_model, flash_model]
        mock_registry_inst.get_by_name.return_value = flash_model
        mock_registry.return_value = mock_registry_inst

        mock_router_inst = MagicMock()
        mock_router.return_value = mock_router_inst

        from airouter.engine.agent.session import AgentSession

        session = AgentSession(
            workdir=tmp_path,
            **kwargs,
        )

    return session


class TestSessionInit:
    def test_session_id_has_microseconds(self, tmp_path):
        session = _make_session(tmp_path)
        # session ID should have microsecond precision: YYYYMMDD_HHMMSS_ffffff
        assert len(session.session_id) > 15  # more than YYYYMMDD_HHMMSS

    def test_session_dir_created_on_save(self, tmp_path):
        session = _make_session(tmp_path)
        # dir not created in __init__
        assert not session.session_dir.exists()
        session.save()
        assert session.session_dir.exists()


class TestSlashCommands:
    def test_help_no_crash(self, tmp_path):
        session = _make_session(tmp_path)
        session.handle_slash("/help")

    def test_cost_no_crash(self, tmp_path):
        session = _make_session(tmp_path)
        session.handle_slash("/cost")

    def test_files_empty(self, tmp_path):
        session = _make_session(tmp_path)
        session.handle_slash("/files")

    def test_summary_empty(self, tmp_path):
        session = _make_session(tmp_path)
        session.handle_slash("/summary")

    def test_model_show(self, tmp_path):
        session = _make_session(tmp_path)
        session.handle_slash("/model")

    def test_model_menu_selects_by_number(self, tmp_path):
        session = _make_session(tmp_path)
        with patch("airouter.engine.agent.session.console") as mock_console, \
             patch("airouter.engine.agent.session.Prompt.ask", return_value="2"):
            mock_console.is_terminal = True
            session.handle_slash("/model")
        assert session.model_override == "deepseek-v4-flash"

    def test_model_auto_clears_override(self, tmp_path):
        session = _make_session(tmp_path, model_override="deepseek-v4-pro")
        session.handle_slash("/model auto")
        assert session.model_override is None

    def test_model_name_still_switches_directly(self, tmp_path):
        session = _make_session(tmp_path)
        session.handle_slash("/model deepseek-v4-flash")
        assert session.model_override == "deepseek-v4-flash"

    def test_unknown_command(self, tmp_path):
        session = _make_session(tmp_path)
        session.handle_slash("/foobar")

    def test_exit_returns_true(self, tmp_path):
        session = _make_session(tmp_path)
        assert session.handle_slash("/exit") is True


class TestPersistence:
    def test_save_and_restore(self, tmp_path):
        session_root = tmp_path / "sessions"
        session = _make_session(tmp_path)
        with patch("airouter.engine.agent.session.SESSION_ROOT", session_root):
            session.history_messages = [
                {"role": "user", "content": "hello"},
                {"role": "assistant", "content": "hi back"},
            ]
            session.cost = CostSummary(total_cost_cny=0.05, total_input_tokens=1000)
            session.touched_files = {"a.py", "b.py"}
            session.turn_count = 2
            session.last_turn_summary = "did something"
            session.save()

            # Restore
            session2 = _make_session(tmp_path)
            result = session2.restore(session.session_id)

        assert result is True
        assert len(session2.history_messages) == 2
        assert session2.cost.total_cost_cny == 0.05
        assert session2.touched_files == {"a.py", "b.py"}
        assert session2.turn_count == 2
        assert session2.last_turn_summary == "did something"

    def test_restore_latest(self, tmp_path):
        session_root = tmp_path / "sessions"
        with patch("airouter.engine.agent.session.SESSION_ROOT", session_root):
            session = _make_session(tmp_path)
            session.history_messages = [{"role": "user", "content": "test"}]
            session.save()

            session2 = _make_session(tmp_path)
            result = session2.restore("latest")
        assert result is True
        assert len(session2.history_messages) == 1

    def test_restore_nonexistent_fails(self, tmp_path):
        session_root = tmp_path / "sessions"
        with patch("airouter.engine.agent.session.SESSION_ROOT", session_root):
            session = _make_session(tmp_path)
            result = session.restore("nonexistent")
        assert result is False

    def test_restore_latest_no_sessions_fails(self, tmp_path):
        session_root = tmp_path / "sessions"
        with patch("airouter.engine.agent.session.SESSION_ROOT", session_root):
            session = _make_session(tmp_path)
            result = session.restore("latest")
        assert result is False

    def test_restore_corrupt_session_fails_without_mutating_state(self, tmp_path):
        session_root = tmp_path / "sessions"
        corrupt_dir = session_root / "corrupt"
        corrupt_dir.mkdir(parents=True)
        (corrupt_dir / "session.json").write_text("{not-json", encoding="utf-8")

        with patch("airouter.engine.agent.session.SESSION_ROOT", session_root):
            session = _make_session(tmp_path)
            original_id = session.session_id
            result = session.restore("corrupt")

        assert result is False
        assert session.session_id == original_id

    def test_restore_latest_skips_corrupt_newer_session(self, tmp_path):
        session_root = tmp_path / "sessions"
        with patch("airouter.engine.agent.session.SESSION_ROOT", session_root):
            valid = _make_session(tmp_path)
            valid.session_id = "20260618_100000_000001"
            valid.session_dir = session_root / valid.session_id
            valid.history_messages = [{"role": "user", "content": "valid"}]
            valid.save()

            corrupt_dir = session_root / "99999999_999999_999999"
            corrupt_dir.mkdir(parents=True)
            (corrupt_dir / "session.json").write_text("{not-json", encoding="utf-8")

            restored = _make_session(tmp_path)
            result = restored.restore("latest")

        assert result is True
        assert restored.session_id == valid.session_id
        assert restored.history_messages[0]["content"] == "valid"

    def test_events_appended(self, tmp_path):
        session = _make_session(tmp_path)
        session._ensure_session_dir()
        session._append_event({"turn": 1, "user_input": "hello"})
        session._append_event({"turn": 2, "user_input": "world"})

        events_file = session.session_dir / "events.jsonl"
        lines = events_file.read_text().strip().splitlines()
        assert len(lines) == 2
        assert json.loads(lines[0])["turn"] == 1

    def test_tools_appended(self, tmp_path):
        from airouter.engine.agent.tools import ToolCallRecord

        session = _make_session(tmp_path)
        session._ensure_session_dir()
        records = [
            ToolCallRecord(name="read_file", args={"path": "a.py"}, result="content", success=True),
            ToolCallRecord(name="edit_file", args={"path": "a.py"}, result="ok", success=True),
        ]
        session._append_tool_records(records)

        tools_file = session.session_dir / "tools.jsonl"
        lines = tools_file.read_text().strip().splitlines()
        assert len(lines) == 2

    def test_touched_files_persisted(self, tmp_path):
        session = _make_session(tmp_path)
        session._ensure_session_dir()
        session.touched_files = {"x.py"}
        session._save_touched_files()

        data = json.loads((session.session_dir / "touched_files.json").read_text())
        assert "x.py" in data["files"]


class TestComplexityContext:
    def test_context_keeps_current_task_separate_from_history(self, tmp_path):
        session = _make_session(tmp_path)
        session.history_messages = [
            {"role": "user", "content": "创建完整聊天网页"},
            {"role": "assistant", "content": "页面已创建"},
        ]
        session.route_decisions = ["R0"]
        session.turn_count = 1

        context = session._build_complexity_context("只改名字")

        assert context.history_user_texts == ("创建完整聊天网页",)
        assert context.prev_assistant_text == "页面已创建"
        assert context.prev_route_decisions == ("R0",)
        assert context.turn_index == 1
        assert "只改名字" not in context.history_user_texts


class TestCompression:
    def test_project_history_removes_provider_specific_tool_messages(self, tmp_path):
        session = _make_session(tmp_path)
        history = [
            {"role": "user", "content": "创建页面"},
            {
                "role": "assistant",
                "content": "我先写文件",
                "tool_calls": [
                    {
                        "id": "broken-call",
                        "type": "function",
                        "function": {
                            "name": "write_file",
                            "arguments": '{"path":"index.html","content":"unterminated',
                        },
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "broken-call",
                "content": "参数 JSON 解析失败",
            },
            {"role": "assistant", "content": "页面已创建"},
        ]

        result = session._project_conversation_history(history)

        assert result == [
            {"role": "user", "content": "创建页面"},
            {"role": "assistant", "content": "页面已创建"},
        ]

    def test_get_history_sanitizes_restored_legacy_tool_trace(self, tmp_path):
        session = _make_session(tmp_path)
        session.history_messages = [
            {"role": "user", "content": "第一轮"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call-1",
                        "type": "function",
                        "function": {"name": "read_file", "arguments": "{bad-json"},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "call-1", "content": "error"},
            {"role": "assistant", "content": "第一轮完成"},
        ]

        result = session._get_history_messages()

        assert result == [
            {"role": "user", "content": "第一轮"},
            {"role": "assistant", "content": "第一轮完成"},
        ]
        assert session.history_messages == result

    def test_project_history_appends_synthesized_final_response(self, tmp_path):
        session = _make_session(tmp_path)
        history = [
            {"role": "user", "content": "执行任务"},
            {
                "role": "assistant",
                "content": "准备继续",
                "tool_calls": [
                    {
                        "id": "call-1",
                        "type": "function",
                        "function": {"name": "read_file", "arguments": "{}"},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "call-1", "content": "done"},
        ]

        result = session._project_conversation_history(
            history,
            final_response="[最大轮次] 已停止执行。",
        )

        assert result[-1] == {
            "role": "assistant",
            "content": "[最大轮次] 已停止执行。",
        }

    def test_cheapest_adapter_skips_provider_without_key(self, tmp_path):
        session = _make_session(tmp_path)
        cheap = MagicMock(input_price_per_1k=0.001, output_price_per_1k=0.002)
        available = MagicMock(input_price_per_1k=0.003, output_price_per_1k=0.004)
        expected_adapter = MagicMock()
        session.registry.all_models = [available, cheap]
        session.factory.get_adapter.side_effect = [
            AdapterAuthError("missing key"),
            expected_adapter,
        ]

        adapter, model = session._get_cheapest_adapter()

        assert adapter is expected_adapter
        assert model is available

    def test_split_into_blocks(self, tmp_path):
        session = _make_session(tmp_path)
        history = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
            {"role": "user", "content": "task 2"},
            {"role": "assistant", "content": "done"},
        ]
        blocks = session._split_into_blocks(history)
        assert len(blocks) == 2

    def test_split_with_tool_messages(self, tmp_path):
        session = _make_session(tmp_path)
        history = [
            {"role": "user", "content": "read file"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "read_file", "arguments": "{}"}}],
            },
            {"role": "tool", "tool_call_id": "c1", "content": "file content"},
            {"role": "assistant", "content": "here is the file"},
        ]
        blocks = session._split_into_blocks(history)
        assert len(blocks) == 1
        assert len(blocks[0]["messages"]) == 4

    def test_remove_orphan_tool_messages(self, tmp_path):
        session = _make_session(tmp_path)
        messages = [
            {"role": "assistant", "content": "hi"},
            {"role": "tool", "tool_call_id": "orphan_1", "content": "orphan result"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "read_file", "arguments": "{}"}}],
            },
            {"role": "tool", "tool_call_id": "c1", "content": "valid result"},
        ]
        result = session._remove_orphan_tool_messages(messages)
        # orphan tool message removed, valid pair kept
        assert len(result) == 3
        tool_msgs = [m for m in result if m["role"] == "tool"]
        assert len(tool_msgs) == 1
        assert tool_msgs[0]["tool_call_id"] == "c1"

    def test_estimate_tokens(self, tmp_path):
        session = _make_session(tmp_path)
        messages = [
            {"role": "user", "content": "hello world"},
            {"role": "assistant", "content": "hi there"},
        ]
        tokens = session._estimate_tokens(messages)
        assert tokens > 0

    def test_compact_short_history_noop(self, tmp_path):
        session = _make_session(tmp_path)
        session.history_messages = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ]
        session._cmd_compact()
        # 不足 6 条，不压缩
        assert len(session.history_messages) == 2


class TestModelOverride:
    def test_model_override_stored(self, tmp_path):
        session = _make_session(tmp_path, model_override="deepseek-v4-pro")
        assert session.model_override == "deepseek-v4-pro"

    def test_apply_model_override(self, tmp_path):
        session = _make_session(tmp_path, model_override="deepseek-v4-pro")

        from airouter.models.enums import (
            BudgetStatus,
            ComplexityLevel,
            RiskLevel,
            StrategyType,
            TaskCategory,
        )
        from airouter.models.schemas import ModelAssignment, RoutingDecision, TaskFeatures

        session.registry.get_by_name.return_value = session.registry.all_models[0]
        decision = RoutingDecision(
            task_hash="test",
            task_features=TaskFeatures(
                category=TaskCategory.CODE_GENERATION,
                complexity=ComplexityLevel.SIMPLE,
                risk_level=RiskLevel.LOW,
                estimated_input_tokens=1000,
                estimated_output_tokens=1000,
            ),
            recommended_strategy=StrategyType.SINGLE_MODEL,
            models=ModelAssignment(executor="deepseek-v4-flash"),
            estimated_cost=0.01,
            baseline_cost=0.06,
            estimated_savings=0.8333,
            estimated_quality=0.8,
            quality_loss_vs_baseline=0.1,
            risk_level=RiskLevel.LOW,
            requires_human_review=False,
            reasons=[],
            alternatives=[],
            budget_status=BudgetStatus.OK,
            quality_gate=[],
            fallback_policy=[],
            config_version="test",
        )

        result = session._apply_model_override(decision)
        assert result.models.executor == "deepseek-v4-pro"
        assert result.estimated_cost == 0.06
        assert result.estimated_savings == 0.0
        assert result.reasons[-1].startswith("用户手动选择 deepseek-v4-pro")

    def test_override_does_not_mutate_router_decision(self, tmp_path):
        session = _make_session(tmp_path, model_override="deepseek-v4-pro")

        from airouter.models.enums import (
            BudgetStatus,
            ComplexityLevel,
            RiskLevel,
            StrategyType,
            TaskCategory,
        )
        from airouter.models.schemas import ModelAssignment, RoutingDecision, TaskFeatures

        session.registry.get_by_name.return_value = session.registry.all_models[0]
        decision = RoutingDecision(
            task_hash="test",
            task_features=TaskFeatures(
                category=TaskCategory.CODE_GENERATION,
                complexity=ComplexityLevel.SIMPLE,
                risk_level=RiskLevel.LOW,
                estimated_input_tokens=1000,
                estimated_output_tokens=1000,
            ),
            recommended_strategy=StrategyType.SINGLE_MODEL,
            models=ModelAssignment(executor="deepseek-v4-flash"),
            estimated_cost=0.01,
            baseline_cost=0.06,
            estimated_savings=0.8333,
            estimated_quality=0.8,
            quality_loss_vs_baseline=0.1,
            risk_level=RiskLevel.LOW,
            requires_human_review=False,
            reasons=[],
            alternatives=[],
            budget_status=BudgetStatus.OK,
            quality_gate=[],
            fallback_policy=[],
            config_version="test",
        )

        session._apply_model_override(decision)

        assert decision.models.executor == "deepseek-v4-flash"
        assert decision.estimated_cost == 0.01
        assert decision.estimated_savings == 0.8333

    def test_no_override_returns_original(self, tmp_path):
        session = _make_session(tmp_path)

        decision = MagicMock()
        result = session._apply_model_override(decision)
        assert result is decision


class TestModelConfirmation:
    def test_confirms_every_turn_even_after_resume(self, tmp_path):
        session = _make_session(tmp_path)
        session.turn_count = 5

        with patch(
            "airouter.engine.agent.session.Confirm.ask",
            return_value=True,
        ) as confirm:
            accepted = session._confirm_execution_model("deepseek-v4-flash")

        assert accepted is True
        confirm.assert_called_once_with(
            "使用Router 推荐模型 deepseek-v4-flash 执行？",
            default=True,
        )

    def test_manual_override_is_explicit_in_confirmation(self, tmp_path):
        session = _make_session(tmp_path, model_override="qwen3.7-max")

        with patch(
            "airouter.engine.agent.session.Confirm.ask",
            return_value=False,
        ) as confirm:
            accepted = session._confirm_execution_model("qwen3.7-max")

        assert accepted is False
        confirm.assert_called_once_with(
            "使用手动固定模型 qwen3.7-max 执行？",
            default=True,
        )

    def test_yes_flag_skips_model_confirmation(self, tmp_path):
        session = _make_session(tmp_path, skip_approval=True)

        with patch("airouter.engine.agent.session.Confirm.ask") as confirm:
            assert session._confirm_execution_model("deepseek-v4-flash") is True

        confirm.assert_not_called()
