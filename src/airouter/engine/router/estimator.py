"""CostEstimator：成本预估（基础成本 + 策略级成本 + Plan-Execute 上下文局部化）。"""

from __future__ import annotations

from pydantic import BaseModel

from airouter.config import ModelEntry
from airouter.models.enums import StrategyType
from airouter.models.schemas import ModelAssignment, TaskFeatures


class CostEstimate(BaseModel):
    input_cost: float
    output_cost: float
    cache_savings: float
    total_cost: float

    @property
    def per_1k_input(self) -> float:
        return self.input_cost

    @property
    def per_1k_output(self) -> float:
        return self.output_cost


class CostEstimator:
    """成本预估器：基础成本 + 策略级成本（含 Plan-Execute 上下文局部化）。"""

    def estimate(
        self,
        model: ModelEntry,
        input_tokens: int,
        output_tokens: int,
    ) -> CostEstimate:
        """计算单次调用的成本预估。"""
        input_cost = (input_tokens / 1000.0) * model.input_price_per_1k
        output_cost = (output_tokens / 1000.0) * model.output_price_per_1k
        cache_savings = 0.0
        total_cost = input_cost + output_cost - cache_savings

        return CostEstimate(
            input_cost=input_cost,
            output_cost=output_cost,
            cache_savings=cache_savings,
            total_cost=total_cost,
        )

    # ── 策略级成本估算 ────────────────────────────────────────
    def estimate_strategy_cost(
        self,
        strategy: StrategyType,
        model_assignment: ModelAssignment,
        features: TaskFeatures,
        registry,
    ) -> CostEstimate:
        """根据策略类型 dispatch 到具体成本函数。

        registry: ModelRegistry，用于从模型名查找 ModelEntry。
        """
        if strategy == StrategyType.SINGLE_MODEL:
            model = registry.get_by_name(model_assignment.executor or "")
            if not model:
                return CostEstimate(input_cost=0, output_cost=0, cache_savings=0, total_cost=0)
            return self.estimate(model, features.estimated_input_tokens, features.estimated_output_tokens)

        if strategy == StrategyType.GUIDED_EXECUTE:
            executor = registry.get_by_name(model_assignment.executor or "")
            reviewer = registry.get_by_name(model_assignment.reviewer or "")
            if not executor:
                return CostEstimate(input_cost=0, output_cost=0, cache_savings=0, total_cost=0)
            exec_cost = self.estimate(executor, features.estimated_input_tokens, features.estimated_output_tokens)
            review_cost = self.estimate_review_cost(reviewer, features) if reviewer else 0.0
            return CostEstimate(
                input_cost=exec_cost.input_cost,
                output_cost=exec_cost.output_cost + review_cost,
                cache_savings=0.0,
                total_cost=exec_cost.total_cost + review_cost,
            )

        if strategy == StrategyType.PLAN_EXECUTE:
            planner = registry.get_by_name(model_assignment.planner or "")
            executor = registry.get_by_name(model_assignment.executor or "")
            if not planner or not executor:
                return CostEstimate(input_cost=0, output_cost=0, cache_savings=0, total_cost=0)
            total = self.estimate_plan_execute_cost(planner, executor, features)
            return CostEstimate(input_cost=total, output_cost=0, cache_savings=0, total_cost=total)

        if strategy == StrategyType.PLAN_EXECUTE_REVIEW:
            planner = registry.get_by_name(model_assignment.planner or "")
            executor = registry.get_by_name(model_assignment.executor or "")
            reviewer = registry.get_by_name(model_assignment.reviewer or "")
            if not planner or not executor:
                return CostEstimate(input_cost=0, output_cost=0, cache_savings=0, total_cost=0)
            pe_cost = self.estimate_plan_execute_cost(planner, executor, features)
            review_cost = self.estimate_review_cost(reviewer, features) if reviewer else 0.0
            return CostEstimate(
                input_cost=pe_cost,
                output_cost=review_cost,
                cache_savings=0.0,
                total_cost=pe_cost + review_cost,
            )

        return CostEstimate(input_cost=0, output_cost=0, cache_savings=0, total_cost=0)

    # ── Plan-Execute 成本（设计文档 4.5.3） ──────────────────
    def estimate_plan_execute_cost(
        self, planner: ModelEntry, executor: ModelEntry, features: TaskFeatures
    ) -> float:
        """Plan-Execute 成本：Planner 全局规划 + Executor 局部执行。

        上下文局部化：每个子任务只看 35% 全局上下文，有重叠修正。
        """
        num_subtasks = max(1, len(features.subtasks))

        # Planner（Tier 1）：看全局上下文
        planner_input = features.estimated_input_tokens + 500  # +system prompt
        planner_output = int(features.estimated_output_tokens * 0.15)  # 计划文本较短
        planner_cost = self._base_cost(planner, planner_input, planner_output)

        # Executor（Tier 2/3）：每个子任务只看局部上下文
        subtask_context_ratio = 0.35
        overlap_factor = 0.7
        total_executor_context = min(
            features.estimated_input_tokens * 0.9,  # 硬上限：不超过全局的 90%
            features.estimated_input_tokens * subtask_context_ratio * num_subtasks * overlap_factor,
        )
        executor_input_per_call = int(
            total_executor_context / num_subtasks
            + planner_output / num_subtasks  # 相关的计划片段
            + 300  # 指令 token
        )
        executor_output_per_call = features.estimated_output_tokens / num_subtasks

        executor_cost_per_call = self._base_cost(executor, executor_input_per_call, executor_output_per_call)
        total_executor_cost = executor_cost_per_call * num_subtasks

        return planner_cost + total_executor_cost

    # ── 审查成本 ──────────────────────────────────────────────
    def estimate_review_cost(self, reviewer: ModelEntry | None, features: TaskFeatures) -> float:
        """审查成本：reviewer 看 executor 输出 + 原始需求摘要 + 审查 prompt。

        reviewer_input = executor_output + min(2000, input * 0.15) + 500
        reviewer_output = max(300, min(800, executor_output * 0.10))
        """
        if not reviewer:
            return 0.0

        executor_output_tokens = features.estimated_output_tokens
        review_input = (
            executor_output_tokens
            + min(2000, int(features.estimated_input_tokens * 0.15))
            + 500
        )
        review_output = max(300, min(800, int(executor_output_tokens * 0.10)))

        return self._base_cost(reviewer, review_input, review_output)

    # ── 内部工具 ──────────────────────────────────────────────
    def _base_cost(self, model: ModelEntry, input_tokens: int | float, output_tokens: int | float) -> float:
        return (input_tokens / 1000.0) * model.input_price_per_1k + (output_tokens / 1000.0) * model.output_price_per_1k
