"""Offline analysis of Finance Judge run results.

Usage:
    python3 scripts/analyze_judge_run.py \\
        --run-dir runs/benchmarks/finance/20260610_084555 \\
        --judge-model MiniMax-M3

    # Explicit judge JSONL:
    python3 scripts/analyze_judge_run.py \\
        --run-dir runs/benchmarks/finance/20260610_084555 \\
        --judge-model MiniMax-M3 \\
        --judge-jsonl finance_judge_minimax_m3.jsonl

Reads existing JSONL files only — does NOT call any API.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

from airouter.engine.benchmark.judge_utils import (
    compute_disagreement,
    spearman_rank_correlation,
)
from airouter.models.model_registry import get_registry


def find_judge_jsonl(run_dir: Path, judge_model: str) -> Path:
    """Locate the judge JSONL for a given model.

    Priority: full file (no suffix) > .targeted > .smoke.
    Raises FileNotFoundError if no match, or if multiple partials
    exist with no full file.
    """
    slug = judge_model.lower().replace("-", "_").replace(".", "_")
    candidates = list(run_dir.glob(f"finance_judge_{slug}*.jsonl"))
    if not candidates:
        candidates = list(run_dir.glob(f"finance_judge_{judge_model}*.jsonl"))
    if not candidates:
        raise FileNotFoundError(
            f"No judge JSONL found in {run_dir} for model {judge_model}"
        )

    # Prefer the full file (no suffix)
    for c in candidates:
        if c.stem == f"finance_judge_{slug}":
            return c

    # No full file — check if multiple partials exist
    partials = [c for c in candidates if c.suffix == ".jsonl"]
    if len(partials) > 1:
        names = ", ".join(c.name for c in partials)
        raise FileNotFoundError(
            f"Multiple partial judge JSONL files found in {run_dir}: {names}. "
            "Use --judge-jsonl to specify which one."
        )
    return candidates[0]


def load_rule_scores(rule_jsonl: Path) -> dict[tuple[str, str], float]:
    """Load (case_id, model) -> overall_score from rule results JSONL."""
    scores: dict[tuple[str, str], float] = {}
    with open(rule_jsonl) as f:
        for line in f:
            d = json.loads(line)
            scores[(d["case_id"], d["model"])] = d.get("overall_score", 0)
    return scores


def load_judge_data(
    judge_jsonl: Path, judge_model: str
) -> tuple[dict[tuple[str, str], dict], int, int, int]:
    """Load judge JSONL, filtering by judge_model.

    Returns (data, physical_lines, matching_lines, duplicate_lines).
    - physical_lines: total lines in file
    - matching_lines: lines with matching judge_model (including duplicates)
    - duplicate_lines: extra lines for same (case_id, model) among matching lines
    """
    data: dict[tuple[str, str], dict] = {}
    physical_lines = 0
    matching_lines = 0
    with open(judge_jsonl) as f:
        for line in f:
            physical_lines += 1
            d = json.loads(line)
            if d.get("judge_model", "") != judge_model:
                continue
            matching_lines += 1
            data[(d["case_id"], d["model"])] = d
    duplicate_lines = matching_lines - len(data)
    return data, physical_lines, matching_lines, duplicate_lines


def get_rule_score(
    key: tuple[str, str],
    rescored: dict[tuple[str, str], float],
    embedded: float,
    warnings: list[str],
) -> float:
    """Get rule score: prefer rescored, fall back to embedded with warning."""
    if key in rescored:
        return rescored[key]
    warnings.append(
        f"  WARNING: ({key[0]}, {key[1]}) not in rescored results, "
        f"using embedded rule_score={embedded:.3f}"
    )
    return embedded


def check_report_has_judge_appendix(report_path: Path) -> bool:
    """Check if the report file contains the exact Judge appendix heading."""
    if not report_path.exists():
        return False
    text = report_path.read_text(encoding="utf-8")
    return "## 附录 A：LLM Judge 辅助审计" in text


def run_analysis(
    run_dir: Path,
    judge_model: str,
    judge_jsonl_name: str | None = None,
) -> str:
    """Run the full analysis and return the output as a string."""
    lines: list[str] = []

    def out(s: str = "") -> None:
        lines.append(s)

    # Locate files
    if judge_jsonl_name:
        judge_jsonl = run_dir / judge_jsonl_name
        if not judge_jsonl.exists():
            raise FileNotFoundError(f"Judge JSONL not found: {judge_jsonl}")
    else:
        judge_jsonl = find_judge_jsonl(run_dir, judge_model)

    rule_jsonl = run_dir / "results.rescored.jsonl"
    if not rule_jsonl.exists():
        rule_jsonl = run_dir / "results.jsonl"
    if not rule_jsonl.exists():
        raise FileNotFoundError(f"No rule results found in {run_dir}")

    # Load rescored rule scores
    rescored_scores = load_rule_scores(rule_jsonl)

    # Load pricing from ModelRegistry
    registry = get_registry()
    entry = registry.get_by_name(judge_model)
    if entry is None:
        input_price = 0.0
        output_price = 0.0
        price_note = "model not in models.yaml, cost=0"
    else:
        input_price = entry.input_price_per_1k
        output_price = entry.output_price_per_1k
        price_note = "from models.yaml (pending CCH CSV calibration)"

    # Load judge data (filtered by judge_model)
    judge_data, physical_lines, matching_lines, duplicate_lines = load_judge_data(
        judge_jsonl, judge_model
    )

    pairs = len(judge_data)
    success = sum(
        1 for d in judge_data.values() if d.get("weighted_score", 0) > 0
    )
    failed = pairs - success

    out("=== Finance Judge Run Analysis ===")
    out(f"Judge model: {judge_model}")
    out(f"Run dir: {run_dir}")
    out(f"Judge JSONL: {judge_jsonl.name}")
    out(f"Rule JSONL: {rule_jsonl.name} ({len(rescored_scores)} pairs loaded)")
    out()

    # 1. Success/failure
    out(f"1. Success/Failure: {success}/{pairs} ({failed} failed)")
    out(f"   Physical JSONL lines: {physical_lines}")
    out(f"   Matching judge_model lines: {matching_lines}")
    out(f"   Duplicate (case_id, model) lines: {duplicate_lines}")
    out("   Note: duplicate_lines counts JSONL-level duplicates only;")
    out("   internal API retries within a single call are not visible here.")
    out()

    # 2. Token usage & cost
    total_prompt = sum(
        d.get("usage", {}).get("prompt_tokens", 0) for d in judge_data.values()
    )
    total_completion = sum(
        d.get("usage", {}).get("completion_tokens", 0) for d in judge_data.values()
    )
    total_tokens = total_prompt + total_completion
    est_cost = (
        (total_prompt / 1000 * input_price)
        + (total_completion / 1000 * output_price)
    )
    out(f"2. Total tokens: {total_tokens:,} (prompt: {total_prompt:,}, completion: {total_completion:,})")
    out(f"   Pricing: input={input_price}, output={output_price} CNY/1K ({price_note})")
    out(f"   Estimated cost: {est_cost:.4f} CNY")
    out("   Note: cost is based on final JSONL response tokens only.")
    out("   Internal retries are not counted; actual cost per CCH CSV may be higher.")
    out()

    # 3. Deterministic disagreement analysis using rescored scores
    warnings: list[str] = []
    disagg_counts: dict[str, int] = defaultdict(int)
    for key, d in judge_data.items():
        if d.get("weighted_score", 0) <= 0:
            continue
        rule_s = get_rule_score(
            key, rescored_scores, d.get("rule_score", 0), warnings
        )
        judge_s = d["normalized_score"]
        label = compute_disagreement(rule_s, judge_s)
        disagg_counts[label] += 1

    total_classified = sum(disagg_counts.values())
    out("3. Rule vs Judge disagreement (deterministic thresholds, rescored scores):")
    out(f"   agree        (|delta|<=0.15):            {disagg_counts['agree']}")
    out(f"   rule_too_high (rule>=0.8, judge<0.6):   {disagg_counts['rule_too_high']}")
    out(f"   rule_too_low  (rule<0.6,  judge>=0.8):   {disagg_counts['rule_too_low']}")
    out(f"   unclear      (delta>0.15, no threshold): {disagg_counts['unclear']}")
    out(f"   Total classified: {total_classified}")
    if total_classified != success:
        out(f"   WARNING: total ({total_classified}) != success ({success})")
    out()

    # Print warnings for fallback rule scores
    if warnings:
        out("   Rule score fallback warnings:")
        for w in warnings[:10]:
            out(w)
        if len(warnings) > 10:
            out(f"   ... and {len(warnings) - 10} more")
        out()

    # 4. Per-model scores (using rescored rule scores)
    model_rule: dict[str, list[float]] = defaultdict(list)
    model_judge: dict[str, list[float]] = defaultdict(list)
    model_agree: dict[str, int] = defaultdict(int)
    for key, d in judge_data.items():
        if d.get("weighted_score", 0) <= 0:
            continue
        rule_s = get_rule_score(
            key, rescored_scores, d.get("rule_score", 0), []
        )
        judge_s = d["normalized_score"]
        model = key[1]
        model_judge[model].append(judge_s)
        model_rule[model].append(rule_s)
        if compute_disagreement(rule_s, judge_s) == "agree":
            model_agree[model] += 1

    out("4. Per-model scores (avg):")
    out(f"   {'Model':<20} {'Rule':>8} {'Judge':>8} {'Delta':>8} {'Agree%':>8}")
    out(f"   {'-' * 52}")

    model_avg_rule: dict[str, float] = {}
    model_avg_judge: dict[str, float] = {}
    for model in sorted(model_judge.keys()):
        avg_r = sum(model_rule[model]) / len(model_rule[model])
        avg_j = sum(model_judge[model]) / len(model_judge[model])
        model_avg_rule[model] = avg_r
        model_avg_judge[model] = avg_j
        delta = avg_j - avg_r
        agree_pct = model_agree[model] / len(model_judge[model])
        out(f"   {model:<20} {avg_r:>8.3f} {avg_j:>8.3f} {delta:>+8.3f} {agree_pct:>7.0%}")

    out()

    # 5. Ranking comparison + Spearman
    rule_ranking = sorted(
        model_avg_rule.keys(), key=lambda m: model_avg_rule[m], reverse=True
    )
    judge_ranking = sorted(
        model_avg_judge.keys(), key=lambda m: model_avg_judge[m], reverse=True
    )

    out("5. Model ranking comparison:")
    out(f"   {'Rank':>4} {'Rule ranking':<20} {'Judge ranking':<20} {'Changed?'}")
    out(f"   {'-' * 60}")
    for i in range(max(len(rule_ranking), len(judge_ranking))):
        r = rule_ranking[i] if i < len(rule_ranking) else "-"
        j = judge_ranking[i] if i < len(judge_ranking) else "-"
        changed = "YES" if r != j else ""
        out(f"   {i + 1:>4} {r:<20} {j:<20} {changed}")

    if rule_ranking == judge_ranking:
        out("   -> Rankings IDENTICAL")
    else:
        out("   -> Rankings DIFFER")

    models_sorted = sorted(model_avg_rule.keys())
    rule_vals = [model_avg_rule[m] for m in models_sorted]
    judge_vals = [model_avg_judge[m] for m in models_sorted]
    rho_model = spearman_rank_correlation(rule_vals, judge_vals)
    out(f"   Spearman rho (model-level, n={len(models_sorted)}): {rho_model:.3f}")

    all_rule: list[float] = []
    all_judge: list[float] = []
    for key, d in judge_data.items():
        if d.get("weighted_score", 0) > 0:
            rule_s = get_rule_score(
                key, rescored_scores, d.get("rule_score", 0), []
            )
            all_rule.append(rule_s)
            all_judge.append(d["normalized_score"])
    rho_pair = spearman_rank_correlation(all_rule, all_judge)
    out(f"   Spearman rho (pair-level, n={len(all_rule)}): {rho_pair:.3f}")
    out()
    out("   Interpretation:")
    out(f"   - Model-level rho={rho_model:.3f}: both scorers largely agree on relative model quality.")
    out(f"   - Pair-level rho={rho_pair:.3f}: rule and judge diverge significantly on individual cases.")
    out("     This does NOT indicate either scorer is wrong — it means individual cases")
    out("     need human review to determine accuracy.")
    out()

    # 6. Top 10 cases for human review
    disagreements: list[tuple] = []
    for key, d in judge_data.items():
        if d.get("weighted_score", 0) <= 0:
            continue
        rule_s = get_rule_score(
            key, rescored_scores, d.get("rule_score", 0), []
        )
        judge_s = d["normalized_score"]
        diff = judge_s - rule_s
        label = compute_disagreement(rule_s, judge_s)
        disagreements.append((
            abs(diff), diff, key[0], key[1], rule_s, judge_s,
            label, d.get("red_flags", []),
        ))

    disagreements.sort(reverse=True)

    out("6. Top 10 cases for human review (largest |rule - judge| delta):")
    out(f"   {'Case':>12} {'Model':<18} {'Rule':>6} {'Judge':>6} {'Delta':>7} {'Label':<14} {'Red flags'}")
    out(f"   {'-' * 90}")
    for abs_d, diff, cid, mdl, rs, js, lbl, flags in disagreements[:10]:
        flags_str = ", ".join(flags) if flags else "-"
        out(f"   {cid:>12} {mdl:<18} {rs:>6.2f} {js:>6.2f} {diff:>+7.2f} {lbl:<14} {flags_str}")

    out()

    # 7. Red flags summary
    all_flags: dict[str, int] = defaultdict(int)
    for d in judge_data.values():
        for flag in d.get("red_flags", []):
            all_flags[flag] += 1

    out("7. Red flags summary:")
    if all_flags:
        for flag, count in sorted(all_flags.items(), key=lambda x: -x[1]):
            out(f"   {flag}: {count}")
    else:
        out("   No red flags detected")
    out()

    # 8. Report path
    report_path = run_dir / "finance_report.md"
    out(f"8. Report path: {report_path}")
    if report_path.exists():
        has_appendix = check_report_has_judge_appendix(report_path)
        if has_appendix:
            out("   Report includes Judge appendix.")
        else:
            out("   WARNING: Report exists but does NOT contain Judge appendix.")
    else:
        out("   Report not yet generated.")
    out()

    # 9. CCH reconciliation
    provider = entry.provider if entry else "unknown"
    out("9. CCH reconciliation:")
    out(f"   Judge model: {judge_model} (provider: {provider})")
    out(f"   Run dir: {run_dir}")
    out(f"   Estimated cost from models.yaml: {est_cost:.4f} CNY")
    out("   Note: models.yaml prices are estimates; use CCH backend usage CSV for reconciliation.")
    out()

    # 10. Caveats
    out("10. Caveats:")
    out(f"    - {judge_model} saw rule scores during judging (non-blind). Auxiliary audit only.")
    out("    - Full blind judge evaluation not yet implemented.")
    out("    - Rule scoring remains the authoritative ranking source.")

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze Finance Judge run results")
    parser.add_argument(
        "--run-dir",
        required=True,
        type=Path,
        help="Path to the benchmark run directory",
    )
    parser.add_argument(
        "--judge-model",
        required=True,
        help="Judge model name (e.g. MiniMax-M3)",
    )
    parser.add_argument(
        "--judge-jsonl",
        default=None,
        help="Explicit judge JSONL filename (overrides auto-detection)",
    )
    args = parser.parse_args()

    try:
        output = run_analysis(
            run_dir=args.run_dir,
            judge_model=args.judge_model,
            judge_jsonl_name=args.judge_jsonl,
        )
        print(output)
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
