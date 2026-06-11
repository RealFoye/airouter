"""TaskAnalyzer：关键词模式提取任务特征（13维）。"""

from __future__ import annotations

import re

from airouter.engine.router.rule_logic import infer_complexity as _rule_infer_complexity
from airouter.models.enums import (
    ComplexityLevel,
    ContextLevel,
    OutputStrictnessLevel,
    ReasoningLevel,
    RiskLevel,
    SensitivityLevel,
    TaskCategory,
    VerifiabilityLevel,
)
from airouter.models.schemas import CAPABILITY_REQUIREMENTS, TaskFeatures

# ── 关键词规则（10 类别） ───────────────────────────────────
# 权重：高特异性词权重高（3），通用词权重低（1）
KEYWORD_RULES: dict[TaskCategory, list[tuple[str, float]]] = {
    TaskCategory.ARCHITECTURE: [
        ("架构", 3), ("微服务", 3), ("分布式", 3), ("高并发", 3), ("百万", 2),
        ("scalability", 3), ("可扩展", 2), ("消息队列", 2),
        ("设计", 1), ("系统", 1), ("网关", 2),
    ],
    TaskCategory.BUG_ANALYSIS: [
        ("bug", 3), ("debug", 3), ("死锁", 3), ("内存泄漏", 3), ("crash", 3),
        ("崩溃", 3), ("堆栈", 3), ("报错", 2), ("异常", 2),
        ("错误", 1), ("修复", 1), ("问题", 1), ("卡死", 2), ("leak", 3),
    ],
    TaskCategory.CODE_REVIEW: [
        ("审查", 3), ("review", 3), ("code smell", 3), ("lint", 3),
        ("代码质量", 3), ("安全检查", 2), ("代码规范", 2),
        ("最佳实践", 2), ("合规", 2),
    ],
    TaskCategory.CODE_GENERATION: [
        ("写", 3), ("实现", 3), ("开发", 2), ("创建", 2), ("新增", 2),
        ("编写", 2), ("构建", 1), ("生成", 2), ("make", 2),
        ("build", 2), ("create", 2), ("implement", 3), ("add", 1),
    ],
    TaskCategory.REFACTORING: [
        ("重构", 3), ("拆分", 2), ("解耦", 3), ("优化代码", 3),
        ("God Class", 3), ("策略模式", 3), ("重命名", 2),
        ("合并", 1), ("提取", 1), ("迁移", 1), ("升级", 1),
    ],
    TaskCategory.DOCUMENTATION: [
        ("文档", 3), ("README", 3), ("API文档", 3), ("OpenAPI", 3),
        ("手册", 3), ("使用手册", 3), ("使用指南", 3), ("教程", 3), ("tutorial", 3),
        ("注释", 2), ("说明", 1),
    ],
    TaskCategory.TEST_GENERATION: [
        ("测试", 3), ("test", 3), ("单元测试", 3), ("集成测试", 3),
        ("pytest", 3), ("jest", 3), ("覆盖率", 3), ("mock", 2), ("fixture", 2),
    ],
    TaskCategory.DATA_PROCESSING: [
        ("ETL", 3), ("CSV", 3), ("数据处理", 3), ("数据清洗", 3),
        ("JSON", 1), ("解析", 2), ("转换", 1), ("批量", 2),
        ("导入", 1), ("导出", 1), ("脚本", 1),
    ],
    TaskCategory.DEVOPS: [
        ("Docker", 3), ("部署", 3), ("CI/CD", 3), ("Kubernetes", 3),
        ("K8s", 3), ("Nginx", 3), ("运维", 3), ("监控", 2), ("告警", 3),
        ("配置", 1), ("日志", 1),
    ],
    TaskCategory.CONVERSATION: [
        ("解释", 3), ("什么是", 3), ("如何理解", 3), ("对比", 2),
        ("区别", 2), ("原理", 2), ("概念", 2), ("为什么", 2), ("GIL", 3),
    ],
}


# ── 复杂度推断规则（已抽取到 rule_logic.py） ─────────────────


