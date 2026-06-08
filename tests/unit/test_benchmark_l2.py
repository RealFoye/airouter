"""Level 2 benchmark runner unit tests."""

import json
from pathlib import Path

import pytest
import yaml

from airouter.engine.benchmark.runner import Level2BenchmarkRunner
from airouter.engine.benchmark.schemas import L2Summary


@pytest.fixture
def cases_yaml(tmp_path: Path) -> Path:
    """Create a minimal L2 cases YAML."""
    data = {
        "version": "2.0",
        "models": ["qwen3.7-max", "qwen3.7-plus"],
        "cases": [
            {
                "id": "CG-001",
                "task_type": "CODE_GENERATION",
                "complexity": "SIMPLE",
                "prompt": "写一个回文检查函数",
                "scoring_type": "code_generation",
                "evaluation_criteria": {
                    "must_have": [
                        {"id": "func", "any_of": ["def "]},
                        {"id": "return", "any_of": ["return"]},
                    ]
                },
                "expected_issues": [],
            },
            {
                "id": "CR-001",
                "task_type": "CODE_REVIEW",
                "complexity": "MODERATE",
                "prompt": "审查这段代码的安全问题",
                "scoring_type": "code_review",
                "evaluation_criteria": {},
                "expected_issues": ["sql_injection"],
            },
        ],
    }
    yaml_path = tmp_path / "l2_cases.yaml"
    yaml_path.write_text(yaml.dump(data), encoding="utf-8")
    return yaml_path


@pytest.fixture
def output_dir(tmp_path: Path) -> Path:
    d = tmp_path / "results"
    d.mkdir()
    return d


def _make_runner(cases_yaml, output_dir, **kwargs):
    return Level2BenchmarkRunner(
        cases_path=cases_yaml,
        force_mock=True,
        rate_limit_rpm=10000,
        results_base_dir=output_dir,
        **kwargs,
    )


class TestLevel2Runner:
    def test_basic_run_produces_summary(self, cases_yaml, output_dir):
        runner = _make_runner(cases_yaml, output_dir)
        summary = runner.run()
        assert isinstance(summary, L2Summary)
        assert summary.level == 2
        assert summary.total_cases == 2
        assert summary.total_models == 2
        assert summary.completed_pairs == 4  # 2 cases × 2 models
        assert summary.failed_pairs == 0
        assert summary.run_id != ""

    def test_run_creates_directory(self, cases_yaml, output_dir):
        runner = _make_runner(cases_yaml, output_dir)
        summary = runner.run()
        run_dir = output_dir / summary.run_id
        assert run_dir.exists()
        assert (run_dir / "run_state.json").exists()
        assert (run_dir / "results.jsonl").exists()
        assert (run_dir / "raw_outputs").exists()

    def test_limit_max_pairs(self, cases_yaml, output_dir):
        runner = _make_runner(cases_yaml, output_dir)
        summary = runner.run(max_pairs=2)
        # Only 2 pairs executed (out of 4)
        assert summary.completed_pairs <= 2
        # Partial run must not report completed
        assert summary.run_completed is False

    def test_run_state_persisted(self, cases_yaml, output_dir):
        runner = _make_runner(cases_yaml, output_dir)
        summary = runner.run()
        state_path = output_dir / summary.run_id / "run_state.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        assert state["status"] == "completed"
        assert state["completed_pairs"] == 4
        assert len(state["models"]) == 2

    def test_jsonl_has_all_records(self, cases_yaml, output_dir):
        runner = _make_runner(cases_yaml, output_dir)
        summary = runner.run()
        jsonl_path = output_dir / summary.run_id / "results.jsonl"
        lines = [line for line in jsonl_path.read_text().strip().split("\n") if line]
        assert len(lines) == 4  # 2 cases × 2 models

    def test_raw_outputs_saved(self, cases_yaml, output_dir):
        runner = _make_runner(cases_yaml, output_dir)
        summary = runner.run()
        raw_dir = output_dir / summary.run_id / "raw_outputs"
        raw_files = list(raw_dir.iterdir())
        assert len(raw_files) == 4
        for f in raw_files:
            assert f.suffix == ".txt"
            assert f.read_text(encoding="utf-8").startswith("[Mock]")

    def test_model_scores_computed(self, cases_yaml, output_dir):
        runner = _make_runner(cases_yaml, output_dir)
        summary = runner.run()
        assert "qwen3.7-max" in summary.model_scores
        assert "qwen3.7-plus" in summary.model_scores
        for score in summary.model_scores.values():
            assert 0.0 <= score <= 1.0


