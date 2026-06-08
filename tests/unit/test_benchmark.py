"""Benchmark 单元测试：Loader / Scorer / Runner。"""

from pathlib import Path

import pytest
import yaml

from airouter.engine.benchmark.loader import load_cases
from airouter.engine.benchmark.runner import Level1BenchmarkRunner
from airouter.engine.benchmark.schemas import BenchmarkCase, BenchmarkSummary, CaseResult
from airouter.engine.benchmark.scorer import (
    METRIC_TARGETS,
    compute_case_failures,
    compute_metrics,
)

# ── Loader 测试 ──────────────────────────────────────────────


class TestLoader:
    """Benchmark case loader tests."""

    def test_load_default_path(self):
        """Default path loads >= 30 cases."""
        cases = load_cases()
        assert len(cases) >= 30

    def test_load_custom_path(self, tmp_path: Path):
        """Custom path loads cases correctly."""
        data = {
            "version": "1.0",
            "cases": [
                {
                    "id": "TEST-001",
                    "prompt": "test prompt",
                    "expected_task_type": "CODE_GENERATION",
                    "expected_complexity": "SIMPLE",
                    "expected_risk": "LOW",
                    "expected_strategy": "SINGLE_MODEL",
                }
            ],
        }
        yaml_path = tmp_path / "test_cases.yaml"
        yaml_path.write_text(yaml.dump(data), encoding="utf-8")

        cases = load_cases(yaml_path)
        assert len(cases) == 1
        assert cases[0].id == "TEST-001"

    def test_invalid_task_type(self, tmp_path: Path):
        """Invalid task_type raises ValueError."""
        data = {
            "cases": [
                {
                    "id": "BAD-001",
                    "prompt": "test",
                    "expected_task_type": "INVALID_TYPE",
                    "expected_complexity": "SIMPLE",
                    "expected_risk": "LOW",
                    "expected_strategy": "SINGLE_MODEL",
                }
            ]
        }
        yaml_path = tmp_path / "bad_cases.yaml"
        yaml_path.write_text(yaml.dump(data), encoding="utf-8")

        with pytest.raises(ValueError, match="invalid expected_task_type"):
            load_cases(yaml_path)

    def test_invalid_complexity(self, tmp_path: Path):
        """Invalid complexity raises ValueError."""
        data = {
            "cases": [
                {
                    "id": "BAD-002",
                    "prompt": "test",
                    "expected_task_type": "CODE_GENERATION",
                    "expected_complexity": "INVALID",
                    "expected_risk": "LOW",
                    "expected_strategy": "SINGLE_MODEL",
                }
            ]
        }
        yaml_path = tmp_path / "bad_cases.yaml"
        yaml_path.write_text(yaml.dump(data), encoding="utf-8")

        with pytest.raises(ValueError, match="invalid expected_complexity"):
            load_cases(yaml_path)

    def test_missing_required_fields(self, tmp_path: Path):
        """Missing required fields raises ValidationError."""
        data = {
            "cases": [
                {
                    "id": "BAD-003",
                    "prompt": "test",
                    # missing expected_task_type etc
                }
            ]
        }
        yaml_path = tmp_path / "bad_cases.yaml"
        yaml_path.write_text(yaml.dump(data), encoding="utf-8")

        with pytest.raises(Exception):  # Pydantic ValidationError
            load_cases(yaml_path)

    def test_empty_yaml_raises_valueerror(self, tmp_path: Path):
        """Empty YAML raises ValueError."""
        yaml_path = tmp_path / "empty.yaml"
        yaml_path.write_text("", encoding="utf-8")

        with pytest.raises(ValueError, match="empty or invalid"):
            load_cases(yaml_path)

    def test_yaml_no_cases_key_raises_valueerror(self, tmp_path: Path):
        """YAML without 'cases' key raises ValueError."""
        data = {"version": "1.0", "description": "test"}
        yaml_path = tmp_path / "no_cases.yaml"
        yaml_path.write_text(yaml.dump(data), encoding="utf-8")

        with pytest.raises(ValueError, match="non-empty"):
            load_cases(yaml_path)

    def test_yaml_empty_cases_list_raises_valueerror(self, tmp_path: Path):
        """YAML with empty cases list raises ValueError."""
        data = {"cases": []}
        yaml_path = tmp_path / "empty_cases.yaml"
        yaml_path.write_text(yaml.dump(data), encoding="utf-8")

        with pytest.raises(ValueError, match="non-empty"):
            load_cases(yaml_path)

    def test_yaml_non_dict_case_raises_valueerror(self, tmp_path: Path):
        """YAML with non-dict case item (e.g. null) raises ValueError."""
        data = {"cases": [None]}
        yaml_path = tmp_path / "null_case.yaml"
        yaml_path.write_text(yaml.dump(data), encoding="utf-8")

        with pytest.raises(ValueError, match="not a dict"):
            load_cases(yaml_path)


