"""Phase 7续：Prompt/上下文优化建议引擎。"""

from __future__ import annotations

from airouter.config import load_models
from airouter.engine.context.compressor import Compressor, select_strategy
from airouter.engine.router.estimator import CostEstimator
from airouter.engine.router.gate import GateInput
from airouter.engine.router.router import Router
from airouter.engine.router.selector import ModelSelector
from airouter.models.enums import (
    CompressionStrategy,
    ContentType,
    ContextLayer,
    ContextLevel,
    StrategyType,
)
from airouter.models.model_registry import ModelRegistry
from airouter.models.schemas import (
    CompressionResult,
    ContextBlock,
    InputBreakdown,
    ModelAssignment,
    OptimizationSuggestion,
    OptimizeResult,
    estimate_tokens,
)

# 场景缓存命中率（设计文档 4.5.2）
SCENARIO_CACHE_RATIO: dict[str, float] = {
    "SINGLE_TURN": 0.0,
    "FIXED_PROMPT_TOOLS": 0.30,
    "AGENT_MULTI_TURN": 0.55,
    "SAME_PROJECT_REPEAT": 0.45,
    "RANDOM_CONTEXT": 0.0,
}

# 场景预估轮数
SCENARIO_ESTIMATED_TURNS: dict[str, int] = {
    "SINGLE_TURN": 1,
    "FIXED_PROMPT_TOOLS": 5,
    "AGENT_MULTI_TURN": 10,
    "SAME_PROJECT_REPEAT": 5,
    "RANDOM_CONTEXT": 1,
}

# 行分类 key → ContextLayer 映射
_LAYER_MAP: dict[str, ContextLayer] = {
    "system_prompt": ContextLayer.SYSTEM_PROMPT,
    "tool_definitions": ContextLayer.TASK_DESCRIPTION,
    "fixed_context": ContextLayer.RELATED_FILES,
    "conversation_history": ContextLayer.CONVERSATION_HISTORY,
    "dynamic_query": ContextLayer.TASK_DESCRIPTION,
}

# 行分类 key → ContentType 映射
_CONTENT_TYPE_MAP: dict[str, ContentType] = {
    "system_prompt": ContentType.PLAIN_TEXT,
    "tool_definitions": ContentType.PLAIN_TEXT,
    "fixed_context": ContentType.CODE,
    "conversation_history": ContentType.CONVERSATION,
    "dynamic_query": ContentType.PLAIN_TEXT,
}


def _zero_suggestion(category: str, title: str = "", description: str = "") -> OptimizationSuggestion:
    """创建一个无节省的建议占位。"""
    return OptimizationSuggestion(
        category=category,
        title=title or category,
        description=description or "无优化空间",
        estimated_savings=0.0,
        savings_percentage=0.0,
    )


