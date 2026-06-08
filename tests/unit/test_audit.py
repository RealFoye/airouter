"""测试审计引擎：Collector、Aggregator、Detector、Attribution。"""

from datetime import datetime, timedelta

from airouter.engine.audit.aggregator import Aggregator
from airouter.engine.audit.attribution import Attribution
from airouter.engine.audit.collector import ConsumptionRecord
from airouter.engine.audit.detector import Detector


def _make_record(
    user_id="alice",
    department="backend",
    project_id="proj-alpha",
    client_type="claude-code",
    task_type="CODE_GENERATION",
    complexity="SIMPLE",
    risk_level="LOW",
    selected_model="deepseek-v4-flash",
    input_tokens=2000,
    output_tokens=500,
    cost_cny=0.01,
    task_hash="abc123",
    timestamp=None,
    is_actual=False,
) -> ConsumptionRecord:
    if timestamp is None:
        timestamp = datetime.now()
    return ConsumptionRecord(
        user_id=user_id,
        department=department,
        project_id=project_id,
        client_type=client_type,
        task_type=task_type,
        complexity=complexity,
        risk_level=risk_level,
        selected_model=selected_model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_cny=cost_cny,
        task_hash=task_hash,
        timestamp=timestamp,
        is_actual=is_actual,
    )


# ── Aggregator ────────────────────────────────────────────────
class TestAggregator:
    def test_empty_records(self):
        agg = Aggregator()
        result = agg.aggregate([], "user")
        assert result == []

    def test_group_by_user(self):
        records = [
            _make_record(user_id="alice", cost_cny=10.0),
            _make_record(user_id="alice", cost_cny=20.0),
            _make_record(user_id="bob", cost_cny=15.0),
        ]
        agg = Aggregator()
        result = agg.aggregate(records, "user")

        assert len(result) == 2
        assert result[0].key == "alice"
        assert result[0].total_cost == 30.0
        assert result[0].total_calls == 2
        assert result[1].key == "bob"
        assert result[1].total_cost == 15.0

    def test_group_by_model(self):
        records = [
            _make_record(selected_model="qwen3.7-max", cost_cny=10.0),
            _make_record(selected_model="qwen3.7-max", cost_cny=20.0),
            _make_record(selected_model="deepseek-v4-flash", cost_cny=5.0),
        ]
        agg = Aggregator()
        result = agg.aggregate(records, "model")

        assert len(result) == 2
        assert result[0].key == "qwen3.7-max"
        assert result[0].total_cost == 30.0

    def test_percentage_calculation(self):
        records = [
            _make_record(user_id="alice", cost_cny=75.0),
            _make_record(user_id="bob", cost_cny=25.0),
        ]
        agg = Aggregator()
        result = agg.aggregate(records, "user")

        assert result[0].percentage == 75.0
        assert result[1].percentage == 25.0

    def test_sorted_by_cost_desc(self):
        records = [
            _make_record(user_id="alice", cost_cny=10.0),
            _make_record(user_id="bob", cost_cny=30.0),
            _make_record(user_id="charlie", cost_cny=20.0),
        ]
        agg = Aggregator()
        result = agg.aggregate(records, "user")

        assert [r.key for r in result] == ["bob", "charlie", "alice"]


