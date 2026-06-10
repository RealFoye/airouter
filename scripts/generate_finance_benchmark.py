"""Generate synthetic enterprise finance benchmark cases.

The data is intentionally fictional. It borrows task shapes from public
finance/document/spreadsheet benchmarks, but does not copy their cases or use
company-internal data.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "data" / "benchmarks" / "finance"
ARTIFACTS = OUT_DIR / "artifacts"


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.strip() + "\n", encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def case(
    case_id: str,
    category: str,
    complexity: str,
    prompt: str,
    input_context: str,
    expected_answer: dict[str, Any],
    evaluation: dict[str, Any],
    artifacts: list[str],
    tags: list[str],
    notes: str,
) -> dict[str, Any]:
    return {
        "id": case_id,
        "domain": "FINANCE_OFFICE",
        "category": category,
        "task_type": "DATA_PROCESSING",
        "complexity": complexity,
        "prompt": prompt,
        "input_context": input_context.strip(),
        "artifacts": artifacts,
        "output_format": {
            "type": "json",
            "required_fields": [
                "decision",
                "amounts",
                "findings",
                "evidence",
                "confidence",
            ],
        },
        "expected_answer": expected_answer,
        "evaluation": evaluation,
        "max_tokens": 8192 if complexity in {"SIMPLE", "MODERATE"} else 12288,
        "tags": tags,
        "notes": notes,
    }


def main() -> None:
    travel_policy = """
# 差旅及费用报销制度（Synthetic）

适用范围：员工差旅、客户拜访、培训及项目执行费用报销。

## 发票与时限
- 发票抬头必须为“广州视源电子科技股份有限公司”，个人抬头不可报销。
- 报销应在费用发生后 30 天内提交，逾期需部门负责人审批；本 benchmark 中无审批附件时按不可报销处理。
- 同一发票号码不得重复报销。

## 住宿
- 一线城市（北京、上海、广州、深圳）住宿标准上限为 600 元/晚。
- 其他城市住宿标准上限为 450 元/晚。
- 超出标准部分不可报销。

## 餐费
- 员工个人餐费上限为 120 元/人/天。
- 客户招待餐费上限为 200 元/人/次，必须填写客户人数和业务目的。
- 酒水、私人聚餐不可报销。

## 交通
- 市内出租车单次 100 元以内可直接报销，超过 100 元需说明路线并经主管审批；无审批附件时超出部分不可报销。
- 机票仅报销经济舱。发票抬头不合规时整笔机票不可报销。
"""

    ap_policy = """
# 采购付款与三单匹配制度（Synthetic）

## 三单匹配
- 合同、采购订单、发票、验收记录的供应商、金额、税率、币种必须一致。
- 按数量验收的采购，付款金额不得超过已验收数量对应金额。
- 发票金额超过合同/PO/验收可付款金额时，应拒绝付款或仅按可付款金额部分付款。

## 付款条件
- 合同写明“验收后付款”的，必须有验收记录才可付款。
- 合同写明“签约预付款”的，可按合同约定比例付款。
- 供应商银行账户变更时，必须有供应商主数据变更审批。

## 审批阈值
- 单笔付款 50,000 元以上需要财务经理审批。
- 单笔付款 100,000 元以上需要 CFO 审批。
"""

    budget_policy = """
# 预算控制制度（Synthetic）

