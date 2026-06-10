"""Finance benchmark Pydantic schemas."""

from __future__ import annotations

from typing import Any, Literal, cast

from pydantic import BaseModel, Field


class FinanceCase(BaseModel):
    """Single finance benchmark case loaded from YAML."""

    id: str
    domain: str = "FINANCE_OFFICE"
    category: str  # TABLE_CALCULATION, REIMBURSEMENT_AUDIT, etc.
    task_type: str = "DATA_PROCESSING"
    complexity: str  # SIMPLE, MODERATE, COMPLEX, EXPERT
    prompt: str
    input_context: str = ""
    artifacts: list[str] = Field(default_factory=list)
    output_format: dict[str, Any] = Field(default_factory=dict)
    expected_answer: dict[str, Any] = Field(default_factory=dict)
    evaluation: dict[str, Any] = Field(default_factory=dict)
    max_tokens: int | None = None
    tags: list[str] = Field(default_factory=list)
    notes: str = ""

    @property
    def scoring_type(self) -> str:
        return cast(str, self.evaluation.get("scoring_type", "finance_numeric"))

    @property
    def numeric_tolerance(self) -> float:
        return cast(float, self.evaluation.get("numeric_tolerance", 0.01))

    @property
    def exact_amounts(self) -> list[str]:
        return cast(list[str], self.evaluation.get("exact_amounts", []))

    @property
    def required_findings(self) -> list[str]:
        return cast(list[str], self.evaluation.get("required_findings", []))

    @property
    def forbidden_findings(self) -> list[str]:
        return cast(list[str], self.evaluation.get("forbidden_findings", []))

    @property
    def penalize_hallucinated_findings(self) -> bool:
        return bool(self.evaluation.get("penalize_hallucinated_findings", False))

    @property
    def evidence_required(self) -> bool:
        return bool(self.evaluation.get("evidence_required", False))

    @property
    def is_policy_qa(self) -> bool:
        """True if this case belongs to POLICY_QA category."""
        return self.category == "POLICY_QA"


class FinanceCaseResult(BaseModel):
    """Result of a single (case, model) pair in finance benchmark."""

    case_id: str
    model: str
    status: Literal["success", "failed", "skipped"]
    category: str = ""
    scoring_type: str = ""
    overall_score: float = 0.0
    dimension_scores: dict[str, float] = Field(default_factory=dict)
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    cost_cny: float = 0.0
    raw_output_path: str = ""
    api_params: dict[str, Any] = Field(default_factory=dict)
    error_type: str | None = None
    error_message: str | None = None
    attempts: int = 1
    started_at: str = ""
    completed_at: str = ""
    details: dict[str, Any] = Field(default_factory=dict)
    response_metadata: dict[str, Any] = Field(default_factory=dict)


class FinanceCategorySummary(BaseModel):
    """Per-category aggregation."""

    category: str
    total_cases: int
    total_pairs: int = 0
    avg_score: float
    model_scores: dict[str, float] = Field(default_factory=dict)
    json_parse_rate: float = 0.0
    amount_accuracy: float = 0.0
    amount_applicable_pairs: int = 0
    finding_recall: float = 0.0
    decision_accuracy: float = 0.0
    evidence_quality: float = 0.0


class FinanceSummary(BaseModel):
    """Summary of a finance benchmark run."""

    level: str = "finance"
    run_id: str
    total_cases: int
    total_models: int
    total_api_calls: int
    total_input_tokens: int
    total_output_tokens: int
    total_cost_cny: float
    total_latency_ms: int
    model_scores: dict[str, float] = Field(default_factory=dict)
    category_scores: dict[str, float] = Field(default_factory=dict)
    category_model_matrix: dict[str, dict[str, float]] = Field(default_factory=dict)
    category_summaries: list[FinanceCategorySummary] = Field(default_factory=list)
    # Per-dimension averages
    avg_json_validity: float = 0.0
    avg_amount_accuracy: float = 0.0
    avg_amount_accuracy_all: float = 0.0
    amount_applicable_pairs: int = 0
    avg_finding_recall: float = 0.0
    avg_decision_accuracy: float = 0.0
    avg_evidence_quality: float = 0.0
    # Meta
    completed_pairs: int
    failed_pairs: int
    case_results: list[FinanceCaseResult] = Field(default_factory=list)
    case_catalog: list[dict[str, Any]] = Field(default_factory=list)
    run_notes: list[str] = Field(default_factory=list)
    run_completed: bool = False
    quality_passed: bool = False
    quality_threshold: float = 0.5
