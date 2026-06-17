"""安全沙箱：容器级隔离执行 harness_validation 命令。

绝不执行模型输出的 validation.commands。
只执行 case 中预定义的 harness_validation.commands。

安全特性：
- 命令验证：shlex.split + shell metacharacter rejection + argv prefix match
- 容器执行：逐条执行（无 sh -c）、--user nobody、--cap-drop ALL、--no-new-privileges
- 路径校验：拒绝绝对路径、路径穿越、home directory 引用
- expected_exit_code 校验
"""

from __future__ import annotations

import logging
import shlex
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

# 旧接口保留（向后兼容），新代码应使用 _validate_command()
ALLOWED_COMMANDS: frozenset[str] = frozenset({
    "python -m pytest",
    "python -I",
})

# 新接口：精确 argv 前缀匹配
ALLOWED_COMMANDS_ARGV: list[list[str]] = [
    ["python", "-m", "pytest"],
    ["python", "-I"],
]

# Shell 元字符（任何命令包含这些字符直接拒绝）
SHELL_METACHARACTERS = frozenset(";&|><`$(){}[]!#\n\r")

SANDBOX_DISABLED_REASON = "no_container_runtime"

# 沙箱 image（固定版本，禁止 :latest）
SANDBOX_IMAGE = "airouter-benchmark:v1.0"


@dataclass(frozen=True)
class SandboxResult:
    """沙箱执行结果。

    passed = post_patch_exit_code == 0 AND NOT pre_patch_vacuous AND NOT test_files_modified.
    """

    exit_code: int = -1
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    sandbox_execution_unavailable: bool = False
    sandbox_type: str = "none"
    error_message: str = ""
    expected_exit_code: int = 0
    # ── Pre/Post patch validation ──
    pre_patch_exit_code: int | None = None
    post_patch_exit_code: int | None = None
    pre_patch_vacuous: bool = False
    test_files_modified: tuple[str, ...] = ()

    @property
    def passed(self) -> bool:
        if self.sandbox_execution_unavailable:
            return False
        # 三条件缺一不可
        post_ok = (
            self.post_patch_exit_code == self.expected_exit_code
            if self.post_patch_exit_code is not None
            else self.exit_code == self.expected_exit_code
        )
        return post_ok and not self.pre_patch_vacuous and not self.test_files_modified


def run_harness_validation(
    workspace_files: dict[str, str],
    patch: str,
    harness_commands: list[str],
    expected_exit_code: int = 0,
    timeout_s: int = 10,
    test_files: list[dict] | None = None,
) -> SandboxResult:
    """在隔离沙箱中执行 harness 验证命令。

    优先使用 Docker/Podman 容器执行：
    - --network none（无网络）
    - --memory 512m --cpus 1 --pids-limit 64
    - --user nobody:nogroup --cap-drop ALL --no-new-privileges
    - 只挂载临时 workspace（read-only）
    - 清空环境变量

    无容器运行时降级：
    - 禁止在宿主机执行不可信 patch
    - 只做静态验证（patch 格式、文件引用、路径校验）
    - sandbox_execution_unavailable = True
    """
    if not harness_commands:
        return SandboxResult(
            exit_code=0,
            sandbox_type="none",
            error_message="no commands to execute",
            expected_exit_code=expected_exit_code,
        )

    # 验证所有命令
    for cmd in harness_commands:
        valid, error = _validate_command(cmd)
        if not valid:
            return SandboxResult(
                exit_code=-1,
                sandbox_type="none",
                error_message=error,
                expected_exit_code=expected_exit_code,
            )

    # 路径校验（workspace 文件 + patch 文件）
    path_errors = _validate_workspace_paths(workspace_files, patch)
    if path_errors:
        return SandboxResult(
            exit_code=-1,
            sandbox_type="none",
            error_message="; ".join(path_errors),
            expected_exit_code=expected_exit_code,
        )

    # 检测容器运行时
    container_runtime = _detect_container_runtime()
    if container_runtime is None:
        # 降级：不执行，只做静态检查
        return _static_validation(
            workspace_files, patch, harness_commands, expected_exit_code,
        )

    # 容器执行
    return _container_execution(
        container_runtime, workspace_files, patch,
        harness_commands, expected_exit_code, timeout_s,
        test_files=test_files,
    )


