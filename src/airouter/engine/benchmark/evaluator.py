"""Level 2 auto-evaluator: AST + structure + keyword scoring (no code execution)."""

from __future__ import annotations

import ast
import re
from typing import Any, Callable

from airouter.engine.benchmark.schemas import L2Case, ScoreResult

# ── ISSUE_KEYWORDS for code_review / bug_analysis ─────────────

ISSUE_KEYWORDS: dict[str, list[str]] = {
    "sql_injection": ["sql injection", "sql注入", "parameterized", "参数化", "prepared statement"],
    "hardcoded_secret": ["hardcoded", "硬编码", "secret", "密钥", "api_key", "credential"],
    "n_plus_one": ["n+1", "n + 1", "eager loading", "预加载", "select_related"],
    "race_condition": ["race condition", "竞态", "lock", "mutex", "thread safe"],
    "deadlock": ["deadlock", "死锁", "circular lock", "交叉获取锁"],
    "memory_leak": ["memory leak", "内存泄漏", "unclosed", "未关闭", "connection pool"],
    "none_type": ["none", "null", "attributeerror", "nonetype", "is none"],
    "index_error": ["index", "越界", "out of range", "indexerror", "list index"],
    "infinite_loop": ["infinite loop", "无限循环", "死循环", "break", "while true"],
    "integer_overflow": ["overflow", "溢出", "integer", "int_max", "sys.maxsize"],
    "srp_violation": ["single responsibility", "单一职责", "srp", "god class", "上帝类", "too many responsibilities"],
    "tight_coupling": ["tight coupling", "紧耦合", "circular dependency", "循环依赖", "coupling"],
    "missing_index": ["index", "索引", "missing index", "缺少索引", "full table scan"],
}

# ── Code extraction ───────────────────────────────────────────


def extract_code(text: str) -> str:
    """Extract code from markdown fenced blocks.

    Rules:
    1. Prefer ```python fenced block
    2. Fall back to largest fenced block (any language)
    3. No fenced blocks → return full text
    """
    # Match ```python ... ``` blocks
    python_pattern = re.compile(r"```python\s*\n(.*?)```", re.DOTALL)
    python_matches: list[str] = python_pattern.findall(text)
    if python_matches:
        return max(python_matches, key=len).strip()

    # Match any fenced block ```...```
    any_pattern = re.compile(r"```\w*\s*\n(.*?)```", re.DOTALL)
    any_matches: list[str] = any_pattern.findall(text)
    if any_matches:
        return max(any_matches, key=len).strip()

    return text.strip()


# ── any_of matching ───────────────────────────────────────────


def _normalize_criteria(raw_criteria: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Normalize evaluation_criteria to {id, any_of} format.

    Supports:
    - {id: str, any_of: [str, ...]} → as-is
    - plain str → {id: str, any_of: [str]}
    """
    result: dict[str, list[dict[str, Any]]] = {}
    for group_name, items in raw_criteria.items():
        normalized: list[dict[str, Any]] = []
        if not isinstance(items, list):
            continue
        for item in items:
            if isinstance(item, dict) and "any_of" in item:
                normalized.append(item)
            elif isinstance(item, str):
                normalized.append({"id": item, "any_of": [item]})
        result[group_name] = normalized
    return result


def _check_any_of(criteria: list[dict[str, Any]], output: str) -> tuple[int, int]:
    """Check any_of groups against output (lower-case comparison).

    Returns (hits, total).
    """
    if not criteria:
        return 0, 0
    output_lower = output.lower()
    hits = 0
    for item in criteria:
        keywords = item.get("any_of", [])
        if any(kw.lower() in output_lower for kw in keywords):
            hits += 1
    return hits, len(criteria)


# ── Scoring functions ─────────────────────────────────────────


def score_code_generation(case: L2Case, output: str) -> ScoreResult:
    """Score code generation output.

    Dimensions: syntax(0.25) + completeness(0.25) + requirement_coverage(0.50)
    """
    code = extract_code(output)
    criteria = _normalize_criteria(case.evaluation_criteria)
    must_have = criteria.get("must_have", [])

    # syntax
    syntax = 0.0
    try:
        ast.parse(code)
        syntax = 1.0
    except (SyntaxError, TypeError):
        pass

    # completeness
    checks = [
        bool(re.search(r"^(import|from)\s", code, re.MULTILINE)),
        bool(re.search(r"^(def|class)\s", code, re.MULTILINE)),
        "try" in code or "raise" in code,
        '"""' in code or "'''" in code,
    ]
    completeness = sum(checks) / len(checks)

    # requirement_coverage
    req_hits, req_total = _check_any_of(must_have, output)
    requirement_coverage = req_hits / req_total if req_total > 0 else 0.0

    overall = syntax * 0.25 + completeness * 0.25 + requirement_coverage * 0.50
    return ScoreResult(
        scoring_type="code_generation",
        overall_score=overall,
        dimension_scores={
            "syntax": syntax,
            "completeness": completeness,
            "requirement_coverage": requirement_coverage,
        },
        details={"code_length": len(code), "req_hits": req_hits, "req_total": req_total},
    )


