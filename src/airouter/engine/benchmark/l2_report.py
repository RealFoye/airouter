"""Level 2 evaluation report generator."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from airouter.engine.benchmark.schemas import (
    JudgeSummary,
    L2Summary,
    PairwiseSummary,
)


def generate_l2_report(
    l2_summary: L2Summary,
    judge_results: JudgeSummary | None = None,
    pairwise_results: PairwiseSummary | None = None,
    output_dir: Path | None = None,
) -> str:
    """Generate a comprehensive L2 evaluation report in Markdown.

    Old run (20260608_202410) is diagnostic data; this new run is the final basis.
    """
    lines: list[str] = []

    # 1. Data note
    lines.append("# Level 2 Benchmark 评估报告\n")
    lines.append("## 数据说明\n")
    lines.append(
        "- 旧 run `20260608_202410` 是**诊断数据**（case 定义有缺陷、评分逻辑粗糙）。"
    )
    lines.append(
        "- 本次 run 修正了 5 个 case prompt、升级了 auto-score（截断惩罚+维度评分）、"
        "引入了 double absolute judge + pairwise judge。**本次数据为最终模型选型依据。**\n"
    )

    # 2. Overview
    lines.append("## 概览\n")
    lines.append(f"- Cases: {l2_summary.total_cases}")
    lines.append(f"- Models: {l2_summary.total_models}")
    lines.append(f"- API calls: {l2_summary.total_api_calls}")
    lines.append(f"- Total cost: ¥{l2_summary.total_cost_cny:.4f}")
    lines.append(f"- Total input tokens: {l2_summary.total_input_tokens}")
    lines.append(f"- Total output tokens: {l2_summary.total_output_tokens}\n")

    # 3. Auto-score ranking
    lines.append("## Auto-score 排名\n")
    if l2_summary.model_scores:
        sorted_models = sorted(l2_summary.model_scores.items(), key=lambda x: x[1], reverse=True)
        lines.append("| Rank | Model | Avg Score |")
        lines.append("|------|-------|-----------|")
        for i, (model, score) in enumerate(sorted_models, 1):
            lines.append(f"| {i} | {model} | {score:.4f} |")
        lines.append("")

    # 4. Absolute Judge ranking
    if judge_results:
        lines.append("## Absolute Judge 排名\n")
        if isinstance(judge_results, list):
            for js in judge_results:
                _write_judge_summary(lines, js)
        else:
            _write_judge_summary(lines, judge_results)

    # 5. Pairwise ranking
    if pairwise_results:
        lines.append("## Pairwise 排名\n")
        lines.append(f"- Agreement rate: {pairwise_results.agreement_rate:.2%}")
        lines.append(f"- Agree/Disagree: {pairwise_results.judge_agreement_detail.get('agree', 0)}"
                      f" / {pairwise_results.judge_agreement_detail.get('disagree', 0)}\n")
        if pairwise_results.overall_ranking:
            lines.append("| Rank | Model | Wins | Losses | Ties | Win Rate |")
            lines.append("|------|-------|------|--------|------|----------|")
            for i, entry in enumerate(pairwise_results.overall_ranking, 1):
                lines.append(
                    f"| {i} | {entry['model']} | {entry['wins']} | "
                    f"{entry['losses']} | {entry['ties']} | {entry['win_rate']:.2%} |"
                )
            lines.append("")

    # 6. By task type
    if l2_summary.task_type_scores:
        lines.append("## 按任务类型拆分\n")
        for tt, score in sorted(l2_summary.task_type_scores.items()):
            lines.append(f"- **{tt}**: {score:.4f}")
        lines.append("")

    # 7. Cost analysis
    lines.append("## 成本分析\n")
    lines.append(f"- 总成本: ¥{l2_summary.total_cost_cny:.4f}")
    if l2_summary.total_api_calls > 0:
        avg_cost = l2_summary.total_cost_cny / l2_summary.total_api_calls
        lines.append(f"- 每 case 平均成本: ¥{avg_cost:.6f}")
    if judge_results:
        judge_cost = judge_results.estimated_cost_cny if hasattr(judge_results, 'estimated_cost_cny') else 0
        lines.append(f"- Judge 成本: ¥{judge_cost:.4f}")
    if pairwise_results:
        lines.append(f"- Pairwise 成本: ¥{pairwise_results.estimated_cost_cny:.4f}")
    lines.append("")

    # 8. Limitations
    lines.append("## 局限性\n")
    lines.append("- 样本量 30 case，统计显著性有限")
    lines.append("- LLM Judge 存在固有偏差（位置偏差、长度偏差等）")
    lines.append("- Auto-score 基于关键词匹配，无法评估语义质量")
    lines.append("- 排名结论需要 auto-score、absolute judge、pairwise judge、人工抽检四个来源一致才能确认\n")

    # 9. Disclaimer
    lines.append("---\n")
    lines.append(
        "*models.yaml 当前是 CCH 历史账单校准价；"
        "新一轮 benchmark / judge 调用仍需导出 CCH usage CSV 对账。*"
    )

    report = "\n".join(lines)

    if output_dir:
        output_dir.mkdir(parents=True, exist_ok=True)
        report_path = output_dir / "model-selection-report.md"
        report_path.write_text(report, encoding="utf-8")

    return report


def _write_judge_summary(lines: list[str], js: Any) -> None:
    """Write a judge summary section."""
    jm = getattr(js, 'judge_model', 'unknown')
    lines.append(f"### Judge: {jm}\n")
    lines.append(f"- Evaluations: {js.successful}/{js.total_evaluations}")
    lines.append(f"- Model truncated: {getattr(js, 'model_truncated_count', 0)}")
    lines.append(f"- Context truncated: {getattr(js, 'judge_context_truncated_count', 0)}")
    lines.append(f"- Starved: {getattr(js, 'starved_count', 0)}")
    lines.append(f"- Cost: ¥{getattr(js, 'estimated_cost_cny', 0):.4f}\n")

    by_model = getattr(js, 'by_model', {})
    if by_model:
        sorted_models = sorted(
            by_model.items(),
            key=lambda x: x[1].get("avg", 0) if isinstance(x[1], dict) else x[1],
            reverse=True,
        )
        lines.append("| Rank | Model | Avg Score |")
        lines.append("|------|-------|-----------|")
        for i, (model, stats) in enumerate(sorted_models, 1):
            avg = stats.get("avg", 0) if isinstance(stats, dict) else stats
            lines.append(f"| {i} | {model} | {avg:.4f} |")
        lines.append("")
