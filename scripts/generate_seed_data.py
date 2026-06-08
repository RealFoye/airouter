#!/usr/bin/env python3
"""生成种子数据：模拟 routing_decisions + execution_feedback。

用于测试 audit 引擎和消费看板。

Usage:
    # 快速验证（200 条）
    python scripts/generate_seed_data.py --rows 200

    # 完整数据（6000 条 = 30天 × 200条/天）
    python scripts/generate_seed_data.py --days 30 --rows-per-day 200

    # 指定输出
    python scripts/generate_seed_data.py --rows 200 --output seed_test.db
"""

import argparse
import hashlib
import random
from datetime import datetime, timedelta
from functools import lru_cache

from airouter.config import load_models
from airouter.models.database import get_session, init_db
from airouter.models.db_models import ExecutionFeedbackRecord, RoutingDecisionRecord

# 固定随机种子，保证测试稳定
SEED = 42

# 虚拟用户（8 人，4 部门）
USERS = [
    {"user_id": "alice", "department": "backend"},
    {"user_id": "bob", "department": "backend"},
    {"user_id": "charlie", "department": "frontend"},
    {"user_id": "diana", "department": "frontend"},
    {"user_id": "eve", "department": "data"},
    {"user_id": "frank", "department": "data"},
    {"user_id": "grace", "department": "devops"},
    {"user_id": "henry", "department": "devops"},
]

# 重度用户（消耗 3-5x 平均）
HEAVY_USERS = {"alice", "bob"}

PROJECTS = ["proj-alpha", "proj-beta", "proj-gamma", "proj-delta", "proj-epsilon"]
CLIENT_TYPES = ["claude-code", "cursor", "api-direct", "custom-agent", "web-ide"]

# 任务类型（按复杂度分布）
TASK_PROFILES = [
    {"task_type": "CODE_GENERATION", "complexity": "SIMPLE", "risk_level": "LOW", "input_tokens": 2000, "output_tokens": 500},
    {"task_type": "CODE_GENERATION", "complexity": "MODERATE", "risk_level": "MEDIUM", "input_tokens": 5000, "output_tokens": 1500},
    {"task_type": "CODE_REVIEW", "complexity": "MODERATE", "risk_level": "MEDIUM", "input_tokens": 8000, "output_tokens": 2000},
    {"task_type": "DOCUMENTATION", "complexity": "SIMPLE", "risk_level": "LOW", "input_tokens": 3000, "output_tokens": 800},
    {"task_type": "CONVERSATION", "complexity": "SIMPLE", "risk_level": "LOW", "input_tokens": 1500, "output_tokens": 400},
    {"task_type": "BUG_ANALYSIS", "complexity": "COMPLEX", "risk_level": "HIGH", "input_tokens": 12000, "output_tokens": 3000},
    {"task_type": "REFACTORING", "complexity": "COMPLEX", "risk_level": "MEDIUM", "input_tokens": 10000, "output_tokens": 2500},
    {"task_type": "TEST_GENERATION", "complexity": "MODERATE", "risk_level": "LOW", "input_tokens": 6000, "output_tokens": 1800},
]


@lru_cache(maxsize=1)
def _get_model_catalog():
    """懒加载模型目录表：name → ModelEntry。"""
    return {m.name: m for m in load_models().models}


@lru_cache(maxsize=1)
def _get_tier_pools():
    """从配置派生 tier 池：tier → [model_name]。"""
    catalog = _get_model_catalog()
    pools: dict[int, list[str]] = {1: [], 2: [], 3: []}
    for name, m in catalog.items():
        pools[m.tier].append(name)
    return pools


@lru_cache(maxsize=1)
def _get_cache_model_names():
    """从配置派生支持 prompt caching 的模型列表。"""
    catalog = _get_model_catalog()
    return [name for name, m in catalog.items() if m.cache.supports_prompt_caching is True]


def generate_task_hash(user_id: str, task_type: str, timestamp: datetime) -> str:
    """生成任务 hash（模拟 task_description 的 MD5）。"""
    raw = f"{user_id}:{task_type}:{timestamp.isoformat()}"
    return hashlib.md5(raw.encode()).hexdigest()[:12]


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """估算成本（从 models.yaml 读取定价）。"""
    catalog = _get_model_catalog()
    m = catalog.get(model)
    if m is None:
        return 0.0
    return (input_tokens / 1000.0) * m.input_price_per_1k + (output_tokens / 1000.0) * m.output_price_per_1k


def select_model(profile: dict, rng: random.Random) -> str:
    """根据任务复杂度选择模型（从 models.yaml 派生 tier 池）。"""
    pools = _get_tier_pools()
    complexity = profile["complexity"]
    if complexity == "SIMPLE":
        return rng.choice(pools[3]) if pools[3] else rng.choice(pools[2])
    elif complexity == "MODERATE":
        return rng.choice(pools[2]) if pools[2] else rng.choice(pools[1])
    else:  # COMPLEX / EXPERT
        return rng.choice(pools[1]) if pools[1] else rng.choice(pools[2])


