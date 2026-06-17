"""Unit tests for ground_truth_loader.py."""

from __future__ import annotations

from pathlib import Path

import pytest

from airouter.engine.benchmark.ground_truth_loader import (
    compute_holdout_hash,
    load_dev_cases,
    load_holdout_cases,
)
from airouter.engine.benchmark.ground_truth_schemas import (
    VALID_HOLDOUT_CATEGORIES,
    GroundTruthCase,
)


class TestLoadDevCases:
    def test_load_default(self):
        cases = load_dev_cases()
        assert len(cases) == 30
        assert all(isinstance(c, GroundTruthCase) for c in cases)

    def test_case_has_required_fields(self):
        cases = load_dev_cases()
        for case in cases:
            assert case.id.startswith("ENG-")
            assert case.prompt
            assert case.category
            assert case.complexity in ("SIMPLE", "MODERATE", "COMPLEX", "EXPERT")
            assert case.risk_level in ("LOW", "MEDIUM", "HIGH", "CRITICAL")

    def test_structured_output_inferred(self):
        cases = load_dev_cases()
        for case in cases:
            assert "action" in case.structured_output.required_fields
            assert "summary" in case.structured_output.required_fields

    def test_missing_file_raises(self):
        with pytest.raises(FileNotFoundError):
            load_dev_cases(Path("/nonexistent/path.yaml"))

    def test_evaluation_loaded(self):
        cases = load_dev_cases()
        # At least some cases should have required_findings
        has_findings = any(c.evaluation.required_findings for c in cases)
        assert has_findings


class TestLoadHoldoutCases:
    def test_missing_file_raises(self):
        with pytest.raises(FileNotFoundError):
            load_holdout_cases(Path("/nonexistent/path.yaml"))


class TestComputeHoldoutHash:
    def test_missing_file_empty_string(self):
        h = compute_holdout_hash(Path("/nonexistent/path.yaml"))
        assert h == ""

    def test_dev_path_returns_hash(self):
        """Dev cases path exists, so we can test the hash function on it."""
        from airouter.engine.benchmark.ground_truth_loader import DEFAULT_DEV_PATH

        h = compute_holdout_hash(DEFAULT_DEV_PATH)
        assert h.startswith("sha256:")
        assert len(h) > 20


class TestValidHoldoutCategories:
    def test_count(self):
        assert len(VALID_HOLDOUT_CATEGORIES) == 8

    def test_expected_categories(self):
        expected = {
            "DOC_UNDERSTANDING", "TABLE_DATA", "CODE_DEBUG", "LOG_OPS",
            "MULTI_TURN", "TOOL_CALLING", "PLANNING", "INSTRUCTION_ANTIHALLU",
        }
        assert VALID_HOLDOUT_CATEGORIES == expected
