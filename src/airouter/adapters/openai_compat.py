"""OpenAI 兼容适配器：统一调用 DeepSeek/Qwen/GLM。

使用 openai Python SDK，所有国内模型都走 OpenAI-compatible API。
支持 client 注入，方便测试和后续加 retry/timeout。
"""

from __future__ import annotations

import logging
import time
from typing import Any

from openai import (
    APIError,
    APITimeoutError,
    AuthenticationError,
    OpenAI,
    RateLimitError,
)

from airouter.adapters.base import (
    AdapterAuthError,
    AdapterError,
    AdapterRateLimitError,
    AdapterResponse,
    AdapterTimeoutError,
    BaseAdapter,
)

logger = logging.getLogger(__name__)


class OpenAICompatAdapter(BaseAdapter):
    """通过 OpenAI SDK 调用兼容 API 的模型。"""

    def __init__(
        self,
        api_base: str,
        api_key: str,
        client: OpenAI | None = None,
    ):
        self._api_base = api_base
        self._api_key = api_key
        self._client = client or OpenAI(base_url=api_base, api_key=api_key)

    def chat(
        self, model: str, messages: list[dict], **kwargs: Any
    ) -> AdapterResponse:
        start = time.perf_counter()
        try:
            response = self._client.chat.completions.create(
                model=model,
                messages=messages,  # type: ignore[arg-type]
                **kwargs,
            )
        except AuthenticationError as e:
            raise AdapterAuthError(f"API key 无效: {e}") from e
        except RateLimitError as e:
            raise AdapterRateLimitError(f"速率限制: {e}") from e
        except APITimeoutError as e:
            raise AdapterTimeoutError(f"请求超时: {e}") from e
        except APIError as e:
            raise AdapterError(f"API 调用失败: {e}") from e

        elapsed_ms = int((time.perf_counter() - start) * 1000)

        if not response.choices:
            raise AdapterError(
                f"Invalid OpenAI-compatible response: choices is empty (model={model})"
            )

        choice = response.choices[0]
        usage = response.usage

        return AdapterResponse(
            content=choice.message.content or "",
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
            latency_ms=elapsed_ms,
            model=model,
            raw_usage=usage.model_dump() if usage else None,
        )
