"""Web 工作台的只读数据访问层。"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from airouter.config import load_all
from airouter.engine.audit.attribution import Attribution
from airouter.engine.audit.collector import Collector
from airouter.engine.benchmark.ground_truth_schemas import CANDIDATE_MODELS
from airouter.models.database import init_db

PROJECT_ROOT = Path(__file__).resolve().parents[3]
RUNS_ROOT = PROJECT_ROOT / "runs" / "benchmarks"


@dataclass(frozen=True)
class RunProgress:
    run_id: str
    path: Path
    completed: int
    expected: int
    succeeded: int
    failed: int
    cost_cny: float
    updated_at: datetime
    status: str

    @property
    def progress(self) -> float:
        if self.expected <= 0:
            return 0.0
        return min(1.0, self.completed / self.expected)


def read_json(path: Path) -> dict[str, Any]:
    """读取 JSON；文件不存在或写入未完成时返回空字典。"""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    """容忍正在追加的最后一行，安全读取 JSONL。"""
    rows: list[dict[str, Any]] = []
    try:
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(item, dict):
                    rows.append(item)
    except OSError:
        return []
    return rows


def _latest_dir(root: Path, required_file: str) -> Path | None:
    candidates = [
        path.parent
        for path in root.glob(f"*/{required_file}")
        if path.is_file()
    ]
    return max(candidates, key=lambda path: path.stat().st_mtime) if candidates else None


def latest_finance_run() -> Path | None:
    return _latest_dir(RUNS_ROOT / "finance", "results.rescored.jsonl")


def latest_routing_run() -> Path | None:
    return _latest_dir(RUNS_ROOT / "routing_ground_truth", "summary.json")


def finance_model_summary(run_dir: Path | None = None) -> list[dict[str, Any]]:
    run_dir = run_dir or latest_finance_run()
    if run_dir is None:
        return []
    source = run_dir / "results.rescored.jsonl"
    if not source.exists():
        source = run_dir / "results.jsonl"
    rows = read_jsonl(source)

    deduped: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        key = (str(row.get("case_id", "")), str(row.get("model", "")))
        deduped[key] = row

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in deduped.values():
        if row.get("status") == "success":
            grouped[str(row.get("model", "unknown"))].append(row)

    result = []
    for model, items in grouped.items():
        scores = [float(item.get("overall_score", 0.0) or 0.0) for item in items]
        result.append({
            "模型": model,
            "样本": len(items),
            "综合分": round(sum(scores) / len(scores), 3) if scores else 0.0,
            "成本（元）": round(sum(float(item.get("cost_cny", 0.0) or 0.0) for item in items), 4),
            "平均延迟（秒）": round(
                sum(float(item.get("latency_ms", 0.0) or 0.0) for item in items)
                / max(1, len(items))
                / 1000,
                1,
            ),
            "金额准确率": _dimension_average(items, "amount_accuracy"),
            "决策准确率": _dimension_average(items, "decision_accuracy"),
            "发现召回率": _dimension_average(items, "finding_recall"),
        })
    return sorted(result, key=lambda item: (-item["综合分"], item["成本（元）"]))


def _dimension_average(items: list[dict[str, Any]], dimension: str) -> float:
    values = []
    for item in items:
        scores = item.get("dimension_scores", {})
        applicability = item.get("details", {}).get("dimension_applicability", {})
        if applicability.get(dimension, True) and dimension in scores:
            values.append(float(scores[dimension]))
    return round(sum(values) / len(values), 3) if values else 0.0


def finance_category_summary(run_dir: Path | None = None) -> list[dict[str, Any]]:
    run_dir = run_dir or latest_finance_run()
    if run_dir is None:
        return []
    source = run_dir / "results.rescored.jsonl"
    if not source.exists():
        source = run_dir / "results.jsonl"
    grouped: dict[tuple[str, str], list[float]] = defaultdict(list)
    for row in read_jsonl(source):
        if row.get("status") != "success":
            continue
        grouped[(str(row.get("category", "unknown")), str(row.get("model", "unknown")))].append(
            float(row.get("overall_score", 0.0) or 0.0)
        )

    result = []
    for (category, model), scores in grouped.items():
        result.append({
            "类别": category,
            "模型": model,
            "得分": round(sum(scores) / len(scores), 3),
        })
    return sorted(result, key=lambda item: (item["类别"], -item["得分"]))


def routing_strategy_summary(run_dir: Path | None = None) -> list[dict[str, Any]]:
    run_dir = run_dir or latest_routing_run()
    if run_dir is None:
        return []
    summary = read_json(run_dir / "summary.json")
    rows = summary.get("dev_signal_results") or summary.get("signal_strategy_results") or []
    return [
        {
            "策略": row.get("strategy_name", "unknown"),
            "可接受匹配率": round(float(row.get("acceptable_match_rate", 0.0)) * 100, 1),
            "欠路由率": round(float(row.get("under_routing_rate", 0.0)) * 100, 1),
            "严重欠路由率": round(float(row.get("severe_under_routing_rate", 0.0)) * 100, 1),
            "过度路由率": round(float(row.get("over_routing_rate", 0.0)) * 100, 1),
            "安全违规率": round(float(row.get("safety_violation_rate", 0.0)) * 100, 1),
            "代理成本（元）": round(float(row.get("total_estimated_cost_cny", 0.0)), 4),
        }
        for row in rows
    ]


def routing_run_summary(run_dir: Path | None = None) -> dict[str, Any]:
    run_dir = run_dir or latest_routing_run()
    if run_dir is None:
        return {}
    return read_json(run_dir / "summary.json")


def current_routing_progress(search_root: Path = Path("/tmp/smoke_routing")) -> RunProgress | None:
    """读取当前 Routing 全量进度，不锁文件、不写运行目录。"""
    candidates = [path for path in search_root.glob("*/results.jsonl") if path.is_file()]
    if not candidates:
        return None
    source = max(candidates, key=lambda path: path.stat().st_mtime)
    rows = read_jsonl(source)

    deduped: dict[tuple[str, str, int], dict[str, Any]] = {}
    for row in rows:
        key = (
            str(row.get("case_id", "")),
            str(row.get("model", "")),
            int(row.get("run_index", 0) or 0),
        )
        deduped[key] = row

    succeeded = sum(1 for row in deduped.values() if row.get("status") == "success")
    failed = sum(1 for row in deduped.values() if row.get("status") == "failed")
    cost = sum(
        float(row.get("billed_cost_cny") or row.get("estimated_cost_cny") or 0.0)
        for row in deduped.values()
    )
    updated_at = datetime.fromtimestamp(source.stat().st_mtime)
    expected = 90 * len(CANDIDATE_MODELS)
    completed = len(deduped)
    age = datetime.now() - updated_at
    if completed >= expected:
        status = "已完成"
    elif age <= timedelta(minutes=15):
        status = "运行中"
    else:
        status = "等待续跑"
    return RunProgress(
        run_id=source.parent.name,
        path=source.parent,
        completed=completed,
        expected=expected,
        succeeded=succeeded,
        failed=failed,
        cost_cny=round(cost, 4),
        updated_at=updated_at,
        status=status,
    )


def audit_snapshot(days: int = 30, db_path: Path | None = None) -> dict[str, Any]:
    """从 seed.db 生成消费审计快照。"""
    db_path = db_path or PROJECT_ROOT / "seed.db"
    if not db_path.exists():
        return Attribution().analyze([])
    init_db(f"sqlite:///{db_path}")
    end_date = datetime.now()
    records = Collector().collect(end_date - timedelta(days=days), end_date)
    return Attribution().analyze(records, top_n_waste=8)


def model_catalog() -> list[dict[str, Any]]:
    config = load_all()
    return [
        {
            "模型": model.name,
            "Tier": model.tier,
            "Provider": model.provider,
            "输入价（元/1K）": model.input_price_per_1k,
            "输出价（元/1K）": model.output_price_per_1k,
            "上下文窗口": model.max_context_window,
            "缓存": "支持" if model.cache.supports_prompt_caching is True else "未知/不支持",
            "敏感数据": "允许" if model.allow_sensitive_data else "禁止",
        }
        for model in config.models.models
    ]


def governance_config() -> dict[str, Any]:
    config = load_all()
    budget = config.budgets.projects.get("ai-router") or config.budgets.projects["default"]
    return {
        "complexity_mode": config.complexity.mode,
        "bundle_dir": str(config.complexity.bundle_dir or ""),
        "hybrid_threshold": config.complexity.hybrid.confidence_threshold,
        "hybrid_allow_upgrade": config.complexity.hybrid.allow_upgrade,
        "hybrid_allow_downgrade": config.complexity.hybrid.allow_downgrade,
        "monthly_budget": budget.monthly_budget_cny,
        "task_budget": budget.task_budget_default_cny,
        "hard_limit_multiplier": budget.task_budget_hard_limit_multiplier,
        "human_review_tasks": config.routing_rules.human_review_required_tasks,
        "allowed_tiers": {
            name: {
                "default": rule.default,
                "high_risk": rule.high_risk,
            }
            for name, rule in config.routing_rules.allowed_tiers.items()
        },
    }


def benchmark_history() -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for benchmark_type, required in (
        ("Finance", "run_state.json"),
        ("Routing", "summary.json"),
        ("Level 2", "run_state.json"),
    ):
        root_name = {
            "Finance": "finance",
            "Routing": "routing_ground_truth",
            "Level 2": "level2",
        }[benchmark_type]
        for source in (RUNS_ROOT / root_name).glob(f"*/{required}"):
            data = read_json(source)
            completed = data.get("completed_pairs", data.get("completed_after", ""))
            total = data.get("total_pairs", data.get("expected_pairs", data.get("total_cases", "")))
            result.append({
                "类型": benchmark_type,
                "Run ID": source.parent.name,
                "状态": data.get("status") or ("完成" if data.get("run_completed") else "历史"),
                "进度": f"{completed or '-'} / {total or '-'}",
                "更新时间": datetime.fromtimestamp(source.stat().st_mtime).strftime("%m-%d %H:%M"),
            })
    return sorted(result, key=lambda item: item["更新时间"], reverse=True)


def read_report(path: Path, max_chars: int = 30000) -> str:
    try:
        return path.read_text(encoding="utf-8")[:max_chars]
    except OSError:
        return ""
