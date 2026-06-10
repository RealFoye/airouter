"""Benchmark Level 2 CLI integration tests."""

import json
import subprocess

import yaml
from typer.testing import CliRunner

from airouter.cli.main import app

runner = CliRunner()


def _make_l2_cases_yaml(path, models=None):
    data = {
        "version": "2.0",
        "models": models or ["qwen3.7-max", "qwen3.7-plus"],
        "cases": [
            {
                "id": "INT-001",
                "task_type": "CODE_GENERATION",
                "complexity": "SIMPLE",
                "prompt": "写一个简单的回文检查函数",
                "scoring_type": "code_generation",
                "evaluation_criteria": {
                    "must_have": [
                        {"id": "func", "any_of": ["def "]},
                    ]
                },
                "expected_issues": [],
            }
        ],
    }
    path.write_text(yaml.dump(data), encoding="utf-8")
    return path


def _run_cli(args, timeout=60):
    """Run CLI via subprocess to get clean stdout/stderr separation."""
    result = subprocess.run(
        ["python", "-m", "airouter.cli.main"] + args,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return result


def test_benchmark_level2_rich_output(tmp_path):
    """Level 2 rich output runs successfully with mock."""
    cases_yaml = _make_l2_cases_yaml(tmp_path / "cases.yaml")
    output_dir = tmp_path / "results"
    result = runner.invoke(app, [
        "benchmark", "--level", "2",
        "--cases", str(cases_yaml),
        "--output-dir", str(output_dir),
    ])
    assert "Level 2 总览" in result.output
    assert result.exit_code == 0


def test_benchmark_level2_json_output(tmp_path):
    """Level 2 JSON output is parseable (subprocess for clean stdout)."""
    cases_yaml = _make_l2_cases_yaml(tmp_path / "cases.yaml")
    output_dir = tmp_path / "results"
    result = _run_cli([
        "benchmark", "--level", "2",
        "--cases", str(cases_yaml),
        "--output-dir", str(output_dir),
        "--format", "json",
    ])
    data = json.loads(result.stdout)
    assert data["level"] == 2
    assert "model_scores" in data
    assert "run_id" in data
    assert "completed_pairs" in data


def test_benchmark_level2_limit(tmp_path):
    """--limit restricts number of pairs."""
    cases_yaml = _make_l2_cases_yaml(tmp_path / "cases.yaml")
    output_dir = tmp_path / "results"
    result = _run_cli([
        "benchmark", "--level", "2",
        "--cases", str(cases_yaml),
        "--output-dir", str(output_dir),
        "--limit", "1",
        "--format", "json",
    ])
    data = json.loads(result.stdout)
    assert data["completed_pairs"] <= 1


def test_benchmark_level2_custom_models(tmp_path):
    """--models overrides YAML models."""
    cases_yaml = _make_l2_cases_yaml(tmp_path / "cases.yaml")
    output_dir = tmp_path / "results"
    result = _run_cli([
        "benchmark", "--level", "2",
        "--cases", str(cases_yaml),
        "--output-dir", str(output_dir),
        "--models", "qwen3.7-max",
        "--format", "json",
    ])
    data = json.loads(result.stdout)
    assert data["total_models"] == 1
    assert "qwen3.7-max" in data["model_scores"]


def test_benchmark_level2_invalid_model(tmp_path):
    """Invalid model name exits 1."""
    cases_yaml = _make_l2_cases_yaml(tmp_path / "cases.yaml")
    output_dir = tmp_path / "results"
    result = runner.invoke(app, [
        "benchmark", "--level", "2",
        "--cases", str(cases_yaml),
        "--output-dir", str(output_dir),
        "--models", "nonexistent-model",
    ])
    assert result.exit_code == 1


def test_benchmark_level2_resume(tmp_path):
    """--resume with --run-id resumes an existing run."""
    cases_yaml = _make_l2_cases_yaml(tmp_path / "cases.yaml")
    output_dir = tmp_path / "results"
    output_dir.mkdir()

    # First run
    result = _run_cli([
        "benchmark", "--level", "2",
        "--cases", str(cases_yaml),
        "--output-dir", str(output_dir),
        "--format", "json",
    ])
    data1 = json.loads(result.stdout)
    run_id = data1["run_id"]

    # Second run with resume
    result2 = _run_cli([
        "benchmark", "--level", "2",
        "--cases", str(cases_yaml),
        "--output-dir", str(output_dir),
        "--resume",
        "--run-id", run_id,
        "--format", "json",
    ])
    data2 = json.loads(result2.stdout)
    assert data2["run_id"] == run_id
    assert data2["completed_pairs"] == data1["completed_pairs"]


def test_benchmark_level99_unsupported():
    """Unsupported level exits 1."""
    result = runner.invoke(app, ["benchmark", "--level", "99"])
    assert result.exit_code == 1
    assert "不支持" in result.output
