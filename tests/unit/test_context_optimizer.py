"""测试上下文工程：B-1 优先级框架 + B-2 压缩引擎。"""

from airouter.config import ContextLengthThreshold, load_compression_policy
from airouter.engine.context.compressor import (
    Compressor,
    RuleSummarizer,
    eliminate_redundancy,
    select_strategy,
)
from airouter.engine.context.priority import PriorityAssembler
from airouter.models.enums import (
    CompressionStrategy,
    ContentType,
    ContextLayer,
    RiskLevel,
)
from airouter.models.schemas import ContextBlock, InputBreakdown, estimate_tokens

# ── estimate_tokens 测试 ──────────────────────────────────


class TestEstimateTokens:
    def test_empty_string(self):
        assert estimate_tokens("") == 0

    def test_single_char(self):
        assert estimate_tokens("x") == 1

    def test_short_text(self):
        assert estimate_tokens("hi") == 1

    def test_longer_text(self):
        # "hello world" = 11 chars → ceil(11/3) = 4
        assert estimate_tokens("hello world") == 4

    def test_chinese_text(self):
        # "你好世界" = 4 chars → ceil(4/3) = 2
        assert estimate_tokens("你好世界") == 2


# ── ContextBlock 测试 ────────────────────────────────────


class TestContextBlock:
    def test_system_prompt_auto_protected(self):
        b = ContextBlock(layer=ContextLayer.SYSTEM_PROMPT, content_type=ContentType.PLAIN_TEXT, content="test")
        assert b.protected is True

    def test_task_description_auto_protected(self):
        b = ContextBlock(layer=ContextLayer.TASK_DESCRIPTION, content_type=ContentType.PLAIN_TEXT, content="test")
        assert b.protected is True

    def test_tool_output_not_protected(self):
        b = ContextBlock(layer=ContextLayer.TOOL_OUTPUT, content_type=ContentType.TOOL_OUTPUT, content="test")
        assert b.protected is False

    def test_auto_token_count(self):
        b = ContextBlock(layer=ContextLayer.AUXILIARY, content_type=ContentType.PLAIN_TEXT, content="hello world")
        assert b.token_count == estimate_tokens("hello world")

    def test_explicit_token_count_preserved(self):
        b = ContextBlock(
            layer=ContextLayer.AUXILIARY, content_type=ContentType.PLAIN_TEXT, content="hello", token_count=999
        )
        assert b.token_count == 999

    def test_empty_content_zero_tokens(self):
        b = ContextBlock(layer=ContextLayer.AUXILIARY, content_type=ContentType.PLAIN_TEXT, content="")
        assert b.token_count == 0


# ── InputBreakdown 测试 ──────────────────────────────────


class TestInputBreakdown:
    def test_stable_prefix(self):
        bd = InputBreakdown(system_prompt_tokens=100, tool_definitions_tokens=50)
        assert bd.stable_prefix == 150

    def test_total(self):
        bd = InputBreakdown(
            system_prompt_tokens=100,
            tool_definitions_tokens=50,
            fixed_context_tokens=200,
            conversation_history_tokens=300,
            dynamic_query_tokens=150,
        )
        assert bd.total == 800


# ── PriorityAssembler 测试 ───────────────────────────────