- 预算执行差异同时满足“超预算率 > 10%”且“超预算金额 > 10,000 元”时，必须提交预算调整说明。
- 单项费用超预算率 > 30% 视为高风险异常。
- 预算分析报告必须列出前三大超支项、原因假设和建议动作。
"""

    write_text(ARTIFACTS / "policies" / "travel_policy.md", travel_policy)
    write_text(ARTIFACTS / "policies" / "ap_policy.md", ap_policy)
    write_text(ARTIFACTS / "policies" / "budget_policy.md", budget_policy)

    expense_rows = [
        {"claim_id": "ER-1001", "employee": "Zhang Wei", "dept": "Sales", "date": "2026-05-08", "category": "hotel", "city": "Shanghai", "amount_cny": 680.00, "invoice_no": "INV-H-1001", "invoice_title": "广州视源电子科技股份有限公司", "attendees": "", "purpose": "client visit"},
        {"claim_id": "ER-1001", "employee": "Zhang Wei", "dept": "Sales", "date": "2026-05-08", "category": "client_meal", "city": "Shanghai", "amount_cny": 420.00, "invoice_no": "INV-M-1001", "invoice_title": "广州视源电子科技股份有限公司", "attendees": "2", "purpose": "client dinner"},
        {"claim_id": "ER-1001", "employee": "Zhang Wei", "dept": "Sales", "date": "2026-05-08", "category": "taxi", "city": "Shanghai", "amount_cny": 95.00, "invoice_no": "INV-T-1001", "invoice_title": "广州视源电子科技股份有限公司", "attendees": "", "purpose": "airport to hotel"},
        {"claim_id": "ER-1002", "employee": "Li Na", "dept": "R&D", "date": "2026-05-12", "category": "flight", "city": "Guangzhou-Beijing", "amount_cny": 1580.00, "invoice_no": "INV-F-2001", "invoice_title": "李娜", "attendees": "", "purpose": "project review"},
        {"claim_id": "ER-1002", "employee": "Li Na", "dept": "R&D", "date": "2026-05-12", "category": "hotel", "city": "Beijing", "amount_cny": 520.00, "invoice_no": "INV-H-2001", "invoice_title": "广州视源电子科技股份有限公司", "attendees": "", "purpose": "project review"},
        {"claim_id": "ER-1003", "employee": "Chen Hao", "dept": "Finance", "date": "2026-05-20", "category": "training_meal", "city": "Hangzhou", "amount_cny": 180.00, "invoice_no": "INV-M-3001", "invoice_title": "广州视源电子科技股份有限公司", "attendees": "1", "purpose": "training"},
        {"claim_id": "ER-1003", "employee": "Chen Hao", "dept": "Finance", "date": "2026-05-20", "category": "hotel", "city": "Hangzhou", "amount_cny": 430.00, "invoice_no": "INV-H-3001", "invoice_title": "广州视源电子科技股份有限公司", "attendees": "", "purpose": "training"},
        {"claim_id": "ER-1004", "employee": "Wang Min", "dept": "Sales", "date": "2026-05-22", "category": "taxi", "city": "Shenzhen", "amount_cny": 88.00, "invoice_no": "INV-T-4001", "invoice_title": "广州视源电子科技股份有限公司", "attendees": "", "purpose": "customer site"},
        {"claim_id": "ER-1004", "employee": "Wang Min", "dept": "Sales", "date": "2026-05-22", "category": "taxi", "city": "Shenzhen", "amount_cny": 88.00, "invoice_no": "INV-T-4001", "invoice_title": "广州视源电子科技股份有限公司", "attendees": "", "purpose": "duplicate copy"},
        {"claim_id": "ER-1004", "employee": "Wang Min", "dept": "Sales", "date": "2026-05-22", "category": "client_meal", "city": "Shenzhen", "amount_cny": 360.00, "invoice_no": "INV-M-4001", "invoice_title": "广州视源电子科技股份有限公司", "attendees": "1", "purpose": ""},
        {"claim_id": "ER-1005", "employee": "Liu Fang", "dept": "HR", "date": "2026-04-01", "category": "hotel", "city": "Chengdu", "amount_cny": 470.00, "invoice_no": "INV-H-5001", "invoice_title": "广州视源电子科技股份有限公司", "attendees": "", "purpose": "campus hiring"},
        {"claim_id": "ER-1005", "employee": "Liu Fang", "dept": "HR", "date": "2026-04-01", "category": "taxi", "city": "Chengdu", "amount_cny": 132.00, "invoice_no": "INV-T-5001", "invoice_title": "广州视源电子科技股份有限公司", "attendees": "", "purpose": "hotel to university, no approval"},
    ]
    write_csv(ARTIFACTS / "expenses" / "expense_claims_may.csv", expense_rows)

    ap_rows = [
        {"contract_id": "CT-2026-014", "po_id": "PO-5001", "invoice_no": "AP-9001", "vendor": "Huaxin Cloud", "contract_amount_ex_tax": 120000.00, "tax_rate": 0.06, "invoice_amount_inc_tax": 63600.00, "received_qty": "", "contract_qty": "", "payment_condition": "50% after acceptance", "acceptance_status": "accepted"},
        {"contract_id": "CT-2026-015", "po_id": "PO-5002", "invoice_no": "AP-9002", "vendor": "Anji Furniture", "contract_amount_ex_tax": 64000.00, "tax_rate": 0.13, "invoice_amount_inc_tax": 72800.00, "received_qty": "200", "contract_qty": "200", "payment_condition": "100% after delivery", "acceptance_status": "accepted"},
        {"contract_id": "CT-2026-016", "po_id": "PO-5003", "invoice_no": "AP-9003", "vendor": "Nanfang Tech", "contract_amount_ex_tax": 50000.00, "tax_rate": 0.06, "invoice_amount_inc_tax": 53000.00, "received_qty": "", "contract_qty": "", "payment_condition": "after acceptance", "acceptance_status": "vendor mismatch: contract vendor is Nanfang Consulting"},
        {"contract_id": "CT-2026-017", "po_id": "PO-5004", "invoice_no": "AP-9004", "vendor": "Yida Hardware", "contract_amount_ex_tax": 98000.00, "tax_rate": 0.13, "invoice_amount_inc_tax": 110740.00, "received_qty": "96", "contract_qty": "100", "payment_condition": "pay by accepted quantity", "acceptance_status": "accepted 96 units"},
        {"contract_id": "CT-2026-018", "po_id": "PO-5005", "invoice_no": "AP-9005", "vendor": "North Star SaaS", "contract_amount_ex_tax": 240000.00, "tax_rate": 0.06, "invoice_amount_inc_tax": 63600.00, "received_qty": "", "contract_qty": "", "payment_condition": "25% signing prepayment", "acceptance_status": "contract signed"},
        {"contract_id": "CT-2026-019", "po_id": "PO-5006", "invoice_no": "AP-9006", "vendor": "Donghai Logistics", "contract_amount_ex_tax": 30000.00, "tax_rate": 0.09, "invoice_amount_inc_tax": 32700.00, "received_qty": "", "contract_qty": "", "payment_condition": "after acceptance", "acceptance_status": "not accepted"},
    ]
    write_csv(ARTIFACTS / "ap" / "three_way_match.csv", ap_rows)

    bank_rows = [
        {"bank_id": "B-001", "date": "2026-05-03", "counterparty": "Customer A", "amount_cny": 150000.00, "reference": "AR-8001"},
        {"bank_id": "B-002", "date": "2026-05-21", "counterparty": "Huaxin Cloud", "amount_cny": -63600.00, "reference": "AP-9001"},
        {"bank_id": "B-003", "date": "2026-05-31", "counterparty": "Bank Service Fee", "amount_cny": -35.00, "reference": "FEE-MAY"},
        {"bank_id": "B-004", "date": "2026-05-19", "counterparty": "Guangfa Travel", "amount_cny": -28000.00, "reference": "TR-7788"},
        {"bank_id": "B-005", "date": "2026-05-28", "counterparty": "Customer B", "amount_cny": 50000.00, "reference": "UNKNOWN"},
        {"bank_id": "B-006", "date": "2026-05-25", "counterparty": "Anji Furniture", "amount_cny": -72320.00, "reference": "AP-9002"},
        {"bank_id": "B-007", "date": "2026-05-26", "counterparty": "Office Depot", "amount_cny": -8800.00, "reference": "OD-1122"},
        {"bank_id": "B-008", "date": "2026-05-26", "counterparty": "Office Depot", "amount_cny": -8800.00, "reference": "OD-1122"},
    ]
    ledger_rows = [
        {"ledger_id": "L-010", "date": "2026-05-03", "counterparty": "Customer A", "amount_cny": 150000.00, "reference": "AR-8001"},
        {"ledger_id": "L-011", "date": "2026-05-21", "counterparty": "Huaxin Cloud", "amount_cny": -63600.00, "reference": "AP-9001"},
        {"ledger_id": "L-012", "date": "2026-05-19", "counterparty": "Guangfa Travel", "amount_cny": -28000.00, "reference": "TR-7788"},
        {"ledger_id": "L-013", "date": "2026-05-25", "counterparty": "Anji Furniture", "amount_cny": -72800.00, "reference": "AP-9002"},
        {"ledger_id": "L-014", "date": "2026-05-27", "counterparty": "Training Vendor", "amount_cny": -12500.00, "reference": "TRN-0601"},
        {"ledger_id": "L-015", "date": "2026-05-26", "counterparty": "Office Depot", "amount_cny": -8800.00, "reference": "OD-1122"},
    ]
    write_csv(ARTIFACTS / "bank" / "bank_statement_may.csv", bank_rows)
    write_csv(ARTIFACTS / "bank" / "ledger_may.csv", ledger_rows)

    budget_rows = [
        {"dept": "Sales", "category": "Travel", "budget_cny": 80000.00, "actual_cny": 98000.00, "owner_note": "more customer visits"},
        {"dept": "Sales", "category": "Entertainment", "budget_cny": 35000.00, "actual_cny": 52000.00, "owner_note": "new distributor campaign"},
        {"dept": "R&D", "category": "Cloud", "budget_cny": 120000.00, "actual_cny": 168000.00, "owner_note": "model experiments"},
        {"dept": "R&D", "category": "Training", "budget_cny": 20000.00, "actual_cny": 12000.00, "owner_note": "vendor discount"},
        {"dept": "Finance", "category": "Software", "budget_cny": 30000.00, "actual_cny": 34000.00, "owner_note": "extra seats"},
        {"dept": "HR", "category": "Recruitment", "budget_cny": 15000.00, "actual_cny": 26000.00, "owner_note": "campus fair"},
        {"dept": "Operations", "category": "Logistics", "budget_cny": 90000.00, "actual_cny": 87000.00, "owner_note": "stable"},
        {"dept": "IT", "category": "Hardware", "budget_cny": 50000.00, "actual_cny": 64500.00, "owner_note": "laptop refresh"},
    ]
    write_csv(ARTIFACTS / "budget" / "budget_actual_may.csv", budget_rows)

    table_context = """
