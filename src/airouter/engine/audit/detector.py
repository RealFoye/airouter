"""Detector：5 类浪费模式检测。

P1: 高配模型滥用（HIGH_TIER_ABUSE）
P2: 重复调用（DUPLICATE_CALLS）
P3: 过长上下文（OVERLONG_CONTEXT）
P4: 可降级未降级（DOWNGRADABLE_NOT_DOWNGRADED）
P5: 缓存机会未利用（CACHE_OPPORTUNITY_MISSED）
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import timedelta

from airouter.config import load_models, load_routing_rules
from airouter.engine.audit.collector import ConsumptionRecord
from airouter.models.schemas import WastePattern


# 模型 tier 映射（从 models.yaml）
def _get_model_tier_map() -> dict[str, int]:
    models = load_models().models
    return {m.name: m.tier for m in models}


# 模型 prompt caching 支持（从 models.yaml）
def _get_model_cache_support() -> dict[str, dict]:
    models = load_models().models
    return {
        m.name: {
            "supports": m.cache.supports_prompt_caching is True,
            "min_prefix_tokens": m.cache.cache_min_prefix_tokens,
        }
        for m in models
    }


# 任务类型 → 最低可用 tier（从 routing_rules.allowed_tiers）
def _get_min_tier_by_task() -> dict[tuple[str, str], int]:
    """(complexity, risk_level) → 最低可用 tier（最便宜的）。"""
    rules = load_routing_rules()
    allowed = rules.allowed_tiers

    result = {}
    for complexity_key, tier_rule in allowed.items():
        default_tiers = list(tier_rule.default)
        high_risk_tiers = list(tier_rule.high_risk)

        # Tier 数字越大越便宜，所以 max() 是最便宜的
        cheapest_default = max(default_tiers) if default_tiers else 3
        cheapest_high = max(high_risk_tiers) if high_risk_tiers else 3

        result[(complexity_key, "LOW")] = cheapest_default
        result[(complexity_key, "MEDIUM")] = cheapest_default
        result[(complexity_key, "HIGH")] = cheapest_high

    return result


class Detector:
    """浪费模式检测器。"""

    def detect(self, records: list[ConsumptionRecord]) -> list[WastePattern]:
        """检测所有浪费模式。

        Args:
            records: 消费记录列表

        Returns:
            WastePattern 列表，按 estimated_savings 降序
        """
        if not records:
            return []

        patterns = []

        # P1: 高配模型滥用
        patterns.extend(self._detect_high_tier_abuse(records))

        # P2: 重复调用
        patterns.extend(self._detect_duplicate_calls(records))

        # P3: 过长上下文
        patterns.extend(self._detect_overlong_context(records))

        # P4: 可降级未降级
        patterns.extend(self._detect_downgradable_not_downgraded(records))

        # P5: 缓存机会未利用
        patterns.extend(self._detect_cache_opportunity_missed(records))

        # 按 estimated_savings 降序
        patterns.sort(key=lambda p: p.estimated_savings, reverse=True)
        return patterns

    def _detect_high_tier_abuse(self, records: list[ConsumptionRecord]) -> list[WastePattern]:
        """P1: SIMPLE 用 Tier 1，或 MODERATE 用 Tier 1（risk != HIGH）。"""
        tier_map = _get_model_tier_map()

        # 按用户分组
        by_user: dict[str, list[ConsumptionRecord]] = defaultdict(list)
        for rec in records:
            tier = tier_map.get(rec.selected_model, 0)
            if tier == 1:
                if rec.complexity == "SIMPLE":
                    by_user[rec.user_id].append(rec)
                elif rec.complexity == "MODERATE" and rec.risk_level != "HIGH":
                    by_user[rec.user_id].append(rec)

        patterns = []
        for user_id, abused_records in by_user.items():
            if not abused_records:
                continue

            total_cost = sum(r.cost_cny for r in abused_records)
            # 估算节省：假设用 Tier 3 模型，成本降低 70%
            estimated_savings = total_cost * 0.7

            # 确定 severity
            if len(abused_records) >= 50:
                severity = "High"
            elif len(abused_records) >= 20:
                severity = "Medium"
            else:
                severity = "Low"

            # 样例
            sample_task_hashes = list(set(r.task_hash for r in abused_records[:5]))
            sample_models = list(set(r.selected_model for r in abused_records[:5]))

            patterns.append(
                WastePattern(
                    pattern_type="HIGH_TIER_ABUSE",
                    scope="user",
                    scope_value=user_id,
                    occurrence_count=len(abused_records),
                    current_cost=round(total_cost, 2),
                    estimated_savings=round(estimated_savings, 2),
                    severity=severity,
                    suggestion=f"用户 {user_id} 在 {len(abused_records)} 条 SIMPLE/MODERATE 任务中使用了 Tier 1 模型，建议降级到 Tier 2/3",
                    evidence_json={
                        "sample_task_hashes": sample_task_hashes,
                        "sample_models": sample_models,
                        "complexity_distribution": {
                            "SIMPLE": sum(1 for r in abused_records if r.complexity == "SIMPLE"),
                            "MODERATE": sum(1 for r in abused_records if r.complexity == "MODERATE"),
                        },
                    },
                )
            )

        return patterns

    def _detect_duplicate_calls(self, records: list[ConsumptionRecord]) -> list[WastePattern]:
        """P2: 同一 user_id + project_id + task_hash 在 10 分钟内出现多次。"""
        # 按 (user_id, project_id, task_hash) 分组
        groups: dict[tuple[str, str, str], list[ConsumptionRecord]] = defaultdict(list)
        for rec in records:
            key = (rec.user_id, rec.project_id, rec.task_hash)
            groups[key].append(rec)

        # 检测 10 分钟内重复
        by_user: dict[str, list[ConsumptionRecord]] = defaultdict(list)
        for (user_id, project_id, task_hash), group_records in groups.items():
            if len(group_records) < 2:
                continue

            # 按时间排序
            sorted_records = sorted(group_records, key=lambda r: r.timestamp)

            # 检测连续重复（10 分钟内）
            for i in range(len(sorted_records) - 1):
                time_diff = sorted_records[i + 1].timestamp - sorted_records[i].timestamp
                if time_diff <= timedelta(minutes=10):
                    # 重复的那条算浪费
                    by_user[user_id].append(sorted_records[i + 1])

        patterns = []
        for user_id, dup_records in by_user.items():
            if not dup_records:
                continue

            total_cost = sum(r.cost_cny for r in dup_records)
            # 节省 = 重复调用的全部成本（应该走缓存）
            estimated_savings = total_cost

            severity = "High" if len(dup_records) >= 20 else ("Medium" if len(dup_records) >= 5 else "Low")

            sample_task_hashes = list(set(r.task_hash for r in dup_records[:5]))

            patterns.append(
                WastePattern(
                    pattern_type="DUPLICATE_CALLS",
                    scope="user",
                    scope_value=user_id,
                    occurrence_count=len(dup_records),
                    current_cost=round(total_cost, 2),
                    estimated_savings=round(estimated_savings, 2),
                    severity=severity,
                    suggestion=f"用户 {user_id} 有 {len(dup_records)} 条重复调用（10 分钟内相同任务），建议启用缓存",
                    evidence_json={
                        "sample_task_hashes": sample_task_hashes,
                        "time_window_minutes": 10,
                    },
                )
            )

        return patterns

    def _detect_overlong_context(self, records: list[ConsumptionRecord]) -> list[WastePattern]:
        """P3: estimated_input_tokens > max(10000, task_type_median * 2)。"""
        # 按 task_type 计算中位数
        by_task_type: dict[str, list[int]] = defaultdict(list)
        for rec in records:
            by_task_type[rec.task_type].append(rec.input_tokens)

        medians = {
            task_type: statistics.median(tokens) if tokens else 0
            for task_type, tokens in by_task_type.items()
        }

        # 检测过长
        by_user: dict[str, list[ConsumptionRecord]] = defaultdict(list)
        for rec in records:
            threshold = max(10000, medians.get(rec.task_type, 0) * 2)
            if rec.input_tokens > threshold:
                by_user[rec.user_id].append(rec)

        patterns = []
        for user_id, overlong_records in by_user.items():
            if not overlong_records:
                continue

            total_cost = sum(r.cost_cny for r in overlong_records)
            avg_input = statistics.mean([r.input_tokens for r in overlong_records])

            # 估算节省：如果 input tokens 降低到中位数，成本降低比例
            avg_saving_ratio = 1 - (medians.get(overlong_records[0].task_type, 0) / avg_input) if avg_input > 0 else 0
            estimated_savings = total_cost * max(0, avg_saving_ratio)

            severity = "High" if len(overlong_records) >= 30 else ("Medium" if len(overlong_records) >= 10 else "Low")

            sample_task_hashes = list(set(r.task_hash for r in overlong_records[:5]))

            patterns.append(
                WastePattern(
                    pattern_type="OVERLONG_CONTEXT",
                    scope="user",
                    scope_value=user_id,
                    occurrence_count=len(overlong_records),
                    current_cost=round(total_cost, 2),
                    estimated_savings=round(estimated_savings, 2),
                    severity=severity,
                    suggestion=f"用户 {user_id} 有 {len(overlong_records)} 条任务上下文过长（平均 {int(avg_input)} tokens），建议裁剪到合理范围",
                    evidence_json={
                        "sample_task_hashes": sample_task_hashes,
                        "average_input_tokens": int(avg_input),
                        "task_type_medians": {
                            rec.task_type: int(medians.get(rec.task_type, 0))
                            for rec in overlong_records[:5]
                        },
                    },
                )
            )

        return patterns

    def _detect_downgradable_not_downgraded(self, records: list[ConsumptionRecord]) -> list[WastePattern]:
        """P4: 实际 selected tier 明显高于最便宜的可用 tier。"""
        tier_map = _get_model_tier_map()
        cheapest_tier_by_task = _get_min_tier_by_task()

        # 检测可降级
        by_user: dict[str, list[ConsumptionRecord]] = defaultdict(list)
        for rec in records:
            actual_tier = tier_map.get(rec.selected_model, 0)
            cheapest_tier = cheapest_tier_by_task.get((rec.complexity, rec.risk_level), 3)

            # 如果实际 tier 比最便宜的 tier 贵 2 级以上（tier 数字越小越贵）
            # 例如：actual=1, cheapest=3 → 1 < 3-1=2 → True，可降级
            if actual_tier > 0 and actual_tier < cheapest_tier - 1:
                by_user[rec.user_id].append(rec)

        patterns = []
        for user_id, downgradable_records in by_user.items():
            if not downgradable_records:
                continue

            total_cost = sum(r.cost_cny for r in downgradable_records)
            # 估算节省：降级到最低可用 tier，成本降低 50%
            estimated_savings = total_cost * 0.5

            severity = "Medium" if len(downgradable_records) >= 10 else "Low"

            sample_task_hashes = list(set(r.task_hash for r in downgradable_records[:5]))

            patterns.append(
                WastePattern(
                    pattern_type="DOWNGRADABLE_NOT_DOWNGRADED",
                    scope="user",
                    scope_value=user_id,
                    occurrence_count=len(downgradable_records),
                    current_cost=round(total_cost, 2),
                    estimated_savings=round(estimated_savings, 2),
                    severity=severity,
                    suggestion=f"用户 {user_id} 有 {len(downgradable_records)} 条任务可以降级到更低 tier 的模型",
                    evidence_json={
                        "sample_task_hashes": sample_task_hashes,
                    },
                )
            )

        return patterns

    def _detect_cache_opportunity_missed(self, records: list[ConsumptionRecord]) -> list[WastePattern]:
        """P5: 相同 task_hash 多次出现 + 模型支持 prompt caching + input tokens > cache_min_prefix_tokens。"""
        cache_support = _get_model_cache_support()

        # 按 task_hash 分组
        by_task_hash: dict[str, list[ConsumptionRecord]] = defaultdict(list)
        for rec in records:
            by_task_hash[rec.task_hash].append(rec)

        # 检测缓存机会
        by_user: dict[str, list[ConsumptionRecord]] = defaultdict(list)
        for task_hash, group_records in by_task_hash.items():
            if len(group_records) < 2:
                continue

            # 检查模型是否支持 caching
            for rec in group_records:
                cache_info = cache_support.get(rec.selected_model, {})
                if cache_info.get("supports") and rec.input_tokens >= cache_info.get("min_prefix_tokens", 1024):
                    by_user[rec.user_id].append(rec)
                    break  # 一个 task_hash 只算一次

        patterns = []
        for user_id, cacheable_records in by_user.items():
            if not cacheable_records:
                continue

            total_cost = sum(r.cost_cny for r in cacheable_records)
            # 估算节省：缓存命中可以节省 80% input cost
            estimated_savings = total_cost * 0.6

            severity = "Medium" if len(cacheable_records) >= 15 else "Low"

            sample_task_hashes = list(set(r.task_hash for r in cacheable_records[:5]))

            patterns.append(
                WastePattern(
                    pattern_type="CACHE_OPPORTUNITY_MISSED",
                    scope="user",
                    scope_value=user_id,
                    occurrence_count=len(cacheable_records),
                    current_cost=round(total_cost, 2),
                    estimated_savings=round(estimated_savings, 2),
                    severity=severity,
                    suggestion=f"用户 {user_id} 有 {len(cacheable_records)} 条任务可以利用 prompt caching（相同 task_hash 多次出现），建议启用缓存",
                    evidence_json={
                        "sample_task_hashes": sample_task_hashes,
                    },
                )
            )

        return patterns
