"""LLM Judge: use an LLM to evaluate benchmark outputs (parallel version)."""

from __future__ import annotations

import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import yaml
from openai import OpenAI, RateLimitError

# Judge prompt template
JUDGE_PROMPT = """你是一个严格的技术评审专家。请对以下模型回答进行评分。

## 任务要求
{prompt}

## 模型回答
{output}

请从以下 4 个维度评分（1-5 分），并给出简短评语：
1. 正确性（correctness, 权重 0.35）：代码/分析/设计是否有根本性错误？逻辑是否正确？
2. 完整性（completeness, 权重 0.30）：是否覆盖了任务要求的所有要点？
3. 实用性（practicality, 权重 0.20）：给出的方案在实际工程中能用吗？代码能直接运行吗？
4. 深度（depth, 权重 0.15）：是否有深入的分析和权衡，而非表面罗列？

评分标准：
- 1 分：完全不达标
- 2 分：有明显不足
- 3 分：基本达标，有小问题
- 4 分：良好，质量较高
- 5 分：优秀，可直接用于生产

请以 JSON 格式返回（不要包含 markdown 代码块标记）：
{{"correctness": 分数, "completeness": 分数, "practicality": 分数, "depth": 分数, "comment": "一句话评语"}}
"""


def load_cases(cases_path: str) -> list[dict[str, Any]]:
    """Load case definitions from YAML."""
    with open(cases_path) as f:
        data = yaml.safe_load(f)
    cases: list[dict[str, Any]] = data.get("cases", [])
    return cases


def load_raw_output(raw_dir: Path, case_id: str, model: str) -> str | None:
    """Load raw model output for a case."""
    filename = f"{case_id}_{model}.txt"
    filepath = raw_dir / filename
    if filepath.exists():
        return filepath.read_text()
    return None


def call_judge(client: OpenAI, model: str, prompt: str, output: str, max_retries: int = 3) -> dict[str, Any]:
    """Call judge model to evaluate output with retry on 429."""
    judge_prompt = JUDGE_PROMPT.format(prompt=prompt, output=output[:8000])

    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": judge_prompt}],
                temperature=0,
                max_tokens=2048,
            )
            content = response.choices[0].message.content
            if not content:
                return {"success": False, "error": "empty response (reasoning starvation)", "scores": {}}
            content = content.strip()

            # Remove markdown code block if present
            if content.startswith("```"):
                content = content.split("\n", 1)[1] if "\n" in content else content[3:]
            if content.endswith("```"):
                content = content[:-3]
            content = content.strip()

            # Try to extract JSON from response
            try:
                scores = json.loads(content)
            except json.JSONDecodeError:
                json_match = re.search(r'\{[^{}]*\}', content, re.DOTALL)
                if json_match:
                    try:
                        scores = json.loads(json_match.group())
                    except json.JSONDecodeError:
                        fixed = json_match.group().replace("'", '"')
                        scores = json.loads(fixed)
                else:
                    return {"success": False, "error": f"no JSON found in: {content[:100]}", "scores": {}}

            return {
                "success": True,
                "scores": scores,
                "usage": {
                    "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
                    "completion_tokens": response.usage.completion_tokens if response.usage else 0,
                },
            }

        except RateLimitError:
            wait = 5 * (attempt + 1)
            print(f"  [429 rate limit, waiting {wait}s, attempt {attempt+1}/{max_retries}]")
            time.sleep(wait)
        except Exception as e:
            return {"success": False, "error": str(e)[:200], "scores": {}}

    return {"success": False, "error": f"max retries ({max_retries}) exceeded", "scores": {}}


def calculate_weighted_score(scores: dict[str, float]) -> float:
    """Calculate weighted overall score from dimension scores."""
    weights = {"correctness": 0.35, "completeness": 0.30, "practicality": 0.20, "depth": 0.15}
    total = 0.0
    for dim, weight in weights.items():
        total += scores.get(dim, 0) * weight
    return total


def _judge_one(
    client: OpenAI,
    judge_model: str,
    case_id: str,
    model: str,
    prompt: str,
    output: str,
    task_type: str,
    complexity: str,
) -> dict[str, Any]:
    """Judge a single case×model pair (called in worker thread)."""
    judge_result = call_judge(client, judge_model, prompt, output)

    if judge_result["success"]:
        scores = judge_result["scores"]
        weighted = calculate_weighted_score(scores)
        normalized = weighted / 5.0
        return {
            "case_id": case_id,
            "model": model,
            "task_type": task_type,
            "complexity": complexity,
            "llm_judge_scores": scores,
            "llm_judge_weighted": weighted,
            "llm_judge_normalized": normalized,
            "comment": scores.get("comment", ""),
            "usage": judge_result.get("usage"),
            "ok": True,
        }
    else:
        return {
            "case_id": case_id,
            "model": model,
            "error": judge_result.get("error", "unknown"),
            "ok": False,
        }