def score_code_review(case: L2Case, output: str) -> ScoreResult:
    """Score code review output.

    Dimensions: issue_detection_rate(0.7) + explanation(0.15) + suggestion(0.15)
    """
    output_lower = output.lower()

    # issue_detection_rate
    expected_issues = case.expected_issues or []
    if expected_issues:
        hits = 0
        for issue_id in expected_issues:
            keywords = ISSUE_KEYWORDS.get(issue_id, [issue_id])
            if any(kw.lower() in output_lower for kw in keywords):
                hits += 1
        issue_rate = hits / len(expected_issues)
    else:
        issue_rate = 0.0

    # explanation: output has substance
    explanation = 1.0 if len(output) > 100 else 0.0

    # suggestion: contains fix/recommendation language
    suggestion_kws = ["fix", "建议", "should", "recommend", "replace", "use", "avoid", "改为", "替换"]
    suggestion = 1.0 if any(kw in output_lower for kw in suggestion_kws) else 0.0

    overall = issue_rate * 0.7 + explanation * 0.15 + suggestion * 0.15
    return ScoreResult(
        scoring_type="code_review",
        overall_score=overall,
        dimension_scores={
            "issue_detection_rate": issue_rate,
            "explanation": explanation,
            "suggestion": suggestion,
        },
        details={"expected_issues": len(expected_issues), "output_length": len(output)},
    )


def score_bug_analysis(case: L2Case, output: str) -> ScoreResult:
    """Score bug analysis output.

    Dimensions: root_cause(0.5) + fix_suggested(0.3) + explanation_quality(0.2)
    """
    output_lower = output.lower()

    # root_cause: match expected_issues keywords
    expected_issues = case.expected_issues or []
    if expected_issues:
        hits = 0
        for issue_id in expected_issues:
            keywords = ISSUE_KEYWORDS.get(issue_id, [issue_id])
            if any(kw.lower() in output_lower for kw in keywords):
                hits += 1
        root_cause = hits / len(expected_issues)
    else:
        # fallback: check must_have criteria
        criteria = _normalize_criteria(case.evaluation_criteria)
        must_have = criteria.get("must_have", [])
        hits, total = _check_any_of(must_have, output)
        root_cause = hits / total if total > 0 else 0.0

    # fix_suggested
    fix_kws = ["fix", "修复", "repair", "solution", "解决", "change to", "改为"]
    fix_suggested = 1.0 if any(kw in output_lower for kw in fix_kws) else 0.0

    # explanation_quality: length bucketing
    length = len(output)
    if length < 50:
        explanation_quality = 0.0
    elif length < 200:
        explanation_quality = 0.5
    else:
        explanation_quality = 1.0

    overall = root_cause * 0.5 + fix_suggested * 0.3 + explanation_quality * 0.2
    return ScoreResult(
        scoring_type="bug_analysis",
        overall_score=overall,
        dimension_scores={
            "root_cause": root_cause,
            "fix_suggested": fix_suggested,
            "explanation_quality": explanation_quality,
        },
        details={"output_length": length},
    )


def score_documentation(case: L2Case, output: str) -> ScoreResult:
    """Score documentation output.

    Dimensions: structure(0.4) + requirement_coverage(0.4) + length_adequate(0.2)
    """
    criteria = _normalize_criteria(case.evaluation_criteria)
    must_have = criteria.get("must_have", [])

    # structure: headings, paragraphs, code blocks, bullet lists
    checks = [
        bool(re.search(r"^#+\s", output, re.MULTILINE)),  # headings
        bool(re.search(r"```", output)),  # code blocks
        bool(re.search(r"^[-*]\s", output, re.MULTILINE)),  # bullet lists
        len(output.split("\n\n")) >= 2,  # multiple paragraphs
    ]
    structure = sum(checks) / len(checks)

    # requirement_coverage
    req_hits, req_total = _check_any_of(must_have, output)
    requirement_coverage = req_hits / req_total if req_total > 0 else 0.0

    # length_adequate
    length_adequate = 1.0 if len(output) > 200 else 0.0

    overall = structure * 0.4 + requirement_coverage * 0.4 + length_adequate * 0.2
    return ScoreResult(
        scoring_type="documentation",
        overall_score=overall,
        dimension_scores={
            "structure": structure,
            "requirement_coverage": requirement_coverage,
            "length_adequate": length_adequate,
        },
        details={"output_length": len(output), "req_hits": req_hits, "req_total": req_total},
    )


