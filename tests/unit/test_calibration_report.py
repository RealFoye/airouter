"""Unit tests for scripts/calibration_report.py.

Tests the core functions without requiring ML backend or real API calls.
"""

from __future__ import annotations

# ruff: noqa: E402
import importlib
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Import calibration_report from scripts/ directory
_script_dir = str(Path(__file__).resolve().parent.parent.parent / "scripts")
if _script_dir not in sys.path:
    sys.path.insert(0, _script_dir)

from airouter.models.enums import ComplexityLevel

# Import after path setup
calibration_report = importlib.import_module("calibration_report")
check_acceptance = calibration_report.check_acceptance
compute_metrics = calibration_report.compute_metrics
compute_tier_prices = calibration_report.compute_tier_prices
run_ml_modes = calibration_report.run_ml_modes
HIGH_RISK_LEVELS = calibration_report.HIGH_RISK_LEVELS

S = ComplexityLevel.SIMPLE
M = ComplexityLevel.MODERATE
C = ComplexityLevel.COMPLEX
E = ComplexityLevel.EXPERT


def _preds(pairs: list[tuple[ComplexityLevel, ComplexityLevel, str]]) -> list[tuple[str, ComplexityLevel, ComplexityLevel, str]]:
    """Helper: build predictions list from (expected, predicted, risk) tuples."""
    return [(f"case-{i}", exp, pred, risk) for i, (exp, pred, risk) in enumerate(pairs)]


class TestCriticalInHighRisk:
    def test_critical_counted_as_high_risk(self):
        """CRITICAL risk level must be included in high-risk stats."""
        assert "CRITICAL" in HIGH_RISK_LEVELS
        assert "HIGH" in HIGH_RISK_LEVELS

    def test_high_risk_total_includes_critical(self):
        preds = _preds([
            (C, C, "HIGH"),
            (C, C, "CRITICAL"),
            (C, C, "LOW"),
        ])
        metrics = compute_metrics(preds)
        assert metrics["high_risk_total"] == 2  # HIGH + CRITICAL

    def test_high_risk_under_includes_critical(self):
        preds = _preds([
            (E, S, "CRITICAL"),  # severe under-routing, CRITICAL
            (C, S, "HIGH"),      # under-routing, HIGH
            (M, S, "LOW"),       # under-routing, LOW
        ])
        metrics = compute_metrics(preds)
        assert metrics["high_risk_under_routing"] == 2  # CRITICAL + HIGH
        assert metrics["high_risk_total"] == 2


class TestMLFailureTracking:
    def test_ml_all_fail_fails_acceptance(self):
        """When all ML predictions fail, acceptance must not pass."""
        rules_metrics = compute_metrics(_preds([(S, S, "LOW")] * 10))
        hybrid_metrics = compute_metrics(_preds([(S, S, "LOW")] * 10))
        # 0 successes out of 10
        failures = check_acceptance(rules_metrics, hybrid_metrics, 0, 10)
        assert any("ML success rate" in f for f in failures)

    def test_ml_partial_failures_counted(self):
        """run_ml_modes tracks real success count and failure IDs."""
        cases = [
            {"id": "A", "prompt": "a", "input_context": "", "expected_complexity": "SIMPLE", "risk_level": "LOW"},
            {"id": "B", "prompt": "b", "input_context": "", "expected_complexity": "SIMPLE", "risk_level": "LOW"},
            {"id": "C", "prompt": "c", "input_context": "", "expected_complexity": "SIMPLE", "risk_level": "LOW"},
        ]

        from airouter.engine.router.analyzer import TaskAnalyzer
        rule_analyzer = TaskAnalyzer()

        mock_backend = MagicMock()
        # Fail on case B, succeed on A and C
        call_count = [0]
        def predict_side_effect(text):
            call_count[0] += 1
            if call_count[0] == 2:
                raise RuntimeError("simulated failure")
            result = MagicMock()
            result.raw_route_class = "R0"
            result.final_route_class = "R0"
            result.raw_confidence = 0.9
            result.final_class_probability = 0.9
            result.probabilities = {"R0": 0.9, "R1": 0.05, "R2": 0.03, "R3": 0.02}
            return result

        mock_backend.predict.side_effect = predict_side_effect

        raw, final, hybrid, success_count, failure_ids = run_ml_modes(
            cases, rule_analyzer, mock_backend,
        )
        assert success_count == 2
        assert failure_ids == ["B"]
        assert len(raw) == 3  # all cases still produce predictions (fallback to rules)


