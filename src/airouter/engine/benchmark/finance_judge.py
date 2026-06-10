"""Finance-specific LLM Judge: audits rule-based scoring with MiniMax-M3.

Unlike the generic llm_judge_v2, this module:
- Includes artifact contents (CSV, policy docs) in the judge context
- Includes expected_answer and required_findings for ground truth comparison
- Injects rule scores so the judge can compare its assessment
- Collects red_flags and rule_score_disagreement
- Supports --limit for smoke testing
"""

from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import yaml

from airouter.adapters.base import AdapterRateLimitError, AdapterResponse, AdapterTimeoutError
from airouter.adapters.factory import AdapterFactory
from airouter.config import AppSettings, load_models
from airouter.engine.benchmark.judge_prompts import (
    VALID_RED_FLAGS,
    calculate_weighted_score,
    get_dimensions,
    get_finance_category_name,
    get_finance_json_format,
    get_finance_judge_task_type,
    get_rubric,
)
from airouter.engine.benchmark.schemas import JudgeResult, JudgeSummary
from airouter.models.model_registry import ModelRegistry

# ── Constants ─────────────────────────────────────────────────

DEFAULT_FINANCE_JUDGE = "MiniMax-M3"
JUDGE_MAX_TOKENS = 8192
OUTPUT_CHAR_LIMIT = 30000
MAX_RETRIES = 5


# ── JSON parsing ─────────────────────────────────────────────


