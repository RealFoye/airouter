"""Ground Truth Benchmark 报告生成器。

生成中文 Markdown 报告，9 节：
1. 报告头  2. Oracle 分析  3. 模型能力矩阵  4. A 层策略对比
5. B 层策略对比  6. Dev vs Holdout  7. 安全分析  8. 成本分析  9. 结论
"""

from __future__ import annotations

from typing import Any

from airouter.engine.benchmark.ground_truth_schemas import (
    GroundTruthSummary,
    StrategyReplayResult,
)


def generate_report(summary: GroundTruthSummary) -> str:
    """生成完整的中文 Markdown 报告。"""
    sections = [
        _section_header(summary),
        _section_oracle(summary),
        _section_model_matrix(summary),
        _section_signal_strategies(summary),
        _section_e2e_strategies(summary),
        _section_dev_holdout(summary),
        _section_safety(summary),
        _section_cost(summary),
        _section_conclusions(summary),
    ]
    return "\n\n".join(sections)


def save_report(summary: GroundTruthSummary, path: str) -> None:
    """生成并保存报告到文件。"""
    from pathlib import Path

    report = generate_report(summary)
    Path(path).write_text(report, encoding="utf-8")


# ── 各节生成 ─────────────────────────────────────────────────


def _section_header(summary: GroundTruthSummary) -> str:
    lines = [
        "# Routing Ground Truth Benchmark 报告",
        "",
        f"- **Run ID**: `{summary.run_id}`",
        f"- **总用例数**: {summary.total_cases}（Dev: {summary.dev_cases}, Holdout: {summary.holdout_cases}）",
        f"- **候选模型**: {', '.join(summary.models)}",
        f"- **Judge 模型**: {', '.join(summary.judge_models)}",
        f"- **每用例运行次数**: {summary.n_runs_per_case}",
    ]
    if summary.eval_frozen_at:
        lines.append(f"- **评分冻结时间**: {summary.eval_frozen_at}")
    if summary.holdout_hash:
        lines.append(f"- **Holdout Hash**: `{summary.holdout_hash}`")
    lines.append("")
    if summary.is_mock_run:
        lines.append("## Mock 评估统计（仅验证链路，Oracle/策略结论不可信）")
        lines.append("")
        lines.append(f"- **Mock 评估数**: {summary.mock_evaluations}")
        lines.append(f"- **总用例×模型 pair**: {summary.candidate_initial_calls + summary.candidate_rerun_calls}")
    else:
        lines.append("## API 调用统计")
        lines.append("")
        lines.append("| 类型 | 次数 |")
        lines.append("|------|------|")
        lines.append(f"| 候选模型（首次） | {summary.candidate_initial_calls} |")
        lines.append(f"| 候选模型（补跑） | {summary.candidate_rerun_calls} |")
        lines.append(f"| Judge（首次） | {summary.judge_initial_calls} |")
        lines.append(f"| Judge（补跑） | {summary.judge_rerun_calls} |")
        lines.append(f"| 重试 | {summary.retry_attempts} |")
        lines.append(f"| **总计** | **{summary.total_physical_api_calls}** |")
    return "\n".join(lines)


def _section_oracle(summary: GroundTruthSummary) -> str:
    lines = [
        "## Oracle 分析",
        "",
        f"共 {len(summary.oracle_results)} 个 Oracle。",
        "",
        "| Case ID | Oracle Model | Oracle Set | Action | Passing |",
        "|---------|-------------|------------|--------|---------|",
    ]
    action_dist: dict[str, int] = {}
    for o in summary.oracle_results:
        oracle_model = o.oracle_model or "无"
        oracle_set = ", ".join(o.oracle_set[:3])
        if len(o.oracle_set) > 3:
            oracle_set += f" (+{len(o.oracle_set) - 3})"
        lines.append(
            f"| {o.case_id} | {oracle_model} | {oracle_set} | {o.oracle_action} | {len(o.passing_models)}/{len(o.all_model_median_scores)} |"
        )
        action_dist[o.oracle_action] = action_dist.get(o.oracle_action, 0) + 1

    lines.append("")
    lines.append("### Oracle Action 分布")
    lines.append("")
    for action, count in sorted(action_dist.items()):
        lines.append(f"- **{action}**: {count} ({count / len(summary.oracle_results) * 100:.1f}%)")

    return "\n".join(lines)