class TestPriorityAssembler:
    def test_empty_input(self):
        asm = PriorityAssembler(total_budget=1000)
        result = asm.assemble([])
        assert result.retained == []
        assert result.dropped == []

    def test_ordering(self):
        blocks = [
            ContextBlock(layer=ContextLayer.AUXILIARY, content_type=ContentType.PLAIN_TEXT, content="aux"),
            ContextBlock(layer=ContextLayer.SYSTEM_PROMPT, content_type=ContentType.PLAIN_TEXT, content="sys"),
            ContextBlock(layer=ContextLayer.TOOL_OUTPUT, content_type=ContentType.TOOL_OUTPUT, content="tool"),
        ]
        result = PriorityAssembler(total_budget=10000).assemble(blocks)
        layers = [b.layer for b in result.retained]
        assert layers.index(ContextLayer.SYSTEM_PROMPT) < layers.index(ContextLayer.TOOL_OUTPUT)
        assert layers.index(ContextLayer.TOOL_OUTPUT) < layers.index(ContextLayer.AUXILIARY)

    def test_within_budget_no_eviction(self):
        blocks = [
            ContextBlock(layer=ContextLayer.SYSTEM_PROMPT, content_type=ContentType.PLAIN_TEXT, content="x" * 30),
            ContextBlock(layer=ContextLayer.AUXILIARY, content_type=ContentType.PLAIN_TEXT, content="y" * 30),
        ]
        result = PriorityAssembler(total_budget=10000).assemble(blocks)
        assert len(result.retained) == 2
        assert len(result.dropped) == 0

    def test_auxiliary_evicted_first(self):
        blocks = [
            ContextBlock(layer=ContextLayer.SYSTEM_PROMPT, content_type=ContentType.PLAIN_TEXT, content="x" * 300),
            ContextBlock(layer=ContextLayer.RELATED_FILES, content_type=ContentType.CODE, content="y" * 300),
            ContextBlock(layer=ContextLayer.AUXILIARY, content_type=ContentType.PLAIN_TEXT, content="z" * 300),
        ]
        result = PriorityAssembler(total_budget=150).assemble(blocks)
        layers = [b.layer for b in result.retained]
        assert ContextLayer.AUXILIARY not in layers
        # 验证 dropped 追踪
        assert any(b.layer == ContextLayer.AUXILIARY for b in result.dropped)

    def test_protected_not_evicted(self):
        """System Prompt 即使超预算也不淘汰。"""
        blocks = [
            ContextBlock(layer=ContextLayer.SYSTEM_PROMPT, content_type=ContentType.PLAIN_TEXT, content="x" * 3000),
            ContextBlock(layer=ContextLayer.AUXILIARY, content_type=ContentType.PLAIN_TEXT, content="y" * 30),
        ]
        result = PriorityAssembler(total_budget=100).assemble(blocks)
        layers = [b.layer for b in result.retained]
        assert ContextLayer.SYSTEM_PROMPT in layers

    def test_conversation_truncated(self):
        """对话历史超预算时截断后半部分。"""
        conv = "\n\n".join([f"turn {i}\n用户说了一些内容\n助手回答了一些内容" for i in range(20)])
        original_tokens = estimate_tokens(conv)
        blocks = [
            ContextBlock(layer=ContextLayer.CONVERSATION_HISTORY, content_type=ContentType.CONVERSATION, content=conv),
        ]
        # 给 70% 预算，足够截断但不至于完全丢弃
        budget = int(original_tokens * 0.7)
        result = PriorityAssembler(total_budget=budget).assemble(blocks)
        assert len(result.retained) >= 1
        assert result.retained[0].token_count < original_tokens

    def test_total_budget_parameter(self):
        blocks = [
            ContextBlock(layer=ContextLayer.RELATED_FILES, content_type=ContentType.CODE, content="x" * 300),
        ]
        # 大预算：保留
        r1 = PriorityAssembler(total_budget=10000).assemble(blocks)
        assert len(r1.retained) == 1
        # 小预算：淘汰
        r2 = PriorityAssembler(total_budget=1).assemble(blocks)
        assert len(r2.retained) == 0

    def test_assembly_result_actions(self):
        """验证 AssemblyResult 包含 actions。"""
        blocks = [
            ContextBlock(layer=ContextLayer.AUXILIARY, content_type=ContentType.PLAIN_TEXT, content="x" * 300),
        ]
        result = PriorityAssembler(total_budget=1).assemble(blocks)
        assert len(result.dropped) == 1
        assert len(result.actions) == 1
        assert "预算裁剪" in result.actions[0]


# ── select_strategy 测试 ─────────────────────────────────


