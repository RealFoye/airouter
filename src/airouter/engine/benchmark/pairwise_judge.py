"""Pairwise Judge: A/B blind comparison with hidden model names."""

from __future__ import annotations

import json
import random
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from itertools import combinations
from pathlib import Path
from typing import Any

import yaml

from airouter.adapters.base import AdapterRateLimitError, AdapterResponse, AdapterTimeoutError
from airouter.adapters.factory import AdapterFactory
from airouter.config import AppSettings, load_models
from airouter.engine.benchmark.judge_prompts import get_dimensions
from airouter.engine.benchmark.schemas import PairwiseResult, PairwiseSummary
from airouter.models.model_registry import ModelRegistry

# ── Constants ─────────────────────────────────────────────────

DEFAULT_JUDGE_MODELS = ["qwen3.7-max", "deepseek-v4-pro"]
PAIRWISE_MAX_TOKENS = 4096
OUTPUT_CHAR_LIMIT = 20000
MAX_RETRIES = 5


# ── JSON parsing ─────────────────────────────────────────────


def _parse_pairwise_json(content: str) -> dict[str, Any] | None:
    """Parse JSON from pairwise response with 3-tier fallback."""
    content = content.strip()
    if content.startswith("```"):
        content = content.split("\n", 1)[1] if "\n" in content else content[3:]
    if content.endswith("```"):
        content = content[:-3]
    content = content.strip()

    try:
        result: dict[str, Any] = json.loads(content)
        return result
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{[^{}]*\}", content, re.DOTALL)
    if match:
        try:
            result = json.loads(match.group())
            return result
        except json.JSONDecodeError:
            try:
                result = json.loads(match.group().replace("'", '"'))
                return result
            except json.JSONDecodeError:
                pass
    return None


# ── Pairwise prompt ──────────────────────────────────────────


def _build_pairwise_prompt(
    case_dict: dict,
    output_a: str,
    output_b: str,
    task_type: str,
) -> str:
    """Build pairwise comparison prompt using task-type dimensions."""
    dims = get_dimensions(task_type)
    dim_lines = "\n".join(f"- {k} (权重 {v})" for k, v in dims.items())

    parts = [
        "你是一个严格的技术评审专家。请比较两个模型对同一任务的回答质量。",
        "",
        f"## 任务要求\n{case_dict['prompt']}",
    ]

    input_context = case_dict.get("input_context", "")
    if input_context:
        parts.append(f"## 项目上下文\n{input_context}")

    parts.append(f"## 评分维度（{task_type}）\n{dim_lines}")
    parts.append(f"## Model A 的回答\n{output_a[:OUTPUT_CHAR_LIMIT]}")
    parts.append(f"## Model B 的回答\n{output_b[:OUTPUT_CHAR_LIMIT]}")
    parts.append(
        "请按上述维度逐一比较，综合判断哪个更好，或是否平局。\n\n"
        "请以 JSON 格式返回（不要包含 markdown 代码块标记）：\n"
        '{"winner": "A" | "B" | "tie", "reason": "一句话理由", '
        '"dimension_winners": {"<dim1>": "A"|"B"|"tie", ...}}'
    )

    return "\n\n".join(parts)


# ── Single pairwise call ─────────────────────────────────────


