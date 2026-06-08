"""测试 PromptOptimizer 优化引擎。"""

import pytest

from airouter.config import ModelCacheConfig
from airouter.engine.optimize.optimizer import PromptOptimizer
from airouter.models.enums import StrategyType
from airouter.models.schemas import (
    InputBreakdown,
    ModelAssignment,
    OptimizationSuggestion,
    estimate_tokens,
)


@pytest.fixture
def optimizer():
    return PromptOptimizer()


# ── 行分类测试 ────────────────────────────────────────────


class TestClassifyPromptLines:
    def test_keywords_classified_correctly(self, optimizer):
        """含 system/tool/conversation 关键词的行归入正确分类。"""
        prompt = "你是一个AI助手\nTool: search_function\nUser: 你好\n请帮我写一个函数"
        classified = optimizer._classify_prompt_lines(prompt)

        assert len(classified["system_prompt"]) > 0
        assert any("你是" in line for line in classified["system_prompt"])
        assert len(classified["tool_definitions"]) > 0
        assert any("Tool" in line for line in classified["tool_definitions"])
        assert len(classified["conversation_history"]) > 0
        assert any("User" in line for line in classified["conversation_history"])
        assert len(classified["dynamic_query"]) > 0
        assert any("请帮我写" in line for line in classified["dynamic_query"])

    def test_code_fence_goes_to_fixed_context(self, optimizer):
        """code fence 内的代码全部归入 fixed_context。"""
        prompt = "请审查代码\n```python\ndef foo():\n    return 42\n```\n请给出建议"
        classified = optimizer._classify_prompt_lines(prompt)

        # code fence 内的行应该在 fixed_context
        assert len(classified["fixed_context"]) >= 3  # ``` + def + return + ```
        # 代码行不应该在 dynamic_query
        assert not any("def foo" in line for line in classified["dynamic_query"])

    def test_plain_text_goes_to_dynamic_query(self, optimizer):
        """纯文本（无关键词）全部归入 dynamic_query。"""
        prompt = "请帮我写一个排序算法\n要求时间复杂度O(nlogn)\n输入是整数数组"
        classified = optimizer._classify_prompt_lines(prompt)

        assert len(classified["system_prompt"]) == 0
        assert len(classified["tool_definitions"]) == 0
        assert len(classified["conversation_history"]) == 0
        assert len(classified["dynamic_query"]) == 3


# ── InputBreakdown 测试 ───────────────────────────────────


class TestInputBreakdown:
    def test_total_equals_estimate_tokens(self, optimizer):
        """total 属性 == estimate_tokens(prompt)（global_total 对齐）。"""
        prompt = "你是一个代码助手\nUser: 写一个函数\n请帮我实现快速排序算法"
        classified = optimizer._classify_prompt_lines(prompt)
        breakdown = optimizer._analyze_breakdown(prompt, classified)

        assert breakdown.total == estimate_tokens(prompt)

    def test_dynamic_query_is_remainder(self, optimizer):
        """dynamic_query_tokens = max(0, global_total - accounted)。"""
        prompt = "你是一个AI助手\nUser: 你好\n请帮我做一件事"
        classified = optimizer._classify_prompt_lines(prompt)
        breakdown = optimizer._analyze_breakdown(prompt, classified)

        accounted = (
            breakdown.system_prompt_tokens
            + breakdown.tool_definitions_tokens
            + breakdown.fixed_context_tokens
            + breakdown.conversation_history_tokens
        )
        expected = max(0, estimate_tokens(prompt) - accounted)
        assert breakdown.dynamic_query_tokens == expected

    def test_mixed_prompt_has_all_parts(self, optimizer):
        """混合 prompt 各分项 > 0。"""
        prompt = (
            "你是一个代码审查助手\n"
            "Tool: search_code\n"
            "```\ndef main():\n    pass\n```\n"
            "User: 请检查安全性\n"
            "请给出详细的审查意见"
        )
        classified = optimizer._classify_prompt_lines(prompt)
        breakdown = optimizer._analyze_breakdown(prompt, classified)

        assert breakdown.system_prompt_tokens > 0
        assert breakdown.tool_definitions_tokens > 0
        assert breakdown.fixed_context_tokens > 0
        assert breakdown.conversation_history_tokens > 0


# ── 缓存建议测试 ──────────────────────────────────────────