def _make_thresholds() -> list[ContextLengthThreshold]:
    return [
        ContextLengthThreshold(max_tokens=5000, strategy="none"),
        ContextLengthThreshold(max_tokens=10000, strategy="conservative"),
        ContextLengthThreshold(max_tokens=30000, strategy="standard"),
        ContextLengthThreshold(max_tokens=999999, strategy="aggressive"),
    ]


class TestSelectStrategy:
    def test_small_context_none(self):
        assert select_strategy(RiskLevel.LOW, 3000, _make_thresholds()) == CompressionStrategy.NONE

    def test_high_risk_caps_conservative(self):
        """HIGH risk 最高只能 CONSERVATIVE。"""
        assert select_strategy(RiskLevel.HIGH, 50000, _make_thresholds()) == CompressionStrategy.CONSERVATIVE

    def test_medium_risk_caps_standard(self):
        assert select_strategy(RiskLevel.MEDIUM, 50000, _make_thresholds()) == CompressionStrategy.STANDARD

    def test_low_risk_allows_aggressive(self):
        assert select_strategy(RiskLevel.LOW, 50000, _make_thresholds()) == CompressionStrategy.AGGRESSIVE

    def test_takes_more_conservative(self):
        """context 说 STANDARD，risk 说 AGGRESSIVE → STANDARD。"""
        # 15K tokens → standard, LOW risk → aggressive, min = standard
        assert select_strategy(RiskLevel.LOW, 15000, _make_thresholds()) == CompressionStrategy.STANDARD

    def test_yaml_lowercase_normalized(self):
        """YAML 小写 'conservative' 能正确匹配。"""
        thresholds = [ContextLengthThreshold(max_tokens=10000, strategy="conservative")]
        assert select_strategy(RiskLevel.LOW, 8000, thresholds) == CompressionStrategy.CONSERVATIVE


# ── eliminate_redundancy 测试 ─────────────────────────────


class TestEliminateRedundancy:
    def test_no_duplicates(self):
        blocks = [
            ContextBlock(layer=ContextLayer.RELATED_FILES, content_type=ContentType.CODE, content="code1"),
            ContextBlock(layer=ContextLayer.RELATED_FILES, content_type=ContentType.CODE, content="code2"),
        ]
        retained, dropped, actions = eliminate_redundancy(blocks)
        assert len(retained) == 2
        assert len(dropped) == 0

    def test_exact_duplicate_removed(self):
        blocks = [
            ContextBlock(layer=ContextLayer.RELATED_FILES, content_type=ContentType.CODE, content="same"),
            ContextBlock(layer=ContextLayer.RELATED_FILES, content_type=ContentType.CODE, content="same"),
        ]
        retained, dropped, actions = eliminate_redundancy(blocks)
        assert len(retained) == 1
        assert len(dropped) == 1
        assert len(actions) == 1

    def test_triple_duplicate_keeps_one(self):
        blocks = [
            ContextBlock(layer=ContextLayer.TOOL_OUTPUT, content_type=ContentType.TOOL_OUTPUT, content="dup"),
            ContextBlock(layer=ContextLayer.TOOL_OUTPUT, content_type=ContentType.TOOL_OUTPUT, content="dup"),
            ContextBlock(layer=ContextLayer.TOOL_OUTPUT, content_type=ContentType.TOOL_OUTPUT, content="dup"),
        ]
        retained, dropped, _ = eliminate_redundancy(blocks)
        assert len(retained) == 1
        assert len(dropped) == 2


# ── RuleSummarizer 测试 ──────────────────────────────────