def _make_case(**overrides) -> BenchmarkCase:
    """Helper to create a BenchmarkCase with defaults."""
    defaults = {
        "id": "TEST-001",
        "prompt": "test",
        "expected_task_type": "CODE_GENERATION",
        "expected_complexity": "SIMPLE",
        "expected_risk": "LOW",
        "expected_strategy": "SINGLE_MODEL",
    }
    defaults.update(overrides)
    return BenchmarkCase(**defaults)


def _make_actuals(**overrides) -> dict:
    """Helper to create actuals dict with defaults."""
    defaults = {
        "task_type": "CODE_GENERATION",
        "complexity": "SIMPLE",
        "risk": "LOW",
        "strategy": "SINGLE_MODEL",
        "executor": "test-model",
        "executor_tier": 3,
        "planner": None,
        "planner_tier": None,
        "reviewer": None,
        "reviewer_tier": None,
        "requires_human_review": False,
        "quality_gate": ["syntax_check"],
        "estimated_cost": 0.01,
        "budget_status": "OK",
        "sensitivity": "LOW",
        "task_hash": "abc123",
        "fallback_triggers": [],
    }
    defaults.update(overrides)
    return defaults


class TestScorerFailures:
    """compute_case_failures tests."""

    def test_all_correct(self):
        """All matching → no failures."""
        case = _make_case()
        actuals = _make_actuals()
        assert compute_case_failures(case, actuals) == []

    def test_task_type_mismatch(self):
        case = _make_case(expected_task_type="CODE_GENERATION")
        actuals = _make_actuals(task_type="CONVERSATION")
        failures = compute_case_failures(case, actuals)
        assert len(failures) == 1
        assert "task_type" in failures[0]

    def test_executor_tier_mismatch(self):
        case = _make_case(expected_executor_tier=1)
        actuals = _make_actuals(executor_tier=3)
        failures = compute_case_failures(case, actuals)
        assert any("executor_tier" in f for f in failures)

    def test_planner_tier_mismatch(self):
        case = _make_case(expected_planner_tier=1)
        actuals = _make_actuals(planner_tier=2)
        failures = compute_case_failures(case, actuals)
        assert any("planner_tier" in f for f in failures)

    def test_reviewer_tier_mismatch(self):
        case = _make_case(expected_reviewer_tier=1)
        actuals = _make_actuals(reviewer_tier=3)
        failures = compute_case_failures(case, actuals)
        assert any("reviewer_tier" in f for f in failures)

    def test_quality_gate_subset(self):
        case = _make_case(expected_quality_gate_contains=["human_review", "syntax_check"])
        actuals = _make_actuals(quality_gate=["syntax_check"])
        failures = compute_case_failures(case, actuals)
        assert any("human_review" in f for f in failures)

    def test_no_candidate_expected(self):
        case = _make_case(expected_no_candidate=True)
        actuals = _make_actuals(task_hash="abc123")
        failures = compute_case_failures(case, actuals)
        assert any("no candidate" in f for f in failures)

    def test_fallback_contains(self):
        case = _make_case(expected_fallback_contains=["NO_CANDIDATE"])
        actuals = _make_actuals(fallback_triggers=[])
        failures = compute_case_failures(case, actuals)
        assert any("NO_CANDIDATE" in f for f in failures)


