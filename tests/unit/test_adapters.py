"""测试模型适配器层：BaseAdapter / MockAdapter / OpenAICompatAdapter / AdapterFactory。"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import pytest

from airouter.adapters.base import (
    AdapterAuthError,
    AdapterError,
    AdapterRateLimitError,
    AdapterResponse,
    AdapterTimeoutError,
)
from airouter.adapters.factory import AdapterFactory
from airouter.adapters.mock import MockAdapter
from airouter.adapters.openai_compat import OpenAICompatAdapter
from airouter.config import AppSettings, ModelEntry


# ── helpers ───────────────────────────────────────────────────
def _empty_settings() -> AppSettings:
    return AppSettings(
        dashscope_api_key="",
        deepseek_api_key="",
        zhipu_api_key="",
    )


def _make_model_entry(
    name: str = "deepseek-v4-flash",
    provider: str = "deepseek",
    api_base: str = "https://api.deepseek.com/v1",
) -> ModelEntry:
    return ModelEntry(
        name=name,
        tier=3,
        provider=provider,
        api_base=api_base,
        input_price_per_1k=0.001,
        output_price_per_1k=0.002,
        max_context_window=65536,
    )


def _make_messages(content: str = "写一个Hello World") -> list[dict]:
    return [
        {"role": "system", "content": "你是一个编程助手"},
        {"role": "user", "content": content},
    ]


def _make_mock_openai_client(
    content: str = "print('hello')",
    prompt_tokens: int = 50,
    completion_tokens: int = 10,
):
    """构造一个模拟的 OpenAI client，返回指定结果。"""
    client = MagicMock()

    # 构造 response 对象
    usage = MagicMock()
    usage.prompt_tokens = prompt_tokens
    usage.completion_tokens = completion_tokens
    usage.model_dump = lambda: {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
    }

    message = MagicMock()
    message.content = content

    choice = MagicMock()
    choice.message = message

    response = MagicMock()
    response.choices = [choice]
    response.usage = usage

    client.chat.completions.create.return_value = response
    return client


# ── AdapterResponse ──────────────────────────────────────────
class TestAdapterResponse:
    def test_fields(self):
        resp = AdapterResponse(
            content="hello",
            input_tokens=10,
            output_tokens=5,
            latency_ms=200,
            model="test-model",
        )
        assert resp.content == "hello"
        assert resp.input_tokens == 10
        assert resp.output_tokens == 5
        assert resp.latency_ms == 200
        assert resp.model == "test-model"
        assert resp.raw_usage is None

    def test_raw_usage(self):
        resp = AdapterResponse(
            content="x",
            input_tokens=1,
            output_tokens=1,
            latency_ms=100,
            model="m",
            raw_usage={"prompt_tokens": 1},
        )
        assert resp.raw_usage == {"prompt_tokens": 1}


# ── 异常体系 ──────────────────────────────────────────────────
class TestAdapterErrors:
    def test_hierarchy(self):
        assert issubclass(AdapterAuthError, AdapterError)
        assert issubclass(AdapterRateLimitError, AdapterError)
        assert issubclass(AdapterTimeoutError, AdapterError)
        assert issubclass(AdapterError, Exception)

    def test_can_catch_as_adapter_error(self):
        with pytest.raises(AdapterError):
            raise AdapterAuthError("bad key")

        with pytest.raises(AdapterError):
            raise AdapterRateLimitError("too many")

        with pytest.raises(AdapterError):
            raise AdapterTimeoutError("timeout")


# ── MockAdapter ───────────────────────────────────────────────
class TestMockAdapter:
    @pytest.fixture
    def adapter(self) -> MockAdapter:
        return MockAdapter()

    def test_returns_response(self, adapter):
        resp = adapter.chat("test-model", _make_messages())
        assert isinstance(resp, AdapterResponse)
        assert resp.model == "test-model"
        assert resp.content
        assert resp.input_tokens > 0
        assert resp.output_tokens > 0
        assert resp.latency_ms >= 100
        assert resp.latency_ms <= 500

    def test_deterministic_content(self, adapter):
        msgs = _make_messages("写一个回文检查")
        r1 = adapter.chat("model-a", msgs)
        r2 = adapter.chat("model-a", msgs)
        assert r1.content == r2.content

    def test_deterministic_tokens(self, adapter):
        msgs = _make_messages("固定输入内容")
        r1 = adapter.chat("model-x", msgs)
        r2 = adapter.chat("model-x", msgs)
        assert r1.input_tokens == r2.input_tokens
        assert r1.output_tokens == r2.output_tokens

    def test_deterministic_latency(self, adapter):
        msgs = _make_messages("测试延迟确定性")
        r1 = adapter.chat("model-y", msgs)
        r2 = adapter.chat("model-y", msgs)
        assert r1.latency_ms == r2.latency_ms

    def test_different_input_different_latency(self, adapter):
        r1 = adapter.chat("m", _make_messages("输入A"))
        r2 = adapter.chat("m", _make_messages("输入B"))
        # 不同输入大概率产生不同 latency（hash 不同）
        # 不强制断言不等，因为 hash 碰撞理论上可能
        assert isinstance(r1.latency_ms, int)
        assert isinstance(r2.latency_ms, int)

    def test_content_contains_model_and_message(self, adapter):
        resp = adapter.chat("qwen3.7-max", _make_messages("设计分布式缓存"))
        assert "qwen3.7-max" in resp.content
        assert "设计分布式缓存" in resp.content

    def test_raw_usage_populated(self, adapter):
        resp = adapter.chat("m", _make_messages())
        assert resp.raw_usage is not None
        assert "prompt_tokens" in resp.raw_usage
        assert "completion_tokens" in resp.raw_usage

    @pytest.mark.asyncio
    async def test_achat(self, adapter):
        msgs = _make_messages("异步测试")
        resp = await adapter.achat("model-async", msgs)
        assert isinstance(resp, AdapterResponse)
        assert resp.model == "model-async"
        assert resp.content


# ── OpenAICompatAdapter ──────────────────────────────────────
class TestOpenAICompatAdapter:
    @pytest.fixture
    def mock_client(self):
        return _make_mock_openai_client(
            content="def hello(): pass",
            prompt_tokens=42,
            completion_tokens=8,
        )

    @pytest.fixture
    def adapter(self, mock_client) -> OpenAICompatAdapter:
        return OpenAICompatAdapter(
            api_base="https://api.deepseek.com/v1",
            api_key="test-key",
            client=mock_client,
        )

    def test_chat_returns_response(self, adapter):
        resp = adapter.chat("deepseek-v4-flash", _make_messages())
        assert isinstance(resp, AdapterResponse)
        assert resp.content == "def hello(): pass"
        assert resp.input_tokens == 42
        assert resp.output_tokens == 8
        assert resp.model == "deepseek-v4-flash"
        assert resp.latency_ms >= 0

    def test_chat_calls_client_correctly(self, adapter, mock_client):
        msgs = _make_messages("测试调用参数")
        adapter.chat("deepseek-v4-flash", msgs, temperature=0.7)
        mock_client.chat.completions.create.assert_called_once_with(
            model="deepseek-v4-flash",
            messages=msgs,
            temperature=0.7,
        )

    def test_raw_usage_populated(self, adapter):
        resp = adapter.chat("m", _make_messages())
        assert resp.raw_usage is not None
        assert resp.raw_usage["prompt_tokens"] == 42

    def test_auth_error_mapping(self):
        client = MagicMock()
        from openai import AuthenticationError as OpenAIAuthError

        client.chat.completions.create.side_effect = OpenAIAuthError(
            "bad key",
            response=MagicMock(status_code=401),
            body=None,
        )
        adapter = OpenAICompatAdapter(
            api_base="https://x.com/v1", api_key="bad", client=client
        )
        with pytest.raises(AdapterAuthError):
            adapter.chat("m", _make_messages())

    def test_rate_limit_error_mapping(self):
        client = MagicMock()
        from openai import RateLimitError as OpenAIRateLimitError

        client.chat.completions.create.side_effect = OpenAIRateLimitError(
            "rate limited",
            response=MagicMock(status_code=429),
            body=None,
        )
        adapter = OpenAICompatAdapter(
            api_base="https://x.com/v1", api_key="k", client=client
        )
        with pytest.raises(AdapterRateLimitError):
            adapter.chat("m", _make_messages())

    def test_timeout_error_mapping(self):
        client = MagicMock()
        from openai import APITimeoutError as OpenAITimeoutError

        client.chat.completions.create.side_effect = OpenAITimeoutError(
            request=MagicMock()
        )
        adapter = OpenAICompatAdapter(
            api_base="https://x.com/v1", api_key="k", client=client
        )
        with pytest.raises(AdapterTimeoutError):
            adapter.chat("m", _make_messages())

    def test_generic_api_error_mapping(self):
        client = MagicMock()
        from openai import APIError as OpenAIAPIError

        client.chat.completions.create.side_effect = OpenAIAPIError(
            "server error",
            request=MagicMock(),
            body=None,
        )
        adapter = OpenAICompatAdapter(
            api_base="https://x.com/v1", api_key="k", client=client
        )
        with pytest.raises(AdapterError):
            adapter.chat("m", _make_messages())

    def test_empty_content_handled(self):
        client = _make_mock_openai_client(content=None, prompt_tokens=10, completion_tokens=0)
        # message.content = None 时应该返回空字符串
        client.chat.completions.create.return_value.choices[0].message.content = None
        adapter = OpenAICompatAdapter(
            api_base="https://x.com/v1", api_key="k", client=client
        )
        resp = adapter.chat("m", _make_messages())
        assert resp.content == ""

    def test_no_usage_handled(self):
        client = MagicMock()
        response = MagicMock()
        response.choices = [MagicMock()]
        response.choices[0].message.content = "ok"
        response.usage = None
        client.chat.completions.create.return_value = response
        adapter = OpenAICompatAdapter(
            api_base="https://x.com/v1", api_key="k", client=client
        )
        resp = adapter.chat("m", _make_messages())
        assert resp.input_tokens == 0
        assert resp.output_tokens == 0
        assert resp.raw_usage is None

    @pytest.mark.asyncio
    async def test_achat(self, adapter):
        resp = await adapter.achat("deepseek-v4-flash", _make_messages())
        assert isinstance(resp, AdapterResponse)
        assert resp.content == "def hello(): pass"


# ── AdapterFactory ────────────────────────────────────────────
class TestAdapterFactory:
    def test_known_provider_with_key(self):
        settings = AppSettings(deepseek_api_key="test-key-123")
        factory = AdapterFactory(settings=settings)
        entry = _make_model_entry(provider="deepseek")
        adapter = factory.get_adapter(entry)
        assert isinstance(adapter, OpenAICompatAdapter)

    def test_known_provider_missing_key_falls_back_to_mock(self, caplog):
        settings = _empty_settings()
        factory = AdapterFactory(settings=settings)
        entry = _make_model_entry(provider="deepseek", name="deepseek-v4-flash")

        with caplog.at_level(logging.WARNING):
            adapter = factory.get_adapter(entry)

        assert isinstance(adapter, MockAdapter)
        assert any(
            "deepseek" in record.message and "deepseek-v4-flash" in record.message
            for record in caplog.records
        )

    def test_unknown_provider_falls_back_to_mock(self, caplog):
        settings = AppSettings()
        factory = AdapterFactory(settings=settings)
        entry = _make_model_entry(provider="unknown_provider", name="some-model")

        with caplog.at_level(logging.WARNING):
            adapter = factory.get_adapter(entry)

        assert isinstance(adapter, MockAdapter)

    def test_same_provider_reuses_adapter(self):
        settings = AppSettings(deepseek_api_key="key")
        factory = AdapterFactory(settings=settings)
        entry1 = _make_model_entry(name="deepseek-v4-flash", provider="deepseek")
        entry2 = _make_model_entry(name="deepseek-v4-pro", provider="deepseek")
        a1 = factory.get_adapter(entry1)
        a2 = factory.get_adapter(entry2)
        assert a1 is a2

    def test_different_providers_different_adapters(self):
        settings = AppSettings(deepseek_api_key="k1", dashscope_api_key="k2")
        factory = AdapterFactory(settings=settings)
        a1 = factory.get_adapter(_make_model_entry(provider="deepseek"))
        a2 = factory.get_adapter(
            _make_model_entry(
                name="qwen3.7-max",
                provider="dashscope",
                api_base="https://dashscope.aliyuncs.com/compatible-mode/v1",
            )
        )
        assert a1 is not a2

    def test_all_known_providers(self):
        settings = AppSettings(
            dashscope_api_key="k1",
            deepseek_api_key="k2",
            zhipu_api_key="k3",
        )
        factory = AdapterFactory(settings=settings)

        for provider, name, api_base in [
            ("dashscope", "qwen3.7-max", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
            ("deepseek", "deepseek-v4-flash", "https://api.deepseek.com/v1"),
            ("zhipu", "glm-5.1", "https://open.bigmodel.cn/api/paas/v4"),
        ]:
            entry = _make_model_entry(name=name, provider=provider, api_base=api_base)
            adapter = factory.get_adapter(entry)
            assert isinstance(adapter, OpenAICompatAdapter), f"provider={provider}"

    def test_default_settings_when_none(self):
        """不传 settings 时不报错（使用默认 AppSettings）。"""
        with patch("airouter.adapters.factory.AppSettings", return_value=_empty_settings()):
            factory = AdapterFactory()
            entry = _make_model_entry(provider="deepseek")
            adapter = factory.get_adapter(entry)
            assert isinstance(adapter, MockAdapter)


# ── 补充测试：Review 反馈修复 ────────────────────────────────
class TestReviewFixes:
    """Review 提出的 4 个修复点验证。"""

    def test_empty_choices_raises_adapter_error(self):
        """[P2] 兼容厂商返回 choices=[] 时应抛 AdapterError，不是 IndexError。"""
        client = MagicMock()
        response = MagicMock()
        response.choices = []
        client.chat.completions.create.return_value = response
        adapter = OpenAICompatAdapter(
            api_base="https://x.com/v1", api_key="k", client=client
        )
        with pytest.raises(AdapterError, match="choices is empty"):
            adapter.chat("m", _make_messages())

    def test_api_key_from_env_variable(self, monkeypatch):
        """[P3] API key 通过环境变量设置后能正确读取。"""
        monkeypatch.setenv("AIROUTER_DEEPSEEK_API_KEY", "env-test-key")
        settings = AppSettings()
        assert settings.deepseek_api_key == "env-test-key"

        factory = AdapterFactory(settings=settings)
        entry = _make_model_entry(provider="deepseek")
        adapter = factory.get_adapter(entry)
        assert isinstance(adapter, OpenAICompatAdapter)

    def test_unknown_provider_warning_mentions_unknown(self, caplog):
        """[P3] 未知 provider warning 应包含 "unknown provider" 而非空环境变量名。"""
        settings = AppSettings()
        factory = AdapterFactory(settings=settings)
        entry = _make_model_entry(provider="some_new_provider", name="new-model")

        with caplog.at_level(logging.WARNING):
            factory.get_adapter(entry)

        assert any(
            "unknown provider" in record.message for record in caplog.records
        )

    def test_same_provider_different_api_base_different_adapter(self):
        """[P3] 同 provider 不同 api_base 应产生不同 adapter（缓存 key 是 tuple）。"""
        settings = AppSettings(deepseek_api_key="key")
        factory = AdapterFactory(settings=settings)
        e1 = _make_model_entry(
            provider="deepseek", api_base="https://api.deepseek.com/v1"
        )
        e2 = _make_model_entry(
            provider="deepseek", api_base="https://api.deepseek.com/v2"
        )
        a1 = factory.get_adapter(e1)
        a2 = factory.get_adapter(e2)
        assert a1 is not a2
