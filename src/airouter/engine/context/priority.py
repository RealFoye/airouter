"""B-1 上下文优先级框架：按层排序 + Token 预算分配 + 淘汰规则。"""

from __future__ import annotations

from dataclasses import dataclass, field

from airouter.models.enums import ContextLayer
from airouter.models.schemas import ContextBlock, estimate_tokens

# 层优先级（值越小越重要）
_LAYER_PRIORITY: dict[ContextLayer, int] = {
    ContextLayer.SYSTEM_PROMPT: 1,
    ContextLayer.TASK_DESCRIPTION: 2,
    ContextLayer.RELATED_FILES: 3,
    ContextLayer.CONVERSATION_HISTORY: 4,
    ContextLayer.TOOL_OUTPUT: 5,
    ContextLayer.AUXILIARY: 6,
}

# 受保护层（不可淘汰）
PROTECTED_LAYERS = {ContextLayer.SYSTEM_PROMPT, ContextLayer.TASK_DESCRIPTION}

# 默认 Token 预算比例
LAYER_BUDGET_RATIOS: dict[ContextLayer, float] = {
    ContextLayer.SYSTEM_PROMPT: 0.20,
    ContextLayer.TASK_DESCRIPTION: 0.25,
    ContextLayer.RELATED_FILES: 0.25,
    ContextLayer.CONVERSATION_HISTORY: 0.15,
    ContextLayer.TOOL_OUTPUT: 0.10,
    ContextLayer.AUXILIARY: 0.05,
}


@dataclass
class AssemblyResult:
    """优先级组装结果：保留块 + 淘汰块 + 操作记录。"""

    retained: list[ContextBlock]
    dropped: list[ContextBlock] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)


