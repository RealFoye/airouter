"""Benchmark Level 3 CLI integration tests."""

import json
import subprocess

from typer.testing import CliRunner

from airouter.cli.main import app

runner = CliRunner()


def _run_cli(args, timeout=120):
    """Run CLI via subprocess for clean stdout/stderr separation."""
    result = subprocess.run(
        ["python", "-m", "airouter.cli.main"] + args,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return result


def test_benchmark_level3_rich_output():
    """Level 3 rich output runs successfully."""
    result = runner.invoke(app, ["benchmark", "--level", "3", "--case-set", "l1"])
    assert result.exit_code == 0
    assert "Level 3 策略回测总览" in result.output
    assert "Baseline" in result.output


def test_benchmark_level3_json_output():
    """Level 3 JSON output is parseable."""
    result = _run_cli(["benchmark", "--level", "3", "--case-set", "l1", "--format", "json"])
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert data["level"] == 3
    assert data["quality_mode"] == "routing_prior"
    assert "baseline_model" in data
    assert "savings_total_cny" in data
    assert "case_results" in data
    assert "disclaimer" in data


def test_benchmark_level3_case_set_all():
    """--case-set all runs both L1 and L2 cases."""
    result = _run_cli(["benchmark", "--level", "3", "--case-set", "all", "--format", "json"])
    data = json.loads(result.stdout)
    assert data["l1_cases"] > 0
    assert data["l2_cases"] > 0
    assert data["total_cases"] == data["l1_cases"] + data["l2_cases"]


def test_benchmark_level3_nonexistent_baseline():
    """Nonexistent baseline model exits 1."""
    result = runner.invoke(app, [
        "benchmark", "--level", "3",
        "--baseline-model", "nonexistent",
    ])
    assert result.exit_code == 1
    assert "Unknown baseline model" in result.output


def test_benchmark_level3_non_tier1_baseline():
    """Non-Tier 1 baseline model exits 1."""
    result = runner.invoke(app, [
        "benchmark", "--level", "3",
        "--baseline-model", "qwen3.7-plus",
    ])
    assert result.exit_code == 1
    assert "must be Tier 1" in result.output


def test_benchmark_level3_cases_rejected():
    """--cases is rejected in Level 3."""
    result = runner.invoke(app, [
        "benchmark", "--level", "3",
        "--cases", "some_file.yaml",
    ])
    assert result.exit_code == 1
    assert "--case-set" in result.output


def test_benchmark_level3_cases_rejected_json():
    """--cases rejection in JSON mode: stderr has JSON, stdout is empty."""
    result = _run_cli([
        "benchmark", "--level", "3",
        "--cases", "some_file.yaml",
        "--format", "json",
    ])
    assert result.returncode == 1
    assert result.stdout.strip() == ""
    error_data = json.loads(result.stderr)
    assert "error" in error_data
    assert "--case-set" in error_data["error"]


def test_benchmark_level3_non_tier1_json():
    """Non-Tier 1 baseline in JSON mode: clean stderr."""
    result = _run_cli([
        "benchmark", "--level", "3",
        "--baseline-model", "qwen3.7-plus",
        "--format", "json",
    ])
    assert result.returncode == 1
    assert result.stdout.strip() == ""
    error_data = json.loads(result.stderr)
    assert "error" in error_data
    assert "Tier 1" in error_data["error"]


def test_benchmark_level3_invalid_case_set_json():
    """Invalid --case-set in JSON mode: stderr has JSON, stdout is empty."""
    result = _run_cli([
        "benchmark", "--level", "3",
        "--case-set", "bad",
        "--format", "json",
    ])
    assert result.returncode == 1
    assert result.stdout.strip() == ""
    error_data = json.loads(result.stderr)
    assert "error" in error_data
    assert "--case-set" in error_data["error"]


def test_benchmark_level3_invalid_case_set_rich():
    """Invalid --case-set in rich mode exits 1 with error message."""
    result = runner.invoke(app, [
        "benchmark", "--level", "3",
        "--case-set", "bad",
    ])
    assert result.exit_code == 1
    assert "--case-set" in result.output
