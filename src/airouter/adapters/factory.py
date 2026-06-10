"""AdapterFactory：根据 ModelEntry 的 provider 返回对应适配器。

- provider → API key 映射
- key 缺失时降级到 MockAdapter + warning（包含 provider/model）
- 同 (provider, api_base) 复用同一个 adapter 实例
- settings 可注入，不依赖全局单例
"""

from __future__ import annotations

import logging

from airouter.adapters.base import BaseAdapter
from airouter.adapters.mock import MockAdapter
from airouter.adapters.openai_compat import OpenAICompatAdapter
from airouter.config import AppSettings, ModelEntry

logger = logging.getLogger(__name__)


class AdapterFactory:
    """模型适配器工厂：provider/key/base_url 映射 + Mock fallback。"""

    _PROVIDER_KEY_MAP: dict[str, str] = {
        "dashscope": "dashscope_api_key",
        "deepseek": "deepseek_api_key",
        "zhipu": "zhipu_api_key",
        "kimi": "kimi_api_key",
        "minimax": "minimax_api_key",
    }

    def __init__(self, settings: AppSettings | None = None):
        self._settings = settings or AppSettings()
        self._adapters: dict[tuple[str, str], BaseAdapter] = {}

    def get_adapter(self, model_entry: ModelEntry) -> BaseAdapter:
        """根据 provider + api_base 返回适配器。

        同 (provider, api_base) 复用实例。key 缺失时降级到 MockAdapter。
        """
        cache_key = (model_entry.provider, model_entry.api_base)

        # 缓存命中
        if cache_key in self._adapters:
            return self._adapters[cache_key]

        provider = model_entry.provider

        # 查找 API key
        key_attr = self._PROVIDER_KEY_MAP.get(provider)
        api_key = ""
        if key_attr:
            api_key = getattr(self._settings, key_attr, "")

        if not api_key:
            env_hint = f"AIROUTER_{key_attr.upper()}" if key_attr else f"unknown provider: {provider}"
            logger.warning(
                "provider=%s model=%s API key 未配置（环境变量 %s），"
                "降级到 MockAdapter",
                provider,
                model_entry.name,
                env_hint,
            )
            adapter: BaseAdapter = MockAdapter()
        else:
            adapter = OpenAICompatAdapter(
                api_base=model_entry.api_base,
                api_key=api_key,
            )

        self._adapters[cache_key] = adapter
        return adapter
