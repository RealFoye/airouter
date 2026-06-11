"""校准报告脚本：对比 rules/ml_raw/ml_final/hybrid 四种模式在标准测试集上的表现。

需要：
- pip install airouter[ml]
- AIROUTER_OPENSQUILLA_BUNDLE_DIR 环境变量指向真实 bundle

用法：
    python scripts/calibration_report.py                    # rules-only baseline
    python scripts/calibration_report.py --with-ml          # 包含 ML 模式
    python scripts/calibration_report.py --output report.json  # 输出 JSON
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from airouter.config import load_models
from airouter.engine.complexity.types import COMPLEXITY_ORDER, ROUTE_TO_COMPLEXITY
from airouter.engine.router.analyzer import TaskAnalyzer
from airouter.models.enums import ComplexityLevel

# ── 数据加载 ──────────────────────────────────────────────────

BENCHMARK_DIR = PROJECT_ROOT / "data" / "benchmarks"

# 高风险等级集合（HIGH + CRITICAL）
HIGH_RISK_LEVELS = frozenset({"HIGH", "CRITICAL"})


def load_cases() -> list[dict]:
    """加载 L1 (40) + Engineering (30) = 70 条校准用例。"""
    cases: list[dict] = []

    # Level 1
    l1_path = BENCHMARK_DIR / "level1" / "router_cases.yaml"
    if l1_path.exists():
        l1 = yaml.safe_load(l1_path.read_text(encoding="utf-8"))
        for c in l1.get("cases", []):
            cases.append({
                "id": c["id"],
                "source": "L1",
                "prompt": c["prompt"],
                "input_context": "",
                "expected_complexity": c["expected_complexity"],
                "risk_level": c.get("expected_risk", "LOW"),
            })

    # Engineering
    eng_path = BENCHMARK_DIR / "engineering" / "engineering_cases.yaml"
    if eng_path.exists():
        eng = yaml.safe_load(eng_path.read_text(encoding="utf-8"))
        for c in eng.get("cases", []):
            cases.append({
                "id": c["id"],
                "source": "ENG",
                "prompt": c["prompt"],
                "input_context": c.get("input_context", ""),
                "expected_complexity": c["complexity"],
                "risk_level": c.get("risk_level", "LOW"),
            })

    return cases


# ── 复杂度 → Tier 映射（用于成本估算） ────────────────────────

TIER_BY_COMPLEXITY = {
    ComplexityLevel.SIMPLE: 3,
    ComplexityLevel.MODERATE: 2,
    ComplexityLevel.COMPLEX: 2,
    ComplexityLevel.EXPERT: 1,
}


def compute_tier_prices() -> tuple[dict[int, float], str]:
    """从 models.yaml 动态计算各 Tier 平均输出价格（CNY/1k tokens）。

    返回 ({tier: avg_output_price_per_1k}, source_label)。
    如果加载失败，回退到保守默认值并标注为 "fallback_defaults"。
    """
    try:
        models_config = load_models()
        tier_prices: dict[int, list[float]] = defaultdict(list)
        for m in models_config.models:
            tier_prices[m.tier].append(m.output_price_per_1k)
        result = {
            tier: sum(prices) / len(prices)
            for tier, prices in tier_prices.items()
            if prices
        }
        return result, "models.yaml"
    except Exception:
        return {1: 0.10, 2: 0.03, 3: 0.005}, "fallback_defaults"


# ── 指标计算 ──────────────────────────────────────────────────


def compute_metrics(
    predictions: list[tuple[str, ComplexityLevel, ComplexityLevel, str]],
    tier_prices: dict[int, float] | None = None,
    cost_source: str = "unknown",
) -> dict:
    """计算校准指标。

    predictions: [(case_id, expected, predicted, risk_level), ...]
    tier_prices: {tier: avg_output_price_per_1k}，来自 models.yaml。
    cost_source: 价格来源标签（"models.yaml" 或 "fallback_defaults"）。
    """
    total = len(predictions)
    if total == 0:
        return {"error": "no predictions"}

    if tier_prices is None:
        tier_prices, cost_source = compute_tier_prices()

    correct = 0
    under_routing = 0
    severe_under_routing = 0
    over_routing = 0
    high_risk_under = 0
    high_risk_total = 0
    tier1_count = 0
    total_cost = 0.0
    confusion: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    for case_id, expected, predicted, risk_level in predictions:
        e_order = COMPLEXITY_ORDER[expected]
        p_order = COMPLEXITY_ORDER[predicted]

        confusion[expected.value][predicted.value] += 1

        if p_order == e_order:
            correct += 1
        elif p_order < e_order:
            under_routing += 1
            if e_order - p_order >= 2:
                severe_under_routing += 1
            if risk_level in HIGH_RISK_LEVELS:
                high_risk_under += 1
        else:
            over_routing += 1

        if risk_level in HIGH_RISK_LEVELS:
            high_risk_total += 1

        # Tier 和成本
        tier = TIER_BY_COMPLEXITY[predicted]
        if tier == 1:
            tier1_count += 1
        # 假设平均 2000 output tokens
        price_per_1k = tier_prices.get(tier, 0.0)
        total_cost += price_per_1k * 2.0

    accuracy = correct / total
    return {
        "total": total,
        "accuracy": round(accuracy, 4),
        "accuracy_pct": f"{accuracy * 100:.1f}%",
        "under_routing": under_routing,
        "under_routing_pct": f"{under_routing / total * 100:.1f}%",
        "severe_under_routing": severe_under_routing,
        "severe_under_routing_pct": f"{severe_under_routing / total * 100:.1f}%",
        "over_routing": over_routing,
        "over_routing_pct": f"{over_routing / total * 100:.1f}%",
        "high_risk_under_routing": high_risk_under,
        "high_risk_total": high_risk_total,
        "high_risk_under_pct": f"{high_risk_under / max(1, high_risk_total) * 100:.1f}%",
        "tier1_rate": f"{tier1_count / total * 100:.1f}%",
        "tier1_count": tier1_count,
        "estimated_cost_cny": round(total_cost, 4),
        "cost_source": cost_source,
        "confusion_matrix": {k: dict(v) for k, v in confusion.items()},
    }


# ── 规则基线 ──────────────────────────────────────────────────


def run_rules_mode(
    cases: list[dict], rule_analyzer: TaskAnalyzer,
) -> list[tuple[str, ComplexityLevel, ComplexityLevel, str]]:
    """纯规则模式：返回 [(id, expected, predicted, risk), ...]"""
    results = []
    for c in cases:
        text = c["prompt"]
        if c.get("input_context"):
            text = c["prompt"] + "\n" + c["input_context"]
        features = rule_analyzer.extract_features(text)
        expected = ComplexityLevel(c["expected_complexity"])
        results.append((c["id"], expected, features.complexity, c["risk_level"]))
    return results


# ── ML 模式 ───────────────────────────────────────────────────


def run_ml_modes(
    cases: list[dict],
    rule_analyzer: TaskAnalyzer,
    ml_backend,
    hybrid_max_upgrade_steps: int = 1,
    hybrid_confidence_threshold: float = 0.50,
) -> tuple[
    list[tuple[str, ComplexityLevel, ComplexityLevel, str]],
    list[tuple[str, ComplexityLevel, ComplexityLevel, str]],
    list[tuple[str, ComplexityLevel, ComplexityLevel, str]],
    int,
    list[str],
]:
    """运行 ml_raw, ml_final, hybrid 三种模式。

    返回 (raw_preds, final_preds, hybrid_preds, ml_success_count, failure_ids)。
    ML predict 失败时，该用例降级到规则结果，并计入 failure_ids。
    """
    raw_preds = []
    final_preds = []
    hybrid_preds = []
    ml_success_count = 0
    failure_ids: list[str] = []

    for c in cases:
        text = c["prompt"]
        if c.get("input_context"):
            text = c["prompt"] + "\n" + c["input_context"]

        expected = ComplexityLevel(c["expected_complexity"])
        rule_features = rule_analyzer.extract_features(text)
        rule_complexity = rule_features.complexity

        try:
            ml_pred = ml_backend.predict(text)
        except Exception:
            # ML 失败 → 所有 ML 模式降级到规则，记录失败
            failure_ids.append(c["id"])
            raw_preds.append((c["id"], expected, rule_complexity, c["risk_level"]))
            final_preds.append((c["id"], expected, rule_complexity, c["risk_level"]))
            hybrid_preds.append((c["id"], expected, rule_complexity, c["risk_level"]))
            continue

        ml_success_count += 1

        # ml_raw: argmax class → complexity
        raw_complexity = ROUTE_TO_COMPLEXITY.get(
            ml_pred.raw_route_class, ComplexityLevel.MODERATE
        )
        raw_preds.append((c["id"], expected, raw_complexity, c["risk_level"]))

        # ml_final: postprocess class → complexity
        final_complexity = ROUTE_TO_COMPLEXITY.get(
            ml_pred.final_route_class, ComplexityLevel.MODERATE
        )
        final_preds.append((c["id"], expected, final_complexity, c["risk_level"]))

        # hybrid: 只升不降，使用 raw class
        rule_order = COMPLEXITY_ORDER[rule_complexity]
        raw_order = COMPLEXITY_ORDER[raw_complexity]

        if (
            ml_pred.raw_confidence >= hybrid_confidence_threshold
            and raw_order > rule_order
        ):
            actual_steps = min(raw_order - rule_order, hybrid_max_upgrade_steps)
            target_order = rule_order + actual_steps
            resolved = rule_complexity
            for level, order in COMPLEXITY_ORDER.items():
                if order == target_order:
                    resolved = level
                    break
        else:
            resolved = rule_complexity

        hybrid_preds.append((c["id"], expected, resolved, c["risk_level"]))

    return raw_preds, final_preds, hybrid_preds, ml_success_count, failure_ids


# ── 报告输出 ──────────────────────────────────────────────────


def print_report(
    mode_name: str, metrics: dict, baseline_metrics: dict | None = None,
) -> None:
    """打印单个模式的指标报告。"""
    print(f"\n{'='*60}")
    print(f"  Mode: {mode_name}")
    print(f"{'='*60}")
    print(f"  Cases:                    {metrics['total']}")
    print(f"  Accuracy:                 {metrics['accuracy_pct']}")
    print(f"  Under-routing:            {metrics['under_routing']} ({metrics['under_routing_pct']})")
    print(f"  Severe under-routing:     {metrics['severe_under_routing']} ({metrics['severe_under_routing_pct']})")
    print(f"  Over-routing:             {metrics['over_routing']} ({metrics['over_routing_pct']})")
    print(f"  High-risk under-routing:  {metrics['high_risk_under_routing']}/{metrics['high_risk_total']} ({metrics['high_risk_under_pct']})")
    print(f"  Tier 1 rate:              {metrics['tier1_rate']} ({metrics['tier1_count']} cases)")
    print(f"  Estimated cost:           ¥{metrics['estimated_cost_cny']}")

    if baseline_metrics:
        delta_acc = metrics["accuracy"] - baseline_metrics["accuracy"]
        delta_cost = metrics["estimated_cost_cny"] - baseline_metrics["estimated_cost_cny"]
        print(f"\n  vs rules baseline:")
        print(f"    Accuracy delta:         {delta_acc:+.1%}")
        print(f"    Cost delta:             ¥{delta_cost:+.4f}")

    # Confusion matrix
    print(f"\n  Confusion Matrix (rows=expected, cols=predicted):")
    levels = ["SIMPLE", "MODERATE", "COMPLEX", "EXPERT"]
    header = "           " + "  ".join(f"{l:>8}" for l in levels)
    print(f"  {header}")
    cm = metrics.get("confusion_matrix", {})
    for row in levels:
        row_data = cm.get(row, {})
        cells = "  ".join(f"{row_data.get(col, 0):>8}" for col in levels)
        print(f"  {row:>10} {cells}")


def check_acceptance(
    rules_metrics: dict,
    hybrid_metrics: dict,
    ml_success_count: int,
    total_cases: int,
) -> list[str]:
    """检查验收标准，返回失败项列表。"""
    failures = []

    # 1. ML 成功率
    if ml_success_count < total_cases:
        failures.append(
            f"ML success rate: {ml_success_count}/{total_cases} (expected {total_cases}/{total_cases})"
        )

    # 2. hybrid severe under-routing <= rules
    if hybrid_metrics["severe_under_routing"] > rules_metrics["severe_under_routing"]:
        failures.append(
            f"hybrid severe under-routing ({hybrid_metrics['severe_under_routing']}) "
            f"> rules ({rules_metrics['severe_under_routing']})"
        )

    # 3. hybrid high-risk under-routing <= rules
    if hybrid_metrics["high_risk_under_routing"] > rules_metrics["high_risk_under_routing"]:
        failures.append(
            f"hybrid high-risk under-routing ({hybrid_metrics['high_risk_under_routing']}) "
            f"> rules ({rules_metrics['high_risk_under_routing']})"
        )

    # 4. hybrid accuracy >= rules accuracy - 5pp
    delta = hybrid_metrics["accuracy"] - rules_metrics["accuracy"]
    if delta < -0.05:
        failures.append(
            f"hybrid accuracy ({hybrid_metrics['accuracy_pct']}) "
            f"< rules ({rules_metrics['accuracy_pct']}) - 5pp"
        )

    return failures


# ── 主入口 ────────────────────────────────────────────────────


def main() -> bool:
    parser = argparse.ArgumentParser(description="AirRouter 校准报告")
    parser.add_argument(
        "--with-ml", action="store_true",
        help="启用 ML 模式（需要 AIROUTER_OPENSQUILLA_BUNDLE_DIR）",
    )
    parser.add_argument(
        "--output", type=str, default=None,
        help="输出 JSON 文件路径",
    )
    parser.add_argument(
        "--max-upgrade-steps", type=int, default=1,
        help="hybrid 最大升级步数（默认 1）",
    )
    parser.add_argument(
        "--confidence-threshold", type=float, default=0.50,
        help="hybrid 置信度阈值（默认 0.50）",
    )
    args = parser.parse_args()

    # 加载用例
    cases = load_cases()
    if not cases:
        print("ERROR: No calibration cases found.")
        print(f"Expected files in: {BENCHMARK_DIR}")
        sys.exit(1)

    print(f"Loaded {len(cases)} calibration cases")
    sources = defaultdict(int)
    for c in cases:
        sources[c["source"]] += 1
    for src, count in sources.items():
        print(f"  {src}: {count} cases")

    # 规则分析器
    rule_analyzer = TaskAnalyzer()

    # ── Rules 基线 ────────────────────────────────────────────
    print("\nRunning rules baseline...")
    tier_prices, cost_source = compute_tier_prices()
    t0 = time.perf_counter()
    rules_preds = run_rules_mode(cases, rule_analyzer)
    rules_time = (time.perf_counter() - t0) * 1000
    rules_metrics = compute_metrics(rules_preds, tier_prices, cost_source)
    print_report("rules (baseline)", rules_metrics)
    print(f"  Latency: {rules_time:.1f}ms total")
    print(f"  Cost source: {cost_source} (tier prices: {tier_prices})")

    all_results = {
        "rules": rules_metrics,
    }

    # ── ML 模式 ───────────────────────────────────────────────
    acceptance_passed = True
    if args.with_ml:
        bundle_dir = os.environ.get("AIROUTER_OPENSQUILLA_BUNDLE_DIR", "")
        if not bundle_dir:
            print("\nERROR: --with-ml requires AIROUTER_OPENSQUILLA_BUNDLE_DIR")
            sys.exit(1)

        print(f"\nInitializing ML backend: {bundle_dir}")
        try:
            from airouter.engine.complexity.ml_backend import get_backend
            ml_backend = get_backend(Path(bundle_dir))
            print(f"ML backend ready (cold start: {ml_backend._cold_start_ms:.0f}ms)")
        except Exception as exc:
            print(f"ERROR: ML backend init failed: {exc}")
            sys.exit(1)

        # 运行 ML 模式
        print("Running ML modes...")
        t0 = time.perf_counter()
        raw_preds, final_preds, hybrid_preds, ml_success_count, failure_ids = run_ml_modes(
            cases, rule_analyzer, ml_backend,
            hybrid_max_upgrade_steps=args.max_upgrade_steps,
            hybrid_confidence_threshold=args.confidence_threshold,
        )
        ml_time = (time.perf_counter() - t0) * 1000

        print(f"ML success: {ml_success_count}/{len(cases)}")
        if failure_ids:
            print(f"ML failures ({len(failure_ids)}): {', '.join(failure_ids[:10])}")
            if len(failure_ids) > 10:
                print(f"  ... and {len(failure_ids) - 10} more")

        tier_prices, cost_source = compute_tier_prices()
        raw_metrics = compute_metrics(raw_preds, tier_prices, cost_source)
        final_metrics = compute_metrics(final_preds, tier_prices, cost_source)
        hybrid_metrics = compute_metrics(hybrid_preds, tier_prices, cost_source)

        print_report("ml_raw (OpenSquilla argmax)", raw_metrics, rules_metrics)
        print_report("ml_final (OpenSquilla postprocess)", final_metrics, rules_metrics)
        print_report(
            f"hybrid (max_steps={args.max_upgrade_steps}, conf>={args.confidence_threshold})",
            hybrid_metrics, rules_metrics,
        )
        print(f"\n  ML total latency: {ml_time:.1f}ms")

        all_results["ml_raw"] = raw_metrics
        all_results["ml_final"] = final_metrics
        all_results["hybrid"] = hybrid_metrics
        all_results["ml_success_count"] = ml_success_count
        all_results["ml_failure_ids"] = failure_ids

        # 验收检查
        print(f"\n{'='*60}")
        print("  Acceptance Criteria Check")
        print(f"{'='*60}")
        failures = check_acceptance(rules_metrics, hybrid_metrics, ml_success_count, len(cases))
        if not failures:
            print("  ALL ACCEPTANCE CRITERIA PASSED")
        else:
            acceptance_passed = False
            print(f"  {len(failures)} CRITERIA FAILED:")
            for f in failures:
                print(f"    - {f}")

        all_results["acceptance"] = {
            "passed": len(failures) == 0,
            "failures": failures,
        }
    else:
        print("\nML modes skipped. Use --with-ml to enable.")

    # ── 输出 ──────────────────────────────────────────────────
    if args.output:
        output_path = Path(args.output)
        output_path.write_text(
            json.dumps(all_results, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\nReport saved to: {output_path}")
    else:
        print(f"\n{'='*60}")
        print("  Summary (rules only)")
        print(f"{'='*60}")
        print(f"  Accuracy:                 {rules_metrics['accuracy_pct']}")
        print(f"  Under-routing:            {rules_metrics['under_routing']} ({rules_metrics['under_routing_pct']})")
        print(f"  Severe under-routing:     {rules_metrics['severe_under_routing']} ({rules_metrics['severe_under_routing_pct']})")
        print(f"  Tier 1 rate:              {rules_metrics['tier1_rate']}")
        if not args.with_ml:
            print("\n  Run with --with-ml for ML comparison.")

    return acceptance_passed


if __name__ == "__main__":
    ok = main()
    sys.exit(0 if ok else 1)
