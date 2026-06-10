"""Tests for finance_evaluator.py."""

from __future__ import annotations

import json

import pytest

from airouter.engine.benchmark.finance_evaluator import (
    POLICY_QA_WEIGHTS,
    STANDARD_WEIGHTS,
    _apply_forbidden_findings_penalty,
    _match_single_finding,
    _normalize_decision,
    _parse_finance_json,
    _score_amount_accuracy,
    _score_decision_accuracy,
    _score_evidence_quality,
    _score_finding_recall,
    finance_auto_score,
)
from airouter.engine.benchmark.finance_schemas import FinanceCase


def _make_case(**overrides) -> FinanceCase:
    """Factory for test FinanceCase with sensible defaults."""
    base: dict = {
        "id": "TEST-001",
        "category": "TABLE_CALCULATION",
        "task_type": "DATA_PROCESSING",
        "complexity": "SIMPLE",
        "prompt": "计算合计金额。只输出 JSON。",
        "input_context": "ER-1001: hotel Shanghai 680; client_meal 420 with 2 attendees; taxi 95.",
        "artifacts": ["artifacts/expenses/expense_claims_may.csv"],
        "expected_answer": {
            "amounts": {"raw_total_cny": 1195.0},
            "required_findings": [],
            "decision": "calculate",
        },
        "evaluation": {
            "primary": "rule_based",
            "numeric_tolerance": 0.01,
            "penalize_hallucinated_findings": True,
            "evidence_required": True,
            "scoring_type": "finance_numeric",
            "exact_amounts": ["raw_total_cny"],
            "required_findings": [],
        },
        "output_format": {
            "type": "json",
            "required_fields": ["decision", "amounts", "findings", "evidence", "confidence"],
        },
        "max_tokens": 8192,
    }
    base.update(overrides)
    return FinanceCase(**base)


# ── JSON Validity (tiered scoring) ────────────────────────


class TestJsonValidity:
    """Test _parse_finance_json tiered scoring."""

    def test_direct_json_success(self):
        text = '{"decision": "calculate", "amounts": {"total": 100}}'
        parsed, score = _parse_finance_json(text)
        assert score == 1.0
        assert parsed is not None
        assert parsed["decision"] == "calculate"

    def test_markdown_code_block_extraction(self):
        text = '一些说明文字\n```json\n{"decision": "calculate", "amounts": {}}\n```\n结尾'
        parsed, score = _parse_finance_json(text)
        assert score == 0.85
        assert parsed is not None
        assert parsed["decision"] == "calculate"

    def test_markdown_block_without_lang(self):
        text = '```\n{"decision": "flag"}\n```'
        parsed, score = _parse_finance_json(text)
        assert score == 0.85
        assert parsed is not None

    def test_single_quote_fix(self):
        text = "{'decision': 'calculate', 'amounts': {}}"
        parsed, score = _parse_finance_json(text)
        assert score == 0.65
        assert parsed is not None

    def test_trailing_comma_fix(self):
        text = '{"decision": "calculate", "amounts": {"total": 100,}}'
        parsed, score = _parse_finance_json(text)
        assert score == 0.65
        assert parsed is not None
        assert parsed["amounts"]["total"] == 100

    def test_completely_invalid(self):
        parsed, score = _parse_finance_json("这不是 JSON")
        assert score == 0.0
        assert parsed is None

    def test_empty_string(self):
        parsed, score = _parse_finance_json("")
        assert score == 0.0
        assert parsed is None

    def test_json_array_with_dict(self):
        text = '[{"decision": "calculate", "amounts": {}}]'
        parsed, score = _parse_finance_json(text)
        assert score == 1.0
        assert parsed is not None
        assert parsed["decision"] == "calculate"

    def test_json_array_of_strings(self):
        """POL-006 style: plain array of finding strings."""
        text = '["发票抬头", "重复报销", "住宿标准"]'
        parsed, score = _parse_finance_json(text)
        assert score == 1.0
        assert parsed is not None
        assert parsed == {"findings": ["发票抬头", "重复报销", "住宿标准"]}

    def test_json_array_of_strings_in_markdown(self):
        text = '```json\n["rule1", "rule2"]\n```'
        parsed, score = _parse_finance_json(text)
        assert score == 0.85
        assert parsed is not None
        assert parsed == {"findings": ["rule1", "rule2"]}

    def test_brace_extraction(self):
        text = '结果如下：{"decision": "calculate", "amounts": {"total": 500}} 请注意。'
        parsed, score = _parse_finance_json(text)
        assert score == 0.85
        assert parsed is not None


