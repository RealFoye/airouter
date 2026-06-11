"""Integration tests for OpenSquilla runtime.

Requires real bundle + ML dependencies. Tests are skipped if unavailable.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

BUNDLE_DIR = os.environ.get("AIROUTER_OPENSQUILLA_BUNDLE_DIR", "")
_skip_reason = ""
if not BUNDLE_DIR:
    _skip_reason = "AIROUTER_OPENSQUILLA_BUNDLE_DIR not set"
elif not Path(BUNDLE_DIR).exists():
    _skip_reason = f"bundle not found: {BUNDLE_DIR}"

try:
    import lightgbm  # noqa: F401
    import onnxruntime  # noqa: F401
except ImportError:
    _skip_reason = "ML dependencies not installed (pip install airouter[ml])"

skip_no_bundle = pytest.mark.skipif(
    bool(_skip_reason),
    reason=_skip_reason,
)


@skip_no_bundle
class TestRealBundle:
    """Real bundle integration tests (skipped without bundle/deps)."""

    def test_real_bundle_verifies(self):
        """Real bundle passes artifact verification."""
        from airouter.engine.complexity.artifact_verifier import ArtifactVerifier
        verifier = ArtifactVerifier(Path(BUNDLE_DIR))
        verifier.verify_all()

    def test_real_bundle_predict(self):
        """Real inference produces valid MLPrediction."""
        from airouter.engine.complexity.ml_backend import OpenSquillaBackend
        backend = OpenSquillaBackend(Path(BUNDLE_DIR))
        assert backend.available
        pred = backend.predict("设计一个分布式微服务架构")
        assert pred.raw_route_class in ("R0", "R1", "R2", "R3")
        assert pred.final_route_class in ("R0", "R1", "R2", "R3")
        assert 0.0 <= pred.raw_confidence <= 1.0
        assert pred.probabilities
        assert pred.model_version != "unknown"

    def test_real_bundle_cold_start_timing(self):
        """First load timing is recorded."""
        from airouter.engine.complexity.ml_backend import OpenSquillaBackend, reset_backend
        reset_backend()
        backend = OpenSquillaBackend(Path(BUNDLE_DIR))
        pred = backend.predict("写一个简单的函数")
        assert pred.cold_start_ms is not None
        assert pred.cold_start_ms > 0
        reset_backend()
