"""Finance benchmark rule-based evaluator.

Scoring dimensions and weights:
- json_validity (0.15): Valid JSON with required fields (tiered scoring)
- amount_accuracy (0.35): Amounts match within tolerance, supports top_item/top_items
- finding_recall (0.25): Required findings present (smart CN/EN matcher)
- decision_accuracy (0.15): Decision matches expected (with synonym normalization)
- evidence_quality (0.10): Evidence references artifacts, business IDs, policy keywords

For POLICY_QA category: redistribute amount_accuracy weight.
"""

from __future__ import annotations

import json
import re
from typing import Any, cast

from airouter.engine.benchmark.finance_schemas import FinanceCase
from airouter.engine.benchmark.schemas import ScoreResult

# ── Weight configurations ──────────────────────────────────

STANDARD_WEIGHTS = {
    "json_validity": 0.15,
    "amount_accuracy": 0.35,
    "finding_recall": 0.25,
    "decision_accuracy": 0.15,
    "evidence_quality": 0.10,
}

POLICY_QA_WEIGHTS = {
    "json_validity": 0.15,
    "amount_accuracy": 0.0,
    "finding_recall": 0.45,
    "decision_accuracy": 0.15,
    "evidence_quality": 0.25,
}

# ── Finding matcher: CN/EN finance keyword mapping ─────────

_FINANCE_KEYWORD_MAP: dict[str, list[str]] = {
    "hotel": ["住宿", "酒店", "宾馆"],
    "client_meal": ["客户餐费", "招待餐费", "招待费", "商务餐费"],
    "meal": ["餐费", "用餐"],
    "over_limit": ["超标", "超限", "超出标准", "超过限额"],
    "duplicate": ["重复", "重复报销", "重复发票"],
    "invoice": ["发票"],
    "personal_invoice_title": ["个人抬头", "个人发票抬头", "发票抬头错误"],
    "vendor_mismatch": ["供应商不一致", "供应商不匹配", "供应商名称不一致"],
    "not_accepted": ["未验收", "未通过验收", "未经验收"],
    "over_billed": ["超开", "多开", "超额开票", "开票金额超出"],
    "budget": ["预算"],
    "overspend": ["超支", "超预算", "超出预算"],
    "bank": ["银行", "银行流水"],
    "ledger": ["账簿", "账面", "台账"],
    "reconciliation": ["对账", "银行对账"],
    "unrecorded": ["未入账", "未记账", "账外"],
    "outstanding": ["未达", "在途", "未达账项"],
    "flight": ["机票", "航班"],
    "taxi": ["出租车", "打车", "的士"],
    "travel": ["差旅", "出差"],
    "reimbursement": ["报销"],
    "approval": ["审批", "批准"],
    "cfo": ["CFO", "财务总监"],
    "three_way_match": ["三单匹配", "三单核对"],
    "payment_condition": ["付款条件", "付款条款"],
    "acceptance": ["验收"],
    "contract": ["合同"],
    "po": ["采购订单", "PO"],
    "variance": ["差异", "偏差", "方差"],
    "risk": ["风险", "高风险"],
    "training": ["培训"],
    "recruitment": ["招聘"],
    "entertainment": ["招待", "接待"],
    "logistics": ["后勤", "物流"],
    "cloud": ["云服务", "云计算"],
    "campus_fair": ["校招", "校园招聘"],
    "model_experiments": ["模型实验", "模型试验"],
    "customer_visits": ["客户拜访", "客户走访"],
    "bank_fee": ["银行手续费", "手续费"],
    "duplicate_payment": ["重复付款", "重复支付"],
    "amount_mismatch": ["金额不一致", "金额不符", "金额差异"],
    "policy": ["制度", "政策", "规定"],
    "threshold": ["阈值", "限额"],
    "not_required": ["不需要", "无需"],
}