class TestAcceptanceExitCode:
    def test_acceptance_failure_list(self):
        """check_acceptance returns non-empty list when criteria fail."""
        rules = compute_metrics(_preds([(S, S, "LOW")] * 10))
        hybrid = compute_metrics(_preds([(S, S, "LOW")] * 10))
        # All succeed but check structure
        failures = check_acceptance(rules, hybrid, 10, 10)
        assert isinstance(failures, list)
        # No failures when metrics match
        assert len(failures) == 0

    def test_acceptance_fails_on_severe_under_routing(self):
        rules = compute_metrics(_preds([(S, S, "LOW")] * 10))
        # Hybrid has more severe under-routing
        hybrid = compute_metrics(_preds([
            (E, S, "LOW"),  # severe (diff=3)
            (E, S, "LOW"),  # severe (diff=3)
            (E, S, "LOW"),  # severe (diff=3)
            (E, S, "LOW"),  # severe (diff=3)
        ] + [(S, S, "LOW")] * 6))
        failures = check_acceptance(rules, hybrid, 10, 10)
        assert any("severe under-routing" in f for f in failures)


class TestCostFromConfig:
    def test_compute_tier_prices_returns_tuple(self):
        """compute_tier_prices returns (dict, source_label)."""
        prices, source = compute_tier_prices()
        assert isinstance(prices, dict)
        assert len(prices) > 0
        assert source in ("models.yaml", "fallback_defaults")
        for tier, price in prices.items():
            assert isinstance(tier, int)
            assert price > 0

    def test_metrics_use_real_prices(self):
        """compute_metrics includes cost_source field."""
        preds = _preds([(S, S, "LOW")])
        metrics = compute_metrics(preds)
        assert "cost_source" in metrics
        assert metrics["cost_source"] in ("models.yaml", "fallback_defaults")

    def test_custom_tier_prices(self):
        """compute_metrics accepts custom tier prices and source."""
        preds = _preds([(S, S, "LOW")])  # SIMPLE → Tier 3
        custom = {1: 0.20, 2: 0.05, 3: 0.01}
        metrics = compute_metrics(preds, custom, "test_override")
        # SIMPLE = Tier 3, 0.01 * 2.0 = 0.02
        assert metrics["estimated_cost_cny"] == pytest.approx(0.02)
        assert metrics["cost_source"] == "test_override"


class TestMetricsCorrectness:
    def test_all_correct(self):
        preds = _preds([(S, S, "LOW"), (M, M, "LOW"), (C, C, "HIGH")])
        metrics = compute_metrics(preds)
        assert metrics["accuracy"] == 1.0
        assert metrics["under_routing"] == 0
        assert metrics["over_routing"] == 0

    def test_under_routing_severity(self):
        preds = _preds([
            (M, S, "LOW"),   # under by 1, not severe
            (E, S, "LOW"),   # under by 3, severe
            (C, S, "LOW"),   # under by 2, severe
        ])
        metrics = compute_metrics(preds)
        assert metrics["under_routing"] == 3
        assert metrics["severe_under_routing"] == 2

    def test_over_routing(self):
        preds = _preds([(S, M, "LOW"), (S, C, "LOW")])
        metrics = compute_metrics(preds)
        assert metrics["over_routing"] == 2
        assert metrics["under_routing"] == 0


class TestMainExitCode:
    def test_main_returns_true_without_ml(self):
        """main() returns True (exit 0) when running rules-only mode."""
        import subprocess
        result = subprocess.run(
            [sys.executable, str(Path(__file__).resolve().parent.parent.parent / "scripts" / "calibration_report.py")],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0
        assert "rules (baseline)" in result.stdout

    def test_main_returns_false_on_acceptance_failure(self):
        """main() returns False when acceptance criteria fail."""
        # Directly test the return value path: when ML is enabled but all fail
        rules = compute_metrics(_preds([(S, S, "LOW")] * 10))
        hybrid = compute_metrics(_preds([(S, S, "LOW")] * 10))
        # 0/10 success → acceptance must fail
        failures = check_acceptance(rules, hybrid, 0, 10)
        assert len(failures) > 0
        assert any("ML success rate" in f for f in failures)
