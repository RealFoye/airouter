"""OpenSquilla ML 后端封装。

进程内单例 Runtime，sys.modules 隔离，Artifact 验证先行。
Backend 不持有 require_runtime——初始化或 predict 失败一律抛 ComplexityBackendUnavailable。
降级/传播由 ComplexityAnalyzer 决定。
"""

from __future__ import annotations

import logging
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import yaml

from airouter.engine.complexity.artifact_verifier import (
    MANIFEST_SHA256,
    ArtifactVerifier,
)
from airouter.engine.complexity.types import ComplexityContext, MLPrediction

log = logging.getLogger(__name__)


class ComplexityBackendUnavailable(Exception):
    """ML 后端不可用——由 Analyzer 决定 fallback 或传播。"""


# ── 进程级单例 ──────────────────────────────────────────────
_ACTIVE_CACHE_KEY: tuple[Path, bool] | None = None
_ACTIVE_BACKEND: OpenSquillaBackend | None = None
_GLOBAL_LOCK = threading.Lock()


def get_backend(bundle_dir: Path, use_aux_head: bool = False) -> OpenSquillaBackend:
    """获取进程内单例 Backend。

    缓存键为 (resolved_path, use_aux_head)。不同配置拒绝复用。
    """
    global _ACTIVE_CACHE_KEY, _ACTIVE_BACKEND

    resolved = bundle_dir.resolve()
    cache_key = (resolved, use_aux_head)

    with _GLOBAL_LOCK:
        if _ACTIVE_BACKEND is not None:
            if _ACTIVE_CACHE_KEY == cache_key:
                return _ACTIVE_BACKEND
            active_path, active_aux = _ACTIVE_CACHE_KEY  # type: ignore[misc]
            raise ComplexityBackendUnavailable(
                f"different backend already active: path={active_path}, "
                f"aux={active_aux}; requested: path={resolved}, aux={use_aux_head}"
            )

        backend = OpenSquillaBackend(resolved, use_aux_head=use_aux_head)
        _ACTIVE_CACHE_KEY = cache_key
        _ACTIVE_BACKEND = backend
        return backend


def reset_backend() -> None:
    """重置单例（仅测试使用）。"""
    global _ACTIVE_CACHE_KEY, _ACTIVE_BACKEND
    with _GLOBAL_LOCK:
        _ACTIVE_CACHE_KEY = None
        _ACTIVE_BACKEND = None