# ── Detector: P1 高配模型滥用 ────────────────────────────────
class TestDetectorP1:
    def test_simple_task_with_tier1(self):
        records = [
            _make_record(
                user_id="alice",
                complexity="SIMPLE",
                selected_model="qwen3.7-max",
                cost_cny=1.0,
            )
            for _ in range(5)
        ]
        detector = Detector()
        patterns = detector.detect(records)

        p1 = [p for p in patterns if p.pattern_type == "HIGH_TIER_ABUSE"]
        assert len(p1) == 1
        assert p1[0].occurrence_count == 5
        assert p1[0].scope == "user"
        assert p1[0].scope_value == "alice"

    def test_moderate_task_with_tier1_low_risk(self):
        records = [
            _make_record(
                user_id="bob",
                complexity="MODERATE",
                risk_level="LOW",
                selected_model="qwen3.7-max",
                cost_cny=1.0,
            )
            for _ in range(3)
        ]
        detector = Detector()
        patterns = detector.detect(records)

        p1 = [p for p in patterns if p.pattern_type == "HIGH_TIER_ABUSE"]
        assert len(p1) == 1
        assert p1[0].occurrence_count == 3

    def test_moderate_task_with_tier1_high_risk_not_flagged(self):
        """MODERATE + HIGH risk 用 Tier 1 不算浪费。"""
        records = [
            _make_record(
                user_id="charlie",
                complexity="MODERATE",
                risk_level="HIGH",
                selected_model="qwen3.7-max",
                cost_cny=1.0,
            )
            for _ in range(3)
        ]
        detector = Detector()
        patterns = detector.detect(records)

        p1 = [p for p in patterns if p.pattern_type == "HIGH_TIER_ABUSE"]
        assert len(p1) == 0

    def test_severity_high(self):
        records = [
            _make_record(
                user_id="alice",
                complexity="SIMPLE",
                selected_model="qwen3.7-max",
                cost_cny=1.0,
            )
            for _ in range(60)
        ]
        detector = Detector()
        patterns = detector.detect(records)

        p1 = [p for p in patterns if p.pattern_type == "HIGH_TIER_ABUSE"]
        assert len(p1) == 1
        assert p1[0].severity == "High"


# ── Detector: P2 重复调用 ─────────────────────────────────────
class TestDetectorP2:
    def test_duplicate_calls_within_10_minutes(self):
        base_time = datetime.now()
        records = [
            _make_record(
                user_id="alice",
                project_id="proj-alpha",
                task_hash="dup123",
                timestamp=base_time,
                cost_cny=1.0,
            ),
            _make_record(
                user_id="alice",
                project_id="proj-alpha",
                task_hash="dup123",
                timestamp=base_time + timedelta(minutes=5),
                cost_cny=1.0,
            ),
        ]
        detector = Detector()
        patterns = detector.detect(records)

        p2 = [p for p in patterns if p.pattern_type == "DUPLICATE_CALLS"]
        assert len(p2) == 1
        assert p2[0].occurrence_count == 1  # 重复的那条

    def test_duplicate_calls_over_10_minutes_not_flagged(self):
        base_time = datetime.now()
        records = [
            _make_record(
                user_id="alice",
                project_id="proj-alpha",
                task_hash="dup123",
                timestamp=base_time,
                cost_cny=1.0,
            ),
            _make_record(
                user_id="alice",
                project_id="proj-alpha",
                task_hash="dup123",
                timestamp=base_time + timedelta(minutes=15),
                cost_cny=1.0,
            ),
        ]
        detector = Detector()
        patterns = detector.detect(records)

        p2 = [p for p in patterns if p.pattern_type == "DUPLICATE_CALLS"]
        assert len(p2) == 0


# ── Detector: P3 过长上下文 ──────────────────────────────────
class TestDetectorP3:
    def test_overlong_context(self):
        # 中位数 2000，阈值 max(10000, 2000*2) = 10000
        records = [
            _make_record(user_id="alice", input_tokens=2000, cost_cny=0.5),
            _make_record(user_id="alice", input_tokens=2000, cost_cny=0.5),
            _make_record(user_id="alice", input_tokens=15000, cost_cny=3.0),  # 超过阈值
        ]
        detector = Detector()
        patterns = detector.detect(records)

        p3 = [p for p in patterns if p.pattern_type == "OVERLONG_CONTEXT"]
        assert len(p3) == 1
        assert p3[0].occurrence_count == 1

    def test_context_within_threshold_not_flagged(self):
        records = [
            _make_record(user_id="alice", input_tokens=2000, cost_cny=0.5),
            _make_record(user_id="alice", input_tokens=2000, cost_cny=0.5),
            _make_record(user_id="alice", input_tokens=5000, cost_cny=1.0),  # 未超过 10000
        ]
        detector = Detector()
        patterns = detector.detect(records)

        p3 = [p for p in patterns if p.pattern_type == "OVERLONG_CONTEXT"]
        assert len(p3) == 0


