"""Tests for judge_utils shared functions."""

from __future__ import annotations

from airouter.engine.benchmark.judge_utils import (
    compute_disagreement,
    spearman_rank_correlation,
)


class TestComputeDisagreement:
    """Tests for compute_disagreement deterministic logic."""

    def test_agree_exact_match(self):
        assert compute_disagreement(0.8, 0.8) == "agree"

    def test_agree_within_threshold(self):
        assert compute_disagreement(0.8, 0.9) == "agree"
        assert compute_disagreement(0.7, 0.6) == "agree"
        assert compute_disagreement(0.85, 0.75) == "agree"

    def test_agree_at_boundary(self):
        # |delta| = 0.15 exactly — must be agree despite float precision
        assert compute_disagreement(0.80, 0.65) == "agree"
        assert compute_disagreement(0.50, 0.65) == "agree"

    def test_rule_too_high(self):
        # rule >= 0.8 AND judge < 0.6
        assert compute_disagreement(0.88, 0.54) == "rule_too_high"
        assert compute_disagreement(1.0, 0.3) == "rule_too_high"
        assert compute_disagreement(0.8, 0.59) == "rule_too_high"

    def test_rule_too_low(self):
        # rule < 0.6 AND judge >= 0.8
        assert compute_disagreement(0.49, 0.89) == "rule_too_low"
        assert compute_disagreement(0.3, 0.9) == "rule_too_low"
        assert compute_disagreement(0.59, 0.8) == "rule_too_low"

    def test_unclear_gap_no_threshold(self):
        # delta > 0.15 but doesn't cross either threshold
        assert compute_disagreement(0.7, 0.5) == "unclear"
        assert compute_disagreement(0.65, 0.85) == "unclear"

    def test_rule_1_0_judge_0_66_is_not_rule_too_low(self):
        """Key regression test: rule=1.0, judge=0.66 must NOT be rule_too_low.

        rule >= 0.8 so it cannot be rule_too_low (which requires rule < 0.6).
        |delta| = 0.34 > 0.15 so it cannot be agree.
        judge 0.66 >= 0.6 so it cannot be rule_too_high.
        Therefore: unclear.
        """
        result = compute_disagreement(1.0, 0.66)
        assert result != "rule_too_low"
        assert result == "unclear"

    def test_rule_0_8_judge_0_59_is_rule_too_high(self):
        assert compute_disagreement(0.8, 0.59) == "rule_too_high"

    def test_rule_0_59_judge_0_8_is_rule_too_low(self):
        assert compute_disagreement(0.59, 0.8) == "rule_too_low"

    def test_both_zero(self):
        assert compute_disagreement(0.0, 0.0) == "agree"

    def test_both_one(self):
        assert compute_disagreement(1.0, 1.0) == "agree"

    def test_four_categories_exhaustive(self):
        """Every (rule, judge) pair maps to exactly one of 4 labels."""
        valid_labels = {"agree", "rule_too_high", "rule_too_low", "unclear"}
        test_pairs = [
            (0.0, 0.0), (0.5, 0.5), (1.0, 1.0),
            (0.9, 0.3), (0.3, 0.9),
            (0.7, 0.5), (0.5, 0.7),
            (0.8, 0.59), (0.59, 0.8),
        ]
        for rule_s, judge_s in test_pairs:
            label = compute_disagreement(rule_s, judge_s)
            assert label in valid_labels, (
                f"({rule_s}, {judge_s}) -> {label} not in {valid_labels}"
            )


