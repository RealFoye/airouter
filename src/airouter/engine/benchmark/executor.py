"""Level 2 model executor: API calls with retry, rate limiting, and cost tracking."""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

from airouter.adapters.base import (
    AdapterAuthError,
    AdapterError,
    AdapterRateLimitError,
    AdapterResponse,
    AdapterTimeoutError,
    BaseAdapter,
)
from airouter.adapters.factory import AdapterFactory
from airouter.adapters.mock import MockAdapter
from airouter.config import ModelEntry
from airouter.engine.benchmark.schemas import ExecutorResult
from airouter.models.model_registry import ModelRegistry

logger = logging.getLogger(__name__)

SYSTEM_PROMPT_VERSION = "1.0"


class ModelExecutor:
    """Execute prompts against models via AdapterFactory.

    force_mock=True (default) → always use MockAdapter, never real API.
    """

    def __init__(
        self,
        adapter_factory: AdapterFactory,
        registry: ModelRegistry,
        force_mock: bool = True,
        rate_limit_rpm: int = 20,
        max_retries: int = 3,
        retry_base_delay_s: float = 2.0,
        temperature: float = 0.0,
        default_max_tokens: int = 2048,
    ):
        self._factory = adapter_factory
        self._registry = registry
        self._force_mock = force_mock
        self._rate_limit_rpm = rate_limit_rpm
        self._max_retries = max_retries
        self._retry_base_delay = retry_base_delay_s
        self._temperature = temperature
        self._default_max_tokens = default_max_tokens
        self._last_call_time: dict[str, float] = {}
        self._mock_adapters: dict[str, MockAdapter] = {}
        # Per-model rate limit locks (different models don't block each other)
        self._rate_locks: dict[str, threading.Lock] = {}
        self._rate_locks_lock = threading.Lock()
        # Thread-safe physical API call counter
        self._physical_call_count = 0
        self._physical_call_lock = threading.Lock()

    def validate_models(self, model_names: list[str]) -> None:
        """Validate all model names exist in registry. Raises ValueError if not."""
        all_models = [m.name for m in self._registry.all_models]
        invalid = [m for m in model_names if m not in all_models]
        if invalid:
            available = ", ".join(sorted(all_models))
            raise ValueError(
                f"Unknown model(s): {', '.join(invalid)}. "
                f"Available models: {available}"
            )

    def execute(
        self,
        model_name: str,
        messages: list[dict],
        max_tokens: int | None = None,
    ) -> ExecutorResult:
        """Execute a single model call with retry and rate limiting.

        Returns ExecutorResult with cost, attempts, and api_params.
        Raises AdapterAuthError immediately (no retry).
        """
        entry = self._get_model_entry(model_name)
        adapter = self._get_adapter(entry)
        tokens = max_tokens or self._default_max_tokens

        response, attempts = self._call_with_retry(
            adapter, model_name, messages,
            temperature=self._temperature,
            max_tokens=tokens,
        )

        cost = self._calculate_cost(entry, response.input_tokens, response.output_tokens)

        return ExecutorResult(
            response_content=response.content,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            latency_ms=response.latency_ms,
            cost_cny=cost,
            attempts=attempts,
            api_params={
                "temperature": self._temperature,
                "max_tokens": tokens,
                "system_prompt_version": SYSTEM_PROMPT_VERSION,
            },
            raw_usage=response.raw_usage,
        )

    def _get_model_entry(self, model_name: str) -> ModelEntry:
        """Look up ModelEntry from registry."""
        result = self._registry.get_by_name(model_name)
        if result is None:
            raise ValueError(f"Model not found in registry: {model_name}")
        return result

    def _get_adapter(self, entry: ModelEntry) -> BaseAdapter:
        """Get adapter. force_mock=True → MockAdapter."""
        if self._force_mock:
            if entry.name not in self._mock_adapters:
                self._mock_adapters[entry.name] = MockAdapter()
            return self._mock_adapters[entry.name]
        return self._factory.get_adapter(entry)

    def get_physical_call_count(self) -> int:
        """返回累计物理 API 调用数（线程安全）。"""
        with self._physical_call_lock:
            return self._physical_call_count

    def reset_physical_call_count(self) -> int:
        """重置计数器并返回旧值。"""
        with self._physical_call_lock:
            old = self._physical_call_count
            self._physical_call_count = 0
            return old

    def snapshot_physical_calls(self) -> int:
        """获取当前计数器快照（用于 before/after delta 计算）。"""
        with self._physical_call_lock:
            return self._physical_call_count

    def _increment_physical_calls(self) -> None:
        """线程安全地递增物理调用计数。"""
        with self._physical_call_lock:
            self._physical_call_count += 1

    def _call_with_retry(
        self,
        adapter: BaseAdapter,
        model_name: str,
        messages: list[dict],
        **kwargs: Any,
    ) -> tuple[AdapterResponse, int]:
        """Call adapter with exponential backoff retry.

        Returns (response, attempts).
        AuthError → re-raise immediately (no retry).
        RateLimit/Timeout → retry with backoff.
        Other AdapterError → retry once, then raise.
        """
        self._wait_for_rate_limit(model_name)

        last_error: Exception | None = None
        for attempt in range(1, self._max_retries + 1):
            try:
                self._last_call_time[model_name] = time.monotonic()
                self._increment_physical_calls()
                response = adapter.chat(model_name, messages, **kwargs)
                return response, attempt
            except AdapterAuthError:
                raise  # immediate abort, no retry
            except (AdapterRateLimitError, AdapterTimeoutError) as e:
                last_error = e
                if attempt < self._max_retries:
                    delay = self._retry_base_delay * (2 ** (attempt - 1))
                    logger.warning(
                        "model=%s attempt=%d/%d error=%s, retrying in %.1fs",
                        model_name, attempt, self._max_retries, type(e).__name__, delay,
                    )
                    time.sleep(delay)
            except AdapterError as e:
                last_error = e
                if attempt < self._max_retries:
                    delay = self._retry_base_delay
                    logger.warning(
                        "model=%s attempt=%d/%d error=%s, retrying in %.1fs",
                        model_name, attempt, self._max_retries, type(e).__name__, delay,
                    )
                    time.sleep(delay)

        raise AdapterError(
            f"model={model_name} failed after {self._max_retries} attempts: {last_error}"
        ) from last_error

    def _wait_for_rate_limit(self, model_name: str) -> None:
        """Enforce per-model rate limit by sleeping if needed.

        Uses per-model lock so different models don't block each other.
        """
        if self._rate_limit_rpm <= 0:
            return
        lock = self._get_rate_lock(model_name)
        with lock:
            min_interval = 60.0 / self._rate_limit_rpm
            last_time = self._last_call_time.get(model_name)
            if last_time is not None:
                elapsed = time.monotonic() - last_time
                if elapsed < min_interval:
                    time.sleep(min_interval - elapsed)
            self._last_call_time[model_name] = time.monotonic()

    def _get_rate_lock(self, model_name: str) -> threading.Lock:
        with self._rate_locks_lock:
            if model_name not in self._rate_locks:
                self._rate_locks[model_name] = threading.Lock()
            return self._rate_locks[model_name]

    def _calculate_cost(
        self, entry: ModelEntry, input_tokens: int, output_tokens: int
    ) -> float:
        """Calculate cost in CNY using ModelEntry per-1K pricing."""
        return (
            input_tokens / 1000 * entry.input_price_per_1k
            + output_tokens / 1000 * entry.output_price_per_1k
        )
