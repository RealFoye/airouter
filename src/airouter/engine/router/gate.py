"""RoutingGate：管控门禁，决定路由推荐能否自动放行。

Selector 可以推荐"性价比最优"，Gate 决定"能否自动执行"。
Gate 是 requires_human_review 和 quality_gate 的唯一决定者。

职责边界：
- Selector：过滤 + 评分 → 推荐最优候选
- Gate：评估推荐 → 决定是否需要人工审核 + 构建质量门禁
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from airouter.models.enums import BudgetStatus, RiskLevel, SensitivityLevel, StrategyType
from airouter.models.schemas import TaskFeatures


@dataclass
class GateInput:
    """Gate 的输入：路由推荐的关键信息。"""
    features: TaskFeatures
    model_name: str
    model_tier: int
    strategy: StrategyType
    estimated_cost: float
    quality: float
    quality_loss_vs_baseline: float
    budget_status: BudgetStatus
    forced_review_task: bool = False  # 任务类型在 human_review_required_tasks 中


class RoutingGate:
    """管控门禁：评估路由推荐，决定是否需要人工审核。"""

    def check_human_review(self, gate_input: GateInput) -> tuple[bool, Optional[str]]:
        """检查是否需要人工审核（设计 4.6.2 的 7 条规则）。

        Gate 是 requires_human_review 的唯一决定者。
        """
        reasons = []
        f = gate_input.features

        # 条件1: 敏感数据
        if f.sensitivity == SensitivityLevel.HIGH:
            reasons.append("任务涉及敏感数据")

        # 条件2: 高风险 + 降级/拆分策略
        if f.risk_level == RiskLevel.HIGH:
            if gate_input.strategy != StrategyType.SINGLE_MODEL or gate_input.model_tier > 1:
                reasons.append("高风险任务使用降级/拆分策略，需要人工确认")

        # 条件3: 超硬预算
        if gate_input.budget_status == BudgetStatus.OVER_HARD_BUDGET:
            reasons.append("预估成本超过硬预算上限，需审批才可执行")

        # 条件4: 软预算超限 — 仅 warning，不触发审核
        # 设计文档原话："超过软预算且用户选择保持强模型方案"才触发
        # MVP 无用户交互，不应替用户默认选择"保持强模型"

        # 条件5: 无候选模型（由 Router 直接处理，此处不检查）

        # 条件6: 质量损失超过 20%（仅对非 LOW risk 生效）
        # LOW risk 的 SIMPLE/LOW/Tier3 省钱路径不应被 Gate 锁死
        if f.risk_level != RiskLevel.LOW and gate_input.quality_loss_vs_baseline > 0.20:
            reasons.append(f"质量损失 {gate_input.quality_loss_vs_baseline:.0%} 超过阈值 20%")

        # 条件7: 任务类型强制审核
        if gate_input.forced_review_task:
            reasons.append(f"{f.category.value} 类型任务需要人工审核")

        if reasons:
            return True, "；".join(reasons)
        return False, None

    def build_quality_gate(
        self,
        features: TaskFeatures,
        requires_human_review: bool,
    ) -> list[str]:
        """构建质量门禁列表（设计 4.6.3）。

        quality_gate 和 requires_human_review 语义联动：
        如果 requires_human_review=true，quality_gate 必须包含 human_review。
        """
        # 基础门禁（按任务类型）
        base_gates = {
            "CODE_GENERATION": ["syntax_check", "ast_parse"],
            "DATA_PROCESSING": ["json_schema_check"],
            "CODE_REVIEW": ["issue_coverage_check"],
            "BUG_ANALYSIS": ["llm_judge", "fix_verification"],
            "DOCUMENTATION": ["llm_judge", "completeness_check"],
            "ARCHITECTURE": ["human_review"],
            "TEST_GENERATION": ["syntax_check"],
            "REFACTORING": ["syntax_check", "ast_parse"],
            "DEVOPS": ["syntax_check"],
            "CONVERSATION": [],
        }

        gates = list(base_gates.get(features.category.value, []))

        # output_strictness == HIGH → 追加 format_check
        if features.output_strictness.value == "HIGH":
            gates.append("format_check")

        # risk_level == HIGH → 追加 human_review
        if features.risk_level == RiskLevel.HIGH:
            gates.append("human_review")

        # verifiability == LOW → 只能靠 LLM 评分或人工
        if features.verifiability.value == "LOW":
            if features.risk_level == RiskLevel.HIGH:
                gates = ["llm_judge", "human_review"]
            else:
                gates = ["llm_judge"]

        # 关键联动：如果 requires_human_review=true，确保 human_review 在门禁中
        if requires_human_review and "human_review" not in gates:
            gates.append("human_review")

        return list(set(gates))  # 去重