class TestRuleSummarizer:
    def setup_method(self):
        self.s = RuleSummarizer()

    # PLAIN_TEXT
    def test_plain_text_conservative(self):
        text = "line1\n\n\n\nline2"
        result = self.s.summarize(text, ContentType.PLAIN_TEXT, CompressionStrategy.CONSERVATIVE)
        assert "\n\n\n" not in result

    def test_plain_text_aggressive(self):
        text = "line1\n\n\n\nline2"
        result = self.s.summarize(text, ContentType.PLAIN_TEXT, CompressionStrategy.AGGRESSIVE)
        assert "\n\n\n" not in result

    # CONVERSATION
    def test_conversation_conservative_only_blank_lines(self):
        text = "turn1\nturn2\n\n\nturn3"
        result = self.s.summarize(text, ContentType.CONVERSATION, CompressionStrategy.CONSERVATIVE)
        assert "\n\n\n" not in result
        assert "turn1" in result

    def test_conversation_standard_keeps_keywords(self):
        text = "hello\nworld\n这是一个重要决定\nfoo\nbar"
        result = self.s.summarize(text, ContentType.CONVERSATION, CompressionStrategy.STANDARD)
        assert "决定" in result
        assert "hello" in result  # 首行
        assert "bar" in result  # 末行

    def test_conversation_aggressive_only_keywords(self):
        text = "hello\nworld\n这是一个重要决定\nfoo\nbar"
        result = self.s.summarize(text, ContentType.CONVERSATION, CompressionStrategy.AGGRESSIVE)
        assert "决定" in result
        # AGGRESSIVE 不保留首末行
        assert "hello" not in result
        assert "bar" not in result

    def test_conversation_keyword_case_insensitive(self):
        """关键词 TODO（大写）在 lower() 后仍能匹配。"""
        text = "hello\nthis is a TODO item\nworld"
        result = self.s.summarize(text, ContentType.CONVERSATION, CompressionStrategy.AGGRESSIVE)
        assert "TODO" in result

    # TOOL_OUTPUT
    def test_tool_output_conservative_no_truncation(self):
        lines = [f"line_{i}" for i in range(100)]
        text = "\n".join(lines)
        result = self.s.summarize(text, ContentType.TOOL_OUTPUT, CompressionStrategy.CONSERVATIVE)
        assert estimate_tokens(result) == estimate_tokens(text)

    def test_tool_output_standard_keeps_tail_20(self):
        lines = [f"line_{i}" for i in range(100)]
        text = "\n".join(lines)
        result = self.s.summarize(text, ContentType.TOOL_OUTPUT, CompressionStrategy.STANDARD)
        result_lines = result.split("\n")
        assert len(result_lines) <= 25  # command + up to ~20 tail + a few

    def test_tool_output_aggressive_keeps_tail_5(self):
        lines = [f"line_{i}" for i in range(100)]
        text = "\n".join(lines)
        result = self.s.summarize(text, ContentType.TOOL_OUTPUT, CompressionStrategy.AGGRESSIVE)
        result_lines = result.split("\n")
        assert len(result_lines) <= 10  # command + 5 tail + a few

    def test_tool_output_keeps_error_lines(self):
        text = "$ make test\nfile1 ok\nfile2 ok\nerror: build failed\nmore output\nmore"
        result = self.s.summarize(text, ContentType.TOOL_OUTPUT, CompressionStrategy.AGGRESSIVE)
        assert "error" in result.lower()

    # ERROR_LOG
    def test_error_log_keeps_traceback(self):
        text = "Traceback (most recent call last):\n  File 'x.py', line 10\n    foo()\nValueError: bad value"
        result = self.s.summarize(text, ContentType.ERROR_LOG, CompressionStrategy.AGGRESSIVE)
        assert "Traceback" in result or "Error" in result

    # CODE
    def test_code_conservative_keeps_all(self):
        text = "import os\n\ndef foo():\n    return 1\n\nclass Bar:\n    pass"
        result = self.s.summarize(text, ContentType.CODE, CompressionStrategy.CONSERVATIVE)
        assert result == text

    def test_code_standard_keeps_signatures(self):
        text = "import os\nimport sys\n\ndef foo(x, y):\n    return x + y\n\nclass Bar:\n    def method(self):\n        pass"
        result = self.s.summarize(text, ContentType.CODE, CompressionStrategy.STANDARD)
        assert "import os" in result
        assert "def foo" in result
        assert "class Bar" in result

    def test_code_aggressive_signatures_only(self):
        text = "import os\nimport sys\n\ndef foo(x, y):\n    return x + y\n\nclass Bar:\n    def method(self):\n        pass"
        result = self.s.summarize(text, ContentType.CODE, CompressionStrategy.AGGRESSIVE)
        assert "import os" in result
        assert "def foo" in result
        # 方法体不应该出现
        assert "return x + y" not in result

    # DOCUMENTATION
    def test_doc_conservative_keeps_all(self):
        text = "# Title\n\nSome paragraph.\n\n- item1\n- item2"
        result = self.s.summarize(text, ContentType.DOCUMENTATION, CompressionStrategy.CONSERVATIVE)
        assert result == text

    def test_doc_standard_keeps_headings_and_lists(self):
        text = "# Title\n\nSome paragraph.\n\n- item1\n- item2\n\nMore text"
        result = self.s.summarize(text, ContentType.DOCUMENTATION, CompressionStrategy.STANDARD)
        assert "# Title" in result
        assert "- item1" in result

    def test_doc_aggressive_headings_only(self):
        text = "# Title\n\nSome paragraph.\n\n- item1\n- item2\n\n## Section\n\nMore text"
        result = self.s.summarize(text, ContentType.DOCUMENTATION, CompressionStrategy.AGGRESSIVE)
        assert "# Title" in result
        assert "## Section" in result
        assert "- item1" not in result