# ── 风险等级推断规则 ────────────────────────────────────────
HIGH_RISK_KEYWORDS = [
    "权限", "鉴权", "支付", "财务", "删除", "生产", "线上",
    "数据库迁移", "migration", "核心", "关键", "安全",
    "架构", "微服务", "系统", "登录", "OAuth", "MFA",
]
MEDIUM_RISK_KEYWORDS = [
    "重构", "升级", "修改", "更新", "审查", "review", "拆分", "解耦",
]


# ── 敏感性推断规则 ──────────────────────────────────────────
HIGH_SENSITIVITY_KEYWORDS = [
    "密码", "token", "密钥", "个人隐私", "身份证", "手机号",
    "银行卡", "财务数据", "薪资", "权限",
]
MEDIUM_SENSITIVITY_KEYWORDS = [
    "用户数据", "邮箱", "日志", "内部",
]


# ── 上下文需求推断规则 ──────────────────────────────────────
HEAVY_CONTEXT_KEYWORDS = [
    "整个项目", "所有文件", "全局", "跨模块", "完整",
]
STANDARD_CONTEXT_KEYWORDS = [
    "相关文件", "相关模块", "依赖", "接口",
]


class TaskAnalyzer:
    """基于关键词规则的任务特征提取器。"""

    def extract_features(self, task_description: str) -> TaskFeatures:
        desc = task_description.strip()
        desc_lower = desc.lower()

        # 1. 类别推断
        category = self._infer_category(desc, desc_lower)

        # 2. 复杂度推断
        complexity = self._infer_complexity(desc, desc_lower)

        # 3. 风险等级
        risk_level = self._infer_risk_level(desc, desc_lower)

        # 4. 敏感性
        sensitivity = self._infer_sensitivity(desc, desc_lower)

        # 5. 可验证性
        verifiability = self._infer_verifiability(category, complexity)

        # 6. 输出严格度
        output_strictness = self._infer_output_strictness(category, desc_lower)

        # 7. 上下文需求
        context_requirement = self._infer_context_requirement(desc, desc_lower, complexity)

        # 8. 推理强度
        reasoning_intensity = self._infer_reasoning_intensity(category, complexity)

        # 9. Token 预估
        estimated_input_tokens = self._estimate_input_tokens(context_requirement)
        estimated_output_tokens = self._estimate_output_tokens(complexity)

        # 10. 子任务（COMPLEX/EXPERT 才提取）
        subtasks = self._extract_subtasks(desc, complexity)

        # 11. 能力需求（从 CAPABILITY_REQUIREMENTS 查表）
        cap_key = (category, complexity)
        required_caps, preferred_caps = CAPABILITY_REQUIREMENTS.get(
            cap_key, (set(), set())
        )

        return TaskFeatures(
            category=category,
            complexity=complexity,
            risk_level=risk_level,
            sensitivity=sensitivity,
            verifiability=verifiability,
            output_strictness=output_strictness,
            context_requirement=context_requirement,
            reasoning_intensity=reasoning_intensity,
            estimated_input_tokens=estimated_input_tokens,
            estimated_output_tokens=estimated_output_tokens,
            subtasks=subtasks,
            required_capabilities=required_caps,
            preferred_capabilities=preferred_caps,
        )

    def _infer_category(self, desc: str, desc_lower: str) -> TaskCategory:
        scores: dict[TaskCategory, float] = {}
        for category, keywords in KEYWORD_RULES.items():
            score = 0.0
            for kw, weight in keywords:
                if kw.lower() in desc_lower or kw in desc:
                    score += weight
            if score > 0:
                scores[category] = score

        if not scores:
            return TaskCategory.CONVERSATION  # fallback

        return max(scores, key=lambda k: scores[k])

    def _infer_complexity(self, desc: str, desc_lower: str) -> ComplexityLevel:
        return _rule_infer_complexity(desc, desc_lower)

    def _infer_risk_level(self, desc: str, desc_lower: str) -> RiskLevel:
        for kw in HIGH_RISK_KEYWORDS:
            if kw.lower() in desc_lower or kw in desc:
                return RiskLevel.HIGH
        for kw in MEDIUM_RISK_KEYWORDS:
            if kw.lower() in desc_lower or kw in desc:
                return RiskLevel.MEDIUM
        return RiskLevel.LOW

    def _infer_sensitivity(self, desc: str, desc_lower: str) -> SensitivityLevel:
        for kw in HIGH_SENSITIVITY_KEYWORDS:
            if kw.lower() in desc_lower or kw in desc:
                return SensitivityLevel.HIGH
        for kw in MEDIUM_SENSITIVITY_KEYWORDS:
            if kw.lower() in desc_lower or kw in desc:
                return SensitivityLevel.MEDIUM
        return SensitivityLevel.LOW

    def _infer_verifiability(
        self, category: TaskCategory, complexity: ComplexityLevel
    ) -> VerifiabilityLevel:
        # 代码类任务可验证性高（可编译/测试），架构类低
        if category in (
            TaskCategory.CODE_GENERATION,
            TaskCategory.TEST_GENERATION,
            TaskCategory.DATA_PROCESSING,
        ):
            return VerifiabilityLevel.HIGH
        if category in (TaskCategory.ARCHITECTURE, TaskCategory.CONVERSATION):
            return VerifiabilityLevel.LOW
        return VerifiabilityLevel.MEDIUM

    def _infer_output_strictness(
        self, category: TaskCategory, desc_lower: str
    ) -> OutputStrictnessLevel:
        strict_keywords = ["json", "schema", "格式", "严格", "yaml", "xml"]
        for kw in strict_keywords:
            if kw in desc_lower:
                return OutputStrictnessLevel.HIGH

        if category in (TaskCategory.DOCUMENTATION, TaskCategory.CONVERSATION):
            return OutputStrictnessLevel.LOW
        if category in (TaskCategory.CODE_GENERATION, TaskCategory.TEST_GENERATION):
            return OutputStrictnessLevel.MEDIUM
        return OutputStrictnessLevel.MEDIUM

    def _infer_context_requirement(
        self, desc: str, desc_lower: str, complexity: ComplexityLevel
    ) -> ContextLevel:
        for kw in HEAVY_CONTEXT_KEYWORDS:
            if kw.lower() in desc_lower or kw in desc:
                return ContextLevel.HEAVY
        for kw in STANDARD_CONTEXT_KEYWORDS:
            if kw.lower() in desc_lower or kw in desc:
                return ContextLevel.STANDARD
        if complexity in (ComplexityLevel.EXPERT, ComplexityLevel.COMPLEX):
            return ContextLevel.HEAVY
        return ContextLevel.MINIMAL

    def _infer_reasoning_intensity(
        self, category: TaskCategory, complexity: ComplexityLevel
    ) -> ReasoningLevel:
        if complexity == ComplexityLevel.EXPERT:
            return ReasoningLevel.VERY_HIGH
        if complexity == ComplexityLevel.COMPLEX:
            return ReasoningLevel.HIGH
        if category in (TaskCategory.ARCHITECTURE, TaskCategory.BUG_ANALYSIS):
            return ReasoningLevel.HIGH
        if complexity == ComplexityLevel.SIMPLE:
            return ReasoningLevel.LOW
        return ReasoningLevel.MEDIUM

    def _estimate_input_tokens(self, context: ContextLevel) -> int:
        mapping = {
            ContextLevel.MINIMAL: 1000,
            ContextLevel.STANDARD: 5000,
            ContextLevel.HEAVY: 20000,
            ContextLevel.EXTREME: 60000,
        }
        return mapping.get(context, 2000)

    def _estimate_output_tokens(self, complexity: ComplexityLevel) -> int:
        mapping = {
            ComplexityLevel.SIMPLE: 80,
            ComplexityLevel.MODERATE: 300,
            ComplexityLevel.COMPLEX: 800,
            ComplexityLevel.EXPERT: 2000,
        }
        return mapping.get(complexity, 300)

    def _extract_subtasks(self, desc: str, complexity: ComplexityLevel) -> list[str]:
        if complexity not in (ComplexityLevel.COMPLEX, ComplexityLevel.EXPERT):
            return []
        # 按词级分隔符拆分（"以及"/"并且" 作为完整词，不拆单字）
        parts = re.split(r'(?:以及|并且|而且|和|及|\+|，|,)', desc)
        parts = [p.strip() for p in parts if len(p.strip()) > 4]
        return parts[:6]  # 最多 6 个子任务

    # ── 复杂度覆盖时的资源重算 ──────────────────────────────
    _CONTEXT_BY_COMPLEXITY: dict[ComplexityLevel, ContextLevel] = {
        ComplexityLevel.SIMPLE: ContextLevel.MINIMAL,
        ComplexityLevel.MODERATE: ContextLevel.STANDARD,
        ComplexityLevel.COMPLEX: ContextLevel.HEAVY,
        ComplexityLevel.EXPERT: ContextLevel.HEAVY,
    }

    _REASONING_BY_COMPLEXITY: dict[ComplexityLevel, ReasoningLevel] = {
        ComplexityLevel.SIMPLE: ReasoningLevel.LOW,
        ComplexityLevel.MODERATE: ReasoningLevel.MEDIUM,
        ComplexityLevel.COMPLEX: ReasoningLevel.HIGH,
        ComplexityLevel.EXPERT: ReasoningLevel.VERY_HIGH,
    }

    _CONTEXT_ORDER = {
        ContextLevel.MINIMAL: 0,
        ContextLevel.STANDARD: 1,
        ContextLevel.HEAVY: 2,
        ContextLevel.EXTREME: 3,
    }

    _REASONING_ORDER = {
        ReasoningLevel.LOW: 0,
        ReasoningLevel.MEDIUM: 1,
        ReasoningLevel.HIGH: 2,
        ReasoningLevel.VERY_HIGH: 3,
    }

    def rebuild_complexity_dependent_features(
        self,
        description: str,
        features: TaskFeatures,
        resolved_complexity: ComplexityLevel,
        *,
        monotonic: bool = True,
    ) -> TaskFeatures:
        """按新复杂度重算 7 个依赖字段。

        monotonic=True（hybrid 默认）：只升不降，取高原则，能力 union 合并。
        monotonic=False（opensquilla 模式）：按 resolved complexity 完整替换所有 7 个字段。
        """
        new_ctx = self._CONTEXT_BY_COMPLEXITY.get(resolved_complexity, ContextLevel.STANDARD)
        new_input = self._estimate_input_tokens(new_ctx)
        new_output = self._estimate_output_tokens(resolved_complexity)
        new_reasoning = self._REASONING_BY_COMPLEXITY.get(resolved_complexity, ReasoningLevel.MEDIUM)
        new_subtasks = self._extract_subtasks(description, resolved_complexity)

        cap_key = (features.category, resolved_complexity)
        new_required, new_preferred = CAPABILITY_REQUIREMENTS.get(cap_key, (set(), set()))

        if monotonic:
            # 取高原则
            ctx = new_ctx if self._CONTEXT_ORDER[new_ctx] > self._CONTEXT_ORDER[features.context_requirement] else features.context_requirement
            input_tokens = max(features.estimated_input_tokens, new_input)
            output_tokens = max(features.estimated_output_tokens, new_output)
            reasoning = new_reasoning if self._REASONING_ORDER[new_reasoning] > self._REASONING_ORDER[features.reasoning_intensity] else features.reasoning_intensity
            subtasks = new_subtasks if new_subtasks else features.subtasks
            required_caps = features.required_capabilities | new_required
            preferred_caps = features.preferred_capabilities | new_preferred
        else:
            # 完整替换
            ctx = new_ctx
            input_tokens = new_input
            output_tokens = new_output
            reasoning = new_reasoning
            subtasks = new_subtasks
            required_caps = new_required
            preferred_caps = new_preferred

        return features.model_copy(update={
            "complexity": resolved_complexity,
            "context_requirement": ctx,
            "estimated_input_tokens": input_tokens,
            "estimated_output_tokens": output_tokens,
            "reasoning_intensity": reasoning,
            "subtasks": subtasks,
            "required_capabilities": required_caps,
            "preferred_capabilities": preferred_caps,
        })