class TestCacheSuggestion:
    def test_single_turn_no_savings(self, optimizer):
        """SINGLE_TURN 场景无缓存收益。"""
        breakdown = InputBreakdown(
            system_prompt_tokens=5000, tool_definitions_tokens=2000, dynamic_query_tokens=500,
        )
        models = ModelAssignment(executor="qwen3.7-max")
        suggestion = optimizer._suggest_cache(models, breakdown, "SINGLE_TURN", 1, 1.0)
        assert suggestion.estimated_savings == 0

    def test_multi_turn_with_caching_model(self, optimizer):
        """AGENT_MULTI_TURN + 支持缓存模型 + turns > 1 → savings > 0。"""
        breakdown = InputBreakdown(
            system_prompt_tokens=5000, tool_definitions_tokens=2000, dynamic_query_tokens=500,
        )
        # qwen3.7-max 支持缓存（stable_prefix=7000 > min_prefix=1024）
        models = ModelAssignment(executor="qwen3.7-max")
        suggestion = optimizer._suggest_cache(models, breakdown, "AGENT_MULTI_TURN", 10, 1.0)
        assert suggestion.estimated_savings > 0
        assert suggestion.category == "缓存"

    def test_no_caching_model(self, optimizer, monkeypatch):
        """模型不支持缓存 → savings = 0。"""
        breakdown = InputBreakdown(
            system_prompt_tokens=5000, tool_definitions_tokens=2000, dynamic_query_tokens=500,
        )
        base_model = optimizer.registry.get_by_name("deepseek-v4-pro")
        no_cache_model = base_model.model_copy(
            update={"cache": ModelCacheConfig(supports_prompt_caching=False)}
        )
        monkeypatch.setattr(optimizer.registry, "get_by_name", lambda name: no_cache_model)

        models = ModelAssignment(executor="deepseek-v4-pro")
        suggestion = optimizer._suggest_cache(models, breakdown, "AGENT_MULTI_TURN", 10, 1.0)
        assert suggestion.estimated_savings == 0

    def test_stable_prefix_too_short(self, optimizer):
        """stable_prefix < cache_min_prefix_tokens → savings = 0。"""
        breakdown = InputBreakdown(
            system_prompt_tokens=10, tool_definitions_tokens=5, dynamic_query_tokens=5000,
        )
        # stable_prefix = 15 < cache_min_prefix_tokens = 1024
        models = ModelAssignment(executor="qwen3.7-max")
        suggestion = optimizer._suggest_cache(models, breakdown, "AGENT_MULTI_TURN", 10, 1.0)
        assert suggestion.estimated_savings == 0


# ── 压缩建议测试 ──────────────────────────────────────────


class TestCompressionSuggestion:
    def _make_compressible_prompt(self):
        """构造有压缩空间的 prompt（含 conversation + tool output）。"""
        lines = ["你是一个AI助手"]
        # 大量对话历史（含关键词触发压缩）
        for i in range(50):
            lines.append(f"User: 问题{i}是什么")
            lines.append(f"Assistant: 结论是答案{i}")
        # 工具输出
        lines.append("$ ls -la")
        for i in range(30):
            lines.append(f"file_{i}.txt  1024 bytes")
        lines.append("Exit code: 0")
        return "\n".join(lines)

    def test_three_strategy_comparison(self, optimizer):
        """3 策略对比：CONSERVATIVE <= STANDARD <= AGGRESSIVE 的 reduction_rate。"""
        prompt = self._make_compressible_prompt()
        classified = optimizer._classify_prompt_lines(prompt)
        breakdown = optimizer._analyze_breakdown(prompt, classified)
        blocks = optimizer._build_context_blocks(classified)

        from airouter.models.enums import RiskLevel

        features_mock = type("F", (), {"risk_level": RiskLevel.LOW})()
        suggestion = optimizer._suggest_compression(blocks, features_mock, breakdown, 0.02, 1.0)

        comparison = suggestion.details.get("comparison", {})
        assert len(comparison) == 3
        # 应该有 3 个策略
        assert "CONSERVATIVE" in comparison
        assert "STANDARD" in comparison
        assert "AGGRESSIVE" in comparison

        # reduction_rate 递增（CONSERVATIVE <= STANDARD <= AGGRESSIVE）
        con_rate = comparison["CONSERVATIVE"]["reduction_rate"]
        std_rate = comparison["STANDARD"]["reduction_rate"]
        agg_rate = comparison["AGGRESSIVE"]["reduction_rate"]
        assert con_rate <= std_rate <= agg_rate

    def test_conversation_has_compression(self, optimizer):
        """含 conversation_history 的 prompt 有压缩效果。"""
        prompt = self._make_compressible_prompt()
        classified = optimizer._classify_prompt_lines(prompt)
        breakdown = optimizer._analyze_breakdown(prompt, classified)
        blocks = optimizer._build_context_blocks(classified)

        from airouter.models.enums import RiskLevel

        features_mock = type("F", (), {"risk_level": RiskLevel.LOW})()
        suggestion = optimizer._suggest_compression(blocks, features_mock, breakdown, 0.02, 1.0)

        # AGGRESSIVE 应该有压缩
        agg = suggestion.details["comparison"]["AGGRESSIVE"]
        assert agg["reduction_rate"] > 0

    def test_short_text_no_savings(self, optimizer):
        """纯短文本 → 压缩 savings ≈ 0。"""
        prompt = "请帮我写一个函数"
        classified = optimizer._classify_prompt_lines(prompt)
        breakdown = optimizer._analyze_breakdown(prompt, classified)
        blocks = optimizer._build_context_blocks(classified)

        from airouter.models.enums import RiskLevel

        features_mock = type("F", (), {"risk_level": RiskLevel.MEDIUM})()
        suggestion = optimizer._suggest_compression(blocks, features_mock, breakdown, 0.02, 1.0)

        # 短文本应该几乎没有压缩
        assert suggestion.estimated_savings < 0.01