费用表 expense_claims_may.csv：
ER-1001: hotel Shanghai 680; client_meal 420 with 2 attendees; taxi 95.
ER-1002: flight Guangzhou-Beijing 1580 with personal invoice title 李娜; hotel Beijing 520.
ER-1003: training_meal Hangzhou 180 with 1 attendee; hotel Hangzhou 430.
ER-1004: taxi 88 invoice INV-T-4001 appears twice; client_meal 360 with 1 attendee and empty purpose.
ER-1005: hotel Chengdu 470; taxi Chengdu 132, no approval.
"""
    ap_context = """
三单匹配表 three_way_match.csv：
AP-9001 Huaxin Cloud: contract ex-tax 120000, VAT 6%, invoice inc-tax 63600, condition 50% after acceptance, accepted.
AP-9002 Anji Furniture: contract ex-tax 64000, VAT 13%, invoice inc-tax 72800, accepted 200/200 chairs.
AP-9003 Nanfang Tech: contract vendor is Nanfang Consulting, invoice vendor is Nanfang Tech, invoice inc-tax 53000.
AP-9004 Yida Hardware: 100 units at total ex-tax 98000, VAT 13%, accepted 96 units, invoice inc-tax 110740.
AP-9005 North Star SaaS: contract ex-tax 240000, VAT 6%, invoice inc-tax 63600, 25% signing prepayment, signed.
AP-9006 Donghai Logistics: ex-tax 30000, VAT 9%, invoice inc-tax 32700, not accepted.
"""
    bank_context = """
银行流水 bank_statement_may.csv 与账簿 ledger_may.csv：
B-001 AR-8001 +150000 matches L-010.
B-002 AP-9001 -63600 matches L-011.
B-003 FEE-MAY -35 has no ledger entry.
B-004 TR-7788 -28000 matches L-012.
B-005 UNKNOWN +50000 has no ledger entry.
B-006 AP-9002 -72320; ledger L-013 records -72800.
B-007 and B-008 both OD-1122 -8800; ledger has one L-015 -8800.
Ledger L-014 TRN-0601 -12500 has no bank entry.
"""
    budget_context = """
