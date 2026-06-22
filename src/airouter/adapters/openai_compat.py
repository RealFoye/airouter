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
        request_kwargs = self._normalize_kwargs(model, kwargs)
        try:
            response = self._client.chat.completions.create(
                model=model,
                messages=messages,  # type: ignore[arg-type]
                **request_kwargs,
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

        content = choice.message.content or ""
        finish_reason = choice.finish_reason

        # Detect reasoning-token starvation (e.g. deepseek-v4-flash).
        # When reasoning_tokens consume most of max_tokens, actual content
        # output is truncated and finish_reason="length".
        reasoning_tokens = 0
        reasoning_starved = False
        if usage:
            usage_dict = usage.model_dump()
            details = usage_dict.get("completion_tokens_details") or {}
            reasoning_tokens = details.get("reasoning_tokens") or 0
            completion_tokens = usage.completion_tokens or 0
            content_tokens = completion_tokens - reasoning_tokens if completion_tokens > 0 else 0
            if (
                finish_reason == "length"
                and reasoning_tokens > 0
                and completion_tokens > 0
                and (reasoning_tokens / completion_tokens > 0.9 or content_tokens <= 32)
            ):
                reasoning_starved = True
                logger.warning(
                    "Reasoning-token starvation detected: model=%s, "
                    "reasoning_tokens=%d/%d (content_tokens=%d). "
                    "Consider increasing max_tokens.",
                    model, reasoning_tokens, completion_tokens, content_tokens,
                )

            # Augment raw_usage with finish_reason and reasoning metadata
            usage_dict["finish_reason"] = finish_reason
            usage_dict["reasoning_tokens"] = reasoning_tokens
            usage_dict["reasoning_starved"] = reasoning_starved
        else:
            usage_dict = None

        # Extract tool_calls for function calling (Agent mode)
        tool_calls_data = None
        if hasattr(choice.message, "tool_calls") and choice.message.tool_calls:
            function_calls = []
            for tc in choice.message.tool_calls:
                if tc.type != "function":
                    logger.warning("Ignoring unsupported custom tool call: id=%s", tc.id)
                    continue
                function_calls.append(
                    {
                        "id": tc.id,
                        "type": tc.type,
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                )
            tool_calls_data = function_calls or None

        return AdapterResponse(
            content=content,
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
            latency_ms=elapsed_ms,
            model=model,
            raw_usage=usage_dict,
            tool_calls=tool_calls_data,
            finish_reason=finish_reason,
        )

    def _normalize_kwargs(self, model: str, kwargs: dict[str, Any]) -> dict[str, Any]:
        """Normalize provider-specific OpenAI-compatible parameters."""
        request_kwargs = dict(kwargs)

        # CCH kimi-k2.6 currently rejects explicit temperature values, while the
        # benchmark executor passes temperature=0.0 by default. Omitting the
        # parameter keeps the call OpenAI-compatible and lets the upstream use
        # its default.
        if model.lower().startswith("kimi-"):
            request_kwargs.pop("temperature", None)

        return request_kwargs