def _section_model_matrix(summary: GroundTruthSummary) -> str:
    lines = [
        "## 模型能力矩阵",
        "",
        "| Model | Median Score Range | Pass Rate | Avg Cost |",
        "|-------|-------------------|-----------|----------|",
    ]

    # 从 oracle 结果中提取各模型数据
    model_stats: dict[str, dict[str, Any]] = {}
    for o in summary.oracle_results:
        for model, score in o.all_model_median_scores.items():
            if model not in model_stats:
                model_stats[model] = {"scores": [], "pass_counts": [], "costs": []}
            model_stats[model]["scores"].append(score)
            model_stats[model]["pass_counts"].append(o.all_model_pass_counts.get(model, 0))

    for model in summary.models:
        stats = model_stats.get(model, {"scores": [], "pass_counts": [], "costs": []})
        if stats["scores"]:
            min_s = min(stats["scores"])
            max_s = max(stats["scores"])
            pass_rate = sum(1 for pc in stats["pass_counts"] if pc > 0) / len(stats["pass_counts"])
            lines.append(f"| {model} | {min_s:.2f}-{max_s:.2f} | {pass_rate:.1%} | - |")
        else:
            lines.append(f"| {model} | N/A | N/A | N/A |")

    return "\n".join(lines)


def _section_signal_strategies(summary: GroundTruthSummary) -> str:
    lines = [
        "## A 层策略对比（Signal Layer）",
        "",
        "| 策略 | Acceptable Match | Cost Regret | Quality Regret | Under-routing | Over-routing | Severe Under |",
        "|------|-----------------|-------------|----------------|---------------|-------------|-------------|",
    ]

    for s in summary.signal_strategy_results:
        lines.append(
            f"| {s.strategy_name} | {s.acceptable_match_rate:.1%} | {s.cost_regret:+.1%} | "
            f"{s.quality_regret:.3f} | {s.under_routing_rate:.1%} | {s.over_routing_rate:.1%} | "
            f"{s.severe_under_routing_rate:.1%} |"
        )

    lines.append("")
    lines.append("### 主要指标说明")
    lines.append("")
    lines.append("- **Acceptable Match Rate**: 选中 Oracle Set 内模型的比例（主要指标）")
    lines.append("- **Cost Regret**: 平均 (策略成本 - Oracle 成本) / Oracle 成本")
    lines.append("- **Quality Regret**: 平均 (Oracle 质量 - 策略质量)")

    return "\n".join(lines)


def _section_e2e_strategies(summary: GroundTruthSummary) -> str:
    lines = [
        "## B 层策略对比（End-to-End）",
        "",
        "| 策略 | Acceptable Match | Cost Regret | Under-routing | Over-routing |",
        "|------|-----------------|-------------|---------------|-------------|",
    ]

    for s in summary.end_to_end_strategy_results:
        lines.append(
            f"| {s.strategy_name} | {s.acceptable_match_rate:.1%} | {s.cost_regret:+.1%} | "
            f"{s.under_routing_rate:.1%} | {s.over_routing_rate:.1%} |"
        )

    return "\n".join(lines)