# Decision synonym normalization
_DECISION_SYNONYMS: dict[str, list[str]] = {
    "partial_approve": [
        "部分通过", "部分批准", "部分审批通过", "partial approval",
        "部分同意", "部分核准", "partial_approval", "partially_approved",
        "部分报销", "部分可报销", "部分费用拒绝", "conditional_approval",
        "approve with deductions", "approved_with_deductions",
        "部分付款", "部分付款或拒绝付款", "reject_or_partial_payment",
        "仅按可付款金额部分付款", "仅按已验收数量对应的金额付款",
        "partially approved", "partial approval",
        "部分通过，",
    ],
    "reject": [
        "拒绝", "不可报销", "不可付款", "驳回", "不予通过", "否决",
        "不予批准", "reject", "rejected", "拒绝付款",
        "不能放行", "否",
    ],
    "reject_or_adjust": [
        "拒绝或调整", "驳回或调整", "reject or adjust",
        "reject_or_partial_payment", "部分付款或拒绝付款",
    ],
    "approve_with_approval": [
        "需审批", "审批后通过", "需审批通过", "approve with approval",
        "需要审批", "需上级审批",
        "需要财务经理审批", "需要财务经理和CFO审批",
        "需财务经理和CFO审批", "可支付，不需要CFO审批",
        "requires financial manager approval",
    ],
    "flag": [
        "标记", "风险提示", "标记风险", "需关注", "flag", "标注",
        "发现疑似重复付款", "疑似重复付款", "存在疑似重复付款",
        "further_review", "flag_for_review", "review",
        "需进一步核实", "manual_review_required",
        "存在重复报销风险", "发现重复发票",
        "识别银行流水中", "识别出账簿中",
        "确认差异", "存在差异", "揭示账簿中",
        "账簿中存在未匹配", "账簿中无银行流水",
        "银行流水中无对应", "识别银行流水",
        "identified bank statement",
        "确认存在账簿未达",
    ],
    "calculate": [
        "计算", "calculate", "核算", "calculated",
        "根据制度计算", "根据差旅", "对各报销单进行审核",
        "identified", "ok",
        "应付款", "approved",
    ],
    "summarize": [
        "汇总", "总结", "归纳", "summarize", "summary",
        "审批前合规性检查",
        "生成2026年5月", "生成2026-05",
        "银行余额调节差异清单",
        "require", "需要预算调整说明",
        "需要提交预算调整说明",
    ],
    "prioritize": [
        "排序", "优先级", "优先排序", "prioritize",
        "prioritize_three_high_risk",
        "优先处理", "优先调查",
        "立即要求", "立即冻结",
    ],
    "rank": [
        "排名", "排序", "rank",
        "前三大超支项", "前三项超支项目", "前三大超支",
        "top three", "top_item",
    ],
    "classify": [
        "分类", "归类", "classify",
        "高风险项目", "中风险项目", "无需动作项目",
        "high_risk_anomalies_found", "identify high-risk",
        "识别高风险", "需要预算调整说明及高风险",
        "高风险异常项", "识别高风险预算异常",
    ],
    "no_action_required": [
        "无需操作", "无需处理", "no action required", "无异常",
        "不需要", "不需要提交预算调整说明",
        "无需提交", "不必提交", "不必须提交", "否", "不用",
    ],
    "approve": [
        "通过", "批准", "approve", "同意", "核准",
        "可报销", "approved", "approved for payment",
    ],
}

# Business ID patterns for evidence checking
_BUSINESS_ID_PATTERNS = [
    re.compile(r"ER-\d{4}"),       # expense claim IDs
    re.compile(r"AP-\d{4}"),       # AP matching IDs
    re.compile(r"B-\d{3}"),        # bank statement IDs
    re.compile(r"L-\d{3}"),        # ledger IDs
    re.compile(r"INV-[A-Z]-\d{4}"), # invoice numbers
    re.compile(r"OD-\d{4}"),       # other document IDs
    re.compile(r"TRN-\d{4}"),      # training reference IDs
]

# Policy keywords for evidence checking
_POLICY_KEYWORDS = [
    "发票抬头", "住宿标准", "住宿限额", "餐费上限", "餐费标准",
    "验收后付款", "预算调整", "预算调整说明", "CFO审批", "财务总监审批",
    "三单匹配", "付款条件", "差旅制度", "差旅标准",
    "双重阈值", "高风险", "30%", "10%",
    "经济舱", "30天", "提交期限",
    "ap_policy", "travel_policy", "budget_policy",
]


# ── JSON parsing ───────────────────────────────────────────


