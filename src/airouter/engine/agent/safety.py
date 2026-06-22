"""SafetyGate: 命令白名单 + 路径限制 + 危险模式检测。"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass, field
from pathlib import Path


class SafetyError(Exception):
    """安全校验失败。"""


class ApprovalRequired(SafetyError):
    """命令不在默认安全范围，但可由用户显式授权。"""

    def __init__(self, message: str, permission_key: str):
        super().__init__(message)
        self.permission_key = permission_key


class CommandRewriteRequired(SafetyError):
    """命令语法无法在无 shell 模式执行，模型应改写后重试。"""


@dataclass
class SafetyConfig:
    """安全门配置。"""

    allowed_command_prefixes: list[tuple[str, ...]] = field(
        default_factory=lambda: [
            ("pytest",),
            ("python", "-m", "pytest"),
            ("python", "-m", "unittest"),
            ("python", "-m", "compileall"),
            ("python3", "-m", "pytest"),
            ("python3", "-m", "unittest"),
            ("python3", "-m", "compileall"),
            ("ruff", "check"),
            ("ruff", "format"),
            ("node", "--check"),
            ("npm", "install"),
            ("npm", "ci"),
            ("npm", "init"),
            ("npm", "create"),
            ("npm", "test"),
            ("npm", "run", "test"),
            ("npm", "run", "build"),
            ("npm", "run", "lint"),
            ("npm", "run", "typecheck"),
            ("npm", "run", "check"),
            ("npx", "tsc"),
            ("npx", "eslint"),
            ("npx", "vite", "build"),
            ("pnpm", "install"),
            ("pnpm", "test"),
            ("pnpm", "run", "test"),
            ("pnpm", "run", "build"),
            ("pnpm", "run", "lint"),
            ("pnpm", "run", "typecheck"),
            ("yarn", "install"),
            ("yarn", "test"),
            ("yarn", "run", "test"),
            ("yarn", "run", "build"),
            ("yarn", "run", "lint"),
            ("yarn", "run", "typecheck"),
            ("git", "status"),
            ("git", "log"),
            ("git", "diff"),
            ("pwd",),
            ("ls",),
            ("find",),
            ("rg",),
            ("grep",),
            ("cat",),
            ("wc",),
            ("head",),
            ("tail",),
            ("mkdir",),
            ("touch",),
            ("cp",),
        ]
    )
    forbidden_patterns: list[str] = field(
        default_factory=lambda: [
            r"rm\s+-rf",
            r"(?:^|\s)(?:rm|rmdir|unlink|shred)(?:\s|$)",
            r"git\s+push\s+--force",
            r"git\s+(?:reset\s+--hard|clean)(?:\s|$)",
            r"DROP\s+TABLE",
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
        """命令必须安全；白名单外或组合命令要求用户授权。"""
        segments = self.parse_command_segments(command)

        approval_reasons = []
        if len(segments) > 1:
            approval_reasons.append("组合命令需要确认")
        if any(not self._matches_allowed_prefix(args) for args in segments):
            approval_reasons.append("命令不在默认白名单中")

        if approval_reasons:
            raise ApprovalRequired(
                f"{'；'.join(approval_reasons)}: {command.strip()}",
                permission_key=f"run_command:{command.strip()}",
            )

    def parse_command_segments(
        self,
        command: str,
        *,
        allow_external_paths: bool = False,
    ) -> list[list[str]]:
        """安全解析命令；仅支持用 ``&&`` 串联的独立命令。

        每个命令最终都通过 ``subprocess.run(..., shell=False)`` 执行。管道、
        重定向、分号等 shell 语法不进入授权流程，始终拒绝。
        """
        if not command or not command.strip():
            raise SafetyError("命令不能为空")

        cmd = command.strip()

        # 第一道防线：危险模式
        for pattern in self.config.forbidden_patterns:
            if re.search(pattern, cmd, re.IGNORECASE):
                raise SafetyError(f"危险命令被拦截: {cmd}")

        try:
            lexer = shlex.shlex(cmd, posix=True, punctuation_chars=";&|<>")
            lexer.whitespace_split = True
            tokens = list(lexer)
        except ValueError as e:
            raise SafetyError(f"命令解析失败: {e}") from e

        unsupported = {"||", ";", "|", ">", ">>", "<", "<<"}
        operator = next((token for token in tokens if token in unsupported), None)
        if operator:
            raise CommandRewriteRequired(
                f"当前执行器不使用 shell，暂不支持运算符 {operator}；"
                "请拆成多个独立命令或改用 read_file/edit_file"
            )

        segments: list[list[str]] = []
        current: list[str] = []
        for token in tokens:
            if token == "&&":
                if not current:
                    raise SafetyError(f"命令解析失败: {cmd}")
                segments.append(current)
                current = []
            else:
                current.append(token)
        if not current:
            raise SafetyError(f"命令解析失败: {cmd}")
        segments.append(current)

        for args in segments:
            self._check_command_path_args(
                args,
                allow_external_paths=allow_external_paths,
                command=cmd,
            )
        return segments

    def _matches_allowed_prefix(self, args: list[str]) -> bool:
        return any(
            tuple(args[: len(prefix)]) == prefix
            for prefix in self.config.allowed_command_prefixes
        )

    def _format_prefixes(self) -> str:
        return ", ".join(" ".join(p) for p in self.config.allowed_command_prefixes)

    def _check_command_path_args(
        self,
        args: list[str],
        *,
        allow_external_paths: bool,
        command: str,
    ) -> None:
        """检查所有路径参数不能越过 workdir。"""
        for arg in args:
            if arg.startswith("-"):
                continue  # 跳过 flags
            # 判断是否是路径参数（包含 / 或 .）
            if "/" in arg or "." in arg:
                if arg.startswith("/"):
                    resolved = Path(arg).resolve()
                    if (
                        not resolved.is_relative_to(self.workdir)
                        and not allow_external_paths
                    ):
                        raise ApprovalRequired(
                            f"命令将访问工作目录外的路径: {arg}",
                            permission_key=f"run_command:{command}",
                        )
                    continue
                # 解析路径
                resolved = (self.workdir / arg).resolve()
                if (
                    not resolved.is_relative_to(self.workdir)
                    and not allow_external_paths
                ):
                    raise ApprovalRequired(
                        f"命令将访问工作目录外的路径: {arg}",
                        permission_key=f"run_command:{command}",
                    )
