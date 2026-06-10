"""Finance benchmark 中文报告生成器。"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from airouter.engine.benchmark.finance_schemas import FinanceSummary
from airouter.engine.benchmark.judge_utils import (
    compute_disagreement,
    spearman_rank_correlation,
)
from airouter.engine.benchmark.schemas import JudgeResult

# 类别中文名映射
_CATEGORY_NAMES = {
    "TABLE_CALCULATION": "表格计算",
    "REIMBURSEMENT_AUDIT": "报销审核",
    "AP_THREE_WAY_MATCH": "三单匹配",
    "BANK_RECONCILIATION": "银行对账",
    "BUDGET_VARIANCE": "预算分析",
    "POLICY_QA": "制度问答",
}


def generate_finance_report(
    summary: FinanceSummary,
    judge_results: Any = None,
    pairwise_results: Any = None,
    output_dir: Path | None = None,
) -> str:
    """生成《企业财务场景模型评测报告》Markdown。

    Returns:
        报告文件路径（如果 output_dir 为 None 则返回 Markdown 文本）。
    """
    lines: list[str] = []

    _add_header(lines, summary)
    _add_executive_summary(lines, summary)
    _add_case_design(lines, summary)
    _add_model_ranking(lines, summary)
    _add_category_breakdown(lines, summary)
    _add_category_diagnostics(lines, summary)
    _add_cost_analysis(lines, summary)
    _add_typical_errors(lines, summary)
    _add_model_diagnostics(lines, summary)
    _add_low_cost_replacement(lines, summary)
    _add_risks_and_limitations(lines, summary)
    _add_conclusion(lines, summary)

    if judge_results is not None:
        _add_judge_results(lines, judge_results, summary)
    if pairwise_results is not None:
        _add_pairwise_results(lines, pairwise_results)

    report_text = "\n".join(lines)

    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)
        report_path = output_dir / "finance_report.md"
        report_path.write_text(report_text, encoding="utf-8")
        return str(report_path)

    return report_text


def _add_header(lines: list[str], summary: FinanceSummary) -> None:
    lines.append("# 企业财务场景模型评测报告")
    lines.append("")
    lines.append(f"> 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"> Run ID：`{summary.run_id}`")
    lines.append("")


def _add_executive_summary(lines: list[str], summary: FinanceSummary) -> None:
    lines.append("## 1. 执行摘要")
    lines.append("")
    lines.append(f"- **Run ID**：`{summary.run_id}`")
    lines.append(f"- **测试时间**：{datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"- **Case 数**：{summary.total_cases}")
    lines.append(f"- **模型数**：{summary.total_models}")
    lines.append(f"- **总调用数**：{summary.total_api_calls}")
    lines.append(f"- **总成本**：{summary.total_cost_cny:.4f} CNY")
    lines.append(f"- **总耗时**：{summary.total_latency_ms / 1000:.1f} 秒")
    lines.append(f"- **完成 pair 数**：{summary.completed_pairs} / {summary.total_cases * summary.total_models}")
    lines.append(f"- **失败 pair 数**：{summary.failed_pairs}")
    lines.append(f"- **是否全部完成**：{'是' if summary.run_completed else '否'}")
    lines.append(f"- **质量达标**：{'是' if summary.quality_passed else '否'}（阈值 {summary.quality_threshold}）")
    if summary.run_notes:
        lines.append("- **运行备注**：")
        for note in summary.run_notes:
            lines.append(f"  - {note}")
    lines.append("")


def _add_model_ranking(lines: list[str], summary: FinanceSummary) -> None:
    lines.append("## 3. 模型总排名")
    lines.append("")
    lines.append("| 排名 | 模型 | 综合分 | JSON 可解析率 | 金额准确率（适用题） | 违规项召回率 | 决策准确率 | 证据得分 | 总成本 (CNY) | 平均延迟 (ms) |")
    lines.append("|------|------|--------|--------------|-----------|-------------|-----------|---------|-------------|--------------|")

    # Sort models by score descending
    ranked = sorted(summary.model_scores.items(), key=lambda x: x[1], reverse=True)

    # Compute per-model dimension averages and cost/latency
    model_dims: dict[str, dict[str, list[float]]] = {}
    model_cost: dict[str, float] = {}
    model_latency: dict[str, list[int]] = {}
    for r in summary.case_results:
        if r.status != "success":
            continue
        m = r.model
        model_dims.setdefault(m, {k: [] for k in r.dimension_scores})
        for k, v in r.dimension_scores.items():
            if k == "amount_accuracy" and not _amount_applicable_result(summary, r):
                continue
            model_dims[m][k].append(v)
        model_cost[m] = model_cost.get(m, 0.0) + r.cost_cny
        model_latency.setdefault(m, []).append(r.latency_ms)

    for rank, (model, score) in enumerate(ranked, 1):
        dims = model_dims.get(model, {})
        json_rate = _avg(dims.get("json_validity", []))
        amount_acc = _avg(dims.get("amount_accuracy", []))
        finding_rec = _avg(dims.get("finding_recall", []))
        decision_acc = _avg(dims.get("decision_accuracy", []))
        evidence_q = _avg(dims.get("evidence_quality", []))
        cost = model_cost.get(model, 0.0)
        latency_list = model_latency.get(model, [])
        avg_latency = sum(latency_list) / len(latency_list) if latency_list else 0

        lines.append(
            f"| {rank} | {model} | {score:.3f} | {json_rate:.2f} | {amount_acc:.2f} | "
            f"{finding_rec:.2f} | {decision_acc:.2f} | {evidence_q:.2f} | "
            f"{cost:.4f} | {avg_latency:.0f} |"
        )

    lines.append("")

    # Per-dimension averages
    lines.append("**整体维度得分：**")
    lines.append("")
    lines.append(f"- JSON 可解析率：{summary.avg_json_validity:.2f}")
    lines.append(
        f"- 金额准确率（仅金额适用题）：{summary.avg_amount_accuracy:.2f} "
        f"（{summary.amount_applicable_pairs} 个 pair）"
    )
    lines.append(
        f"- 金额准确率（兼容口径，N/A 按不扣分处理）：{summary.avg_amount_accuracy_all:.2f}"
    )
    lines.append(f"- 违规项召回率：{summary.avg_finding_recall:.2f}")
    lines.append(f"- 决策准确率：{summary.avg_decision_accuracy:.2f}")
    lines.append(f"- 证据质量得分：{summary.avg_evidence_quality:.2f}")
    lines.append("")


def _add_case_design(lines: list[str], summary: FinanceSummary) -> None:
    lines.append("## 2. 题目设计总览")
    lines.append("")
    lines.append(
        "本轮 Finance Benchmark 覆盖 6 类企业财务办公任务，每类 6 题；"
        "每题分别由 5 个模型作答，因此总计 36 个 case、180 个 model-case pair。"
    )
    lines.append("")
    lines.append("| Case | 类别 | 复杂度 | 考察点 | 题目摘要 |")
    lines.append("|------|------|--------|--------|----------|")
    for case in summary.case_catalog:
        cat = _CATEGORY_NAMES.get(str(case.get("category", "")), str(case.get("category", "")))
        tags = ", ".join(str(t) for t in case.get("tags", [])[:3])
        focus = tags or str(case.get("scoring_type", ""))
        lines.append(
            f"| {case.get('id', '')} | {cat} | {case.get('complexity', '')} | "
            f"{_escape_table(focus)} | {_escape_table(_shorten(str(case.get('prompt', '')), 72))} |"
        )
    lines.append("")


def _add_category_breakdown(lines: list[str], summary: FinanceSummary) -> None:
    lines.append("## 4. 分类别表现")
    lines.append("")

    for cat_summary in summary.category_summaries:
        cat_name = _CATEGORY_NAMES.get(cat_summary.category, cat_summary.category)
        lines.append(f"### {cat_name}（{cat_summary.category}）")
        lines.append("")
        lines.append(f"- **Case 数**：{cat_summary.total_cases}")
        lines.append(f"- **Model-case pair 数**：{cat_summary.total_pairs}")
        lines.append(f"- **平均分**：{cat_summary.avg_score:.3f}")
        lines.append(f"- **JSON 可解析率**：{cat_summary.json_parse_rate:.2f}")
        if cat_summary.amount_applicable_pairs:
            lines.append(
                f"- **金额准确率（适用题）**：{cat_summary.amount_accuracy:.2f} "
                f"（{cat_summary.amount_applicable_pairs} 个 pair）"
            )
        else:
            lines.append("- **金额准确率**：不适用")
        lines.append(f"- **违规项召回率**：{cat_summary.finding_recall:.2f}")
        lines.append(f"- **决策准确率**：{cat_summary.decision_accuracy:.2f}")
        lines.append(f"- **证据质量得分**：{cat_summary.evidence_quality:.2f}")
        lines.append("")

        if cat_summary.model_scores:
            lines.append("| 模型 | 得分 |")
            lines.append("|------|------|")
            for model, score in sorted(
                cat_summary.model_scores.items(), key=lambda x: x[1], reverse=True
            ):
                lines.append(f"| {model} | {score:.3f} |")
            lines.append("")


def _add_category_diagnostics(lines: list[str], summary: FinanceSummary) -> None:
    """Per-category model diagnostics: why each model loses points."""
    lines.append("## 5. 分类别模型诊断")
    lines.append("")

    for cat_summary in summary.category_summaries:
        cat_name = _CATEGORY_NAMES.get(cat_summary.category, cat_summary.category)
        lines.append(f"### {cat_name}")
        lines.append("")

        if not cat_summary.model_scores:
            lines.append("无数据。")
            lines.append("")
            continue

        best_model = max(cat_summary.model_scores, key=lambda m: cat_summary.model_scores[m])
        best_score = cat_summary.model_scores[best_model]
        lines.append(f"**最佳模型**：{best_model}（{best_score:.3f}）")
        lines.append("")

        # Collect case_results for this category
        cat_results = [
            r for r in summary.case_results
            if r.category == cat_summary.category and r.status == "success"
        ]

        lines.append("| 模型 | 得分 | 与最佳差距 | 主要弱点维度 | 最差案例 |")
        lines.append("|------|------|----------|-------------|---------|")

        for model, score in sorted(
            cat_summary.model_scores.items(), key=lambda x: x[1], reverse=True
        ):
            gap = best_score - score
            model_results = [r for r in cat_results if r.model == model]

            # Find weakest dimension
            weakest_dim = "N/A"
            weakest_val = 0.0
            if model_results:
                dim_avgs: dict[str, float] = {}
                for dim in model_results[0].dimension_scores:
                    if dim == "amount_accuracy":
                        applicable_vals = [
                            r.dimension_scores[dim]
                            for r in model_results
                            if _amount_applicable_result(summary, r)
                        ]
                        if applicable_vals:
                            dim_avgs[dim] = sum(applicable_vals) / len(applicable_vals)
                    else:
                        vals = [r.dimension_scores[dim] for r in model_results]
                        dim_avgs[dim] = sum(vals) / len(vals)
                if dim_avgs:
                    wk = min(dim_avgs, key=lambda k: dim_avgs[k])
                    weakest_dim = wk
                    weakest_val = dim_avgs[wk]

            # Worst case
            worst = min(model_results, key=lambda r: r.overall_score, default=None)
            worst_str = f"{worst.case_id} ({worst.overall_score:.3f})" if worst else "N/A"

            lines.append(
                f"| {model} | {score:.3f} | {gap:.3f} | "
                f"{weakest_dim} ({weakest_val:.2f}) | {worst_str} |"
            )

        lines.append("")

        # Error type analysis
        lines.append("**错误类型分析**：")
        lines.append("")
        has_error_content = False
        for model in sorted(cat_summary.model_scores):
            model_results = [r for r in cat_results if r.model == model]
            low = [r for r in model_results if r.overall_score < 0.7]
            if not low:
                continue

            json_fail = sum(
                1 for r in low if r.dimension_scores.get("json_validity", 1.0) < 0.5
            )
            amount_err = sum(
                1 for r in low
                if _amount_applicable_result(summary, r)
                and r.dimension_scores.get("amount_accuracy", 1.0) < 0.5
            )
            decision_low = sum(
                1 for r in low if r.dimension_scores.get("decision_accuracy", 1.0) < 0.3
            )
            finding_low = sum(
                1 for r in low if r.dimension_scores.get("finding_recall", 1.0) < 0.5
            )

            parts: list[str] = []
            if json_fail:
                parts.append(f"JSON 解析失败 {json_fail}")
            if amount_err:
                parts.append(f"金额错误 {amount_err}")
            if finding_low:
                parts.append(f"违规项遗漏 {finding_low}")
            if decision_low:
                parts.append(f"决策偏差 {decision_low}")

            err_str = "、".join(parts) if parts else "综合偏低"
            lines.append(f"- **{model}**：{len(low)} 个低分 case（{err_str}）")
            has_error_content = True

        if not has_error_content:
            lines.append("本类别无低于 0.7 的明显低分 case，主要差异来自维度细项。")
        lines.append("")


def _add_cost_analysis(lines: list[str], summary: FinanceSummary) -> None:
    lines.append("## 6. 成本与延迟分析")
    lines.append("")

    model_cost: dict[str, float] = {}
    model_latency: dict[str, list[int]] = {}
    model_scores_list: dict[str, list[float]] = {}
    for r in summary.case_results:
        if r.status != "success":
            continue
        model_cost[r.model] = model_cost.get(r.model, 0.0) + r.cost_cny
        model_latency.setdefault(r.model, []).append(r.latency_ms)
        model_scores_list.setdefault(r.model, []).append(r.overall_score)

    if not model_cost:
        lines.append("暂无成本数据。")
        lines.append("")
        return

    lines.append("| 模型 | 总成本 (CNY) | 平均延迟 (ms) | 综合分 | 性价比 (分/元) |")
    lines.append("|------|-------------|--------------|--------|--------------|")

    for model in sorted(model_cost.keys()):
        cost = model_cost[model]
        latency_list = model_latency.get(model, [])
        avg_latency = sum(latency_list) / len(latency_list) if latency_list else 0
        scores = model_scores_list.get(model, [])
        avg_score = sum(scores) / len(scores) if scores else 0
        # Cost-effectiveness: score per 1 CNY spent (higher = better value)
        cost_eff = avg_score / cost if cost > 0 else 0

        lines.append(
            f"| {model} | {cost:.4f} | {avg_latency:.0f} | {avg_score:.3f} | {cost_eff:.1f} |"
        )

    lines.append("")
    lines.append("> **性价比**：综合分 / 总成本（分/元），数值越高表示每元投入获得的评分越高。")
    lines.append("")

    # Find cheapest and fastest
    cheapest = min(model_cost.items(), key=lambda x: x[1])
    fastest_model = min(
        model_latency.items(),
        key=lambda x: sum(x[1]) / len(x[1]) if x[1] else float("inf"),
    )
    fastest_avg = sum(fastest_model[1]) / len(fastest_model[1]) if fastest_model[1] else 0

    lines.append(f"- **最便宜模型**：{cheapest[0]}（{cheapest[1]:.4f} CNY）")
    lines.append(f"- **最快模型**：{fastest_model[0]}（平均 {fastest_avg:.0f} ms）")
    lines.append("")


def _summarize_expected_answer(expected_answer: dict) -> str:
    """Summarize expected answer for report display, showing key=value pairs."""
    parts = []

    # Decision
    decision = expected_answer.get("decision")
    if decision:
        parts.append(f"decision={decision}")

    # Amounts with key=value
    amounts = expected_answer.get("amounts", {})
    if isinstance(amounts, dict) and amounts:
        amount_strs = [f"{k}={v}" for k, v in amounts.items()]
        parts.append(f"amounts: {', '.join(amount_strs)}")

    # Required findings
    required_findings = expected_answer.get("required_findings", [])
    if required_findings:
        parts.append(f"required_findings: {', '.join(required_findings)}")

    # Top item
    top_item = expected_answer.get("top_item", {})
    if isinstance(top_item, dict) and top_item:
        parts.append(f"top_item: {top_item}")

    # Top items (array)
    top_items = expected_answer.get("top_items", [])
    if isinstance(top_items, list) and top_items:
        parts.append(f"top_items: {top_items[:2]}...")  # Show first 2

    return "; ".join(parts) if parts else ""


def _interpret_low_score_case(summary: FinanceSummary, result: Any) -> dict:
    """Multi-label classification of low-score case with explanation.

    Returns dict with:
        - primary_type: str (most severe issue)
        - secondary_types: list[str] (additional issues)
        - explanation: str (conservative, human-readable)
        - suggestion: str (actionable next step)
    """
    dims = result.dimension_scores
    amount_applicable = _amount_applicable_result(summary, result)

    labels = []
    explanations = []
    suggestions = []

    # Check each dimension
    json_validity = dims.get("json_validity", 1.0)
    amount_accuracy = dims.get("amount_accuracy", 1.0)
    finding_recall = dims.get("finding_recall", 1.0)
    decision_accuracy = dims.get("decision_accuracy", 1.0)
    evidence_quality = dims.get("evidence_quality", 1.0)

    # JSON validity
    if json_validity < 0.7:
        labels.append("结构化输出不合规")
        explanations.append("JSON 格式或必要字段缺失")
        suggestions.append("检查模型输出是否符合 JSON schema")

    # Amount accuracy with cross-reference logic
    if amount_applicable and amount_accuracy < 0.5:
        # Cross-reference with other dimensions
        if finding_recall >= 0.7 and evidence_quality >= 0.6:
            # High finding/evidence but low amount: likely schema mismatch
            labels.append("结构化输出不合规")
            labels.append("汇总口径不匹配")
            explanations.append(
                "模型可能完成了部分业务判断，但输出口径与评分 schema 不一致，需要人工复核"
            )
            suggestions.append("检查 schema prompt 是否包含 amounts 子键提示")
        elif finding_recall < 0.5 and evidence_quality < 0.5:
            # All dimensions low: real business error
            labels.append("真实业务错误")
            explanations.append("多维度表现均较差，说明确实存在业务理解或执行问题")
            suggestions.append("需要人工复核模型输出，确认问题根因")
        else:
            # Mixed: amount mismatch + other issues
            labels.append("汇总口径不匹配")
            if evidence_quality < 0.6:
                labels.append("证据不足")
            explanations.append(
                "评分器未能在模型输出中找到预期金额，可能是 key 名不匹配或计算口径不同"
            )
            suggestions.append("检查模型输出的 amount key 是否与预期一致")
    elif amount_applicable and amount_accuracy >= 0.5 and amount_accuracy < 0.8:
        labels.append("评分器疑似偏严")
        explanations.append("部分金额正确，但评分器可能过于严格")
        suggestions.append("人工复核评分逻辑")

    # Finding recall with cross-reference logic
    if finding_recall < 0.5:
        # Cross-reference: high decision + high evidence but low finding
        if decision_accuracy >= 0.8 and evidence_quality >= 0.7:
            labels.append("评分器疑似偏严")
            labels.append("finding matcher 需复核")
            explanations.append(
                "模型决策和证据基本正确，但 required_findings 未命中，"
                "可能是 identifier 与自然语言表达不一致，需要复核 finding matcher"
            )
            suggestions.append("补充 required_findings aliases，或让 matcher 支持自然语言语义匹配")
        else:
            labels.append("关键发现遗漏")
            explanations.append("遗漏大量发现项")
            suggestions.append("检查模型是否理解了 required_findings 要求")
    elif finding_recall >= 0.5 and finding_recall < 0.8:
        labels.append("发现项部分遗漏")
        explanations.append("次要发现项遗漏")

    # Decision accuracy
    if decision_accuracy < 0.5:
        labels.append("决策判断错误")
        explanations.append("决策与预期完全不符")
        suggestions.append("检查模型对任务目标的理解")
    elif decision_accuracy >= 0.5 and decision_accuracy < 0.8:
        labels.append("决策部分匹配")
        explanations.append("决策语义接近但不精确")

    # Evidence quality
    if evidence_quality < 0.5:
        if "证据不足" not in labels:
            labels.append("证据不足")
            explanations.append("未引用附件或业务 ID")
            suggestions.append("检查 prompt 是否明确要求引用证据")

    # Reasoning starvation
    if result.response_metadata.get("reasoning_starved") or result.response_metadata.get("model_truncated"):
        labels.append("推理 token 饥饿")
        explanations.append("运行层问题导致输出被截断或推理不足")
        suggestions.append("增加 max_tokens 或检查 API 限制")

    # Deduplicate labels
    labels = list(dict.fromkeys(labels))

    # Select primary type (most severe)
    severity_order = [
        "真实业务错误",
        "结构化输出不合规",
        "汇总口径不匹配",
        "关键发现遗漏",
        "决策判断错误",
        "证据不足",
        "评分器疑似偏严",
        "finding matcher 需复核",
        "发现项部分遗漏",
        "决策部分匹配",
        "推理 token 饥饿",
    ]
    primary_type = "题目口径需澄清"  # default fallback
    for severity_label in severity_order:
        if severity_label in labels:
            primary_type = severity_label
            break

    secondary_types = [label for label in labels if label != primary_type]

    # Combine explanations
    explanation = "；".join(explanations) if explanations else "需要人工复核"
    suggestion = "；".join(suggestions) if suggestions else "无具体建议"

    return {
        "primary_type": primary_type,
        "secondary_types": secondary_types,
        "explanation": explanation,
        "suggestion": suggestion,
    }


def _add_typical_errors(lines: list[str], summary: FinanceSummary) -> None:
    lines.append("## 7. 典型错误案例")
    lines.append("")

    # Group by category, find lowest scoring cases
    cat_low_cases: dict[str, list] = {}
    for r in summary.case_results:
        if r.status != "success":
            continue
        cat_low_cases.setdefault(r.category, []).append(r)

    for cat in sorted(cat_low_cases.keys()):
        cat_name = _CATEGORY_NAMES.get(cat, cat)
        cases = sorted(cat_low_cases[cat], key=lambda x: x.overall_score)
        # Show up to 2 lowest scoring cases
        shown = 0
        for r in cases:
            if r.overall_score >= 0.8:
                continue  # skip high-scoring cases
            if shown >= 2:
                break
            lines.append(f"### {cat_name} — {r.case_id} × {r.model}")
            lines.append("")

            # 1. Overall score
            lines.append(f"- **综合分**：{r.overall_score:.3f}")

            # 2. Dimension scores
            lines.append("- **维度得分**：")
            for dim, score in r.dimension_scores.items():
                lines.append(f"  - {dim}: {score:.2f}")

            # 3. Expected answer summary
            case_info = _case_info(summary, r.case_id)
            expected_answer = case_info.get("expected_answer", {})
            expected_summary = _summarize_expected_answer(expected_answer)
            if expected_summary:
                lines.append(f"- **标准答案摘要**：{_escape_inline(expected_summary)}")

            # 4. Model output excerpt (1500 chars)
            raw_excerpt = _raw_output_excerpt(r.raw_output_path, limit=1500)
            if raw_excerpt:
                lines.append(f"- **模型输出摘要**：{_escape_inline(raw_excerpt)}")

            # 4b. Full model output path
            if r.raw_output_path:
                lines.append(f"- **完整模型输出路径**：`{r.raw_output_path}`")

            # 5. Rule-based deduction reason (programmatic analysis)
            lines.append("- **规则扣分原因**：")
            low_dims = []
            for dim, score in r.dimension_scores.items():
                if score < 0.7:
                    low_dims.append(f"{dim}={score:.2f}")
            if low_dims:
                lines.append(f"  - 低分维度：{', '.join(low_dims)}")
            else:
                lines.append("  - 无明显低分维度（综合分受多维度轻微影响）")

            # 6. Multi-label interpretation
            interpretation = _interpret_low_score_case(summary, r)
            lines.append("- **人工解读**：")
            lines.append(f"  - 主类型：{interpretation['primary_type']}")
            if interpretation["secondary_types"]:
                lines.append(f"  - 辅助标签：{', '.join(interpretation['secondary_types'])}")
            lines.append(f"  - 说明：{interpretation['explanation']}")

            # 7. Suggestion
            lines.append(f"- **后续处理建议**：{interpretation['suggestion']}")

            lines.append("")
            shown += 1

    if not any(cat_low_cases.values()):
        lines.append("暂无低分案例。")
        lines.append("")


def _add_model_diagnostics(lines: list[str], summary: FinanceSummary) -> None:
    lines.append("## 8. 模型错误与优势画像")
    lines.append("")

    by_model: dict[str, list] = defaultdict(list)
    for result in summary.case_results:
        if result.status == "success":
            by_model[result.model].append(result)

    for model in sorted(by_model):
        results = by_model[model]
        issue_counter: Counter[str] = Counter()
        for result in results:
            issue_counter.update(_classify_result_issues(summary, result))

        lines.append(f"### {model}")
        lines.append("")
        if issue_counter:
            issue_desc = "；".join(
                f"{_ISSUE_LABELS[k]} {v} 次"
                for k, v in issue_counter.most_common()
            )
            lines.append(f"- **高频问题**：{issue_desc}")
        else:
            lines.append("- **高频问题**：未发现显著系统性问题")

        strengths = _model_strengths(summary, model)
        if strengths:
            lines.append(f"- **相对优势**：{'; '.join(strengths)}")
        else:
            lines.append("- **相对优势**：暂无明显领先类别")

        weak_examples = sorted(results, key=lambda x: x.overall_score)[:3]
        if weak_examples:
            lines.append("- **代表性低分样例**：")
            for result in weak_examples:
                case_info = _case_info(summary, result.case_id)
                cat = _CATEGORY_NAMES.get(result.category, result.category)
                issues = _classify_result_issues(summary, result)
                issue_text = ", ".join(_ISSUE_LABELS[i] for i in issues) or "综合分偏低"
                prompt = _shorten(str(case_info.get("prompt", "")), 48)
                lines.append(
                    f"  - `{result.case_id}`（{cat}，{prompt}）："
                    f"{result.overall_score:.3f}，{issue_text}"
                )
        lines.append("")

    starved = [
        r for r in summary.case_results
        if r.response_metadata.get("reasoning_starved")
    ]
    if starved:
        lines.append("### 运行层异常")
        lines.append("")
        lines.append(
            "以下结果属于推理 token 饥饿/截断，不能简单归因于业务能力差："
        )
        for r in starved:
            lines.append(
                f"- `{r.case_id} × {r.model}`：finish_reason="
                f"{r.response_metadata.get('finish_reason')}，reasoning_tokens="
                f"{r.response_metadata.get('reasoning_tokens')}"
            )
        lines.append("")


def _add_low_cost_replacement(lines: list[str], summary: FinanceSummary) -> None:
    lines.append("## 9. 低成本模型可替代场景")
    lines.append("")

    lines.append("根据分类别模型得分矩阵分析：")
    lines.append("")

    for cat, model_dict in sorted(summary.category_model_matrix.items()):
        cat_name = _CATEGORY_NAMES.get(cat, cat)
        if not model_dict:
            continue

        best_model = max(model_dict.items(), key=lambda x: x[1])
        worst_model = min(model_dict.items(), key=lambda x: x[1])
        gap = best_model[1] - worst_model[1]

        if gap < 0.1:
            lines.append(f"- **{cat_name}**：模型间差异小（{gap:.3f}），低成本模型可替代强模型。")
        elif gap < 0.2:
            lines.append(
                f"- **{cat_name}**：模型间差异中等（{gap:.3f}），推荐 `{best_model[0]}`，"
                f"低成本模型可用于非关键场景。"
            )
        else:
            lines.append(
                f"- **{cat_name}**：模型间差异大（{gap:.3f}），"
                f"推荐使用 `{best_model[0]}` 或人工审核。"
            )

    lines.append("")


def _add_risks_and_limitations(lines: list[str], summary: FinanceSummary) -> None:
    lines.append("## 10. 风险与局限性")
    lines.append("")
    lines.append("1. **数据为合成数据**：所有 benchmark 数据均为 synthetic fiction，不代表全部真实企业财务场景。")
    lines.append("2. **规则评分局限**：规则评分适合金额类、结构化任务，但对于解释性、推理性任务仍需人工抽查。")
    lines.append("3. **模型输出多样性**：不同模型可能使用不同的 JSON 结构和表达方式，评分器已尽量覆盖，但仍可能遗漏。")
    lines.append("4. **成本估算**：报告中的成本基于 models.yaml 中的价格估算，实际成本需以 CCH 后台账单为准。")
    lines.append("5. **LLM Judge 偏差**：如果使用了 LLM Judge 评分，需注意 Judge 模型本身也有偏差，不应作为唯一排名依据。")
    lines.append("6. **题面可见性**：如果题目依赖 CSV/制度附件，必须确认附件内容已进入 prompt；否则模型可能因缺少上下文而被误扣。")
    lines.append("")

    # CCH 对账信息
    starts = [r.started_at for r in summary.case_results if r.started_at]
    ends = [r.completed_at for r in summary.case_results if r.completed_at]
    if starts and ends:
        def _to_beijing(raw: str) -> datetime:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if dt.tzinfo is not None:
                return dt.astimezone(timezone(timedelta(hours=8)))
            return dt  # naive = 本地北京时间

        t0 = _to_beijing(min(starts))
        t1 = _to_beijing(max(ends))
        wall_min = (t1 - t0).total_seconds() / 60
        bj_start = t0.strftime("%Y-%m-%d %H:%M")
        bj_end = t1.strftime("%Y-%m-%d %H:%M")

        lines.append("### CCH 账单对账")
        lines.append("")
        lines.append(f"- **实际等待时间**：{wall_min:.1f} 分钟（并发执行，非 sum(latency)）")
        lines.append(f"- **CCH 导出范围**：{bj_start} ~ {bj_end}（北京时间，建议前后各扩 5 分钟）")
        lines.append(f"- **注意**：`total_latency_ms`（{summary.total_latency_ms / 1000:.0f} 秒）是所有 API 调用延迟之和，并发场景下远大于 wall clock")
        lines.append("")

    lines.append("> **提醒**：真实 API 跑完后，请导出 CCH usage CSV 进行成本对账。")
    lines.append("")


def _add_conclusion(lines: list[str], summary: FinanceSummary) -> None:
    lines.append("## 11. 结论与建议")
    lines.append("")

    if not summary.model_scores:
        lines.append("暂无足够数据生成结论。")
        lines.append("")
        return

    ranked = sorted(summary.model_scores.items(), key=lambda x: x[1], reverse=True)
    best = ranked[0]

    lines.append("### 默认推荐模型")
    lines.append("")
    lines.append(f"综合评分最高的是 **{best[0]}**（{best[1]:.3f} 分）。")
    lines.append("")

    # Per-category best
    lines.append("### 分类别推荐")
    lines.append("")
    lines.append("| 类别 | 推荐模型 | 得分 |")
    lines.append("|------|---------|------|")
    for cat, model_dict in sorted(summary.category_model_matrix.items()):
        if not model_dict:
            continue
        cat_name = _CATEGORY_NAMES.get(cat, cat)
        best_in_cat = max(model_dict.items(), key=lambda x: x[1])
        lines.append(f"| {cat_name} | {best_in_cat[0]} | {best_in_cat[1]:.3f} |")
    lines.append("")

    # Automation recommendation
    lines.append("### 自动化建议")
    lines.append("")
    for cat, model_dict in sorted(summary.category_model_matrix.items()):
        cat_name = _CATEGORY_NAMES.get(cat, cat)
        if not model_dict:
            continue
        avg = sum(model_dict.values()) / len(model_dict)
        if avg >= 0.8:
            lines.append(f"- **{cat_name}**：模型表现优秀（平均 {avg:.2f}），可考虑自动化处理。")
        elif avg >= 0.5:
            lines.append(f"- **{cat_name}**：模型表现一般（平均 {avg:.2f}），建议低成本模型 + 人工抽检。")
        else:
            lines.append(f"- **{cat_name}**：模型表现较差（平均 {avg:.2f}），建议强模型 + 人工审核。")
    lines.append("")


# Re-export from judge_utils for backward compatibility
_compute_disagreement = compute_disagreement
_spearman_rank_correlation = spearman_rank_correlation


def _add_judge_results(
    lines: list[str],
    judge_results: Any,
    summary: FinanceSummary | None = None,
) -> None:
    """Finance-specific LLM Judge audit chapter."""
    lines.append("## 附录 A：LLM Judge 辅助审计（MiniMax-M3）")
    lines.append("")
    lines.append("> **说明**：MiniMax-M3 作为辅助审计层，**不参与主排名**。"
                 "规则评分仍为最终排名依据。Judge 用于发现规则评分可能遗漏的质量问题。")
    lines.append("")

    if not hasattr(judge_results, "results") or not judge_results.results:
        lines.append("无 Judge 数据。")
        lines.append("")
        return

    results: list[JudgeResult] = judge_results.results
    successful: list[JudgeResult] = [r for r in results if r.weighted_score > 0]

    # Overview
    lines.append("### 概览")
    lines.append("")
    lines.append(f"- **Judge 模型**：{judge_results.judge_model}")
    lines.append(f"- **评测总数**：{judge_results.total_evaluations}")
    lines.append(f"- **成功数**：{judge_results.successful}")
    lines.append(f"- **失败数**：{judge_results.failed}")
    lines.append(f"- **估算成本**：{judge_results.estimated_cost_cny:.4f} CNY")
    lines.append("")

    # Rule vs Judge per model
    lines.append("### 规则分 vs Judge 分对比（按模型）")
    lines.append("")
    lines.append("| 模型 | 规则评分 | Judge 评分 | 差值 | 一致率 |")
    lines.append("|------|---------|-----------|------|-------|")

    # Build rule score lookup from summary (rescored scores preferred)
    rule_lookup: dict[tuple[str, str], float] = {}
    rule_by_model: dict[str, list[float]] = {}
    if summary:
        for r in summary.case_results:
            if r.status == "success":
                rule_lookup[(r.case_id, r.model)] = r.overall_score
                rule_by_model.setdefault(r.model, []).append(r.overall_score)

    def _rule_score(jr: JudgeResult) -> float:
        """Get rule score: prefer rescored from summary, fall back to embedded."""
        return rule_lookup.get((jr.case_id, jr.model), jr.rule_score or 0.0)

    model_judge_scores: dict[str, list[float]] = {}
    model_agree_count: dict[str, int] = {}
    model_total_count: dict[str, int] = {}

    for jr in successful:
        model_judge_scores.setdefault(jr.model, []).append(jr.normalized_score)
        model_total_count[jr.model] = model_total_count.get(jr.model, 0) + 1

        rule_s = _rule_score(jr)
        disagreement = _compute_disagreement(rule_s, jr.normalized_score)
        if disagreement == "agree":
            model_agree_count[jr.model] = model_agree_count.get(jr.model, 0) + 1

    for model in sorted(model_judge_scores.keys()):
        j_scores = model_judge_scores[model]
        j_avg = sum(j_scores) / len(j_scores)
        r_avg = sum(rule_by_model.get(model, [0])) / max(len(rule_by_model.get(model, [1])), 1)
        diff = j_avg - r_avg
        agree_pct = model_agree_count.get(model, 0) / max(model_total_count.get(model, 1), 1)
        lines.append(f"| {model} | {r_avg:.3f} | {j_avg:.3f} | {diff:+.3f} | {agree_pct:.0%} |")
    lines.append("")

    # Per-category comparison
    if summary:
        lines.append("### 分类别对比")
        lines.append("")
        lines.append("| 类别 | 规则均分 | Judge 均分 | 差距 |")
        lines.append("|------|---------|-----------|------|")

        # Build per-category rule scores from summary
        cat_rule: dict[str, list[float]] = {}
        for r in summary.case_results:
            if r.status == "success":
                cat_rule.setdefault(r.category, []).append(r.overall_score)

        # Build per-category judge scores
        cat_judge: dict[str, list[float]] = {}
        for jr in successful:
            # Get category from summary case_results
            cat = None
            for cr in summary.case_results:
                if cr.case_id == jr.case_id and cr.model == jr.model:
                    cat = cr.category
                    break
            if cat:
                cat_judge.setdefault(cat, []).append(jr.normalized_score)

        all_cats = sorted(set(list(cat_rule.keys()) + list(cat_judge.keys())))
        for cat in all_cats:
            cat_name = _CATEGORY_NAMES.get(cat, cat)
            r_avg = sum(cat_rule.get(cat, [0])) / max(len(cat_rule.get(cat, [1])), 1)
            j_avg = sum(cat_judge.get(cat, [0])) / max(len(cat_judge.get(cat, [1])), 1)
            diff = j_avg - r_avg
            lines.append(f"| {cat_name} | {r_avg:.3f} | {j_avg:.3f} | {diff:+.3f} |")
        lines.append("")

    # High rule / Low judge cases (rule_too_high)
    rule_too_high: list[JudgeResult] = []
    for jr in successful:
        rule_s = _rule_score(jr)
        disagreement = _compute_disagreement(rule_s, jr.normalized_score)
        if disagreement == "rule_too_high":
            rule_too_high.append(jr)

    if rule_too_high:
        rule_too_high.sort(key=lambda x: x.normalized_score)
        lines.append("### 规则评分偏高（规则分≥0.8，Judge 分<0.6）")
        lines.append("")
        lines.append("| Case | 模型 | 规则分 | Judge 分 | Red Flags | 评语 |")
        lines.append("|------|------|-------|---------|-----------|------|")
        for jr in rule_too_high[:10]:
            flags = ", ".join(jr.red_flags) if jr.red_flags else "-"
            comment = _shorten(jr.comment, 60)
            rule_s = _rule_score(jr)
            lines.append(
                f"| {jr.case_id} | {jr.model} | {rule_s:.3f} | "
                f"{jr.normalized_score:.3f} | {_escape_table(flags)} | {_escape_table(comment)} |"
            )
        lines.append("")

    # Low rule / High judge cases (rule_too_low)
    rule_too_low: list[JudgeResult] = []
    for jr in successful:
        rule_s = _rule_score(jr)
        disagreement = _compute_disagreement(rule_s, jr.normalized_score)
        if disagreement == "rule_too_low":
            rule_too_low.append(jr)

    if rule_too_low:
        rule_too_low.sort(key=lambda x: x.normalized_score, reverse=True)
        lines.append("### 规则评分偏低（规则分<0.6，Judge 分≥0.8）")
        lines.append("")
        lines.append("| Case | 模型 | 规则分 | Judge 分 | 评语 |")
        lines.append("|------|------|-------|---------|------|")
        for jr in rule_too_low[:10]:
            comment = _shorten(jr.comment, 60)
            rule_s = _rule_score(jr)
            lines.append(
                f"| {jr.case_id} | {jr.model} | {rule_s:.3f} | "
                f"{jr.normalized_score:.3f} | {_escape_table(comment)} |"
            )
        lines.append("")

    # Hallucination / weak evidence risk cases
    risk_cases: list[JudgeResult] = []
    for jr in successful:
        hc = jr.dimensions.get("hallucination_control", 5.0)
        if jr.red_flags or hc < 3.0:
            risk_cases.append(jr)

    if risk_cases:
        risk_cases.sort(key=lambda x: x.dimensions.get("hallucination_control", 5.0))
        lines.append("### 幻觉/证据风险案例")
        lines.append("")
        lines.append("| Case | 模型 | 幻觉控制分 | Red Flags | 评语 |")
        lines.append("|------|------|----------|-----------|------|")
        for jr in risk_cases[:10]:
            hc = jr.dimensions.get("hallucination_control", 5.0)
            flags = ", ".join(jr.red_flags) if jr.red_flags else "-"
            comment = _shorten(jr.comment, 60)
            lines.append(
                f"| {jr.case_id} | {jr.model} | {hc:.1f} | "
                f"{_escape_table(flags)} | {_escape_table(comment)} |"
            )
        lines.append("")

    # Ranking consistency
    if summary and model_judge_scores and rule_by_model:
        lines.append("### 排名一致性")
        lines.append("")

        models = sorted(model_judge_scores.keys())
        rule_ranking = sorted(
            models,
            key=lambda m: sum(rule_by_model.get(m, [0])) / max(len(rule_by_model.get(m, [1])), 1),
            reverse=True,
        )
        judge_ranking = sorted(
            models,
            key=lambda m: sum(model_judge_scores.get(m, [0])) / max(len(model_judge_scores.get(m, [1])), 1),
            reverse=True,
        )

        lines.append(f"- **规则排名 Top1**：{rule_ranking[0]}")
        lines.append(f"- **Judge 排名 Top1**：{judge_ranking[0]}")
        top1_match = "一致" if rule_ranking[0] == judge_ranking[0] else "不一致"
        lines.append(f"- **Top1 一致性**：{top1_match}")

        if len(models) >= 3:
            rule_vals = [
                sum(rule_by_model.get(m, [0])) / max(len(rule_by_model.get(m, [1])), 1)
                for m in models
            ]
            judge_vals = [
                sum(model_judge_scores.get(m, [0])) / max(len(model_judge_scores.get(m, [1])), 1)
                for m in models
            ]
            rho = _spearman_rank_correlation(rule_vals, judge_vals)
            lines.append(f"- **Spearman 相关系数**：{rho:.3f}")

        lines.append("")
        lines.append("| 模型 | 规则排名 | Judge 排名 | 差异 |")
        lines.append("|------|---------|-----------|------|")
        for m in models:
            r_pos = rule_ranking.index(m) + 1
            j_pos = judge_ranking.index(m) + 1
            diff = j_pos - r_pos
            lines.append(f"| {m} | #{r_pos} | #{j_pos} | {diff:+d} |")
        lines.append("")

    lines.append("> **结论**：以上 Judge 评分仅作为规则评分的辅助审计参考，不改变最终模型排名。")
    lines.append("")


def _add_pairwise_results(lines: list[str], pairwise_results: Any) -> None:
    lines.append("## 附录 B：Pairwise 对比结果")
    lines.append("")

    if hasattr(pairwise_results, "overall_ranking"):
        lines.append("| 排名 | 模型 | 胜率 |")
        lines.append("|------|------|------|")
        for i, entry in enumerate(pairwise_results.overall_ranking, 1):
            model = entry.get("model", "")
            win_rate = entry.get("win_rate", 0)
            lines.append(f"| {i} | {model} | {win_rate:.2%} |")
        lines.append("")

    if hasattr(pairwise_results, "agreement_rate"):
        lines.append(f"Judge 一致率：{pairwise_results.agreement_rate:.2%}")
        lines.append("")


def _avg(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


_ISSUE_LABELS = {
    "json_invalid": "JSON 不合规",
    "amount_mismatch": "金额/排序不匹配",
    "finding_missing": "关键发现遗漏",
    "decision_mismatch": "决策语义不匹配",
    "evidence_weak": "证据引用不足",
    "reasoning_starved": "推理 token 饥饿/截断",
}


def _case_info(summary: FinanceSummary, case_id: str) -> dict[str, Any]:
    for case in summary.case_catalog:
        if case.get("id") == case_id:
            return case
    return {}


def _amount_applicable_result(summary: FinanceSummary, result: Any) -> bool:
    applicability = result.details.get("dimension_applicability", {})
    if "amount_accuracy" in applicability:
        return bool(applicability["amount_accuracy"])
    return bool(_case_info(summary, result.case_id).get("amount_applicable", False))


def _classify_result_issues(summary: FinanceSummary, result: Any) -> list[str]:
    issues: list[str] = []
    dims = result.dimension_scores
    if result.response_metadata.get("reasoning_starved") or result.response_metadata.get("model_truncated"):
        issues.append("reasoning_starved")
    if dims.get("json_validity", 1.0) < 0.7:
        issues.append("json_invalid")
    if _amount_applicable_result(summary, result) and dims.get("amount_accuracy", 1.0) < 0.8:
        issues.append("amount_mismatch")
    if dims.get("finding_recall", 1.0) < 0.8:
        issues.append("finding_missing")
    if dims.get("decision_accuracy", 1.0) < 0.8:
        issues.append("decision_mismatch")
    if dims.get("evidence_quality", 1.0) < 0.5:
        issues.append("evidence_weak")
    return issues


def _model_strengths(summary: FinanceSummary, model: str) -> list[str]:
    strengths: list[str] = []
    for cat, model_scores in sorted(summary.category_model_matrix.items()):
        score = model_scores.get(model)
        if score is None:
            continue
        cat_avg = sum(model_scores.values()) / len(model_scores) if model_scores else 0.0
        if score >= 0.8 or score >= cat_avg + 0.05:
            cat_name = _CATEGORY_NAMES.get(cat, cat)
            strengths.append(f"{cat_name} {score:.3f}")
    return strengths


def _raw_output_excerpt(raw_output_path: str, limit: int = 220) -> str:
    if not raw_output_path:
        return ""
    path = Path(raw_output_path)
    if not path.exists() or not path.is_file():
        return ""
    text = path.read_text(encoding="utf-8").strip()
    text = " ".join(text.split())
    return _shorten(text, limit)


def _shorten(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: max(limit - 1, 0)] + "…"


def _escape_table(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def _escape_inline(text: str) -> str:
    return text.replace("\n", " ")