# ── Compressor 测试 ───────────────────────────────────────


class TestCompressor:
    def setup_method(self):
        self.policy = load_compression_policy()
        self.compressor = Compressor(self.policy)

    def test_empty_blocks(self):
        result = self.compressor.compress([])
        assert result.original_tokens == 0
        assert result.compressed_tokens == 0
        assert result.strategy == CompressionStrategy.NONE

    def test_none_strategy_still_deduplicates(self):
        """NONE 策略仍然做冗余剔除。"""
        blocks = [
            ContextBlock(layer=ContextLayer.RELATED_FILES, content_type=ContentType.CODE, content="same code"),
            ContextBlock(layer=ContextLayer.RELATED_FILES, content_type=ContentType.CODE, content="same code"),
        ]
        result = self.compressor.compress(blocks, risk_level=RiskLevel.LOW)
        # < 5K tokens → NONE strategy
        assert result.strategy == CompressionStrategy.NONE
        assert len(result.blocks) == 1
        assert len(result.dropped_blocks) == 1

    def test_protected_not_compressed(self):
        """SYSTEM_PROMPT 不传 protected 也不被压缩。"""
        sys_content = "你是AI助手" * 1000  # ~3333 tokens
        blocks = [
            ContextBlock(layer=ContextLayer.SYSTEM_PROMPT, content_type=ContentType.PLAIN_TEXT, content=sys_content),
            ContextBlock(
                layer=ContextLayer.CONVERSATION_HISTORY,
                content_type=ContentType.CONVERSATION,
                content="普通对话" * 5000,
            ),
        ]
        result = self.compressor.compress(blocks, risk_level=RiskLevel.LOW)
        sys_block = [b for b in result.blocks if b.layer == ContextLayer.SYSTEM_PROMPT]
        assert len(sys_block) == 1
        assert sys_block[0].content == sys_content

    def test_reduction_rate_calculated(self):
        blocks = [
            ContextBlock(
                layer=ContextLayer.CONVERSATION_HISTORY,
                content_type=ContentType.CONVERSATION,
                content=("用户: 你好\n助手: 你好\n\n" * 200),
            ),
        ]
        result = self.compressor.compress(blocks, risk_level=RiskLevel.LOW)
        if result.strategy != CompressionStrategy.NONE:
            assert result.reduction_rate > 0
            assert result.original_tokens > result.compressed_tokens

    def test_per_layer_tokens_populated(self):
        blocks = [
            ContextBlock(layer=ContextLayer.SYSTEM_PROMPT, content_type=ContentType.PLAIN_TEXT, content="x" * 100),
            ContextBlock(
                layer=ContextLayer.CONVERSATION_HISTORY,
                content_type=ContentType.CONVERSATION,
                content="y" * 20000,
            ),
        ]
        result = self.compressor.compress(blocks, risk_level=RiskLevel.LOW)
        assert "SYSTEM_PROMPT" in result.per_layer_tokens
        assert "CONVERSATION_HISTORY" in result.per_layer_tokens

    def test_applied_actions_populated(self):
        blocks = [
            ContextBlock(
                layer=ContextLayer.CONVERSATION_HISTORY,
                content_type=ContentType.CONVERSATION,
                content=("轮次\n用户问\n助手答\n\n" * 300),
            ),
        ]
        result = self.compressor.compress(blocks, risk_level=RiskLevel.LOW)
        if result.strategy != CompressionStrategy.NONE:
            assert len(result.applied_actions) > 0

    def test_high_risk_conservative(self):
        """HIGH risk → CONSERVATIVE，代码不被压缩。"""
        code = "import os\ndef foo():\n    return 1\n" * 500
        blocks = [
            ContextBlock(layer=ContextLayer.RELATED_FILES, content_type=ContentType.CODE, content=code),
        ]
        result = self.compressor.compress(blocks, risk_level=RiskLevel.HIGH)
        assert result.strategy == CompressionStrategy.CONSERVATIVE

    def test_total_budget_triggers_assembler(self):
        """指定 total_budget 时调用 PriorityAssembler。"""
        blocks = [
            ContextBlock(layer=ContextLayer.SYSTEM_PROMPT, content_type=ContentType.PLAIN_TEXT, content="x" * 300),
            ContextBlock(
                layer=ContextLayer.AUXILIARY, content_type=ContentType.PLAIN_TEXT, content="y" * 30000
            ),
        ]
        result = self.compressor.compress(blocks, risk_level=RiskLevel.LOW, total_budget=500)
        # AUXILIARY 应该被淘汰
        aux_blocks = [b for b in result.blocks if b.layer == ContextLayer.AUXILIARY]
        assert len(aux_blocks) == 0

    def test_strategy_case_normalization(self):
        """YAML 小写 strategy 能正确匹配。"""
        thresholds = [ContextLengthThreshold(max_tokens=10000, strategy="conservative")]
        s = select_strategy(RiskLevel.LOW, 8000, thresholds)
        assert s == CompressionStrategy.CONSERVATIVE

    def test_none_strategy_with_total_budget(self):
        """NONE 策略 + total_budget → 仍执行预算裁剪。"""
        blocks = [
            ContextBlock(layer=ContextLayer.AUXILIARY, content_type=ContentType.PLAIN_TEXT, content="x" * 300),
        ]
        result = self.compressor.compress(blocks, risk_level=RiskLevel.LOW, total_budget=1)
        assert result.strategy == CompressionStrategy.NONE
        assert result.compressed_tokens == 0
        assert len(result.dropped_blocks) == 1
        assert len(result.applied_actions) >= 1

    def test_budget_drop_tracking(self):
        """预算裁剪的 dropped 和 actions 被记录到 CompressionResult。"""
        blocks = [
            ContextBlock(layer=ContextLayer.SYSTEM_PROMPT, content_type=ContentType.PLAIN_TEXT, content="x" * 100),
            ContextBlock(layer=ContextLayer.AUXILIARY, content_type=ContentType.PLAIN_TEXT, content="y" * 3000),
        ]
        result = self.compressor.compress(blocks, risk_level=RiskLevel.LOW, total_budget=50)
        # AUXILIARY 被淘汰
        assert any(b.layer == ContextLayer.AUXILIARY for b in result.dropped_blocks)
        # actions 里有预算裁剪记录
        assert any("预算裁剪" in a for a in result.applied_actions)


