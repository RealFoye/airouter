"""CostEstimator：成本预估（基础成本 + 缓存调整）。"""

from __future__ import annotations

from pydantic import BaseModel

from airouter.config import ModelEntry


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
    """成本预估器。Week 1 MVP：基础成本计算，缓存调整简化。"""

    def estimate(
        self,
        model: ModelEntry,
        input_tokens: int,
        output_tokens: int,
    ) -> CostEstimate:
        """计算单次调用的成本预估。"""
        # 基础成本
        input_cost = (input_tokens / 1000.0) * model.input_price_per_1k
        output_cost = (output_tokens / 1000.0) * model.output_price_per_1k

        # 缓存调整（Week 1 简化：不计算缓存收益）
        cache_savings = 0.0

        total_cost = input_cost + output_cost - cache_savings

        return CostEstimate(
            input_cost=input_cost,
            output_cost=output_cost,
            cache_savings=cache_savings,
            total_cost=total_cost,
        )

    def estimate_strategy_cost(
        self,
        models: list[ModelEntry],
        input_tokens: int,
        output_tokens: int,
        num_calls: int = 1,
    ) -> float:
        """估算多模型策略的总成本（简化版：所有模型用相同 token 数）。"""
        total = 0.0
        for model in models:
            est = self.estimate(model, input_tokens, output_tokens)
            total += est.total_cost
        return total * num_calls
