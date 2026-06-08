"""B-2 上下文压缩引擎：冗余剔除 + 规则摘要化 + 策略分级。"""

from __future__ import annotations

import hashlib
import re

from airouter.config import CompressionPolicyConfig, ContextLengthThreshold, load_compression_policy
from airouter.engine.context.priority import PROTECTED_LAYERS, PriorityAssembler
from airouter.models.enums import CompressionStrategy, ContentType, RiskLevel
from airouter.models.schemas import CompressionResult, ContextBlock, estimate_tokens

# ── 策略选择 ──────────────────────────────────────────────

# risk_level → 策略上限
_RISK_STRATEGY_CAP: dict[RiskLevel, CompressionStrategy] = {
    RiskLevel.HIGH: CompressionStrategy.CONSERVATIVE,
    RiskLevel.MEDIUM: CompressionStrategy.STANDARD,
    RiskLevel.LOW: CompressionStrategy.AGGRESSIVE,
}

# 策略严格度排序（索引越大越激进）
_STRATEGY_ORDER: list[CompressionStrategy] = [
    CompressionStrategy.NONE,
    CompressionStrategy.CONSERVATIVE,
    CompressionStrategy.STANDARD,
    CompressionStrategy.AGGRESSIVE,
]


def select_strategy(
    risk_level: RiskLevel,
    total_tokens: int,
    thresholds: list[ContextLengthThreshold],
) -> CompressionStrategy:
    """
    1. 根据 total_tokens 匹配 threshold → strategy（YAML 小写 → 枚举大写）
    2. 根据 risk_level 确定上限
    3. 取更保守的那个
    """
    # 从 threshold 获取策略（按 max_tokens 升序排列，取第一个 >= total_tokens 的）
    sorted_thresholds = sorted(thresholds, key=lambda t: t.max_tokens)
    context_strategy = CompressionStrategy.NONE
    for t in sorted_thresholds:
        if total_tokens <= t.max_tokens:
            # YAML 里是小写 "none"/"conservative" 等
            context_strategy = CompressionStrategy(t.strategy.upper())
            break

    # risk_level 上限
    risk_cap = _RISK_STRATEGY_CAP.get(risk_level, CompressionStrategy.STANDARD)

    # 取更保守的（ORDER 中更靠前的）
    ctx_idx = _STRATEGY_ORDER.index(context_strategy)
    risk_idx = _STRATEGY_ORDER.index(risk_cap)
    return _STRATEGY_ORDER[min(ctx_idx, risk_idx)]


# ── 冗余剔除 ──────────────────────────────────────────────


def eliminate_redundancy(blocks: list[ContextBlock]) -> tuple[list[ContextBlock], list[ContextBlock], list[str]]:
    """
    检测完全重复的 content（相同 hash）→ 只保留一份。
    返回 (retained, dropped, actions)。
    """
    seen_hashes: dict[str, int] = {}  # hash → index of first occurrence
    retained: list[ContextBlock] = []
    dropped: list[ContextBlock] = []
    actions: list[str] = []

    for block in blocks:
        h = hashlib.md5(block.content.encode()).hexdigest()
        if h in seen_hashes:
            dropped.append(block)
            actions.append(f"冗余剔除: 移除重复块 (layer={block.layer.value})")
        else:
            seen_hashes[h] = len(retained)
            retained.append(block)

    return retained, dropped, actions


# ── 规则摘要器 ────────────────────────────────────────────


