"""Oracle 生成器：从多次运行结果中确定每 case 的最优模型和 oracle set。

Oracle = 中位成本最低的及格模型。
Oracle set = 成本距最低 ≤ max(5%, ¥0.005) 的及格模型集合。

聚合通过规则：
- required_passes = run_count // 2 + 1（1次需1通过；2次需2；3次需2）
- SAFETY_HARD_FAILURES 一票否决（不受多数投票保护）
- 普通 hard failure 使用多数投票（harness_validation_failed 等）
"""

from __future__ import annotations

from statistics import median
from typing import Literal

from airouter.engine.benchmark.ground_truth_schemas import (
    CANDIDATE_MODELS,
    SAFETY_HARD_FAILURES,
    AggregatedModelResult,
    GroundTruthCase,
    GroundTruthCaseResult,
    HumanAuditEntry,
    OracleResult,
)


def aggregate_results(
    results: list[GroundTruthCaseResult],
) -> list[AggregatedModelResult]:
    """将多次运行的单次结果聚合为 (case, model) 级聚合结果。

    聚合规则：
    - median_score = 中位 final_score
    - pass_count = final_pass=True 的次数
    - required_passes = run_count // 2 + 1（多数通过）
    - SAFETY_HARD_FAILURES 一票否决（modified_forbidden_file 等）
    - 普通 hard failure（harness_validation_failed）使用多数投票
    - status="failed" → incomplete=True，不计为质量失败
    """
    # 按 (case_id, model) 分组
    groups: dict[tuple[str, str], list[GroundTruthCaseResult]] = {}
    for r in results:
        key = (r.case_id, r.model)
        groups.setdefault(key, []).append(r)

    aggregated = []
    for (case_id, model), runs in sorted(groups.items()):
        # 只统计 status="success" 的运行（API 成功的）
        successful = [r for r in runs if r.status == "success"]

        if not successful:
            # 全部失败 → incomplete
            aggregated.append(AggregatedModelResult(
                case_id=case_id,
                model=model,
                run_count=len(runs),
                incomplete=True,
            ))
            continue

        scores = [r.final_score for r in successful]
        costs = [r.estimated_cost_cny for r in successful]
        pass_count = sum(1 for r in successful if r.final_pass)
        run_count = len(successful)

        # 多数通过：required_passes = run_count // 2 + 1
        # 1次→1, 2次→2, 3次→2
        required_passes = run_count // 2 + 1
        majority_pass = pass_count >= required_passes

        # 合并硬失败
        all_hard_failures: set[str] = set()
        for r in successful:
            all_hard_failures.update(r.hard_failure_ids)

        # SAFETY_HARD_FAILURES 一票否决
        safety_failures = all_hard_failures & SAFETY_HARD_FAILURES
        agg_pass = majority_pass and not bool(safety_failures)

        # 维度中位分
        dim_scores: dict[str, list[float]] = {}
        for r in successful:
            for dim, score in r.dimension_scores.items():
                dim_scores.setdefault(dim, []).append(score)
        dim_medians = {dim: median(vals) for dim, vals in dim_scores.items()}

        # Judge 中位分
        judge_scores = [r.judge_score for r in successful if r.judge_score is not None]
        judge_median = median(judge_scores) if judge_scores else None

        aggregated.append(AggregatedModelResult(
            case_id=case_id,
            model=model,
            run_count=run_count,
            median_score=median(scores),
            median_cost_cny=median(costs),
            pass_count=pass_count,
            aggregated_pass=agg_pass,
            hard_failure_ids=sorted(all_hard_failures),
            dimension_median_scores=dim_medians,
            judge_median_score=judge_median,
            final_pass=agg_pass,
        ))

    return aggregated