def _parse_finance_json(output: str) -> tuple[dict | None, float]:
    """Parse model output as JSON with tiered scoring.

    Returns:
        (parsed_dict, validity_score) where validity_score is:
        - 1.0: direct json.loads success
        - 0.85: extracted from markdown code block
        - 0.65: fixed (single quotes, trailing commas) then parsed
        - 0.0: all attempts failed

    Supports both dict and array outputs. Plain arrays are wrapped as
    ``{"findings": [array]}`` so downstream scoring can treat them uniformly.
    """
    if not output or not output.strip():
        return None, 0.0

    text = output.strip()

    def _aggregate_dict_list(items: list[dict]) -> dict:
        """Aggregate findings/evidence/decision from a list of dicts.

        For outputs like ``[{findings: "A"}, {findings: "B"}]``, collect all
        findings into a single dict rather than discarding everything after
        the first element.
        """
        result: dict[str, Any] = {}
        all_findings: list[Any] = []
        all_evidence: list[Any] = []

        for item in items:
            # Collect findings under various key names
            f = item.get("findings") or item.get("finding") or item.get("violations")
            if isinstance(f, list):
                all_findings.extend(f)
            elif f:
                all_findings.append(f)

            # Collect evidence under various key names
            e = item.get("evidence") or item.get("references")
            if isinstance(e, list):
                all_evidence.extend(e)
            elif e:
                all_evidence.append(e)

            # Take the first non-empty decision
            if "decision" not in result and item.get("decision"):
                result["decision"] = item["decision"]

            # Merge other fields (later values overwrite earlier ones)
            _SKIP_KEYS = {"findings", "finding", "violations", "evidence", "references", "decision"}
            for k, v in item.items():
                if k not in _SKIP_KEYS:
                    result[k] = v

        if all_findings:
            result["findings"] = all_findings
        if all_evidence:
            result["evidence"] = all_evidence

        return result

    def _wrap_if_array(parsed: Any) -> dict | None:
        """If parsed is a list, handle appropriately.

        - List of dicts: aggregate findings/evidence/decision across all dicts
        - List of strings/primitives: wrap as {"findings": [...]}
        """
        if isinstance(parsed, dict):
            return parsed
        if isinstance(parsed, list):
            if parsed and isinstance(parsed[0], dict):
                return _aggregate_dict_list(cast(list[dict], parsed))
            return {"findings": parsed}
        return None

    # Tier 1: direct parse
    try:
        parsed = json.loads(text)
        result = _wrap_if_array(parsed)
        if result is not None:
            return result, 1.0
    except (json.JSONDecodeError, ValueError):
        pass

    # Tier 2: extract from markdown code block
    md_match = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
    if md_match:
        try:
            parsed = json.loads(md_match.group(1).strip())
            result = _wrap_if_array(parsed)
            if result is not None:
                return result, 0.85
        except (json.JSONDecodeError, ValueError):
            pass

    # Tier 2b: find largest [...] or {...} block
    bracket_match = re.search(r"\[[^\[\]]*(?:\[[^\[\]]*\][^\[\]]*)*\]", text, re.DOTALL)
    if bracket_match:
        try:
            parsed = json.loads(bracket_match.group(0))
            result = _wrap_if_array(parsed)
            if result is not None:
                return result, 0.85
        except (json.JSONDecodeError, ValueError):
            pass

    brace_match = re.search(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", text, re.DOTALL)
    if brace_match:
        try:
            parsed = json.loads(brace_match.group(0))
            if isinstance(parsed, dict):
                return parsed, 0.85
        except (json.JSONDecodeError, ValueError):
            pass

    # Tier 3: fix common issues (single quotes, trailing commas)
    fixed = text
    # Replace single quotes with double quotes (careful with nested strings)
    fixed = re.sub(r"(?<!\w)'([^']*)'(?!\w)", r'"\1"', fixed)
    # Remove trailing commas before } or ]
    fixed = re.sub(r",\s*([}\]])", r"\1", fixed)
    try:
        parsed = json.loads(fixed)
        result = _wrap_if_array(parsed)
        if result is not None:
            return result, 0.65
    except (json.JSONDecodeError, ValueError):
        pass

    return None, 0.0


# ── Finding matcher ────────────────────────────────────────


def _extract_finding_text(output_json: dict) -> str:
    """Extract all text from findings field for searching."""
    findings = output_json.get("findings", [])
    if isinstance(findings, list):
        parts = []
        for f in findings:
            if isinstance(f, dict):
                # Concatenate all string values in the finding dict
                for v in f.values():
                    if isinstance(v, str):
                        parts.append(v)
                    elif isinstance(v, (int, float)):
                        parts.append(str(v))
            elif isinstance(f, str):
                parts.append(f)
            elif isinstance(f, (int, float)):
                parts.append(str(f))
        return " ".join(parts)
    elif isinstance(findings, str):
        return findings
    return ""


def _extract_all_text(output_json: dict) -> str:
    """Extract all text from the entire output JSON for broad searching."""
    parts = []
    for key, value in output_json.items():
        if isinstance(value, str):
            parts.append(value)
        elif isinstance(value, (int, float)):
            parts.append(str(value))
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    for v in item.values():
                        if isinstance(v, str):
                            parts.append(v)
                        elif isinstance(v, (int, float)):
                            parts.append(str(v))
        elif isinstance(value, dict):
            for v in value.values():
                if isinstance(v, str):
                    parts.append(v)
                elif isinstance(v, (int, float)):
                    parts.append(str(v))
    return " ".join(parts)


def _match_single_finding(required: str, search_text: str) -> bool:
    """Check if a single required finding is present in search text.

    Uses multiple matching strategies:
    1. Case-insensitive substring
    2. Underscore-split word matching
    3. CN/EN keyword mapping
    4. Numeric extraction matching
    """
    req_lower = required.lower().strip()
    text_lower = search_text.lower()

    if not req_lower:
        return True

    # Strategy 1: direct substring
    if req_lower in text_lower:
        return True

    # Strategy 2: underscore split — check if key words appear
    if "_" in required:
        words = [w for w in required.split("_") if len(w) > 1]
        # Require at least 60% of words to match
        if words:
            matched = sum(1 for w in words if w.lower() in text_lower)
            if matched / len(words) >= 0.6:
                return True

    # Strategy 3: CN/EN keyword mapping
    for en_key, cn_values in _FINANCE_KEYWORD_MAP.items():
        # Check if the required finding contains an English key
        if en_key in req_lower or en_key.replace("_", " ") in req_lower:
            # Check if any Chinese equivalent appears in text
            for cn in cn_values:
                if cn.lower() in text_lower:
                    return True
        # Check if the required finding contains a Chinese keyword
        for cn in cn_values:
            if cn in required:
                if cn in search_text or en_key in text_lower:
                    return True

    # Strategy 4: numeric extraction — find numbers in required, check in text
    numbers = re.findall(r"\d+\.?\d*", required)
    if numbers:
        # At least one number must appear in the text
        num_found = sum(1 for n in numbers if n in search_text)
        if num_found > 0:
            # Also check that at least one contextual word matches
            alpha_words = [w for w in re.findall(r"[a-zA-Z]+", required) if len(w) > 1]
            if not alpha_words:
                return True  # pure number match is sufficient
            # Check if any alpha word (or its CN mapping) appears
            for w in alpha_words:
                w_lower = w.lower()
                if w_lower in text_lower:
                    return True
                if w_lower in _FINANCE_KEYWORD_MAP:
                    for cn in _FINANCE_KEYWORD_MAP[w_lower]:
                        if cn in search_text:
                            return True

    return False


def _score_finding_recall(
    output_json: dict,
    required_findings: list[str],
) -> float:
    """Score finding recall using smart matching."""
    if not required_findings:
        return 1.0

    # Search in both findings field and full output text
    finding_text = _extract_finding_text(output_json)
    all_text = _extract_all_text(output_json)
    search_text = finding_text + " " + all_text

    matched = sum(
        1 for f in required_findings
        if _match_single_finding(f, search_text)
    )
    return matched / len(required_findings)


# ── Decision accuracy ──────────────────────────────────────


def _normalize_decision(decision: str) -> str:
    """Normalize decision string to canonical form."""
    if not decision:
        return ""
    d = decision.strip().lower()

    # Check if it's already a canonical form
    if d in _DECISION_SYNONYMS:
        return d

    # Check synonyms
    for canonical, synonyms in _DECISION_SYNONYMS.items():
        for syn in synonyms:
            if syn.lower() == d or syn == decision.strip():
                return canonical

    # Fallback: return stripped lowercase
    return d


def _score_decision_accuracy(
    output_json: dict,
    expected_decision: str,
) -> float:
    """Check decision matches expected with synonym normalization.

    Handles three levels of matching:
    1. Exact canonical match (1.0)
    2. Substring / partial canonical match (0.5)
    3. Synonym substring in raw decision text (0.5)
    """
    if not expected_decision:
        return 1.0

    actual = output_json.get("decision", "")
    if not actual:
        return 0.0

    norm_expected = _normalize_decision(expected_decision)
    norm_actual = _normalize_decision(str(actual))

    # Level 1: exact canonical match
    if norm_actual == norm_expected:
        return 1.0

    # Level 2: partial canonical match
    if norm_actual in norm_expected or norm_expected in norm_actual:
        return 0.5

    # Level 3: search for expected-decision synonyms in the raw text
    actual_str = str(actual).lower()
    expected_synonyms = _DECISION_SYNONYMS.get(norm_expected, [])
    # Sort longer synonyms first to prefer specific matches
    for syn in sorted(expected_synonyms, key=len, reverse=True):
        syn_lower = syn.lower()
        if len(syn_lower) >= 1 and syn_lower == actual_str:
            return 1.0
        if len(syn_lower) >= 2 and syn_lower in actual_str:
            return 0.5

    # Level 4: search for expected-decision keywords via CN/EN mapping
    # Handles cases like "发现疑似重复付款" when expected is "flag"
    for en_key, cn_values in _FINANCE_KEYWORD_MAP.items():
        if en_key in norm_expected.replace("_", " "):
            for cn in cn_values:
                if cn in actual_str:
                    return 0.3

    return 0.0


# ── Amount accuracy ────────────────────────────────────────


def _is_amount_applicable(
    expected_answer: dict[str, Any],
    exact_amounts: list[str],
) -> bool:
    """Return whether amount_accuracy is meaningful for this case."""
    amounts = expected_answer.get("amounts")
    if isinstance(amounts, dict):
        if exact_amounts:
            for key in exact_amounts:
                if isinstance(amounts.get(key), (int, float)):
                    return True
        if any(isinstance(v, (int, float)) for v in amounts.values()):
            return True
    if expected_answer.get("top_item") is not None:
        return True
    top_items = expected_answer.get("top_items")
    return isinstance(top_items, list) and len(top_items) > 0


def _normalize_match_text(value: str) -> str:
    """Normalize text for loose matching across model-specific JSON shapes."""
    lowered = value.lower()
    lowered = lowered.replace("＆", "&")
    lowered = re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff&]+", " ", lowered)
    return re.sub(r"\s+", " ", lowered).strip()


