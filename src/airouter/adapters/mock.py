"""MockAdapter：完全确定性的模拟适配器。

同输入 → 同 content、同 input_tokens、同 output_tokens、同 latency_ms。
用于测试、Benchmark 回归和 API 不可用时的降级。
"""

from __future__ import annotations

import hashlib

from airouter.adapters.base import AdapterResponse, BaseAdapter


class MockAdapter(BaseAdapter):
    """不调用任何 API，返回确定性模拟结果。"""

    def chat(
        self, model: str, messages: list[dict], **kwargs
    ) -> AdapterResponse:
        last_user_msg = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                last_user_msg = msg.get("content", "")
                break

        content = f"[Mock] {model}: {last_user_msg[:80]}"

        # token 估算：字符数 // 4（粗略模拟中英文混合）
        total_chars = sum(len(m.get("content", "")) for m in messages)
        input_tokens = max(1, total_chars // 4)
        output_tokens = max(1, len(content) // 4)

        # latency：基于输入 hash 映射到 100-500ms，确定性
        digest = hashlib.md5(
            f"{model}:{last_user_msg}".encode()
        ).hexdigest()
        latency_ms = int(digest[:8], 16) % 401 + 100

        return AdapterResponse(
            content=content,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
            model=model,
            raw_usage={
                "prompt_tokens": input_tokens,
                "completion_tokens": output_tokens,
            },
        )
