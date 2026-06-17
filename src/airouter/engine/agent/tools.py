"""工具定义 + ToolExecutor: 4 个工具覆盖代码修改场景。"""

from __future__ import annotations

import json
import logging
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from airouter.engine.agent.safety import SafetyError, SafetyGate

logger = logging.getLogger(__name__)

# ── OpenAI Function Calling 工具定义 ─────────────────────────

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "读取指定文件的内容。修改文件前必须先读取。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "文件相对路径"},
                    "offset": {
                        "type": "integer",
                        "description": "起始行号（可选，从 1 开始）",
                    },
                    "limit": {"type": "integer", "description": "读取行数（可选）"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "创建或覆盖写入文件。写入前会自动备份原文件。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "文件相对路径"},
                    "content": {"type": "string", "description": "文件完整内容"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": "精确替换文件中的某段文本。比 write_file 更安全，只改需要改的部分。修改前必须先 read_file。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "文件相对路径"},
                    "old_text": {"type": "string", "description": "要被替换的原始文本"},
                    "new_text": {"type": "string", "description": "替换后的新文本"},
                },
                "required": ["path", "old_text", "new_text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "在安全沙箱中执行命令。仅允许白名单命令：pytest, ruff, git status/log/diff, wc, head, tail。",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "要执行的命令"},
                },
                "required": ["command"],
            },
        },
    },
]


# ── 工具调用记录 ─────────────────────────────────────────────


@dataclass
class ToolCallRecord:
    """单次工具调用记录。"""

    name: str
    args: dict
    result: str
    success: bool = True
    error: str | None = None


# ── ToolExecutor ─────────────────────────────────────────────


class ToolExecutor:
    """执行工具调用并记录历史。"""

    def __init__(
        self,
        workdir: Path,
        safety: SafetyGate,
        allowed_tools: list[str] | None = None,
    ):
        self.workdir = workdir.resolve()
        self.safety = safety
        self.allowed_tools = allowed_tools
        self.history: list[ToolCallRecord] = []

    def execute(self, tool_calls: list[dict]) -> list[dict]:
        """执行一组 tool_calls，返回结果列表（OpenAI tool message 格式）。"""
        results = []
        for tc in tool_calls:
            fn = tc["function"]
            name = fn["name"]

            # 检查工具是否在允许列表中
            if self.allowed_tools is not None and name not in self.allowed_tools:
                result_text = (
                    f"工具不允许: {name}。允许的工具: {', '.join(self.allowed_tools)}"
                )
                self.history.append(
                    ToolCallRecord(name, {}, result_text, success=False)
                )
                results.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": result_text,
                })
                continue

            try:
                args = json.loads(fn["arguments"])
            except json.JSONDecodeError as e:
                args = {}
                result_text = f"错误: 参数 JSON 解析失败: {e}"
                self.history.append(
                    ToolCallRecord(name, args, result_text, success=False, error=str(e))
                )
                results.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": result_text,
                })
                continue

            # 安全校验
            try:
                self.safety.check(name, args)
            except SafetyError as e:
                result_text = f"安全拦截: {e}"
                self.history.append(
                    ToolCallRecord(name, args, result_text, success=False, error=str(e))
                )
                results.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": result_text,
                })
                continue

            # 执行
            try:
                result_text = self._dispatch(name, args)
                self.history.append(ToolCallRecord(name, args, result_text))
            except Exception as e:
                result_text = f"执行失败: {e}"
                self.history.append(
                    ToolCallRecord(name, args, result_text, success=False, error=str(e))
                )

            results.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": result_text,
            })

        return results

    def _dispatch(self, name: str, args: dict) -> str:
        if name == "read_file":
            return self._read_file(args["path"], args.get("offset"), args.get("limit"))
        elif name == "write_file":
            return self._write_file(args["path"], args["content"])
        elif name == "edit_file":
            return self._edit_file(args["path"], args["old_text"], args["new_text"])
        elif name == "run_command":
            return self._run_command(args["command"])
        else:
            return f"未知工具: {name}"

    def _read_file(self, path: str, offset: int | None = None, limit: int | None = None) -> str:
        full_path = (self.workdir / path).resolve()
        if not full_path.exists():
            return f"文件不存在: {path}"
        if not full_path.is_file():
            return f"不是文件: {path}"

        content = full_path.read_text(encoding="utf-8", errors="replace")
        lines = content.splitlines(keepends=True)

        start = (offset - 1) if offset and offset > 0 else 0
        end = (start + limit) if limit else len(lines)
        selected = lines[start:end]

        result = "".join(selected)
        total_lines = len(lines)
        header = f"[文件: {path}, 总行数: {total_lines}"
        if offset or limit:
            header += f", 显示: {start+1}-{min(end, total_lines)}"
        header += "]\n"
        return header + result

    def _write_file(self, path: str, content: str) -> str:
        full_path = (self.workdir / path).resolve()

        # 备份原文件
        if full_path.exists():
            backup = full_path.with_suffix(full_path.suffix + ".bak")
            shutil.copy2(full_path, backup)

        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content, encoding="utf-8")

        lines = content.count("\n") + (1 if content and not content.endswith("\n") else 0)
        return f"已写入: {path} ({lines} 行)"

    def _edit_file(self, path: str, old_text: str, new_text: str) -> str:
        full_path = (self.workdir / path).resolve()
        if not full_path.exists():
            return f"文件不存在: {path}"

        content = full_path.read_text(encoding="utf-8")
        count = content.count(old_text)

        if count == 0:
            return f"未找到匹配的文本，无法替换: {path}\n请确认 old_text 与文件内容完全一致。"
        if count > 1:
            return f"找到 {count} 处匹配，无法确定替换哪一处: {path}\n请提供更多上下文使 old_text 唯一。"

        # 备份
        backup = full_path.with_suffix(full_path.suffix + ".bak")
        shutil.copy2(full_path, backup)

        new_content = content.replace(old_text, new_text, 1)
        full_path.write_text(new_content, encoding="utf-8")

        return f"已替换: {path} (1 处)"

    def _run_command(self, command: str) -> str:
        try:
            args = shlex.split(command)
            result = subprocess.run(
                args,
                shell=False,
                capture_output=True,
                text=True,
                timeout=60,
                cwd=str(self.workdir),
            )
            output = ""
            if result.stdout:
                output += result.stdout
            if result.stderr:
                output += f"\n[stderr]\n{result.stderr}"
            output += f"\n[exit code: {result.returncode}]"

            # 截断过长输出
            max_chars = 8000
            if len(output) > max_chars:
                output = output[:max_chars] + f"\n... (输出被截断，共 {len(output)} 字符)"

            return output.strip()
        except subprocess.TimeoutExpired:
            return "命令执行超时 (60s)"
        except Exception as e:
            return f"命令执行失败: {e}"