def _expected_item_text(item: dict[str, Any]) -> str:
    """Join non-numeric fields from an expected top item."""
    return " ".join(str(v) for v in item.values() if not isinstance(v, (int, float)))


def _candidate_text_matches_item(candidate_text: str, item: dict[str, Any]) -> bool:
    """Check whether candidate text contains the item's string identity."""
    expected_parts = [
        _normalize_match_text(str(v))
        for v in item.values()
        if isinstance(v, str) and str(v).strip()
    ]
    if not expected_parts:
        return True
    candidate_norm = _normalize_match_text(candidate_text)
    return all(part in candidate_norm for part in expected_parts)


def _iter_amount_candidates(obj: Any, path: str = "", depth: int = 0):
    """Yield (path_text, numeric_value) pairs from nested JSON."""
    if depth > 6:
        return
    if isinstance(obj, dict):
        for key, value in obj.items():
            key_text = f"{path} {key}".strip()
            if isinstance(value, (int, float)):
                yield key_text, float(value)
            else:
                yield from _iter_amount_candidates(value, key_text, depth + 1)
    elif isinstance(obj, list):
        for index, item in enumerate(obj):
            yield from _iter_amount_candidates(item, f"{path} {index}".strip(), depth + 1)


def _search_amount_for_expected_item(
    output_json: dict,
    expected_item: dict[str, Any],
    expected_amount: float,
    tolerance: float,
) -> bool:
    """Loose amount match for top_item/top_items across equivalent shapes.

    Example accepted:
    expected: {"dept": "R&D", "category": "Cloud", "variance_cny": 48000}
    output:   {"amounts": {"R&D Cloud": 48000}}
    """
    if _find_value_recursive(output_json, expected_amount, tolerance) is None:
        return False

    for path_text, value in _iter_amount_candidates(output_json):
        if abs(value - expected_amount) <= tolerance and _candidate_text_matches_item(
            path_text, expected_item
        ):
            return True

    return False


