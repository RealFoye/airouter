"""测试数据库：4 张表创建 + CRUD + JSON 字段 + FK 关系。"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import inspect

from airouter.models.database import get_session, init_db
from airouter.models.db_models import (
    BenchmarkResultRecord,
    ConfigSnapshotRecord,
    ExecutionFeedbackRecord,
    RoutingDecisionRecord,
)


@pytest.fixture(autouse=True)
def setup_db():
    """每个测试用例使用独立的 in-memory 数据库。"""
    # 重置全局状态
    import airouter.models.database as db_module
    db_module._engine = None
    db_module._SessionLocal = None

    init_db("sqlite:///:memory:")
    yield


# ── 表创建 ──────────────────────────────────────────────────
class TestTableCreation:
    def test_all_four_tables_exist(self):
        engine = init_db("sqlite:///:memory:")
        inspector = inspect(engine)
        table_names = set(inspector.get_table_names())
        assert "routing_decisions" in table_names
        assert "execution_feedback" in table_names
        assert "benchmark_results" in table_names
        assert "config_snapshots" in table_names

    def test_routing_decisions_columns(self):
        engine = init_db("sqlite:///:memory:")
        inspector = inspect(engine)
        columns = {c["name"] for c in inspector.get_columns("routing_decisions")}
        # 常查字段
        assert "task_hash" in columns
        assert "task_type" in columns
        assert "selected_strategy" in columns
        assert "estimated_cost_cny" in columns
        # JSON 字段
        assert "features_json" in columns
        assert "alternatives_json" in columns
        # 审计字段
        assert "config_version" in columns
        assert "config_snapshot_id" in columns

    def test_execution_feedback_fk(self):
        engine = init_db("sqlite:///:memory:")
        inspector = inspect(engine)
        fks = inspector.get_foreign_keys("execution_feedback")
        assert len(fks) == 1
        assert fks[0]["referred_table"] == "routing_decisions"
        assert fks[0]["constrained_columns"] == ["routing_decision_id"]

    def test_fk_enforcement(self):
        """SQLite 外键强制：引用不存在的 routing_decision_id 应报错。"""
        from sqlalchemy.exc import IntegrityError

        with pytest.raises(IntegrityError):
            with get_session() as session:
                fb = ExecutionFeedbackRecord(
                    routing_decision_id=999,  # 不存在
                    actual_cost_cny=0.05,
                )
                session.add(fb)


# ── RoutingDecisionRecord CRUD ──────────────────────────────
class TestRoutingDecisionCRUD:
    def test_create_and_read(self):
        with get_session() as session:
            record = RoutingDecisionRecord(
                task_hash="abc123",
                task_type="CODE_GENERATION",
                complexity="COMPLEX",
                risk_level="HIGH",
                selected_strategy="SINGLE_MODEL",
                estimated_input_tokens=5000,
                estimated_output_tokens=800,
                estimated_cost_cny=0.05,
                budget_status="OK",
                requires_human_review=True,
                config_version="v1.0",
                task_description="写一个FastAPI JWT鉴权中间件",
            )
            session.add(record)

        with get_session() as session:
            result = session.query(RoutingDecisionRecord).filter_by(task_hash="abc123").one()
            assert result.task_type == "CODE_GENERATION"
            assert result.complexity == "COMPLEX"
            assert result.risk_level == "HIGH"
            assert result.estimated_cost_cny == 0.05
            assert result.requires_human_review is True
            assert result.created_at is not None

    def test_json_field_write_read(self):
        features = {
            "category": "CODE_GENERATION",
            "complexity": "COMPLEX",
            "risk_level": "HIGH",
            "estimated_input_tokens": 5000,
        }
        alternatives = [
            {"strategy": "PLAN_EXECUTE", "cost": 0.03, "quality": 0.7},
            {"strategy": "GUIDED_EXECUTE", "cost": 0.04, "quality": 0.75},
        ]

        with get_session() as session:
            record = RoutingDecisionRecord(
                task_hash="json_test",
                features_json=json.dumps(features, ensure_ascii=False),
                alternatives_json=json.dumps(alternatives, ensure_ascii=False),
            )
            session.add(record)

        with get_session() as session:
            result = session.query(RoutingDecisionRecord).filter_by(task_hash="json_test").one()
            loaded_features = json.loads(result.features_json)
            assert loaded_features["category"] == "CODE_GENERATION"
            loaded_alts = json.loads(result.alternatives_json)
            assert len(loaded_alts) == 2
            assert loaded_alts[0]["strategy"] == "PLAN_EXECUTE"


# ── ExecutionFeedbackRecord CRUD ────────────────────────────
class TestExecutionFeedbackCRUD:
    def _create_decision(self, session, task_hash="fk_test") -> int:
        record = RoutingDecisionRecord(task_hash=task_hash)
        session.add(record)
        session.flush()
        return record.id

    def test_create_with_fk(self):
        with get_session() as session:
            rd_id = self._create_decision(session)
            feedback = ExecutionFeedbackRecord(
                routing_decision_id=rd_id,
                executed_strategy="SINGLE_MODEL",
                actual_input_tokens=4800,
                actual_output_tokens=750,
                actual_cost_cny=0.048,
                actual_latency_ms=1200,
                quality_score=0.82,
                quality_gate_passed=True,
                user_accepted=True,
            )
            session.add(feedback)

        with get_session() as session:
            fb = session.query(ExecutionFeedbackRecord).first()
            assert fb.routing_decision_id == rd_id
            assert fb.actual_cost_cny == 0.048
            assert fb.quality_gate_passed is True
            assert fb.user_accepted is True

    def test_actual_calls_json(self):
        """Plan-Execute 多次调用明细 JSON 字段。"""
        calls = [
            {"role": "planner", "model": "qwen3.7-max", "input_tokens": 10000, "cost_cny": 0.20},
            {"role": "executor", "model": "deepseek-v4-flash", "input_tokens": 3000, "cost_cny": 0.02},
        ]

        with get_session() as session:
            rd_id = self._create_decision(session)
            feedback = ExecutionFeedbackRecord(
                routing_decision_id=rd_id,
                actual_calls_json=json.dumps(calls, ensure_ascii=False),
            )
            session.add(feedback)

        with get_session() as session:
            fb = session.query(ExecutionFeedbackRecord).first()
            loaded_calls = json.loads(fb.actual_calls_json)
            assert len(loaded_calls) == 2
            assert loaded_calls[0]["role"] == "planner"

    def test_relationship_back_populates(self):
        """通过 relationship 双向访问。"""
        with get_session() as session:
            rd_id = self._create_decision(session, "rel_test")
            feedback = ExecutionFeedbackRecord(
                routing_decision_id=rd_id,
                actual_cost_cny=0.05,
            )
            session.add(feedback)

        with get_session() as session:
            rd = session.query(RoutingDecisionRecord).filter_by(task_hash="rel_test").one()
            assert len(rd.feedback) == 1
            assert rd.feedback[0].actual_cost_cny == 0.05


# ── BenchmarkResultRecord CRUD ──────────────────────────────
class TestBenchmarkResultCRUD:
    def test_create_and_read(self):
        with get_session() as session:
            record = BenchmarkResultRecord(
                suite_name="level1_offline",
                suite_version="v1.0",
                case_id="case_001",
                task_type="CODE_GENERATION",
                complexity="SIMPLE",
                model_or_strategy="qwen3.7-max",
                input_tokens=2000,
                output_tokens=500,
                cost_cny=0.01,
                latency_ms=800,
                quality_score=0.75,
                severe_failure=False,
                gate_passed=True,
            )
            session.add(record)

        with get_session() as session:
            result = session.query(BenchmarkResultRecord).filter_by(case_id="case_001").one()
            assert result.suite_name == "level1_offline"
            assert result.cost_cny == 0.01
            assert result.gate_passed is True
            assert result.severe_failure is False

    def test_score_detail_json(self):
        detail = {"capability": 0.9, "cost": 0.8, "quality": 0.75, "latency": 0.6}
        with get_session() as session:
            record = BenchmarkResultRecord(
                suite_name="level2_comparison",
                case_id="case_002",
                score_detail_json=json.dumps(detail),
            )
            session.add(record)

        with get_session() as session:
            result = session.query(BenchmarkResultRecord).filter_by(case_id="case_002").one()
            loaded = json.loads(result.score_detail_json)
            assert loaded["quality"] == 0.75


# ── ConfigSnapshotRecord CRUD ───────────────────────────────
class TestConfigSnapshotCRUD:
    def test_create_and_read(self):
        merged = {"models": [{"name": "qwen3.7-max"}], "routing_rules": {"version": "v1"}}

        with get_session() as session:
            record = ConfigSnapshotRecord(
                config_version="v1.0",
                models_hash="abc123",
                routing_rules_hash="def456",
                budgets_hash="ghi789",
                quality_defaults_hash="jkl012",
                compression_policy_hash="mno345",
                merged_config_json=json.dumps(merged, ensure_ascii=False),
            )
            session.add(record)

        with get_session() as session:
            result = session.query(ConfigSnapshotRecord).filter_by(config_version="v1.0").one()
            assert result.models_hash == "abc123"
            loaded = json.loads(result.merged_config_json)
            assert loaded["models"][0]["name"] == "qwen3.7-max"


# ── Cascade + 边界 ──────────────────────────────────────────
class TestCascadeAndEdgeCases:
    def test_cascade_delete(self):
        """删除 routing_decision 应级联删除关联的 execution_feedback。"""
        with get_session() as session:
            rd = RoutingDecisionRecord(task_hash="cascade_test")
            session.add(rd)
            session.flush()

            fb = ExecutionFeedbackRecord(
                routing_decision_id=rd.id,
                actual_cost_cny=0.05,
            )
            session.add(fb)

        with get_session() as session:
            rd = session.query(RoutingDecisionRecord).filter_by(task_hash="cascade_test").one()
            session.delete(rd)

        with get_session() as session:
            assert session.query(RoutingDecisionRecord).count() == 0
            assert session.query(ExecutionFeedbackRecord).count() == 0

    def test_cascade_delete_raw_sql(self):
        """raw SQL 删除 parent → DB 级 ondelete CASCADE 应清掉 child。"""
        from sqlalchemy import text

        with get_session() as session:
            rd = RoutingDecisionRecord(task_hash="cascade_raw")
            session.add(rd)
            session.flush()

            fb = ExecutionFeedbackRecord(
                routing_decision_id=rd.id,
                actual_cost_cny=0.05,
            )
            session.add(fb)

        with get_session() as session:
            session.execute(
                text("DELETE FROM routing_decisions WHERE task_hash = :h"),
                {"h": "cascade_raw"},
            )

        with get_session() as session:
            assert session.query(RoutingDecisionRecord).count() == 0
            assert session.query(ExecutionFeedbackRecord).count() == 0

    def test_multiple_feedback_per_decision(self):
        """一条决策可以有多条反馈（如重试场景）。"""
        with get_session() as session:
            rd = RoutingDecisionRecord(task_hash="multi_fb")
            session.add(rd)
            session.flush()

            for i in range(3):
                fb = ExecutionFeedbackRecord(
                    routing_decision_id=rd.id,
                    actual_cost_cny=0.01 * (i + 1),
                )
                session.add(fb)

        with get_session() as session:
            rd = session.query(RoutingDecisionRecord).filter_by(task_hash="multi_fb").one()
            assert len(rd.feedback) == 3