# ── 降级建议测试 ──────────────────────────────────────────


class TestDowngradeSuggestion:
    def test_tier1_has_downgrade(self, optimizer):
        """当前 Tier 1 + 有 Tier 2 → savings > 0。"""
        features = optimizer.router.analyzer.extract_features("写一个简单的排序函数")
        features = features.model_copy(update={"estimated_input_tokens": 5000})

        models = ModelAssignment(executor="qwen3.7-max")  # Tier 1
        current_cost = optimizer._estimate_current_cost(StrategyType.SINGLE_MODEL, models, features)

        suggestion = optimizer._suggest_downgrade(features, StrategyType.SINGLE_MODEL, models, current_cost)
        assert suggestion.estimated_savings > 0
        assert suggestion.category == "降级"

    def test_tier3_no_downgrade(self, optimizer):
        """当前已是 Tier 3 → savings = 0。"""
        features = optimizer.router.analyzer.extract_features("写一个函数")
        features = features.model_copy(update={"estimated_input_tokens": 1000})

        models = ModelAssignment(executor="deepseek-v4-flash")  # Tier 3
        current_cost = optimizer._estimate_current_cost(StrategyType.SINGLE_MODEL, models, features)

        suggestion = optimizer._suggest_downgrade(features, StrategyType.SINGLE_MODEL, models, current_cost)
        assert suggestion.estimated_savings == 0

    def test_high_risk_no_downgrade_allowed(self, optimizer):
        """P1-1: EXPERT+HIGH 任务 routing_rules 只允许 Tier 1 → 降级建议 savings=0。"""
        features = optimizer.router.analyzer.extract_features(
            "设计一个支持百万并发的支付系统架构，涉及权限、鉴权、安全和数据库迁移"
        )
        # 保持 Router 给的 estimated_input_tokens（filter_candidates 用这个过滤 context window）
        models = ModelAssignment(executor="qwen3.7-max")  # Tier 1
        current_cost = optimizer._estimate_current_cost(StrategyType.SINGLE_MODEL, models, features)

        suggestion = optimizer._suggest_downgrade(features, StrategyType.SINGLE_MODEL, models, current_cost)
        # filter_candidates 会过滤 allowed_tiers，EXPERT+HIGH 只允许 Tier 1，不应建议降级
        assert suggestion.estimated_savings == 0


# ── Plan-Execute 建议测试 ─────────────────────────────────