def _search_string_for_expected_item(
    output_json: dict,
    expected_item: dict[str, Any],
    expected_text: str,
) -> bool:
    """Loose string match for top_item/top_items across equivalent shapes."""
    expected_norm = _normalize_match_text(expected_text)
    if not expected_norm:
        return True

    all_text = _normalize_match_text(_extract_all_text(output_json))
    if expected_norm in all_text:
        return True

    item_text = _expected_item_text(expected_item)
    if item_text:
        for candidate_text, _ in _iter_amount_candidates(output_json):
            if _candidate_text_matches_item(candidate_text, expected_item):
                return True

    return False


def _find_amount_in_json(
    output_json: dict,
    key: str,
    tolerance: float = 0.01,
    expected_value: float | None = None,
) -> float | None:
    """Search for an amount key in the output JSON, returning its value or None.

    Searches recursively through nested dicts and lists.
    Falls back to value-based matching if key is not found.

    Handles amounts as:
    - dict: ``{"raw_total_cny": 775}``
    - scalar: ``{"amounts": 775}``
    - list: ``{"amounts": [775, 100]}``
    """
    amounts = output_json.get("amounts", {})

    # Direct lookup in amounts dict
    if isinstance(amounts, dict) and key in amounts:
        val = amounts[key]
        if isinstance(val, (int, float)):
            return float(val)

    # Recursive key search through entire JSON
    result = _search_amount_recursive(output_json, key, depth=0)
    if result is not None:
        return result

    # Fallback: value-based matching
    if expected_value is not None:
        # Search in amounts dict values
        if isinstance(amounts, dict):
            for v in amounts.values():
                if isinstance(v, (int, float)) and abs(float(v) - expected_value) <= tolerance:
                    return float(v)

        # Search in amounts scalar
        if isinstance(amounts, (int, float)) and abs(float(amounts) - expected_value) <= tolerance:
            return float(amounts)

        # Search in amounts list
        if isinstance(amounts, list):
            for v in amounts:
                if isinstance(v, (int, float)) and abs(float(v) - expected_value) <= tolerance:
                    return float(v)

        # Recursive value search through entire JSON
        found = _find_value_recursive(output_json, expected_value, tolerance, depth=0)
        if found is not None:
            return found

    return None


def _find_value_recursive(
    obj: Any,
    expected: float,
    tolerance: float,
    depth: int = 0,
) -> float | None:
    """Search for a numeric value matching expected within tolerance."""
    if depth > 5:
        return None
    if isinstance(obj, (int, float)) and abs(float(obj) - expected) <= tolerance:
        return float(obj)
    if isinstance(obj, dict):
        for v in obj.values():
            result = _find_value_recursive(v, expected, tolerance, depth + 1)
            if result is not None:
                return result
    elif isinstance(obj, list):
        for item in obj:
            result = _find_value_recursive(item, expected, tolerance, depth + 1)
            if result is not None:
                return result
    return None