class PromptOptimizer:
    """Prompt/上下文优化建议引擎。"""

    def __init__(self) -> None:
        self.router = Router()
        self.estimator = CostEstimator()
        self.registry = ModelRegistry(load_models())
        self.selector = ModelSelector()
        self.compressor = Compressor()

    def optimize(
        self,
        prompt: str,
        model_name: str | None = None,
        scenario: str = "SINGLE_TURN",
        expected_turns: int | None = None,
    ) -> OptimizeResult:
        """主入口：分析 prompt 并生成 5 类优化建议。"""
        # 0. 参数校验
        if scenario not in SCENARIO_CACHE_RATIO:
            valid = ", ".join(SCENARIO_CACHE_RATIO.keys())
            raise ValueError(f"未知场景 '{scenario}'。可用场景: {valid}")
        if expected_turns is not None and expected_turns < 1:
            raise ValueError(f"expected_turns 必须 >= 1，当前: {expected_turns}")

        # 1. 路由分析
        decision = self.router.route(prompt)
        features = decision.task_features

        # 2. 统一行分类
        classified = self._classify_prompt_lines(prompt)

        # 3. InputBreakdown（global_total 对齐）
        breakdown = self._analyze_breakdown(prompt, classified)

        # 4. 用真实 token 覆盖 features
        features = features.model_copy(
            update={"estimated_input_tokens": breakdown.total}
        )

        # 5. 确定当前策略 + 模型
        if model_name:
            if not self.registry.get_by_name(model_name):
                available = [m.name for m in self.registry.all_models]
                raise ValueError(
                    f"模型 '{model_name}' 不存在。可用模型: {', '.join(available)}"
                )
            current_strategy = StrategyType.SINGLE_MODEL
            current_models = ModelAssignment(executor=model_name)
        else:
            current_strategy = decision.recommended_strategy
            current_models = decision.models

        # 5b. Router escalate 检测（所有 requires_human_review 都 warning）
        requires_review = decision.requires_human_review
        escalate_warning: str | None = None
        if requires_review:
            if not current_models.executor and not current_models.planner:
                escalate_warning = "Router 判定该任务需要人工审核（无候选策略满足治理约束），优化建议仅供参考"
            else:
                escalate_warning = "Router 判定该任务需要人工审核，降级/分层建议需经审批后方可执行"

        # 6. 确定轮数
        turns = expected_turns if expected_turns is not None else SCENARIO_ESTIMATED_TURNS.get(scenario, 1)

        # 7. 当前成本
        current_cost = self._estimate_current_cost(current_strategy, current_models, features)
        scenario_cost = current_cost * turns

        # 8. 当前 executor 的 input price（压缩/裁剪建议用）
        executor_price = self._get_executor_input_price(current_models)

        # 8b. 当前 executor 质量得分（降级/分层 Gate 审批检查用）
        executor_name = current_models.executor or current_models.planner
        current_model = self.registry.get_by_name(executor_name) if executor_name else None
        current_quality = self.selector._quality_score(current_model, features) if current_model else 0.0

        # 9. 构建 ContextBlock 列表（复用 classified）
        context_blocks = self._build_context_blocks(classified)

        # 10. 生成 5 类建议
        suggestions: list[OptimizationSuggestion] = [
            self._suggest_cache(current_models, breakdown, scenario, turns, scenario_cost),
            self._suggest_compression(
                context_blocks, features, breakdown, executor_price, scenario_cost, turns,
            ),
            self._suggest_downgrade(
                features, current_strategy, current_models, scenario_cost, current_quality, turns,
            ),
            self._suggest_trimming(
                features, breakdown, executor_price, scenario_cost, turns, prompt,
            ),
            self._suggest_plan_execute(
                features, current_strategy, current_models, scenario_cost, current_quality, turns,
            ),
        ]
        suggestions = [s for s in suggestions if s.estimated_savings > 0]

        # 11. 汇总
        total_savings, optimized_cost, total_pct = self._summarize_savings(
            suggestions, scenario_cost,
        )

        warnings = [
            "各优化建议的节省金额为独立估算，不能直接全部相加",
            "汇总会比较“当前模型缓存/内容精简”和“降级/分层”路径，取较优者",
            "压缩和裁剪存在重叠，降级和分层互斥",
            "Token 组成分析为启发式估算，实际分布可能不同",
        ]
        # 审批提示：建议后方案触发 Gate 时，浮到顶层 warning
        has_approval_items = any(
            s.details.get("requires_approval") for s in suggestions
        )
        if has_approval_items and not escalate_warning:
            warnings.insert(0, "部分优化建议（降级/分层）需审批后方可执行，详见各建议详情")
        if escalate_warning:
            warnings.insert(0, escalate_warning)

        return OptimizeResult(
            current_strategy=current_strategy,
            current_models=current_models,
            current_cost=current_cost,
            scenario_cost=scenario_cost,
            scenario=scenario,
            estimated_turns=turns,
            estimated_output_tokens=features.estimated_output_tokens,
            input_breakdown=breakdown,
            suggestions=suggestions,
            total_estimated_savings=total_savings,
            optimized_cost=optimized_cost,
            total_savings_percentage=total_pct,
            warnings=warnings,
        )

    # ── 行分类 ──────────────────────────────────────────────

    def _classify_prompt_lines(self, prompt: str) -> dict[str, list[str]]:
        """统一行分类：返回 {category: [lines]}，供 breakdown 和 context_blocks 共用。"""
        result: dict[str, list[str]] = {
            "system_prompt": [],
            "tool_definitions": [],
            "fixed_context": [],
            "conversation_history": [],
            "dynamic_query": [],
        }

        in_code_fence = False
        active_section: str | None = None
        section_aliases = {
            "system": "system_prompt",
            "system prompt": "system_prompt",
            "系统": "system_prompt",
            "系统提示": "system_prompt",
            "系统指令": "system_prompt",
            "tool definitions": "tool_definitions",
            "tools": "tool_definitions",
            "工具": "tool_definitions",
            "工具定义": "tool_definitions",
            "context": "fixed_context",
            "fixed context": "fixed_context",
            "project context": "fixed_context",
            "背景": "fixed_context",
            "固定上下文": "fixed_context",
            "项目上下文": "fixed_context",
            "history": "conversation_history",
            "conversation history": "conversation_history",
            "历史对话": "conversation_history",
            "对话历史": "conversation_history",
            "request": "dynamic_query",
            "current request": "dynamic_query",
            "user request": "dynamic_query",
            "当前请求": "dynamic_query",
            "用户请求": "dynamic_query",
        }

        for line in prompt.split("\n"):
            stripped = line.strip()

            # code fence 状态机
            if stripped.startswith("```"):
                in_code_fence = not in_code_fence
                result["fixed_context"].append(line)
                continue

            if in_code_fence:
                result["fixed_context"].append(line)
                continue

            lower = stripped.lower()

            # 支持自然的分节 Prompt。标题后的正文沿用该分类，直到出现下一节。
            # 例如“对话历史：”下的中文内容不必每行都写 User:/Assistant:。
            normalized_header = lower.lstrip("#").strip().rstrip(":：").strip()
            section = section_aliases.get(normalized_header)
            if section:
                active_section = section
                result[section].append(line)
                continue

            if active_section is not None:
                result[active_section].append(line)
                continue

            if any(kw in lower for kw in ("you are", "你是", "system:", "系统:", "系统：", "# system", "作为")):
                result["system_prompt"].append(line)
            elif any(kw in lower for kw in ("function", "tool", "工具", "parameters", "参数", "schema")):
                result["tool_definitions"].append(line)
            elif any(
                kw in lower
                for kw in (
                    "user:", "用户:", "用户：", "assistant:", "助手:", "助手：",
                    "human:", "human：", "ai:", "ai：", "[user]", "[assistant]",
                )
            ):
                result["conversation_history"].append(line)
            elif any(kw in lower for kw in ("import ", "def ", "class ", "<file", "文件", "---")):
                result["fixed_context"].append(line)
            else:
                result["dynamic_query"].append(line)

        return result

    # ── InputBreakdown ──────────────────────────────────────

    def _analyze_breakdown(self, prompt: str, classified: dict[str, list[str]]) -> InputBreakdown:
        """从分类结果算 token 数，dynamic_query 用 global_total - accounted 对齐。"""
        global_total = estimate_tokens(prompt)

        system_prompt_tokens = sum(estimate_tokens(line) for line in classified["system_prompt"])
        tool_definitions_tokens = sum(estimate_tokens(line) for line in classified["tool_definitions"])
        fixed_context_tokens = sum(estimate_tokens(line) for line in classified["fixed_context"])
        conversation_history_tokens = sum(estimate_tokens(line) for line in classified["conversation_history"])

        accounted = system_prompt_tokens + tool_definitions_tokens + fixed_context_tokens + conversation_history_tokens
        dynamic_query_tokens = max(0, global_total - accounted)

        return InputBreakdown(
            system_prompt_tokens=system_prompt_tokens,
            tool_definitions_tokens=tool_definitions_tokens,
            fixed_context_tokens=fixed_context_tokens,
            conversation_history_tokens=conversation_history_tokens,
            dynamic_query_tokens=dynamic_query_tokens,
        )

    # ── ContextBlock 构建 ───────────────────────────────────

    def _build_context_blocks(self, classified: dict[str, list[str]]) -> list[ContextBlock]:
        """从分类结果构建 ContextBlock，每个分类一块。"""
        blocks: list[ContextBlock] = []
        for key, lines in classified.items():
            if not lines:
                continue
            content = "\n".join(lines)
            blocks.append(ContextBlock(
                layer=_LAYER_MAP[key],
                content_type=_CONTENT_TYPE_MAP[key],
                content=content,
            ))
        return blocks

    # ── 成本计算 ────────────────────────────────────────────

    def _estimate_current_cost(
        self, strategy: StrategyType, models: ModelAssignment, features
    ) -> float:
        """基于修正后 features 计算当前方案成本。"""
        estimate = self.estimator.estimate_strategy_cost(
            strategy=strategy, model_assignment=models, features=features, registry=self.registry,
        )
        return estimate.total_cost

    def _get_executor_input_price(self, models: ModelAssignment) -> float:
        """从 current_models 获取 executor 的 input price。"""
        name = models.executor or models.planner
        if not name:
            return 0.0
        model = self.registry.get_by_name(name)
        return model.input_price_per_1k if model else 0.0

    # ── Gate 审批检查 ──────────────────────────────────────

    def _check_suggestion_approval(
        self,
        features,
        suggested_model_name: str,
        suggested_strategy: StrategyType,
        suggested_cost: float,
        baseline_quality: float,
        suggested_quality: float,
    ) -> bool:
        """对优化建议的方案跑 Gate，返回是否需要审批。"""
        suggested_model = self.registry.get_by_name(suggested_model_name)
        if not suggested_model:
            return False

        quality_loss = max(0.0, baseline_quality - suggested_quality)
        forced_review = features.category.value in self.router._routing_rules.human_review_required_tasks
        budget_status, _ = self.selector._compute_budget_status(suggested_cost, features)

        gate_input = GateInput(
            features=features,
            model_name=suggested_model_name,
            model_tier=suggested_model.tier,
            strategy=suggested_strategy,
            estimated_cost=suggested_cost,
            quality=suggested_quality,
            quality_loss_vs_baseline=quality_loss,
            budget_status=budget_status,
            forced_review_task=forced_review,
        )
        requires, _ = self.router.gate.check_human_review(gate_input)
        return bool(requires)

    # ── Savings 汇总 ────────────────────────────────────────

    @staticmethod
    def _summarize_savings(
        suggestions: list[OptimizationSuggestion], current_cost: float,
    ) -> tuple[float, float, float]:
        """汇总优化建议，避免把不同模型路径的节省重复相加。

        当前模型路径可组合缓存与内容精简；压缩和裁剪有重叠，只取较大值。
        降级与 Plan-Execute 会改变模型/策略，其节省与当前模型路径不直接相加。
        最终在这两条路径之间取较优者，作为保守参考值。

        Returns: (total_savings, optimized_cost, total_pct)
        """
        cache_savings = sum(
            s.estimated_savings for s in suggestions if s.category == "缓存"
        )
        content_savings = max(
            (
                s.estimated_savings
                for s in suggestions
                if s.category in ("压缩", "裁剪")
            ),
            default=0.0,
        )
        current_model_path = cache_savings + content_savings
        exclusive = max(
            (s.estimated_savings for s in suggestions if s.category in ("降级", "分层")),
            default=0.0,
        )
        raw_savings = max(current_model_path, exclusive)
        total_savings = min(current_cost, raw_savings)
        optimized_cost = max(0.0, current_cost - total_savings)
        total_pct = total_savings / current_cost if current_cost > 0 else 0.0
        return total_savings, optimized_cost, total_pct

    # ── 缓存建议 ────────────────────────────────────────────

    def _suggest_cache(
        self,
        models: ModelAssignment,
        breakdown: InputBreakdown,
        scenario: str,
        turns: int,
        current_cost: float,
    ) -> OptimizationSuggestion:
        """缓存建议：严格按设计文档 estimate_cache_adjustment()。"""
        # 取 executor 模型
        name = models.executor or models.planner
        if not name:
            return _zero_suggestion("缓存", "固定前缀缓存", "无法确定当前模型")

        model = self.registry.get_by_name(name)
        if not model:
            return _zero_suggestion("缓存", "固定前缀缓存", "模型未找到")

        # 检查缓存支持
        if not model.cache.is_caching_effective:
            return _zero_suggestion("缓存", "固定前缀缓存", "模型不支持或未验证 Prompt Caching")

        stable_prefix = breakdown.stable_prefix
        if stable_prefix < model.cache.cache_min_prefix_tokens:
            return _zero_suggestion(
                "缓存", "固定前缀缓存",
                f"稳定前缀 {stable_prefix} tokens < 最小缓存长度 {model.cache.cache_min_prefix_tokens}",
            )

        cacheable_ratio = SCENARIO_CACHE_RATIO.get(scenario, 0.0)
        if cacheable_ratio == 0:
            return _zero_suggestion("缓存", "固定前缀缓存", f"场景 {scenario} 无缓存收益")

        base_input_price = model.input_price_per_1k / 1000

        # 首次缓存写入的额外成本
        cache_write_premium = stable_prefix * base_input_price * (model.cache.cache_write_price_multiplier - 1)

        # 后续每次调用的缓存读取节省
        cache_read_savings_per_turn = stable_prefix * base_input_price * (1 - model.cache.cache_read_price_ratio)

        # 净节省
        net_savings = (turns - 1) * cacheable_ratio * cache_read_savings_per_turn - cache_write_premium
        net_savings = max(0.0, net_savings)

        if net_savings <= 0:
            return _zero_suggestion("缓存", "固定前缀缓存", "缓存写入成本超过读取节省")

        pct = net_savings / current_cost if current_cost > 0 else 0.0

        return OptimizationSuggestion(
            category="缓存",
            title="固定前缀缓存",
            description=f"稳定前缀 {stable_prefix} tokens 可缓存，预估 {turns} 轮",
            estimated_savings=net_savings,
            savings_percentage=pct,
            details={
                "stable_prefix_tokens": stable_prefix,
                "scenario": scenario,
                "estimated_turns": turns,
                "cacheable_ratio": cacheable_ratio,
                "cache_write_premium": round(cache_write_premium, 6),
                "cache_read_savings_per_turn": round(cache_read_savings_per_turn, 6),
                "model_supports_caching": True,
            },
        )

    # ── 压缩建议 ────────────────────────────────────────────

    def _suggest_compression(
        self,
        blocks: list[ContextBlock],
        features,
        breakdown: InputBreakdown,
        executor_price: float,
        current_cost: float,
        turns: int = 1,
    ) -> OptimizationSuggestion:
        """压缩建议：真正调用 Compressor，展示 3 策略对比。"""
        if not blocks:
            return _zero_suggestion("压缩", "上下文压缩", "无可压缩内容")

        risk_level = features.risk_level

        # 跑 3 种策略
        results: dict[CompressionStrategy, CompressionResult] = {}
        for strategy in [CompressionStrategy.CONSERVATIVE, CompressionStrategy.STANDARD, CompressionStrategy.AGGRESSIVE]:
            result = self.compressor.compress(blocks, risk_level=risk_level, strategy_override=strategy)
            results[strategy] = result

        # 自动推荐策略
        auto_strategy = select_strategy(
            risk_level, breakdown.total, self.compressor.policy.context_length_thresholds,
        )
        comparison = {}
        for s, r in results.items():
            comparison[s.value] = {
                "compressed_tokens": r.compressed_tokens,
                "reduction_rate": round(r.reduction_rate, 4),
            }

        if auto_strategy == CompressionStrategy.NONE:
            return OptimizationSuggestion(
                category="压缩",
                title="上下文压缩",
                description=f"当前上下文 {breakdown.total} tokens 未达到主动压缩阈值",
                estimated_savings=0.0,
                savings_percentage=0.0,
                details={
                    "auto_strategy": auto_strategy.value,
                    "comparison": comparison,
                },
            )

        best = results.get(auto_strategy, results[CompressionStrategy.STANDARD])

        savings_tokens = best.original_tokens - best.compressed_tokens
        savings = savings_tokens / 1000 * executor_price * turns
        pct = savings / current_cost if current_cost > 0 else 0.0

        return OptimizationSuggestion(
            category="压缩",
            title="上下文压缩",
            description=f"自动推荐 {auto_strategy.value} 策略",
            estimated_savings=savings,
            savings_percentage=pct,
            details={
                "auto_strategy": auto_strategy.value,
                "comparison": comparison,
                "applied_actions": best.applied_actions,
                "original_tokens": best.original_tokens,
                "compressed_tokens": best.compressed_tokens,
            },
        )

    # ── 降级建议 ────────────────────────────────────────────

    def _suggest_downgrade(
        self,
        features,
        current_strategy: StrategyType,
        current_models: ModelAssignment,
        current_cost: float,
        current_quality: float = 0.0,
        turns: int = 1,
    ) -> OptimizationSuggestion:
        """降级建议：使用完整路由硬约束过滤（capabilities + allowed_tiers + context window + sensitivity）。"""
        executor_name = current_models.executor or current_models.planner
        if not executor_name:
            return _zero_suggestion("降级", "模型降级", "无法确定当前模型")

        current_model = self.registry.get_by_name(executor_name)
        if not current_model or current_model.tier >= 3:
            return _zero_suggestion("降级", "模型降级", "当前已是最低 Tier 或无更低 Tier 模型")

        # 使用完整过滤（capabilities + allowed_tiers + context window + sensitivity）
        filtered = self.selector.filter_candidates(self.registry.all_models, features)

        # 找低 tier 候选（tier > current，tier <= 3）
        lower_tier_candidates = [
            m for m in filtered if m.tier > current_model.tier and m.tier <= 3
        ]
        if not lower_tier_candidates:
            return _zero_suggestion("降级", "模型降级", "无符合条件的低 Tier 模型")

        # 按 input + output 总成本排序
        def total_price(m):
            return m.input_price_per_1k + m.output_price_per_1k

        cheapest = min(lower_tier_candidates, key=total_price)

        # 用修正后 features 重新算成本
        new_models = ModelAssignment(executor=cheapest.name)
        new_cost_per_turn = self.estimator.estimate_strategy_cost(
            StrategyType.SINGLE_MODEL, new_models, features, self.registry,
        ).total_cost
        new_cost = new_cost_per_turn * turns

        savings = max(0.0, current_cost - new_cost)
        pct = savings / current_cost if current_cost > 0 else 0.0

        # 基于建议后的方案跑 Gate，判断是否需要审批
        suggested_quality = self.selector._quality_score(cheapest, features)
        requires_approval = self._check_suggestion_approval(
            features, cheapest.name, StrategyType.SINGLE_MODEL,
            new_cost, current_quality, suggested_quality,
        )

        return OptimizationSuggestion(
            category="降级",
            title="模型降级",
            description=f"Tier {current_model.tier} → Tier {cheapest.tier} ({cheapest.name})",
            estimated_savings=savings,
            savings_percentage=pct,
            details={
                "current_model": current_model.name,
                "current_tier": current_model.tier,
                "suggested_model": cheapest.name,
                "suggested_tier": cheapest.tier,
                "new_cost": round(new_cost, 6),
                "new_cost_per_turn": round(new_cost_per_turn, 6),
                "requires_approval": requires_approval,
            },
        )

    # ── 裁剪建议 ────────────────────────────────────────────

    def _suggest_trimming(
        self,
        features,
        breakdown: InputBreakdown,
        executor_price: float,
        current_cost: float,
        turns: int = 1,
        prompt: str = "",
    ) -> OptimizationSuggestion:
        """裁剪建议：移除冗余固定上下文。"""
        # 只在 HEAVY/EXTREME 上下文时建议裁剪
        if features.context_requirement not in (ContextLevel.HEAVY, ContextLevel.EXTREME):
            return _zero_suggestion("裁剪", "上下文裁剪", "上下文长度正常，无需裁剪")

        fixed_tokens = breakdown.fixed_context_tokens
        if fixed_tokens <= 0:
            return _zero_suggestion("裁剪", "上下文裁剪", "无可裁剪的固定上下文")

        # 裁剪 30%-50% 的固定上下文
        trim_ratio = 0.3 if features.context_requirement == ContextLevel.HEAVY else 0.5
        trim_tokens = int(fixed_tokens * trim_ratio)
        savings = trim_tokens / 1000 * executor_price * turns
        pct = savings / current_cost if current_cost > 0 else 0.0
        evidence = self._build_trimming_evidence(prompt, trim_tokens, trim_ratio)

        return OptimizationSuggestion(
            category="裁剪",
            title="上下文裁剪",
            description=f"摘要或移除固定上下文候选 (~{trim_tokens} tokens)",
            estimated_savings=savings,
            savings_percentage=pct,
            details={
                "trimmable_tokens": fixed_tokens,
                "trim_ratio": trim_ratio,
                "trimmed_tokens": trim_tokens,
                "evidence": evidence,
                "evidence_method": "启发式定位，执行前需确认",
            },
        )

    def _build_trimming_evidence(
        self,
        prompt: str,
        trim_tokens: int,
        trim_ratio: float,
    ) -> list[dict[str, object]]:
        """定位固定上下文中的裁剪候选，不把启发式预算伪装成语义重复检测。"""
        if not prompt or trim_tokens <= 0:
            return []

        fixed_section_aliases = {
            "context",
            "fixed context",
            "project context",
            "背景",
            "固定上下文",
            "项目上下文",
        }
        all_section_aliases = fixed_section_aliases | {
            "system",
            "system prompt",
            "系统",
            "系统提示",
            "系统指令",
            "tool definitions",
            "tools",
            "工具",
            "工具定义",
            "history",
            "conversation history",
            "历史对话",
            "对话历史",
            "request",
            "current request",
            "user request",
            "当前请求",
            "用户请求",
        }

        lines = prompt.splitlines()
        normalized_occurrences: dict[str, list[int]] = {}
        for line_no, line in enumerate(lines, 1):
            normalized = " ".join(line.split()).casefold()
            if normalized:
                normalized_occurrences.setdefault(normalized, []).append(line_no)

        records: list[tuple[int, str, str]] = []
        active_section: str | None = None
        in_code_fence = False

        for line_no, line in enumerate(lines, 1):
            stripped = line.strip()
            normalized_header = stripped.casefold().lstrip("#").strip().rstrip(":：").strip()

            if normalized_header in all_section_aliases:
                active_section = (
                    "fixed_context"
                    if normalized_header in fixed_section_aliases
                    else "other"
                )
                continue

            if stripped.startswith("```"):
                in_code_fence = not in_code_fence
                records.append((line_no, line, "代码块"))
                continue

            if in_code_fence:
                records.append((line_no, line, "代码块"))
            elif active_section == "fixed_context" and stripped:
                records.append((line_no, line, "项目上下文"))
            elif active_section is not None:
                continue
            elif stripped and any(
                marker in stripped.casefold()
                for marker in ("import ", "def ", "class ", "<file", "文件")
            ):
                records.append((line_no, line, "文件或代码上下文"))

        if not records:
            return []

        groups: list[list[tuple[int, str, str]]] = []
        for record in records:
            if (
                groups
                and record[0] == groups[-1][-1][0] + 1
                and record[2] == groups[-1][-1][2]
            ):
                groups[-1].append(record)
            else:
                groups.append([record])

        candidates: list[dict[str, object]] = []
        remaining = trim_tokens
        for group in sorted(groups, key=lambda item: sum(estimate_tokens(r[1]) for r in item), reverse=True):
            if remaining <= 0:
                break

            group_text = "\n".join(record[1] for record in group).strip()
            group_tokens = max(1, estimate_tokens(group_text))
            estimated_reduction = min(
                remaining,
                max(1, int(group_tokens * trim_ratio)),
            )
            duplicate_line: int | None = None
            for line_no, line, _ in group:
                normalized = " ".join(line.split()).casefold()
                occurrences = normalized_occurrences.get(normalized, [])
                other_lines = [candidate for candidate in occurrences if candidate != line_no]
                if other_lines:
                    duplicate_line = other_lines[0]
                    break

            if duplicate_line is not None:
                reason = f"与第 {duplicate_line} 行内容完全重复，可优先去重"
                confidence = "确定性重复"
            else:
                reason = (
                    f"{group[0][2]}属于半固定输入；当前按 {trim_ratio:.0%} "
                    "启发式预算建议优先摘要，未证明语义重复"
                )
                confidence = "启发式候选"

            excerpt = " ".join(group_text.split())
            if len(excerpt) > 180:
                excerpt = excerpt[:177] + "..."

            candidates.append(
                {
                    "line_start": group[0][0],
                    "line_end": group[-1][0],
                    "source": group[0][2],
                    "excerpt": excerpt,
                    "reason": reason,
                    "confidence": confidence,
                    "estimated_reduction_tokens": estimated_reduction,
                }
            )
            remaining -= estimated_reduction

        return candidates

    # ── Plan-Execute 建议 ───────────────────────────────────

    def _suggest_plan_execute(
        self,
        features,
        current_strategy: StrategyType,
        current_models: ModelAssignment,
        current_cost: float,
        current_quality: float = 0.0,
        turns: int = 1,
    ) -> OptimizationSuggestion:
        """Plan-Execute 建议：使用完整路由硬约束过滤 + subtasks >= 2。"""
        if current_strategy in (StrategyType.PLAN_EXECUTE, StrategyType.PLAN_EXECUTE_REVIEW):
            return _zero_suggestion("分层", "Plan-Execute 策略", "当前已使用分层策略")

        if len(features.subtasks) < 2:
            return _zero_suggestion("分层", "Plan-Execute 策略", "子任务少于 2 个，分层开销不划算")

        # 使用完整过滤（capabilities + allowed_tiers + context window + sensitivity）
        filtered = self.selector.filter_candidates(self.registry.all_models, features)

        tier1 = [m for m in filtered if m.tier == 1]
        tier23 = [m for m in filtered if m.tier in (2, 3)]

        if not tier1 or not tier23:
            return _zero_suggestion("分层", "Plan-Execute 策略", "无合适的 Planner/Executor 组合")

        def total_price(m):
            return m.input_price_per_1k + m.output_price_per_1k

        planner = min(tier1, key=total_price)
        executor = min(tier23, key=total_price)

        pe_models = ModelAssignment(planner=planner.name, executor=executor.name)
        pe_cost_per_turn = self.estimator.estimate_strategy_cost(
            StrategyType.PLAN_EXECUTE, pe_models, features, self.registry,
        ).total_cost
        pe_cost = pe_cost_per_turn * turns

        savings = max(0.0, current_cost - pe_cost)
        pct = savings / current_cost if current_cost > 0 else 0.0

        # 基于建议后的方案跑 Gate，判断是否需要审批
        planner_q = self.selector._quality_score(planner, features)
        executor_q = self.selector._quality_score(executor, features)
        suggested_quality = self.selector._strategy_quality(
            StrategyType.PLAN_EXECUTE, planner_q, executor_q, 0.0, len(features.subtasks),
        )
        requires_approval = self._check_suggestion_approval(
            features, executor.name, StrategyType.PLAN_EXECUTE,
            pe_cost, current_quality, suggested_quality,
        )

        return OptimizationSuggestion(
            category="分层",
            title="Plan-Execute 策略",
            description=f"Planner: {planner.name} (Tier 1), Executor: {executor.name} (Tier {executor.tier})",
            estimated_savings=savings,
            savings_percentage=pct,
            details={
                "planner": planner.name,
                "executor": executor.name,
                "num_subtasks": len(features.subtasks),
                "pe_cost": round(pe_cost, 6),
                "pe_cost_per_turn": round(pe_cost_per_turn, 6),
                "requires_approval": requires_approval,
            },
        )