def _pairwise_one(
    adapter,
    judge_model: str,
    case_dict: dict,
    model_a: str,
    model_b: str,
    output_a: str,
    output_b: str,
) -> PairwiseResult:
    """Run a single pairwise comparison."""
    task_type = case_dict.get("task_type", "CODE_GENERATION")

    # Local RNG for A/B order (not global random.seed)
    rng = random.Random(f"{case_dict['id']}:{model_a}:{model_b}:{judge_model}")
    swap = rng.random() < 0.5

    if swap:
        actual_a_output, actual_b_output = output_b, output_a
        a_was_first = False  # A position has model_b's output
    else:
        actual_a_output, actual_b_output = output_a, output_b
        a_was_first = True

    prompt = _build_pairwise_prompt(case_dict, actual_a_output, actual_b_output, task_type)
    messages = [{"role": "user", "content": prompt}]

    for attempt in range(MAX_RETRIES):
        try:
            resp: AdapterResponse = adapter.chat(
                model=judge_model,
                messages=messages,
                max_tokens=PAIRWISE_MAX_TOKENS,
                temperature=0,
            )

            if not resp.content or not resp.content.strip():
                if attempt < MAX_RETRIES - 1:
                    wait = min(2 ** attempt, 30)
                    time.sleep(wait)
                    continue
                return PairwiseResult(
                    case_id=case_dict["id"],
                    model_a=model_a,
                    model_b=model_b,
                    judge_model=judge_model,
                    winner_label="",
                    reason="empty response",
                    a_was_first=a_was_first,
                    usage={"prompt_tokens": resp.input_tokens, "completion_tokens": resp.output_tokens},
                )

            parsed = _parse_pairwise_json(resp.content)
            if parsed is None:
                if attempt < MAX_RETRIES - 1:
                    wait = min(2 ** attempt, 30)
                    time.sleep(wait)
                    continue
                return PairwiseResult(
                    case_id=case_dict["id"],
                    model_a=model_a,
                    model_b=model_b,
                    judge_model=judge_model,
                    winner_label="",
                    reason=f"JSON parse failed: {resp.content[:100]}",
                    a_was_first=a_was_first,
                    usage={"prompt_tokens": resp.input_tokens, "completion_tokens": resp.output_tokens},
                )

            winner_label = parsed.get("winner", "tie")
            dim_winners = parsed.get("dimension_winners", {})

            # Map winner_label back to real model name
            if winner_label == "tie":
                winner_model = None
            elif winner_label == "A":
                winner_model = model_a if a_was_first else model_b
            elif winner_label == "B":
                winner_model = model_b if a_was_first else model_a
            else:
                winner_model = None

            return PairwiseResult(
                case_id=case_dict["id"],
                model_a=model_a,
                model_b=model_b,
                judge_model=judge_model,
                winner_label=winner_label,
                winner_model=winner_model,
                reason=parsed.get("reason", ""),
                dimension_winners=dim_winners,
                a_was_first=a_was_first,
                usage={"prompt_tokens": resp.input_tokens, "completion_tokens": resp.output_tokens},
            )

        except AdapterRateLimitError:
            wait = min(2 ** attempt, 30)
            time.sleep(wait)
        except AdapterTimeoutError:
            wait = min(2 ** attempt, 30)
            time.sleep(wait)
        except Exception as e:
            return PairwiseResult(
                case_id=case_dict["id"],
                model_a=model_a,
                model_b=model_b,
                judge_model=judge_model,
                winner_label="",
                reason=f"error: {str(e)[:200]}",
                a_was_first=a_was_first,
            )

    return PairwiseResult(
        case_id=case_dict["id"],
        model_a=model_a,
        model_b=model_b,
        judge_model=judge_model,
        winner_label="",
        reason=f"max retries ({MAX_RETRIES}) exceeded",
        a_was_first=a_was_first,
    )


# ── JSONL resume ─────────────────────────────────────────────