class PriorityAssembler:
    """按优先级组装上下文块，超预算时从低优先级开始淘汰。"""

    def __init__(self, total_budget: int = 8000):
        self.total_budget = total_budget

    def assemble(self, blocks: list[ContextBlock]) -> AssemblyResult:
        """
        1. 按 layer 排序（P1 > P2 > ... > P6）
        2. 受保护层直接保留
        3. 非保护层超预算时从最低优先级开始淘汰
        """
        if not blocks:
            return AssemblyResult(retained=[])

        # 确保 token_count 已计算
        for b in blocks:
            if b.token_count <= 0:
                b.token_count = estimate_tokens(b.content)

        # 按优先级排序
        sorted_blocks = sorted(blocks, key=lambda b: _LAYER_PRIORITY[b.layer])

        total_tokens = sum(b.token_count for b in sorted_blocks)
        if total_tokens <= self.total_budget:
            return AssemblyResult(retained=sorted_blocks)

        # 分离保护层和非保护层
        protected = [b for b in sorted_blocks if b.protected or b.layer in PROTECTED_LAYERS]
        evictable = [b for b in sorted_blocks if not b.protected and b.layer not in PROTECTED_LAYERS]

        # 保护层已占用的 token
        protected_tokens = sum(b.token_count for b in protected)
        remaining_budget = max(0, self.total_budget - protected_tokens)

        # 淘汰
        retained, dropped, actions = self._evict(evictable, remaining_budget)

        return AssemblyResult(
            retained=protected + retained,
            dropped=dropped,
            actions=actions,
        )

    def _evict(
        self, blocks: list[ContextBlock], budget: int
    ) -> tuple[list[ContextBlock], list[ContextBlock], list[str]]:
        """从最低优先级开始淘汰，直到满足预算。返回 (retained, dropped, actions)。"""
        if not blocks:
            return [], [], []

        # 按优先级从低到高排列（先淘汰 AUXILIARY）
        by_priority_desc = sorted(blocks, key=lambda b: -_LAYER_PRIORITY[b.layer])

        retained = list(blocks)
        dropped: list[ContextBlock] = []
        actions: list[str] = []

        current_tokens = sum(b.token_count for b in retained)

        for block in by_priority_desc:
            if current_tokens <= budget:
                break

            if block.layer == ContextLayer.AUXILIARY:
                # 直接丢弃
                retained.remove(block)
                dropped.append(block)
                current_tokens -= block.token_count
                actions.append(f"预算裁剪: 丢弃 AUXILIARY 块 ({block.token_count} tokens)")

            elif block.layer == ContextLayer.CONVERSATION_HISTORY:
                # 保留最近轮次（按 metadata.get("turn_index") 或截断）
                truncated = self._truncate_conversation(block)
                if truncated is not None:
                    delta = block.token_count - truncated.token_count
                    current_tokens -= delta
                    # 替换原块
                    idx = retained.index(block)
                    retained[idx] = truncated
                    # 记录被丢弃的部分
                    dropped_block = block.model_copy(
                        update={
                            "content": block.content[: len(block.content) - len(truncated.content)],
                            "token_count": block.token_count - truncated.token_count,
                        }
                    )
                    dropped.append(dropped_block)
                    actions.append(f"预算裁剪: 截断对话历史 ({delta} tokens)")

            elif block.layer == ContextLayer.TOOL_OUTPUT:
                # 保留最后 N 行
                truncated = self._truncate_tool_output(block)
                if truncated is not None:
                    delta = block.token_count - truncated.token_count
                    current_tokens -= delta
                    idx = retained.index(block)
                    retained[idx] = truncated
                    dropped_block = block.model_copy(
                        update={
                            "content": block.content[: len(block.content) - len(truncated.content)],
                            "token_count": block.token_count - truncated.token_count,
                        }
                    )
                    dropped.append(dropped_block)
                    actions.append(f"预算裁剪: 截断工具输出 ({delta} tokens)")

            elif block.layer == ContextLayer.RELATED_FILES:
                # 按大小截断（保留前半部分）
                truncated = self._truncate_file(block, budget, current_tokens)
                if truncated is not None:
                    delta = block.token_count - truncated.token_count
                    current_tokens -= delta
                    idx = retained.index(block)
                    retained[idx] = truncated
                    dropped_block = block.model_copy(
                        update={
                            "content": block.content[len(truncated.content) :],
                            "token_count": block.token_count - truncated.token_count,
                        }
                    )
                    dropped.append(dropped_block)
                    actions.append(f"预算裁剪: 截断文件内容 ({delta} tokens)")

        # 如果还是超预算，整体截断
        if current_tokens > budget and retained:
            retained, extra_dropped, extra_actions = self._global_truncate(retained, budget)
            dropped.extend(extra_dropped)
            actions.extend(extra_actions)

        return retained, dropped, actions

    def _truncate_conversation(self, block: ContextBlock) -> ContextBlock | None:
        """保留最近轮次（按 \\n\\n 分隔，保留后半部分）。"""
        turns = block.content.split("\n\n")
        if len(turns) <= 1:
            return None
        # 保留后半部分
        half = max(1, len(turns) // 2)
        kept = "\n\n".join(turns[-half:])
        new_count = estimate_tokens(kept)
        if new_count >= block.token_count:
            return None
        return block.model_copy(update={"content": kept, "token_count": new_count})

    def _truncate_tool_output(self, block: ContextBlock, max_lines: int = 30) -> ContextBlock | None:
        """保留最后 max_lines 行。"""
        lines = block.content.split("\n")
        if len(lines) <= max_lines:
            return None
        kept = "\n".join(lines[-max_lines:])
        new_count = estimate_tokens(kept)
        if new_count >= block.token_count:
            return None
        return block.model_copy(update={"content": kept, "token_count": new_count})

    def _truncate_file(
        self, block: ContextBlock, budget: int, current_tokens: int
    ) -> ContextBlock | None:
        """按预算截断文件内容（保留前半）。"""
        excess = current_tokens - budget
        if excess <= 0:
            return None
        # 保留比例
        keep_ratio = max(0.1, 1 - excess / max(1, block.token_count))
        keep_len = max(10, int(len(block.content) * keep_ratio))
        kept = block.content[:keep_len]
        new_count = estimate_tokens(kept)
        if new_count >= block.token_count:
            return None
        return block.model_copy(update={"content": kept, "token_count": new_count})

    def _global_truncate(
        self, blocks: list[ContextBlock], budget: int
    ) -> tuple[list[ContextBlock], list[ContextBlock], list[str]]:
        """最后手段：从最低优先级开始整块丢弃。"""
        sorted_blocks = sorted(blocks, key=lambda b: -_LAYER_PRIORITY[b.layer])
        retained = list(blocks)
        dropped: list[ContextBlock] = []
        actions: list[str] = []
        current = sum(b.token_count for b in retained)

        for block in sorted_blocks:
            if current <= budget:
                break
            if block in retained and block.layer not in PROTECTED_LAYERS and not block.protected:
                retained.remove(block)
                dropped.append(block)
                current -= block.token_count
                actions.append(f"预算裁剪: 全局丢弃 {block.layer.value} 块 ({block.token_count} tokens)")

        return retained, dropped, actions