class RuleSummarizer:
    """6 种上下文类型的规则摘要。"""

    # 对话关键词
    _CONVERSATION_KEYWORDS = {"决定", "结论", "错误", "todo", "修复", "fix", "error", "conclusion", "注意", "warning"}

    def summarize(self, text: str, content_type: ContentType, strategy: CompressionStrategy) -> str:
        """分发到对应的摘要方法。"""
        if strategy == CompressionStrategy.NONE:
            return text
        dispatch = {
            ContentType.PLAIN_TEXT: self._summarize_plain_text,
            ContentType.CONVERSATION: self._summarize_conversation,
            ContentType.TOOL_OUTPUT: self._summarize_tool_output,
            ContentType.ERROR_LOG: self._summarize_error_log,
            ContentType.CODE: self._summarize_code,
            ContentType.DOCUMENTATION: self._summarize_documentation,
        }
        fn = dispatch.get(content_type, self._summarize_plain_text)
        return fn(text, strategy)

    # ── PLAIN_TEXT：只去连续空行 ──

    def _summarize_plain_text(self, text: str, strategy: CompressionStrategy) -> str:
        return re.sub(r"\n{3,}", "\n\n", text)

    # ── CONVERSATION ──

    def _summarize_conversation(self, text: str, strategy: CompressionStrategy) -> str:
        if strategy == CompressionStrategy.CONSERVATIVE:
            return re.sub(r"\n{3,}", "\n\n", text)

        lines = text.split("\n")
        if not lines:
            return text

        kept: list[str] = []

        if strategy == CompressionStrategy.STANDARD:
            # STANDARD: 首末句 + 关键词句
            kept.append(lines[0])
            for line in lines[1:-1]:
                if self._has_keyword(line):
                    kept.append(line)
            if len(lines) > 1:
                kept.append(lines[-1])
        else:  # AGGRESSIVE: 只保留关键词句
            for line in lines:
                if self._has_keyword(line):
                    kept.append(line)

        return "\n".join(kept) if kept else text

    def _has_keyword(self, line: str) -> bool:
        lower = line.lower()
        return any(kw in lower for kw in self._CONVERSATION_KEYWORDS)

    # ── TOOL_OUTPUT ──

    def _summarize_tool_output(self, text: str, strategy: CompressionStrategy) -> str:
        if strategy == CompressionStrategy.CONSERVATIVE:
            return re.sub(r"\n{3,}", "\n\n", text)

        lines = text.split("\n")
        if not lines:
            return text

        # 命令（首行）、退出码行、错误行
        important: list[str] = []
        if lines:
            important.append(lines[0])  # 命令

        for i, line in enumerate(lines):
            lower = line.lower().strip()
            if any(kw in lower for kw in ("exit code", "error", "failed", "traceback", "exception")):
                if line not in important:
                    important.append(line)

        # 最后 N 行
        if strategy == CompressionStrategy.STANDARD:
            tail_n = 20
        else:  # AGGRESSIVE
            tail_n = 5

        tail = lines[-tail_n:] if len(lines) > tail_n else lines
        result_lines = important.copy()
        for line in tail:
            if line not in result_lines:
                result_lines.append(line)

        return "\n".join(result_lines)

    # ── ERROR_LOG ──

    def _summarize_error_log(self, text: str, strategy: CompressionStrategy) -> str:
        lines = text.split("\n")
        if not lines:
            return text

        # 所有策略都保留关键行
        important: list[str] = []
        for line in lines:
            lower = line.strip().lower()
            if any(kw in lower for kw in ("traceback", "error", "exception", "file \"", "line ", "raise")):
                important.append(line)

        if strategy == CompressionStrategy.AGGRESSIVE:
            # 只留首尾各 3 行
            head = lines[:3]
            tail = lines[-3:] if len(lines) > 3 else []
            result = head + important + tail
        elif strategy == CompressionStrategy.STANDARD:
            # 首 5 + 尾 5 + 关键行
            head = lines[:5]
            tail = lines[-5:] if len(lines) > 5 else []
            result = head + important + tail
        else:  # CONSERVATIVE
            result = lines  # 保留全部

        # 去重保序
        seen: set[str] = set()
        deduped: list[str] = []
        for line in result:
            if line not in seen:
                seen.add(line)
                deduped.append(line)

        return "\n".join(deduped)

    # ── CODE ──

    def _summarize_code(self, text: str, strategy: CompressionStrategy) -> str:
        if strategy == CompressionStrategy.CONSERVATIVE:
            return text

        lines = text.split("\n")
        if not lines:
            return text

        kept: list[str] = []
        for line in lines:
            stripped = line.strip()
            # import 语句
            if stripped.startswith(("import ", "from ")):
                kept.append(line)
            # 函数签名 (def/class)
            elif re.match(r"^\s*(def |class |async def )", line):
                kept.append(line)
            # 注释
            elif stripped.startswith(("#", "//", "/*", "*", '"""', "'''")):
                if strategy == CompressionStrategy.STANDARD:
                    kept.append(line)
            # 装饰器
            elif stripped.startswith("@"):
                kept.append(line)

        if not kept:
            return text  # 没匹配到任何结构，保留原文
        return "\n".join(kept)

    # ── DOCUMENTATION ──

    def _summarize_documentation(self, text: str, strategy: CompressionStrategy) -> str:
        if strategy == CompressionStrategy.CONSERVATIVE:
            return text

        lines = text.split("\n")
        if not lines:
            return text

        kept: list[str] = []
        for line in lines:
            stripped = line.strip()
            # 标题 (# / ## / ###)
            if stripped.startswith("#"):
                kept.append(line)
            # 列表项 (- / * / 1.)
            elif re.match(r"^\s*[-*]\s", line) or re.match(r"^\s*\d+\.\s", line):
                if strategy == CompressionStrategy.STANDARD:
                    kept.append(line)
            # 包含数字/限制/条件的句子
            elif strategy == CompressionStrategy.STANDARD and re.search(r"\d+", stripped):
                kept.append(line)
            # AGGRESSIVE: 只保留标题

        if not kept:
            return text
        return "\n".join(kept)


# ── Compressor 主类 ───────────────────────────────────────


