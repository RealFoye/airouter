"""StrategyClassifier：从 TaskFeatures 判断哪些策略有资格进入候选池。

职责：TaskFeatures → ClassificationResult（策略列表 + 触发/拒绝原因）。
成本节省率和质量损失率不在此处检查，留到 Selector scoring post-filter。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from airouter.models.enums import (
    ComplexityLevel,
    ReasoningLevel,
    RiskLevel,
    StrategyType,
    VerifiabilityLevel,
)
from airouter.models.schemas import TaskFeatures


@dataclass
class ClassificationResult:
    """策略分类结果：有资格的策略 + 每种策略的触发/拒绝原因。"""

    strategies: list[StrategyType]
    reasons: dict[str, str] = field(default_factory=dict)


class StrategyClassifier:
    """策略分类器：判断哪些策略类型应该作为候选。"""

    def __init__(self, human_review_required_tasks: list[str] | None = None):
        self._forced_review_tasks = set(human_review_required_tasks or [])

    def classify(self, features: TaskFeatures) -> ClassificationResult:
        """返回有资格的策略列表 + 触发/拒绝原因。"""
        strategies = [StrategyType.SINGLE_MODEL]
        reasons: dict[str, str] = {
            StrategyType.SINGLE_MODEL.value: "始终作为候选",
        }

        # Plan-Execute
        pe_ok, pe_reason = self._check_plan_execute(features)
        if pe_ok:
            strategies.append(StrategyType.PLAN_EXECUTE)
        reasons[StrategyType.PLAN_EXECUTE.value] = pe_reason

        # Guided Execute
        ge_ok, ge_reason = self._check_guided_execute(features)
        if ge_ok:
            strategies.append(StrategyType.GUIDED_EXECUTE)
        reasons[StrategyType.GUIDED_EXECUTE.value] = ge_reason

        # Plan-Execute-Review
        per_ok, per_reason = self._check_plan_execute_review(features)
        if per_ok:
            strategies.append(StrategyType.PLAN_EXECUTE_REVIEW)
        reasons[StrategyType.PLAN_EXECUTE_REVIEW.value] = per_reason

        return ClassificationResult(strategies=strategies, reasons=reasons)

    # ── Plan-Execute（5 个结构条件） ──────────────────────────
    def _check_plan_execute(self, f: TaskFeatures) -> tuple[bool, str]:
        rejects = []

        if f.complexity not in (ComplexityLevel.COMPLEX, ComplexityLevel.EXPERT):
            rejects.append(f"complexity={f.complexity.value} (需要 COMPLEX/EXPERT)")

        if f.estimated_output_tokens < 500:
            rejects.append(f"output_tokens={f.estimated_output_tokens} (需要≥500)")

        if f.reasoning_intensity not in (ReasoningLevel.HIGH, ReasoningLevel.VERY_HIGH):
            rejects.append(f"reasoning={f.reasoning_intensity.value} (需要 HIGH/VERY_HIGH)")

        if len(f.subtasks) < 2:
            rejects.append(f"subtasks={len(f.subtasks)} (需要≥2)")

        # 条件5: verifiability >= MEDIUM 或 risk == LOW
        verif_ok = f.verifiability in (VerifiabilityLevel.MEDIUM, VerifiabilityLevel.HIGH)
        risk_low = f.risk_level == RiskLevel.LOW
        if not verif_ok and not risk_low:
            rejects.append(
                f"verifiability={f.verifiability.value}+risk={f.risk_level.value} "
                "(需要 verifiability≥MEDIUM 或 risk=LOW)"
            )

        if rejects:
            return False, "拒绝: " + "; ".join(rejects)
        return True, "触发: 满足全部 5 个结构条件"

    # ── Guided Execute（4 个结构条件） ────────────────────────
    def _check_guided_execute(self, f: TaskFeatures) -> tuple[bool, str]:
        rejects = []

        if f.complexity not in (ComplexityLevel.MODERATE, ComplexityLevel.COMPLEX):
            rejects.append(f"complexity={f.complexity.value} (需要 MODERATE/COMPLEX)")

        if f.estimated_output_tokens < 800:
            rejects.append(f"output_tokens={f.estimated_output_tokens} (需要≥800)")

        if f.risk_level == RiskLevel.LOW:
            rejects.append("risk=LOW (低风险不需要审查开销)")

        # 条件5: verifiability != LOW 或 risk != HIGH
        # 不能同时 LOW verifiability + HIGH risk
        if f.verifiability == VerifiabilityLevel.LOW and f.risk_level == RiskLevel.HIGH:
            rejects.append("verifiability=LOW + risk=HIGH (不可同时)")

        if rejects:
            return False, "拒绝: " + "; ".join(rejects)
        return True, "触发: 满足全部 4 个结构条件"

    # ── Plan-Execute-Review ───────────────────────────────────
    def _check_plan_execute_review(self, f: TaskFeatures) -> tuple[bool, str]:
        # base_decomposable
        base_ok = True
        base_rejects = []

        if f.complexity not in (ComplexityLevel.COMPLEX, ComplexityLevel.EXPERT):
            base_ok = False
            base_rejects.append(f"complexity={f.complexity.value}")

        if f.estimated_output_tokens < 500:
            base_ok = False
            base_rejects.append(f"output_tokens={f.estimated_output_tokens}")

        if f.reasoning_intensity not in (ReasoningLevel.HIGH, ReasoningLevel.VERY_HIGH):
            base_ok = False
            base_rejects.append(f"reasoning={f.reasoning_intensity.value}")

        if len(f.subtasks) < 2:
            base_ok = False
            base_rejects.append(f"subtasks={len(f.subtasks)}")

        if not base_ok:
            return False, "拒绝: base_decomposable 不满足 (" + "; ".join(base_rejects) + ")"

        # review_need
        risk_high = f.risk_level == RiskLevel.HIGH
        verif_low = f.verifiability == VerifiabilityLevel.LOW
        forced = f.category.value in self._forced_review_tasks

        if not (risk_high or verif_low or forced):
            return False, "拒绝: review_need 不满足 (risk!=HIGH, verifiability!=LOW, 非强制审核类型)"

        triggers = []
        if risk_high:
            triggers.append("risk=HIGH")
        if verif_low:
            triggers.append("verifiability=LOW")
        if forced:
            triggers.append(f"category={f.category.value} (强制审核)")

        return True, "触发: base_decomposable + review_need (" + ", ".join(triggers) + ")"
