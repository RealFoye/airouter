"""Tests for scripts/analyze_judge_run.py.

Uses temporary run directories — no API calls.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Add scripts/ to path for import
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

from analyze_judge_run import (  # noqa: E402
    check_report_has_judge_appendix,
    find_judge_jsonl,
    get_rule_score,
    load_judge_data,
    load_rule_scores,
    run_analysis,
)


@pytest.fixture
def tmp_run_dir(tmp_path: Path) -> Path:
    """Create a minimal temporary run directory with all required files."""
    run_dir = tmp_path / "test_run"
    run_dir.mkdir()

    # results.rescored.jsonl
    rescored = [
        {"case_id": "FIN-001", "model": "model-a", "overall_score": 0.9},
        {"case_id": "FIN-001", "model": "model-b", "overall_score": 0.5},
        {"case_id": "FIN-002", "model": "model-a", "overall_score": 0.8},
        {"case_id": "FIN-002", "model": "model-b", "overall_score": 0.3},
    ]
    with open(run_dir / "results.rescored.jsonl", "w") as f:
        for r in rescored:
            f.write(json.dumps(r) + "\n")

    # finance_judge_testjudge.jsonl
    judge = [
        {
            "case_id": "FIN-001",
            "model": "model-a",
            "judge_model": "TestJudge",
            "weighted_score": 4.5,
            "normalized_score": 0.9,
            "rule_score": 0.85,
            "usage": {"prompt_tokens": 1000, "completion_tokens": 200},
            "red_flags": [],
        },
        {
            "case_id": "FIN-001",
            "model": "model-b",
            "judge_model": "TestJudge",
            "weighted_score": 2.5,
            "normalized_score": 0.5,
            "rule_score": 0.55,
            "usage": {"prompt_tokens": 1000, "completion_tokens": 200},
            "red_flags": ["json_structure_issue"],
        },
        {
            "case_id": "FIN-002",
            "model": "model-a",
            "judge_model": "TestJudge",
            "weighted_score": 4.0,
            "normalized_score": 0.8,
            "rule_score": 0.75,
            "usage": {"prompt_tokens": 1000, "completion_tokens": 200},
            "red_flags": [],
        },
        {
            "case_id": "FIN-002",
            "model": "model-b",
            "judge_model": "TestJudge",
            "weighted_score": 1.5,
            "normalized_score": 0.3,
            "rule_score": 0.35,
            "usage": {"prompt_tokens": 1000, "completion_tokens": 200},
            "red_flags": ["business_action_unclear"],
        },
    ]
    with open(run_dir / "finance_judge_testjudge.jsonl", "w") as f:
        for j in judge:
            f.write(json.dumps(j) + "\n")

    return run_dir


class TestFindJudgeJsonl:
    """Tests for find_judge_jsonl."""

    def test_finds_full_file(self, tmp_path: Path):
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        (run_dir / "finance_judge_minimax_m3.smoke.jsonl").write_text("")
        (run_dir / "finance_judge_minimax_m3.jsonl").write_text("")
        result = find_judge_jsonl(run_dir, "MiniMax-M3")
        assert result.name == "finance_judge_minimax_m3.jsonl"

    def test_finds_single_partial(self, tmp_path: Path):
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        (run_dir / "finance_judge_minimax_m3.smoke.jsonl").write_text("")
        result = find_judge_jsonl(run_dir, "MiniMax-M3")
        assert result.name == "finance_judge_minimax_m3.smoke.jsonl"

    def test_errors_on_multiple_partials(self, tmp_path: Path):
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        (run_dir / "finance_judge_minimax_m3.smoke.jsonl").write_text("")
        (run_dir / "finance_judge_minimax_m3.targeted.jsonl").write_text("")
        with pytest.raises(FileNotFoundError, match="Multiple partial"):
            find_judge_jsonl(run_dir, "MiniMax-M3")

    def test_not_found(self, tmp_path: Path):
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        with pytest.raises(FileNotFoundError, match="No judge JSONL"):
            find_judge_jsonl(run_dir, "MiniMax-M3")


class TestLoadRuleScores:
    """Tests for load_rule_scores."""

    def test_loads_all_pairs(self, tmp_run_dir: Path):
        scores = load_rule_scores(tmp_run_dir / "results.rescored.jsonl")
        assert len(scores) == 4
        assert scores[("FIN-001", "model-a")] == 0.9
        assert scores[("FIN-002", "model-b")] == 0.3


class TestLoadJudgeData:
    """Tests for load_judge_data."""

    def test_filters_by_judge_model(self, tmp_run_dir: Path):
        data, phys, matching, dupes = load_judge_data(
            tmp_run_dir / "finance_judge_testjudge.jsonl", "TestJudge"
        )
        assert phys == 4
        assert matching == 4
        assert dupes == 0
        assert len(data) == 4

    def test_filters_out_other_models(self, tmp_run_dir: Path):
        data, phys, matching, dupes = load_judge_data(
            tmp_run_dir / "finance_judge_testjudge.jsonl", "OtherJudge"
        )
        assert phys == 4
        assert matching == 0
        assert dupes == 0
        assert len(data) == 0

    def test_mixed_judge_model_no_false_duplicate(self, tmp_path: Path):
        """Mixed judge_model lines must not inflate duplicate count."""
        run_dir = tmp_path / "mixed"
        run_dir.mkdir()
        jsonl = run_dir / "finance_judge_testjudge.jsonl"
        rows = [
            {
                "case_id": "FIN-001", "model": "m1",
                "judge_model": "TestJudge",
                "weighted_score": 4.0, "normalized_score": 0.8,
                "rule_score": 0.8, "usage": {}, "red_flags": [],
            },
            {
                "case_id": "FIN-001", "model": "m1",
                "judge_model": "OtherJudge",
                "weighted_score": 3.0, "normalized_score": 0.6,
                "rule_score": 0.7, "usage": {}, "red_flags": [],
            },
            {
                "case_id": "FIN-002", "model": "m1",
                "judge_model": "TestJudge",
                "weighted_score": 3.5, "normalized_score": 0.7,
                "rule_score": 0.7, "usage": {}, "red_flags": [],
            },
        ]
        with open(jsonl, "w") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")

        data, phys, matching, dupes = load_judge_data(jsonl, "TestJudge")
        assert phys == 3
        assert matching == 2  # Only TestJudge lines
        assert dupes == 0  # No duplicates among matching lines
        assert len(data) == 2

    def test_actual_duplicates_counted(self, tmp_path: Path):
        """Duplicate lines for same (case_id, model) with matching judge_model."""
        run_dir = tmp_path / "dup"
        run_dir.mkdir()
        jsonl = run_dir / "finance_judge_testjudge.jsonl"
        rows = [
            {
                "case_id": "FIN-001", "model": "m1",
                "judge_model": "TestJudge",
                "weighted_score": 4.0, "normalized_score": 0.8,
                "rule_score": 0.8, "usage": {}, "red_flags": [],
            },
            {
                "case_id": "FIN-001", "model": "m1",
                "judge_model": "TestJudge",
                "weighted_score": 4.5, "normalized_score": 0.9,
                "rule_score": 0.8, "usage": {}, "red_flags": [],
            },
        ]
        with open(jsonl, "w") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")

        data, phys, matching, dupes = load_judge_data(jsonl, "TestJudge")
        assert phys == 2
        assert matching == 2
        assert dupes == 1
        assert len(data) == 1
        # Last occurrence wins
        assert data[("FIN-001", "m1")]["normalized_score"] == 0.9


class TestGetRuleScore:
    """Tests for get_rule_score: rescored > embedded."""

    def test_prefers_rescored(self):
        rescored = {("FIN-001", "model-a"): 0.95}
        warnings: list[str] = []
        result = get_rule_score(("FIN-001", "model-a"), rescored, 0.85, warnings)
        assert result == 0.95
        assert len(warnings) == 0

    def test_falls_back_with_warning(self):
        rescored: dict[tuple[str, str], float] = {}
        warnings: list[str] = []
        result = get_rule_score(("FIN-001", "model-a"), rescored, 0.85, warnings)
        assert result == 0.85
        assert len(warnings) == 1
        assert "WARNING" in warnings[0]
        assert "0.850" in warnings[0]


class TestCheckReportAppendix:
    """Tests for check_report_has_judge_appendix."""

    def test_has_exact_heading(self, tmp_path: Path):
        report = tmp_path / "report.md"
        report.write_text("# Report\n## 附录 A：LLM Judge 辅助审计（MiniMax-M3）\n")
        assert check_report_has_judge_appendix(report) is True

    def test_no_appendix_generic_judge(self, tmp_path: Path):
        """Generic 'Judge' text should NOT match — must be exact heading."""
        report = tmp_path / "report.md"
        report.write_text("# Report\n## Some Judge section\n")
        assert check_report_has_judge_appendix(report) is False

    def test_no_appendix(self, tmp_path: Path):
        report = tmp_path / "report.md"
        report.write_text("# Report\n## 1. 执行摘要\n")
        assert check_report_has_judge_appendix(report) is False

    def test_missing_file(self, tmp_path: Path):
        report = tmp_path / "nonexistent.md"
        assert check_report_has_judge_appendix(report) is False


class TestRunAnalysis:
    """Integration tests for run_analysis."""

    def test_run_dir_param_works(self, tmp_run_dir: Path):
        output = run_analysis(tmp_run_dir, "TestJudge")
        assert "=== Finance Judge Run Analysis ===" in output
        assert "TestJudge" in output
        assert "Success/Failure: 4/4" in output

    def test_rescored_overrides_embedded(self, tmp_run_dir: Path):
        """rescored scores should be used over embedded rule_score."""
        output = run_analysis(tmp_run_dir, "TestJudge")
        assert "results.rescored.jsonl (4 pairs loaded)" in output

    def test_cost_from_model_registry_unknown(self, tmp_run_dir: Path):
        """Unknown model should show cost=0 with warning."""
        output = run_analysis(tmp_run_dir, "TestJudge")
        assert "model not in models.yaml" in output
        assert "0.0000 CNY" in output

    def test_explicit_judge_jsonl(self, tmp_run_dir: Path):
        output = run_analysis(
            tmp_run_dir, "TestJudge",
            judge_jsonl_name="finance_judge_testjudge.jsonl",
        )
        assert "=== Finance Judge Run Analysis ===" in output

    def test_missing_judge_jsonl_errors(self, tmp_run_dir: Path):
        with pytest.raises(FileNotFoundError, match="not found"):
            run_analysis(
                tmp_run_dir, "TestJudge",
                judge_jsonl_name="nonexistent.jsonl",
            )

    def test_missing_rule_jsonl_errors(self, tmp_path: Path):
        run_dir = tmp_path / "empty_run"
        run_dir.mkdir()
        (run_dir / "finance_judge_testjudge.jsonl").write_text("")
        with pytest.raises(FileNotFoundError, match="No rule results"):
            run_analysis(run_dir, "TestJudge")

    def test_report_appendix_check(self, tmp_run_dir: Path):
        # No report exists yet
        output = run_analysis(tmp_run_dir, "TestJudge")
        assert "Report not yet generated" in output

        # Create report without appendix
        (tmp_run_dir / "finance_report.md").write_text("# Report\n")
        output = run_analysis(tmp_run_dir, "TestJudge")
        assert "does NOT contain Judge appendix" in output

        # Create report with exact appendix heading
        (tmp_run_dir / "finance_report.md").write_text(
            "# Report\n## 附录 A：LLM Judge 辅助审计（MiniMax-M3）\n"
        )
        output = run_analysis(tmp_run_dir, "TestJudge")
        assert "includes Judge appendix" in output

    def test_four_categories_sum(self, tmp_run_dir: Path):
        output = run_analysis(tmp_run_dir, "TestJudge")
        assert "Total classified: 4" in output

    def test_cost_caveat_note(self, tmp_run_dir: Path):
        output = run_analysis(tmp_run_dir, "TestJudge")
        assert "Internal retries are not counted" in output
        assert "CCH CSV" in output

    def test_blind_caveat(self, tmp_run_dir: Path):
        output = run_analysis(tmp_run_dir, "TestJudge")
        assert "non-blind" in output

    def test_line_counts_in_output(self, tmp_run_dir: Path):
        output = run_analysis(tmp_run_dir, "TestJudge")
        assert "Physical JSONL lines: 4" in output
        assert "Matching judge_model lines: 4" in output
        assert "Duplicate (case_id, model) lines: 0" in output


class TestRescoredVsEmbeddedClassification:
    """Test that rescored scores change disagreement classification."""

    def test_embedded_vs_rescored_produces_different_label(self, tmp_path: Path):
        """Construct data where embedded rule_score gives 'agree'
        but rescored gives 'rule_too_high'."""
        run_dir = tmp_path / "diff_run"
        run_dir.mkdir()

        # Rescored: rule=0.85 (high) — with judge=0.55 this is rule_too_high
        rescored = [
            {"case_id": "FIN-001", "model": "m1", "overall_score": 0.85},
        ]
        with open(run_dir / "results.rescored.jsonl", "w") as f:
            for r in rescored:
                f.write(json.dumps(r) + "\n")

        # Judge: normalized=0.55, embedded rule_score=0.60
        # With embedded: |0.60-0.55|=0.05 <= 0.15 → agree
        # With rescored: rule=0.85, judge=0.55, rule>=0.8 and judge<0.6 → rule_too_high
        judge = [
            {
                "case_id": "FIN-001", "model": "m1",
                "judge_model": "TestJudge",
                "weighted_score": 2.75, "normalized_score": 0.55,
                "rule_score": 0.60,  # embedded — would give "agree"
                "usage": {"prompt_tokens": 100, "completion_tokens": 50},
                "red_flags": [],
            },
        ]
        with open(run_dir / "finance_judge_testjudge.jsonl", "w") as f:
            for j in judge:
                f.write(json.dumps(j) + "\n")

        output = run_analysis(run_dir, "TestJudge")
        # Should show rule_too_high (from rescored 0.85), not agree (from embedded 0.60)
        assert "rule_too_high (rule>=0.8, judge<0.6):   1" in output
        assert "agree        (|delta|<=0.15):            0" in output