# ── 集成测试 ──────────────────────────────────────────────


class TestContextIntegration:
    def test_full_pipeline(self):
        """完整管线：压缩 + 预算裁剪。"""
        blocks = [
            ContextBlock(
                layer=ContextLayer.SYSTEM_PROMPT, content_type=ContentType.PLAIN_TEXT, content="系统提示" * 100
            ),
            ContextBlock(
                layer=ContextLayer.CONVERSATION_HISTORY,
                content_type=ContentType.CONVERSATION,
                content=("用户: 你好\n助手: 你好\n\n" * 100),
            ),
            ContextBlock(
                layer=ContextLayer.TOOL_OUTPUT,
                content_type=ContentType.TOOL_OUTPUT,
                content=("\n".join([f"file_{i}.txt" for i in range(100)])),
            ),
        ]
        compressor = Compressor(load_compression_policy())
        result = compressor.compress(blocks, risk_level=RiskLevel.LOW)
        assert result.original_tokens > 0
        assert result.compressed_tokens <= result.original_tokens

    def test_risk_level_switches_strategy(self):
        """不同 risk_level 产生不同策略。"""
        blocks = [
            ContextBlock(
                layer=ContextLayer.CONVERSATION_HISTORY,
                content_type=ContentType.CONVERSATION,
                content=("用户问\n助手答\n\n" * 500),
            ),
        ]
        compressor = Compressor(load_compression_policy())

        r_high = compressor.compress(blocks, risk_level=RiskLevel.HIGH)
        r_low = compressor.compress(blocks, risk_level=RiskLevel.LOW)

        # HIGH 应该比 LOW 压缩更少（或相等）
        assert r_high.compressed_tokens >= r_low.compressed_tokens

    def test_redundancy_before_compression(self):
        """冗余剔除在压缩之前运行。"""
        dup_content = "重复的内容" * 100
        blocks = [
            ContextBlock(
                layer=ContextLayer.RELATED_FILES, content_type=ContentType.CODE, content=dup_content
            ),
            ContextBlock(
                layer=ContextLayer.RELATED_FILES, content_type=ContentType.CODE, content=dup_content
            ),
            ContextBlock(
                layer=ContextLayer.CONVERSATION_HISTORY,
                content_type=ContentType.CONVERSATION,
                content="普通对话" * 200,
            ),
        ]
        compressor = Compressor(load_compression_policy())
        result = compressor.compress(blocks, risk_level=RiskLevel.LOW)
        # 重复块应该被移除
        assert len(result.dropped_blocks) >= 1
        # 最终 blocks 里只有一份 dup
        code_blocks = [b for b in result.blocks if b.layer == ContextLayer.RELATED_FILES]
        assert len(code_blocks) == 1


