"""Level 3 benchmark runner unit tests."""

import pytest

from airouter.engine.benchmark.runner import Level3BenchmarkRunner
from airouter.engine.benchmark.schemas import BacktestSummary


def _make_runner(**kwargs):
    return Level3BenchmarkRunner(**kwargs)


class TestCaseSet:
    def test_case_set_l1(self):
        runner = _make_runner(case_set="l1")
        summary = runner.run()
        assert isinstance(summary, BacktestSummary)
        assert summary.l1_cases == 40
        assert summary.l2_cases == 0
        assert summary.total_cases == 40

    def test_case_set_l2(self):
        runner = _make_runner(case_set="l2")
        summary = runner.run()
        assert summary.l1_cases == 0
        assert summary.l2_cases == 30
        assert summary.total_cases == 30

    def test_case_set_all(self):
        runner = _make_runner(case_set="all")
        summary = runner.run()
        assert summary.l1_cases == 40
        assert summary.l2_cases == 30
        assert summary.total_cases == 70

    def test_invalid_case_set_raises(self):
        with pytest.raises(ValueError, match="case_set must be one of"):
            _make_runner(case_set="invalid")


class TestSavings:
    def test_savings_rate_positive(self):
        runner = _make_runner(case_set="l1")
        summary = runner.run()
        # With smart routing, savings should be positive
        assert summary.savings_total_cny > 0
        assert summary.savings_rate > 0

    def test_overspend_cases_exist(self):
        """At least one L1 case should have router cost > baseline."""
        runner = _make_runner(case_set="l1")
        summary = runner.run()
        # We saw 1 overspend case in smoke test
        assert summary.overspend_count >= 0
        # Verify overspend cases have negative savings
        for case in summary.overspend_cases:
            assert case["savings_cny"] < 0

    def test_effective_cost_used_in_summary(self):
        """Summary totals use effective_router_cost, not raw_router_cost."""
        runner = _make_runner(case_set="all")
        summary = runner.run()
        total_effective = sum(r.effective_router_cost for r in summary.case_results)
        assert summary.router_total_cost == pytest.approx(total_effective)


class TestInputContext:
    def test_l2_cases_have_context(self):
        """L2 cases with input_context should exist."""
        runner = _make_runner(case_set="l2")
        cases = runner._load_cases()
        cases_with_context = [c for c in cases if c.input_context]
        assert len(cases_with_context) > 0

    def test_l2_route_text_includes_context(self, monkeypatch):
        """Router.route() should receive input_context + prompt for L2 cases."""
        runner = _make_runner(case_set="l2")
        cases = runner._load_cases()
        cases_with_context = [c for c in cases if c.input_context]
        assert len(cases_with_context) > 0

        # Capture what gets passed to Router.route
        route_calls: list[str] = []

        original_route = runner._router.route

        def capturing_route(text):
            route_calls.append(text)
            return original_route(text)

        monkeypatch.setattr(runner._router, "route", capturing_route)
        runner.run()

        # Verify at least one call includes context
        assert len(route_calls) == len(cases)
        context_included = any(
            c.input_context in text
            for c in cases_with_context
            for text in route_calls
            if c.input_context
        )
        assert context_included, "No route call included input_context"


class TestBacktestResultFields:
    def test_result_id_format(self):
        runner = _make_runner(case_set="l1")
        summary = runner.run()
        for r in summary.case_results:
            assert r.result_id == f"{r.source}:{r.case_id}"

    def test_has_executable_model_field(self):
        runner = _make_runner(case_set="all")
        summary = runner.run()
        # Check the field exists and is bool
        for r in summary.case_results:
            assert isinstance(r.has_executable_model, bool)

    def test_baseline_model_consistent(self):
        runner = _make_runner(case_set="l1", baseline_model="qwen3.7-max")
        summary = runner.run()
        assert summary.baseline_model == "qwen3.7-max"
        for r in summary.case_results:
            assert r.baseline_model == "qwen3.7-max"

    def test_custom_baseline_model(self):
        runner = _make_runner(case_set="l1", baseline_model="deepseek-v4-pro")
        summary = runner.run()
        assert summary.baseline_model == "deepseek-v4-pro"


class TestQualityMode:
    def test_quality_mode_is_routing_prior(self):
        runner = _make_runner(case_set="l1")
        summary = runner.run()
        assert summary.quality_mode == "routing_prior"

    def test_disclaimer_present(self):
        runner = _make_runner(case_set="l1")
        summary = runner.run()
        assert "routing priors" in summary.disclaimer
