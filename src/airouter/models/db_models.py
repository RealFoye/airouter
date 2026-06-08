"""SQLAlchemy ORM models：4 张运行记录表（设计文档 §10）。

控制面（YAML）与数据面（DB）分离。DB 仅存运行记录，不存配置。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class RoutingDecisionRecord(Base):
    """路由决策记录：完整审计轨迹，存预估值。"""

    __tablename__ = "routing_decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_hash: Mapped[str] = mapped_column(Text, nullable=False, index=True)

    # 常查字段（单独列，避免每次解析 JSON）
    user_id: Mapped[str | None] = mapped_column(Text)
    project_id: Mapped[str | None] = mapped_column(Text)
    department: Mapped[str | None] = mapped_column(Text)
    client_type: Mapped[str | None] = mapped_column(Text)
    task_type: Mapped[str | None] = mapped_column(Text, index=True)
    complexity: Mapped[str | None] = mapped_column(Text)
    risk_level: Mapped[str | None] = mapped_column(Text)
    selected_strategy: Mapped[str | None] = mapped_column(Text)
    selected_models_json: Mapped[str | None] = mapped_column(Text)
    estimated_input_tokens: Mapped[int | None] = mapped_column(Integer)
    estimated_output_tokens: Mapped[int | None] = mapped_column(Integer)
    estimated_cost_cny: Mapped[float | None] = mapped_column(Float)
    budget_status: Mapped[str | None] = mapped_column(Text)
    requires_human_review: Mapped[bool | None] = mapped_column(Boolean)
    config_version: Mapped[str | None] = mapped_column(Text)
    config_snapshot_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("config_snapshots.id")
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, nullable=False
    )

    # 复杂信息（JSON 存储）
    task_description: Mapped[str | None] = mapped_column(Text)
    features_json: Mapped[str | None] = mapped_column(Text)
    constraints_json: Mapped[str | None] = mapped_column(Text)
    strategy_candidates_json: Mapped[str | None] = mapped_column(Text)
    selected_strategy_detail_json: Mapped[str | None] = mapped_column(Text)
    score_breakdown_json: Mapped[str | None] = mapped_column(Text)
    alternatives_json: Mapped[str | None] = mapped_column(Text)
    quality_gate_json: Mapped[str | None] = mapped_column(Text)
    fallback_policy_json: Mapped[str | None] = mapped_column(Text)
    human_review_reason: Mapped[str | None] = mapped_column(Text)
    reasoning: Mapped[str | None] = mapped_column(Text)

    # 关系
    feedback: Mapped[list[ExecutionFeedbackRecord]] = relationship(
        back_populates="routing_decision", cascade="all, delete-orphan"
    )


class ExecutionFeedbackRecord(Base):
    """路由执行反馈：存实际执行值，与 routing_decisions 的预估值形成对比。"""

    __tablename__ = "execution_feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    routing_decision_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("routing_decisions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    executed_strategy: Mapped[str | None] = mapped_column(Text)
    executed_models_json: Mapped[str | None] = mapped_column(Text)
    actual_input_tokens: Mapped[int | None] = mapped_column(Integer)
    actual_output_tokens: Mapped[int | None] = mapped_column(Integer)
    actual_cost_cny: Mapped[float | None] = mapped_column(Float)
    actual_latency_ms: Mapped[int | None] = mapped_column(Integer)
    quality_score: Mapped[float | None] = mapped_column(Float)
    quality_gate_passed: Mapped[bool | None] = mapped_column(Boolean)
    user_accepted: Mapped[bool | None] = mapped_column(Boolean)
    user_override_reason: Mapped[str | None] = mapped_column(Text)
    user_override_note: Mapped[str | None] = mapped_column(Text)
    actual_calls_json: Mapped[str | None] = mapped_column(Text)
    error_type: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, nullable=False
    )

    # 关系
    routing_decision: Mapped[RoutingDecisionRecord] = relationship(
        back_populates="feedback"
    )


class BenchmarkResultRecord(Base):
    """Benchmark 运行结果：存模型/策略在测试集上的表现。"""

    __tablename__ = "benchmark_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    suite_name: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    suite_version: Mapped[str | None] = mapped_column(Text)
    case_id: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    case_version: Mapped[str | None] = mapped_column(Text)
    task_type: Mapped[str | None] = mapped_column(Text)
    complexity: Mapped[str | None] = mapped_column(Text)
    model_or_strategy: Mapped[str | None] = mapped_column(Text)
    models_json: Mapped[str | None] = mapped_column(Text)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    cost_cny: Mapped[float | None] = mapped_column(Float)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    quality_score: Mapped[float | None] = mapped_column(Float)
    severe_failure: Mapped[bool] = mapped_column(Boolean, default=False)
    gate_passed: Mapped[bool | None] = mapped_column(Boolean)
    raw_output_path: Mapped[str | None] = mapped_column(Text)
    score_detail_json: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, nullable=False
    )


class ConfigSnapshotRecord(Base):
    """配置快照：审计用，记录每次决策时的完整配置。"""

    __tablename__ = "config_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    config_version: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    models_hash: Mapped[str | None] = mapped_column(Text)
    routing_rules_hash: Mapped[str | None] = mapped_column(Text)
    budgets_hash: Mapped[str | None] = mapped_column(Text)
    quality_defaults_hash: Mapped[str | None] = mapped_column(Text)
    compression_policy_hash: Mapped[str | None] = mapped_column(Text)
    merged_config_json: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, nullable=False
    )
