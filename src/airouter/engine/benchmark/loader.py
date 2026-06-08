"""Load benchmark cases from YAML."""

from __future__ import annotations

from enum import Enum
from pathlib import Path

import yaml

from airouter.engine.benchmark.schemas import BenchmarkCase, L2Case
from airouter.models.enums import (
    ComplexityLevel,
    RiskLevel,
    StrategyType,
    TaskCategory,
)

DEFAULT_CASES_PATH = Path(__file__).resolve().parents[4] / "data" / "benchmarks" / "level1" / "router_cases.yaml"
DEFAULT_L2_CASES_PATH = Path(__file__).resolve().parents[4] / "data" / "benchmarks" / "level2" / "router_quality_cases.yaml"

VALID_ENUMS: dict[str, set[Enum]] = {
    "expected_task_type": set(TaskCategory),
    "expected_complexity": set(ComplexityLevel),
    "expected_risk": set(RiskLevel),
    "expected_strategy": set(StrategyType),
}

VALID_SCORING_TYPES = {
    "code_generation", "code_review", "bug_analysis",
    "documentation", "refactoring", "architecture",
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


def load_l2_cases(path: Path | None = None) -> list[L2Case]:
    """Load and validate Level 2 benchmark cases from YAML.

    Args:
        path: Path to YAML file. Defaults to data/benchmarks/level2/router_quality_cases.yaml.

    Returns:
        List of validated L2Case objects.

    Raises:
        FileNotFoundError: If YAML file does not exist.
        ValueError: If enum values or scoring_type are invalid.
    """
    cases_path = path or DEFAULT_L2_CASES_PATH
    if not cases_path.exists():
        raise FileNotFoundError(f"Benchmark cases file not found: {cases_path}")

    with open(cases_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not data or not isinstance(data, dict):
        raise ValueError(f"Benchmark YAML is empty or invalid: {cases_path}")

    raw_cases = data.get("cases")
    if not raw_cases or not isinstance(raw_cases, list):
        raise ValueError(f"Benchmark YAML must contain non-empty 'cases' list: {cases_path}")

    valid_task_types = {v.value for v in TaskCategory}
    valid_complexities = {v.value for v in ComplexityLevel}

    cases: list[L2Case] = []

    for i, raw in enumerate(raw_cases):
        if not isinstance(raw, dict):
            raise ValueError(f"Case at index {i} is not a dict: {raw!r}")
        case_id = raw.get("id", "UNKNOWN")

        # Validate task_type
        task_type = raw.get("task_type")
        if task_type and task_type not in valid_task_types:
            valid_list = ", ".join(sorted(valid_task_types))
            raise ValueError(
                f"Case {case_id}: invalid task_type '{task_type}'. Valid values: {valid_list}"
            )

        # Validate complexity
        complexity = raw.get("complexity")
        if complexity and complexity not in valid_complexities:
            valid_list = ", ".join(sorted(valid_complexities))
            raise ValueError(
                f"Case {case_id}: invalid complexity '{complexity}'. Valid values: {valid_list}"
            )

        # Validate scoring_type
        scoring_type = raw.get("scoring_type")
        if scoring_type and scoring_type not in VALID_SCORING_TYPES:
            valid_list = ", ".join(sorted(VALID_SCORING_TYPES))
            raise ValueError(
                f"Case {case_id}: invalid scoring_type '{scoring_type}'. Valid values: {valid_list}"
            )

        cases.append(L2Case(**raw))

    return cases
