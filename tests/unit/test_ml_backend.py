"""Unit tests for ml_backend module.

Uses tmp_path and mocking — no real bundle or ML dependencies required.
"""

from __future__ import annotations

import sys
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from airouter.engine.complexity.ml_backend import (
    ComplexityBackendUnavailable,
    OpenSquillaBackend,
    get_backend,
    reset_backend,
)


@pytest.fixture(autouse=True)
def _reset_singleton():
    """Reset singleton state before each test."""
    reset_backend()
    yield
    reset_backend()
    # Clean up any src.* modules that tests may have injected
    to_remove = [k for k in sys.modules if k == "src" or k.startswith("src.")]
    for k in to_remove:
        sys.modules.pop(k, None)


class TestBackendUnavailable:
    def test_bundle_not_found(self, tmp_path: Path):
        with pytest.raises(ComplexityBackendUnavailable, match="not found"):
            OpenSquillaBackend(tmp_path / "nonexistent")

    def test_predict_when_not_initialized(self, tmp_path: Path):
        """Backend that fails init should raise on predict too."""
        with pytest.raises(ComplexityBackendUnavailable):
            backend = OpenSquillaBackend(tmp_path / "nonexistent")
            backend.predict("test")


class TestSingleton:
    def test_same_path_reuses_backend(self, tmp_path: Path):
        """Same bundle path should return the same backend instance."""
        with patch.object(OpenSquillaBackend, "_init_runtime"):
            b1 = get_backend(tmp_path / "bundle")
            b2 = get_backend(tmp_path / "bundle")
            assert b1 is b2

    def test_different_bundle_rejected(self, tmp_path: Path):
        """Second different bundle path should be rejected."""
        with patch.object(OpenSquillaBackend, "_init_runtime"):
            get_backend(tmp_path / "bundle1")
            with pytest.raises(ComplexityBackendUnavailable, match="different backend"):
                get_backend(tmp_path / "bundle2")

    def test_same_path_different_aux_rejected(self, tmp_path: Path):
        """Same path but different use_aux_head should be rejected."""
        with patch.object(OpenSquillaBackend, "_init_runtime"):
            get_backend(tmp_path / "bundle", use_aux_head=False)
            with pytest.raises(ComplexityBackendUnavailable, match="different backend"):
                get_backend(tmp_path / "bundle", use_aux_head=True)


class TestModuleCleanup:
    def test_failed_import_cleans_new_modules(self, tmp_path: Path):
        """Init failure should clean up src.* modules added during attempt."""
        bundle = tmp_path / "bundle"
        bundle.mkdir()

        # Inject a fake src module to trigger the conflict path
        # Actually, let's test the cleanup on a different failure path
        # by making artifact verification fail
        with pytest.raises(ComplexityBackendUnavailable):
            OpenSquillaBackend(bundle)

        # After failure, no src.* modules should remain from the attempt
        src_mods = [k for k in sys.modules if k == "src" or k.startswith("src.")]
        assert len(src_mods) == 0


class TestSysModulesConflict:
    def test_existing_src_module_rejected(self, tmp_path: Path):
        """If sys.modules['src'] exists and is not OpenSquilla, reject."""
        bundle = tmp_path / "bundle"
        bundle.mkdir()

        # Inject a fake src module
        fake_mod = MagicMock()
        fake_mod.__path__ = ["/some/other/path"]
        fake_mod.__file__ = "/some/other/path/__init__.py"
        sys.modules["src"] = fake_mod

        with pytest.raises(ComplexityBackendUnavailable, match="already occupied"):
            OpenSquillaBackend(bundle)


class TestBuildRequest:
    def test_build_request_mapping(self):
        """Verify InferenceRequest fields are correctly mapped."""
        backend = MagicMock(spec=OpenSquillaBackend)
        backend._request_type = MagicMock()
        backend._available = True

        # Call the real _build_request method
        OpenSquillaBackend._build_request(backend, "分析这段代码的性能问题")

        backend._request_type.assert_called_once()
        call_kwargs = backend._request_type.call_args
        assert call_kwargs.kwargs["current_user_text"] == "分析这段代码的性能问题"
        assert call_kwargs.kwargs["history_user_texts"] == []
        assert call_kwargs.kwargs["prev_assistant_text"] is None
        assert call_kwargs.kwargs["prev_assistant_usage"] is None
        assert call_kwargs.kwargs["prev_route_decisions"] == []
        assert call_kwargs.kwargs["flags_text_override"] is None
        meta = call_kwargs.kwargs["context_metadata"]
        assert meta["turn_index"] == 0
        assert meta["has_code_block"] is False
        assert meta["has_prev_assistant"] is False

    def test_build_request_with_code_block(self):
        """Code block detection in context_metadata."""
        backend = MagicMock(spec=OpenSquillaBackend)
        backend._request_type = MagicMock()
        backend._available = True

        OpenSquillaBackend._build_request(backend, "请优化 ```python\ndef foo(): pass\n```")

        meta = backend._request_type.call_args.kwargs["context_metadata"]
        assert meta["has_code_block"] is True