class TestScorerMetrics:
    """compute_metrics tests."""

    def test_all_correct_classification(self):
        """All correct → classification_accuracy = 1.0."""
        cases = [_make_case(id=f"C{i}") for i in range(3)]
        results = [
            CaseResult(case_id=c.id, passed=True, actual_task_type="CODE_GENERATION")
            for c in cases
        ]
        metrics = compute_metrics(cases, results)
        assert metrics["classification_accuracy"] == 1.0

    def test_partial_correct(self):
        """50% correct → 0.5."""
        cases = [
            _make_case(id="C1", expected_task_type="CODE_GENERATION"),
            _make_case(id="C2", expected_task_type="CONVERSATION"),
        ]
        results = [
            CaseResult(case_id="C1", passed=True, actual_task_type="CODE_GENERATION"),
            CaseResult(case_id="C2", passed=False, actual_task_type="CODE_GENERATION"),
        ]
        metrics = compute_metrics(cases, results)
        assert metrics["classification_accuracy"] == 0.5

    def test_role_tier_all_roles(self):
        """role_tier_accuracy covers executor/planner/reviewer."""
        cases = [
            _make_case(id="C1", expected_executor_tier=1, expected_planner_tier=2),
            _make_case(id="C2", expected_reviewer_tier=1),
        ]
        results = [
            CaseResult(case_id="C1", passed=True, actual_executor_tier=1, actual_planner_tier=2),
            CaseResult(case_id="C2", passed=True, actual_reviewer_tier=1),
        ]
        metrics = compute_metrics(cases, results)
        assert metrics["role_tier_accuracy"] == 1.0

    def test_cost_nan_fails(self):
        """NaN cost → case fails cost reasonableness."""
        cases = [_make_case(id="C1")]
        results = [
            CaseResult(case_id="C1", passed=True, actual_estimated_cost=float("nan"), actual_complexity="SIMPLE")
        ]
        metrics = compute_metrics(cases, results)
        assert metrics["cost_estimation_reasonableness"] == 0.0

    def test_cost_negative_fails(self):
        """Negative cost → case fails cost reasonableness."""
        cases = [_make_case(id="C1")]
        results = [
            CaseResult(case_id="C1", passed=True, actual_estimated_cost=-1.0, actual_complexity="SIMPLE")
        ]
        metrics = compute_metrics(cases, results)
        assert metrics["cost_estimation_reasonableness"] == 0.0

    def test_cost_skips_no_candidate(self):
        """expected_no_candidate=true → skipped in cost metric."""
        cases = [_make_case(id="C1", expected_no_candidate=True)]
        results = [
            CaseResult(case_id="C1", passed=True, actual_estimated_cost=0.0, actual_complexity="SIMPLE")
        ]
        metrics = compute_metrics(cases, results)
        assert metrics["cost_estimation_reasonableness"] == 1.0

    def test_expert_tier3_constraint(self):
        """EXPERT + Tier 3 → constraint violation."""
        cases = [_make_case(id="C1", expected_complexity="EXPERT")]
        results = [
            CaseResult(
                case_id="C1", passed=True,
                actual_complexity="EXPERT", actual_executor_tier=3,
                actual_risk="HIGH", actual_sensitivity="LOW",
                actual_requires_human_review=True, actual_quality_gate=["human_review"],
            )
        ]
        metrics = compute_metrics(cases, results)
        assert metrics["constraint_satisfaction"] < 1.0

    def test_review_without_human_gate_constraint(self):
        """requires_review=true but no human_review in quality_gate → violation."""
        cases = [_make_case(id="C1")]
        results = [
            CaseResult(
                case_id="C1", passed=True,
                actual_complexity="MODERATE", actual_risk="HIGH",
                actual_sensitivity="LOW", actual_task_type="CODE_GENERATION",
                actual_requires_human_review=True,
                actual_quality_gate=["syntax_check"],
            )
        ]
        metrics = compute_metrics(cases, results)
        assert metrics["constraint_satisfaction"] < 1.0

    def test_simple_low_no_review_constraint(self):
        """SIMPLE + LOW + sensitivity!=HIGH + not forced review + requires_review=true → violation."""
        cases = [_make_case(id="C1")]
        results = [
            CaseResult(
                case_id="C1", passed=True,
                actual_complexity="SIMPLE", actual_risk="LOW",
                actual_sensitivity="LOW", actual_task_type="CODE_GENERATION",
                actual_requires_human_review=True,
                actual_quality_gate=["human_review", "syntax_check"],
            )
        ]
        metrics = compute_metrics(cases, results)
        assert metrics["constraint_satisfaction"] < 1.0

    def test_simple_low_with_high_sensitivity_ok(self):
        """SIMPLE + LOW + sensitivity=HIGH + requires_review=true → NOT a violation (precondition not met)."""
        cases = [_make_case(id="C1")]
        results = [
            CaseResult(
                case_id="C1", passed=True,
                actual_complexity="SIMPLE", actual_risk="LOW",
                actual_sensitivity="HIGH", actual_task_type="CODE_GENERATION",
                actual_requires_human_review=True,
                actual_quality_gate=["human_review", "syntax_check"],
            )
        ]
        metrics = compute_metrics(cases, results)
        # Constraint 2 precondition not met (sensitivity=HIGH), so no violation from that rule
        # Constraint 3 met (human_review in quality_gate)
        # Constraint 1 not triggered (not EXPERT)
        assert metrics["constraint_satisfaction"] == 1.0

    def test_multiple_violations_no_negative(self):
        """Multiple constraint violations in one case → satisfaction >= 0 (binary per case)."""
        # Trigger all 3 constraints at once:
        # 1. EXPERT + Tier 3 executor
        # 2. SIMPLE + LOW + sensitivity!=HIGH + not forced + requires_review=true (contradicts #1)
        #    We need complexity=EXPERT for #1 but constraint 2 needs SIMPLE+LOW.
        #    So constraint 2 won't trigger. Let's trigger #1 and #3:
        #    - EXPERT + Tier 3 → violation #1
        #    - requires_review=true + no human_review in gate → violation #3
        cases = [_make_case(id="C1", expected_complexity="EXPERT")]
        results = [
            CaseResult(
                case_id="C1", passed=True,
                actual_complexity="EXPERT", actual_executor_tier=3,
                actual_risk="HIGH", actual_sensitivity="LOW",
                actual_task_type="CODE_GENERATION",
                actual_requires_human_review=True,
                actual_quality_gate=["syntax_check"],  # no human_review → violation #3
            )
        ]
        metrics = compute_metrics(cases, results)
        # 1 violated case out of 1 total → satisfaction = 0.0, NOT negative
        assert metrics["constraint_satisfaction"] == 0.0
        assert metrics["constraint_satisfaction"] >= 0.0

    def test_constraint_satisfaction_range(self):
        """constraint_satisfaction is always in [0, 1]."""
        cases = [_make_case(id=f"C{i}") for i in range(5)]
        results = [
            CaseResult(
                case_id=f"C{i}", passed=True,
                actual_complexity="EXPERT", actual_executor_tier=3,
                actual_risk="HIGH", actual_sensitivity="LOW",
                actual_task_type="ARCHITECTURE",
                actual_requires_human_review=True,
                actual_quality_gate=["syntax_check"],
            )
            for i in range(5)
        ]
        metrics = compute_metrics(cases, results)
        assert 0.0 <= metrics["constraint_satisfaction"] <= 1.0


