"""Benchmark CLI integration tests."""

import json

import yaml
from typer.testing import CliRunner

from airouter.cli.main import app

runner = CliRunner()


def test_benchmark_level1_rich_output():
    """Level 1 rich output runs successfully."""
    result = runner.invoke(app, ["benchmark", "--level", "1"])
    # Exit code depends on whether all cases pass
    assert "Benchmark 总览" in result.output
    assert "指标详情" in result.output


def test_benchmark_level1_json_output():
    """Level 1 JSON output is parseable and contains metrics."""
    result = runner.invoke(app, ["benchmark", "--level", "1", "--format", "json"])
    data = json.loads(result.output)
    assert "level" in data
    assert data["level"] == 1
    assert "metrics" in data
    assert "classification_accuracy" in data["metrics"]
    assert "total_cases" in data
    assert "case_results" in data


def test_benchmark_level1_fail_fast():
    """--fail-fast runs without error."""
    result = runner.invoke(app, ["benchmark", "--level", "1", "--fail-fast"])
    assert "Benchmark 总览" in result.output


def test_benchmark_level1_resume():
    """--resume prints stateless warning and runs normally."""
    result = runner.invoke(app, ["benchmark", "--level", "1", "--resume"])
    assert "无状态运行" in result.output
    assert "Benchmark 总览" in result.output


def test_benchmark_level99_unsupported():
    """Unsupported level exits 1."""
    result = runner.invoke(app, ["benchmark", "--level", "99"])
    assert result.exit_code == 1
    assert "不支持" in result.output


def test_benchmark_nonexistent_cases_file():
    """--cases with nonexistent file exits 1."""
    result = runner.invoke(app, ["benchmark", "--level", "1", "--cases", "/nonexistent/path.yaml"])
    assert result.exit_code == 1


def test_benchmark_help():
    """--help exits 0."""
    result = runner.invoke(app, ["benchmark", "--help"])
    assert result.exit_code == 0
    assert "Benchmark" in result.output


def test_benchmark_resume_json_stdout_clean():
    """--resume --format json: JSON output is on stdout, warning is on stderr.

    CliRunner mix_stderr=False has issues with typer, so we verify at shell level.
    """
    import subprocess

    result = subprocess.run(
        ["python", "-m", "airouter.cli.main", "benchmark", "--level", "1", "--resume", "--format", "json"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    # stdout must be parseable JSON
    data = json.loads(result.stdout)
    assert data["level"] == 1
    assert "metrics" in data
    # stderr contains the resume warning
    assert "无状态运行" in result.stderr


def test_benchmark_empty_yaml(tmp_path):
    """Empty YAML file exits 1 with clean error, no traceback."""
    yaml_path = tmp_path / "empty.yaml"
    yaml_path.write_text("", encoding="utf-8")

    result = runner.invoke(app, ["benchmark", "--level", "1", "--cases", str(yaml_path)])
    assert result.exit_code == 1
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert "Traceback" not in result.output


def test_benchmark_yaml_no_cases_key(tmp_path):
    """YAML without 'cases' key exits 1 with clean error, no traceback."""
    yaml_path = tmp_path / "no_cases.yaml"
    yaml_path.write_text("version: '1.0'\ndescription: 'test'\n", encoding="utf-8")

    result = runner.invoke(app, ["benchmark", "--level", "1", "--cases", str(yaml_path)])
    assert result.exit_code == 1
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert "Traceback" not in result.output


def test_benchmark_custom_cases(tmp_path):
    """Custom cases file works."""
    data = {
        "version": "1.0",
        "cases": [
            {
                "id": "CUSTOM-001",
                "prompt": "写一个简单的问候函数",
                "expected_task_type": "CODE_GENERATION",
                "expected_complexity": "SIMPLE",
                "expected_risk": "LOW",
                "expected_strategy": "SINGLE_MODEL",
                "expected_requires_human_review": False,
            }
        ],
    }
    yaml_path = tmp_path / "custom_cases.yaml"
    yaml_path.write_text(yaml.dump(data), encoding="utf-8")

    result = runner.invoke(app, ["benchmark", "--level", "1", "--cases", str(yaml_path)])
    assert "Benchmark 总览" in result.output
    assert "CUSTOM-001" in result.output or "1/1" in result.output
