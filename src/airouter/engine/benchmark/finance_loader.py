"""Load finance benchmark cases from YAML."""

from __future__ import annotations

from pathlib import Path

import yaml

from airouter.engine.benchmark.finance_schemas import FinanceCase

DEFAULT_FINANCE_CASES_PATH = (
    Path(__file__).resolve().parents[4]
    / "data" / "benchmarks" / "finance" / "finance_cases.yaml"
)

VALID_FINANCE_CATEGORIES = {
    "TABLE_CALCULATION",
    "REIMBURSEMENT_AUDIT",
    "AP_THREE_WAY_MATCH",
    "BANK_RECONCILIATION",
    "BUDGET_VARIANCE",
    "POLICY_QA",
}

VALID_COMPLEXITIES = {"SIMPLE", "MODERATE", "COMPLEX", "EXPERT"}


def load_finance_cases(path: Path | None = None) -> list[FinanceCase]:
    """Load and validate finance benchmark cases from YAML."""
    cases_path = path or DEFAULT_FINANCE_CASES_PATH
    if not cases_path.exists():
        raise FileNotFoundError(f"Finance benchmark cases file not found: {cases_path}")

    with open(cases_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not data or not isinstance(data, dict):
        raise ValueError(f"Finance benchmark YAML is empty or invalid: {cases_path}")

    raw_cases = data.get("cases")
    if not raw_cases or not isinstance(raw_cases, list):
        raise ValueError(
            f"Finance benchmark YAML must contain non-empty 'cases' list: {cases_path}"
        )

    cases: list[FinanceCase] = []

    for i, raw in enumerate(raw_cases):
        if not isinstance(raw, dict):
            raise ValueError(f"Case at index {i} is not a dict: {raw!r}")
        case_id = raw.get("id", "UNKNOWN")

        category = raw.get("category", "")
        if category not in VALID_FINANCE_CATEGORIES:
            raise ValueError(
                f"Case {case_id}: invalid category '{category}'. "
                f"Valid values: {', '.join(sorted(VALID_FINANCE_CATEGORIES))}"
            )

        complexity = raw.get("complexity", "")
        if complexity not in VALID_COMPLEXITIES:
            raise ValueError(
                f"Case {case_id}: invalid complexity '{complexity}'. "
                f"Valid values: {', '.join(sorted(VALID_COMPLEXITIES))}"
            )

        scoring_type = raw.get("evaluation", {}).get("scoring_type", "")
        if scoring_type and not scoring_type.startswith("finance_"):
            raise ValueError(
                f"Case {case_id}: scoring_type '{scoring_type}' must start with 'finance_'"
            )

        cases.append(FinanceCase(**raw))

    return cases
