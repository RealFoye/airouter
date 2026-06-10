"""Shared utilities for Judge scoring analysis.

Used by both finance_report.py (report generation) and
scripts/analyze_judge_run.py (offline analysis).
"""

from __future__ import annotations


def compute_disagreement(rule_score: float, judge_score: float) -> str:
    """Deterministic disagreement label between rule and judge scores.

    Returns one of: "rule_too_high", "rule_too_low", "agree", "unclear".

    Thresholds:
    - rule_too_high: rule >= 0.8 AND judge < 0.6 (规则可能打高了)
    - rule_too_low:  rule < 0.6 AND judge >= 0.8 (规则可能打低了)
    - agree:         |rule - judge| <= 0.15
    - unclear:       everything else (差距明显但未跨越阈值)
    """
    if rule_score >= 0.8 and judge_score < 0.6:
        return "rule_too_high"
    if rule_score < 0.6 and judge_score >= 0.8:
        return "rule_too_low"
    if abs(rule_score - judge_score) <= 0.15 + 1e-12:
        return "agree"
    return "unclear"


def spearman_rank_correlation(x: list[float], y: list[float]) -> float:
    """Spearman rank correlation with average-rank tie-breaking.

    Tied values receive the average of the ranks they would occupy.
    This is the standard definition used by scipy.stats.spearmanr.
    """
    n = len(x)
    if n < 2:
        return 0.0

    def _rank_avg(vals: list[float]) -> list[float]:
        indexed = sorted(enumerate(vals), key=lambda t: t[1])
        ranks = [0.0] * n
        i = 0
        while i < n:
            j = i
            # Find end of tie group
            while j < n - 1 and indexed[j + 1][1] == indexed[j][1]:
                j += 1
            avg_rank = (i + j) / 2.0 + 1.0
            for k in range(i, j + 1):
                ranks[indexed[k][0]] = avg_rank
            i = j + 1
        return ranks

    rx = _rank_avg(x)
    ry = _rank_avg(y)

    # Use Pearson on ranks (handles ties correctly)
    mean_rx = sum(rx) / n
    mean_ry = sum(ry) / n

    cov: float = sum((rx[i] - mean_rx) * (ry[i] - mean_ry) for i in range(n))
    std_x: float = (sum((rx[i] - mean_rx) ** 2 for i in range(n))) ** 0.5
    std_y: float = (sum((ry[i] - mean_ry) ** 2 for i in range(n))) ** 0.5

    if std_x == 0 or std_y == 0:
        return 0.0
    return cov / (std_x * std_y)
