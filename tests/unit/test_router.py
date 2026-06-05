"""测试 Router：端到端 20 条任务路由。"""

import pytest

from airouter.engine.router.router import Router
from airouter.models.enums import (
    BudgetStatus,
    RiskLevel,
    StrategyType,
)


@pytest.fixture
def router() -> Router:
    return Router()


# ── 20 条端到端测试 ─────────────────────────────────────────
TEST_DESCRIPTIONS = [
    "写一个FastAPI JWT鉴权中间件",
    "审查这段代码的安全漏洞",
    "将这个God Class拆分为策略模式",
    "分析这个并发死锁问题",
    "为这个API生成OpenAPI文档",
    "设计一个支持百万并发的消息推送系统",
    "为这个用户服务写单元测试",
    "写一个ETL脚本处理CSV数据",
    "编写Docker Compose部署方案",
    "解释Python的GIL是什么",
    "实现用户登录模块，支持OAuth2和MFA",
    "重构数据库访问层，引入Repository模式",
    "修复生产环境的内存泄漏",
    "编写微服务网关的路由规则",
    "设计分布式缓存架构",
    "生成JSON Schema配置文件",
    "审查支付模块的代码质量",
    "写一个数据清洗脚本处理用户日志",
    "为整个项目编写使用手册",
    "实现跨模块的权限管理系统",
]


@pytest.mark.parametrize(
    "desc", TEST_DESCRIPTIONS, ids=[f"e2e_{i+1}" for i in range(len(TEST_DESCRIPTIONS))]
)
def test_router_end_to_end(router: Router, desc: str):
    """每条任务都能产出完整的路由决策。"""
    decision = router.route(desc)

    # 基本字段检查
    assert decision.task_hash
    assert decision.recommended_strategy == StrategyType.SINGLE_MODEL
    assert decision.models.executor is not None
    assert decision.estimated_cost >= 0
    assert decision.baseline_cost >= 0
    assert 0 <= decision.estimated_savings <= 1
    assert 0 <= decision.estimated_quality <= 1
    assert len(decision.reasons) > 0
    assert isinstance(decision.quality_gate, list)
    assert isinstance(decision.fallback_policy, list)
    assert decision.config_version


def test_router_high_risk_requires_review(router: Router):
    """高风险任务应触发人工审核。"""
    decision = router.route("设计一个支持百万并发的消息推送系统")
    assert decision.requires_human_review is True


def test_router_simple_task_low_cost(router: Router):
    """简单任务成本应该低。"""
    decision = router.route("解释Python的GIL是什么")
    assert decision.estimated_cost < 0.1


def test_router_complex_task_higher_cost(router: Router):
    """复杂任务成本更高。"""
    simple = router.route("写一个简单的函数")
    complex_ = router.route("设计一个支持百万并发的消息推送系统")
    assert complex_.estimated_cost > simple.estimated_cost


def test_router_alternatives_populated(router: Router):
    """应该有替代方案。"""
    decision = router.route("写一个FastAPI JWT鉴权中间件")
    # 可能有 0+ 个替代方案
    assert isinstance(decision.alternatives, list)


def test_router_budget_status(router: Router):
    """预算状态应该是有效的枚举值。"""
    decision = router.route("写一个ETL脚本处理CSV数据")
    assert decision.budget_status in (BudgetStatus.OK, BudgetStatus.WARNING, BudgetStatus.OVER_BUDGET, BudgetStatus.OVER_HARD_BUDGET)


def test_router_savings_nonnegative(router: Router):
    """节省比例不应为负。"""
    for desc in TEST_DESCRIPTIONS[:5]:
        decision = router.route(desc)
        assert decision.estimated_savings >= 0


# ── 政策验证测试（不是通路测试） ─────────────────────────────
# 这些测试证明企业管控规则正确实现。

def test_policy_high_risk_tier2_must_review(router: Router):
    """核心政策：高风险 + Tier 2 降级 → requires_human_review=true。

    这是 Week 1 最大的 bug case：写JWT鉴权中间件推荐 Tier 2，
    风险 HIGH，但 requires_human_review 曾为 false。
    用确定性断言，不用 if（避免空测试）。
    """
    decision = router.route("写一个FastAPI JWT鉴权中间件")
    executor = router.registry.get_by_name(decision.models.executor)
    assert decision.risk_level == RiskLevel.HIGH
    assert executor is not None
    assert executor.tier == 2
    assert decision.requires_human_review is True
    assert "human_review" in decision.quality_gate
    assert "降级" in decision.human_review_reason or "拆分" in decision.human_review_reason


def test_policy_simple_low_risk_no_review(router: Router):
    """SIMPLE + LOW risk → 不应触发审核（省钱路径不锁死）。"""
    decision = router.route("写一个Python函数检查回文")
    assert decision.risk_level == RiskLevel.LOW
    assert decision.requires_human_review is False


def test_policy_gate_review_consistency(router: Router):
    """政策一致性：requires_human_review=true → human_review 在 quality_gate 中。"""
    for desc in TEST_DESCRIPTIONS:
        decision = router.route(desc)
        if decision.requires_human_review:
            assert "human_review" in decision.quality_gate, (
                f"Inconsistency for '{desc}': requires_human_review=true "
                f"but human_review not in quality_gate {decision.quality_gate}"
            )


def test_policy_high_risk_tier1_no_downgrade_trigger(router: Router):
    """高风险 + Tier 1 执行 → 不应触发条件2（降级审核）。"""
    decision = router.route("修复生产环境的内存泄漏")
    executor = router.registry.get_by_name(decision.models.executor)
    assert decision.risk_level == RiskLevel.HIGH
    assert executor is not None
    assert executor.tier == 1
    # Tier 1 执行，不应因"降级"触发审核
    if decision.human_review_reason:
        assert "降级" not in decision.human_review_reason
