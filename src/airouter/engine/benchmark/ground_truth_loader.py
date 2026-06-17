"""Ground Truth Benchmark 数据加载器。

加载 Dev (engineering_cases.yaml) 和 Holdout (general_cases.yaml) 用例。
Development 30 cases 复用 engineering_cases.yaml，补充 structured_output 字段推断。
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import yaml

from airouter.engine.benchmark.ground_truth_schemas import (
    VALID_HOLDOUT_CATEGORIES,
    EvaluationSpec,
    GroundTruthCase,
    GroundTruthData,
    HarnessValidation,
    RoutingMessage,
    RoutingMetadata,
    StructuredOutputSpec,
    TestFile,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
DEFAULT_DEV_PATH = PROJECT_ROOT / "data" / "benchmarks" / "engineering" / "engineering_cases.yaml"
DEFAULT_HOLDOUT_PATH = PROJECT_ROOT / "data" / "benchmarks" / "routing_ground_truth" / "general_cases.yaml"


def load_dev_cases(path: Path | None = None) -> list[GroundTruthCase]:
    """加载 Development 用例（复用 engineering_cases.yaml）。

    自动补充 structured_output 和 evaluation 字段推断。
    """
    path = path or DEFAULT_DEV_PATH
    if not path.exists():
        raise FileNotFoundError(f"Dev cases not found: {path}")

    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    cases_data = raw.get("cases", [])
    return [_parse_dev_case(c) for c in cases_data]


def load_holdout_cases(path: Path | None = None) -> list[GroundTruthCase]:
    """加载 Holdout 用例（general_cases.yaml）。"""
    path = path or DEFAULT_HOLDOUT_PATH
    if not path.exists():
        raise FileNotFoundError(f"Holdout cases not found: {path}")

    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    cases_data = raw.get("cases", [])

    cases = []
    for c in cases_data:
        case = _parse_holdout_case(c)
        if case.category not in VALID_HOLDOUT_CATEGORIES:
            raise ValueError(
                f"Holdout case {case.id} has invalid category {case.category}. "
                f"Must be one of: {sorted(VALID_HOLDOUT_CATEGORIES)}"
            )
        cases.append(case)
    return cases


def compute_holdout_hash(path: Path | None = None) -> str:
    """计算 Holdout YAML 文件 SHA256。"""
    path = path or DEFAULT_HOLDOUT_PATH
    if not path.exists():
        return ""
    content = path.read_bytes()
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


# ── 内部解析 ─────────────────────────────────────────────────


def _parse_history_messages(routing_raw: dict[str, Any]) -> list[RoutingMessage]:
    """解析历史消息（支持新旧两种 YAML 格式）。

    新格式：history_messages: [{role: user, content: "..."}]
    旧格式：history_user_texts: ["..."] → 转为 role=user
    """
    messages_raw = routing_raw.get("history_messages")
    if messages_raw:
        return [
            RoutingMessage(
                role=m.get("role", "user"),
                content=m.get("content", ""),
            )
            for m in messages_raw
        ]
    # 旧格式兼容
    user_texts = routing_raw.get("history_user_texts", [])
    return [RoutingMessage(role="user", content=t) for t in user_texts]


def _parse_dev_case(raw: dict[str, Any]) -> GroundTruthCase:
    """解析 engineering case，补充 structured_output 推断。"""
    evaluation_raw = raw.get("evaluation", {})
    evaluation = EvaluationSpec(
        primary=evaluation_raw.get("primary", "rule_based"),
        required_findings=evaluation_raw.get("required_findings", []),
        forbidden_findings=evaluation_raw.get("forbidden_findings", []),
        required_outputs=evaluation_raw.get("required_outputs", []),
        forbidden_outputs=evaluation_raw.get("forbidden_outputs", []),
        must_not_modify=evaluation_raw.get("must_not_modify", []),
        should_ask_clarification=evaluation_raw.get("should_ask_clarification", False),
        requires_human_approval=evaluation_raw.get("requires_human_approval", False),
    )

    # 推断 structured_output spec
    required_fields = ["action", "summary"]
    optional_fields = ["findings", "evidence", "claims"]
    if raw.get("task_type") == "CODE_CHANGE":
        required_fields.append("findings")
        optional_fields.extend(["patch", "modified_files", "validation"])
    structured_output = StructuredOutputSpec(
        required_fields=required_fields,
        optional_fields=optional_fields,
    )

    return GroundTruthCase(
        id=raw["id"],
        domain=raw.get("domain", "ENGINEERING"),
        category=raw.get("category", "CODE_FIX"),
        task_type=raw.get("task_type", "CODE_CHANGE"),
        complexity=raw.get("complexity", "MODERATE"),
        risk_level=raw.get("risk_level", "LOW"),
        prompt=raw["prompt"],
        input_context=raw.get("input_context", ""),
        expected_behavior=raw.get("expected_behavior", []),
        forbidden_behavior=raw.get("forbidden_behavior", []),
        evaluation=evaluation,
        ground_truth=_parse_ground_truth(raw.get("ground_truth", {})),
        workspace_files=raw.get("workspace_files", {}),
        harness_validation=_parse_harness(raw.get("harness_validation", {})),
        structured_output=structured_output,
        max_tokens=raw.get("max_tokens", 4096),
        tags=raw.get("tags", []),
        notes=raw.get("notes", ""),
    )


def _parse_holdout_case(raw: dict[str, Any]) -> GroundTruthCase:
    """解析 Holdout case（完整字段）。"""
    evaluation_raw = raw.get("evaluation", {})
    routing_raw = raw.get("routing_metadata", {})
    gt_raw = raw.get("ground_truth", {})
    harness_raw = raw.get("harness_validation", {})
    so_raw = raw.get("structured_output", {})

    return GroundTruthCase(
        id=raw["id"],
        domain=raw.get("domain", "GENERAL"),
        category=raw["category"],
        task_type=raw.get("task_type", "ANALYSIS_ONLY"),
        complexity=raw.get("complexity", "MODERATE"),
        risk_level=raw.get("risk_level", "LOW"),
        prompt=raw["prompt"],
        input_context=raw.get("input_context", ""),
        routing_metadata=RoutingMetadata(
            history_messages=_parse_history_messages(routing_raw),
            prev_assistant_text=routing_raw.get("prev_assistant_text"),
            prev_assistant_usage=routing_raw.get("prev_assistant_usage"),
            n_tools=routing_raw.get("n_tools", 0),
            tool_result_length=routing_raw.get("tool_result_length", 0),
        ),
        expected_behavior=raw.get("expected_behavior", []),
        forbidden_behavior=raw.get("forbidden_behavior", []),
        evaluation=EvaluationSpec(
            primary=evaluation_raw.get("primary", "rule_based"),
            required_findings=evaluation_raw.get("required_findings", []),
            forbidden_findings=evaluation_raw.get("forbidden_findings", []),
            required_outputs=evaluation_raw.get("required_outputs", []),
            forbidden_outputs=evaluation_raw.get("forbidden_outputs", []),
            must_not_modify=evaluation_raw.get("must_not_modify", []),
            should_ask_clarification=evaluation_raw.get("should_ask_clarification", False),
            requires_human_approval=evaluation_raw.get("requires_human_approval", False),
        ),
        ground_truth=_parse_ground_truth(gt_raw),
        workspace_files=raw.get("workspace_files", {}),
        harness_validation=_parse_harness(harness_raw),
        structured_output=StructuredOutputSpec(
            required_fields=so_raw.get("required_fields", ["action", "summary", "findings"]),
            optional_fields=so_raw.get("optional_fields", ["patch", "validation", "modified_files"]),
        ),
        max_tokens=raw.get("max_tokens", 4096),
        tags=raw.get("tags", []),
        notes=raw.get("notes", ""),
    )


def _parse_ground_truth(raw: dict[str, Any]) -> GroundTruthData:
    if not raw:
        return GroundTruthData()
    test_files = [
        TestFile(filename=tf["filename"], content=tf["content"])
        for tf in raw.get("test_files", [])
    ]
    return GroundTruthData(
        expected_values=raw.get("expected_values", {}),
        expected_fact_ids=raw.get("expected_fact_ids", []),
        hidden_tests=raw.get("hidden_tests", []),
        test_files=test_files,
        allowed_root_causes=raw.get("allowed_root_causes", []),
        evidence_line_ids=raw.get("evidence_line_ids", []),
        expected_tools=raw.get("expected_tools", []),
        required_history_refs=raw.get("required_history_refs", []),
        allowed_claims=raw.get("allowed_claims", []),
        forbidden_claims=raw.get("forbidden_claims", []),
    )


def _parse_harness(raw: dict[str, Any]) -> HarnessValidation:
    if not raw:
        return HarnessValidation()
    return HarnessValidation(
        commands=raw.get("commands", []),
        timeout_s=raw.get("timeout_s", 10),
        expected_exit_code=raw.get("expected_exit_code", 0),
    )
