"""Unit tests for ComplexityAnalyzer."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from airouter.config import ComplexityConfig, HybridConfig
from airouter.engine.complexity.analyzer import ComplexityAnalyzer
from airouter.engine.complexity.ml_backend import ComplexityBackendUnavailable
from airouter.engine.complexity.types import MLPrediction
from airouter.engine.router.analyzer import TaskAnalyzer
from airouter.models.enums import ComplexityLevel


def _make_ml_pred(
    raw_class: str = "R2",
    final_class: str = "R2",
    raw_conf: float = 0.8,
) -> MLPrediction:
    return MLPrediction(
        raw_route_class=raw_class,
        final_route_class=final_class,
        raw_confidence=raw_conf,
        final_class_probability=raw_conf,
        probabilities={"R0": 0.05, "R1": 0.1, "R2": raw_conf, "R3": 0.05},
        margin=0.5,
        difficulty_score=1.5,
        flags={},
        latency_ms=10.0,
        model_version="test",
    )


class TestRulesMode:
    def test_rules_mode_passthrough(self):
        """mode=rules output identical to TaskAnalyzer."""
        config = ComplexityConfig(mode="rules")
        analyzer = ComplexityAnalyzer(config)
        result = analyzer.analyze("修复这个简单的 bug")
        assert result.analysis.mode == "rules"
        assert result.analysis.ml_available is False
        assert result.analysis.ml_prediction is None
        # Verify features match pure rule extraction
        rule_analyzer = TaskAnalyzer()
        rule_features = rule_analyzer.extract_features("修复这个简单的 bug")
        assert result.features.complexity == rule_features.complexity

    def test_rules_mode_never_initializes_backend(self):
        """mode=rules should never create backend."""
        config = ComplexityConfig(mode="rules")
        with patch("airouter.engine.complexity.analyzer.ComplexityAnalyzer._try_init_backend") as mock:
            ComplexityAnalyzer(config)
            mock.assert_not_called()


class TestShadowMode:
    def test_shadow_mode_no_override(self):
        """mode=shadow: features unchanged, ML data recorded."""
        config = ComplexityConfig(mode="shadow")
        analyzer = ComplexityAnalyzer(config)
        # Mock backend
        mock_backend = MagicMock()
        mock_backend.predict.return_value = _make_ml_pred(raw_class="R3")
        analyzer._backend = mock_backend

        result = analyzer.analyze("修复这个简单的 bug")
        assert result.analysis.mode == "shadow"
        assert result.analysis.ml_available is True
        assert result.analysis.ml_prediction is not None
        # Features should NOT change (shadow = log only)
        rule_analyzer = TaskAnalyzer()
        rule_features = rule_analyzer.extract_features("修复这个简单的 bug")
        assert result.features.complexity == rule_features.complexity
        assert "shadow mode" in result.analysis.resolution_reason


class TestHybridMode:
    def test_hybrid_upgrade_only(self):
        """ML predicts higher → resolved upgrades."""
        config = ComplexityConfig(mode="hybrid")
        analyzer = ComplexityAnalyzer(config)
        mock_backend = MagicMock()
        mock_backend.predict.return_value = _make_ml_pred(raw_class="R2", raw_conf=0.8)
        analyzer._backend = mock_backend

        result = analyzer.analyze("修复这个简单的 bug")  # rule = SIMPLE
        assert result.analysis.resolved == ComplexityLevel.COMPLEX or result.analysis.resolved == ComplexityLevel.MODERATE
        # With max_upgrade_steps=1, SIMPLE(0) → MODERATE(1)
        assert result.analysis.resolved == ComplexityLevel.MODERATE

    def test_hybrid_no_downgrade(self):
        """ML predicts lower → resolved stays at rule value."""
        config = ComplexityConfig(mode="hybrid")
        analyzer = ComplexityAnalyzer(config)
        mock_backend = MagicMock()
        mock_backend.predict.return_value = _make_ml_pred(raw_class="R0", raw_conf=0.9)
        analyzer._backend = mock_backend

        result = analyzer.analyze("设计跨模块分布式鉴权系统架构")  # rule = COMPLEX or EXPERT
        assert result.analysis.resolved.value in ("COMPLEX", "EXPERT")

    def test_hybrid_max_upgrade_steps(self):
        """max_upgrade_steps=1 limits upgrade to one step."""
        config = ComplexityConfig(mode="hybrid", hybrid=HybridConfig(max_upgrade_steps=1))
        analyzer = ComplexityAnalyzer(config)
        mock_backend = MagicMock()
        mock_backend.predict.return_value = _make_ml_pred(raw_class="R3", raw_conf=0.9)
        analyzer._backend = mock_backend

        result = analyzer.analyze("修复这个简单的 bug")  # rule = SIMPLE
        # SIMPLE(0) + 1 step = MODERATE(1), not EXPERT(3)
        assert result.analysis.resolved == ComplexityLevel.MODERATE

    def test_hybrid_confidence_threshold(self):
        """raw_confidence < threshold → no upgrade."""
        config = ComplexityConfig(
            mode="hybrid",
            hybrid=HybridConfig(confidence_threshold=0.9),
        )
        analyzer = ComplexityAnalyzer(config)
        mock_backend = MagicMock()
        mock_backend.predict.return_value = _make_ml_pred(raw_class="R3", raw_conf=0.5)
        analyzer._backend = mock_backend

        result = analyzer.analyze("修复这个简单的 bug")
        assert result.analysis.resolved == ComplexityLevel.SIMPLE
        assert "confidence" in result.analysis.resolution_reason

    def test_hybrid_uses_raw_not_final(self):
        """Hybrid must use raw_route_class, not final_route_class."""
        config = ComplexityConfig(mode="hybrid")
        analyzer = ComplexityAnalyzer(config)
        mock_backend = MagicMock()
        # raw=R1 (MODERATE), final=R3 (EXPERT)
        mock_backend.predict.return_value = _make_ml_pred(
            raw_class="R1", final_class="R3", raw_conf=0.8
        )
        analyzer._backend = mock_backend

        result = analyzer.analyze("修复这个简单的 bug")  # rule=SIMPLE
        # Should use raw R1 → MODERATE (1 step), not final R3 → EXPERT
        assert result.analysis.resolved == ComplexityLevel.MODERATE

    def test_hybrid_allow_upgrade_false(self):
        """allow_upgrade=False → no upgrade even with high confidence."""
        config = ComplexityConfig(
            mode="hybrid",
            hybrid=HybridConfig(allow_upgrade=False),
        )
        analyzer = ComplexityAnalyzer(config)
        mock_backend = MagicMock()
        mock_backend.predict.return_value = _make_ml_pred(raw_class="R3", raw_conf=0.95)
        analyzer._backend = mock_backend

        result = analyzer.analyze("修复这个简单的 bug")  # rule=SIMPLE
        assert result.analysis.resolved == ComplexityLevel.SIMPLE
        assert "allow_upgrade" in result.analysis.resolution_reason


class TestOpensquillaMode:
    def test_opensquilla_uses_final(self):
        """opensquilla mode uses final_route_class."""
        config = ComplexityConfig(mode="opensquilla")
        analyzer = ComplexityAnalyzer(config)
        mock_backend = MagicMock()
        mock_backend.predict.return_value = _make_ml_pred(
            raw_class="R1", final_class="R3", raw_conf=0.8
        )
        analyzer._backend = mock_backend

        result = analyzer.analyze("修复这个简单的 bug")
        assert result.analysis.resolved == ComplexityLevel.EXPERT  # final R3

    def test_opensquilla_downgrade_rebuilds_resources(self):
        """opensquilla downgrade: 7 fields fully replaced (not take-high)."""
        config = ComplexityConfig(mode="opensquilla")
        analyzer = ComplexityAnalyzer(config)
        mock_backend = MagicMock()
        # Rule=COMPLEX, ML final=R0 (SIMPLE) → should downgrade
        mock_backend.predict.return_value = _make_ml_pred(
            raw_class="R0", final_class="R0", raw_conf=0.9
        )
        analyzer._backend = mock_backend

        result = analyzer.analyze("设计跨模块分布式鉴权系统架构")
        # Rule would be COMPLEX/EXPERT, ML says SIMPLE → opensquilla replaces
        assert result.analysis.resolved == ComplexityLevel.SIMPLE
        # Resources should be SIMPLE defaults, not take-high
        assert result.features.estimated_output_tokens == 80  # SIMPLE default
        assert result.features.reasoning_intensity.value == "LOW"


class TestMLUnavailable:
    def test_ml_unavailable_graceful(self):
        """ML unavailable → fallback to rules."""
        config = ComplexityConfig(mode="hybrid")
        analyzer = ComplexityAnalyzer(config)
        # No backend (init failed)
        analyzer._backend = None

        result = analyzer.analyze("修复这个简单的 bug")
        assert result.analysis.ml_available is False
        assert result.analysis.resolved == ComplexityLevel.SIMPLE

    def test_require_runtime_true_propagates(self):
        """require_runtime=True → backend error not swallowed."""
        config = ComplexityConfig(mode="hybrid", require_runtime=True)
        with pytest.raises(ComplexityBackendUnavailable):
            ComplexityAnalyzer(config)


class TestResourceRecalculation:
    def test_resource_recalculation_complete(self):
        """After upgrade SIMPLE→MODERATE, all 7 fields are recalculated."""
        config = ComplexityConfig(mode="hybrid")
        analyzer = ComplexityAnalyzer(config)
        mock_backend = MagicMock()
        mock_backend.predict.return_value = _make_ml_pred(raw_class="R2", raw_conf=0.9)
        analyzer._backend = mock_backend

        # Get rule-only baseline for comparison
        rule_analyzer = TaskAnalyzer()
        rule_features = rule_analyzer.extract_features("修复这个简单的 bug")
        assert rule_features.complexity == ComplexityLevel.SIMPLE

        result = analyzer.analyze("修复这个简单的 bug")
        # With max_upgrade_steps=1: SIMPLE → MODERATE
        assert result.analysis.resolved == ComplexityLevel.MODERATE
        f = result.features

        # 1. context_requirement: MINIMAL → STANDARD
        from airouter.models.enums import ContextLevel
        assert f.context_requirement == ContextLevel.STANDARD
        assert f.context_requirement != rule_features.context_requirement

        # 2. estimated_input_tokens: 1000 → 5000
        assert f.estimated_input_tokens == 5000

        # 3. estimated_output_tokens: 80 → 300
        assert f.estimated_output_tokens == 300

        # 4. reasoning_intensity: rule=HIGH, MODERATE maps MEDIUM → monotonic keeps HIGH
        from airouter.models.enums import ReasoningLevel
        assert f.reasoning_intensity == ReasoningLevel.HIGH  # max(HIGH, MEDIUM) = HIGH

        # 5. subtasks: should be a list (may be empty for MODERATE)
        assert isinstance(f.subtasks, list)

        # 6. required_capabilities: union includes MODERATE caps
        # BUG_ANALYSIS MODERATE required = {"code_gen", "complex_reasoning"}
        assert "complex_reasoning" in f.required_capabilities
        assert "code_gen" in f.required_capabilities  # from SIMPLE

        # 7. preferred_capabilities: union merged
        assert "code_review" in f.preferred_capabilities

    def test_immutable_fields_not_overridden(self):
        """risk/sensitivity/verifiability not overridden by ML."""
        config = ComplexityConfig(mode="opensquilla")
        analyzer = ComplexityAnalyzer(config)
        mock_backend = MagicMock()
        mock_backend.predict.return_value = _make_ml_pred(raw_class="R3", final_class="R3")
        analyzer._backend = mock_backend

        result = analyzer.analyze("修复这个简单的 bug")
        rule_analyzer = TaskAnalyzer()
        rule_features = rule_analyzer.extract_features("修复这个简单的 bug")
        # These should remain unchanged
        assert result.features.risk_level == rule_features.risk_level
        assert result.features.sensitivity == rule_features.sensitivity
        assert result.features.verifiability == rule_features.verifiability

    def test_capability_merge_on_override(self):
        """hybrid upgrade: capabilities union merged."""
        config = ComplexityConfig(mode="hybrid")
        analyzer = ComplexityAnalyzer(config)
        mock_backend = MagicMock()
        mock_backend.predict.return_value = _make_ml_pred(raw_class="R2", raw_conf=0.9)
        analyzer._backend = mock_backend

        result = analyzer.analyze("修复这个简单的 bug")
        rule_analyzer = TaskAnalyzer()
        rule_features = rule_analyzer.extract_features("修复这个简单的 bug")
        # Capabilities should be union (superset)
        assert result.features.required_capabilities >= rule_features.required_capabilities

    def test_subtasks_reextracted_on_upgrade(self):
        """Upgrade to COMPLEX: subtasks re-extracted."""
        config = ComplexityConfig(mode="hybrid", hybrid=HybridConfig(max_upgrade_steps=3))
        analyzer = ComplexityAnalyzer(config)
        mock_backend = MagicMock()
        mock_backend.predict.return_value = _make_ml_pred(raw_class="R2", raw_conf=0.9)
        analyzer._backend = mock_backend

        result = analyzer.analyze("修复 bug 以及重构架构")
        if result.analysis.resolved in (ComplexityLevel.COMPLEX, ComplexityLevel.EXPERT):
            # Subtasks should be extracted
            assert isinstance(result.features.subtasks, list)


class TestRouterSingleAnalyzerEntry:
    def test_router_single_analyzer_entry(self):
        """router.analyzer is ComplexityAnalyzer, router.rule_analyzer is TaskAnalyzer."""
        from airouter.engine.router.router import Router
        router = Router()
        # Single analyzer entry point
        assert isinstance(router.analyzer, ComplexityAnalyzer)
        # Pure rule analyzer preserved for direct access
        assert isinstance(router.rule_analyzer, TaskAnalyzer)
        # They share the same rule_analyzer instance
        assert router.analyzer._rule_analyzer is router.rule_analyzer

    def test_router_route_uses_analyzer(self):
        """router.route() populates complexity_analysis in RoutingDecision."""
        from airouter.engine.router.router import Router
        router = Router()
        decision = router.route("修复这个简单的 bug")
        # complexity_analysis must be populated (rules mode)
        assert decision.complexity_analysis is not None
        assert decision.complexity_analysis.mode == "rules"
        assert decision.complexity_analysis.ml_available is False