def apply_human_verdicts(
    aggregated: list[AggregatedModelResult],
    audit_entries: list[HumanAuditEntry],
) -> list[AggregatedModelResult]:
    """应用人工抽检判定，覆盖 final_pass。"""
    verdict_map: dict[tuple[str, str], HumanAuditEntry] = {}
    for entry in audit_entries:
        verdict_map[(entry.case_id, entry.model)] = entry

    updated = []
    for agg in aggregated:
        key = (agg.case_id, agg.model)
        if key in verdict_map:
            entry = verdict_map[key]
            agg = agg.model_copy(update={
                "human_verdict": entry.human_verdict,
            })
            if entry.human_verdict == "SCORER_FALSE_POSITIVE":
                agg = agg.model_copy(update={"final_pass": False})
            elif entry.human_verdict == "SCORER_FALSE_NEGATIVE":
                agg = agg.model_copy(update={"final_pass": True})
        updated.append(agg)

    return updated


def generate_oracles(
    cases: list[GroundTruthCase],
    aggregated: list[AggregatedModelResult],
    dataset: Literal["dev", "holdout"] = "dev",
) -> list[OracleResult]:
    """为每个 case 生成 Oracle 结果。

    oracle_model = 中位成本最低的 final_pass=True 的模型。
    oracle_set = 成本距最低 ≤ max(5%, ¥0.005) 的及格模型。
    """
    # 按 case_id 分组
    by_case: dict[str, list[AggregatedModelResult]] = {}
    for agg in aggregated:
        by_case.setdefault(agg.case_id, []).append(agg)

    # 获取 pass_threshold
    thresholds: dict[str, float] = {}
    case_id_set: set[str] = set()
    for case in cases:
        thresholds[case.id] = case.pass_threshold
        case_id_set.add(case.id)

    oracles = []
    for case_id in sorted(by_case.keys()):
        if case_id not in case_id_set:
            continue
        models = by_case[case_id]
        pass_threshold = thresholds.get(case_id, 0.80)

        # 分离通过/未通过
        passing = [m for m in models if m.final_pass and not m.incomplete]
        hard_failure_models = [m.model for m in models if m.hard_failure_ids]

        # 按中位成本排序
        passing.sort(key=lambda m: m.median_cost_cny)

        # Oracle 模型
        oracle_model = passing[0].model if passing else None

        # Oracle set
        oracle_set, ceiling = _compute_oracle_set(passing)

        # Oracle action
        oracle_action = _determine_oracle_action(case_id, cases, passing, models)

        oracles.append(OracleResult(
            case_id=case_id,
            dataset=dataset,
            pass_threshold=pass_threshold,
            passing_models=[m.model for m in passing],
            passing_median_scores={m.model: m.median_score for m in passing},
            passing_pass_counts={m.model: m.pass_count for m in passing},
            oracle_model=oracle_model,
            oracle_model_provisional=oracle_model,  # estimated_cost 版
            oracle_median_score=passing[0].median_score if passing else None,
            oracle_set=oracle_set,
            oracle_set_cost_ceiling=ceiling,
            all_model_median_scores={m.model: m.median_score for m in models},
            all_model_pass_counts={m.model: m.pass_count for m in models},
            hard_failure_models=hard_failure_models,
            n_runs=max((m.run_count for m in models), default=1),
            oracle_action=oracle_action,
        ))

    return oracles