def _section_dev_holdout(summary: GroundTruthSummary) -> str:
    lines = [
        "## Dev vs Holdout 对比",
        "",
    ]

    if summary.dev_signal_results and summary.holdout_signal_results:
        lines.append("| 策略 | Dev Acceptable | Holdout Acceptable | 方向一致 |")
        lines.append("|------|---------------|-------------------|---------|")

        dev_map = {s.strategy_name: s for s in summary.dev_signal_results}
        hold_map = {s.strategy_name: s for s in summary.holdout_signal_results}

        for name in dev_map:
            dev_acc = dev_map[name].acceptable_match_rate
            hold_acc = hold_map.get(name, StrategyReplayResult(strategy_name=name))
            hold_rate = hold_acc.acceptable_match_rate if isinstance(hold_acc, StrategyReplayResult) else 0.0
            consistent = "是" if abs(dev_acc - hold_rate) < 0.15 else "否"
            lines.append(f"| {name} | {dev_acc:.1%} | {hold_rate:.1%} | {consistent} |")
    else:
        lines.append("仅运行了单一数据集，无法进行 Dev vs Holdout 对比。")

    return "\n".join(lines)


def _section_safety(summary: GroundTruthSummary) -> str:
    lines = [
        "## 安全分析",
        "",
    ]

    # 从所有策略中找最差的 under_routing
    all_strategies = summary.signal_strategy_results + summary.end_to_end_strategy_results

    lines.append("| 策略 | Under-routing | Severe Under | Safety Violation | High-risk Pass |")
    lines.append("|------|--------------|-------------|-----------------|---------------|")
    for s in all_strategies:
        lines.append(
            f"| {s.strategy_name} | {s.under_routing_rate:.1%} | {s.severe_under_routing_rate:.1%} | "
            f"{s.safety_violation_rate:.1%} | {s.high_risk_pass_rate:.1%} |"
        )

    return "\n".join(lines)


def _section_cost(summary: GroundTruthSummary) -> str:
    lines = [
        "## 成本分析",
        "",
        f"- **总估算成本**: ¥{summary.total_estimated_cost_cny:.4f}",
    ]

    if summary.total_billed_cost_cny is not None:
        lines.append(f"- **总实际账单成本**: ¥{summary.total_billed_cost_cny:.4f}")
        delta = summary.total_billed_cost_cny - summary.total_estimated_cost_cny
        lines.append(f"- **估算偏差**: ¥{delta:+.4f}")
    else:
        lines.append("- **实际账单成本**: 待 CCH CSV 对账")

    lines.append("")
    lines.append("### 各策略成本")
    lines.append("")
    lines.append("| 策略 | 估算成本 | Cost Regret |")
    lines.append("|------|---------|-------------|")
    for s in summary.signal_strategy_results + summary.end_to_end_strategy_results:
        lines.append(f"| {s.strategy_name} | ¥{s.total_estimated_cost_cny:.4f} | {s.cost_regret:+.1%} |")

    return "\n".join(lines)


def _section_conclusions(summary: GroundTruthSummary) -> str:
    lines = [
        "## 结论与建议",
        "",
    ]

    # 找最佳策略
    best_signal = max(
        summary.signal_strategy_results,
        key=lambda s: s.acceptable_match_rate,
    ) if summary.signal_strategy_results else None

    if best_signal:
        lines.append(f"### A 层最佳策略: `{best_signal.strategy_name}`")
        lines.append("")
        lines.append(
            f"- Acceptable Match Rate: {best_signal.acceptable_match_rate:.1%}"
        )
        lines.append(f"- Cost Regret: {best_signal.cost_regret:+.1%}")
        lines.append(f"- Under-routing: {best_signal.under_routing_rate:.1%}")

    lines.append("")

    # Oracle action 分析
    oracles = summary.oracle_results
    human_count = sum(1 for o in oracles if o.oracle_action == "HUMAN")
    review_count = sum(1 for o in oracles if o.oracle_action == "REVIEW")
    auto_count = sum(1 for o in oracles if o.oracle_action == "AUTO")

    lines.append("### Oracle Action 总结")
    lines.append("")
    lines.append(f"- **AUTO**: {auto_count} 个用例可完全自动处理")
    lines.append(f"- **REVIEW**: {review_count} 个用例需要执行后复核")
    lines.append(f"- **HUMAN**: {human_count} 个用例需要人工介入")

    if summary.conclusions:
        lines.append("")
        lines.append("### 其他结论")
        lines.append("")
        for c in summary.conclusions:
            lines.append(f"- {c}")

    return "\n".join(lines)
