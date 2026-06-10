"""LLM Judge V2: task-type-specific rubrics, JSONL resume, parallel execution."""

from __future__ import annotations

import json
import re
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
    calculate_weighted_score,
    get_dimensions,
    get_json_format,
    get_rubric,
)
from airouter.engine.benchmark.schemas import JudgeResult, JudgeSummary
from airouter.models.model_registry import ModelRegistry

# ── Constants ─────────────────────────────────────────────────

DEFAULT_JUDGE_MODELS = ["qwen3.7-max", "deepseek-v4-pro"]
JUDGE_MAX_TOKENS = 4096
OUTPUT_CHAR_LIMIT = 30000
MAX_RETRIES = 5


# ── JSON parsing ─────────────────────────────────────────────


def _parse_judge_json(content: str) -> dict[str, Any] | None:
    """Parse JSON from judge response with 3-tier fallback."""
    content = content.strip()
    # Remove markdown code block if present
    if content.startswith("```"):
        content = content.split("\n", 1)[1] if "\n" in content else content[3:]
    if content.endswith("```"):
        content = content[:-3]
    content = content.strip()

    # Tier 1: direct parse
    try:
        result: dict[str, Any] = json.loads(content)
        return result
    except json.JSONDecodeError:
        pass

    # Tier 2: regex extract
    match = re.search(r"\{[^{}]*\}", content, re.DOTALL)
    if match:
        try:
            result = json.loads(match.group())
            return result
        except json.JSONDecodeError:
            # Tier 3: fix single quotes
            try:
                fixed = match.group().replace("'", '"')
                result = json.loads(fixed)
                return result
            except json.JSONDecodeError:
                pass

    return None


# ── Context building ─────────────────────────────────────────


def _build_judge_context(case_dict: dict, model_output: str) -> tuple[str, bool]:
    """Build judge prompt context from case + model output.

    Returns (context_text, judge_context_truncated).
    """
    parts: list[str] = []

    input_context = case_dict.get("input_context", "")
    if input_context:
        parts.append(f"## 项目上下文\n{input_context}")

    parts.append(f"## 任务要求\n{case_dict['prompt']}")

    eval_criteria = case_dict.get("evaluation_criteria")
    if eval_criteria:
        parts.append(f"## 评分标准\n{json.dumps(eval_criteria, ensure_ascii=False, indent=2)}")

    expected_issues = case_dict.get("expected_issues", [])
    if expected_issues:
        parts.append(f"## 预期应发现的问题\n{json.dumps(expected_issues, ensure_ascii=False)}")

    truncated_output = model_output[:OUTPUT_CHAR_LIMIT]
    judge_context_truncated = len(model_output) > OUTPUT_CHAR_LIMIT
    parts.append(f"## 模型回答\n{truncated_output}")

    return "\n\n".join(parts), judge_context_truncated


# ── Single judge call ────────────────────────────────────────


