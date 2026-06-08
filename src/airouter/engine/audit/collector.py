"""Collector：从 DB 采集 Token 消费记录。

数据源优先级：有实际值用实际值，没有则用预估值（COALESCE）。
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

from sqlalchemy import and_, func

from airouter.models.database import get_session
from airouter.models.db_models import ExecutionFeedbackRecord, RoutingDecisionRecord


class ConsumptionRecord:
    """单条消费记录（合并 routing_decision + execution_feedback）。"""

    def __init__(
        self,
        user_id: str,
        department: str,
        project_id: str,
        client_type: str,
        task_type: str,
        complexity: str,
        risk_level: str,
        selected_model: str,
        input_tokens: int,
        output_tokens: int,
        cost_cny: float,
        task_hash: str,
        timestamp: datetime,
        is_actual: bool,
    ):
        self.user_id = user_id
        self.department = department
        self.project_id = project_id
        self.client_type = client_type
        self.task_type = task_type
        self.complexity = complexity
        self.risk_level = risk_level
        self.selected_model = selected_model
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.cost_cny = cost_cny
        self.task_hash = task_hash
        self.timestamp = timestamp
        self.is_actual = is_actual


class Collector:
    """Token 消费采集器。"""

    def collect(
        self,
        start_date: datetime,
        end_date: datetime,
        user_id: Optional[str] = None,
        project_id: Optional[str] = None,
        department: Optional[str] = None,
    ) -> list[ConsumptionRecord]:
        """采集指定时间范围内的消费记录。

        Args:
            start_date: 开始时间
            end_date: 结束时间
            user_id: 可选用户过滤
            project_id: 可选项目过滤
            department: 可选部门过滤

        Returns:
            ConsumptionRecord 列表
        """
        with get_session() as session:
            # LEFT JOIN routing_decisions + execution_feedback
            query = (
                session.query(
                    RoutingDecisionRecord.user_id,
                    RoutingDecisionRecord.department,
                    RoutingDecisionRecord.project_id,
                    RoutingDecisionRecord.client_type,
                    RoutingDecisionRecord.task_type,
                    RoutingDecisionRecord.complexity,
                    RoutingDecisionRecord.risk_level,
                    RoutingDecisionRecord.selected_models_json,
                    func.coalesce(
                        ExecutionFeedbackRecord.actual_input_tokens,
                        RoutingDecisionRecord.estimated_input_tokens,
                    ).label("input_tokens"),
                    func.coalesce(
                        ExecutionFeedbackRecord.actual_output_tokens,
                        RoutingDecisionRecord.estimated_output_tokens,
                    ).label("output_tokens"),
                    func.coalesce(
                        ExecutionFeedbackRecord.actual_cost_cny,
                        RoutingDecisionRecord.estimated_cost_cny,
                    ).label("cost_cny"),
                    RoutingDecisionRecord.task_hash,
                    RoutingDecisionRecord.created_at,
                    ExecutionFeedbackRecord.id.isnot(None).label("has_feedback"),
                )
                .outerjoin(
                    ExecutionFeedbackRecord,
                    RoutingDecisionRecord.id == ExecutionFeedbackRecord.routing_decision_id,
                )
                .filter(
                    and_(
                        RoutingDecisionRecord.created_at >= start_date,
                        RoutingDecisionRecord.created_at < end_date,
                    )
                )
            )

            # 可选过滤
            if user_id:
                query = query.filter(RoutingDecisionRecord.user_id == user_id)
            if project_id:
                query = query.filter(RoutingDecisionRecord.project_id == project_id)
            if department:
                query = query.filter(RoutingDecisionRecord.department == department)

            results = []
            for row in query.all():
                # 解析 selected_models_json
                model_name = "unknown"
                if row.selected_models_json:
                    try:
                        models = json.loads(row.selected_models_json)
                        if isinstance(models, list) and models:
                            model_name = models[0]
                    except (json.JSONDecodeError, TypeError):
                        pass

                results.append(
                    ConsumptionRecord(
                        user_id=row.user_id or "unknown",
                        department=row.department or "unknown",
                        project_id=row.project_id or "unknown",
                        client_type=row.client_type or "unknown",
                        task_type=row.task_type or "unknown",
                        complexity=row.complexity or "unknown",
                        risk_level=row.risk_level or "unknown",
                        selected_model=model_name,
                        input_tokens=int(row.input_tokens or 0),
                        output_tokens=int(row.output_tokens or 0),
                        cost_cny=float(row.cost_cny or 0),
                        task_hash=row.task_hash or "",
                        timestamp=row.created_at,
                        is_actual=bool(row.has_feedback),
                    )
                )

            return results
