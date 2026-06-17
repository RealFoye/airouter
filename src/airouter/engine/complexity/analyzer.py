"""统一 ComplexityAnalyzer：规则 + 可选 ML 增强。"""

from __future__ import annotations

import logging
from typing import Any

from airouter.config import ComplexityConfig
from airouter.engine.complexity.types import (
    COMPLEXITY_ORDER,
    ROUTE_TO_COMPLEXITY,
    BackendMetadata,
    ComplexityAnalysis,
    ComplexityContext,
    ComplexityEvaluation,
    MLPrediction,
)
from airouter.engine.router.analyzer import TaskAnalyzer
from airouter.models.enums import ComplexityLevel
from airouter.models.schemas import TaskFeatures

log = logging.getLogger(__name__)


class ComplexityAnalyzer:
    """统一复杂度分析器：规则基线 + 可选 ML 增强。

    四种 mode：
    - rules: 纯规则，不加载 ML
    - shadow: ML 运行但不影响路由，仅记录诊断
    - opensquilla: 使用 ML final class 替换规则结果
    - hybrid: 使用 ML raw class 升级（只升不降）
    """

    def __init__(
        self,
        config: ComplexityConfig,
        rule_analyzer: TaskAnalyzer | None = None,
    ):
        self._config = config
        self._rule_analyzer = rule_analyzer or TaskAnalyzer()
        self._backend: Any = None
        self._init_failure_reason: str | None = None

        if config.mode != "rules":
            self._try_init_backend()

    def _try_init_backend(self) -> None:
        """尝试初始化 ML 后端。失败时根据 require_runtime 降级或抛错。"""
        try:
            from airouter.engine.complexity.ml_backend import (
                ComplexityBackendUnavailable,
                get_backend,
            )

            bundle_dir = self._config.bundle_dir
            if bundle_dir is None:
                raise ComplexityBackendUnavailable("no bundle_dir configured")

            self._backend = get_backend(
                bundle_dir,
                use_aux_head=self._config.use_aux_head,
            )
        except ImportError as exc:
            self._handle_backend_error(f"ML dependencies not installed: {exc}")
        except Exception as exc:
            self._handle_backend_error(str(exc))

    def _handle_backend_error(self, reason: str) -> None:
        """处理后端初始化失败。"""
        self._init_failure_reason = reason
        if self._config.require_runtime:
            from airouter.engine.complexity.ml_backend import ComplexityBackendUnavailable
            raise ComplexityBackendUnavailable(reason)
        log.warning("ml_backend_unavailable: %s", reason)
        self._backend = None

    def extract_rule_features(self, task_description: str) -> TaskFeatures:
        """纯规则特征提取（委托给 TaskAnalyzer）。"""
        return self._rule_analyzer.extract_features(task_description)

    def extract_features(self, task_description: str) -> TaskFeatures:
        """兼容接口：仅返回 features（供不关心诊断的调用方使用）。"""
        result = self.analyze(task_description)
        return result.features

    def analyze(self, task_description: str, context: ComplexityContext | None = None) -> ComplexityEvaluation:
        """完整分析：返回 ComplexityEvaluation（features + analysis）。

        context: 可选的 ML 上下文（多轮历史、工具元数据等），传递给 ML 后端。
        """
        features = self._rule_analyzer.extract_features(task_description)

        if self._config.mode == "rules" or self._backend is None:
            analysis = ComplexityAnalysis(
                rule_complexity=features.complexity,
                rule_category=features.category,
                rule_risk=features.risk_level,
                ml_prediction=None,
                backend_metadata=BackendMetadata(
                    fallback_reason=self._init_failure_reason,
                ),
                resolved=features.complexity,
                resolution_reason="rules mode" if self._config.mode == "rules" else f"ML unavailable: {self._init_failure_reason}",
                mode=self._config.mode,
                ml_available=False,
            )
            return ComplexityEvaluation(features=features, analysis=analysis)

        # ML 可用：获取预测
        ml_pred = self._get_ml_prediction(task_description, context)
        if ml_pred is None:
            analysis = ComplexityAnalysis(
                rule_complexity=features.complexity,
                rule_category=features.category,
                rule_risk=features.risk_level,
                ml_prediction=None,
                backend_metadata=BackendMetadata(fallback_reason="predict failed"),
                resolved=features.complexity,
                resolution_reason="ML predict failed, fallback to rules",
                mode=self._config.mode,
                ml_available=False,
            )
            return ComplexityEvaluation(features=features, analysis=analysis)

        # 解析模式
        resolved, reason = self._resolve(features, ml_pred)

        # 资源重算
        if resolved != features.complexity:
            monotonic = self._config.mode != "opensquilla"
            features = self._rule_analyzer.rebuild_complexity_dependent_features(
                task_description, features, resolved, monotonic=monotonic,
            )

        analysis = ComplexityAnalysis(
            rule_complexity=self._rule_analyzer.extract_features(task_description).complexity,
            rule_category=features.category,
            rule_risk=features.risk_level,
            ml_prediction=ml_pred,
            backend_metadata=BackendMetadata(
                verification_ms=self._backend.verification_ms if self._backend else None,
                load_ms=self._backend.load_ms if self._backend else None,
                manifest_hash=self._backend.manifest_hash if self._backend else None,
                fallback_reason=None,
                config_version=None,
            ),
            resolved=resolved,
            resolution_reason=reason,
            mode=self._config.mode,
            ml_available=True,
        )
        return ComplexityEvaluation(features=features, analysis=analysis)

    def _get_ml_prediction(self, task_description: str, context: ComplexityContext | None = None) -> MLPrediction | None:
        """尝试获取 ML 预测。失败时返回 None 或抛错。"""
        try:
            result: MLPrediction = self._backend.predict(task_description, context)
            return result
        except Exception as exc:
            if self._config.require_runtime:
                raise
            log.warning("ml_predict_failed: %s", str(exc))
            return None

    def _resolve(
        self,
        features: TaskFeatures,
        ml_pred: MLPrediction,
    ) -> tuple[ComplexityLevel, str]:
        """根据 mode 解析最终复杂度。"""
        rule_complexity = features.complexity

        if self._config.mode == "shadow":
            return rule_complexity, f"shadow mode: rule={rule_complexity.value}, ML not applied"

        if self._config.mode == "opensquilla":
            ml_complexity = ROUTE_TO_COMPLEXITY.get(
                ml_pred.final_route_class, ComplexityLevel.MODERATE
            )
            return ml_complexity, (
                f"opensquilla mode: using final class {ml_pred.final_route_class} "
                f"→ {ml_complexity.value}"
            )

        if self._config.mode == "hybrid":
            ml_complexity = ROUTE_TO_COMPLEXITY.get(
                ml_pred.raw_route_class, ComplexityLevel.MODERATE
            )
            rule_order = COMPLEXITY_ORDER[rule_complexity]
            ml_order = COMPLEXITY_ORDER[ml_complexity]

            # 置信度检查
            if ml_pred.raw_confidence < self._config.hybrid.confidence_threshold:
                return rule_complexity, (
                    f"hybrid: ML confidence {ml_pred.raw_confidence:.2f} "
                    f"< threshold {self._config.hybrid.confidence_threshold:.2f}, no upgrade"
                )

            # allow_upgrade=False → 不升级
            if not self._config.hybrid.allow_upgrade:
                return rule_complexity, "hybrid: allow_upgrade=False, no upgrade"

            # 只升不降
            if ml_order <= rule_order:
                return rule_complexity, (
                    f"hybrid: ML={ml_complexity.value} <= rule={rule_complexity.value}, no change"
                )

            # 升级（受 max_upgrade_steps 限制）
            max_steps = self._config.hybrid.max_upgrade_steps
            actual_steps = min(ml_order - rule_order, max_steps)
            # 找到升级后的复杂度
            target_order = rule_order + actual_steps
            for level, order in COMPLEXITY_ORDER.items():
                if order == target_order:
                    return level, (
                        f"hybrid: upgraded {actual_steps} step(s) "
                        f"from {rule_complexity.value} to {level.value} "
                        f"(raw={ml_pred.raw_route_class}, conf={ml_pred.raw_confidence:.2f})"
                    )

            return rule_complexity, "hybrid: could not resolve upgrade target"

        return rule_complexity, f"unknown mode {self._config.mode}"