def _load_completed_keys(jsonl_path: Path) -> set[str]:
    """Load completed result keys from JSONL."""
    completed: set[str] = set()
    if jsonl_path.exists():
        with open(jsonl_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    key = f"{data.get('case_id')}:{data.get('model_a')}:{data.get('model_b')}:{data.get('judge_model')}"
                    if data.get("winner_label"):
                        completed.add(key)
                except json.JSONDecodeError:
                    continue
    return completed


def _append_jsonl(jsonl_path: Path, result: PairwiseResult) -> None:
    """Append result to JSONL."""
    with open(jsonl_path, "a") as f:
        f.write(result.model_dump_json() + "\n")


# ── Main entry point ─────────────────────────────────────────


def run_pairwise_judge(
    cases_path: str,
    raw_dir: str,
    judge_models: list[str] | None = None,
    all_models: list[str] | None = None,
    output_path: str | None = None,
    resume_path: str | None = None,
    workers: int = 20,
) -> PairwiseSummary:
    """Run pairwise A/B comparison on all model pairs.

    Uses ModelRegistry + AdapterFactory for API calls.
    """
    if judge_models is None:
        judge_models = DEFAULT_JUDGE_MODELS

    settings = AppSettings()
    models_cfg = load_models(settings.data_dir)
    registry = ModelRegistry(models_cfg)
    factory = AdapterFactory(settings)

    # Validate judge models
    for jm in judge_models:
        entry = registry.get_by_name(jm)
        if entry is None:
            available = [m.name for m in registry.all_models]
            raise ValueError(f"Unknown judge model: {jm}. Available: {', '.join(available)}")

    # Load cases
    with open(cases_path) as f:
        data = yaml.safe_load(f)
    cases = data.get("cases", [])

    if all_models is None:
        all_models = data.get("models", ["deepseek-v4-flash", "deepseek-v4-pro", "qwen3.7-plus", "glm-5.1", "qwen3.7-max"])

    # Generate model pairs
    model_pairs = list(combinations(all_models, 2))
    raw_path = Path(raw_dir)

    # Setup output
    if output_path is None:
        output_path = str(Path(raw_dir).parent / "pairwise_results.jsonl")
    jsonl_path = Path(output_path)
    jsonl_path.parent.mkdir(parents=True, exist_ok=True)

    # Resume
    resume_jsonl = Path(resume_path) if resume_path else jsonl_path
    completed_keys = _load_completed_keys(resume_jsonl)
    if completed_keys:
        print(f"Resuming: loaded {len(completed_keys)} existing pairwise results")

    # Build work items — one per (case, model_a, model_b) triple, only if ANY judge_model is pending
    work_items: list[tuple[dict, str, str, str, str]] = []  # (case, model_a, model_b, output_a, output_b)
    for case in cases:
        case_id = case["id"]
        for model_a, model_b in model_pairs:
            path_a = raw_path / f"{case_id}_{model_a}.txt"
            path_b = raw_path / f"{case_id}_{model_b}.txt"
            if not path_a.exists() or not path_b.exists():
                continue

            # Check if any judge_model still needs evaluation for this pair
            pending = False
            for jm in judge_models:
                key = f"{case_id}:{model_a}:{model_b}:{jm}"
                if key not in completed_keys:
                    pending = True
                    break
            if not pending:
                continue

            output_a = path_a.read_text()
            output_b = path_b.read_text()
            work_items.append((
                case, model_a, model_b, output_a, output_b,
            ))

    total_expected = len(cases) * len(model_pairs) * len(judge_models)
    skipped = len(completed_keys)
    total_work = len(work_items)
    print(f"Starting Pairwise Judge: models={judge_models}, workers={workers}")
    print(f"Pairs per case: {len(model_pairs)}, Total expected: {total_expected}, Skipped: {skipped}, To evaluate: {total_work}")

    # Create adapters
    adapters: dict[str, Any] = {}
    for jm in judge_models:
        entry = registry.get_by_name(jm)
        if entry is None:
            raise ValueError(f"Judge model not found: {jm}")
        adapters[jm] = factory.get_adapter(entry)

    # Execute
    lock = threading.Lock()
    results: list[PairwiseResult] = []
    done_count = 0
    fail_count = 0
    start_time = time.time()

    def process_item(item):
        nonlocal done_count, fail_count
        case, model_a, model_b, output_a, output_b = item

        for jm in judge_models:
            key = f"{case['id']}:{model_a}:{model_b}:{jm}"
            with lock:
                if key in completed_keys:
                    continue

            result = _pairwise_one(adapters[jm], jm, case, model_a, model_b, output_a, output_b)

            with lock:
                if result.winner_label:
                    print(f"  ✓ {result.case_id} {result.model_a} vs {result.model_b} [{jm}]  winner={result.winner_model or 'tie'}")
                    results.append(result)
                else:
                    print(f"  ✗ {result.case_id} {result.model_a} vs {result.model_b} [{jm}]  {result.reason}")
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

    return _build_summary_from_jsonl(jsonl_path, judge_models, all_models, elapsed)


def _build_summary_from_jsonl(
    jsonl_path: Path,
    judge_models: list[str],
    all_models: list[str],
    elapsed: float,
) -> PairwiseSummary:
    """Build PairwiseSummary from JSONL file (source of truth).

    Dedupe strategy: for each unique key, keep the LAST entry in the file.
    Reports duplicate_count so callers know how many re-evaluations occurred.
    """
    all_results: dict[str, PairwiseResult] = {}  # key → latest result
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
                    key = f"{data.get('case_id')}:{data.get('model_a')}:{data.get('model_b')}:{data.get('judge_model')}"
                    if key in all_results:
                        duplicate_count += 1
                    # Always overwrite with the latest entry (last-wins)
                    all_results[key] = PairwiseResult(**data)
                except (json.JSONDecodeError, Exception):
                    continue

    results_list = list(all_results.values())

    successful = [r for r in results_list if r.winner_label]
    failed = len(results_list) - len(successful)

    # Calculate win rates
    win_counts: dict[str, dict[str, int]] = {m: {} for m in all_models}
    loss_counts: dict[str, dict[str, int]] = {m: {} for m in all_models}
    tie_counts: dict[str, int] = {m: 0 for m in all_models}
    total_wins: dict[str, int] = {m: 0 for m in all_models}
    total_losses: dict[str, int] = {m: 0 for m in all_models}

    for r in successful:
        ma, mb = r.model_a, r.model_b
        if r.winner_model == ma:
            win_counts[ma][mb] = win_counts[ma].get(mb, 0) + 1
            loss_counts[mb][ma] = loss_counts[mb].get(ma, 0) + 1
            total_wins[ma] += 1
            total_losses[mb] += 1
        elif r.winner_model == mb:
            win_counts[mb][ma] = win_counts[mb].get(ma, 0) + 1
            loss_counts[ma][mb] = loss_counts[ma].get(mb, 0) + 1
            total_wins[mb] += 1
            total_losses[ma] += 1
        else:
            tie_counts[ma] += 1
            tie_counts[mb] += 1

    # Win rates: {model: {opponent: win_rate}}
    win_rates: dict[str, dict[str, float]] = {}
    for m in all_models:
        win_rates[m] = {}
        for opp in all_models:
            if m == opp:
                continue
            w = win_counts.get(m, {}).get(opp, 0)
            losses = loss_counts.get(m, {}).get(opp, 0)
            t = 0  # per-opponent ties not tracked separately
            total = w + losses
            win_rates[m][opp] = w / total if total > 0 else 0.0

    # Overall ranking
    ranking = []
    for m in all_models:
        w = total_wins.get(m, 0)
        losses = total_losses.get(m, 0)
        t = tie_counts.get(m, 0)
        total = w + losses + t
        wr = w / total if total > 0 else 0.0
        ranking.append({"model": m, "wins": w, "losses": losses, "ties": t, "win_rate": wr})
    ranking.sort(key=lambda x: x["win_rate"], reverse=True)  # type: ignore[arg-type,return-value]

    # Judge agreement rate
    agree = 0
    disagree = 0
    results_by_pair: dict[str, list[PairwiseResult]] = {}
    for r in successful:
        pair_key = f"{r.case_id}:{r.model_a}:{r.model_b}"
        results_by_pair.setdefault(pair_key, []).append(r)

    for pair_key, pair_results in results_by_pair.items():
        if len(pair_results) >= 2:
            r1, r2 = pair_results[0], pair_results[1]
            if r1.winner_model == r2.winner_model:
                agree += 1
            else:
                disagree += 1

    agreement_rate = agree / (agree + disagree) if (agree + disagree) > 0 else 0.0

    # Cost estimation
    settings = AppSettings()
    models_cfg = load_models(settings.data_dir)
    registry = ModelRegistry(models_cfg)
    total_cost = 0.0
    for jm in judge_models:
        entry = registry.get_by_name(jm)
        if entry:
            jm_results = [r for r in results_list if r.judge_model == jm]
            total_prompt = sum(r.usage.get("prompt_tokens", 0) for r in jm_results)
            total_completion = sum(r.usage.get("completion_tokens", 0) for r in jm_results)
            total_cost += (total_prompt / 1000 * entry.input_price_per_1k +
                          total_completion / 1000 * entry.output_price_per_1k)

    return PairwiseSummary(
        total_pairs=len(list(combinations(all_models, 2))),
        total_judges=len(judge_models),
        total_calls=len(results_list),
        successful=len(successful),
        failed=failed,
        total_lines=total_lines,
        duplicate_count=duplicate_count,
        win_rates=win_rates,
        overall_ranking=ranking,
        agreement_rate=agreement_rate,
        judge_agreement_detail={"agree": agree, "disagree": disagree},
        estimated_cost_cny=total_cost,
        results=results_list,
    )