def inject_waste_patterns(records: list[dict], rng: random.Random, now: datetime) -> None:
    """注入浪费模式（P1-P5）。"""
    n = len(records)
    tier_pools = _get_tier_pools()
    cache_models = _get_cache_model_names()

    # P1: 高配滥用（15%）- SIMPLE/MODERATE 任务用了 Tier 1
    p1_count = int(n * 0.15)
    p1_indices = rng.sample(range(n), p1_count)
    tier1 = tier_pools[1]
    for idx in p1_indices:
        rec = records[idx]
        if rec["complexity"] in ("SIMPLE", "MODERATE") and rec["risk_level"] != "HIGH":
            rec["selected_model"] = rng.choice(tier1)
            rec["waste_pattern"] = "P1"

    # P2: 重复调用（10%）- 同一 user_id + task_hash 在 10 分钟内出现多次
    p2_count = int(n * 0.10)
    p2_users = rng.choices(USERS, k=p2_count)
    latest_allowed = now - timedelta(seconds=1)
    for user in p2_users:
        base_records = [r for r in records if r["user_id"] == user["user_id"]]
        if base_records:
            base = rng.choice(base_records)
            # 确保 dup timestamp 不超过 now
            remaining = (latest_allowed - base["timestamp"]).total_seconds()
            if remaining < 60:
                continue
            max_minutes = min(9, int(remaining // 60))
            if max_minutes < 1:
                continue
            dup = base.copy()
            dup["timestamp"] = base["timestamp"] + timedelta(minutes=rng.randint(1, max_minutes))
            dup["task_hash"] = base["task_hash"]
            dup["waste_pattern"] = "P2"
            records.append(dup)

    # P3: 过长上下文（8%）- input_tokens 远超中位数
    p3_count = int(n * 0.08)
    p3_indices = rng.sample(range(n), p3_count)
    for idx in p3_indices:
        rec = records[idx]
        multiplier = rng.uniform(3.0, 5.0)
        rec["estimated_input_tokens"] = int(rec["estimated_input_tokens"] * multiplier)
        rec["waste_pattern"] = "P3"

    # P4: 可降级未降级（5%）- DOCUMENTATION/CONVERSATION 用了 Tier 1
    p4_candidates = [i for i, r in enumerate(records) if r["task_type"] in ("DOCUMENTATION", "CONVERSATION") and "waste_pattern" not in r]
    p4_count = min(int(n * 0.05), len(p4_candidates))
    p4_indices = rng.sample(p4_candidates, p4_count)
    for idx in p4_indices:
        rec = records[idx]
        rec["selected_model"] = rng.choice(tier1)
        rec["waste_pattern"] = "P4"

    # P5: 缓存机会未利用（3%）- 相同 task_hash 多次出现但没走缓存
    # 需要模型支持 caching 且 input_tokens > cache_min_prefix_tokens (1024)
    p5_count = int(n * 0.03)
    p5_users = rng.choices(USERS, k=p5_count)
    latest_allowed = now - timedelta(seconds=1)
    for user in p5_users:
        base_records = [r for r in records if r["user_id"] == user["user_id"]]
        if not base_records:
            continue
        base = rng.choice(base_records)
        # 强制使用支持 caching 的模型，并确保 input_tokens > 1024
        if cache_models:
            base["selected_model"] = rng.choice(cache_models)
        base["estimated_input_tokens"] = max(base["estimated_input_tokens"], 2000)
        # 计算最大允许偏移小时数，确保不进入未来且不触发 P2（≥2h 间隔）
        max_hours = int((latest_allowed - base["timestamp"]).total_seconds() // 3600)
        if max_hours < 2:
            continue
        # 复制 2-3 次，间隔较久（≥ 2 小时），不会触发 P2
        for _ in range(rng.randint(2, 3)):
            dup = base.copy()
            dup["timestamp"] = base["timestamp"] + timedelta(hours=rng.randint(2, min(24, max_hours)))
            dup["task_hash"] = base["task_hash"]
            dup["waste_pattern"] = "P5"
            records.append(dup)


def generate_seed_data(days: int, rows_per_day: int, output_db: str, append: bool = False) -> None:
    """生成种子数据。"""
    rng = random.Random(SEED)

    total_rows = days * rows_per_day
    print(f"生成 {total_rows} 条种子数据（{days} 天 × {rows_per_day} 条/天）...")

    # 初始化数据库
    init_db(f"sqlite:///{output_db}")

    # 默认清空数据库，除非指定 --append
    if not append:
        print("清空现有数据...")
        with get_session() as session:
            session.query(RoutingDecisionRecord).delete()
            session.query(ExecutionFeedbackRecord).delete()
            session.commit()

    # 生成基础记录
    records = []
    now = datetime.now()
    start_date = now - timedelta(days=days)

    for day_offset in range(days):
        day = start_date + timedelta(days=day_offset)
        for row_idx in range(rows_per_day):
            timestamp = day + timedelta(seconds=rng.randint(0, 86400))
            user = rng.choice(USERS)

            # 重度用户消耗 3-5x
            if user["user_id"] in HEAVY_USERS and rng.random() < 0.3:
                # 额外生成 2-4 条
                for _ in range(rng.randint(2, 4)):
                    extra_ts = timestamp + timedelta(minutes=rng.randint(1, 30))
                    profile = rng.choice(TASK_PROFILES)
                    model = select_model(profile, rng)
                    task_hash = generate_task_hash(user["user_id"], profile["task_type"], extra_ts)

                    records.append({
                        "user_id": user["user_id"],
                        "department": user["department"],
                        "project_id": rng.choice(PROJECTS),
                        "client_type": rng.choice(CLIENT_TYPES),
                        "task_type": profile["task_type"],
                        "complexity": profile["complexity"],
                        "risk_level": profile["risk_level"],
                        "selected_model": model,
                        "estimated_input_tokens": profile["input_tokens"],
                        "estimated_output_tokens": profile["output_tokens"],
                        "task_hash": task_hash,
                        "timestamp": extra_ts,
                    })

            profile = rng.choice(TASK_PROFILES)
            model = select_model(profile, rng)
            task_hash = generate_task_hash(user["user_id"], profile["task_type"], timestamp)

            records.append({
                "user_id": user["user_id"],
                "department": user["department"],
                "project_id": rng.choice(PROJECTS),
                "client_type": rng.choice(CLIENT_TYPES),
                "task_type": profile["task_type"],
                "complexity": profile["complexity"],
                "risk_level": profile["risk_level"],
                "selected_model": model,
                "estimated_input_tokens": profile["input_tokens"],
                "estimated_output_tokens": profile["output_tokens"],
                "task_hash": task_hash,
                "timestamp": timestamp,
            })

    # 注入浪费模式
    inject_waste_patterns(records, rng, now)

    print(f"总记录数：{len(records)}（含注入的浪费模式）")

    # 写入数据库
    with get_session() as session:
        for rec in records:
            cost = estimate_cost(rec["selected_model"], rec["estimated_input_tokens"], rec["estimated_output_tokens"])

            rd = RoutingDecisionRecord(
                task_hash=rec["task_hash"],
                user_id=rec["user_id"],
                department=rec["department"],
                project_id=rec["project_id"],
                client_type=rec["client_type"],
                task_type=rec["task_type"],
                complexity=rec["complexity"],
                risk_level=rec["risk_level"],
                selected_strategy="SINGLE_MODEL",
                selected_models_json=f'["{rec["selected_model"]}"]',
                estimated_input_tokens=rec["estimated_input_tokens"],
                estimated_output_tokens=rec["estimated_output_tokens"],
                estimated_cost_cny=cost,
                budget_status="OK",
                requires_human_review=False,
                config_version="v1.0",
                created_at=rec["timestamp"],
            )
            session.add(rd)
            session.flush()

            # 生成 execution_feedback（80% 有反馈）
            if rng.random() < 0.8:
                # actual 通常接近 estimated，但有 10-20% 偏差
                actual_input = int(rec["estimated_input_tokens"] * rng.uniform(0.8, 1.2))
                actual_output = int(rec["estimated_output_tokens"] * rng.uniform(0.8, 1.2))
                actual_cost = estimate_cost(rec["selected_model"], actual_input, actual_output)

                ef = ExecutionFeedbackRecord(
                    routing_decision_id=rd.id,
                    executed_strategy="SINGLE_MODEL",
                    executed_models_json=f'["{rec["selected_model"]}"]',
                    actual_input_tokens=actual_input,
                    actual_output_tokens=actual_output,
                    actual_cost_cny=actual_cost,
                    actual_latency_ms=rng.randint(500, 5000),
                    quality_score=rng.uniform(0.6, 0.95),
                    quality_gate_passed=rng.random() < 0.9,
                    user_accepted=rng.random() < 0.95,
                    created_at=max(
                        rec["timestamp"],
                        min(
                            rec["timestamp"] + timedelta(seconds=rng.randint(10, 300)),
                            now - timedelta(seconds=1),
                        ),
                    ),
                )
                session.add(ef)

    print(f"✓ 已写入 {output_db}")


def main():
    parser = argparse.ArgumentParser(description="生成种子数据")
    parser.add_argument("--days", type=int, default=1, help="天数（默认 1）")
    parser.add_argument("--rows-per-day", type=int, default=200, help="每天记录数（默认 200）")
    parser.add_argument("--rows", type=int, help="总记录数（覆盖 --days 和 --rows-per-day）")
    parser.add_argument("--output", type=str, default="seed.db", help="输出数据库文件（默认 seed.db）")
    parser.add_argument("--append", action="store_true", help="追加到现有数据（默认覆盖）")

    args = parser.parse_args()

    if args.rows:
        # 单日模式
        days = 1
        rows_per_day = args.rows
    else:
        days = args.days
        rows_per_day = args.rows_per_day

    generate_seed_data(days, rows_per_day, args.output, append=args.append)


if __name__ == "__main__":
    main()
