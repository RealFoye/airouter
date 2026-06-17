"""策略回放：A 层信号对比 + B 层端到端。

A 层（信号对比）：所有策略共享同一个 TaskAnalyzer + ModelSelector + Gate + SINGLE_MODEL + 候选池。
唯一变量是复杂度信号来源（rules / ml_raw / ml_final / hybrid）。

B 层（端到端）：完整 Router.route()，使用受限候选池。
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Literal

from airouter.engine.benchmark.ground_truth_schemas import (
    CANDIDATE_MODELS,
    AggregatedModelResult,
    OracleResult,
    StrategyReplayResult,
)

log = logging.getLogger(__name__)


# ── Action 归一化 ─────────────────────────────────────────────


_ACTION_NORMALIZE = {
    "AUTO": "AUTO",
    "HUMAN": "ESCALATE",
    "ESCALATE_TO_HUMAN": "ESCALATE",
    "REVIEW": "REVIEW",
    "EXECUTE_WITH_REVIEW": "REVIEW",
    "CLARIFY": "CLARIFY",
}


def _normalize_action(action: str) -> str:
    """归一化 action 枚举到标准集合 {AUTO, ESCALATE, REVIEW, CLARIFY}。"""
    return _ACTION_NORMALIZE.get(action, action)


# ── 路由分类 ─────────────────────────────────────────────────


def classify_routing(
    selected_model: str | None,
    selected_pass: bool,
    oracle: OracleResult,
    risk_level: str = "LOW",
) -> str:
    """分类路由结果。

    optimal: 选中 oracle_set 内模型
    over_routing: 通过但不在 oracle_set 内（存在更便宜的达标模型）
    acceptable_no_cheaper: 通过但 oracle_set 为空（已是唯一选择）
    under_routing: 未通过但存在达标模型
    no_passing_model: 无模型能通过，非路由问题
    """
    if selected_model is None:
        return "under_routing" if oracle.passing_models else "no_passing_model"

    if selected_pass:
        if selected_model in oracle.oracle_set:
            return "optimal"
        if oracle.oracle_set:
            return "over_routing"
        return "acceptable_no_cheaper"
    else:
        if oracle.passing_models:
            return "under_routing"
        return "no_passing_model"


def is_severe_under_routing(
    classification: str, risk_level: str, has_hard_failure: bool,
) -> bool:
    """severe_under_routing = HIGH/CRITICAL + (under_routing OR hard_failure)。"""
    if risk_level not in ("HIGH", "CRITICAL"):
        return False
    return classification == "under_routing" or has_hard_failure


# ── A 层：信号对比 ───────────────────────────────────────────


class SignalLayerReplay:
    """A 层回放：所有策略使用同一 selector，只比较复杂度信号。

    feature_resolver: (case) → TaskFeatures
    唯一变量是 feature_resolver 返回的 features（特别是 complexity 字段）。
    selector / estimator / candidate_models 全部共享。
    """

    def replay(
        self,
        strategy_name: str,
        feature_resolver: Callable[[Any], Any],
        cases: list[Any],
        results_by_case_model: dict[tuple[str, str], AggregatedModelResult],
        oracle_by_case: dict[str, OracleResult],
        selector: Any,
        estimator: Any,
        candidate_models: list[Any],
        dataset: Literal["dev", "holdout", "all"] = "all",
    ) -> StrategyReplayResult:
        """执行 A 层策略回放。

        对每个 case：
        1. features = feature_resolver(case)
        2. candidates = selector.select_best_strategy(
               [SINGLE_MODEL], candidate_models, features, estimator
           )
        3. selected_model = candidates[0].model_assignment.executor if candidates else None
        4. 查 results_index → classify → 累加指标
        """
        from airouter.models.enums import StrategyType

        per_case = []
        total_cost = 0.0
        total_quality = 0.0
        acceptable_count = 0
        oracle_match_count = 0
        under_count = 0
        over_count = 0
        severe_under_count = 0
        high_risk_total = 0
        high_risk_pass = 0
        safety_violations = 0

        for case in cases:
            case_id = case.id
            risk_level = case.risk_level
            oracle = oracle_by_case.get(case_id)
            if oracle is None:
                continue

            # 策略提取 features → selector 选模型
            features = feature_resolver(case)
            strategy_scores = selector.select_best_strategy(
                [StrategyType.SINGLE_MODEL],
                candidate_models,
                features,
                estimator,
            )

            if strategy_scores:
                selected_model = strategy_scores[0].model_assignment.executor
            else:
                selected_model = None

            # 查找结果
            agg = results_by_case_model.get((case_id, selected_model)) if selected_model else None
            selected_pass = agg.final_pass if agg else False
            selected_score = agg.median_score if agg else 0.0
            selected_cost = agg.median_cost_cny if agg else 0.0

            # 分类
            classification = classify_routing(selected_model, selected_pass, oracle, risk_level)

            # 指标累加
            total_cost += selected_cost
            total_quality += selected_score

            if classification in ("optimal", "acceptable_no_cheaper"):
                acceptable_count += 1
            if classification == "optimal":
                oracle_match_count += 1
            if classification == "under_routing":
                under_count += 1
            if classification == "over_routing":
                over_count += 1

            severe = is_severe_under_routing(
                classification, risk_level, bool(agg and agg.hard_failure_ids),
            )
            if severe:
                severe_under_count += 1

            if risk_level in ("HIGH", "CRITICAL"):
                high_risk_total += 1
                if selected_pass:
                    high_risk_pass += 1

            if agg and agg.hard_failure_ids:
                safety_violations += 1

            per_case.append({
                "case_id": case_id,
                "selected_model": selected_model,
                "complexity": features.complexity.value if hasattr(features.complexity, "value") else str(features.complexity),
                "classification": classification,
                "score": selected_score,
                "cost": selected_cost,
                "in_oracle_set": selected_model in oracle.oracle_set if selected_model else False,
            })

        n = len(per_case)
        if n == 0:
            return StrategyReplayResult(
                strategy_name=strategy_name, layer="signal", dataset=dataset,
            )

        # Oracle 成本基准（用于 cost_regret）
        oracle_costs = []
        quality_regrets = []
        for pc in per_case:
            oracle = oracle_by_case.get(pc["case_id"])
            if oracle and oracle.oracle_model:
                oracle_agg = results_by_case_model.get((pc["case_id"], oracle.oracle_model))
                if oracle_agg:
                    oracle_cost = oracle_agg.median_cost_cny
                    if oracle_cost > 0:
                        regret = (pc["cost"] - oracle_cost) / oracle_cost
                        oracle_costs.append(regret)
                    quality_regrets.append(
                        max(0.0, (oracle_agg.median_score if oracle_agg else 0.0) - pc["score"]),
                    )

        return StrategyReplayResult(
            strategy_name=strategy_name,
            layer="signal",
            dataset=dataset,
            acceptable_match_rate=acceptable_count / n,
            cost_regret=sum(oracle_costs) / len(oracle_costs) if oracle_costs else 0.0,
            quality_regret=sum(quality_regrets) / len(quality_regrets) if quality_regrets else 0.0,
            oracle_model_match_rate=oracle_match_count / n,
            avg_quality_score=total_quality / n,
            total_estimated_cost_cny=total_cost,
            safety_violation_rate=safety_violations / n,
            high_risk_pass_rate=high_risk_pass / max(1, high_risk_total),
            under_routing_rate=under_count / n,
            over_routing_rate=over_count / n,
            severe_under_routing_rate=severe_under_count / n,
            per_case_results=per_case,
        )


# ── B 层：端到端 ─────────────────────────────────────────────


class EndToEndReplay:
    """B 层回放：模拟完整 Router.route() 行为。

    router_chooser: (case) → (model_name | None, metadata_dict)
        模拟 Router 的完整决策流程。
        metadata_dict 可包含 selected_action, requires_human_review, strategy_type 等。
    """

    def replay(
        self,
        strategy_name: str,
        cases: list[Any],
        results_by_case_model: dict[tuple[str, str], AggregatedModelResult],
        oracle_by_case: dict[str, OracleResult],
        router_chooser: Callable[[Any], tuple[str | None, dict]],
        dataset: Literal["dev", "holdout", "all"] = "all",
    ) -> StrategyReplayResult:
        """执行 B 层策略回放。"""
        per_case = []
        total_cost = 0.0
        total_quality = 0.0
        acceptable_count = 0
        under_count = 0
        over_count = 0
        severe_under_count = 0
        safety_violations = 0
        oracle_action_correct = 0
        oracle_action_total = 0
        over_escalation = 0
        unsafe_auto = 0

        for case in cases:
            case_id = case.id
            oracle = oracle_by_case.get(case_id)
            if oracle is None:
                continue

            selected_model, metadata = router_chooser(case)
            if selected_model and selected_model not in CANDIDATE_MODELS:
                selected_model = None

            agg = results_by_case_model.get((case_id, selected_model)) if selected_model else None
            selected_pass = agg.final_pass if agg else False
            selected_score = agg.median_score if agg else 0.0
            selected_cost = agg.median_cost_cny if agg else 0.0

            classification = classify_routing(selected_model, selected_pass, oracle, case.risk_level)

            total_cost += selected_cost
            total_quality += selected_score

            if classification in ("optimal", "acceptable_no_cheaper"):
                acceptable_count += 1
            if classification == "under_routing":
                under_count += 1
            if classification == "over_routing":
                over_count += 1

            severe = is_severe_under_routing(
                classification, case.risk_level, bool(agg and agg.hard_failure_ids),
            )
            if severe:
                severe_under_count += 1
            if agg and agg.hard_failure_ids:
                safety_violations += 1

            # Oracle action 对比（归一化后比较）
            router_action = metadata.get("selected_action", "AUTO")
            norm_router = _normalize_action(router_action)
            norm_oracle = _normalize_action(oracle.oracle_action)
            if norm_oracle != "AUTO":
                oracle_action_total += 1
                if norm_router == norm_oracle:
                    oracle_action_correct += 1

            # over_escalation: Oracle=AUTO 但 Router=ESCALATE
            if norm_oracle == "AUTO" and norm_router == "ESCALATE":
                over_escalation += 1
            # unsafe_auto: Oracle=REVIEW/ESCALATE/CLARIFY 但 Router=AUTO
            if norm_oracle in ("REVIEW", "ESCALATE", "CLARIFY") and norm_router == "AUTO":
                unsafe_auto += 1

            per_case.append({
                "case_id": case_id,
                "selected_model": selected_model,
                "classification": classification,
                "score": selected_score,
                "cost": selected_cost,
                "in_oracle_set": selected_model in oracle.oracle_set if selected_model else False,
                "router_action": router_action,
                "oracle_action": oracle.oracle_action,
            })

        n = len(per_case)
        if n == 0:
            return StrategyReplayResult(
                strategy_name=strategy_name, layer="end_to_end", dataset=dataset,
            )

        oracle_costs = []
        quality_regrets = []
        for pc in per_case:
            oracle = oracle_by_case.get(pc["case_id"])
            if oracle and oracle.oracle_model:
                oracle_agg = results_by_case_model.get((pc["case_id"], oracle.oracle_model))
                if oracle_agg and oracle_agg.median_cost_cny > 0:
                    regret = (pc["cost"] - oracle_agg.median_cost_cny) / oracle_agg.median_cost_cny
                    oracle_costs.append(regret)
                    quality_regrets.append(
                        max(0.0, oracle_agg.median_score - pc["score"]),
                    )

        return StrategyReplayResult(
            strategy_name=strategy_name,
            layer="end_to_end",
            dataset=dataset,
            acceptable_match_rate=acceptable_count / n,
            cost_regret=sum(oracle_costs) / len(oracle_costs) if oracle_costs else 0.0,
            quality_regret=sum(quality_regrets) / len(quality_regrets) if quality_regrets else 0.0,
            avg_quality_score=total_quality / n,
            total_estimated_cost_cny=total_cost,
            safety_violation_rate=safety_violations / n,
            under_routing_rate=under_count / n,
            over_routing_rate=over_count / n,
            severe_under_routing_rate=severe_under_count / n,
            oracle_action_accuracy=(
                oracle_action_correct / max(1, oracle_action_total)
            ),
            over_escalation_rate=over_escalation / n,
            unsafe_auto_rate=unsafe_auto / n,
            per_case_results=per_case,
        )


# ── 辅助函数 ─────────────────────────────────────────────────


def build_results_index(
    aggregated: list[AggregatedModelResult],
) -> dict[tuple[str, str], AggregatedModelResult]:
    """将聚合结果列表转为 {(case_id, model): result} 索引。"""
    return {(r.case_id, r.model): r for r in aggregated}


def build_oracle_index(oracles: list[OracleResult]) -> dict[str, OracleResult]:
    """将 Oracle 结果列表转为 {case_id: result} 索引。"""
    return {o.case_id: o for o in oracles}


def compute_quality_upper_bound(
    cases: list[Any],
    results_by_case_model: dict[tuple[str, str], AggregatedModelResult],
) -> float:
    """quality_upper_bound: 每 case 选最高分模型的平均分（不可部署上界）。"""
    scores = []
    for case in cases:
        case_scores = [
            r.median_score
            for (cid, _), r in results_by_case_model.items()
            if cid == case.id
        ]
        if case_scores:
            scores.append(max(case_scores))
    return sum(scores) / len(scores) if scores else 0.0
