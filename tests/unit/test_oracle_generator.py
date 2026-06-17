"""Unit tests for oracle_generator.py."""

from __future__ import annotations

from airouter.engine.benchmark.ground_truth_schemas import (
    AggregatedModelResult,
    GroundTruthCase,
    GroundTruthCaseResult,
    HumanAuditEntry,
)
from airouter.engine.benchmark.oracle_generator import (
    aggregate_results,
    apply_human_verdicts,
    generate_oracles,
    identify_rerun_candidates,
)


def _agg(case_id: str, model: str, score: float = 0.9, cost: float = 0.01,
         pass_flag: bool = True, run_count: int = 1) -> AggregatedModelResult:
    return AggregatedModelResult(
        case_id=case_id, model=model, run_count=run_count,
        median_score=score, median_cost_cny=cost,
        pass_count=1 if pass_flag else 0,
        aggregated_pass=pass_flag,
        final_pass=pass_flag,
    )


def _case(case_id: str, risk: str = "LOW", **kwargs) -> GroundTruthCase:
    defaults = {"id": case_id, "category": "CODE_DEBUG", "prompt": "test", "risk_level": risk}
    defaults.update(kwargs)
    return GroundTruthCase(**defaults)


class TestAggregateResults:
    def test_single_run(self):
        results = [
            GroundTruthCaseResult(
                case_id="GT-001", model="qwen3.7-max",
                final_score=0.9, final_pass=True,
                estimated_cost_cny=0.05,
            ),
        ]
        aggs = aggregate_results(results)
        assert len(aggs) == 1
        assert aggs[0].median_score == 0.9
        assert aggs[0].final_pass is True

    def test_multiple_runs_median(self):
        results = [
            GroundTruthCaseResult(
                case_id="GT-001", model="m1", run_index=i,
                final_score=s, final_pass=p,
                estimated_cost_cny=0.01,
            )
            for i, (s, p) in enumerate([(0.7, True), (0.9, True), (0.8, True)])
        ]
        aggs = aggregate_results(results)
        assert len(aggs) == 1
        assert aggs[0].median_score == 0.8  # median of [0.7, 0.8, 0.9]
        assert aggs[0].pass_count == 3
        assert aggs[0].aggregated_pass is True

    def test_api_failure_incomplete(self):
        results = [
            GroundTruthCaseResult(
                case_id="GT-001", model="m1",
                status="failed",
                error_type="api_timeout", error_message="timeout",
            ),
        ]
        aggs = aggregate_results(results)
        assert len(aggs) == 1
        assert aggs[0].incomplete is True


class TestGenerateOracles:
    def test_cheapest_passing_is_oracle(self):
        cases = [_case("GT-001")]
        aggs = [
            _agg("GT-001", "expensive", score=0.95, cost=0.10),
            _agg("GT-001", "cheap", score=0.85, cost=0.01),
            _agg("GT-001", "failed", score=0.3, cost=0.005, pass_flag=False),
        ]
        oracles = generate_oracles(cases, aggs)
        assert len(oracles) == 1
        assert oracles[0].oracle_model == "cheap"
        assert "cheap" in oracles[0].oracle_set

    def test_no_passing_model(self):
        cases = [_case("GT-001")]
        aggs = [
            _agg("GT-001", "m1", pass_flag=False),
            _agg("GT-001", "m2", pass_flag=False),
        ]
        oracles = generate_oracles(cases, aggs)
        assert oracles[0].oracle_model is None
        assert oracles[0].oracle_set == []
        assert oracles[0].oracle_action == "HUMAN"

    def test_oracle_set_tolerance(self):
        cases = [_case("GT-001")]
        aggs = [
            _agg("GT-001", "m1", cost=0.01),  # cheapest
            _agg("GT-001", "m2", cost=0.014),  # within 5%
            _agg("GT-001", "m3", cost=0.02),   # outside
        ]
        oracles = generate_oracles(cases, aggs)
        assert "m1" in oracles[0].oracle_set
        assert "m2" in oracles[0].oracle_set
        assert "m3" not in oracles[0].oracle_set

    def test_high_risk_oracle_action(self):
        cases = [_case("GT-001", risk="HIGH")]
        aggs = [_agg("GT-001", "m1")]
        oracles = generate_oracles(cases, aggs)
        assert oracles[0].oracle_action == "REVIEW"