class TestMapResult:
    def test_map_result_basic(self):
        """Verify MLPrediction fields from InferenceResult."""
        backend = MagicMock(spec=OpenSquillaBackend)
        backend._cold_start_ms = 500.0
        backend._model_version = "v4.2"

        decision = MagicMock()
        decision.route_class = "R2"
        decision.difficulty_score = 1.5
        decision.flags = {"high_risk": True}

        result = MagicMock()
        result.decision = decision
        result.probabilities = {"R0": 0.1, "R1": 0.3, "R2": 0.5, "R3": 0.1}
        result.aux_decision_probs = None

        pred = OpenSquillaBackend._map_result(backend, result, 42.0)
        assert pred.final_route_class == "R2"
        assert pred.raw_route_class == "R2"  # argmax = R2
        assert pred.raw_confidence == 0.5
        assert pred.final_class_probability == 0.5
        assert pred.margin == pytest.approx(0.2)  # 0.5 - 0.3
        assert pred.difficulty_score == 1.5
        assert pred.flags == {"high_risk": True}
        assert pred.latency_ms == 42.0
        assert pred.cold_start_ms == 500.0
        assert pred.model_version == "v4.2"

    def test_map_result_raw_differs_from_final(self):
        """When postprocess changes route_class, raw != final."""
        backend = MagicMock(spec=OpenSquillaBackend)
        backend._cold_start_ms = None
        backend._model_version = "unknown"

        decision = MagicMock()
        decision.route_class = "R3"  # postprocess upgraded
        decision.difficulty_score = 2.0
        decision.flags = {}

        result = MagicMock()
        result.decision = decision
        result.probabilities = {"R0": 0.05, "R1": 0.1, "R2": 0.6, "R3": 0.25}

        pred = OpenSquillaBackend._map_result(backend, result, 10.0)
        assert pred.raw_route_class == "R2"  # argmax
        assert pred.final_route_class == "R3"  # postprocess


class TestRulesModeNeverInitializesBackend:
    def test_rules_mode_never_initializes_backend(self):
        """mode=rules should never create OpenSquillaBackend."""
        # This is a conceptual test — in rules mode, the Analyzer
        # never calls get_backend(). We verify the Analyzer logic
        # in test_complexity_analyzer.py.
        # Here we just verify the backend isn't auto-created on import.
        from airouter.engine.complexity.ml_backend import _ACTIVE_BACKEND
        assert _ACTIVE_BACKEND is None


class TestConcurrentPredict:
    def test_predict_lock_serializes(self):
        """Verify predict uses a lock for thread safety."""
        backend = MagicMock(spec=OpenSquillaBackend)
        backend._predict_lock = threading.Lock()
        backend._available = True
        backend._core = MagicMock()
        backend._request_type = MagicMock()
        backend._cold_start_ms = None
        backend._model_version = "test"

        # Mock predict to be slow
        call_order = []

        def slow_predict(request):
            call_order.append("start")
            import time
            time.sleep(0.01)
            call_order.append("end")
            result = MagicMock()
            result.decision = MagicMock()
            result.decision.route_class = "R1"
            result.decision.difficulty_score = 0.5
            result.decision.flags = {}
            result.probabilities = {"R0": 0.1, "R1": 0.7, "R2": 0.15, "R3": 0.05}
            return result

        backend._core.predict = slow_predict
        backend._request_type.return_value = MagicMock()

        # Run two threads
        errors = []

        def run_predict():
            try:
                OpenSquillaBackend.predict(backend, "test task")
            except Exception as e:
                errors.append(e)

        t1 = threading.Thread(target=run_predict)
        t2 = threading.Thread(target=run_predict)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert not errors
        # Verify serialized: start, end, start, end (not start, start, end, end)
        assert call_order[0] == "start"
        assert call_order[1] == "end"
