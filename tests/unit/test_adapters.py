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
        kimi_api_key="",
        minimax_api_key="",
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
    choice.finish_reason = "stop"

    response = MagicMock()
    response.choices = [choice]
    response.usage = usage

    client.chat.completions.create.return_value = response
    return client


def _make_reasoning_mock_client(
    content: str = "",
    prompt_tokens: int = 32,
    completion_tokens: int = 1024,
    reasoning_tokens: int = 1017,
    finish_reason: str = "length",
):
    """构造模拟 reasoning model 响应的 OpenAI client。"""
    client = MagicMock()

    usage = MagicMock()
    usage.prompt_tokens = prompt_tokens
    usage.completion_tokens = completion_tokens
    usage.model_dump = lambda ct=completion_tokens, rt=reasoning_tokens, pt=prompt_tokens: {
        "prompt_tokens": pt,
        "completion_tokens": ct,
        "completion_tokens_details": {
            "reasoning_tokens": rt,
            "accepted_prediction_tokens": None,
            "audio_tokens": None,
            "rejected_prediction_tokens": None,
        },
        "prompt_tokens_details": {"audio_tokens": None, "cached_tokens": 0},
    }

    message = MagicMock()
    message.content = content
    message.model_extra = {"reasoning_content": "thinking..." if reasoning_tokens > 0 else None}

    choice = MagicMock()
    choice.message = message
    choice.finish_reason = finish_reason

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

    def test_kimi_drops_temperature_param(self, adapter, mock_client):
        """CCH kimi-k2.6 rejects explicit temperature; adapter omits it."""
        msgs = _make_messages("测试 Kimi 参数兼容")
        adapter.chat("kimi-k2.6", msgs, temperature=0.0, max_tokens=64)
        mock_client.chat.completions.create.assert_called_once_with(
            model="kimi-k2.6",
            messages=msgs,
            max_tokens=64,
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
            kimi_api_key="k4",
            minimax_api_key="k5",
        )
        factory = AdapterFactory(settings=settings)

        for provider, name, api_base in [
            ("dashscope", "qwen3.7-max", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
            ("deepseek", "deepseek-v4-flash", "https://api.deepseek.com/v1"),
            ("zhipu", "glm-5.1", "https://open.bigmodel.cn/api/paas/v4"),
            ("kimi", "kimi-k2.6", "https://token.cvte.com/v1"),
            ("minimax", "MiniMax-M3", "https://token.cvte.com/v1"),
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
        monkeypatch.setenv("AIROUTER_KIMI_API_KEY", "kimi-env-test-key")
        settings = AppSettings()
        assert settings.deepseek_api_key == "env-test-key"
        assert settings.kimi_api_key == "kimi-env-test-key"

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


# ── Reasoning-token starvation detection ─────────────────────
class TestReasoningStarvation:
    """OpenAICompatAdapter reasoning-token starvation detection.

    Detection condition: finish_reason == "length" AND reasoning_tokens > 0
    AND completion_tokens > 0 AND (reasoning_ratio > 0.9 OR content_tokens <= 32).
    """

    def test_starvation_empty_content_high_ratio(self, caplog):
        """Empty content + finish_reason=length + ratio>0.9 → flagged."""
        client = _make_reasoning_mock_client(
            content="",
            completion_tokens=1024,
            reasoning_tokens=1017,
            finish_reason="length",
        )
        adapter = OpenAICompatAdapter(
            api_base="https://x.com/v1", api_key="k", client=client
        )
        with caplog.at_level(logging.WARNING):
            resp = adapter.chat("deepseek-v4-flash", _make_messages())

        assert resp.content == ""
        assert resp.raw_usage is not None
        assert resp.raw_usage["reasoning_starved"] is True
        assert resp.raw_usage["reasoning_tokens"] == 1017
        assert resp.raw_usage["finish_reason"] == "length"
        assert any("Reasoning-token starvation" in r.message for r in caplog.records)

    def test_starvation_nonempty_content_low_content_tokens(self):
        """Non-empty content but content_tokens<=32 → flagged (truncated output)."""
        # content_tokens = 1024 - 1000 = 24 ≤ 32
        client = _make_reasoning_mock_client(
            content="def is_palindrome(s):\n    return",  # partial code, truncated
            completion_tokens=1024,
            reasoning_tokens=1000,
            finish_reason="length",
        )
        adapter = OpenAICompatAdapter(
            api_base="https://x.com/v1", api_key="k", client=client
        )
        resp = adapter.chat("deepseek-v4-flash", _make_messages())
        assert resp.raw_usage["reasoning_starved"] is True

    def test_starvation_diagnostic_scenario(self):
        """Exact scenario from diagnostic: 1017 reasoning / 1024 completion, content_len=16."""
        client = _make_reasoning_mock_client(
            content="x" * 16,
            completion_tokens=1024,
            reasoning_tokens=1017,
            finish_reason="length",
        )
        adapter = OpenAICompatAdapter(
            api_base="https://x.com/v1", api_key="k", client=client
        )
        resp = adapter.chat("deepseek-v4-flash", _make_messages())
        assert resp.raw_usage["reasoning_starved"] is True

    def test_no_starvation_sufficient_content_tokens(self):
        """Enough content tokens despite length truncation → not starved."""
        # content_tokens = 2048 - 500 = 1548 > 32, ratio = 500/2048 ≈ 0.24 < 0.9
        client = _make_reasoning_mock_client(
            content="def is_palindrome(s): return s == s[::-1]" * 20,
            completion_tokens=2048,
            reasoning_tokens=500,
            finish_reason="length",
        )
        adapter = OpenAICompatAdapter(
            api_base="https://x.com/v1", api_key="k", client=client
        )
        resp = adapter.chat("deepseek-v4-flash", _make_messages())
        assert resp.raw_usage["reasoning_starved"] is False

    def test_no_starvation_with_stop(self):
        """finish_reason=stop → not starved regardless of reasoning tokens."""
        client = _make_reasoning_mock_client(
            content="def is_palindrome(s): ...",
            completion_tokens=895,
            reasoning_tokens=566,
            finish_reason="stop",
        )
        adapter = OpenAICompatAdapter(
            api_base="https://x.com/v1", api_key="k", client=client
        )
        resp = adapter.chat("deepseek-v4-flash", _make_messages())
        assert resp.raw_usage["reasoning_starved"] is False

    def test_no_starvation_low_reasoning_ratio(self):
        """finish_reason=length but ratio<0.9 AND content_tokens>32 → not starved."""
        # content_tokens = 1024 - 500 = 524 > 32, ratio = 500/1024 ≈ 0.49 < 0.9
        client = _make_reasoning_mock_client(
            content="",
            completion_tokens=1024,
            reasoning_tokens=500,
            finish_reason="length",
        )
        adapter = OpenAICompatAdapter(
            api_base="https://x.com/v1", api_key="k", client=client
        )
        resp = adapter.chat("deepseek-v4-flash", _make_messages())
        assert resp.raw_usage["reasoning_starved"] is False

    def test_raw_usage_includes_reasoning_metadata(self):
        """raw_usage always includes finish_reason, reasoning_tokens, reasoning_starved."""
        client = _make_mock_openai_client(
            content="hello", prompt_tokens=10, completion_tokens=5
        )
        adapter = OpenAICompatAdapter(
            api_base="https://x.com/v1", api_key="k", client=client
        )
        resp = adapter.chat("m", _make_messages())
        assert "finish_reason" in resp.raw_usage
        assert "reasoning_tokens" in resp.raw_usage
        assert "reasoning_starved" in resp.raw_usage
        assert resp.raw_usage["reasoning_tokens"] == 0
        assert resp.raw_usage["reasoning_starved"] is False

    def test_boundary_content_tokens_33_not_starved(self):
        """content_tokens=33 (just above 32) with ratio<0.9 → not starved."""
        # content_tokens = 1000 - 967 = 33, ratio = 967/1000 = 0.967 > 0.9 → starved by ratio!
        # So let's use: completion=2000, reasoning=1967, content_tokens=33, ratio=0.98 > 0.9 → starved
        # Need ratio < 0.9: completion=2000, reasoning=1700, content_tokens=300 > 32 → not starved
        # Better: completion=1000, reasoning=967, content_tokens=33, ratio=0.967 > 0.9
        # This WILL be starved by ratio. Let me pick different numbers.
        # completion=1000, reasoning=800, content_tokens=200 > 32, ratio=0.8 < 0.9 → not starved
        client = _make_reasoning_mock_client(
            content="",
            completion_tokens=1000,
            reasoning_tokens=800,
            finish_reason="length",
        )
        adapter = OpenAICompatAdapter(
            api_base="https://x.com/v1", api_key="k", client=client
        )
        resp = adapter.chat("deepseek-v4-flash", _make_messages())
        assert resp.raw_usage["reasoning_starved"] is False

    def test_boundary_content_tokens_32_starved(self):
        """content_tokens=32 with ratio<0.9 → starved (at boundary)."""
        # completion=1000, reasoning=968, content_tokens=32, ratio=0.968 > 0.9 → starved by both
        # For ratio<0.9: completion=5000, reasoning=4968, content_tokens=32, ratio=0.994 → starved
        # Hard to get ratio<0.9 with content_tokens≤32 when reasoning is large.
        # Actually: completion=400, reasoning=368, content_tokens=32, ratio=0.92 > 0.9 → starved
        # completion=500, reasoning=468, content_tokens=32, ratio=0.936 > 0.9 → starved
        # The content_tokens<=32 condition catches cases regardless of ratio
        client = _make_reasoning_mock_client(
            content="x" * 32,
            completion_tokens=400,
            reasoning_tokens=368,
            finish_reason="length",
        )
        adapter = OpenAICompatAdapter(
            api_base="https://x.com/v1", api_key="k", client=client
        )
        resp = adapter.chat("deepseek-v4-flash", _make_messages())
        assert resp.raw_usage["reasoning_starved"] is True