# ── Amount Accuracy ────────────────────────────────────────


class TestAmountAccuracy:
    """Test _score_amount_accuracy with tolerance and top_item/top_items."""

    def test_exact_match(self):
        output = {"amounts": {"raw_total_cny": 1195.0}}
        expected = {"amounts": {"raw_total_cny": 1195.0}}
        score = _score_amount_accuracy(output, expected, ["raw_total_cny"], 0.01)
        assert score == 1.0

    def test_within_tolerance(self):
        output = {"amounts": {"raw_total_cny": 1195.005}}
        expected = {"amounts": {"raw_total_cny": 1195.0}}
        score = _score_amount_accuracy(output, expected, ["raw_total_cny"], 0.01)
        assert score == 1.0

    def test_outside_tolerance(self):
        output = {"amounts": {"raw_total_cny": 1195.1}}
        expected = {"amounts": {"raw_total_cny": 1195.0}}
        score = _score_amount_accuracy(output, expected, ["raw_total_cny"], 0.01)
        assert score == 0.0

    def test_missing_amount_key(self):
        output = {"amounts": {"other_key": 100.0}}
        expected = {"amounts": {"raw_total_cny": 1195.0}}
        score = _score_amount_accuracy(output, expected, ["raw_total_cny"], 0.01)
        assert score == 0.0

    def test_multiple_amounts_partial(self):
        output = {"amounts": {"approved_cny": 1000.0, "rejected_cny": 999.0}}
        expected = {"amounts": {"approved_cny": 1000.0, "rejected_cny": 195.0}}
        score = _score_amount_accuracy(
            output, expected, ["approved_cny", "rejected_cny"], 0.01
        )
        assert score == 0.5  # one correct, one wrong

    def test_no_amounts_to_check(self):
        output = {"decision": "calculate"}
        expected = {"amounts": {}}
        score = _score_amount_accuracy(output, expected, [], 0.01)
        assert score == 1.0  # nothing to check = full score

    def test_top_item_scoring(self):
        output = {
            "top_item": {"dept": "Sales", "amount_cny": 35000.0},
        }
        expected = {
            "top_item": {"dept": "Sales", "amount_cny": 35000.0},
        }
        score = _score_amount_accuracy(output, expected, [], 0.01)
        assert score == 1.0

    def test_top_items_scoring(self):
        output = {
            "top_items": [
                {"dept": "Sales", "variance_cny": 17000.0},
                {"dept": "R&D", "variance_cny": 48000.0},
                {"dept": "HR", "variance_cny": 22000.0},
            ],
        }
        expected = {
            "top_items": [
                {"dept": "Sales", "variance_cny": 17000.0},
                {"dept": "R&D", "variance_cny": 48000.0},
                {"dept": "HR", "variance_cny": 22000.0},
            ],
        }
        score = _score_amount_accuracy(output, expected, [], 0.01)
        assert score == 1.0

    def test_top_items_wrong_dept(self):
        output = {
            "top_items": [
                {"dept": "Engineering", "variance_cny": 17000.0},
            ],
        }
        expected = {
            "top_items": [
                {"dept": "Sales", "variance_cny": 17000.0},
            ],
        }
        score = _score_amount_accuracy(output, expected, [], 0.01)
        assert score == 0.5  # amount correct but dept wrong

    def test_top_items_match_flat_composite_amount_keys(self):
        """Budget top items can be expressed as flat composite amount keys."""
        output = {
            "amounts": {
                "R&D Cloud": 48000.0,
                "Sales Travel": 18000.0,
                "Sales Entertainment": 17000.0,
            }
        }
        expected = {
            "top_items": [
                {"dept": "R&D", "category": "Cloud", "variance_cny": 48000.0},
                {"dept": "Sales", "category": "Travel", "variance_cny": 18000.0},
                {"dept": "Sales", "category": "Entertainment", "variance_cny": 17000.0},
            ]
        }
        score = _score_amount_accuracy(output, expected, [], 0.01)
        assert score == 1.0

    def test_nested_amount_search(self):
        output = {"result": {"amounts": {"total_cny": 500.0}}}
        expected = {"amounts": {"total_cny": 500.0}}
        score = _score_amount_accuracy(output, expected, ["total_cny"], 0.01)
        assert score == 1.0

    def test_scalar_amounts(self):
        """Model outputs amounts as a single number."""
        output = {"amounts": 775.0}
        expected = {"amounts": {"raw_total_cny": 775.0}}
        score = _score_amount_accuracy(output, expected, ["raw_total_cny"], 0.01)
        assert score == 1.0

    def test_list_amounts(self):
        """Model outputs amounts as a list of numbers."""
        output = {"amounts": [100, 200, 775.0]}
        expected = {"amounts": {"raw_total_cny": 775.0}}
        score = _score_amount_accuracy(output, expected, ["raw_total_cny"], 0.01)
        assert score == 1.0

    def test_value_in_nested_structure(self):
        """Expected value found in deeply nested output."""
        output = {
            "result": {"summary": {"total": 775.0}},
            "amounts": {},
        }
        expected = {"amounts": {"raw_total_cny": 775.0}}
        score = _score_amount_accuracy(output, expected, ["raw_total_cny"], 0.01)
        assert score == 1.0