预算表 budget_actual_may.csv：
Sales Travel budget 80000 actual 98000.
Sales Entertainment budget 35000 actual 52000.
R&D Cloud budget 120000 actual 168000.
R&D Training budget 20000 actual 12000.
Finance Software budget 30000 actual 34000.
HR Recruitment budget 15000 actual 26000.
Operations Logistics budget 90000 actual 87000.
IT Hardware budget 50000 actual 64500.
预算制度：超预算率 > 10% 且超预算金额 > 10000 需要预算调整说明；超预算率 > 30% 为高风险异常。
"""

    common_eval = {
        "primary": "rule_based",
        "numeric_tolerance": 0.01,
        "penalize_hallucinated_findings": True,
        "evidence_required": True,
    }

    cases: list[dict[str, Any]] = []

    # Table calculation
    cases.extend([
        case("FIN-TAB-001", "TABLE_CALCULATION", "SIMPLE", "根据费用表计算 ER-1001 的原始合计金额。只输出 JSON。", table_context, {"amounts": {"raw_total_cny": 1195.00}, "required_findings": [], "decision": "calculate"}, {**common_eval, "scoring_type": "finance_numeric", "exact_amounts": ["raw_total_cny"]}, ["artifacts/expenses/expense_claims_may.csv"], ["spreadsheet", "sum"], "基础合计，类似 SpreadsheetBench 的表格聚合任务。"),
        case("FIN-TAB-002", "TABLE_CALCULATION", "MODERATE", "按部门汇总费用表中的原始报销金额，并找出金额最高的部门。只输出 JSON。", table_context, {"amounts": {"Sales": 1731.00, "R&D": 2100.00, "Finance": 610.00, "HR": 602.00}, "top_item": {"dept": "R&D", "amount_cny": 2100.00}, "decision": "calculate"}, {**common_eval, "scoring_type": "finance_groupby", "exact_amounts": ["Sales", "R&D", "Finance", "HR"]}, ["artifacts/expenses/expense_claims_may.csv"], ["spreadsheet", "groupby"], "部门维度分类汇总。"),
        case("FIN-TAB-003", "TABLE_CALCULATION", "MODERATE", "根据差旅制度，计算 ER-1001 可报销金额、不可报销金额，并列出原因。只输出 JSON。", travel_policy + "\n" + table_context, {"amounts": {"approved_amount_cny": 1095.00, "rejected_amount_cny": 100.00}, "required_findings": ["hotel_over_limit_80", "client_meal_over_limit_20"], "decision": "partial_approve"}, {**common_eval, "scoring_type": "finance_policy_numeric", "exact_amounts": ["approved_amount_cny", "rejected_amount_cny"], "required_findings": ["hotel_over_limit_80", "client_meal_over_limit_20"]}, ["artifacts/policies/travel_policy.md", "artifacts/expenses/expense_claims_may.csv"], ["policy", "reimbursement"], "计算+制度套用。"),
        case("FIN-TAB-004", "TABLE_CALCULATION", "MODERATE", "找出费用表中所有重复发票号，并计算重复报销风险金额。只输出 JSON。", table_context, {"amounts": {"duplicate_risk_amount_cny": 88.00}, "required_findings": ["INV-T-4001 duplicated in ER-1004"], "decision": "flag"}, {**common_eval, "scoring_type": "finance_duplicate", "exact_amounts": ["duplicate_risk_amount_cny"], "required_findings": ["INV-T-4001"]}, ["artifacts/expenses/expense_claims_may.csv"], ["duplicate", "invoice"], "重复发票检测。"),
        case("FIN-TAB-005", "TABLE_CALCULATION", "COMPLEX", "对所有报销单应用差旅制度，计算每个 claim_id 的可报销金额。只输出 JSON。", travel_policy + "\n" + table_context, {"amounts": {"ER-1001": 1095.00, "ER-1002": 520.00, "ER-1003": 550.00, "ER-1004": 88.00, "ER-1005": 550.00}, "decision": "calculate"}, {**common_eval, "scoring_type": "finance_batch_policy", "exact_amounts": ["ER-1001", "ER-1002", "ER-1003", "ER-1004", "ER-1005"]}, ["artifacts/policies/travel_policy.md", "artifacts/expenses/expense_claims_may.csv"], ["batch", "policy"], "批量规则计算。"),
        case("FIN-TAB-006", "TABLE_CALCULATION", "COMPLEX", "按 claim_id 计算原始金额与可报销金额差异，找出差异最大的报销单。只输出 JSON。", travel_policy + "\n" + table_context, {"amounts": {"largest_gap_cny": 1580.00}, "top_item": {"claim_id": "ER-1002", "reason": "personal invoice title flight rejected"}, "decision": "calculate"}, {**common_eval, "scoring_type": "finance_variance", "exact_amounts": ["largest_gap_cny"], "required_findings": ["ER-1002"]}, ["artifacts/policies/travel_policy.md", "artifacts/expenses/expense_claims_may.csv"], ["variance", "policy"], "找最大差异和原因。"),
    ])

    # Reimbursement audit
    cases.extend([
        case("FIN-EXP-001", "REIMBURSEMENT_AUDIT", "MODERATE", "审核 ER-1002，判断是否可报销并给出批准金额和违规项。只输出 JSON。", travel_policy + "\n" + table_context, {"amounts": {"approved_amount_cny": 520.00, "rejected_amount_cny": 1580.00}, "required_findings": ["flight_personal_invoice_title"], "decision": "partial_approve"}, {**common_eval, "scoring_type": "finance_reimbursement", "exact_amounts": ["approved_amount_cny", "rejected_amount_cny"], "required_findings": ["personal invoice", "李娜"]}, ["artifacts/policies/travel_policy.md", "artifacts/expenses/expense_claims_may.csv"], ["reimbursement", "invoice_title"], "个人抬头整笔机票拒绝。"),
        case("FIN-EXP-002", "REIMBURSEMENT_AUDIT", "SIMPLE", "审核 ER-1003，计算可报销金额。只输出 JSON。", travel_policy + "\n" + table_context, {"amounts": {"approved_amount_cny": 550.00, "rejected_amount_cny": 60.00}, "required_findings": ["training_meal_over_personal_limit_60"], "decision": "partial_approve"}, {**common_eval, "scoring_type": "finance_reimbursement", "exact_amounts": ["approved_amount_cny", "rejected_amount_cny"], "required_findings": ["meal over limit", "60"]}, ["artifacts/policies/travel_policy.md", "artifacts/expenses/expense_claims_may.csv"], ["reimbursement", "meal"], "个人餐费限额。"),
        case("FIN-EXP-003", "REIMBURSEMENT_AUDIT", "COMPLEX", "审核 ER-1004：注意重复发票、客户餐费人数和业务目的。给出批准金额。只输出 JSON。", travel_policy + "\n" + table_context, {"amounts": {"approved_amount_cny": 88.00, "rejected_amount_cny": 448.00}, "required_findings": ["duplicate_invoice_INV-T-4001", "client_meal_missing_purpose_or_over_limit"], "decision": "partial_approve"}, {**common_eval, "scoring_type": "finance_reimbursement", "exact_amounts": ["approved_amount_cny", "rejected_amount_cny"], "required_findings": ["duplicate", "missing purpose"]}, ["artifacts/policies/travel_policy.md", "artifacts/expenses/expense_claims_may.csv"], ["reimbursement", "duplicate"], "多规则叠加。"),
        case("FIN-EXP-004", "REIMBURSEMENT_AUDIT", "MODERATE", "审核 ER-1005，判断住宿和出租车分别能报多少。只输出 JSON。", travel_policy + "\n" + table_context, {"amounts": {"approved_amount_cny": 550.00, "rejected_amount_cny": 52.00}, "required_findings": ["chengdu_hotel_cap_450", "taxi_over_100_no_approval"], "decision": "partial_approve"}, {**common_eval, "scoring_type": "finance_reimbursement", "exact_amounts": ["approved_amount_cny", "rejected_amount_cny"], "required_findings": ["450", "taxi"]}, ["artifacts/policies/travel_policy.md", "artifacts/expenses/expense_claims_may.csv"], ["reimbursement", "cap"], "非一线城市住宿上限+出租车上限。"),
        case("FIN-EXP-005", "REIMBURSEMENT_AUDIT", "COMPLEX", "从费用表中找出所有应触发人工审核或拒绝的项目，按严重程度排序。只输出 JSON。", travel_policy + "\n" + table_context, {"required_findings": ["ER-1002 personal invoice title", "ER-1004 duplicated invoice", "ER-1004 missing client meal purpose", "ER-1005 taxi over limit no approval"], "decision": "flag"}, {**common_eval, "scoring_type": "finance_risk_list", "required_findings": ["ER-1002", "ER-1004", "ER-1005"]}, ["artifacts/policies/travel_policy.md", "artifacts/expenses/expense_claims_may.csv"], ["risk", "audit"], "风险列表召回。"),
        case("FIN-EXP-006", "REIMBURSEMENT_AUDIT", "EXPERT", "请输出一份报销审核 JSON 汇总：总原始金额、总可报销金额、总拒绝金额、每个拒绝原因的金额影响。只输出 JSON。", travel_policy + "\n" + table_context, {"amounts": {"raw_total_cny": 5043.00, "approved_total_cny": 2803.00, "rejected_total_cny": 2240.00}, "required_findings": ["personal_invoice_title_1580", "over_limits", "duplicate_invoice", "missing_purpose"], "decision": "summarize"}, {**common_eval, "scoring_type": "finance_audit_summary", "exact_amounts": ["raw_total_cny", "approved_total_cny", "rejected_total_cny"], "required_findings": ["1580", "duplicate", "missing purpose"]}, ["artifacts/policies/travel_policy.md", "artifacts/expenses/expense_claims_may.csv"], ["summary", "audit"], "端到端报销审核汇总。"),
    ])

    # AP matching
    cases.extend([
        case("FIN-AP-001", "AP_THREE_WAY_MATCH", "MODERATE", "审核 AP-9001 是否满足付款条件，计算可付款金额和审批要求。只输出 JSON。", ap_policy + "\n" + ap_context, {"amounts": {"payable_amount_cny": 63600.00}, "required_findings": ["accepted", "finance_manager_approval_required"], "decision": "approve_with_approval"}, {**common_eval, "scoring_type": "finance_ap_match", "exact_amounts": ["payable_amount_cny"], "required_findings": ["accepted", "50000"]}, ["artifacts/policies/ap_policy.md", "artifacts/ap/three_way_match.csv"], ["ap", "approval"], "验收后 50% 付款。"),
        case("FIN-AP-002", "AP_THREE_WAY_MATCH", "MODERATE", "审核 AP-9002，判断发票金额是否与合同/PO一致，给出差异。只输出 JSON。", ap_policy + "\n" + ap_context, {"amounts": {"expected_invoice_amount_cny": 72320.00, "over_billed_cny": 480.00}, "required_findings": ["invoice_over_billed_480"], "decision": "reject_or_adjust"}, {**common_eval, "scoring_type": "finance_ap_match", "exact_amounts": ["expected_invoice_amount_cny", "over_billed_cny"], "required_findings": ["480"]}, ["artifacts/policies/ap_policy.md", "artifacts/ap/three_way_match.csv"], ["ap", "tax"], "税额金额差异。"),
        case("FIN-AP-003", "AP_THREE_WAY_MATCH", "MODERATE", "审核 AP-9003，重点检查供应商一致性。只输出 JSON。", ap_policy + "\n" + ap_context, {"amounts": {"payable_amount_cny": 0.00}, "required_findings": ["vendor_mismatch_Nanfang_Tech_vs_Nanfang_Consulting"], "decision": "reject"}, {**common_eval, "scoring_type": "finance_ap_match", "exact_amounts": ["payable_amount_cny"], "required_findings": ["vendor mismatch", "Nanfang"]}, ["artifacts/policies/ap_policy.md", "artifacts/ap/three_way_match.csv"], ["ap", "vendor"], "供应商不一致。"),
        case("FIN-AP-004", "AP_THREE_WAY_MATCH", "COMPLEX", "审核 AP-9004：按已验收数量计算可付款金额和超开金额。只输出 JSON。", ap_policy + "\n" + ap_context, {"amounts": {"payable_amount_cny": 106310.40, "over_billed_cny": 4429.60}, "required_findings": ["accepted_96_of_100"], "decision": "partial_approve"}, {**common_eval, "scoring_type": "finance_ap_match", "exact_amounts": ["payable_amount_cny", "over_billed_cny"], "required_findings": ["96"]}, ["artifacts/policies/ap_policy.md", "artifacts/ap/three_way_match.csv"], ["ap", "quantity"], "按验收数量付款。"),
        case("FIN-AP-005", "AP_THREE_WAY_MATCH", "COMPLEX", "审核 AP-9005：签约预付款是否可支付？是否需要 CFO 审批？只输出 JSON。", ap_policy + "\n" + ap_context, {"amounts": {"payable_amount_cny": 63600.00}, "required_findings": ["25_percent_signing_prepayment_allowed", "finance_manager_approval_required", "no_cfo_required_under_100000"], "decision": "approve_with_approval"}, {**common_eval, "scoring_type": "finance_ap_match", "exact_amounts": ["payable_amount_cny"], "required_findings": ["25%", "50000"]}, ["artifacts/policies/ap_policy.md", "artifacts/ap/three_way_match.csv"], ["ap", "prepayment"], "签约预付款。"),
        case("FIN-AP-006", "AP_THREE_WAY_MATCH", "SIMPLE", "审核 AP-9006 是否可付款。只输出 JSON。", ap_policy + "\n" + ap_context, {"amounts": {"payable_amount_cny": 0.00}, "required_findings": ["not_accepted"], "decision": "reject"}, {**common_eval, "scoring_type": "finance_ap_match", "exact_amounts": ["payable_amount_cny"], "required_findings": ["not accepted"]}, ["artifacts/policies/ap_policy.md", "artifacts/ap/three_way_match.csv"], ["ap", "acceptance"], "未验收拒付。"),
    ])

    # Bank reconciliation
    cases.extend([
        case("FIN-BANK-001", "BANK_RECONCILIATION", "SIMPLE", "找出银行流水中没有对应账簿记录的项目。只输出 JSON。", bank_context, {"required_findings": ["B-003 bank fee -35", "B-005 unknown receipt 50000", "B-008 duplicate payment 8800"], "decision": "flag"}, {**common_eval, "scoring_type": "finance_reconciliation", "required_findings": ["B-003", "B-005", "B-008"]}, ["artifacts/bank/bank_statement_may.csv", "artifacts/bank/ledger_may.csv"], ["bank", "unmatched"], "未入账银行流水。"),
        case("FIN-BANK-002", "BANK_RECONCILIATION", "MODERATE", "找出账簿中没有银行流水匹配的项目，并说明可能原因。只输出 JSON。", bank_context, {"required_findings": ["L-014 outstanding payment -12500"], "decision": "flag"}, {**common_eval, "scoring_type": "finance_reconciliation", "required_findings": ["L-014", "12500"]}, ["artifacts/bank/bank_statement_may.csv", "artifacts/bank/ledger_may.csv"], ["bank", "outstanding"], "账簿未达账项。"),
        case("FIN-BANK-003", "BANK_RECONCILIATION", "MODERATE", "检查 AP-9002 的银行付款和账簿金额差异。只输出 JSON。", bank_context, {"amounts": {"bank_amount_cny": -72320.00, "ledger_amount_cny": -72800.00, "difference_cny": 480.00}, "required_findings": ["AP-9002 amount_mismatch_480"], "decision": "flag"}, {**common_eval, "scoring_type": "finance_reconciliation", "exact_amounts": ["difference_cny"], "required_findings": ["480"]}, ["artifacts/bank/bank_statement_may.csv", "artifacts/bank/ledger_may.csv"], ["bank", "mismatch"], "金额差异。"),
        case("FIN-BANK-004", "BANK_RECONCILIATION", "COMPLEX", "找出疑似重复付款，并给出重复风险金额。只输出 JSON。", bank_context, {"amounts": {"duplicate_payment_risk_cny": 8800.00}, "required_findings": ["B-007 and B-008 duplicate OD-1122"], "decision": "flag"}, {**common_eval, "scoring_type": "finance_reconciliation", "exact_amounts": ["duplicate_payment_risk_cny"], "required_findings": ["OD-1122", "8800"]}, ["artifacts/bank/bank_statement_may.csv", "artifacts/bank/ledger_may.csv"], ["bank", "duplicate_payment"], "重复付款。"),
        case("FIN-BANK-005", "BANK_RECONCILIATION", "COMPLEX", "生成 2026-05 银行余额调节差异清单，包含银行未入账、账簿未达、金额不一致、重复付款四类。只输出 JSON。", bank_context, {"required_findings": ["B-003", "B-005", "L-014", "AP-9002 difference 480", "OD-1122 duplicate"], "decision": "summarize"}, {**common_eval, "scoring_type": "finance_reconciliation", "required_findings": ["B-003", "B-005", "L-014", "480", "OD-1122"]}, ["artifacts/bank/bank_statement_may.csv", "artifacts/bank/ledger_may.csv"], ["bank", "summary"], "多类别调节。"),
        case("FIN-BANK-006", "BANK_RECONCILIATION", "EXPERT", "如果只允许优先处理 3 个风险最高的对账差异，请按金额和风险排序，并说明处理动作。只输出 JSON。", bank_context, {"required_findings": ["B-005 unknown receipt 50000", "L-014 outstanding payment 12500", "OD-1122 duplicate payment 8800"], "decision": "prioritize"}, {**common_eval, "scoring_type": "finance_reconciliation_priority", "required_findings": ["50000", "12500", "8800"]}, ["artifacts/bank/bank_statement_may.csv", "artifacts/bank/ledger_may.csv"], ["bank", "prioritization"], "风险优先级排序。"),
    ])

    # Budget variance
    cases.extend([
        case("FIN-BUD-001", "BUDGET_VARIANCE", "SIMPLE", "计算所有预算项的总预算、总实际和总超支金额。只输出 JSON。", budget_context, {"amounts": {"total_budget_cny": 440000.00, "total_actual_cny": 541500.00, "total_overspend_cny": 101500.00}, "decision": "calculate"}, {**common_eval, "scoring_type": "finance_budget", "exact_amounts": ["total_budget_cny", "total_actual_cny", "total_overspend_cny"]}, ["artifacts/budget/budget_actual_may.csv", "artifacts/policies/budget_policy.md"], ["budget", "sum"], "预算总览。"),
        case("FIN-BUD-002", "BUDGET_VARIANCE", "MODERATE", "找出前三大绝对超支项，按超支金额降序。只输出 JSON。", budget_context, {"top_items": [{"dept": "R&D", "category": "Cloud", "variance_cny": 48000.00}, {"dept": "Sales", "category": "Travel", "variance_cny": 18000.00}, {"dept": "Sales", "category": "Entertainment", "variance_cny": 17000.00}], "decision": "rank"}, {**common_eval, "scoring_type": "finance_budget_rank", "required_findings": ["R&D Cloud 48000", "Sales Travel 18000", "Sales Entertainment 17000"]}, ["artifacts/budget/budget_actual_may.csv"], ["budget", "rank"], "Top 3 超支。"),
        case("FIN-BUD-003", "BUDGET_VARIANCE", "MODERATE", "根据预算制度，找出需要提交预算调整说明的项目。只输出 JSON。", budget_context, {"required_findings": ["Sales Travel", "Sales Entertainment", "R&D Cloud", "HR Recruitment", "IT Hardware"], "decision": "flag"}, {**common_eval, "scoring_type": "finance_budget_policy", "required_findings": ["Sales Travel", "Sales Entertainment", "R&D Cloud", "HR Recruitment", "IT Hardware"]}, ["artifacts/budget/budget_actual_may.csv", "artifacts/policies/budget_policy.md"], ["budget", "policy"], "双阈值制度判断。"),
        case("FIN-BUD-004", "BUDGET_VARIANCE", "MODERATE", "找出高风险预算异常项（超预算率 > 30%），并给出超预算率。只输出 JSON。", budget_context, {"required_findings": ["Sales Entertainment 48.57%", "R&D Cloud 40.00%", "HR Recruitment 73.33%"], "decision": "flag"}, {**common_eval, "scoring_type": "finance_budget_policy", "required_findings": ["48.57", "40", "73.33"]}, ["artifacts/budget/budget_actual_may.csv", "artifacts/policies/budget_policy.md"], ["budget", "high_risk"], "高风险异常率。"),
        case("FIN-BUD-005", "BUDGET_VARIANCE", "COMPLEX", "写一份 JSON 化预算分析摘要：列出主要超支原因假设和建议动作，但必须基于表中 owner_note，不得编造。只输出 JSON。", budget_context, {"required_findings": ["R&D Cloud model experiments", "Sales customer visits or distributor campaign", "HR campus fair"], "decision": "summarize"}, {**common_eval, "scoring_type": "finance_budget_explanation", "required_findings": ["model experiments", "customer visits", "campus fair"], "forbidden_findings": ["macroeconomic", "exchange rate"]}, ["artifacts/budget/budget_actual_may.csv"], ["budget", "analysis"], "解释质量但要求证据约束。"),
        case("FIN-BUD-006", "BUDGET_VARIANCE", "EXPERT", "结合预算制度，给 CFO 输出一份机器可读的预算风险清单：高风险/中风险/无需动作三类，并给金额影响。只输出 JSON。", budget_context, {"required_findings": ["high: Sales Entertainment", "high: R&D Cloud", "high: HR Recruitment", "medium: Sales Travel", "medium: IT Hardware"], "decision": "classify"}, {**common_eval, "scoring_type": "finance_budget_risk", "required_findings": ["Sales Entertainment", "R&D Cloud", "HR Recruitment", "Sales Travel", "IT Hardware"]}, ["artifacts/budget/budget_actual_may.csv", "artifacts/policies/budget_policy.md"], ["budget", "risk"], "预算风险分级。"),
    ])

    # Policy/document QA
    cases.extend([
        case("FIN-POL-001", "POLICY_QA", "SIMPLE", "员工在北京住宿 680 元/晚，发票抬头合规。根据制度最多可报多少？只输出 JSON。", travel_policy, {"amounts": {"approved_amount_cny": 600.00, "rejected_amount_cny": 80.00}, "required_findings": ["Beijing tier1 cap 600"], "decision": "partial_approve"}, {**common_eval, "scoring_type": "finance_policy_qa", "exact_amounts": ["approved_amount_cny", "rejected_amount_cny"], "required_findings": ["600"]}, ["artifacts/policies/travel_policy.md"], ["policy", "qa"], "制度问答。"),
        case("FIN-POL-002", "POLICY_QA", "SIMPLE", "机票发票抬头是员工个人姓名，是否可以报销？只输出 JSON。", travel_policy, {"amounts": {"approved_amount_cny": 0.00}, "required_findings": ["personal invoice title not reimbursable"], "decision": "reject"}, {**common_eval, "scoring_type": "finance_policy_qa", "exact_amounts": ["approved_amount_cny"], "required_findings": ["个人抬头", "不可报销"]}, ["artifacts/policies/travel_policy.md"], ["policy", "invoice_title"], "个人抬头。"),
        case("FIN-POL-003", "POLICY_QA", "MODERATE", "供应商银行账户变更但没有主数据变更审批，付款申请能否放行？只输出 JSON。", ap_policy, {"amounts": {"payable_amount_cny": 0.00}, "required_findings": ["vendor_master_change_approval_required"], "decision": "reject"}, {**common_eval, "scoring_type": "finance_policy_qa", "exact_amounts": ["payable_amount_cny"], "required_findings": ["供应商主数据", "审批"]}, ["artifacts/policies/ap_policy.md"], ["policy", "vendor_master"], "供应商账户变更。"),
        case("FIN-POL-004", "POLICY_QA", "MODERATE", "单笔付款 120000 元，三单匹配无误。需要哪些审批？只输出 JSON。", ap_policy, {"required_findings": ["finance_manager_approval", "cfo_approval"], "decision": "approve_with_approval"}, {**common_eval, "scoring_type": "finance_policy_qa", "required_findings": ["财务经理", "CFO"]}, ["artifacts/policies/ap_policy.md"], ["policy", "approval"], "审批阈值。"),
        case("FIN-POL-005", "POLICY_QA", "MODERATE", "预算项目超支 9000 元，超预算率 20%。是否必须提交预算调整说明？只输出 JSON。", budget_policy, {"required_findings": ["not_required_because_amount_not_over_10000"], "decision": "no_action_required"}, {**common_eval, "scoring_type": "finance_policy_qa", "required_findings": ["10000", "不需要"]}, ["artifacts/policies/budget_policy.md"], ["policy", "budget"], "双条件阈值的反例。"),
        case("FIN-POL-006", "POLICY_QA", "COMPLEX", "根据三份制度，总结一个财务助手在审批前必须检查的 8 个硬约束。只输出 JSON 数组，不要自由发挥。", travel_policy + "\n" + ap_policy + "\n" + budget_policy, {"required_findings": ["invoice title", "duplicate invoice", "hotel cap", "meal cap", "acceptance before payment", "vendor consistency", "payment approval threshold", "budget variance threshold"], "decision": "summarize"}, {**common_eval, "scoring_type": "finance_policy_summary", "required_findings": ["发票抬头", "重复发票", "住宿", "餐费", "验收", "供应商", "审批", "预算"]}, ["artifacts/policies/travel_policy.md", "artifacts/policies/ap_policy.md", "artifacts/policies/budget_policy.md"], ["policy", "summary"], "制度摘要和硬约束提取。"),
    ])

    data = {
        "version": "finance-1.0",
        "description": "Synthetic enterprise finance office benchmark for table calculation, reimbursement audit, AP matching, bank reconciliation, budget analysis, and policy QA.",
        "source_policy": "Fictional data. Public benchmarks are used only as task-shape inspiration, not copied cases.",
        "public_inspirations": [
            {"name": "SpreadsheetBench", "url": "https://spreadsheetbench.github.io/", "used_for": "spreadsheet task patterns"},
            {"name": "FinanceBench", "url": "https://huggingface.co/datasets/PatronusAI/financebench", "used_for": "finance document QA framing"},
            {"name": "FinQA", "url": "https://finqasite.github.io/", "used_for": "financial numerical reasoning"},
            {"name": "TAT-QA", "url": "https://nextplusplus.github.io/TAT-QA/", "used_for": "table-text question answering"},
            {"name": "DocILE", "url": "https://docile.rossum.ai/", "used_for": "invoice/purchase-order document tasks"},
        ],
        "models": ["qwen3.7-max", "qwen3.7-plus", "deepseek-v4-flash", "deepseek-v4-pro", "glm-5.1"],
        "scoring_principles": [
            "Numeric fields are rule-scored with cent-level tolerance.",
            "Required findings are recall-scored with evidence requirements.",
            "Hallucinated violations should be penalized.",
            "LLM judge may assess explanation quality but must not override numeric ground truth.",
        ],
        "cases": cases,
    }

    write_text(OUT_DIR / "finance_cases.yaml", yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=120))

    readme = """