def run_judge(
    cases_path: str,
    raw_dir: str,
    judge_model: str = "MiniMax-M3",
    api_base: str = "https://token.cvte.com/v1",
    api_key: str | None = None,
    output_path: str | None = None,
    resume_from: str | None = None,
    workers: int = 1,
) -> dict[str, Any]:
    """Run LLM judge on all benchmark outputs."""
    api_key = api_key or os.environ.get("CCH_API_KEY", "dummy")
    client = OpenAI(base_url=api_base, api_key=api_key)

    cases = load_cases(cases_path)
    raw_path = Path(raw_dir)
    all_models = ["deepseek-v4-flash", "deepseek-v4-pro", "qwen3.7-plus", "glm-5.1", "qwen3.7-max"]

    # Load existing results for resume
    existing_results: dict[str, dict] = {}
    if resume_from and os.path.exists(resume_from):
        with open(resume_from) as f:
            prev_data = json.load(f)
        for r in prev_data.get("results", []):
            if "llm_judge_normalized" in r:
                key = f"{r['case_id']}:{r['model']}"
                existing_results[key] = r
        print(f"Resuming: loaded {len(existing_results)} existing results from {resume_from}")

    # Build work items
    work_items = []
    for case in cases:
        case_id = case["id"]
        prompt = case["prompt"]
        task_type = case.get("task_type", "")
        complexity = case.get("complexity", "")
        for model in all_models:
            key = f"{case_id}:{model}"
            if key in existing_results:
                continue
            output = load_raw_output(raw_path, case_id, model)
            if output is None:
                continue
            work_items.append((case_id, model, prompt, output, task_type, complexity))

    skipped = len(existing_results)
    total_work = len(work_items)
    print(f"Starting LLM Judge with model: {judge_model}, workers: {workers}")
    print(f"Total: {len(cases)} cases × {len(all_models)} models = {len(cases) * len(all_models)}")
    print(f"Skipped (already done): {skipped}, To evaluate: {total_work}\n")

    results: list[dict] = list(existing_results.values())
    lock = threading.Lock()
    usage_acc = {"prompt_tokens": 0, "completion_tokens": 0}
    done_count = 0
    fail_count = 0
    start_time = time.time()

    def process_item(item):
        nonlocal done_count, fail_count
        case_id, model, prompt, output, task_type, complexity = item
        r = _judge_one(client, judge_model, case_id, model, prompt, output, task_type, complexity)

        with lock:
            if r["ok"]:
                comment_short = r.get("comment", "")[:40]
                print(f"  ✓ {r['case_id']} × {r['model']}  score={r['llm_judge_normalized']:.2f}  {comment_short}")
                usage = r.pop("usage", None)
                if usage:
                    usage_acc["prompt_tokens"] += usage.get("prompt_tokens", 0)
                    usage_acc["completion_tokens"] += usage.get("completion_tokens", 0)
                results.append(r)
            else:
                print(f"  ✗ {r['case_id']} × {r['model']}  error: {r.get('error', 'unknown')}")
                r.pop("usage", None)
                results.append(r)
                fail_count += 1
            done_count += 1
            remaining = total_work - done_count
            if remaining % 10 == 0:
                print(f"  ── progress: {done_count}/{total_work} done, {remaining} remaining, {fail_count} failed")

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

    summary = build_summary(results, usage_acc, elapsed, judge_model)

    output_data = {
        "judge_model": judge_model,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "total_cases": len(cases),
        "total_outputs": len(results),
        "usage": usage_acc,
        "elapsed_seconds": elapsed,
        "workers": workers,
        "summary": summary,
        "results": results,
    }

    if output_path:
        with open(output_path, "w") as f:
            json.dump(output_data, f, ensure_ascii=False, indent=2)
        print(f"Results saved to: {output_path}")

    print_summary(summary)
    return output_data