class TestSpearmanRankCorrelation:
    """Tests for spearman_rank_correlation with average-rank tie-breaking."""

    def test_perfect_positive(self):
        rho = spearman_rank_correlation([1.0, 2.0, 3.0], [1.0, 2.0, 3.0])
        assert abs(rho - 1.0) < 1e-9

    def test_perfect_negative(self):
        rho = spearman_rank_correlation([1.0, 2.0, 3.0], [3.0, 2.0, 1.0])
        assert abs(rho + 1.0) < 1e-9

    def test_no_correlation(self):
        # Orthogonal-ish ranks
        rho = spearman_rank_correlation(
            [1.0, 2.0, 3.0, 4.0], [2.0, 4.0, 1.0, 3.0]
        )
        assert -0.5 < rho < 0.5

    def test_single_pair(self):
        assert spearman_rank_correlation([1.0], [1.0]) == 0.0

    def test_empty(self):
        assert spearman_rank_correlation([], []) == 0.0

    def test_ties_average_rank(self):
        """Tied values get average rank: [1, 2, 2, 4] -> ranks [1, 2.5, 2.5, 4]."""
        x = [1.0, 2.0, 2.0, 4.0]
        y = [1.0, 2.0, 3.0, 4.0]
        rho = spearman_rank_correlation(x, y)
        # Should be computable without error and close to 1.0
        assert 0.9 < rho <= 1.0

    def test_all_tied(self):
        """All same values -> std=0 -> return 0."""
        rho = spearman_rank_correlation([5.0, 5.0, 5.0], [1.0, 2.0, 3.0])
        assert rho == 0.0

    def test_both_all_tied(self):
        rho = spearman_rank_correlation([5.0, 5.0, 5.0], [5.0, 5.0, 5.0])
        assert rho == 0.0

    def test_ties_in_both(self):
        """Ties in both x and y — should still produce valid rho."""
        x = [1.0, 1.0, 3.0, 4.0]
        y = [1.0, 2.0, 2.0, 4.0]
        rho = spearman_rank_correlation(x, y)
        assert -1.0 <= rho <= 1.0

    def test_known_value_with_ties(self):
        """Verify against scipy reference for a known tied case.

        x = [1, 2, 3, 4, 5]
        y = [5, 3, 3, 2, 1]
        scipy.stats.spearmanr gives rho ≈ -0.975
        """
        x = [1.0, 2.0, 3.0, 4.0, 5.0]
        y = [5.0, 3.0, 3.0, 2.0, 1.0]
        rho = spearman_rank_correlation(x, y)
        # y ranks: 5→5, 3→2.5, 3→2.5, 2→1, 1→... wait
        # y sorted: [1, 2, 3, 3, 5] -> ranks [1, 2, 3.5, 3.5, 5]
        # Original y = [5, 3, 3, 2, 1] -> ranks = [5, 3.5, 3.5, 2, 1]
        # x ranks: [1, 2, 3, 4, 5]
        # Pearson on (x_ranks, y_ranks)
        # mean_x = 3, mean_y = 3
        # cov = (1-3)(5-3) + (2-3)(3.5-3) + (3-3)(3.5-3) + (4-3)(2-3) + (5-3)(1-3)
        #     = (-2)(2) + (-1)(0.5) + (0)(0.5) + (1)(-1) + (2)(-2)
        #     = -4 - 0.5 + 0 - 1 - 4 = -9.5
        # std_x = sqrt(4+1+0+1+4) = sqrt(10)
        # std_y = sqrt(4+0.25+0.25+1+4) = sqrt(9.5)
        # rho = -9.5 / (sqrt(10) * sqrt(9.5)) = -9.5 / sqrt(95) ≈ -9.5/9.747 ≈ -0.9746
        assert abs(rho - (-0.9746)) < 0.001


class TestDisagreementSumEqualsSuccess:
    """Integration-style test: four categories sum to success count."""

    def test_four_categories_sum(self):
        """Simulate a set of (rule, judge) pairs and verify category counts sum."""
        pairs = [
            (0.9, 0.85),   # agree
            (0.7, 0.65),   # agree
            (0.88, 0.54),  # rule_too_high
            (0.84, 0.50),  # rule_too_high
            (0.49, 0.89),  # rule_too_low
            (0.3, 0.9),    # rule_too_low
            (0.7, 0.5),    # unclear
            (1.0, 0.66),   # unclear (key test case!)
            (0.5, 0.5),    # agree
            (0.65, 0.85),  # unclear
        ]
        counts = {"agree": 0, "rule_too_high": 0, "rule_too_low": 0, "unclear": 0}
        for rule_s, judge_s in pairs:
            label = compute_disagreement(rule_s, judge_s)
            counts[label] += 1

        total = sum(counts.values())
        assert total == len(pairs)
        assert counts["agree"] == 3
        assert counts["rule_too_high"] == 2
        assert counts["rule_too_low"] == 2
        assert counts["unclear"] == 3
