"""枚举定义：任务分类、复杂度、风险等维度。"""

from enum import Enum


class TaskCategory(str, Enum):
    CODE_GENERATION = "CODE_GENERATION"
    CODE_REVIEW = "CODE_REVIEW"
    REFACTORING = "REFACTORING"
    BUG_ANALYSIS = "BUG_ANALYSIS"
    DOCUMENTATION = "DOCUMENTATION"
    ARCHITECTURE = "ARCHITECTURE"
    TEST_GENERATION = "TEST_GENERATION"
    DATA_PROCESSING = "DATA_PROCESSING"
    DEVOPS = "DEVOPS"
    CONVERSATION = "CONVERSATION"


class ComplexityLevel(str, Enum):
    SIMPLE = "SIMPLE"
    MODERATE = "MODERATE"
    COMPLEX = "COMPLEX"
    EXPERT = "EXPERT"


class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class SensitivityLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class VerifiabilityLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class OutputStrictnessLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class ContextLevel(str, Enum):
    MINIMAL = "MINIMAL"
    STANDARD = "STANDARD"
    HEAVY = "HEAVY"
    EXTREME = "EXTREME"


class ReasoningLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    VERY_HIGH = "VERY_HIGH"


class StrategyType(str, Enum):
    SINGLE_MODEL = "SINGLE_MODEL"
    GUIDED_EXECUTE = "GUIDED_EXECUTE"
    PLAN_EXECUTE = "PLAN_EXECUTE"
    PLAN_EXECUTE_REVIEW = "PLAN_EXECUTE_REVIEW"


class BudgetStatus(str, Enum):
    OK = "OK"
    WARNING = "WARNING"
    OVER_BUDGET = "OVER_BUDGET"
    OVER_HARD_BUDGET = "OVER_HARD_BUDGET"


# ── 上下文工程枚举 ─────────────────────────────────────────


class ContextLayer(str, Enum):
    """上下文优先级层（P1 最高 → P6 最低）。"""

    SYSTEM_PROMPT = "SYSTEM_PROMPT"
    TASK_DESCRIPTION = "TASK_DESCRIPTION"
    RELATED_FILES = "RELATED_FILES"
    CONVERSATION_HISTORY = "CONVERSATION_HISTORY"
    TOOL_OUTPUT = "TOOL_OUTPUT"
    AUXILIARY = "AUXILIARY"


class ContentType(str, Enum):
    """上下文内容类型，决定摘要规则。"""

    PLAIN_TEXT = "PLAIN_TEXT"
    CODE = "CODE"
    CONVERSATION = "CONVERSATION"
    TOOL_OUTPUT = "TOOL_OUTPUT"
    ERROR_LOG = "ERROR_LOG"
    DOCUMENTATION = "DOCUMENTATION"


class CompressionStrategy(str, Enum):
    """压缩策略级别。"""

    NONE = "NONE"
    CONSERVATIVE = "CONSERVATIVE"
    STANDARD = "STANDARD"
    AGGRESSIVE = "AGGRESSIVE"