def _search_amount_recursive(
    obj: Any,
    key: str,
    depth: int = 0,
) -> float | None:
    """Recursively search for a key with numeric value."""
    if depth > 5:
        return None

    if isinstance(obj, dict):
        if key in obj:
            val = obj[key]
            if isinstance(val, (int, float)):
                return float(val)
        for v in obj.values():
            result = _search_amount_recursive(v, key, depth + 1)
            if result is not None:
                return result
    elif isinstance(obj, list):
        for item in obj:
            result = _search_amount_recursive(item, key, depth + 1)
            if result is not None:
                return result

    return None


def _score_amount_accuracy(
    output_json: dict,
    expected_answer: dict[str, Any],
    exact_amounts: list[str],
    tolerance: float,
) -> float:
    """Score numeric amount accuracy.

    Supports:
    - expected_answer.amounts (flat dict)
    - expected_answer.top_item (single ranked item)
    - expected_answer.top_items (list of ranked items)
    """
    scores: list[float] = []

    # 1. Check exact_amounts from evaluation
    expected_amounts = expected_answer.get("amounts", {})
    if exact_amounts and expected_amounts:
        for key in exact_amounts:
            if key not in expected_amounts:
                continue
            expected_val = expected_amounts[key]
            if not isinstance(expected_val, (int, float)):
                continue
            actual_val = _find_amount_in_json(
                output_json, key, tolerance, expected_value=expected_val
            )
            if actual_val is not None and abs(actual_val - expected_val) <= tolerance:
                scores.append(1.0)
            else:
                scores.append(0.0)

    # 2. Check top_item if present
    top_item = expected_answer.get("top_item")
    if top_item and isinstance(top_item, dict):
        for key, expected_val in top_item.items():
            if isinstance(expected_val, (int, float)):
                # Search for the amount in output's top_item or similar
                actual = _search_amount_in_top_item(output_json, key, expected_val, tolerance)
                if not actual:
                    actual = _search_amount_for_expected_item(
                        output_json, top_item, expected_val, tolerance
                    )
                scores.append(1.0 if actual else 0.0)
            elif isinstance(expected_val, str):
                # String field like dept name
                actual = _search_string_in_top_item(output_json, key, expected_val)
                if not actual:
                    actual = _search_string_for_expected_item(
                        output_json, top_item, expected_val
                    )
                scores.append(1.0 if actual else 0.0)

    # 3. Check top_items if present
    top_items = expected_answer.get("top_items")
    if top_items and isinstance(top_items, list):
        for i, item in enumerate(top_items):
            if not isinstance(item, dict):
                continue
            for key, expected_val in item.items():
                if isinstance(expected_val, (int, float)):
                    actual = _search_amount_in_top_items_list(
                        output_json, i, key, expected_val, tolerance
                    )
                    if not actual:
                        actual = _search_amount_for_expected_item(
                            output_json, item, expected_val, tolerance
                        )
                    scores.append(1.0 if actual else 0.0)
                elif isinstance(expected_val, str):
                    actual = _search_string_in_top_items_list(
                        output_json, i, key, expected_val
                    )
                    if not actual:
                        actual = _search_string_for_expected_item(
                            output_json, item, expected_val
                        )
                    scores.append(1.0 if actual else 0.0)

    if not scores:
        return 1.0  # no amounts to check

    return sum(scores) / len(scores)


def _search_amount_in_top_item(
    output_json: dict,
    key: str,
    expected: float,
    tolerance: float,
) -> bool:
    """Search for an amount in the model's top_item output."""
    top_item = output_json.get("top_item")
    if isinstance(top_item, dict):
        val = top_item.get(key)
        if isinstance(val, (int, float)) and abs(val - expected) <= tolerance:
            return True
    # Also search in top_items[0]
    top_items = output_json.get("top_items", [])
    if isinstance(top_items, list) and top_items:
        first = top_items[0]
        if isinstance(first, dict):
            val = first.get(key)
            if isinstance(val, (int, float)) and abs(val - expected) <= tolerance:
                return True
    return False


def _search_string_in_top_item(
    output_json: dict,
    key: str,
    expected: str,
) -> bool:
    """Search for a string value in the model's top_item output."""
    top_item = output_json.get("top_item")
    if isinstance(top_item, dict):
        val = top_item.get(key, "")
        if isinstance(val, str) and val.strip().lower() == expected.strip().lower():
            return True
    top_items = output_json.get("top_items", [])
    if isinstance(top_items, list) and top_items:
        first = top_items[0]
        if isinstance(first, dict):
            val = first.get(key, "")
            if isinstance(val, str) and val.strip().lower() == expected.strip().lower():
                return True
    return False


