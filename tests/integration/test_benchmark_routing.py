"""Routing Ground Truth Benchmark CLI integration tests."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from typer.testing import CliRunner

from airouter.cli.main import app

runner = CliRunner()


def test_routing_benchmark_mock_json():
    """Mock mode routing benchmark produces valid JSON output."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        result = runner.invoke(
            app,
            [
                "benchmark",
                "--level", "routing",
                "--format", "json",
                "--output-dir", tmp_dir,
            ],
        )
        assert result.exit_code == 0, f"CLI failed: {result.output}"
        data = json.loads(result.output)
        assert "run_id" in data
        assert data["total_cases"] == 90  # 30 dev + 60 holdout
        assert data["dev_cases"] == 30
        assert data["holdout_cases"] == 60
        assert data["is_mock_run"] is True
        assert data["mock_evaluations"] > 0
        assert data["total_physical_api_calls"] == 0
        # New limit/resume fields
        assert data["remaining_pairs"] == 0
        assert data["run_completed"] is True
        assert data["complete_cases"] > 0
        assert data["analysis_deferred"] is False
        # Strategy results
        assert len(data["signal_strategy_results"]) >= 1
        assert len(data["end_to_end_strategy_results"]) >= 1


def test_routing_benchmark_mock_rich():
    """Mock mode routing benchmark produces rich output with strategy tables."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        result = runner.invoke(
            app,
            [
                "benchmark",
                "--level", "routing",
                "--format", "rich",
                "--output-dir", tmp_dir,
            ],
        )
        assert result.exit_code == 0, f"CLI failed: {result.output}"
        assert "A 层" in result.output or "策略" in result.output


def test_routing_benchmark_creates_report():
    """Mock mode creates report.md in run directory."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        result = runner.invoke(
            app,
            [
                "benchmark",
                "--level", "routing",
                "--format", "rich",
                "--output-dir", tmp_dir,
            ],
        )
        assert result.exit_code == 0, f"CLI failed: {result.output}"
        # Check report was created
        run_dirs = list(Path(tmp_dir).iterdir())
        assert len(run_dirs) >= 1
        run_dir = run_dirs[0]
        report = run_dir / "report.md"
        assert report.exists(), f"report.md not found in {run_dir}"
        content = report.read_text(encoding="utf-8")
        assert len(content) > 100
