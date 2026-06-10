"""Finance benchmark runner unit tests."""

import json
from pathlib import Path

import pytest
import yaml

from airouter.engine.benchmark.finance_runner import FinanceBenchmarkRunner
from airouter.engine.benchmark.finance_schemas import FinanceSummary


@pytest.fixture
def finance_yaml(tmp_path: Path) -> Path:
    """Create a minimal finance cases YAML."""
    data = {
        "version": "finance-1.0",
        "models": ["qwen3.7-max", "qwen3.7-plus"],
        "cases": [
            {
                "id": "FIN-TEST-001",
                "domain": "FINANCE_OFFICE",
                "category": "TABLE_CALCULATION",
                "task_type": "DATA_PROCESSING",
                "complexity": "SIMPLE",
                "prompt": "计算 ER-1001 的合计金额。只输出 JSON。",
                "input_context": "ER-1001: hotel Shanghai 680; client_meal 420; taxi 95.",
                "artifacts": ["artifacts/expenses/expense_claims_may.csv"],
                "output_format": {
                    "type": "json",
                    "required_fields": ["decision", "amounts", "findings", "evidence", "confidence"],
                },
                "expected_answer": {
                    "amounts": {"raw_total_cny": 1195.0},
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
            },
            {
                "id": "FIN-TEST-002",
                "domain": "FINANCE_OFFICE",
                "category": "REIMBURSEMENT_AUDIT",
                "task_type": "DATA_PROCESSING",
                "complexity": "MODERATE",
                "prompt": "审核 ER-1001 报销单。只输出 JSON。",
                "input_context": "ER-1001: hotel Shanghai 680; client_meal 420 with 2 attendees.",
                "artifacts": ["artifacts/policies/travel_policy.md"],
                "output_format": {
                    "type": "json",
                    "required_fields": ["decision", "amounts", "findings", "evidence", "confidence"],
                },
                "expected_answer": {
                    "amounts": {"approved_amount_cny": 1095.0, "rejected_amount_cny": 100.0},
                    "required_findings": ["hotel_over_limit"],
                    "decision": "partial_approve",
                },
                "evaluation": {
                    "primary": "rule_based",
                    "numeric_tolerance": 0.01,
                    "penalize_hallucinated_findings": True,
                    "evidence_required": True,
                    "scoring_type": "finance_reimbursement",
                    "exact_amounts": ["approved_amount_cny", "rejected_amount_cny"],
                    "required_findings": ["hotel_over_limit"],
                },
                "max_tokens": 8192,
            },
        ],
    }
    yaml_path = tmp_path / "finance_cases.yaml"
    yaml_path.write_text(yaml.dump(data, allow_unicode=True), encoding="utf-8")
    return yaml_path


@pytest.fixture
def output_dir(tmp_path: Path) -> Path:
    d = tmp_path / "results"
    d.mkdir()
    return d


def _make_runner(finance_yaml, output_dir, **kwargs):
    return FinanceBenchmarkRunner(
        cases_path=finance_yaml,
        force_mock=True,
        rate_limit_rpm=10000,
        results_base_dir=output_dir,
        **kwargs,
    )


class TestFinanceRunner:
    def test_basic_run_produces_summary(self, finance_yaml, output_dir):
        runner = _make_runner(finance_yaml, output_dir)
        summary = runner.run()
        assert isinstance(summary, FinanceSummary)
        assert summary.level == "finance"
        assert summary.total_cases == 2
        assert summary.total_models == 2
        assert summary.completed_pairs == 4  # 2 cases × 2 models
        assert summary.failed_pairs == 0
        assert summary.run_id != ""

    def test_run_creates_directory(self, finance_yaml, output_dir):
        runner = _make_runner(finance_yaml, output_dir)
        summary = runner.run()
        run_dir = output_dir / summary.run_id
        assert run_dir.exists()
        assert (run_dir / "run_state.json").exists()
        assert (run_dir / "results.jsonl").exists()
        assert (run_dir / "raw_outputs").exists()

    def test_limit_max_pairs(self, finance_yaml, output_dir):
        runner = _make_runner(finance_yaml, output_dir)
        summary = runner.run(max_pairs=2)
        assert summary.completed_pairs == 2
        assert summary.run_completed is False

    def test_run_state_persisted(self, finance_yaml, output_dir):
        runner = _make_runner(finance_yaml, output_dir)
        summary = runner.run()
        run_dir = output_dir / summary.run_id
        state = json.loads((run_dir / "run_state.json").read_text(encoding="utf-8"))
        assert state["status"] == "completed"
        assert state["completed_pairs"] == 4
        assert len(state["models"]) == 2

    def test_jsonl_has_all_records(self, finance_yaml, output_dir):
        runner = _make_runner(finance_yaml, output_dir)
        summary = runner.run()
        run_dir = output_dir / summary.run_id
        lines = (run_dir / "results.jsonl").read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 4

    def test_raw_outputs_saved(self, finance_yaml, output_dir):
        runner = _make_runner(finance_yaml, output_dir)
        summary = runner.run()
        run_dir = output_dir / summary.run_id
        raw_dir = run_dir / "raw_outputs"
        txt_files = list(raw_dir.glob("*.txt"))
        assert len(txt_files) == 4

    def test_category_scores_computed(self, finance_yaml, output_dir):
        runner = _make_runner(finance_yaml, output_dir)
        summary = runner.run()
        assert "TABLE_CALCULATION" in summary.category_scores
        assert "REIMBURSEMENT_AUDIT" in summary.category_scores

    def test_model_scores_in_range(self, finance_yaml, output_dir):
        runner = _make_runner(finance_yaml, output_dir)
        summary = runner.run()
        for model, score in summary.model_scores.items():
            assert 0.0 <= score <= 1.0, f"{model} score {score} out of range"

    def test_dimension_scores_present(self, finance_yaml, output_dir):
        runner = _make_runner(finance_yaml, output_dir)
        summary = runner.run()
        # Mock output won't be valid JSON, so scores will be 0, but dims should exist
        assert hasattr(summary, "avg_json_validity")
        assert hasattr(summary, "avg_amount_accuracy")
        assert hasattr(summary, "avg_finding_recall")

    def test_jsonl_includes_category(self, finance_yaml, output_dir):
        runner = _make_runner(finance_yaml, output_dir)
        runner.run()
        run_dir = output_dir / sorted(
            [d.name for d in output_dir.iterdir() if d.is_dir()]
        )[0]
        lines = (run_dir / "results.jsonl").read_text(encoding="utf-8").strip().split("\n")
        for line in lines:
            record = json.loads(line)
            assert "category" in record
            assert record["category"] in ("TABLE_CALCULATION", "REIMBURSEMENT_AUDIT")

    def test_invalid_model_raises(self, finance_yaml, output_dir):
        runner = FinanceBenchmarkRunner(
            cases_path=finance_yaml,
            models=["nonexistent-model"],
            force_mock=True,
            rate_limit_rpm=10000,
            results_base_dir=output_dir,
        )
        with pytest.raises(ValueError, match="Unknown model"):
            runner.run()


class TestFinanceResume:
    def test_resume_skips_completed(self, finance_yaml, output_dir):
        runner1 = _make_runner(finance_yaml, output_dir)
        summary1 = runner1.run()

        runner2 = _make_runner(finance_yaml, output_dir)
        summary2 = runner2.run(resume=True)
        assert summary2.completed_pairs == summary1.completed_pairs

    def test_resume_validates_hash(self, finance_yaml, output_dir):
        runner1 = _make_runner(finance_yaml, output_dir)
        runner1.run()

        # Modify cases file
        data = yaml.safe_load(finance_yaml.read_text(encoding="utf-8"))
        data["cases"][0]["prompt"] = "不同的提示"
        finance_yaml.write_text(yaml.dump(data, allow_unicode=True), encoding="utf-8")

        runner2 = _make_runner(finance_yaml, output_dir)
        with pytest.raises(ValueError, match="cases_hash"):
            runner2.run(resume=True)

    def test_resume_validates_models(self, finance_yaml, output_dir):
        runner1 = _make_runner(finance_yaml, output_dir)
        runner1.run()

        runner2 = FinanceBenchmarkRunner(
            cases_path=finance_yaml,
            models=["qwen3.7-max"],  # different model list
            force_mock=True,
            rate_limit_rpm=10000,
            results_base_dir=output_dir,
        )
        with pytest.raises(ValueError, match="models"):
            runner2.run(resume=True)

    def test_resume_failed_then_success(self, finance_yaml, output_dir, monkeypatch):
        """First run fails one pair, resume succeeds."""
        from airouter.adapters.base import AdapterError

        call_count = {"n": 0}
        original_execute = None

        def failing_execute(self_exec, model, messages, max_tokens=None):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise AdapterError("Simulated failure")
            return original_execute(model, messages, max_tokens=max_tokens)

        runner1 = _make_runner(finance_yaml, output_dir)
        original_execute = runner1._executor.execute
        monkeypatch.setattr(runner1._executor, "execute",
                           lambda model, messages, max_tokens=None: failing_execute(
                               runner1._executor, model, messages, max_tokens
                           ))
        summary1 = runner1.run()
        assert summary1.failed_pairs >= 1

        # Resume without the monkeypatch
        runner2 = _make_runner(finance_yaml, output_dir)
        summary2 = runner2.run(resume=True)
        assert summary2.completed_pairs == 4


class TestBuildSchemaHint:
    """Test _build_schema_hint() method."""

    def test_with_exact_amounts(self, finance_yaml, output_dir):
        """Test schema hint with exact_amounts from evaluation."""
        from airouter.engine.benchmark.finance_loader import load_finance_cases

        runner = _make_runner(finance_yaml, output_dir)
        cases = load_finance_cases(finance_yaml)
        case = cases[0]  # FIN-TEST-001 has exact_amounts: ["raw_total_cny"]

        hint = runner._build_schema_hint(case)
        assert "raw_total_cny" in hint
        assert "amounts 中请使用以下 key" in hint
        assert "不要改写 key 名" in hint

    def test_with_multiple_amount_keys(self, finance_yaml, output_dir):
        """Test schema hint with multiple amount keys."""
        from airouter.engine.benchmark.finance_loader import load_finance_cases

        runner = _make_runner(finance_yaml, output_dir)
        cases = load_finance_cases(finance_yaml)
        case = cases[1]  # FIN-TEST-002 has approved_amount_cny, rejected_amount_cny

        hint = runner._build_schema_hint(case)
        assert "approved_amount_cny" in hint
        assert "rejected_amount_cny" in hint

    def test_with_top_item(self, finance_yaml, output_dir, tmp_path: Path):
        """Test schema hint with top_item field."""
        from airouter.engine.benchmark.finance_schemas import FinanceCase

        runner = _make_runner(finance_yaml, output_dir)
        case = FinanceCase(
            id="TEST-001",
            category="TABLE_CALCULATION",
            complexity="MODERATE",
            prompt="Test prompt",
            expected_answer={
                "amounts": {"total_cny": 1000},
                "top_item": {"dept": "Sales", "amount_cny": 500},
            },
            evaluation={"exact_amounts": ["total_cny"]},
        )

        hint = runner._build_schema_hint(case)
        assert "top_item 字段" in hint
        assert "dept" in hint
        assert "amount_cny" in hint

    def test_with_top_items_array(self, finance_yaml, output_dir, tmp_path: Path):
        """Test schema hint with top_items array."""
        from airouter.engine.benchmark.finance_schemas import FinanceCase

        runner = _make_runner(finance_yaml, output_dir)
        case = FinanceCase(
            id="TEST-002",
            category="TABLE_CALCULATION",
            complexity="COMPLEX",
            prompt="Test prompt",
            expected_answer={
                "amounts": {"total_cny": 1000},
                "top_items": [
                    {"dept": "Sales", "total_cny": 500, "variance_cny": 50},
                    {"dept": "Marketing", "total_cny": 300, "variance_cny": 30},
                ],
            },
            evaluation={"exact_amounts": ["total_cny"]},
        )

        hint = runner._build_schema_hint(case)
        assert "top_items 字段（数组）" in hint
        assert "每个元素包含这些 key" in hint
        assert "dept" in hint
        assert "total_cny" in hint
        assert "variance_cny" in hint

    def test_fallback_no_explicit_keys(self, finance_yaml, output_dir, tmp_path: Path):
        """Test schema hint fallback when no explicit keys."""
        from airouter.engine.benchmark.finance_schemas import FinanceCase

        runner = _make_runner(finance_yaml, output_dir)
        case = FinanceCase(
            id="TEST-003",
            category="POLICY_QA",
            complexity="SIMPLE",
            prompt="Test prompt",
            expected_answer={},
            evaluation={},
        )

        hint = runner._build_schema_hint(case)
        assert "amounts 应使用结构化 key" in hint
        assert "如 raw_total_cny" in hint
        assert "明确数值和币种" in hint

    def test_schema_hint_in_messages(self, finance_yaml, output_dir):
        """Test that schema hint is appended to messages."""
        from airouter.engine.benchmark.finance_loader import load_finance_cases

        runner = _make_runner(finance_yaml, output_dir)
        cases = load_finance_cases(finance_yaml)
        case = cases[0]

        messages = runner._build_messages(case)
        user_content = messages[-1]["content"]
        assert "【输出结构要求】" in user_content
        assert "raw_total_cny" in user_content