class TestResume:
    def test_resume_skips_completed(self, cases_yaml, output_dir):
        """Second run with resume should skip completed pairs."""
        runner = _make_runner(cases_yaml, output_dir)
        summary1 = runner.run()

        # Resume
        runner2 = _make_runner(cases_yaml, output_dir)
        summary2 = runner2.run(resume=True, run_id=summary1.run_id)
        # All pairs were already completed, so no new pairs
        assert summary2.completed_pairs == 4

    def test_resume_validates_hash(self, cases_yaml, output_dir):
        """Resume with different cases should fail."""
        runner = _make_runner(cases_yaml, output_dir)
        summary = runner.run()

        # Modify cases YAML
        data = yaml.safe_load(cases_yaml.read_text())
        data["cases"][0]["prompt"] = "changed prompt"
        cases_yaml.write_text(yaml.dump(data), encoding="utf-8")

        runner2 = _make_runner(cases_yaml, output_dir)
        with pytest.raises(ValueError, match="cases_hash 不匹配"):
            runner2.run(resume=True, run_id=summary.run_id)

    def test_resume_validates_models(self, cases_yaml, output_dir):
        """Resume with different models should fail."""
        runner = _make_runner(cases_yaml, output_dir)
        summary = runner.run()

        runner2 = Level2BenchmarkRunner(
            cases_path=cases_yaml,
            models=["qwen3.7-max"],  # only 1 model
            force_mock=True,
            rate_limit_rpm=10000,
            results_base_dir=output_dir,
        )
        with pytest.raises(ValueError, match="models 不匹配"):
            runner2.run(resume=True, run_id=summary.run_id)


class TestModelValidation:
    def test_invalid_model_raises(self, cases_yaml, output_dir):
        runner = Level2BenchmarkRunner(
            cases_path=cases_yaml,
            models=["nonexistent-model"],
            force_mock=True,
            rate_limit_rpm=10000,
            results_base_dir=output_dir,
        )
        with pytest.raises(ValueError, match="Unknown model"):
            runner.run()


class TestHelpers:
    def test_run_id_dedup(self, tmp_path):
        """Run ID should dedup with suffix when directory exists."""
        from airouter.engine.benchmark.runner import _generate_run_id

        base_dir = tmp_path / "runs"
        base_dir.mkdir()

        id1 = _generate_run_id(base_dir)
        (base_dir / id1).mkdir()

        id2 = _generate_run_id(base_dir)
        assert id1 != id2

    def test_sanitize_filename(self):
        from airouter.engine.benchmark.runner import _sanitize_filename

        assert _sanitize_filename("CG-001::qwen3.7-max") == "CG-001__qwen3.7-max"
        assert _sanitize_filename("simple_name") == "simple_name"

    def test_normalize_models(self):
        from airouter.engine.benchmark.runner import _normalize_models

        result = _normalize_models(["  b  ", "a", "b", " c "])
        assert result == ["a", "b", "c"]

    def test_jsonl_dedup(self, tmp_path):
        from airouter.engine.benchmark.runner import _dedup_results_from_jsonl

        jsonl = tmp_path / "results.jsonl"
        lines = [
            json.dumps({"case_id": "C1", "model": "m1", "status": "failed", "score": 0.1}),
            json.dumps({"case_id": "C1", "model": "m1", "status": "success", "score": 0.9}),
            json.dumps({"case_id": "C2", "model": "m1", "status": "success", "score": 0.8}),
        ]
        jsonl.write_text("\n".join(lines), encoding="utf-8")

        records = _dedup_results_from_jsonl(jsonl)
        assert len(records) == 2
        c1 = [r for r in records if r["case_id"] == "C1"][0]
        assert c1["status"] == "success"  # last record wins
        assert c1["score"] == 0.9