class OpenSquillaBackend:
    """OpenSquilla ML 推理后端封装。

    注意：不接收 require_runtime 参数。
    初始化或 predict 失败一律抛 ComplexityBackendUnavailable。
    """

    def __init__(self, bundle_dir: Path, use_aux_head: bool = False):
        self._bundle_dir = bundle_dir
        self._use_aux_head = use_aux_head
        self._core: Any = None
        self._request_type: Any = None
        self._model_version: str = "unknown"
        self._cold_start_ms: float | None = None
        self._verification_ms: float | None = None
        self._load_ms: float | None = None
        self._manifest_hash: str | None = None
        self._predict_lock = threading.Lock()
        self._available = False

        try:
            self._init_runtime()
        except ComplexityBackendUnavailable:
            raise
        except Exception as exc:
            self._cleanup_modules()
            raise ComplexityBackendUnavailable(
                f"failed to initialize ML backend: {exc}"
            ) from exc

    def _init_runtime(self) -> None:
        t0 = time.perf_counter()

        # 1. 检查 bundle 存在性
        if not self._bundle_dir.exists():
            raise ComplexityBackendUnavailable(
                f"bundle directory not found: {self._bundle_dir}"
            )

        # 2. sys.modules 冲突检测
        if "src" in sys.modules and not self._is_opensquilla_src():
            raise ComplexityBackendUnavailable(
                "sys.modules['src'] already occupied by non-OpenSquilla module"
            )

        # 3. Artifact 验证
        t_verify = time.perf_counter()
        verifier = ArtifactVerifier(self._bundle_dir)
        verifier.verify_all()
        self._verification_ms = (time.perf_counter() - t_verify) * 1000
        self._manifest_hash = MANIFEST_SHA256

        # 4. 加载 runtime_src
        t_load = time.perf_counter()
        runtime_src = self._bundle_dir / "runtime_src"
        saved_sys_path = list(sys.path)
        if str(runtime_src) not in sys.path:
            sys.path.insert(0, str(runtime_src))

        # 5. 记录初始模块集
        initial_modules = set(sys.modules.keys())

        try:
            # 6. 导入 InferenceCore
            from src.router.inference.core import InferenceCore  # type: ignore[import-not-found]  # noqa: I001
            from src.router.inference.types import InferenceRequest  # type: ignore[import-not-found]  # noqa: I001

            # 7. 加载配置
            config_path = self._bundle_dir / "router.runtime.yaml"
            runtime_config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}

            # 8. 初始化 InferenceCore
            self._core = InferenceCore.from_model_dir(
                str(self._bundle_dir),
                runtime_config,
                use_aux_head=self._use_aux_head,
            )
            self._request_type = InferenceRequest
            self._model_version = self._read_model_version()
            self._available = True
            self._load_ms = (time.perf_counter() - t_load) * 1000

        except Exception:
            # 清理本次新加入的模块
            new_modules = set(sys.modules.keys()) - initial_modules
            for mod_name in new_modules:
                if mod_name.startswith("src") or mod_name.startswith("src."):
                    sys.modules.pop(mod_name, None)
            # 恢复 sys.path
            sys.path[:] = saved_sys_path
            raise

        elapsed = (time.perf_counter() - t0) * 1000
        self._cold_start_ms = elapsed

    def _is_opensquilla_src(self) -> bool:
        """检查 sys.modules['src'] 是否来自 OpenSquilla bundle。"""
        src_mod = sys.modules.get("src")
        if src_mod is None:
            return False
        mod_path = getattr(src_mod, "__path__", None) or getattr(src_mod, "__file__", None)
        if mod_path is None:
            return False
        return str(self._bundle_dir / "runtime_src") in str(mod_path)

    def _cleanup_modules(self) -> None:
        """清理本次初始化新加入的 src.* 模块。"""
        to_remove = [
            key for key in sys.modules
            if key == "src" or key.startswith("src.")
        ]
        for key in to_remove:
            sys.modules.pop(key, None)

    def _read_model_version(self) -> str:
        import json

        for name in ("version.json", "inference_manifest.json"):
            path = self._bundle_dir / name
            if not path.exists():
                continue
            data = json.loads(path.read_text(encoding="utf-8"))
            for key in ("version", "model_version", "bundle_version"):
                value = data.get(key)
                if value:
                    return str(value)
        return "unknown"

    @property
    def available(self) -> bool:
        return self._available

    @property
    def verification_ms(self) -> float | None:
        return self._verification_ms

    @property
    def load_ms(self) -> float | None:
        return self._load_ms

    @property
    def manifest_hash(self) -> str | None:
        return self._manifest_hash

    def predict(self, task_description: str, context: ComplexityContext | None = None) -> MLPrediction:
        """执行 ML 推理。返回真实 MLPrediction 或抛 ComplexityBackendUnavailable。

        context: 可选的额外上下文（多轮历史、工具元数据等）。
                 context=None 时自动推导行为不变。
        """
        if not self._available or self._core is None or self._request_type is None:
            raise ComplexityBackendUnavailable("ML backend not initialized")

        with self._predict_lock:
            try:
                t0 = time.perf_counter()
                request = self._build_request(task_description, context)
                result = self._core.predict(request)
                latency_ms = (time.perf_counter() - t0) * 1000
                return self._map_result(result, latency_ms)
            except ComplexityBackendUnavailable:
                raise
            except Exception as exc:
                raise ComplexityBackendUnavailable(
                    f"predict failed: {exc}"
                ) from exc

    def _build_request(self, task_description: str, context: ComplexityContext | None = None) -> Any:
        request_type = self._request_type
        if request_type is None:
            raise ComplexityBackendUnavailable("request type not initialized")

        if context is not None:
            # OpenSquilla 的历史特征提取器读取对象属性，而不是裸字符串。
            # AirRouter 对外仅保存稳定的 R0-R3 标签，在适配边界补齐训练时
            # 所需的 difficulty/margin 字段，避免多轮预测静默回退 Rules。
            previous_decisions = [
                SimpleNamespace(
                    route_class=route_class,
                    difficulty=0.0,
                    margin=0.0,
                )
                for route_class in context.prev_route_decisions
            ]
            return request_type(
                current_user_text=task_description,
                history_user_texts=list(context.history_user_texts),
                prev_assistant_text=context.prev_assistant_text,
                prev_assistant_usage=context.prev_assistant_usage,
                prev_route_decisions=previous_decisions,
                flags_text_override=None,
                context_metadata={
                    "turn_index": context.turn_index,
                    "context_tokens_est": max(1, context.context_tokens_est),
                    "n_tools": context.n_tools,
                    "tool_result_length": context.tool_result_length,
                    "has_code_block": context.has_code_block,
                    "has_prev_assistant": context.has_prev_assistant,
                },
            )

        return request_type(
            current_user_text=task_description,
            history_user_texts=[],
            prev_assistant_text=None,
            prev_assistant_usage=None,
            prev_route_decisions=[],
            flags_text_override=None,
            context_metadata={
                "turn_index": 0,
                "context_tokens_est": max(1, len(task_description) // 4),
                "n_tools": 0,
                "tool_result_length": 0,
                "has_code_block": "```" in task_description,
                "has_prev_assistant": False,
            },
        )

    def _map_result(self, result: Any, latency_ms: float) -> MLPrediction:
        decision = result.decision
        route_class = str(decision.route_class)
        probabilities = dict(result.probabilities or {})
        raw_confidence = float(probabilities.get(route_class, 0.0))

        # final_route_class: OpenSquilla postprocess 可能改写 route_class
        # 在 InferenceResult 中 decision.route_class 就是 final（经过 8 层后处理）
        # raw 需要从 probabilities 的 argmax 取
        raw_class = max(probabilities, key=lambda k: probabilities[k]) if probabilities else route_class
        raw_confidence_val = float(probabilities.get(raw_class, 0.0))

        # margin: top1 - top2
        sorted_probs = sorted(probabilities.values(), reverse=True)
        margin = (sorted_probs[0] - sorted_probs[1]) if len(sorted_probs) >= 2 else sorted_probs[0] if sorted_probs else 0.0

        difficulty = float(getattr(decision, "difficulty_score", 0.0))

        return MLPrediction(
            raw_route_class=raw_class,
            final_route_class=route_class,
            raw_confidence=raw_confidence_val,
            final_class_probability=raw_confidence,
            probabilities=probabilities,
            margin=margin,
            difficulty_score=difficulty,
            flags=dict(getattr(decision, "flags", {}) or {}),
            latency_ms=latency_ms,
            cold_start_ms=self._cold_start_ms,
            model_version=self._model_version,
        )