def _search_amount_in_top_items_list(
    output_json: dict,
    index: int,
    key: str,
    expected: float,
    tolerance: float,
) -> bool:
    """Search for an amount at a specific index in top_items."""
    top_items = output_json.get("top_items", [])
    if isinstance(top_items, list) and index < len(top_items):
        item = top_items[index]
        if isinstance(item, dict):
            val = item.get(key)
            if isinstance(val, (int, float)) and abs(val - expected) <= tolerance:
                return True
    return False


def _search_string_in_top_items_list(
    output_json: dict,
    index: int,
    key: str,
    expected: str,
) -> bool:
    """Search for a string at a specific index in top_items."""
    top_items = output_json.get("top_items", [])
    if isinstance(top_items, list) and index < len(top_items):
        item = top_items[index]
        if isinstance(item, dict):
            val = item.get(key, "")
            if isinstance(val, str) and val.strip().lower() == expected.strip().lower():
                return True
    return False


# ── Evidence quality ───────────────────────────────────────


def _score_evidence_quality(
    output_json: dict,
    artifacts: list[str],
    input_context: str = "",
) -> float:
    """Score evidence quality by checking references to:
    1. Artifact filenames
    2. Business IDs from input_context (ER-, AP-, B-, L-, INV-, etc.)
    3. Policy keywords
    """
    evidence = output_json.get("evidence", [])
    if isinstance(evidence, list):
        evidence_text = " ".join(str(e) for e in evidence)
    else:
        evidence_text = str(evidence) if evidence else ""

    all_text = (evidence_text + " " + _extract_all_text(output_json)).strip()
    if not all_text:
        return 0.0

    # Check 1: artifact filenames
    artifact_available = bool(artifacts)
    artifact_found = False
    for artifact in artifacts:
        # Extract filename without path
        filename = artifact.split("/")[-1] if "/" in artifact else artifact
        # Also check without extension
        name_no_ext = filename.rsplit(".", 1)[0] if "." in filename else filename
        artifact_found = artifact_found or (
            filename.lower() in all_text.lower()
            or name_no_ext.lower() in all_text.lower()
        )

    # Check 2: business IDs from input_context
    ids_in_context: list[str] = []
    if input_context:
        for pattern in _BUSINESS_ID_PATTERNS:
            ids_in_context.extend(pattern.findall(input_context))
    id_available = bool(ids_in_context)
    id_found = any(bid in all_text for bid in ids_in_context)

    # Check 3: policy keywords
    policy_keywords_in_context: list[str] = []
    for kw in _POLICY_KEYWORDS:
        if kw.lower() in input_context.lower():
            policy_keywords_in_context.append(kw)
    policy_available = bool(policy_keywords_in_context)
    policy_found = any(kw.lower() in all_text.lower() for kw in policy_keywords_in_context)

    # Do not require citing every ID in a large table. Evidence should be present,
    # anchored to at least one relevant business object, and preferably cite policy
    # or source artifact when those are applicable.
    score = 0.4
    score += 0.25 if (not id_available or id_found) else 0.0
    score += 0.20 if (not policy_available or policy_found) else 0.0
    score += 0.15 if (not artifact_available or artifact_found) else 0.0
    return min(score, 1.0)


# ── Forbidden findings penalty ─────────────────────────────


def _apply_forbidden_findings_penalty(
    output_json: dict,
    forbidden_findings: list[str],
    score: float,
) -> tuple[float, dict[str, Any]]:
    """Deduct score for forbidden (hallucinated) findings."""
    if not forbidden_findings:
        return score, {}

    all_text = _extract_all_text(output_json)
    all_text_lower = all_text.lower()

    penalties: list[str] = []
    for forbidden in forbidden_findings:
        if forbidden.lower() in all_text_lower:
            penalties.append(forbidden)

    total_penalty = min(0.10 * len(penalties), 0.50)
    adjusted = max(0.0, score - total_penalty)

    details: dict[str, Any] = {}
    if penalties:
        details = {
            "forbidden_found": penalties,
            "penalty": total_penalty,
        }

    return adjusted, details


# ── Main scoring function ──────────────────────────────────


# ── Result-type task decision scoring ──────────────────────

_RESULT_TYPE_TASKS = frozenset({"calculate", "rank", "summarize", "classify", "prioritize"})


def _score_rank_decision(
    output_json: dict,
    expected_answer: dict[str, Any],
    amount_accuracy: float,
    amount_applicable: bool,
) -> float:
    """Score rank/prioritize decision using amount_accuracy as primary signal.

    Many models put Top-N results in an ``amounts`` array rather than a
    ``top_items`` field, so amount_accuracy already captures whether the
    ranking is correct.  Explicit top_item / top_items matching provides
    supplementary credit.
    """
    base_score = amount_accuracy if amount_applicable else 0.0

    expected_top = expected_answer.get("top_item")
    expected_items = expected_answer.get("top_items", [])
    actual_top = output_json.get("top_item")
    actual_items = output_json.get("top_items") or output_json.get("ranking")

    explicit_score = 0.0
    if expected_top and actual_top:
        if str(actual_top).lower() == str(expected_top).lower():
            explicit_score = max(explicit_score, 1.0)
        elif str(expected_top).lower() in str(actual_top).lower():
            explicit_score = max(explicit_score, 0.5)

    if expected_items and isinstance(actual_items, list):
        matched = 0.0
        for i, exp in enumerate(expected_items):
            if i < len(actual_items):
                if str(actual_items[i]).lower() == str(exp).lower():
                    matched += 1.0
                elif str(exp).lower() in str(actual_items[i]).lower():
                    matched += 0.5
        explicit_score = max(explicit_score, matched / len(expected_items))

    return max(base_score, explicit_score)


