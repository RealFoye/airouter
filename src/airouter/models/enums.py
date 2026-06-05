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