# ── Finding Recall ─────────────────────────────────────────


class TestFindingRecall:
    """Test finding recall with smart matching."""

    def test_direct_substring(self):
        assert _match_single_finding("hotel_over_limit", "hotel over limit detected")

    def test_chinese_match_for_hotel_over_limit(self):
        output_json = {
            "findings": [
                {"type": "住宿超标", "evidence": "上海住宿680超过600限额"}
            ]
        }
        score = _score_finding_recall(output_json, ["hotel_over_limit_80"])
        assert score == 1.0

    def test_chinese_match_vendor_mismatch(self):
        output_json = {
            "findings": [
                {"type": "供应商不一致", "evidence": "合同方为南方咨询，发票方为南方科技"}
            ]
        }
        score = _score_finding_recall(output_json, ["vendor_mismatch"])
        assert score == 1.0

    def test_chinese_match_duplicate(self):
        output_json = {
            "findings": [
                {"type": "重复发票", "evidence": "INV-T-4001出现两次"}
            ]
        }
        score = _score_finding_recall(output_json, ["duplicate"])
        assert score == 1.0

    def test_number_match_with_context(self):
        output_json = {
            "findings": [
                {"type": "bank_fee", "evidence": "B-003 bank fee -35 not in ledger"}
            ]
        }
        score = _score_finding_recall(output_json, ["B-003"])
        assert score == 1.0

    def test_number_mismatch_not_counted(self):
        """A number that doesn't match should not count as finding hit."""
        output_json = {
            "findings": [
                {"type": "fee", "evidence": "B-005 fee -50"}
            ]
        }
        score = _score_finding_recall(output_json, ["B-003"])
        assert score == 0.0

    def test_partial_findings(self):
        output_json = {
            "findings": [
                {"type": "住宿超标", "evidence": "上海住宿超标"},
            ]
        }
        score = _score_finding_recall(
            output_json,
            ["hotel_over_limit", "personal_invoice_title"],
        )
        assert score == 0.5  # 1 of 2 matched

    def test_no_required_findings(self):
        score = _score_finding_recall({"findings": []}, [])
        assert score == 1.0

    def test_case_insensitive(self):
        assert _match_single_finding("HOTEL_OVER_LIMIT", "hotel over limit found")

    def test_underscore_split_matching(self):
        """hotel_over_limit_80 should match if 'hotel', 'over', 'limit' appear."""
        assert _match_single_finding(
            "hotel_over_limit_80",
            "hotel over limit by 80 CNY",
        )

    def test_chinese_personal_invoice_title(self):
        output_json = {
            "findings": [
                {"type": "个人发票抬头", "evidence": "机票发票抬头为李娜，非公司名称"}
            ]
        }
        score = _score_finding_recall(output_json, ["personal_invoice_title"])
        assert score == 1.0

    def test_chinese_not_accepted(self):
        output_json = {
            "findings": [
                {"type": "未验收", "evidence": "AP-9006尚未通过验收"}
            ]
        }
        score = _score_finding_recall(output_json, ["not_accepted"])
        assert score == 1.0

    def test_finding_in_full_output_text(self):
        """Finding can also be found in other fields, not just 'findings'."""
        output_json = {
            "findings": [],
            "decision": "reject",
            "evidence": ["hotel_over_limit_80 detected in ER-1001"],
        }
        score = _score_finding_recall(output_json, ["hotel_over_limit_80"])
        assert score == 1.0