class TestPlanExecuteSuggestion:
    def test_already_plan_execute_no_savings(self, optimizer):
        """已是 PLAN_EXECUTE → savings = 0。"""
        features = optimizer.router.analyzer.extract_features("设计一个分布式系统")
        features = features.model_copy(update={"estimated_input_tokens": 20000})

        models = ModelAssignment(planner="qwen3.7-max", executor="qwen3.7-plus")
        suggestion = optimizer._suggest_plan_execute(
            features, StrategyType.PLAN_EXECUTE, models, 1.0,
        )
        assert suggestion.estimated_savings == 0

    def test_no_subtasks_no_savings(self, optimizer):
        """没有 subtasks → savings = 0。"""
        features = optimizer.router.analyzer.extract_features("写一个函数")
        # 清除 subtasks
        features = features.model_copy(update={"subtasks": [], "estimated_input_tokens": 1000})

        models = ModelAssignment(executor="qwen3.7-max")
        suggestion = optimizer._suggest_plan_execute(
            features, StrategyType.SINGLE_MODEL, models, 1.0,
        )
        assert suggestion.estimated_savings == 0

    def test_one_subtask_no_savings(self, optimizer):
        """P1-2: 只有 1 个 subtask → savings = 0（分层开销不划算）。"""
        features = optimizer.router.analyzer.extract_features("写一个函数")
        features = features.model_copy(update={"subtasks": ["实现排序"], "estimated_input_tokens": 1000})

        models = ModelAssignment(executor="qwen3.7-max")
        suggestion = optimizer._suggest_plan_execute(
            features, StrategyType.SINGLE_MODEL, models, 1.0,
        )
        assert suggestion.estimated_savings == 0


# ── OptimizeResult 汇总测试 ───────────────────────────────


