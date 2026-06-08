"""Attribution：消费归因分析。

分析"谁/什么项目/什么任务类型贡献了多少消费/节省空间"。
用于 CLI 和 Web 消费看板。
"""

from __future__ import annotations

from airouter.engine.audit.aggregator import Aggregator
from airouter.engine.audit.collector import ConsumptionRecord
from airouter.engine.audit.detector import Detector


class Attribution:
    """消费归因分析器。"""

    def __init__(self):
        self.aggregator = Aggregator()
        self.detector = Detector()

    def analyze(
        self,
        records: list[ConsumptionRecord],
        top_n_waste: int = 5,
    ) -> dict:
        """执行消费归因分析。

        Args:
            records: 消费记录列表
            top_n_waste: 返回 Top N 浪费模式

        Returns:
            归因分析结果字典：
            {
                "total_cost": float,
                "total_calls": int,
                "total_input_tokens": int,
                "total_output_tokens": int,
                "daily_average": float,
                "by_user": list[CostBreakdown],
                "by_model": list[CostBreakdown],
                "by_project": list[CostBreakdown],
                "by_department": list[CostBreakdown],
                "by_task_type": list[CostBreakdown],
                "top_waste_patterns": list[WastePattern],
                "total_estimated_savings": float,
                "heavy_users": list[str],
            }
        """
        if not records:
            return {
                "total_cost": 0.0,
                "total_calls": 0,
                "total_input_tokens": 0,
                "total_output_tokens": 0,
                "daily_average": 0.0,
                "by_user": [],
                "by_model": [],
                "by_project": [],
                "by_department": [],
                "by_task_type": [],
                "top_waste_patterns": [],
                "total_estimated_savings": 0.0,
                "heavy_users": [],
            }

        # 基础统计
        total_cost = sum(r.cost_cny for r in records)
        total_calls = len(records)
        total_input_tokens = sum(r.input_tokens for r in records)
        total_output_tokens = sum(r.output_tokens for r in records)

        # 计算天数
        if records:
            timestamps = [r.timestamp for r in records]
            min_ts = min(timestamps)
            max_ts = max(timestamps)
            days = max(1, (max_ts - min_ts).days + 1)
        else:
            days = 1

        daily_average = total_cost / days

        # 多维分组
        by_user = self.aggregator.aggregate(records, "user")
        by_model = self.aggregator.aggregate(records, "model")
        by_project = self.aggregator.aggregate(records, "project")
        by_department = self.aggregator.aggregate(records, "department")
        by_task_type = self.aggregator.aggregate(records, "task_type")

        # 浪费模式检测
        waste_patterns = self.detector.detect(records)
        top_waste = waste_patterns[:top_n_waste]
        total_estimated_savings = sum(p.estimated_savings for p in waste_patterns)

        # 识别重度用户（消耗 > 30% 总消费）
        heavy_users = [
            item.key for item in by_user if item.percentage > 30.0
        ]

        return {
            "total_cost": round(total_cost, 2),
            "total_calls": total_calls,
            "total_input_tokens": total_input_tokens,
            "total_output_tokens": total_output_tokens,
            "daily_average": round(daily_average, 2),
            "by_user": by_user,
            "by_model": by_model,
            "by_project": by_project,
            "by_department": by_department,
            "by_task_type": by_task_type,
            "top_waste_patterns": top_waste,
            "total_estimated_savings": round(total_estimated_savings, 2),
            "heavy_users": heavy_users,
        }
