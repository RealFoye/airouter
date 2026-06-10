"""Tests for judge_prompts: dimensions, rubric, weighted score."""

from __future__ import annotations

import pytest

from airouter.engine.benchmark.judge_prompts import (
    _DEFAULT_DIMENSIONS,
    _DIMENSIONS,
    calculate_weighted_score,
    get_dimensions,
    get_json_format,
    get_rubric,
)


class TestGetDimensions:
    @pytest.mark.parametrize("task_type", list(_DIMENSIONS.keys()))
    def test_known_task_types(self, task_type):
        dims = get_dimensions(task_type)
        assert len(dims) > 0
        # Weights should sum to ~1.0
        assert sum(dims.values()) == pytest.approx(1.0, abs=0.01)

    def test_unknown_task_type_fallback(self):
        dims = get_dimensions("UNKNOWN_TYPE")
        assert dims == _DEFAULT_DIMENSIONS
        assert sum(dims.values()) == pytest.approx(1.0, abs=0.01)

    def test_code_generation_dimensions(self):
        dims = get_dimensions("CODE_GENERATION")
        assert "correctness" in dims
        assert "code_quality" in dims
        assert dims["correctness"] == 0.35


class TestGetRubric:
    def test_rubric_contains_all_dimensions(self):
        rubric = get_rubric("CODE_GENERATION")
        dims = get_dimensions("CODE_GENERATION")
        for dim_name in dims:
            assert dim_name in rubric

    def test_rubric_contains_scoring_scale(self):
        rubric = get_rubric("ARCHITECTURE")
        assert "1 分" in rubric or "1分" in rubric
        assert "5 分" in rubric or "5分" in rubric


class TestGetJsonFormat:
    def test_json_format_contains_dimensions(self):
        fmt = get_json_format("CODE_REVIEW")
        dims = get_dimensions("CODE_REVIEW")
        for dim_name in dims:
            assert dim_name in fmt

    def test_json_format_contains_comment(self):
        fmt = get_json_format("BUG_ANALYSIS")
        assert "comment" in fmt


class TestCalculateWeightedScore:
    def test_perfect_scores(self):
        dims = get_dimensions("CODE_GENERATION")
        scores = {dim: 5.0 for dim in dims}
        weighted = calculate_weighted_score("CODE_GENERATION", scores)
        assert weighted == pytest.approx(5.0)

    def test_zero_scores(self):
        scores = {dim: 0.0 for dim in get_dimensions("ARCHITECTURE")}
        weighted = calculate_weighted_score("ARCHITECTURE", scores)
        assert weighted == pytest.approx(0.0)

    def test_weighted_calculation(self):
        # BUG_ANALYSIS: root_cause_accuracy(0.35), fix_correctness(0.30),
        #               explanation(0.20), prevention(0.15)
        scores = {
            "root_cause_accuracy": 4.0,
            "fix_correctness": 3.0,
            "explanation": 5.0,
            "prevention": 2.0,
        }
        weighted = calculate_weighted_score("BUG_ANALYSIS", scores)
        expected = 4.0 * 0.35 + 3.0 * 0.30 + 5.0 * 0.20 + 2.0 * 0.15
        assert weighted == pytest.approx(expected)

    def test_missing_dimension_defaults_to_zero(self):
        scores = {"correctness": 5.0}  # only one dimension
        weighted = calculate_weighted_score("CODE_GENERATION", scores)
        expected = 5.0 * 0.35  # other dims contribute 0
        assert weighted == pytest.approx(expected)