class TestOptimizeResult:
    def test_result_fields_correct(self, optimizer):
        """optimized_cost 不为负，total_savings <= current_cost，warnings 非空。"""
        result = optimizer.optimize(
            prompt="你是一个代码审查助手\nUser: 请检查安全性\nAssistant: 存在SQL注入风险\n" * 10,
            scenario="AGENT_MULTI_TURN",
            expected_turns=5,
        )

        assert result.optimized_cost >= 0
        assert result.total_estimated_savings <= result.current_cost
        assert len(result.warnings) > 0
        assert result.current_strategy in list(StrategyType)

    def test_model_override_single_model(self, optimizer):
        """传 --model 时 current_strategy = SINGLE_MODEL。"""
        result = optimizer.optimize(
            prompt="写一个函数",
            model_name="qwen3.7-max",
        )
        assert result.current_strategy == StrategyType.SINGLE_MODEL
        assert result.current_models.executor == "qwen3.7-max"

    def test_router_escalate_shows_warning(self, optimizer):
        """P2-1: Router escalate (requires_human_review + empty models) → warning 包含'人工审核'。"""
        # 这个任务会触发 Router escalate（高复杂度 + 需要人工审核）
        result = optimizer.optimize(
            prompt="构建WebSocket实时通知系统，包含连接管理、消息广播、离线队列",
        )
        # 如果 Router escalate 了，warnings 里应该有"人工审核"
        if result.current_models.executor is None and result.current_models.planner is None:
            assert any("人工审核" in w for w in result.warnings)

    def test_exclusive_savings_takes_max(self, optimizer):
        """P2-3: 降级和分层互斥，合计只取 max — 直接调用生产代码 _summarize_savings。"""
        downgrade = OptimizationSuggestion(
            category="降级", title="降级", description="",
            estimated_savings=2.0, savings_percentage=0.4,
        )
        pe = OptimizationSuggestion(
            category="分层", title="分层", description="",
            estimated_savings=3.0, savings_percentage=0.6,
        )
        cache = OptimizationSuggestion(
            category="缓存", title="缓存", description="",
            estimated_savings=0.5, savings_percentage=0.1,
        )

        current_cost = 10.0
        total_savings, optimized_cost, total_pct = optimizer._summarize_savings(
            [downgrade, pe, cache], current_cost,
        )

        # 正交: 缓存 0.5; 互斥: max(2.0, 3.0) = 3.0; 合计 3.5
        assert total_savings == 3.5
        assert optimized_cost == 6.5
        assert total_pct == pytest.approx(0.35)

        # 如果互斥错误地求和：2.0 + 3.0 + 0.5 = 5.5，证明互斥确实取 max
        assert total_savings < 5.5

    def test_summarize_savings_cap_at_current_cost(self, optimizer):
        """savings 不能超过 current_cost（cap）。"""
        big = OptimizationSuggestion(
            category="降级", title="", description="",
            estimated_savings=100.0, savings_percentage=1.0,
        )
        total_savings, optimized_cost, _ = optimizer._summarize_savings([big], 10.0)
        assert total_savings == 10.0
        assert optimized_cost == 0.0

    def test_summarize_savings_zero_cost(self, optimizer):
        """current_cost=0 → total_pct=0, 不报错。"""
        s = OptimizationSuggestion(
            category="压缩", title="", description="",
            estimated_savings=1.0, savings_percentage=0.0,
        )
        total_savings, optimized_cost, total_pct = optimizer._summarize_savings([s], 0.0)
        assert total_savings == 0.0
        assert optimized_cost == 0.0
        assert total_pct == 0.0

    def test_gate_approval_warning_with_models(self, optimizer):
        """P1: requires_human_review=True + 有候选模型 → warning 包含'人工审核'，降级/分层标 requires_approval。"""
        # 高风险复杂任务会触发 requires_human_review=True
        result = optimizer.optimize(
            prompt="重构支付核心服务：拆分订单模块、修改扣款逻辑、数据库迁移、权限校验、并发一致性、线上无损发布",
            model_name="qwen3.7-max",
        )
        # 如果有降级或分层建议，它们的 details 应标 requires_approval=True
        exclusive_items = [s for s in result.suggestions if s.category in ("降级", "分层")]
        for item in exclusive_items:
            assert item.details.get("requires_approval") is True, (
                f"{item.category} 建议应标记 requires_approval=True"
            )
        # 如果 requires_human_review=True，warnings 应包含"人工审核"
        if any(s.details.get("requires_approval") for s in result.suggestions):
            assert any("人工审核" in w for w in result.warnings)

    def test_approval_warning_when_router_ok_but_suggestion_needs_approval(self, optimizer):
        """P1: Router 不需要审批，但建议后方案需要 → warnings 仍提示审批。

        场景：BUG_ANALYSIS + HIGH risk，Router 推荐 Tier 1（不需要审批），
        但降级到 Tier 2 后 Gate 条件 2 触发。
        """
        result = optimizer.optimize(
            prompt="修复生产环境支付扣款重复的问题，涉及数据库事务、幂等和回滚",
            model_name="qwen3.7-max",
        )
        has_approval = any(s.details.get("requires_approval") for s in result.suggestions)
        if has_approval:
            assert any("审批" in w for w in result.warnings), (
                f"有 requires_approval=True 的建议但 warnings 无审批提示: {result.warnings}"
            )

    def test_engine_validates_model_name(self, optimizer):
        """P2: Engine 层直接调用时，无效 model_name 应 raise ValueError。"""
        with pytest.raises(ValueError, match="不存在"):
            optimizer.optimize("写一个函数", model_name="nonexistent-model-xyz")

    def test_engine_validates_scenario(self, optimizer):
        """P2: Engine 层无效 scenario 应 raise ValueError。"""
        with pytest.raises(ValueError, match="未知场景"):
            optimizer.optimize("写一个函数", scenario="BAD_SCENARIO")

    def test_engine_validates_turns(self, optimizer):
        """P2: Engine 层 expected_turns < 1 应 raise ValueError。"""
        with pytest.raises(ValueError, match="expected_turns"):
            optimizer.optimize("写一个函数", expected_turns=-5)

    def test_downgrade_approval_based_on_suggestion_not_router(self, optimizer):
        """P1: requires_approval 基于建议后方案重新判断，不继承 Router 原始 decision。

        场景：Router 原始推荐是 Tier 1（不需要审批），但降级建议到 Tier 2
        后按 Gate 条件"高风险 + Tier 2"应该需要审批。
        """
        # BUG_ANALYSIS + HIGH risk → Router 推荐 Tier 1（不需要审批）
        # 但降级到 Tier 2 后 Gate 条件 2 触发
        result = optimizer.optimize(
            prompt="修复生产环境支付扣款重复的问题，涉及数据库事务、幂等和回滚",
            model_name="qwen3.7-max",
        )
        # 如果有降级建议，requires_approval 应该基于建议后的 Tier 2 模型判断
        downgrade_items = [s for s in result.suggestions if s.category == "降级"]
        for item in downgrade_items:
            suggested_tier = item.details.get("suggested_tier")
            if suggested_tier and suggested_tier > 1:
                # HIGH risk + Tier > 1 → Gate 条件 2 触发
                assert item.details.get("requires_approval") is True, (
                    f"降级到 Tier {suggested_tier} 应触发审批"
                )