def _parse_finance_judge_json(content: str) -> dict[str, Any] | None:
    """Parse JSON from finance judge response with multi-tier fallback.

    Handles MiniMax reasoning tags, markdown code fences, and mixed text.
    """
    import re

    content = content.strip()

    # Strip reasoning/thinking tags (MiniMax, Claude, etc.)
    content = re.sub(r"", "", content, flags=re.DOTALL)
    content = re.sub(r"", "", content, flags=re.DOTALL)
    content = content.strip()

    # Strip markdown code fences
    if content.startswith("```"):
        content = content.split("\n", 1)[1] if "\n" in content else content[3:]
    if content.endswith("```"):
        content = content[:-3]
    content = content.strip()

    # Tier 1: direct parse
    try:
        result: dict[str, Any] = json.loads(content)
        return result
    except (json.JSONDecodeError, ValueError):
        pass

    # Tier 2: regex extract first JSON object (more robust pattern)
    match = re.search(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", content, re.DOTALL)
    if match:
        try:
            parsed: dict[str, Any] = json.loads(match.group(0))
            return parsed
        except (json.JSONDecodeError, ValueError):
            pass

    # Tier 3: fix single quotes
    if match:
        fixed = match.group(0).replace("'", '"')
        try:
            parsed_fixed: dict[str, Any] = json.loads(fixed)
            return parsed_fixed
        except (json.JSONDecodeError, ValueError):
            pass

    # Tier 4: aggressive search for any JSON object
    for m in re.finditer(r"\{", content):
        start = m.start()
        depth = 0
        end = start
        for i, c in enumerate(content[start:], start):
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        if end > start:
            candidate = content[start:end]
            try:
                parsed_aggressive: dict[str, Any] = json.loads(candidate)
                return parsed_aggressive
            except (json.JSONDecodeError, ValueError):
                # Try fixing single quotes
                fixed_candidate = candidate.replace("'", '"')
                try:
                    parsed_fixed_aggressive: dict[str, Any] = json.loads(fixed_candidate)
                    return parsed_fixed_aggressive
                except (json.JSONDecodeError, ValueError):
                    continue

    return None


# ── Context building ─────────────────────────────────────────


def build_finance_judge_context(
    case_dict: dict,
    model_output: str,
    rule_score: float,
    rule_dimensions: dict[str, float],
    artifact_contents: str,
) -> tuple[str, bool]:
    """Build finance-specific judge context.

    Returns (context_text, truncated).
    """
    sections: list[str] = []

    # Category context
    category = case_dict.get("category", "UNKNOWN")
    category_cn = get_finance_category_name(category)
    sections.append(f"## 任务类别\n{category_cn}（{category}）")

    # Task prompt
    prompt = case_dict.get("prompt", "")
    if prompt:
        sections.append(f"## 任务要求\n{prompt}")

    # Input context
    input_ctx = case_dict.get("input_context", "")
    if input_ctx:
        sections.append(f"## 输入上下文\n{input_ctx}")

    # Artifact contents
    if artifact_contents:
        sections.append(f"## 附件内容\n{artifact_contents}")

    # Expected answer (ground truth)
    expected = case_dict.get("expected_answer", {})
    if expected:
        sections.append(f"## 参考答案\n```json\n{json.dumps(expected, ensure_ascii=False, indent=2)}\n```")

    # Required findings
    evaluation = case_dict.get("evaluation", {})
    req_findings = evaluation.get("required_findings", [])
    if not req_findings:
        req_findings = expected.get("required_findings", [])
    if req_findings:
        sections.append(f"## 必须发现的项\n{json.dumps(req_findings, ensure_ascii=False)}")

    # Forbidden findings
    forbidden = evaluation.get("forbidden_findings", [])
    if forbidden:
        sections.append(f"## 禁止出现的项（幻觉检测）\n{json.dumps(forbidden, ensure_ascii=False)}")

    # Current rule score
    dim_lines = [f"  - {k}: {v:.2f}" for k, v in rule_dimensions.items()]
    sections.append(
        f"## 当前规则评分\n"
        f"综合分: {rule_score:.3f}\n"
        f"各维度:\n" + "\n".join(dim_lines)
    )

    # Model output
    model_truncated = False
    output_text = model_output
    if len(output_text) > OUTPUT_CHAR_LIMIT:
        output_text = output_text[:OUTPUT_CHAR_LIMIT] + "\n...[truncated]"
        model_truncated = True
    sections.append(f"## 模型回答\n{output_text}")

    return "\n\n".join(sections), model_truncated


# ── Artifact loading ──────────────────────────────────────────


def _load_artifact_contents(case_dict: dict, cases_path: Path) -> str:
    """Load artifact files referenced by a case."""
    artifacts = case_dict.get("artifacts", [])
    if not artifacts:
        return ""

    root = cases_path.parent
    chunks: list[str] = []
    for artifact in artifacts:
        artifact_path = root / artifact
        if not artifact_path.exists() or not artifact_path.is_file():
            continue
        try:
            text = artifact_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if len(text) > 20000:
            text = text[:20000] + "\n...[truncated]"
        chunks.append(f"附件 {artifact} 内容：\n{text}")
    return "\n\n".join(chunks)


# ── Single pair judging ──────────────────────────────────────


def _finance_judge_one(
    adapter: Any,
    judge_model: str,
    case_dict: dict,
    model: str,
    model_output: str,
    model_truncated: bool,
    rule_score: float,
    rule_dimensions: dict[str, float],
    artifact_contents: str,
) -> JudgeResult:
    """Evaluate a single (case, model) pair with the finance judge."""
    category = case_dict.get("category", "TABLE_CALCULATION")
    task_type = get_finance_judge_task_type(category)
    rubric = get_rubric(task_type)
    json_format = get_finance_json_format(task_type)
    category_cn = get_finance_category_name(category)

    context, judge_context_truncated = build_finance_judge_context(
        case_dict, model_output, rule_score, rule_dimensions, artifact_contents,
    )

    prompt = (
        f"你是一位严格的企业财务评审专家。当前任务类别为「{category_cn}」。\n"
        f"请根据该类别的专业标准，对以下模型回答进行独立评分。\n"
        f"你可以看到参考答案、规则评分结果和原始附件数据。\n"
        f"请独立判断模型回答的质量，不要受规则评分影响。\n\n"
        f"{rubric}\n\n"
        f"{context}\n\n"
        f"请以 JSON 格式返回（不要包含 markdown 代码块标记）：\n{json_format}"
    )

    retry_instruction = (
        "上一次输出不是合法 JSON。请重新输出且只能输出一个 JSON 对象，"
        "不要解释、不要 Markdown、不要 reasoning 标签、不要  标签。"
        "直接输出 JSON，以 { 开头，以 } 结尾。\n\n"
        f"{json_format}"
    )

    messages: list[dict] = [{"role": "user", "content": prompt}]

    for attempt in range(MAX_RETRIES):
        try:
            resp: AdapterResponse = adapter.chat(
                model=judge_model,
                messages=messages,
                max_tokens=JUDGE_MAX_TOKENS,
                temperature=0,
            )

            # Check reasoning starvation
            raw_usage = resp.raw_usage or {}
            reasoning_starved = False
            finish_reason = raw_usage.get("finish_reason", "")
            reasoning_tokens = raw_usage.get("reasoning_tokens", 0)
            completion_tokens = resp.output_tokens
            if (
                finish_reason == "length"
                and reasoning_tokens > 0
                and completion_tokens > 0
                and reasoning_tokens / completion_tokens > 0.9
            ):
                reasoning_starved = True
                if attempt < MAX_RETRIES - 1:
                    wait = min(2 ** attempt, 30)
                    print(f"  [starvation detected, retrying in {wait}s]")
                    messages.append({"role": "assistant", "content": resp.content or ""})
                    messages.append({"role": "user", "content": retry_instruction})
                    time.sleep(wait)
                    continue

            if not resp.content or not resp.content.strip():
                if attempt < MAX_RETRIES - 1:
                    wait = min(2 ** attempt, 30)
                    print(f"  [empty response, retrying in {wait}s]")
                    messages.append({"role": "assistant", "content": ""})
                    messages.append({"role": "user", "content": retry_instruction})
                    time.sleep(wait)
                    continue
                return JudgeResult(
                    case_id=case_dict["id"],
                    model=model,
                    judge_model=judge_model,
                    task_type=task_type,
                    comment="empty response (reasoning starvation)",
                    model_truncated=model_truncated,
                    judge_context_truncated=judge_context_truncated,
                    reasoning_starved=True,
                    rule_score=rule_score,
                    usage={"prompt_tokens": resp.input_tokens, "completion_tokens": resp.output_tokens},
                )

            scores = _parse_finance_judge_json(resp.content)
            if scores is None:
                if attempt < MAX_RETRIES - 1:
                    wait = min(2 ** attempt, 30)
                    print(f"  [JSON parse failed, retrying in {wait}s]")
                    messages.append({"role": "assistant", "content": resp.content})
                    messages.append({"role": "user", "content": retry_instruction})
                    time.sleep(wait)
                    continue
                return JudgeResult(
                    case_id=case_dict["id"],
                    model=model,
                    judge_model=judge_model,
                    task_type=task_type,
                    comment=f"JSON parse failed: {resp.content[:100]}",
                    model_truncated=model_truncated,
                    judge_context_truncated=judge_context_truncated,
                    rule_score=rule_score,
                    usage={"prompt_tokens": resp.input_tokens, "completion_tokens": resp.output_tokens},
                )

            # Validate that parsed JSON contains expected dimension keys
            dims = get_dimensions(task_type)
            dim_scores = {k: float(scores.get(k, 0)) for k in dims}
            # Check if at least one dimension has a non-zero value
            if all(v == 0 for v in dim_scores.values()) and not scores.get("comment"):
                # JSON parsed but no valid dimensions and no comment - likely malformed
                if attempt < MAX_RETRIES - 1:
                    wait = min(2 ** attempt, 30)
                    print(f"  [empty dimensions, retrying in {wait}s]")
                    messages.append({"role": "assistant", "content": resp.content})
                    messages.append({"role": "user", "content": retry_instruction})
                    time.sleep(wait)
                    continue
                return JudgeResult(
                    case_id=case_dict["id"],
                    model=model,
                    judge_model=judge_model,
                    task_type=task_type,
                    comment=f"judge_call_failed: empty dimensions, raw={resp.content[:100]}",
                    model_truncated=model_truncated,
                    judge_context_truncated=judge_context_truncated,
                    rule_score=rule_score,
                    usage={"prompt_tokens": resp.input_tokens, "completion_tokens": resp.output_tokens},
                )

            # Extract dimension scores
            weighted = calculate_weighted_score(task_type, dim_scores)
            normalized = weighted / 5.0

            # Extract red_flags with validation
            raw_flags = scores.get("red_flags", [])
            if not isinstance(raw_flags, list):
                raw_flags = []
            red_flags = [f for f in raw_flags if isinstance(f, str) and f in VALID_RED_FLAGS]

            # Extract rule_score_disagreement (informational only)
            raw_disagree = scores.get("rule_score_disagreement", "")
            if not isinstance(raw_disagree, str) or raw_disagree not in (
                "agree", "rule_too_high", "rule_too_low", "unclear"
            ):
                raw_disagree = "unclear"

            return JudgeResult(
                case_id=case_dict["id"],
                model=model,
                judge_model=judge_model,
                task_type=task_type,
                dimensions=dim_scores,
                weighted_score=weighted,
                normalized_score=normalized,
                comment=scores.get("comment", ""),
                model_truncated=model_truncated,
                judge_context_truncated=judge_context_truncated,
                reasoning_starved=reasoning_starved,
                rule_score=rule_score,
                rule_score_disagreement=raw_disagree,
                red_flags=red_flags,
                usage={"prompt_tokens": resp.input_tokens, "completion_tokens": resp.output_tokens},
            )

        except AdapterRateLimitError:
            wait = min(2 ** attempt, 30)
            print(f"  [429 rate limit, waiting {wait}s, attempt {attempt + 1}/{MAX_RETRIES}]")
            time.sleep(wait)
        except AdapterTimeoutError:
            wait = min(2 ** attempt, 30)
            print(f"  [timeout, waiting {wait}s, attempt {attempt + 1}/{MAX_RETRIES}]")
            time.sleep(wait)
        except Exception as e:
            return JudgeResult(
                case_id=case_dict["id"],
                model=model,
                judge_model=judge_model,
                task_type=task_type,
                comment=f"error: {str(e)[:200]}",
                model_truncated=model_truncated,
                judge_context_truncated=False,
                rule_score=rule_score,
            )

    return JudgeResult(
        case_id=case_dict["id"],
        model=model,
        judge_model=judge_model,
        task_type=task_type,
        comment=f"max retries ({MAX_RETRIES}) exceeded",
        model_truncated=model_truncated,
        judge_context_truncated=False,
        rule_score=rule_score,
    )


# ── JSONL resume ─────────────────────────────────────────────


def _load_completed_keys(jsonl_path: Path) -> set[str]:
    """Load set of completed result keys from JSONL file."""
    completed: set[str] = set()
    if jsonl_path.exists():
        with open(jsonl_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    key = f"{data.get('case_id', '')}:{data.get('model', '')}:{data.get('judge_model', '')}"
                    if data.get("weighted_score", 0) > 0:
                        completed.add(key)
                except json.JSONDecodeError:
                    continue
    return completed


def _append_jsonl(jsonl_path: Path, result: JudgeResult) -> None:
    """Append a result to JSONL file."""
    with open(jsonl_path, "a") as f:
        f.write(result.model_dump_json() + "\n")


# ── Summary builder ──────────────────────────────────────────


def _build_finance_judge_summary(
    jsonl_path: Path, judge_model: str, elapsed: float
) -> JudgeSummary:
    """Build JudgeSummary from JSONL file."""
    all_results: dict[str, JudgeResult] = {}
    duplicate_count = 0
    total_lines = 0

    if jsonl_path.exists():
        with open(jsonl_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                total_lines += 1
                try:
                    data = json.loads(line)
                    key = f"{data.get('case_id')}:{data.get('model')}:{data.get('judge_model')}"
                    if key in all_results:
                        duplicate_count += 1
                    all_results[key] = JudgeResult(**data)
                except (json.JSONDecodeError, Exception):
                    continue

    results_list = list(all_results.values())
    jm_results = [r for r in results_list if r.judge_model == judge_model]
    successful = [r for r in jm_results if r.weighted_score > 0]
    failed = len(jm_results) - len(successful)

    by_model_scores: dict[str, list[float]] = {}
    for r in successful:
        by_model_scores.setdefault(r.model, []).append(r.normalized_score)
    by_model: dict[str, dict[str, float]] = {
        m: {"avg": sum(scores) / len(scores), "count": float(len(scores))}
        for m, scores in by_model_scores.items()
    }

    by_task_type_scores: dict[str, dict[str, list[float]]] = {}
    for r in successful:
        by_task_type_scores.setdefault(r.task_type, {}).setdefault(r.model, []).append(r.normalized_score)
    by_task_type: dict[str, dict[str, float]] = {
        tt: {m: sum(scores) / len(scores) for m, scores in model_scores.items()}
        for tt, model_scores in by_task_type_scores.items()
    }

    # Cost estimation
    settings = AppSettings()
    models_cfg = load_models(settings.data_dir)
    registry = ModelRegistry(models_cfg)
    entry = registry.get_by_name(judge_model)
    total_prompt = sum(r.usage.get("prompt_tokens", 0) for r in jm_results)
    total_completion = sum(r.usage.get("completion_tokens", 0) for r in jm_results)
    cost = 0.0
    if entry:
        cost = (total_prompt / 1000 * entry.input_price_per_1k +
                total_completion / 1000 * entry.output_price_per_1k)

    return JudgeSummary(
        judge_model=judge_model,
        total_evaluations=len(jm_results),
        successful=len(successful),
        failed=failed,
        total_lines=total_lines,
        duplicate_count=duplicate_count,
        model_truncated_count=sum(1 for r in jm_results if r.model_truncated),
        judge_context_truncated_count=sum(1 for r in jm_results if r.judge_context_truncated),
        starved_count=sum(1 for r in jm_results if r.reasoning_starved),
        by_model=by_model,
        by_task_type=by_task_type,
        estimated_cost_cny=cost,
        results=jm_results,
    )


def load_judge_summary_from_jsonl(
    run_dir: Path, judge_model: str
) -> JudgeSummary | None:
    """Load JudgeSummary from an existing JSONL file (no API calls).

    Searches for full > targeted > smoke JSONL in run_dir.
    Returns None if no JSONL found.
    """
    slug = judge_model.lower().replace("-", "_").replace(".", "_")
    candidates = list(run_dir.glob(f"finance_judge_{slug}*.jsonl"))
    if not candidates:
        return None

    # Prefer full > targeted > smoke
    preferred_order = [
        f"finance_judge_{slug}",
        f"finance_judge_{slug}.targeted",
        f"finance_judge_{slug}.smoke",
    ]
    jsonl_path = candidates[0]
    for name in preferred_order:
        p = run_dir / f"{name}.jsonl"
        if p.exists():
            jsonl_path = p
            break

    return _build_finance_judge_summary(jsonl_path, judge_model, elapsed=0.0)


# ── Main entry point ─────────────────────────────────────────


def run_finance_judge(
    cases_path: str,
    raw_dir: str,
    results_jsonl_path: str,
    judge_models: list[str] | None = None,
    output_path: str | None = None,
    workers: int = 10,
    limit: int | None = None,
    case_ids: list[str] | None = None,
) -> JudgeSummary:
    """Run finance-specific LLM judge on existing benchmark outputs.

    Does NOT call the evaluated models. Only reads raw_outputs and calls
    the judge model.

    Args:
        cases_path: Path to finance_cases.yaml
        raw_dir: Path to raw_outputs/ directory
        results_jsonl_path: Path to results.rescored.jsonl or results.jsonl
        judge_models: Judge model list (v1: only MiniMax-M3)
        output_path: Output JSONL path
        workers: Concurrent workers
        limit: Max pairs to evaluate (for smoke testing)
        case_ids: Only evaluate specific case IDs (for targeted audit)
    """
    if judge_models is None:
        judge_models = [DEFAULT_FINANCE_JUDGE]

    judge_model = judge_models[0]  # v1: single judge

    settings = AppSettings()
    models_cfg = load_models(settings.data_dir)
    registry = ModelRegistry(models_cfg)
    factory = AdapterFactory(settings)

    # Validate judge model
    entry = registry.get_by_name(judge_model)
    if entry is None:
        available = [m.name for m in registry.all_models]
        raise ValueError(f"Unknown judge model: {judge_model}. Available: {', '.join(available)}")

    # Load cases
    with open(cases_path) as f:
        data = yaml.safe_load(f)
    cases = data.get("cases", [])
    all_models = data.get("models", [
        "deepseek-v4-flash", "deepseek-v4-pro", "qwen3.7-plus", "glm-5.1", "qwen3.7-max"
    ])

    cases_path_obj = Path(cases_path)
    raw_path = Path(raw_dir)

    # Setup output
    if output_path is None:
        model_slug = judge_model.lower().replace("-", "_").replace(".", "_")
        if case_ids is not None:
            suffix = ".targeted"
        elif limit is not None:
            suffix = ".smoke"
        else:
            suffix = ""
        output_path = str(Path(raw_dir).parent / f"finance_judge_{model_slug}{suffix}.jsonl")
    jsonl_path = Path(output_path)
    jsonl_path.parent.mkdir(parents=True, exist_ok=True)

    # Load rule scores from results JSONL
    rule_scores: dict[str, dict[str, Any]] = {}
    results_path = Path(results_jsonl_path)
    if results_path.exists():
        with open(results_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                    key = f"{record.get('case_id', '')}::{record.get('model', '')}"
                    rule_scores[key] = {
                        "overall_score": record.get("overall_score", 0.0),
                        "dimension_scores": record.get("dimension_scores", {}),
                    }
                except json.JSONDecodeError:
                    continue

    # Resume
    completed_keys = _load_completed_keys(jsonl_path)
    if completed_keys:
        print(f"Resuming: loaded {len(completed_keys)} existing judge results")

    # Build work items
    work_items: list[tuple[dict, str, str, bool, float, dict[str, float], str]] = []
    case_ids_set = set(case_ids) if case_ids else None
    for case in cases:
        case_id = case["id"]
        # Filter by case_ids if specified
        if case_ids_set is not None and case_id not in case_ids_set:
            continue
        for model in all_models:
            key = f"{case_id}:{model}:{judge_model}"
            if key in completed_keys:
                continue

            # Load raw output
            filename = f"{case_id}_{model}.txt"
            filepath = raw_path / filename
            if not filepath.exists():
                continue

            model_output = filepath.read_text()

            # Check model_truncated from metadata
            meta_path = raw_path / f"{case_id}_{model}_meta.json"
            model_truncated = False
            if meta_path.exists():
                try:
                    meta = json.loads(meta_path.read_text())
                    model_truncated = meta.get("finish_reason") == "length"
                except (json.JSONDecodeError, KeyError):
                    pass

            # Get rule score
            rule_key = f"{case_id}::{model}"
            rule_data = rule_scores.get(rule_key, {"overall_score": 0.0, "dimension_scores": {}})

            # Load artifact contents
            artifact_contents = _load_artifact_contents(case, cases_path_obj)

            work_items.append((
                case, model, model_output, model_truncated,
                rule_data["overall_score"],
                rule_data["dimension_scores"],
                artifact_contents,
            ))

    # Apply limit
    if limit is not None:
        work_items = work_items[:limit]

    total_work = len(work_items)
    skipped = len(completed_keys)
    print(f"Starting Finance Judge: model={judge_model}, workers={workers}")
    print(f"To evaluate: {total_work}, Skipped: {skipped}")
    if case_ids is not None:
        print(f"  🎯 TARGETED MODE: {len(case_ids)} cases ({', '.join(case_ids)})")
    if limit is not None:
        print(f"  ⚠ SMOKE MODE: limited to {limit} pairs")

    # Create adapter
    adapter = factory.get_adapter(entry)

    # Execute
    lock = threading.Lock()
    results: list[JudgeResult] = []
    done_count = 0
    fail_count = 0
    start_time = time.time()

    def process_item(item):
        nonlocal done_count, fail_count
        case, model, model_output, model_truncated, r_score, r_dims, art_contents = item

        jm_key = f"{case['id']}:{model}:{judge_model}"
        with lock:
            if jm_key in completed_keys:
                return

        result = _finance_judge_one(
            adapter, judge_model, case, model, model_output,
            model_truncated, r_score, r_dims, art_contents,
        )

        with lock:
            if result.weighted_score > 0:
                comment_short = result.comment[:40] if result.comment else ""
                print(
                    f"  ✓ {result.case_id} × {result.model} [{judge_model}]  "
                    f"score={result.normalized_score:.2f}  rule={result.rule_score:.2f}  "
                    f"{comment_short}"
                )
            else:
                print(f"  ✗ {result.case_id} × {result.model} [{judge_model}]  {result.comment}")
                fail_count += 1

            results.append(result)
            _append_jsonl(jsonl_path, result)
            completed_keys.add(jm_key)
            done_count += 1
            remaining = total_work - done_count
            if remaining > 0 and remaining % 10 == 0:
                print(f"  ── progress: {done_count}/{total_work}, {remaining} remaining, {fail_count} failed")

    if workers <= 1:
        for item in work_items:
            process_item(item)
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(process_item, item): item for item in work_items}
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as e:
                    print(f"  ✗ worker exception: {e}")

    elapsed = time.time() - start_time
    print(f"\nDone: {done_count} evaluated, {fail_count} failed, {skipped} skipped, {elapsed:.1f}s")

    return _build_finance_judge_summary(jsonl_path, judge_model, elapsed)