def identify_rerun_candidates(
    cases: list[GroundTruthCase],
    first_run_results: list[GroundTruthCaseResult],
    oracles: list[OracleResult],
) -> list[tuple[str, str]]:
    """识别需要补跑的 (case_id, model) 列表。

    触发条件（满足任一即补跑）：
    1. 距 pass_threshold ≤ ±0.05 的边界分数
    2. Oracle 模型本身（确保有足够运行次数）
    3. risk_level = HIGH/CRITICAL 且未通过
    4. rule_score 与 judge_score 分歧 > 0.15
    5. 与 oracle_model 相邻成本的未达标模型

    使用实际 median_cost_cny 排序（不使用 tier 估算）。
    """
    threshold_map = {c.id: c.pass_threshold for c in cases}
    risk_map = {c.id: c.risk_level for c in cases}
    oracle_by_case = {o.case_id: o for o in oracles}

    # 构建 (case_id, model) → 结果索引
    results_map: dict[tuple[str, str], GroundTruthCaseResult] = {}
    for r in first_run_results:
        results_map[(r.case_id, r.model)] = r

    rerun: set[tuple[str, str]] = set()

    for case in cases:
        oracle = oracle_by_case.get(case.id)
        if not oracle:
            continue

        # 获取该 case 各模型的实际 median_cost_cny
        model_costs: list[tuple[str, float]] = []
        for model in CANDIDATE_MODELS:
            entry = results_map.get((case.id, model))
            if entry and entry.status == "success" and entry.estimated_cost_cny > 0:
                model_costs.append((model, entry.estimated_cost_cny))
        model_costs.sort(key=lambda x: x[1])

        # 条件 1：边界分数（距阈值 ±0.05）
        threshold = threshold_map.get(case.id, 0.80)
        for model in CANDIDATE_MODELS:
            entry = results_map.get((case.id, model))
            if entry and entry.status == "success" and abs(entry.final_score - threshold) <= 0.05:
                rerun.add((case.id, model))

        # 条件 2：Oracle 模型本身
        if oracle.oracle_model:
            rerun.add((case.id, oracle.oracle_model))

        # 条件 3：高风险且未通过
        if risk_map.get(case.id) in ("HIGH", "CRITICAL"):
            for model in CANDIDATE_MODELS:
                entry = results_map.get((case.id, model))
                if entry and entry.status == "success" and not entry.final_pass:
                    rerun.add((case.id, model))

        # 条件 4：rule/judge 分歧 > 0.15
        for model in CANDIDATE_MODELS:
            entry = results_map.get((case.id, model))
            if entry and entry.judge_score is not None and abs(entry.rule_score - entry.judge_score) > 0.15:
                rerun.add((case.id, model))

        # 条件 5：与 oracle_model 相邻成本的未达标模型
        if oracle.oracle_model and model_costs:
            oracle_idx = next(
                (i for i, (m, _) in enumerate(model_costs) if m == oracle.oracle_model),
                None,
            )
            if oracle_idx is not None:
                for adj_idx in [oracle_idx - 1, oracle_idx + 1]:
                    if 0 <= adj_idx < len(model_costs):
                        adj_model, _ = model_costs[adj_idx]
                        entry = results_map.get((case.id, adj_model))
                        if entry and entry.status == "success" and not entry.final_pass:
                            rerun.add((case.id, adj_model))

    return sorted(rerun)


def _compute_oracle_set(
    passing: list[AggregatedModelResult],
) -> tuple[list[str], float]:
    """计算 oracle_set 和成本上限。"""
    if not passing:
        return [], 0.0

    cheapest_cost = passing[0].median_cost_cny
    ceiling = cheapest_cost + max(cheapest_cost * 0.05, 0.005)
    oracle_set = [
        m.model for m in passing
        if m.median_cost_cny <= ceiling
    ]
    return oracle_set, ceiling


def _determine_oracle_action(
    case_id: str,
    cases: list[GroundTruthCase],
    passing: list[AggregatedModelResult],
    all_models: list[AggregatedModelResult],
) -> str:
    """确定 oracle action: AUTO / CLARIFY / REVIEW / HUMAN。

    优先级：no_passing > clarify > approval > high_risk > AUTO。
    """
    case = next((c for c in cases if c.id == case_id), None)
    if case is None:
        return "AUTO"

    # 无模型通过 → HUMAN
    if not passing:
        return "HUMAN"

    # 需要追问 → CLARIFY（优先级高于 approval 和 review）
    if case.evaluation.should_ask_clarification:
        return "CLARIFY"

    # 需要人工审批 → HUMAN
    if case.evaluation.requires_human_approval:
        return "HUMAN"

    # 高风险 → REVIEW
    if case.is_high_risk:
        return "REVIEW"

    return "AUTO"
