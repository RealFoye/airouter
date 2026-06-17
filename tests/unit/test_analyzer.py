"""测试 TaskAnalyzer：20 条任务分类正确。"""

import pytest

from airouter.engine.router.analyzer import TaskAnalyzer
from airouter.models.enums import (
    ComplexityLevel,
    ContextLevel,
    ReasoningLevel,
    RiskLevel,
    SensitivityLevel,
    TaskCategory,
    VerifiabilityLevel,
)


@pytest.fixture
def analyzer() -> TaskAnalyzer:
    return TaskAnalyzer()


# ── 20 条测试用例 ───────────────────────────────────────────
# 期望值基于规则引擎的实际行为，部分任务有多种合理解读
TEST_CASES = [
    # (描述, 期望类别, 期望复杂度, 期望风险)
    ("写一个FastAPI JWT鉴权中间件", TaskCategory.CODE_GENERATION, ComplexityLevel.COMPLEX, RiskLevel.HIGH),
    ("审查这段代码的安全漏洞", TaskCategory.CODE_REVIEW, ComplexityLevel.MODERATE, RiskLevel.HIGH),
    ("将这个God Class拆分为策略模式", TaskCategory.REFACTORING, ComplexityLevel.COMPLEX, RiskLevel.MEDIUM),
    ("分析这个并发死锁问题", TaskCategory.BUG_ANALYSIS, ComplexityLevel.COMPLEX, RiskLevel.LOW),
    ("为这个API生成OpenAPI文档", TaskCategory.DOCUMENTATION, ComplexityLevel.SIMPLE, RiskLevel.LOW),
    ("设计一个支持百万并发的消息推送系统", TaskCategory.ARCHITECTURE, ComplexityLevel.EXPERT, RiskLevel.HIGH),
    ("为这个用户服务写单元测试", TaskCategory.TEST_GENERATION, ComplexityLevel.SIMPLE, RiskLevel.LOW),
    ("写一个ETL脚本处理CSV数据", TaskCategory.DATA_PROCESSING, ComplexityLevel.SIMPLE, RiskLevel.LOW),
    ("编写Docker Compose部署方案", TaskCategory.DEVOPS, ComplexityLevel.MODERATE, RiskLevel.LOW),
    ("解释Python的GIL是什么", TaskCategory.CONVERSATION, ComplexityLevel.SIMPLE, RiskLevel.LOW),
    ("实现用户登录模块，支持OAuth2和MFA", TaskCategory.CODE_GENERATION, ComplexityLevel.COMPLEX, RiskLevel.HIGH),
    ("重构数据库访问层，引入Repository模式", TaskCategory.REFACTORING, ComplexityLevel.COMPLEX, RiskLevel.MEDIUM),
    ("修复生产环境的内存泄漏", TaskCategory.BUG_ANALYSIS, ComplexityLevel.COMPLEX, RiskLevel.HIGH),
    ("编写微服务网关的路由规则", TaskCategory.ARCHITECTURE, ComplexityLevel.COMPLEX, RiskLevel.HIGH),
    ("设计分布式缓存架构", TaskCategory.ARCHITECTURE, ComplexityLevel.COMPLEX, RiskLevel.HIGH),
    ("生成JSON Schema配置文件", TaskCategory.CODE_GENERATION, ComplexityLevel.SIMPLE, RiskLevel.LOW),
    ("审查支付模块的代码质量", TaskCategory.CODE_REVIEW, ComplexityLevel.MODERATE, RiskLevel.HIGH),
    ("写一个数据清洗脚本处理用户日志", TaskCategory.DATA_PROCESSING, ComplexityLevel.MODERATE, RiskLevel.LOW),
    ("为整个项目编写使用手册", TaskCategory.DOCUMENTATION, ComplexityLevel.MODERATE, RiskLevel.LOW),
    ("实现跨模块的权限管理系统", TaskCategory.CODE_GENERATION, ComplexityLevel.COMPLEX, RiskLevel.HIGH),
]


