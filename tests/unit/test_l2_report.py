"""Tests for l2_report: report generation with judge and pairwise results."""

from __future__ import annotations

from pathlib import Path

from airouter.engine.benchmark.l2_report import generate_l2_report
from airouter.engine.benchmark.schemas import (
    JudgeSummary,
    L2Summary,
    PairwiseSummary,
)


def _make_l2_summary(**kwargs) -> L2Summary:
    defaults = {
        "run_id": "test_run_001",
        "total_cases": 30,
        "total_models": 5,
        "total_api_calls": 150,
        "total_input_tokens": 100000,
        "total_output_tokens": 200000,
        "total_cost_cny": 12.34,
        "total_latency_ms": 50000,
        "completed_pairs": 150,
        "failed_pairs": 0,
        "model_scores": {"qwen3.7-max": 0.85, "deepseek-v4-pro": 0.80, "glm-5.1": 0.75},
        "task_type_scores": {"CODE_GENERATION": 0.82, "CODE_REVIEW": 0.78},
    }
    defaults.update(kwargs)
    return L2Summary(**defaults)


def _make_judge_summary(**kwargs) -> JudgeSummary:
    defaults = {
        "judge_model": "qwen3.7-max",
        "total_evaluations": 150,
        "successful": 150,
        "failed": 0,
        "model_truncated_count": 2,
        "judge_context_truncated_count": 1,
        "starved_count": 0,
        "by_model": {
            "qwen3.7-max": {"avg": 0.85, "count": 30.0},
            "deepseek-v4-pro": {"avg": 0.80, "count": 30.0},
        },
        "by_task_type": {},
        "estimated_cost_cny": 5.67,
        "results": [],
    }
    defaults.update(kwargs)
    return JudgeSummary(**defaults)


def _make_pairwise_summary(**kwargs) -> PairwiseSummary:
    defaults = {
        "total_pairs": 10,
        "total_judges": 2,
        "total_calls": 600,
        "successful": 600,
        "failed": 0,
        "win_rates": {"qwen3.7-max": {"deepseek-v4-pro": 0.6}},
        "overall_ranking": [
            {"model": "qwen3.7-max", "wins": 20, "losses": 5, "ties": 5, "win_rate": 0.67},
            {"model": "deepseek-v4-pro", "wins": 15, "losses": 10, "ties": 5, "win_rate": 0.50},
        ],
        "agreement_rate": 0.85,
        "judge_agreement_detail": {"agree": 255, "disagree": 45},
        "estimated_cost_cny": 8.90,
        "results": [],
    }
    defaults.update(kwargs)
    return PairwiseSummary(**defaults)


class TestGenerateReport:
    def test_basic_report(self):
        report = generate_l2_report(_make_l2_summary())
        assert "Level 2 Benchmark" in report
        assert "qwen3.7-max" in report
        assert "Auto-score" in report
        assert "成本分析" in report
        assert "局限性" in report

    def test_report_with_judge(self):
        report = generate_l2_report(
            _make_l2_summary(),
            judge_results=_make_judge_summary(),
        )
        assert "Absolute Judge" in report
        assert "qwen3.7-max" in report
        assert "150/150" in report or "150" in report

    def test_report_with_pairwise(self):
        report = generate_l2_report(
            _make_l2_summary(),
            pairwise_results=_make_pairwise_summary(),
        )
        assert "Pairwise" in report
        assert "Agreement rate" in report or "agreement_rate" in report.lower()
        assert "Win Rate" in report or "win_rate" in report.lower()

    def test_report_with_all_results(self):
        report = generate_l2_report(
            _make_l2_summary(),
            judge_results=_make_judge_summary(),
            pairwise_results=_make_pairwise_summary(),
        )
        assert "Auto-score" in report
        assert "Absolute Judge" in report
        assert "Pairwise" in report
        assert "CCH" in report  # billing reminder

    def test_report_saves_to_file(self, tmp_path: Path):
        report = generate_l2_report(
            _make_l2_summary(),
            output_dir=tmp_path,
        )
        report_path = tmp_path / "model-selection-report.md"
        assert report_path.exists()
        assert report_path.read_text(encoding="utf-8") == report

    def test_report_no_unsubstantiated_claims(self):
        """Report should not claim undisputed #1 ranking."""
        report = generate_l2_report(_make_l2_summary())
        assert "无争议第一" not in report
        assert "undisputed" not in report.lower()

    def test_report_includes_data_note(self):
        report = generate_l2_report(_make_l2_summary())
        assert "诊断数据" in report
        assert "20260608_202410" in report

    def test_report_includes_limitations(self):
        report = generate_l2_report(_make_l2_summary())
        assert "样本量" in report
        assert "人工抽检" in report

    def test_missing_pairwise_graceful(self):
        """Report should work without pairwise results."""
        report = generate_l2_report(
            _make_l2_summary(),
            judge_results=_make_judge_summary(),
            pairwise_results=None,
        )
        assert "Pairwise" not in report
        assert "Absolute Judge" in report
