"""测试枚举定义和 Pydantic schemas。"""

from airouter.models.enums import (
    BudgetStatus,
    ComplexityLevel,
    ContextLevel,
    OutputStrictnessLevel,
    ReasoningLevel,
    RiskLevel,
    SensitivityLevel,
    StrategyType,
    TaskCategory,
    VerifiabilityLevel,
)
from airouter.models.schemas import (
    CAPABILITY_REQUIREMENTS,
    AlternativeStrategy,
    BenchmarkResult,
    ConfigSnapshot,
    ExecutionFeedback,
    FallbackPolicy,
    ModelAssignment,
    RoutingDecision,
    TaskFeatures,
)


# ── 枚举完整性 ──────────────────────────────────────────────
def test_task_category_count():
    assert len(TaskCategory) == 10


def test_complexity_level_count():
    assert len(ComplexityLevel) == 4


def test_risk_level_count():
    assert len(RiskLevel) == 3


def test_sensitivity_level_count():
    assert len(SensitivityLevel) == 3


def test_verifiability_level_count():
    assert len(VerifiabilityLevel) == 3


def test_output_strictness_level_count():
    assert len(OutputStrictnessLevel) == 3


def test_context_level_count():
    assert len(ContextLevel) == 4


def test_reasoning_level_count():
    assert len(ReasoningLevel) == 4


def test_strategy_type_count():
    assert len(StrategyType) == 4


def test_budget_status_count():
    assert len(BudgetStatus) == 3


# ── CAPABILITY_REQUIREMENTS 完整性 ──────────────────────────
def test_capability_requirements_count():
    """10 类别 × 4 复杂度 = 40 条映射。"""
    assert len(CAPABILITY_REQUIREMENTS) == 40


def test_capability_requirements_coverage():
    """每个 (category, complexity) 组合都有定义。"""
    for cat in TaskCategory:
        for comp in ComplexityLevel:
            key = (cat, comp)
            assert key in CAPABILITY_REQUIREMENTS, f"Missing mapping for {key}"


def test_capability_requirements_structure():
    """每条映射都是 (required: set, preferred: set) 元组。"""
    for key, value in CAPABILITY_REQUIREMENTS.items():
        assert isinstance(value, tuple)
        assert len(value) == 2
        required, preferred = value
        assert isinstance(required, set)
        assert isinstance(preferred, set)
        assert len(required) > 0, f"Required set should not be empty for {key}"


# ── TaskFeatures ────────────────────────────────────────────
def test_task_features_minimal():
    features = TaskFeatures(
        category=TaskCategory.CODE_GENERATION,
        complexity=ComplexityLevel.SIMPLE,
    )
    assert features.risk_level == RiskLevel.MEDIUM
    assert features.estimated_input_tokens == 2000
    assert features.subtasks == []


def test_task_features_full():
    features = TaskFeatures(
        category=TaskCategory.ARCHITECTURE,
        complexity=ComplexityLevel.EXPERT,
        risk_level=RiskLevel.HIGH,
        sensitivity=SensitivityLevel.LOW,
        verifiability=VerifiabilityLevel.LOW,
        output_strictness=OutputStrictnessLevel.MEDIUM,
        context_requirement=ContextLevel.HEAVY,
        reasoning_intensity=ReasoningLevel.VERY_HIGH,
        estimated_input_tokens=50000,
        estimated_output_tokens=3000,
        subtasks=["设计API", "设计DB", "设计缓存"],
        required_capabilities={"architecture", "complex_reasoning"},
        preferred_capabilities={"security"},
    )
    assert len(features.subtasks) == 3
    assert "architecture" in features.required_capabilities


def test_task_features_serialization():
    features = TaskFeatures(
        category=TaskCategory.BUG_ANALYSIS,
        complexity=ComplexityLevel.COMPLEX,
    )
    data = features.model_dump()
    assert data["category"] == "BUG_ANALYSIS"
    assert data["complexity"] == "COMPLEX"
    restored = TaskFeatures(**data)
    assert restored == features


# ── RoutingDecision ─────────────────────────────────────────
def test_routing_decision_serialization():
    features = TaskFeatures(
        category=TaskCategory.CODE_GENERATION,
        complexity=ComplexityLevel.MODERATE,
    )
    decision = RoutingDecision(
        task_hash="abc123",
        task_features=features,
        recommended_strategy=StrategyType.SINGLE_MODEL,
        models=ModelAssignment(executor="qwen3.7-plus"),
        estimated_cost=0.15,
        baseline_cost=0.40,
        estimated_savings=0.62,
        estimated_quality=0.75,
        quality_loss_vs_baseline=0.05,
        risk_level=RiskLevel.MEDIUM,
        requires_human_review=False,
        reasons=["成本最优", "能力匹配"],
        alternatives=[
            AlternativeStrategy(
                strategy=StrategyType.SINGLE_MODEL,
                model="qwen3.7-max",
                cost=0.40,
                quality=0.80,
                note="质量更高但成本更高",
            )
        ],
        budget_status=BudgetStatus.OK,
        quality_gate=["syntax_check"],
        fallback_policy=[
            FallbackPolicy(trigger="API_TIMEOUT", action="switch_to_backup")
        ],
        config_version="v1.0",
    )
    data = decision.model_dump()
    assert data["recommended_strategy"] == "SINGLE_MODEL"
    assert len(data["alternatives"]) == 1
    restored = RoutingDecision(**data)
    assert restored.task_hash == "abc123"


# ── ExecutionFeedback ───────────────────────────────────────
def test_execution_feedback():
    feedback = ExecutionFeedback(
        routing_decision_id=1,
        model_name="qwen3.7-plus",
        actual_input_tokens=2500,
        actual_output_tokens=800,
        actual_cost_cny=0.08,
        latency_ms=1500,
        quality_score=0.85,
    )
    assert feedback.actual_cost_cny == 0.08


# ── BenchmarkResult ─────────────────────────────────────────
def test_benchmark_result():
    result = BenchmarkResult(
        benchmark_level=2,
        case_id="code_gen_001",
        case_category=TaskCategory.CODE_GENERATION,
        case_complexity=ComplexityLevel.MODERATE,
        model_name="deepseek-v4-flash",
        strategy=StrategyType.SINGLE_MODEL,
        input_tokens=2000,
        output_tokens=500,
        cost_cny=0.01,
        latency_ms=800,
        quality_score=0.72,
    )
    assert result.benchmark_level == 2


# ── ConfigSnapshot ──────────────────────────────────────────
def test_config_snapshot():
    snapshot = ConfigSnapshot(
        config_version="v1.0",
        models_config_hash="hash1",
        routing_rules_hash="hash2",
        budgets_hash="hash3",
        quality_defaults_hash="hash4",
        compression_policy_hash="hash5",
        merged_config_json={"models": [], "rules": {}},
    )
    assert snapshot.config_version == "v1.0"
