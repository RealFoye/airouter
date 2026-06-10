"""Finance benchmark CLI integration tests."""

import json
import subprocess

import yaml
from typer.testing import CliRunner

from airouter.cli.main import app

runner = CliRunner()


def _make_finance_cases_yaml(path, models=None):
    data = {
        "version": "finance-1.0",
        "models": models or ["qwen3.7-max", "qwen3.7-plus"],
        "cases": [
            {
                "id": "FIN-INT-001",
                "domain": "FINANCE_OFFICE",
                "category": "TABLE_CALCULATION",
                "task_type": "DATA_PROCESSING",
                "complexity": "SIMPLE",
                "prompt": "计算 ER-1001 的合计金额。只输出 JSON。",
                "input_context": "ER-1001: hotel Shanghai 680; taxi 95.",
                "artifacts": [],
                "output_format": {
                    "type": "json",
                    "required_fields": ["decision", "amounts", "findings", "evidence", "confidence"],
                },
                "expected_answer": {
                    "amounts": {"raw_total_cny": 775.0},
                    "required_findings": [],
                    "decision": "calculate",
                },
                "evaluation": {
                    "primary": "rule_based",
                    "numeric_tolerance": 0.01,
                    "penalize_hallucinated_findings": True,
                    "evidence_required": True,
                    "scoring_type": "finance_numeric",
                    "exact_amounts": ["raw_total_cny"],
                    "required_findings": [],
                },
                "max_tokens": 8192,
            }
        ],
    }
    path.write_text(yaml.dump(data, allow_unicode=True), encoding="utf-8")
    return path


def _run_cli(args, timeout=60):
    """Run CLI via subprocess for clean stdout/stderr separation."""
    result = subprocess.run(
        ["python", "-m", "airouter.cli.main"] + args,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return result


def test_benchmark_finance_rich_output(tmp_path):
    """Finance rich output runs successfully with mock."""
    cases_yaml = _make_finance_cases_yaml(tmp_path / "finance_cases.yaml")
    output_dir = tmp_path / "results"
    result = runner.invoke(app, [
        "benchmark", "--level", "finance",
        "--cases", str(cases_yaml),
        "--output-dir", str(output_dir),
    ])
    assert "Finance Benchmark 总览" in result.output
    assert result.exit_code == 0


def test_benchmark_finance_json_output(tmp_path):
    """Finance JSON output is parseable."""
    cases_yaml = _make_finance_cases_yaml(tmp_path / "finance_cases.yaml")
    output_dir = tmp_path / "results"
    result = _run_cli([
        "benchmark", "--level", "finance",
        "--cases", str(cases_yaml),
        "--output-dir", str(output_dir),
        "--format", "json",
    ])
    data = json.loads(result.stdout)
    assert data["level"] == "finance"
    assert "model_scores" in data
    assert "run_id" in data
    assert "completed_pairs" in data
    assert "category_scores" in data


def test_benchmark_finance_limit(tmp_path):
    """--limit restricts number of pairs."""
    cases_yaml = _make_finance_cases_yaml(tmp_path / "finance_cases.yaml")
    output_dir = tmp_path / "results"
    result = _run_cli([
        "benchmark", "--level", "finance",
        "--cases", str(cases_yaml),
        "--output-dir", str(output_dir),
        "--limit", "1",
        "--format", "json",
    ])
    data = json.loads(result.stdout)
    assert data["completed_pairs"] <= 1


def test_benchmark_finance_custom_models(tmp_path):
    """--models overrides YAML models."""
    cases_yaml = _make_finance_cases_yaml(tmp_path / "finance_cases.yaml")
    output_dir = tmp_path / "results"
    result = _run_cli([
        "benchmark", "--level", "finance",
        "--cases", str(cases_yaml),
        "--output-dir", str(output_dir),
        "--models", "qwen3.7-max",
        "--format", "json",
    ])
    data = json.loads(result.stdout)
    assert data["total_models"] == 1
    assert "qwen3.7-max" in data["model_scores"]


def test_benchmark_finance_invalid_model(tmp_path):
    """Invalid model name exits 1."""
    cases_yaml = _make_finance_cases_yaml(tmp_path / "finance_cases.yaml")
    output_dir = tmp_path / "results"
    result = runner.invoke(app, [
        "benchmark", "--level", "finance",
        "--cases", str(cases_yaml),
        "--output-dir", str(output_dir),
        "--models", "nonexistent-model",
    ])
    assert result.exit_code == 1


def test_benchmark_finance_resume(tmp_path):
    """--resume with --run-id resumes an existing run."""
    cases_yaml = _make_finance_cases_yaml(tmp_path / "finance_cases.yaml")
    output_dir = tmp_path / "results"
    output_dir.mkdir()

    # First run
    result = _run_cli([
        "benchmark", "--level", "finance",
        "--cases", str(cases_yaml),
        "--output-dir", str(output_dir),
        "--format", "json",
    ])
    data1 = json.loads(result.stdout)
    run_id = data1["run_id"]

    # Second run with resume
    result2 = _run_cli([
        "benchmark", "--level", "finance",
        "--cases", str(cases_yaml),
        "--output-dir", str(output_dir),
        "--resume",
        "--run-id", run_id,
        "--format", "json",
    ])
    data2 = json.loads(result2.stdout)
    assert data2["run_id"] == run_id
    assert data2["completed_pairs"] == data1["completed_pairs"]


def test_benchmark_finance_json_not_polluted_by_rich(tmp_path):
    """JSON output stdout is not polluted by Rich formatting."""
    cases_yaml = _make_finance_cases_yaml(tmp_path / "finance_cases.yaml")
    output_dir = tmp_path / "results"
    result = _run_cli([
        "benchmark", "--level", "finance",
        "--cases", str(cases_yaml),
        "--output-dir", str(output_dir),
        "--format", "json",
    ])
    # stdout should be valid JSON
    data = json.loads(result.stdout)
    assert isinstance(data, dict)
    assert "level" in data


def test_benchmark_old_levels_still_work(tmp_path):
    """Ensure --level 1, 2, 3 still work after the str change."""
    # Level 1 should work
    result = runner.invoke(app, ["benchmark", "--level", "1"])
    # Level 1 runs without error (exit 0 or 1 depending on pass/fail, but not crash)
    assert result.exit_code in (0, 1)
    assert "Benchmark" in result.output or "Level" in result.output

    # Level 99 should fail
    result = runner.invoke(app, ["benchmark", "--level", "99"])
    assert result.exit_code == 1
    assert "不支持" in result.output


def test_judge_existing_requires_run_id(tmp_path):
    """--judge-existing without --run-id exits 1."""
    cases_yaml = _make_finance_cases_yaml(tmp_path / "finance_cases.yaml")
    result = runner.invoke(app, [
        "benchmark", "--level", "finance",
        "--cases", str(cases_yaml),
        "--judge-existing",
    ])
    assert result.exit_code == 1
    assert "--run-id" in result.output or "run-id" in result.output


def test_judge_existing_nonexistent_run(tmp_path):
    """--judge-existing with non-existent run-id exits 1."""
    cases_yaml = _make_finance_cases_yaml(tmp_path / "finance_cases.yaml")
    output_dir = tmp_path / "results"
    output_dir.mkdir()
    result = runner.invoke(app, [
        "benchmark", "--level", "finance",
        "--cases", str(cases_yaml),
        "--output-dir", str(output_dir),
        "--judge-existing",
        "--run-id", "nonexistent_run_12345",
    ])
    assert result.exit_code == 1