# Finance Office Benchmark

这是一份企业财务办公场景 benchmark 数据包，全部数据均为 synthetic fiction，不包含公司真实数据。

## 目标

测量模型在财务日常工作中的落地能力，而不是通用榜单能力：

- 表格理解、分类汇总、数值计算
- 报销制度套用和违规识别
- 合同 / PO / 发票 / 验收三单匹配
- 银行流水与账簿对账
- 预算执行差异分析
- 财务制度问答和硬约束提取

## 数据规模

- 36 cases
- 6 个类别，每类 6 条
- 5 个模型时为 180 次模型执行，不含 judge

## 公开 benchmark 借鉴

本数据包参考公开 benchmark 的任务形态，但不复制公开 case：

- SpreadsheetBench: spreadsheet/Excel 操作任务形态
- FinanceBench: 金融文档问答和证据定位形态
- FinQA / TAT-QA: 表格 + 文本的金融数值推理
- DocILE: invoices / purchase orders / line items 的文档理解任务形态

## 推荐评分策略

财务场景不要只靠 LLM Judge。建议优先规则评分：

1. JSON 是否可解析
2. 金额字段是否正确，容忍 0.01 CNY
3. required_findings 是否召回
4. forbidden_findings 是否避免
5. evidence 是否能引用输入表/制度
6. LLM Judge 只评解释质量，不覆盖金额真值

## 文件

- `finance_cases.yaml`: benchmark case 主文件
- `artifacts/policies/*.md`: synthetic 财务制度
- `artifacts/expenses/*.csv`: 报销明细
- `artifacts/ap/*.csv`: 合同 / PO / 发票 / 验收匹配
- `artifacts/bank/*.csv`: 银行流水与账簿
- `artifacts/budget/*.csv`: 预算执行表
"""
    write_text(OUT_DIR / "README.md", readme)


if __name__ == "__main__":
    main()