# ── Detector: P4 可降级未降级 ────────────────────────────────
class TestDetectorP4:
    def test_downgradable_not_downgraded(self):
        # COMPLEX + LOW risk，最便宜的可用 tier 应该是 2（从 routing_rules）
        # 实际用了 tier 1（qwen3.7-max）
        # P4 检测条件是 actual_tier < cheapest_tier - 1，所以 tier 1 < 2 - 1 = 1 不成立
        # 因此这个测试验证 P4 不会误触发
        records = [
            _make_record(
                user_id="alice",
                complexity="COMPLEX",
                risk_level="LOW",
                selected_model="qwen3.7-max",
                cost_cny=1.0,
            )
            for _ in range(5)
        ]
        detector = Detector()
        patterns = detector.detect(records)

        p4_list = [p for p in patterns if p.pattern_type == "DOWNGRADABLE_NOT_DOWNGRADED"]
        # 不应该触发，因为 tier 1 并不比 cheapest_tier 2 贵 2 级以上
        assert len(p4_list) == 0

    def test_downgradable_triggers_for_moderate(self):
        # MODERATE + LOW risk，最便宜的可用 tier 应该是 3（从 routing_rules: [2, 3]）
        # 实际用了 tier 1（qwen3.7-max）
        # P4 条件：actual_tier(1) < cheapest_tier(3) - 1 = 2 → 1 < 2 → True
        # 应该触发 P4
        records = [
            _make_record(
                user_id="bob",
                complexity="MODERATE",
                risk_level="LOW",
                selected_model="qwen3.7-max",
                cost_cny=1.0,
            )
            for _ in range(5)
        ]
        detector = Detector()
        patterns = detector.detect(records)

        p4_list = [p for p in patterns if p.pattern_type == "DOWNGRADABLE_NOT_DOWNGRADED"]
        # 应该触发：tier 1 比 cheapest tier 3 贵 2 级
        assert len(p4_list) == 1
        assert p4_list[0].occurrence_count == 5


# ── Detector: P5 缓存机会未利用 ─────────────────────────────
class TestDetectorP5:
    def test_cache_opportunity_missed(self):
        # 相同 task_hash 多次出现，模型支持 caching，input tokens > cache_min_prefix_tokens
        # qwen3.7-max 支持 caching，cache_min_prefix_tokens = 1024
        records = [
            _make_record(
                user_id="alice",
                task_hash="cache123",
                selected_model="qwen3.7-max",  # 支持 caching
                input_tokens=2000,  # > 1024
                cost_cny=1.0,
            )
            for _ in range(3)
        ]
        detector = Detector()
        patterns = detector.detect(records)

        p5_list = [p for p in patterns if p.pattern_type == "CACHE_OPPORTUNITY_MISSED"]
        # 应该检测到 P5：3 次相同 task_hash + qwen3.7-max 支持 caching + input > 1024
        # occurrence_count 是"有多少个 task_hash 可以利用缓存"，不是重复调用次数
        assert len(p5_list) >= 1
        assert p5_list[0].occurrence_count == 1  # 1 个 task_hash 有缓存机会


# ── Attribution ────────────────────────────────────────────────
class TestAttribution:
    def test_empty_records(self):
        attr = Attribution()
        result = attr.analyze([])

        assert result["total_cost"] == 0.0
        assert result["total_calls"] == 0
        assert result["by_user"] == []
        assert result["top_waste_patterns"] == []

    def test_basic_attribution(self):
        records = [
            _make_record(user_id="alice", cost_cny=10.0),
            _make_record(user_id="alice", cost_cny=20.0),
            _make_record(user_id="bob", cost_cny=15.0),
        ]
        attr = Attribution()
        result = attr.analyze(records)

        assert result["total_cost"] == 45.0
        assert result["total_calls"] == 3
        assert len(result["by_user"]) == 2
        assert result["by_user"][0].key == "alice"
        assert result["by_user"][0].total_cost == 30.0

    def test_heavy_users_detection(self):
        records = [
            _make_record(user_id="alice", cost_cny=35.0),  # 70%
            _make_record(user_id="bob", cost_cny=10.0),
            _make_record(user_id="charlie", cost_cny=5.0),
        ]
        attr = Attribution()
        result = attr.analyze(records)

        assert "alice" in result["heavy_users"]

    def test_total_estimated_savings(self):
        # 注入一些 P1 浪费
        records = [
            _make_record(
                user_id="alice",
                complexity="SIMPLE",
                selected_model="qwen3.7-max",
                cost_cny=10.0,
            )
            for _ in range(5)
        ]
        attr = Attribution()
        result = attr.analyze(records)

        assert result["total_estimated_savings"] > 0.0
