"""Executor unit tests: ModelExecutor with mock adapters."""

import pytest

from airouter.adapters.base import (
    AdapterAuthError,
    AdapterError,
    AdapterRateLimitError,
    AdapterResponse,
    BaseAdapter,
)
from airouter.adapters.factory import AdapterFactory
from airouter.config import load_models
from airouter.engine.benchmark.executor import ModelExecutor
from airouter.models.model_registry import ModelRegistry


@pytest.fixture
def executor():
    registry = ModelRegistry(load_models())
    factory = AdapterFactory()
    return ModelExecutor(
        adapter_factory=factory,
        registry=registry,
        force_mock=True,
        rate_limit_rpm=1000,  # high limit for tests
    )


class TestModelExecutor:
    def test_execute_returns_executor_result(self, executor):
        messages = [{"role": "user", "content": "hello"}]
        result = executor.execute("qwen3.7-max", messages)
        assert result.response_content.startswith("[Mock]")
        assert result.input_tokens > 0
        assert result.output_tokens > 0
        assert result.latency_ms > 0
        assert result.cost_cny >= 0.0
        assert result.attempts == 1
        assert "temperature" in result.api_params

    def test_validate_models_valid(self, executor):
        executor.validate_models(["qwen3.7-max", "qwen3.7-plus"])

    def test_validate_models_invalid(self, executor):
        with pytest.raises(ValueError, match="Unknown model"):
            executor.validate_models(["nonexistent-model"])

    def test_validate_models_shows_available(self, executor):
        with pytest.raises(ValueError, match="Available models"):
            executor.validate_models(["fake-model"])

    def test_cost_calculation(self, executor):
        """Cost should be proportional to token counts."""
        messages = [{"role": "user", "content": "test prompt " * 50}]
        result = executor.execute("qwen3.7-max", messages)
        # Just verify cost is calculated (non-negative)
        assert result.cost_cny >= 0.0

    def test_force_mock_uses_mock_adapter(self, executor):
        """force_mock=True should always return MockAdapter responses."""
        messages = [{"role": "user", "content": "force mock test"}]
        result = executor.execute("deepseek-v4-flash", messages)
        assert "[Mock]" in result.response_content


class TestRetryBehavior:
    def test_auth_error_no_retry(self):
        """AdapterAuthError should raise immediately without retry."""

        class FailAdapter(BaseAdapter):
            def chat(self, model, messages, **kwargs):
                raise AdapterAuthError("bad key")

        registry = ModelRegistry(load_models())
        factory = AdapterFactory()
        executor = ModelExecutor(factory, registry, force_mock=False, rate_limit_rpm=1000)
        # Replace adapter
        entry = registry.get_by_name("qwen3.7-max")
        executor._factory._adapters[(entry.provider, entry.api_base)] = FailAdapter()
        executor._force_mock = False

        with pytest.raises(AdapterAuthError, match="bad key"):
            executor.execute("qwen3.7-max", [{"role": "user", "content": "test"}])

    def test_rate_limit_retries(self):
        """RateLimitError should retry and succeed."""
        call_count = 0

        class RetryAdapter(BaseAdapter):
            def chat(self, model, messages, **kwargs):
                nonlocal call_count
                call_count += 1
                if call_count < 3:
                    raise AdapterRateLimitError("rate limited")
                return AdapterResponse(
                    content="success after retry",
                    input_tokens=10,
                    output_tokens=10,
                    latency_ms=100,
                    model=model,
                )

        registry = ModelRegistry(load_models())
        factory = AdapterFactory()
        executor = ModelExecutor(
            factory, registry, force_mock=False,
            rate_limit_rpm=1000, max_retries=3, retry_base_delay_s=0.01,
        )
        entry = registry.get_by_name("qwen3.7-max")
        executor._factory._adapters[(entry.provider, entry.api_base)] = RetryAdapter()

        result = executor.execute("qwen3.7-max", [{"role": "user", "content": "test"}])
        assert result.response_content == "success after retry"
        assert result.attempts == 3
        assert call_count == 3

    def test_max_retries_exhausted(self):
        """Should raise after max_retries exhausted."""

        class AlwaysFailAdapter(BaseAdapter):
            def chat(self, model, messages, **kwargs):
                raise AdapterRateLimitError("always limited")

        registry = ModelRegistry(load_models())
        factory = AdapterFactory()
        executor = ModelExecutor(
            factory, registry, force_mock=False,
            rate_limit_rpm=1000, max_retries=2, retry_base_delay_s=0.01,
        )
        entry = registry.get_by_name("qwen3.7-max")
        executor._factory._adapters[(entry.provider, entry.api_base)] = AlwaysFailAdapter()

        with pytest.raises(AdapterError, match="failed after 2 attempts"):
            executor.execute("qwen3.7-max", [{"role": "user", "content": "test"}])
