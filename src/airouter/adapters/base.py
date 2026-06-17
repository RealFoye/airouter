"""模型适配器契约层：AdapterResponse + 异常体系 + BaseAdapter ABC。"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class AdapterResponse:
    """模型调用的统一返回结构。不承载错误状态，错误只通过异常传递。"""

    content: str
    input_tokens: int
    output_tokens: int
    latency_ms: int
    model: str
    raw_usage: dict | None = field(default=None)
    tool_calls: list[dict] | None = field(default=None)
    finish_reason: str | None = field(default=None)


# ── 异常体系 ──────────────────────────────────────────────────
class AdapterError(Exception):
    """适配器调用失败的基类。"""


class AdapterAuthError(AdapterError):
    """API key 无效或过期。"""


class AdapterRateLimitError(AdapterError):
    """触发速率限制。"""


class AdapterTimeoutError(AdapterError):
    """请求超时。"""


# ── 抽象基类 ──────────────────────────────────────────────────
class BaseAdapter(ABC):
    """所有适配器的抽象基类。"""

    @abstractmethod
    def chat(
        self, model: str, messages: list[dict], **kwargs
    ) -> AdapterResponse:
        """同步调用模型，返回 AdapterResponse。失败抛 AdapterError 子类。"""

    async def achat(
        self, model: str, messages: list[dict], **kwargs
    ) -> AdapterResponse:
        """异步调用，默认通过 asyncio.to_thread 包装同步方法。"""
        return await asyncio.to_thread(self.chat, model, messages, **kwargs)
