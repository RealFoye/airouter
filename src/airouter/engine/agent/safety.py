"""SafetyGate: 命令白名单 + 路径限制 + 危险模式检测。"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass, field
from pathlib import Path


class SafetyError(Exception):
    """安全校验失败。"""


@dataclass
class SafetyConfig:
    """安全门配置。"""

    allowed_command_prefixes: list[tuple[str, ...]] = field(
        default_factory=lambda: [
            ("pytest",),
            ("python", "-m", "pytest"),
            ("ruff", "check"),
            ("ruff", "format"),
            ("git", "status"),
            ("git", "log"),
            ("git", "diff"),
            ("ls",),
            ("wc",),
            ("head",),
            ("tail",),
        ]
    )
    forbidden_patterns: list[str] = field(
        default_factory=lambda: [
            r"rm\s+-rf",
            r"git\s+push\s+--force",
            r"DROP\s+TABLE",
            r"sudo\s+",
            r"chmod\s+777",
            r"curl.*\|.*sh",
            r">\s*/dev/sd",
            r"mkfs\.",
            r"dd\s+if=",
            r";.*rm\s",
            r"\|.*sh\b",
        ]
    )
    max_file_size_bytes: int = 5 * 1024 * 1024  # 5 MB


class SafetyGate:
    """工具调用的安全校验门。"""

    def __init__(self, workdir: Path, config: SafetyConfig | None = None):
        self.workdir = workdir.resolve()
        self.config = config or SafetyConfig()

    def check(self, tool_name: str, args: dict) -> None:
        """校验工具调用是否安全。不安全则抛 SafetyError。"""
        if tool_name in ("read_file", "write_file", "edit_file"):
            self._check_path(args.get("path", ""))
        elif tool_name == "run_command":
            self._check_command(args.get("command", ""))

    def _check_path(self, path: str) -> None:
        """路径必须在 workdir 范围内。"""
        if not path:
            raise SafetyError("文件路径不能为空")
        resolved = (self.workdir / path).resolve()
        if not resolved.is_relative_to(self.workdir):
            raise SafetyError(f"路径越界: {path} (resolved: {resolved})")

    def _check_command(self, command: str) -> None:
        """命令必须在白名单内，且不包含危险模式。"""
        if not command or not command.strip():
            raise SafetyError("命令不能为空")

        cmd = command.strip()

        # 第一道防线：危险模式
        for pattern in self.config.forbidden_patterns:
            if re.search(pattern, cmd, re.IGNORECASE):
                raise SafetyError(f"危险命令被拦截: {cmd}")

        # 解析参数
        try:
            args = shlex.split(cmd)
        except ValueError as e:
            raise SafetyError(f"命令解析失败: {e}")

        if not args:
            raise SafetyError("命令不能为空")

        # 前缀白名单
        if not self._matches_allowed_prefix(args):
            raise SafetyError(
                f"命令不在白名单中: {cmd}\n"
                f"允许的命令前缀: {self._format_prefixes()}"
            )

        # 路径参数检查（所有命令的路径参数都不能越界）
        self._check_command_path_args(args)

    def _matches_allowed_prefix(self, args: list[str]) -> bool:
        return any(
            tuple(args[: len(prefix)]) == prefix
            for prefix in self.config.allowed_command_prefixes
        )

    def _format_prefixes(self) -> str:
        return ", ".join(" ".join(p) for p in self.config.allowed_command_prefixes)

    def _check_command_path_args(self, args: list[str]) -> None:
        """检查所有路径参数不能越过 workdir。"""
        for arg in args:
            if arg.startswith("-"):
                continue  # 跳过 flags
            # 判断是否是路径参数（包含 / 或 .）
            if "/" in arg or "." in arg:
                if arg.startswith("/"):
                    raise SafetyError(f"绝对路径不允许: {arg}")
                # 解析路径
                resolved = (self.workdir / arg).resolve()
                if not resolved.is_relative_to(self.workdir):
                    raise SafetyError(f"路径越界: {arg}")