def score_refactoring(case: L2Case, output: str) -> ScoreResult:
    """Score refactoring output.

    Dimensions: syntax(0.25) + requirement_coverage(0.35) + code_changed(0.15) + completeness(0.25)
    """
    code = extract_code(output)
    criteria = _normalize_criteria(case.evaluation_criteria)
    must_have = criteria.get("must_have", [])

    # syntax
    syntax = 0.0
    try:
        ast.parse(code)
        syntax = 1.0
    except (SyntaxError, TypeError):
        pass

    # requirement_coverage
    req_hits, req_total = _check_any_of(must_have, output)
    requirement_coverage = req_hits / req_total if req_total > 0 else 0.0

    # code_changed: refactored code differs from input_context
    input_ctx = case.input_context.strip() if case.input_context else ""
    code_changed = 1.0 if (input_ctx and code.strip() != input_ctx) else (0.0 if input_ctx else 1.0)

    # completeness
    checks = [
        bool(re.search(r"^(import|from)\s", code, re.MULTILINE)),
        bool(re.search(r"^(def|class)\s", code, re.MULTILINE)),
        "try" in code or "raise" in code,
        '"""' in code or "'''" in code,
    ]
    completeness = sum(checks) / len(checks)

    overall = syntax * 0.25 + requirement_coverage * 0.35 + code_changed * 0.15 + completeness * 0.25
    return ScoreResult(
        scoring_type="refactoring",
        overall_score=overall,
        dimension_scores={
            "syntax": syntax,
            "requirement_coverage": requirement_coverage,
            "code_changed": code_changed,
            "completeness": completeness,
        },
        details={"code_length": len(code), "req_hits": req_hits, "req_total": req_total},
    )


def score_architecture(case: L2Case, output: str) -> ScoreResult:
    """Score architecture design output.

    Dimensions: requirement_coverage(0.4) + structure(0.3) + depth(0.3)
    """
    criteria = _normalize_criteria(case.evaluation_criteria)
    must_have = criteria.get("must_have", [])

    # requirement_coverage
    req_hits, req_total = _check_any_of(must_have, output)
    requirement_coverage = req_hits / req_total if req_total > 0 else 0.0

    # structure: headings, bullet lists, diagrams
    checks = [
        bool(re.search(r"^#+\s", output, re.MULTILINE)),
        bool(re.search(r"^[-*]\s", output, re.MULTILINE)),
        bool(re.search(r"```", output)) or bool(re.search(r"\+\-\-", output)),
    ]
    structure = sum(checks) / len(checks)

    # depth: length bucketing
    length = len(output)
    if length < 100:
        depth = 0.0
    elif length < 500:
        depth = 0.5
    else:
        depth = 1.0

    overall = requirement_coverage * 0.4 + structure * 0.3 + depth * 0.3
    return ScoreResult(
        scoring_type="architecture",
        overall_score=overall,
        dimension_scores={
            "requirement_coverage": requirement_coverage,
            "structure": structure,
            "depth": depth,
        },
        details={"output_length": length, "req_hits": req_hits, "req_total": req_total},
    )


# ── Dispatcher ────────────────────────────────────────────────

SCORER_DISPATCH: dict[str, Callable[[L2Case, str], ScoreResult]] = {
    "code_generation": score_code_generation,
    "code_review": score_code_review,
    "bug_analysis": score_bug_analysis,
    "documentation": score_documentation,
    "refactoring": score_refactoring,
    "architecture": score_architecture,
}


def auto_score(case: L2Case, output: str) -> ScoreResult:
    """Dispatch to the appropriate scorer based on case.scoring_type."""
    scorer = SCORER_DISPATCH.get(case.scoring_type)
    if not scorer:
        raise ValueError(f"Unknown scoring_type: {case.scoring_type}")
    return scorer(case, output)