def _validate_command(cmd: str) -> tuple[bool, str]:
    """验证命令是否安全。返回 (is_valid, error_message)。

    1. 拒绝 shell 元字符
    2. shlex.split 分词
    3. argv 前缀匹配（精确 token 对比）
    """
    # 1. 拒绝 shell 元字符
    for ch in cmd:
        if ch in SHELL_METACHARACTERS:
            return False, f"shell metacharacter rejected: {ch!r}"

    # 2. shlex.split 分词
    try:
        tokens = shlex.split(cmd)
    except ValueError as e:
        return False, f"invalid command syntax: {e}"

    if not tokens:
        return False, "empty command"

    # 3. argv 前缀匹配
    for allowed_argv in ALLOWED_COMMANDS_ARGV:
        if tokens[:len(allowed_argv)] == allowed_argv:
            return True, ""

    return False, f"command not in allowlist: {cmd}"


def _is_allowed_command(cmd: str) -> bool:
    """向后兼容接口。新代码应使用 _validate_command()。"""
    valid, _ = _validate_command(cmd)
    return valid


def _validate_workspace_paths(workspace_files: dict, patch: str) -> list[str]:
    """校验 workspace 文件和 patch 引用的路径。

    拒绝：绝对路径、路径穿越、home directory 引用。
    """
    errors = []
    all_files = list(workspace_files) + _extract_patch_files(patch)
    for filename in all_files:
        # 拒绝绝对路径
        if filename.startswith("/") or filename.startswith("\\"):
            errors.append(f"absolute path rejected: {filename}")
        # 拒绝路径穿越
        parts = Path(filename).parts
        if ".." in parts:
            errors.append(f"path traversal rejected: {filename}")
        # 拒绝 home directory 引用
        if filename.startswith("~"):
            errors.append(f"home directory reference rejected: {filename}")
    return errors


def _detect_container_runtime() -> str | None:
    """检测可用的容器运行时（Docker 或 Podman）。"""
    for runtime in ("docker", "podman"):
        if shutil.which(runtime):
            try:
                result = subprocess.run(
                    [runtime, "info"],
                    capture_output=True, timeout=5,
                )
                if result.returncode == 0:
                    return runtime
            except (subprocess.TimeoutExpired, OSError):
                continue
    return None


def _static_validation(
    workspace_files: dict[str, str],
    patch: str,
    harness_commands: list[str],
    expected_exit_code: int = 0,
) -> SandboxResult:
    """无容器时的降级验证：只做静态检查。"""
    errors = []

    # 检查 patch 中引用的文件是否存在于 workspace
    if patch:
        for filename in _extract_patch_files(patch):
            if filename not in workspace_files:
                errors.append(f"patch references file not in workspace: {filename}")

    # 路径穿越检查（已由 _validate_workspace_paths 统一处理）

    if errors:
        return SandboxResult(
            exit_code=-1,
            sandbox_execution_unavailable=True,
            sandbox_type="static_only",
            error_message="; ".join(errors),
            expected_exit_code=expected_exit_code,
        )

    return SandboxResult(
        exit_code=0,
        stdout="static validation passed (no container execution)",
        sandbox_execution_unavailable=True,
        sandbox_type="static_only",
        expected_exit_code=expected_exit_code,
    )