class TestStrategyOverride:
    """Compressor strategy_override 参数测试。"""

    def setup_method(self):
        self.compressor = Compressor(load_compression_policy())
        # 构造有压缩空间的 conversation 块（含关键词触发压缩）
        lines = []
        for i in range(200):
            lines.append(f"User: 问题{i}")
            lines.append(f"Assistant: 结论是答案{i}，需要注意错误处理")
        self.blocks = [
            ContextBlock(
                layer=ContextLayer.CONVERSATION_HISTORY,
                content_type=ContentType.CONVERSATION,
                content="\n".join(lines),
            ),
        ]

    def test_override_aggressive_overrides_auto(self):
        """strategy_override=AGGRESSIVE 覆盖自动选择（短文本 auto 可能是 NONE）。"""
        result = self.compressor.compress(
            self.blocks, risk_level=RiskLevel.MEDIUM, strategy_override=CompressionStrategy.AGGRESSIVE
        )
        assert result.strategy == CompressionStrategy.AGGRESSIVE
        # AGGRESSIVE 应该有压缩效果
        assert result.compressed_tokens < result.original_tokens

    def test_override_none_uses_auto(self):
        """strategy_override=None 走正常 select_strategy。"""
        result_auto = self.compressor.compress(self.blocks, risk_level=RiskLevel.MEDIUM)
        result_none = self.compressor.compress(
            self.blocks, risk_level=RiskLevel.MEDIUM, strategy_override=None
        )
        assert result_auto.strategy == result_none.strategy
        assert result_auto.compressed_tokens == result_none.compressed_tokens