# ── Decision Accuracy ──────────────────────────────────────


class TestDecisionAccuracy:
    """Test decision matching with Chinese synonym normalization."""

    def test_exact_match(self):
        output = {"decision": "calculate"}
        assert _score_decision_accuracy(output, "calculate") == 1.0

    def test_case_insensitive(self):
        output = {"decision": "Calculate"}
        assert _score_decision_accuracy(output, "calculate") == 1.0

    def test_chinese_partial_approve(self):
        output = {"decision": "部分通过"}
        assert _score_decision_accuracy(output, "partial_approve") == 1.0

    def test_chinese_reject(self):
        output = {"decision": "拒绝"}
        assert _score_decision_accuracy(output, "reject") == 1.0

    def test_chinese_flag(self):
        output = {"decision": "标记风险"}
        assert _score_decision_accuracy(output, "flag") == 1.0

    def test_chinese_summarize(self):
        output = {"decision": "汇总"}
        assert _score_decision_accuracy(output, "summarize") == 1.0

    def test_chinese_approve_with_approval(self):
        output = {"decision": "需审批"}
        assert _score_decision_accuracy(output, "approve_with_approval") == 1.0

    def test_mismatch(self):
        output = {"decision": "approve"}
        assert _score_decision_accuracy(output, "reject") == 0.0

    def test_missing_decision(self):
        output = {"amounts": {}}
        assert _score_decision_accuracy(output, "calculate") == 0.0

    def test_no_expected_decision(self):
        output = {"decision": "anything"}
        assert _score_decision_accuracy(output, "") == 1.0

    def test_partial_credit_reject_or_adjust(self):
        """reject when expected reject_or_adjust should get partial credit."""
        output = {"decision": "reject"}
        score = _score_decision_accuracy(output, "reject_or_adjust")
        assert score == 0.5

    def test_normalize_decision(self):
        assert _normalize_decision("部分通过") == "partial_approve"
        assert _normalize_decision("拒绝") == "reject"
        assert _normalize_decision("calculate") == "calculate"
        assert _normalize_decision("汇总") == "summarize"

    def test_duplicate_payment_flag(self):
        """'发现疑似重复付款' should normalize to flag."""
        output = {"decision": "发现疑似重复付款"}
        assert _score_decision_accuracy(output, "flag") == 1.0

    def test_long_sentence_flag(self):
        """Long sentence containing flag keywords gets partial credit."""
        output = {"decision": "存在疑似重复付款，需进一步核实"}
        assert _score_decision_accuracy(output, "flag") >= 0.5

    def test_further_review_flag(self):
        output = {"decision": "further_review"}
        assert _score_decision_accuracy(output, "flag") == 1.0

    def test_partial_approval_variants(self):
        """Various partial approval expressions."""
        assert _score_decision_accuracy({"decision": "partially_approved"}, "partial_approve") == 1.0
        assert _score_decision_accuracy({"decision": "部分报销"}, "partial_approve") == 1.0
        assert _score_decision_accuracy({"decision": "conditional_approval"}, "partial_approve") == 1.0

    def test_long_sentence_classify(self):
        output = {"decision": "高风险项目需暂停支出，中风险项目需提交说明"}
        assert _score_decision_accuracy(output, "classify") >= 0.5

    def test_no_action_required_negative_answer(self):
        assert _score_decision_accuracy({"decision": "否"}, "no_action_required") == 1.0
        assert _score_decision_accuracy(
            {"decision": "不需要提交预算调整说明"}, "no_action_required"
        ) >= 0.5