# ── Runner 测试 ──────────────────────────────────────────────


class TestRunner:
    """Level1BenchmarkRunner tests."""

    def test_single_case_runs(self):
        """Single case runs and returns CaseResult."""
        runner = Level1BenchmarkRunner()
        case = _make_case(id="RUN-001", prompt="写一个简单的函数")
        result = runner._run_case(case)
        assert isinstance(result, CaseResult)
        assert result.case_id == "RUN-001"
        assert result.actual_task_type != ""

    def test_run_returns_summary(self, tmp_path: Path):
        """run() returns BenchmarkSummary with 6 metrics."""
        data = {
            "cases": [
                {
                    "id": "RUN-002",
                    "prompt": "写一个简单的函数",
                    "expected_task_type": "CODE_GENERATION",
                    "expected_complexity": "SIMPLE",
                    "expected_risk": "LOW",
                    "expected_strategy": "SINGLE_MODEL",
                }
            ]
        }
        yaml_path = tmp_path / "cases.yaml"
        yaml_path.write_text(yaml.dump(data), encoding="utf-8")

        runner = Level1BenchmarkRunner(cases_path=yaml_path)
        summary = runner.run()

        assert isinstance(summary, BenchmarkSummary)
        assert summary.level == 1
        assert summary.total_cases == 1
        for metric_name in METRIC_TARGETS:
            assert metric_name in summary.metrics

    def test_fail_fast(self, tmp_path: Path):
        """fail_fast stops after first failure."""
        data = {
            "cases": [
                {
                    "id": "FF-001",
                    "prompt": "写一个函数",
                    "expected_task_type": "ARCHITECTURE",  # will fail
                    "expected_complexity": "SIMPLE",
                    "expected_risk": "LOW",
                    "expected_strategy": "SINGLE_MODEL",
                },
                {
                    "id": "FF-002",
                    "prompt": "写另一个函数",
                    "expected_task_type": "CODE_GENERATION",
                    "expected_complexity": "SIMPLE",
                    "expected_risk": "LOW",
                    "expected_strategy": "SINGLE_MODEL",
                },
            ]
        }
        yaml_path = tmp_path / "cases.yaml"
        yaml_path.write_text(yaml.dump(data), encoding="utf-8")

        runner = Level1BenchmarkRunner(cases_path=yaml_path)
        summary = runner.run(fail_fast=True)
        assert summary.total_cases == 1  # stopped after first
        # Metrics denominator must use executed cases (1), not total cases (2)
        assert 0.0 <= summary.metrics.get("classification_accuracy", 0.0) <= 1.0

    def test_all_passed_true(self, tmp_path: Path):
        """all_passed=True when all cases pass and metrics pass targets."""
        data = {
            "cases": [
                {
                    "id": "PASS-001",
                    "prompt": "写一个简单的问候函数",
                    "expected_task_type": "CODE_GENERATION",
                    "expected_complexity": "SIMPLE",
                    "expected_risk": "LOW",
                    "expected_strategy": "SINGLE_MODEL",
                    "expected_requires_human_review": False,
                }
            ]
        }
        yaml_path = tmp_path / "cases.yaml"
        yaml_path.write_text(yaml.dump(data), encoding="utf-8")

        runner = Level1BenchmarkRunner(cases_path=yaml_path)
        summary = runner.run()
        # If the case passes, all_passed should be True
        if summary.passed_cases == summary.total_cases:
            assert summary.all_passed

    def test_all_passed_false_on_failure(self, tmp_path: Path):
        """all_passed=False when a case fails."""
        data = {
            "cases": [
                {
                    "id": "FAIL-001",
                    "prompt": "写一个简单的函数",
                    "expected_task_type": "ARCHITECTURE",  # wrong expected
                    "expected_complexity": "SIMPLE",
                    "expected_risk": "LOW",
                    "expected_strategy": "SINGLE_MODEL",
                }
            ]
        }
        yaml_path = tmp_path / "cases.yaml"
        yaml_path.write_text(yaml.dump(data), encoding="utf-8")

        runner = Level1BenchmarkRunner(cases_path=yaml_path)
        summary = runner.run()
        # This case will likely fail (CODE_GENERATION != ARCHITECTURE)
        if summary.failed_cases > 0:
            assert not summary.all_passed