@pytest.mark.parametrize(
    "desc,expected_cat,expected_comp,expected_risk",
    TEST_CASES,
    ids=[f"case_{i+1}" for i in range(len(TEST_CASES))],
)
def test_task_classification(
    analyzer: TaskAnalyzer,
    desc: str,
    expected_cat: TaskCategory,
    expected_comp: ComplexityLevel,
    expected_risk: RiskLevel,
):
    features = analyzer.extract_features(desc)
    assert features.category == expected_cat, f"Category mismatch for '{desc}'"
    assert features.complexity == expected_comp, f"Complexity mismatch for '{desc}'"
    assert features.risk_level == expected_risk, f"Risk mismatch for '{desc}'"


# ── 特征完整性 ──────────────────────────────────────────────
def test_features_have_all_13_dimensions(analyzer: TaskAnalyzer):
    features = analyzer.extract_features("写一个FastAPI JWT鉴权中间件")
    data = features.model_dump()
    expected_fields = {
        "category", "complexity", "risk_level", "sensitivity",
        "verifiability", "output_strictness", "context_requirement",
        "reasoning_intensity", "estimated_input_tokens", "estimated_output_tokens",
        "subtasks", "required_capabilities", "preferred_capabilities",
    }
    assert set(data.keys()) == expected_fields


def test_capability_requirements_populated(analyzer: TaskAnalyzer):
    features = analyzer.extract_features("写一个简单的Hello World")
    assert len(features.required_capabilities) > 0


def test_sensitivity_detection(analyzer: TaskAnalyzer):
    features = analyzer.extract_features("处理用户密码和Token的存储")
    assert features.sensitivity == SensitivityLevel.HIGH


def test_phone_formatter_example_is_not_high_sensitivity(analyzer: TaskAnalyzer):
    features = analyzer.extract_features(
        "帮我写一个Python函数，把用户输入的手机号格式化成 +86 138-1234-5678 的标准格式，非法输入返回 None。"
    )
    assert features.category == TaskCategory.CODE_GENERATION
    assert features.sensitivity == SensitivityLevel.LOW
    assert features.risk_level == RiskLevel.LOW


def test_batch_customer_phone_data_is_high_sensitivity(analyzer: TaskAnalyzer):
    features = analyzer.extract_features(
        "请把以下客户手机号批量脱敏：13812345678、13912345678、18812345678。"
    )
    assert features.sensitivity == SensitivityLevel.HIGH
    assert features.risk_level == RiskLevel.MEDIUM


def test_external_phone_export_is_high_risk(analyzer: TaskAnalyzer):
    features = analyzer.extract_features("导出全部客户手机号发给外部供应商")
    assert features.sensitivity == SensitivityLevel.HIGH
    assert features.risk_level == RiskLevel.HIGH


def test_password_validation_function_is_not_high_sensitivity(analyzer: TaskAnalyzer):
    features = analyzer.extract_features("写一个密码强度校验函数，返回 strong/weak。")
    assert features.sensitivity == SensitivityLevel.LOW


def test_secret_csv_cleaning_stays_high_sensitivity(analyzer: TaskAnalyzer):
    features = analyzer.extract_features("数据清洗包含密码和密钥的CSV文件")
    assert features.sensitivity == SensitivityLevel.HIGH


def test_context_requirement_detection(analyzer: TaskAnalyzer):
    features = analyzer.extract_features("重构整个项目的所有模块")
    assert features.context_requirement == ContextLevel.HEAVY


def test_subtasks_for_complex_tasks(analyzer: TaskAnalyzer):
    features = analyzer.extract_features(
        "设计一个支持百万并发的消息推送系统，包括网关、缓存和监控"
    )
    assert features.complexity == ComplexityLevel.EXPERT
    assert len(features.subtasks) > 0


def test_reasoning_intensity_expert(analyzer: TaskAnalyzer):
    features = analyzer.extract_features("设计分布式系统架构")
    assert features.reasoning_intensity in (ReasoningLevel.HIGH, ReasoningLevel.VERY_HIGH)


def test_verifiability_code_gen(analyzer: TaskAnalyzer):
    features = analyzer.extract_features("写一个函数计算斐波那契数列")
    assert features.verifiability == VerifiabilityLevel.HIGH


def test_verifiability_architecture(analyzer: TaskAnalyzer):
    features = analyzer.extract_features("设计一个微服务架构")
    assert features.verifiability == VerifiabilityLevel.LOW