class TestApplyHumanVerdicts:
    def test_false_positive_overrides(self):
        aggs = [_agg("GT-001", "m1", pass_flag=True)]
        entries = [
            HumanAuditEntry(
                case_id="GT-001", model="m1",
                human_verdict="SCORER_FALSE_POSITIVE",
            ),
        ]
        updated = apply_human_verdicts(aggs, entries)
        assert updated[0].final_pass is False
        assert updated[0].human_verdict == "SCORER_FALSE_POSITIVE"

    def test_false_negative_overrides(self):
        aggs = [_agg("GT-001", "m1", pass_flag=False)]
        entries = [
            HumanAuditEntry(
                case_id="GT-001", model="m1",
                human_verdict="SCORER_FALSE_NEGATIVE",
            ),
        ]
        updated = apply_human_verdicts(aggs, entries)
        assert updated[0].final_pass is True


class TestIdentifyRerunCandidates:
    def test_boundary_scores_trigger_rerun(self):
        cases = [_case("GT-001")]
        results = [
            GroundTruthCaseResult(
                case_id="GT-001", model="deepseek-v4-flash",
                final_score=0.82,  # within ±0.05 of 0.80
                pass_threshold=0.80,
                status="success",
                estimated_cost_cny=0.001,
            ),
        ]
        oracles = generate_oracles(cases, aggregate_results(results))
        reruns = identify_rerun_candidates(cases, results, oracles)
        assert any(cid == "GT-001" for cid, _ in reruns)

    def test_high_risk_triggers_rerun(self):
        cases = [_case("GT-001", risk="HIGH")]
        results = [
            GroundTruthCaseResult(
                case_id="GT-001", model="deepseek-v4-flash",
                final_score=0.70, pass_threshold=0.85,
                final_pass=False,
                status="success",
                estimated_cost_cny=0.001,
            ),
        ]
        oracles = generate_oracles(cases, aggregate_results(results))
        reruns = identify_rerun_candidates(cases, results, oracles)
        assert ("GT-001", "deepseek-v4-flash") in reruns


class TestOracleActionPriority:
    """Oracle action 优先级：no_passing > clarify > approval > high_risk > AUTO。"""

    def _gen(self, risk="LOW", clarify=False, approval=False, has_passing=True):
        from airouter.engine.benchmark.ground_truth_schemas import EvaluationSpec
        case = _case(
            "GT-001", risk=risk,
            evaluation=EvaluationSpec(
                should_ask_clarification=clarify,
                requires_human_approval=approval,
            ),
        )
        if has_passing:
            aggs = [_agg("GT-001", "m1", pass_flag=True)]
        else:
            aggs = [_agg("GT-001", "m1", pass_flag=False, score=0.5)]
        oracles = generate_oracles([case], aggs, "dev")
        return oracles[0].oracle_action if oracles else "AUTO"

    def test_no_passing_returns_human(self):
        assert self._gen(has_passing=False) == "HUMAN"

    def test_high_risk_only_returns_review(self):
        assert self._gen(risk="HIGH") == "REVIEW"

    def test_clarify_over_high_risk(self):
        """clarify 优先于 high_risk review。"""
        assert self._gen(risk="HIGH", clarify=True) == "CLARIFY"

    def test_approval_over_high_risk(self):
        """approval 优先于 high_risk review。"""
        assert self._gen(risk="HIGH", approval=True) == "HUMAN"

    def test_clarify_over_approval(self):
        """clarify 优先于 approval。"""
        assert self._gen(clarify=True, approval=True) == "CLARIFY"

    def test_low_no_special_returns_auto(self):
        assert self._gen(risk="LOW") == "AUTO"
