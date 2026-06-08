"""Aggregator：多维分组聚合。

按 user / project / model / task_type / department / day 汇总消费。
"""

from __future__ import annotations

from collections import defaultdict
from typing import Callable

from airouter.engine.audit.collector import ConsumptionRecord
from airouter.models.schemas import CostBreakdown


class Aggregator:
    """消费聚合器。"""

    def aggregate(
        self,
        records: list[ConsumptionRecord],
        group_by: str,
    ) -> list[CostBreakdown]:
        """按指定维度分组聚合。

        Args:
            records: 消费记录列表
            group_by: 分组维度（user / project / model / task_type / department / day）

        Returns:
            CostBreakdown 列表，按 total_cost 降序
        """
        if not records:
            return []

        # 提取分组键
        key_extractor = self._get_key_extractor(group_by)

        # 分组聚合
        groups: dict[str, dict] = defaultdict(lambda: {"cost": 0.0, "calls": 0})
        for rec in records:
            key = key_extractor(rec)
            groups[key]["cost"] += rec.cost_cny
            groups[key]["calls"] += 1

        # 计算总消费
        total_cost = sum(g["cost"] for g in groups.values())

        # 转换为 CostBreakdown
        result = []
        for key, data in groups.items():
            percentage = (data["cost"] / total_cost * 100) if total_cost > 0 else 0
            result.append(
                CostBreakdown(
                    key=key,
                    total_cost=data["cost"],
                    total_calls=data["calls"],
                    percentage=percentage,
                )
            )

        # 按 total_cost 降序
        result.sort(key=lambda x: x.total_cost, reverse=True)
        return result

    def _get_key_extractor(self, group_by: str) -> Callable[[ConsumptionRecord], str]:
        """获取分组键提取函数。"""
        extractors = {
            "user": lambda r: r.user_id,
            "project": lambda r: r.project_id,
            "model": lambda r: r.selected_model,
            "task_type": lambda r: r.task_type,
            "department": lambda r: r.department,
            "day": lambda r: r.timestamp.strftime("%Y-%m-%d"),
            "client_type": lambda r: r.client_type,
        }
        return extractors.get(group_by, lambda r: "unknown")