# ── Evidence Quality ───────────────────────────────────────


class TestEvidenceQuality:
    """Test evidence references artifacts, business IDs, and policy keywords."""

    def test_artifact_filename_referenced(self):
        output = {
            "evidence": ["expense_claims_may.csv", "travel_policy.md"],
        }
        score = _score_evidence_quality(
            output,
            ["artifacts/expenses/expense_claims_may.csv", "artifacts/policies/travel_policy.md"],
            "ER-1001 hotel Shanghai 680",
        )
        assert score > 0.5

    def test_business_id_referenced(self):
        output = {
            "evidence": ["ER-1001 住宿超标"],
            "findings": [{"evidence": "ER-1001 Shanghai hotel 680 exceeds cap"}],
        }
        score = _score_evidence_quality(
            output,
            ["artifacts/expenses/expense_claims_may.csv"],
            "ER-1001: hotel Shanghai 680",
        )
        assert score > 0.3

    def test_policy_keyword_referenced(self):
        output = {
            "evidence": ["住宿标准"],
            "findings": [{"evidence": "住宿标准规定tier-1城市上限600"}],
        }
        score = _score_evidence_quality(
            output,
            ["artifacts/policies/travel_policy.md"],
            "住宿标准 tier-1城市 上限600",
        )
        assert score > 0.3

    def test_no_evidence(self):
        output = {"findings": []}
        score = _score_evidence_quality(
            output,
            ["artifacts/expenses/expense_claims_may.csv"],
            "ER-1001 hotel",
        )
        # No evidence field, but findings might contain some references
        assert score >= 0.0

    def test_empty_artifacts(self):
        output = {"evidence": ["some reference"]}
        score = _score_evidence_quality(output, [], "")
        assert score == 1.0  # nothing to check


# ── Forbidden Findings ─────────────────────────────────────


class TestForbiddenFindings:
    """Test forbidden findings penalty."""

    def test_no_forbidden_keywords(self):
        output = {"findings": [{"evidence": "model experiments budget overrun"}]}
        score, details = _apply_forbidden_findings_penalty(
            output, ["macroeconomic", "exchange rate"], 0.8
        )
        assert score == 0.8  # no penalty
        assert details == {}

    def test_one_forbidden_keyword(self):
        output = {"findings": [{"evidence": "due to macroeconomic factors"}]}
        score, details = _apply_forbidden_findings_penalty(
            output, ["macroeconomic", "exchange rate"], 0.8
        )
        assert score == pytest.approx(0.7)  # 0.8 - 0.1
        assert "forbidden_found" in details

    def test_multiple_forbidden_keywords(self):
        output = {
            "findings": [
                {"evidence": "macroeconomic and exchange rate impacts"}
            ]
        }
        score, details = _apply_forbidden_findings_penalty(
            output, ["macroeconomic", "exchange rate"], 0.8
        )
        assert score == pytest.approx(0.6)  # 0.8 - 0.2
        assert len(details["forbidden_found"]) == 2

    def test_penalty_capped_at_050(self):
        output = {"findings": [{"evidence": "a b c d e f"}]}
        score, _ = _apply_forbidden_findings_penalty(
            output, ["a", "b", "c", "d", "e", "f"], 0.8
        )
        assert score == pytest.approx(0.3)  # 0.8 - 0.5 (capped)

    def test_empty_forbidden(self):
        output = {"findings": []}
        score, details = _apply_forbidden_findings_penalty(output, [], 0.8)
        assert score == 0.8
        assert details == {}