def finance_auto_score(case: FinanceCase, output: str) -> ScoreResult:
    """Main entry point: score a finance benchmark case output.

    Returns ScoreResult with overall_score and dimension_scores.
    """
    # 1. Determine weight configuration
    weights = POLICY_QA_WEIGHTS if case.is_policy_qa else STANDARD_WEIGHTS

    # 2. Parse JSON once
    parsed_json, json_validity_score = _parse_finance_json(output)
    required_fields = case.output_format.get("required_fields", [])

    # Check required fields presence for json_validity
    if parsed_json and required_fields:
        fields_present = sum(
            1 for f in required_fields if f in parsed_json
        )
        field_ratio = fields_present / len(required_fields)
        # Blend: 70% parse success + 30% field completeness
        json_validity = json_validity_score * (0.7 + 0.3 * field_ratio)
    else:
        json_validity = json_validity_score

    # 3. Score each dimension
    amount_applicable = _is_amount_applicable(case.expected_answer, case.exact_amounts)
    if parsed_json and amount_applicable:
        amount_accuracy = _score_amount_accuracy(
            parsed_json,
            case.expected_answer,
            case.exact_amounts,
            case.numeric_tolerance,
        )
    elif parsed_json and not amount_applicable:
        # Not applicable should not penalize the overall weighted score.
        # Aggregate reports filter these out via dimension_applicability.
        amount_accuracy = 1.0
    else:
        amount_accuracy = 0.0  # JSON parse failed

    if parsed_json:
        # Merge required_findings from evaluation and expected_answer
        eval_findings = case.required_findings
        expected_findings = case.expected_answer.get("required_findings", [])
        all_findings: list[str] = list(eval_findings)
        if isinstance(expected_findings, list):
            for f in expected_findings:
                if f not in all_findings:
                    all_findings.append(f)
        finding_recall = _score_finding_recall(parsed_json, all_findings)
        decision_accuracy = _score_decision_accuracy(
            parsed_json, case.expected_answer.get("decision", "")
        )
        evidence_quality = _score_evidence_quality(
            parsed_json, case.artifacts, case.input_context
        )
    else:
        finding_recall = 0.0
        decision_accuracy = 0.0
        evidence_quality = 0.0

    # 4. Override decision_accuracy for result-type tasks
    #    (calculate/rank/summarize/classify/prioritize depend on business correctness,
    #    not on matching a fixed action label)
    if parsed_json:
        expected_decision = case.expected_answer.get("decision", "")
        norm_decision = _normalize_decision(expected_decision)
        if norm_decision in _RESULT_TYPE_TASKS:
            if norm_decision == "calculate":
                if amount_applicable:
                    decision_accuracy = amount_accuracy
                else:
                    decision_accuracy = min(finding_recall, evidence_quality * 2)
            elif norm_decision in ("rank", "prioritize"):
                decision_accuracy = _score_rank_decision(
                    parsed_json, case.expected_answer,
                    amount_accuracy, amount_applicable,
                )
            elif norm_decision in ("summarize", "classify"):
                decision_accuracy = min(finding_recall, evidence_quality * 2)

    # 5. Compute weighted overall
    dim_scores = {
        "json_validity": json_validity,
        "amount_accuracy": amount_accuracy,
        "finding_recall": finding_recall,
        "decision_accuracy": decision_accuracy,
        "evidence_quality": evidence_quality,
    }
    overall = sum(dim_scores[k] * weights[k] for k in weights)

    # 5. Apply forbidden_findings penalty
    details: dict[str, Any] = {
        "dimension_applicability": {
            "json_validity": True,
            "amount_accuracy": amount_applicable,
            "finding_recall": True,
            "decision_accuracy": bool(case.expected_answer.get("decision", "")),
            "evidence_quality": True,
        }
    }
    if case.forbidden_findings and parsed_json:
        overall, penalty_details = _apply_forbidden_findings_penalty(
            parsed_json, case.forbidden_findings, overall
        )
        if penalty_details:
            details["forbidden_penalty"] = penalty_details

    # Clamp to [0, 1]
    overall = max(0.0, min(1.0, overall))

    return ScoreResult(
        scoring_type=case.scoring_type,
        overall_score=overall,
        dimension_scores=dim_scores,
        details=details,
    )