def build_summary(
    results: list[dict], usage: dict, elapsed: float, judge_model: str
) -> dict[str, Any]:
    """Build summary statistics from judge results."""
    successful = [r for r in results if "llm_judge_normalized" in r]

    if not successful:
        return {"error": "no successful evaluations"}

    by_model = {}
    for model in ["deepseek-v4-flash", "deepseek-v4-pro", "qwen3.7-plus", "glm-5.1", "qwen3.7-max"]:
        model_results = [r for r in successful if r["model"] == model]
        if model_results:
            scores = [r["llm_judge_normalized"] for r in model_results]
            by_model[model] = {
                "avg_score": sum(scores) / len(scores),
                "min_score": min(scores),
                "max_score": max(scores),
                "count": len(scores),
            }

    by_task_type: dict[str, dict[str, list]] = {}
    for r in successful:
        task_type = r.get("task_type", "unknown")
        model = r["model"]
        by_task_type.setdefault(task_type, {}).setdefault(model, []).append(r["llm_judge_normalized"])

    for task_type in by_task_type:
        for model in by_task_type[task_type]:
            scores = by_task_type[task_type][model]
            by_task_type[task_type][model] = sum(scores) / len(scores)

    # Estimate cost based on judge model pricing
    cost_map = {
        "MiniMax-M3": (0.00216, 0.00864),
        "qwen3.7-max": (0.018, 0.054),
        "deepseek-v4-pro": (0.003132, 0.006264),
        "deepseek-v4-flash": (0.001008, 0.002016),
        "qwen3.7-plus": (0.001944, 0.00864),
        "glm-5.1": (0.01008, 0.0288),
    }
    input_price, output_price = cost_map.get(judge_model, (0.01, 0.05))
    estimated_cost_cny = (usage["prompt_tokens"] / 1000 * input_price +
                          usage["completion_tokens"] / 1000 * output_price)

    return {
        "judge_model": judge_model,
        "total_evaluations": len(successful),
        "elapsed_seconds": elapsed,
        "usage": usage,
        "estimated_cost_cny": estimated_cost_cny,
        "by_model": by_model,
        "by_task_type": by_task_type,
    }


def print_summary(summary: dict[str, Any]) -> None:
    """Print summary to console."""
    print("\n" + "=" * 60)
    print("LLM JUDGE SUMMARY")
    print("=" * 60)

    if "error" in summary:
        print(f"Error: {summary['error']}")
        return

    print(f"Judge Model: {summary['judge_model']}")
    print(f"Total Evaluations: {summary['total_evaluations']}")
    print(f"Elapsed: {summary['elapsed_seconds']:.1f}s")
    print(f"Tokens: {summary['usage']['prompt_tokens']} in / {summary['usage']['completion_tokens']} out")
    print(f"Estimated Cost: ¥{summary['estimated_cost_cny']:.2f}")

    print("\n── By Model ──")
    by_model = summary.get("by_model", {})
    sorted_models = sorted(by_model.items(), key=lambda x: x[1]["avg_score"], reverse=True)
    for model, stats in sorted_models:
        print(f"  {model:20s}  avg={stats['avg_score']:.3f}  min={stats['min_score']:.3f}  max={stats['max_score']:.3f}")

    print("\n── By Task Type ──")
    by_task_type = summary.get("by_task_type", {})
    for task_type, models in sorted(by_task_type.items()):
        print(f"\n  {task_type}:")
        sorted_models = sorted(models.items(), key=lambda x: x[1], reverse=True)
        for model, score in sorted_models:
            short_name = model.split("/")[-1] if "/" in model else model
            print(f"    {short_name:20s}  {score:.3f}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="LLM Judge for benchmark outputs")
    parser.add_argument("--cases", default="data/benchmarks/level2/router_quality_cases.yaml")
    parser.add_argument("--raw-dir", default="runs/benchmarks/level2/20260608_202410/raw_outputs")
    parser.add_argument("--judge-model", default="MiniMax-M3")
    parser.add_argument("--output", default="runs/benchmarks/level2/20260608_202410/llm_judge_results.json")
    parser.add_argument("--api-base", default="https://token.cvte.com/v1")
    parser.add_argument("--resume", help="Resume from existing results file (skip already scored)")
    parser.add_argument("--workers", type=int, default=5, help="Number of parallel workers (default: 5)")

    args = parser.parse_args()

    run_judge(
        cases_path=args.cases,
        raw_dir=args.raw_dir,
        judge_model=args.judge_model,
        api_base=args.api_base,
        output_path=args.output,
        resume_from=args.resume,
        workers=args.workers,
    )