def _container_execution(
    runtime: str,
    workspace_files: dict[str, str],
    patch: str,
    harness_commands: list[str],
    expected_exit_code: int,
    timeout_s: int,
    test_files: list[dict] | None = None,
) -> SandboxResult:
    """在容器内执行验证命令。逐条执行，不使用 shell。

    四步流程：
    1. Pre-patch: 在原始 workspace 上运行 harness commands（验证 baseline）
    2. 注入测试文件 + 记录 checksum
    3. 应用 patch + 验证测试文件未被篡改
    4. Post-patch: 在 patched workspace 上运行 harness commands
    """
    tmpdir = Path(tempfile.mkdtemp(prefix="airouter_sandbox_"))
    try:
        workspace = tmpdir / "workspace"
        workspace.mkdir()

        # 写入 workspace 文件
        for filename, content in workspace_files.items():
            file_path = workspace / filename
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding="utf-8")

        # 注入测试文件（如果有）
        test_checksums: dict[str, str] = {}
        if test_files:
            for tf in test_files:
                test_path = workspace / tf["filename"]
                test_path.parent.mkdir(parents=True, exist_ok=True)
                test_path.write_text(tf["content"], encoding="utf-8")
                test_path.chmod(0o444)  # 只读
                # 记录 checksum
                import hashlib
                test_checksums[tf["filename"]] = hashlib.sha256(
                    tf["content"].encode("utf-8")
                ).hexdigest()

        # 构建容器基础参数
        base_args = [
            runtime, "run", "--rm",
            "--network", "none",
            "--memory", "512m",
            "--cpus", "1",
            "--pids-limit", "64",
            "--user", "nobody:nogroup",
            "--read-only",
            "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges",
            "--tmpfs", "/tmp:noexec,nosuid,size=64m",
            "-v", f"{workspace}:/workspace:ro",
            "-w", "/workspace",
            "--env", "PATH=/usr/local/bin:/usr/bin:/bin",
            SANDBOX_IMAGE,
        ]

        def _run_commands(commands: list[str]) -> tuple[int, str, str]:
            """在容器中逐条执行命令，返回 (last_exit_code, stdout, stderr)。"""
            combined_stdout = ""
            combined_stderr = ""
            for cmd_str in commands:
                tokens = shlex.split(cmd_str)
                exec_cmd = base_args + tokens
                result = subprocess.run(
                    exec_cmd, capture_output=True, text=True,
                    timeout=timeout_s + 5,
                )
                combined_stdout += result.stdout or ""
                combined_stderr += result.stderr or ""
                if result.returncode != expected_exit_code:
                    return result.returncode, combined_stdout, combined_stderr
            return expected_exit_code, combined_stdout, combined_stderr

        # Step 1: Pre-patch 运行（验证 baseline）
        pre_patch_exit_code = None
        pre_patch_vacuous = False
        if test_files and harness_commands:
            pre_exit, _, _ = _run_commands(harness_commands)
            pre_patch_exit_code = pre_exit
            # 所有命令通过 → vacuous（baseline 无效：测试在未 patch 时已通过）
            pre_patch_vacuous = (pre_exit == expected_exit_code)

        # Step 2: 应用 patch
        if patch:
            # 确保测试文件可写（patch 可能修改同目录）
            if test_files:
                for tf in test_files:
                    test_path = workspace / tf["filename"]
                    if test_path.exists():
                        test_path.chmod(0o644)

            patch_file = tmpdir / "patch.diff"
            patch_file.write_text(patch, encoding="utf-8")
            patch_result = subprocess.run(
                ["patch", "-p1", "-d", str(workspace), "-i", str(patch_file)],
                capture_output=True, text=True, timeout=5,
            )
            if patch_result.returncode != 0:
                return SandboxResult(
                    exit_code=-1,
                    stdout=patch_result.stdout,
                    stderr=patch_result.stderr,
                    sandbox_type="container",
                    error_message="patch application failed",
                    expected_exit_code=expected_exit_code,
                    pre_patch_exit_code=pre_patch_exit_code,
                    pre_patch_vacuous=pre_patch_vacuous,
                )

            # 恢复测试文件只读
            if test_files:
                for tf in test_files:
                    test_path = workspace / tf["filename"]
                    if test_path.exists():
                        test_path.chmod(0o444)

        # Step 3: 验证测试文件未被篡改
        modified_tests: tuple[str, ...] = ()
        if test_checksums:
            import hashlib
            tampered = []
            for tf_name, expected_hash in test_checksums.items():
                test_path = workspace / tf_name
                if test_path.exists():
                    actual_hash = hashlib.sha256(
                        test_path.read_bytes()
                    ).hexdigest()
                    if actual_hash != expected_hash:
                        tampered.append(tf_name)
            modified_tests = tuple(tampered)

        # Step 4: Post-patch 运行
        post_exit, combined_stdout, combined_stderr = _run_commands(harness_commands)

        return SandboxResult(
            exit_code=post_exit,
            stdout=combined_stdout[-4000:],
            stderr=combined_stderr[-4000:],
            timed_out=False,
            sandbox_type="container",
            expected_exit_code=expected_exit_code,
            pre_patch_exit_code=pre_patch_exit_code,
            post_patch_exit_code=post_exit,
            pre_patch_vacuous=pre_patch_vacuous,
            test_files_modified=modified_tests,
            error_message="" if post_exit == expected_exit_code else (
                f"command exited {post_exit}, expected {expected_exit_code}"
            ),
        )

    except subprocess.TimeoutExpired:
        return SandboxResult(
            exit_code=-1,
            timed_out=True,
            sandbox_type="container",
            error_message=f"execution timed out after {timeout_s}s",
            expected_exit_code=expected_exit_code,
        )
    except Exception as exc:
        return SandboxResult(
            exit_code=-1,
            sandbox_type="container",
            error_message=str(exc),
            expected_exit_code=expected_exit_code,
        )
    finally:
        # 清理
        shutil.rmtree(tmpdir, ignore_errors=True)


def _extract_patch_files(patch: str) -> list[str]:
    """从 unified diff patch 中提取涉及的文件名。"""
    files = []
    for line in patch.splitlines():
        if line.startswith("+++ ") or line.startswith("--- "):
            path = line[4:].strip()
            # 去除 a/ b/ 前缀
            if path.startswith(("a/", "b/")):
                path = path[2:]
            if path and path != "/dev/null" and path not in files:
                files.append(path)
    return files
