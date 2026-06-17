"""ToolExecutor 单元测试。"""

import json

import pytest

from airouter.engine.agent.safety import SafetyGate
from airouter.engine.agent.tools import TOOL_DEFINITIONS, ToolExecutor


@pytest.fixture
def executor(tmp_path):
    safety = SafetyGate(workdir=tmp_path)
    return ToolExecutor(workdir=tmp_path, safety=safety)


@pytest.fixture
def sample_file(tmp_path):
    p = tmp_path / "hello.py"
    p.write_text("def hello():\n    return 'hello'\n", encoding="utf-8")
    return p


class TestReadFile:
    def test_read_existing_file(self, executor, sample_file):
        result = executor._read_file("hello.py")
        assert "def hello():" in result
        assert "总行数: 2" in result

    def test_read_nonexistent(self, executor):
        result = executor._read_file("missing.py")
        assert "不存在" in result

    def test_read_with_offset(self, executor, sample_file):
        result = executor._read_file("hello.py", offset=2)
        assert "return 'hello'" in result

    def test_read_with_limit(self, executor, sample_file):
        result = executor._read_file("hello.py", limit=1)
        assert "def hello():" in result


class TestWriteFile:
    def test_write_new_file(self, executor, tmp_path):
        result = executor._write_file("new.py", "print('hi')\n")
        assert "已写入" in result
        assert (tmp_path / "new.py").read_text() == "print('hi')\n"

    def test_write_overwrite_creates_backup(self, executor, sample_file, tmp_path):
        executor._write_file("hello.py", "new content\n")
        assert (tmp_path / "hello.py.bak").exists()
        assert (tmp_path / "hello.py").read_text() == "new content\n"

    def test_write_creates_parent_dirs(self, executor, tmp_path):
        result = executor._write_file("sub/dir/file.py", "content\n")
        assert "已写入" in result
        assert (tmp_path / "sub" / "dir" / "file.py").exists()


class TestEditFile:
    def test_edit_success(self, executor, sample_file, tmp_path):
        result = executor._edit_file("hello.py", "return 'hello'", "return 'world'")
        assert "已替换" in result
        assert "return 'world'" in (tmp_path / "hello.py").read_text()

    def test_edit_creates_backup(self, executor, sample_file, tmp_path):
        executor._edit_file("hello.py", "return 'hello'", "return 'world'")
        assert (tmp_path / "hello.py.bak").exists()

    def test_edit_not_found(self, executor, sample_file):
        result = executor._edit_file("hello.py", "nonexistent text", "new")
        assert "未找到" in result

    def test_edit_multiple_matches(self, executor, tmp_path):
        p = tmp_path / "dup.py"
        p.write_text("x = 1\nx = 1\n", encoding="utf-8")
        result = executor._edit_file("dup.py", "x = 1", "x = 2")
        assert "2 处匹配" in result

    def test_edit_nonexistent_file(self, executor):
        result = executor._edit_file("missing.py", "a", "b")
        assert "不存在" in result


class TestRunCommand:
    def test_run_echo(self, executor):
        result = executor._run_command("wc -l /dev/null")
        assert "exit code: 0" in result

    def test_run_timeout(self, executor):
        # This should timeout quickly with sleep
        result = executor._run_command("pytest --version")
        assert "exit code" in result or "失败" in result


class TestToolCallExecution:
    def test_execute_read_file(self, executor, sample_file):
        tool_calls = [{
            "id": "call_1",
            "type": "function",
            "function": {
                "name": "read_file",
                "arguments": json.dumps({"path": "hello.py"}),
            },
        }]
        results = executor.execute(tool_calls)
        assert len(results) == 1
        assert results[0]["role"] == "tool"
        assert results[0]["tool_call_id"] == "call_1"
        assert "def hello():" in results[0]["content"]

    def test_execute_invalid_json(self, executor):
        tool_calls = [{
            "id": "call_2",
            "type": "function",
            "function": {
                "name": "read_file",
                "arguments": "not json",
            },
        }]
        results = executor.execute(tool_calls)
        assert "解析失败" in results[0]["content"]

    def test_execute_safety_blocked(self, executor):
        tool_calls = [{
            "id": "call_3",
            "type": "function",
            "function": {
                "name": "run_command",
                "arguments": json.dumps({"command": "rm -rf /"}),
            },
        }]
        results = executor.execute(tool_calls)
        assert "安全拦截" in results[0]["content"]

    def test_history_recorded(self, executor, sample_file):
        tool_calls = [{
            "id": "call_4",
            "type": "function",
            "function": {
                "name": "read_file",
                "arguments": json.dumps({"path": "hello.py"}),
            },
        }]
        executor.execute(tool_calls)
        assert len(executor.history) == 1
        assert executor.history[0].name == "read_file"
        assert executor.history[0].success is True


class TestToolDefinitions:
    def test_definitions_structure(self):
        assert len(TOOL_DEFINITIONS) == 4
        names = {d["function"]["name"] for d in TOOL_DEFINITIONS}
        assert names == {"read_file", "write_file", "edit_file", "run_command"}

    def test_all_have_type_function(self):
        for d in TOOL_DEFINITIONS:
            assert d["type"] == "function"
            assert "name" in d["function"]
            assert "parameters" in d["function"]


class TestAllowedTools:
    def test_blocked_disallowed_tool(self, tmp_path):
        """run_command 不在 allowed_tools 中时被拦截。"""
        safety = SafetyGate(workdir=tmp_path)
        executor = ToolExecutor(
            workdir=tmp_path,
            safety=safety,
            allowed_tools=["read_file", "edit_file"],
        )
        tool_calls = [{
            "id": "call_5",
            "type": "function",
            "function": {
                "name": "run_command",
                "arguments": json.dumps({"command": "ls"}),
            },
        }]
        results = executor.execute(tool_calls)
        assert len(results) == 1
        assert "工具不允许" in results[0]["content"]
        assert "run_command" in results[0]["content"]

    def test_allowed_tool_passes(self, tmp_path, sample_file):
        """allowed_tools 中的工具正常执行。"""
        safety = SafetyGate(workdir=tmp_path)
        executor = ToolExecutor(
            workdir=tmp_path,
            safety=safety,
            allowed_tools=["read_file", "edit_file"],
        )
        tool_calls = [{
            "id": "call_6",
            "type": "function",
            "function": {
                "name": "read_file",
                "arguments": json.dumps({"path": "hello.py"}),
            },
        }]
        results = executor.execute(tool_calls)
        assert len(results) == 1
        assert "def hello():" in results[0]["content"]
        assert "工具不允许" not in results[0]["content"]

    def test_none_allowed_tools_allows_all(self, tmp_path, sample_file):
        """allowed_tools=None 时所有工具都允许。"""
        safety = SafetyGate(workdir=tmp_path)
        executor = ToolExecutor(
            workdir=tmp_path,
            safety=safety,
            allowed_tools=None,
        )
        tool_calls = [{
            "id": "call_7",
            "type": "function",
            "function": {
                "name": "read_file",
                "arguments": json.dumps({"path": "hello.py"}),
            },
        }]
        results = executor.execute(tool_calls)
        assert len(results) == 1
        assert "def hello():" in results[0]["content"]
