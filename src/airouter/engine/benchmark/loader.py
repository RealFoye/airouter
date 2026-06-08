"""Load benchmark cases from YAML."""

from __future__ import annotations

from enum import Enum
from pathlib import Path

import yaml

from airouter.engine.benchmark.schemas import BenchmarkCase
from airouter.models.enums import (
    ComplexityLevel,
    RiskLevel,
    StrategyType,
    TaskCategory,
)

DEFAULT_CASES_PATH = Path(__file__).resolve().parents[4] / "data" / "benchmarks" / "level1" / "router_cases.yaml"

VALID_ENUMS: dict[str, set[Enum]] = {
    "expected_task_type": set(TaskCategory),
    "expected_complexity": set(ComplexityLevel),
    "expected_risk": set(RiskLevel),
    "expected_strategy": set(StrategyType),
}


def load_cases(path: Path | None = None) -> list[BenchmarkCase]:
    """Load and validate benchmark cases from YAML.

    Args:
        path: Path to YAML file. Defaults to data/benchmarks/level1/router_cases.yaml.

    Returns:
        List of validated BenchmarkCase objects.

    Raises:
        FileNotFoundError: If YAML file does not exist.
        ValueError: If enum values are invalid.
    """
    cases_path = path or DEFAULT_CASES_PATH
    if not cases_path.exists():
        raise FileNotFoundError(f"Benchmark cases file not found: {cases_path}")

    with open(cases_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not data or not isinstance(data, dict):
        raise ValueError(f"Benchmark YAML is empty or invalid: {cases_path}")

    raw_cases = data.get("cases")
    if not raw_cases or not isinstance(raw_cases, list):
        raise ValueError(f"Benchmark YAML must contain non-empty 'cases' list: {cases_path}")

    cases: list[BenchmarkCase] = []

    for i, raw in enumerate(raw_cases):
        if not isinstance(raw, dict):
            raise ValueError(f"Case at index {i} is not a dict: {raw!r}")
        case_id = raw.get("id", "UNKNOWN")

        # Validate enum fields
        for field, valid_values in VALID_ENUMS.items():
            value = raw.get(field)
            if value and value not in {v.value for v in valid_values}:
                valid_list = ", ".join(sorted(v.value for v in valid_values))
                raise ValueError(f"Case {case_id}: invalid {field} '{value}'. Valid values: {valid_list}")

        cases.append(BenchmarkCase(**raw))

    return cases