class Compressor:
    """上下文压缩引擎。"""

    def __init__(self, policy: CompressionPolicyConfig | None = None):
        self.policy = policy or load_compression_policy()
        self.summarizer = RuleSummarizer()

    def compress(
        self,
        blocks: list[ContextBlock],
        risk_level: RiskLevel = RiskLevel.MEDIUM,
        total_budget: int | None = None,
        strategy_override: CompressionStrategy | None = None,
    ) -> CompressionResult:
        """
        执行管线：
        1. 记录 original_tokens
        2. 冗余剔除（永远先跑）
        3. select_strategy
        4. NONE → 跳过摘要/截断
        5. 非保护层摘要/截断
        6. 可选 PriorityAssembler 预算裁剪
        7. 构建 CompressionResult
        """
        if not blocks:
            return CompressionResult(
                strategy=CompressionStrategy.NONE,
                original_tokens=0,
                compressed_tokens=0,
                reduction_rate=0.0,
                blocks=[],
                per_layer_tokens={},
            )

        # 确保 token_count 已计算
        for b in blocks:
            if b.token_count <= 0:
                b.token_count = estimate_tokens(b.content)

        # 1. 记录原始 token
        original_tokens = sum(b.token_count for b in blocks)

        # 记录每层原始分布
        per_layer: dict[str, dict[str, int]] = {}
        for b in blocks:
            key = b.layer.value
            if key not in per_layer:
                per_layer[key] = {"original": 0, "compressed": 0}
            per_layer[key]["original"] += b.token_count

        # 2. 冗余剔除
        all_actions: list[str] = []
        all_dropped: list[ContextBlock] = []
        working_blocks, redundancy_dropped, redundancy_actions = eliminate_redundancy(blocks)
        all_dropped.extend(redundancy_dropped)
        all_actions.extend(redundancy_actions)

        # 3. 选策略
        current_tokens = sum(b.token_count for b in working_blocks)
        if strategy_override is not None:
            strategy = strategy_override
        else:
            strategy = select_strategy(risk_level, current_tokens, self.policy.context_length_thresholds)

        # 4. NONE → 跳过摘要/截断，但仍执行预算裁剪
        if strategy != CompressionStrategy.NONE:
            # 5. 非保护层摘要/截断
            compressed_blocks: list[ContextBlock] = []
            for block in working_blocks:
                if block.protected or block.layer in PROTECTED_LAYERS:
                    compressed_blocks.append(block)
                    continue

                new_content = self.summarizer.summarize(block.content, block.content_type, strategy)

                # TOOL_OUTPUT 额外截断（CONSERVATIVE 不截断）
                if block.content_type == ContentType.TOOL_OUTPUT and strategy != CompressionStrategy.CONSERVATIVE:
                    max_lines = 20 if strategy == CompressionStrategy.STANDARD else 5
                    lines = new_content.split("\n")
                    if len(lines) > max_lines:
                        new_content = "\n".join(lines[-max_lines:])

                new_tokens = estimate_tokens(new_content)
                if new_tokens < block.token_count:
                    all_actions.append(
                        f"摘要压缩: {block.layer.value}/{block.content_type.value} "
                        f"{block.token_count}→{new_tokens} tokens ({strategy.value})"
                    )

                compressed_blocks.append(
                    block.model_copy(update={"content": new_content, "token_count": new_tokens})
                )
        else:
            compressed_blocks = working_blocks

        # 6. 可选 PriorityAssembler 预算裁剪
        if total_budget is not None:
            assembler = PriorityAssembler(total_budget=total_budget)
            assembly_result = assembler.assemble(compressed_blocks)
            compressed_blocks = assembly_result.retained
            all_dropped.extend(assembly_result.dropped)
            all_actions.extend(assembly_result.actions)

        # 7. 构建结果
        warnings: list[str] = []
        protected_tokens = sum(
            b.token_count for b in compressed_blocks if b.protected or b.layer in PROTECTED_LAYERS
        )
        if total_budget and protected_tokens > total_budget:
            warnings.append(
                f"保护层占用 {protected_tokens} tokens 超过预算 {total_budget}"
            )

        return self._build_result(
            strategy=strategy,
            blocks=compressed_blocks,
            original_tokens=original_tokens,
            per_layer=per_layer,
            applied_actions=all_actions,
            dropped_blocks=all_dropped,
            warnings=warnings,
            total_budget=total_budget,
        )

    def _build_result(
        self,
        strategy: CompressionStrategy,
        blocks: list[ContextBlock],
        original_tokens: int,
        per_layer: dict[str, dict[str, int]],
        applied_actions: list[str],
        dropped_blocks: list[ContextBlock],
        warnings: list[str],
        total_budget: int | None,
    ) -> CompressionResult:
        compressed_tokens = sum(b.token_count for b in blocks)

        # 更新 per_layer compressed 分布
        for b in blocks:
            key = b.layer.value
            if key not in per_layer:
                per_layer[key] = {"original": 0, "compressed": 0}
            per_layer[key]["compressed"] += b.token_count

        reduction_rate = (
            (original_tokens - compressed_tokens) / original_tokens if original_tokens > 0 else 0.0
        )

        return CompressionResult(
            strategy=strategy,
            original_tokens=original_tokens,
            compressed_tokens=compressed_tokens,
            reduction_rate=reduction_rate,
            blocks=blocks,
            per_layer_tokens=per_layer,
            applied_actions=applied_actions,
            dropped_blocks=dropped_blocks,
            warnings=warnings,
        )