# ── POLICY_QA Weight Redistribution ────────────────────────


class TestPolicyQAWeights:
    """Test POLICY_QA uses category-based detection."""

    def test_policy_qa_category(self):
        case = _make_case(category="POLICY_QA")
        assert case.is_policy_qa is True

    def test_non_policy_qa_category(self):
        case = _make_case(category="TABLE_CALCULATION")
        assert case.is_policy_qa is False

    def test_policy_qa_with_amounts_still_uses_policy_weights(self):
        """Even if POLICY_QA case has amounts, use POLICY_QA weights."""
        case = _make_case(
            category="POLICY_QA",
            expected_answer={"amounts": {"threshold_cny": 50000}, "decision": "summarize"},
        )
        assert case.is_policy_qa is True

    def test_weight_sum_equals_one(self):
        assert sum(STANDARD_WEIGHTS.values()) == pytest.approx(1.0)
        assert sum(POLICY_QA_WEIGHTS.values()) == pytest.approx(1.0)

    def test_policy_qa_amount_weight_is_zero(self):
        assert POLICY_QA_WEIGHTS["amount_accuracy"] == 0.0


# ── End-to-end finance_auto_score ──────────────────────────


class TestFinanceAutoScore:
    """Integration tests for finance_auto_score."""

    def test_perfect_score(self):
        case = _make_case()
        output = json.dumps({
            "decision": "calculate",
            "amounts": {"raw_total_cny": 1195.0},
            "findings": [],
            "evidence": ["expense_claims_may.csv", "ER-1001"],
            "confidence": 0.95,
        })
        result = finance_auto_score(case, output)
        assert result.overall_score > 0.8
        assert result.scoring_type == "finance_numeric"

    def test_invalid_json_zero_score(self):
        case = _make_case()
        result = finance_auto_score(case, "这不是 JSON")
        assert result.overall_score == 0.0

    def test_markdown_json_partial_validity(self):
        case = _make_case()
        output = '```json\n{"decision": "calculate", "amounts": {"raw_total_cny": 1195.0}, "findings": [], "evidence": ["expense_claims_may.csv"], "confidence": 0.9}\n```'
        result = finance_auto_score(case, output)
        assert result.dimension_scores["json_validity"] == pytest.approx(0.85, abs=0.05)
        assert result.overall_score > 0.5

    def test_wrong_amount_low_score(self):
        case = _make_case()
        output = json.dumps({
            "decision": "calculate",
            "amounts": {"raw_total_cny": 999.0},
            "findings": [],
            "evidence": ["expense_claims_may.csv"],
            "confidence": 0.5,
        })
        result = finance_auto_score(case, output)
        assert result.dimension_scores["amount_accuracy"] == 0.0

    def test_score_bounds_0_to_1(self):
        case = _make_case()
        output = json.dumps({
            "decision": "calculate",
            "amounts": {"raw_total_cny": 1195.0},
            "findings": [],
            "evidence": [],
            "confidence": 1.0,
        })
        result = finance_auto_score(case, output)
        assert 0.0 <= result.overall_score <= 1.0

    def test_forbidden_findings_penalty_applied(self):
        case = _make_case(
            evaluation={
                "scoring_type": "finance_budget_explanation",
                "numeric_tolerance": 0.01,
                "penalize_hallucinated_findings": True,
                "evidence_required": True,
                "forbidden_findings": ["macroeconomic", "exchange rate"],
                "required_findings": [],
            },
        )
        output = json.dumps({
            "decision": "summarize",
            "amounts": {},
            "findings": [{"evidence": "macroeconomic factors caused budget overrun"}],
            "evidence": [],
            "confidence": 0.5,
        })
        result = finance_auto_score(case, output)
        assert "forbidden_penalty" in result.details

    def test_policy_qa_no_amount_check(self):
        """POLICY_QA case should not penalize for missing amounts."""
        case = _make_case(
            category="POLICY_QA",
            expected_answer={"decision": "summarize"},
            evaluation={
                "scoring_type": "finance_policy_qa",
                "numeric_tolerance": 0.01,
                "penalize_hallucinated_findings": True,
                "evidence_required": True,
                "required_findings": ["差旅标准", "住宿限额"],
            },
            input_context="差旅制度规定住宿标准 tier-1城市住宿限额600",
        )
        output = json.dumps({
            "decision": "汇总",
            "findings": [
                {"type": "差旅标准", "evidence": "住宿限额600适用于tier-1城市"}
            ],
            "evidence": ["travel_policy.md", "住宿标准"],
            "confidence": 0.9,
        })
        result = finance_auto_score(case, output)
        # amount_accuracy weight is 0, so missing amounts don't hurt
        assert result.dimension_scores["amount_accuracy"] == 1.0
        assert result.details["dimension_applicability"]["amount_accuracy"] is False
        assert result.overall_score > 0.3

    def test_policy_qa_amount_dimension_computed_when_expected(self):
        """POLICY_QA overall uses policy weights, but reportable amount is computed."""
        case = _make_case(
            category="POLICY_QA",
            expected_answer={
                "amounts": {"approved_amount_cny": 600.0, "rejected_amount_cny": 80.0},
                "decision": "partial_approve",
            },
            evaluation={
                "scoring_type": "finance_policy_qa",
                "numeric_tolerance": 0.01,
                "penalize_hallucinated_findings": True,
                "evidence_required": True,
                "exact_amounts": ["approved_amount_cny", "rejected_amount_cny"],
                "required_findings": [],
            },
        )
        output = json.dumps({
            "decision": "partial_approve",
            "amounts": {"approved_amount_cny": 600.0, "rejected_amount_cny": 80.0},
            "findings": [],
            "evidence": [],
            "confidence": 0.9,
        })
        result = finance_auto_score(case, output)
        assert result.dimension_scores["amount_accuracy"] == 1.0
        assert result.details["dimension_applicability"]["amount_accuracy"] is True

    def test_top_items_in_expected_answer(self):
        """Budget top 3 overspend items should be scored."""
        case = _make_case(
            category="BUDGET_VARIANCE",
            expected_answer={
                "amounts": {"total_overspend_cny": 101500.0},
                "top_items": [
                    {"dept": "Sales", "variance_cny": 17000.0},
                    {"dept": "R&D", "variance_cny": 48000.0},
                    {"dept": "HR", "variance_cny": 22000.0},
                ],
                "decision": "rank",
            },
            evaluation={
                "scoring_type": "finance_budget_rank",
                "numeric_tolerance": 0.01,
                "penalize_hallucinated_findings": True,
                "evidence_required": True,
                "exact_amounts": ["total_overspend_cny"],
                "required_findings": [],
            },
        )
        output = json.dumps({
            "decision": "rank",
            "amounts": {"total_overspend_cny": 101500.0},
            "top_items": [
                {"dept": "Sales", "variance_cny": 17000.0},
                {"dept": "R&D", "variance_cny": 48000.0},
                {"dept": "HR", "variance_cny": 22000.0},
            ],
            "findings": [],
            "evidence": [],
            "confidence": 0.9,
        })
        result = finance_auto_score(case, output)
        assert result.dimension_scores["amount_accuracy"] == 1.0