def _judge_one(
    adapter,
    judge_model: str,
    case_dict: dict,
    model: str,
    model_output: str,
    model_truncated: bool,
) -> JudgeResult:
    """Evaluate a single case×model pair with the judge."""
    task_type = case_dict.get("task_type", "CODE_GENERATION")
    rubric = get_rubric(task_type)
    json_format = get_json_format(task_type)
    context, judge_context_truncated = _build_judge_context(case_dict, model_output)

    prompt = (
        f"你是一个严格的技术评审专家。请对以下模型回答进行评分。\n\n"
        f"{rubric}\n\n"
        f"{context}\n\n"
        f"请以 JSON 格式返回（不要包含 markdown 代码块标记）：\n{json_format}"
    )

    messages = [{"role": "user", "content": prompt}]

    for attempt in range(MAX_RETRIES):
        try:
            resp: AdapterResponse = adapter.chat(
                model=judge_model,
                messages=messages,
                max_tokens=JUDGE_MAX_TOKENS,
                temperature=0,
            )

            # Check for reasoning starvation
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
                    time.sleep(wait)
                    continue

            if not resp.content or not resp.content.strip():
                if attempt < MAX_RETRIES - 1:
                    wait = min(2 ** attempt, 30)
                    print(f"  [empty response, retrying in {wait}s]")
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
                    usage={"prompt_tokens": resp.input_tokens, "completion_tokens": resp.output_tokens},
                )

            scores = _parse_judge_json(resp.content)
            if scores is None:
                if attempt < MAX_RETRIES - 1:
                    wait = min(2 ** attempt, 30)
                    print(f"  [JSON parse failed, retrying in {wait}s]")
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
                    usage={"prompt_tokens": resp.input_tokens, "completion_tokens": resp.output_tokens},
                )

            # Remove non-numeric keys
            dims = get_dimensions(task_type)
            dim_scores = {k: float(scores.get(k, 0)) for k in dims}
            weighted = calculate_weighted_score(task_type, dim_scores)
            normalized = weighted / 5.0

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
                judge_context_truncated=judge_context_truncated,
            )

    return JudgeResult(
        case_id=case_dict["id"],
        model=model,
        judge_model=judge_model,
        task_type=task_type,
        comment=f"max retries ({MAX_RETRIES}) exceeded",
        model_truncated=model_truncated,
        judge_context_truncated=judge_context_truncated,
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


# ── Main entry point ─────────────────────────────────────────


def run_absolute_judge(
    cases_path: str,
    raw_dir: str,
    judge_models: list[str] | None = None,
    output_path: str | None = None,
    resume_path: str | None = None,
    workers: int = 20,
) -> JudgeSummary:
    """Run LLM judge on all benchmark outputs.

    Uses ModelRegistry + AdapterFactory for API calls.
    """
    if judge_models is None:
        judge_models = DEFAULT_JUDGE_MODELS

    settings = AppSettings()
    models_cfg = load_models(settings.data_dir)
    registry = ModelRegistry(models_cfg)
    factory = AdapterFactory(settings)

    # Validate judge models exist in registry
    for jm in judge_models:
        entry = registry.get_by_name(jm)
        if entry is None:
            available = [m.name for m in registry.all_models]
            raise ValueError(f"Unknown judge model: {jm}. Available: {', '.join(available)}")

    # Load cases
    with open(cases_path) as f:
        data = yaml.safe_load(f)
    cases = data.get("cases", [])

    raw_path = Path(raw_dir)
    all_models = data.get("models", ["deepseek-v4-flash", "deepseek-v4-pro", "qwen3.7-plus", "glm-5.1", "qwen3.7-max"])

    # Setup output
    if output_path is None:
        output_path = str(Path(raw_dir).parent / "llm_judge_v2_results.jsonl")
    jsonl_path = Path(output_path)
    jsonl_path.parent.mkdir(parents=True, exist_ok=True)

    # Resume
    resume_jsonl = Path(resume_path) if resume_path else jsonl_path
    completed_keys = _load_completed_keys(resume_jsonl)
    if completed_keys:
        print(f"Resuming: loaded {len(completed_keys)} existing results")

    # Build work items — one per (case, model) pair, only if ANY judge_model is pending
    work_items: list[tuple[dict, str, str, bool]] = []  # (case, model, output, model_truncated)
    for case in cases:
        case_id = case["id"]
        for model in all_models:
            # Load raw output
            filename = f"{case_id}_{model}.txt"
            filepath = raw_path / filename
            if not filepath.exists():
                continue

            model_output = filepath.read_text()

            # Check if any judge_model still needs evaluation for this pair
            pending = False
            for jm in judge_models:
                key = f"{case_id}:{model}:{jm}"
                if key not in completed_keys:
                    pending = True
                    break
            if not pending:
                continue

            # Check model_truncated from metadata file
            meta_path = raw_path / f"{case_id}_{model}_meta.json"
            model_truncated = False
            if meta_path.exists():
                try:
                    meta = json.loads(meta_path.read_text())
                    model_truncated = meta.get("finish_reason") == "length"
                except (json.JSONDecodeError, KeyError):
                    pass

            work_items.append((case, model, model_output, model_truncated))

    total_work = len(work_items)
    total_expected = len(cases) * len(all_models) * len(judge_models)
    skipped = len(completed_keys)
    print(f"Starting Absolute Judge: models={judge_models}, workers={workers}")
    print(f"Total expected: {total_expected}, Skipped: {skipped}, To evaluate: {total_work}")

    # Create adapters (one per judge model's provider)
    adapters: dict[str, Any] = {}
    for jm in judge_models:
        entry = registry.get_by_name(jm)
        if entry is None:
            raise ValueError(f"Judge model not found: {jm}")
        adapters[jm] = factory.get_adapter(entry)

    # Execute
    lock = threading.Lock()
    results: list[JudgeResult] = []
    done_count = 0
    fail_count = 0
    start_time = time.time()

    def process_item(item):
        nonlocal done_count, fail_count
        case, model, model_output, model_truncated = item

        for jm in judge_models:
            key = f"{case['id']}:{model}:{jm}"
            with lock:
                if key in completed_keys:
                    continue

            result = _judge_one(adapters[jm], jm, case, model, model_output, model_truncated)

            with lock:
                if result.weighted_score > 0:
                    comment_short = result.comment[:40] if result.comment else ""
                    print(f"  ✓ {result.case_id} × {result.model} [{jm}]  score={result.normalized_score:.2f}  {comment_short}")
                    results.append(result)
                else:
                    print(f"  ✗ {result.case_id} × {result.model} [{jm}]  {result.comment}")
                    results.append(result)
                    fail_count += 1

                _append_jsonl(jsonl_path, result)
                completed_keys.add(key)
                done_count += 1
                remaining = total_work - done_count
                if remaining % 10 == 0:
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

    # Build summary from JSONL (source of truth)
    return _build_summary_from_jsonl(jsonl_path, judge_models, elapsed)


def _build_summary_from_jsonl(
    jsonl_path: Path, judge_models: list[str], elapsed: float
) -> JudgeSummary:
    """Build JudgeSummary from JSONL file (source of truth).

    Dedupe strategy: for each unique key, keep the LAST entry in the file.
    Reports duplicate_count so callers know how many re-evaluations occurred.
    """
    all_results: dict[str, JudgeResult] = {}  # key → latest result
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
                    # Always overwrite with the latest entry (last-wins)
                    all_results[key] = JudgeResult(**data)
                except (json.JSONDecodeError, Exception):
                    continue

    results_list = list(all_results.values())

    # Split by judge model
    summaries: list[JudgeSummary] = []
    for jm in judge_models:
        jm_results = [r for r in results_list if r.judge_model == jm]
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

        # Cost estimation from registry
        settings = AppSettings()
        models_cfg = load_models(settings.data_dir)
        registry = ModelRegistry(models_cfg)
        entry = registry.get_by_name(jm)
        total_prompt = sum(r.usage.get("prompt_tokens", 0) for r in jm_results)
        total_completion = sum(r.usage.get("completion_tokens", 0) for r in jm_results)
        cost = 0.0
        if entry:
            cost = (total_prompt / 1000 * entry.input_price_per_1k +
                    total_completion / 1000 * entry.output_price_per_1k)

        summaries.append(JudgeSummary(
            judge_model=jm,
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
        ))

    # Return combined summary (first judge's summary with combined stats)
    if len(summaries) == 1:
        return summaries[0]

    # Combine: merge all results, aggregate stats
    combined_results = []
    for s in summaries:
        combined_results.extend(s.results)

    combined_successful = sum(s.successful for s in summaries)
    combined_failed = sum(s.failed for s in summaries)
    combined_cost = sum(s.estimated_cost_cny for s in summaries)

    # Merge by_model across judges
    merged_scores: dict[str, list[float]] = {}
    for r in combined_results:
        if r.weighted_score > 0:
            merged_scores.setdefault(r.model, []).append(r.normalized_score)
    merged_by_model_stats: dict[str, dict[str, float]] = {
        m: {"avg": sum(scores) / len(scores), "count": float(len(scores))}
        for m, scores in merged_scores.items()
    }

    return JudgeSummary(
        judge_model=",".join(judge_models),
        total_evaluations=len(combined_results),
        successful=combined_successful,
        failed=combined_failed,
        total_lines=total_lines,
        duplicate_count=duplicate_count,
        model_truncated_count=sum(s.model_truncated_count for s in summaries),
        judge_context_truncated_count=sum(s.judge_context_truncated_count for s in summaries),
        starved_count=sum(s.starved_count for s in summaries),
        by_model=merged_by_model_stats,
        estimated_cost_cny=combined_cost,
        results=combined_results,
    )
