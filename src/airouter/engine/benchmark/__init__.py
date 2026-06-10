"""Benchmark module for Level 1, Level 2, Level 3, and Finance."""

from airouter.engine.benchmark.finance_evaluator import finance_auto_score
from airouter.engine.benchmark.finance_judge import run_finance_judge
from airouter.engine.benchmark.finance_report import generate_finance_report
from airouter.engine.benchmark.finance_runner import FinanceBenchmarkRunner
from airouter.engine.benchmark.finance_schemas import (
    FinanceCase,
    FinanceCaseResult,
    FinanceCategorySummary,
    FinanceSummary,
)
from airouter.engine.benchmark.l2_report import generate_l2_report
from airouter.engine.benchmark.llm_judge_v2 import run_absolute_judge
from airouter.engine.benchmark.pairwise_judge import run_pairwise_judge
from airouter.engine.benchmark.reporter import Level3BacktestReporter
from airouter.engine.benchmark.runner import (
    Level1BenchmarkRunner,
    Level2BenchmarkRunner,
    Level3BenchmarkRunner,
)
from airouter.engine.benchmark.schemas import (
    BacktestCase,
    BacktestResult,
    BacktestSummary,
    BenchmarkCase,
    BenchmarkSummary,
    CaseResult,
    ExecutorResult,
    JudgeResult,
    JudgeSummary,
    L2Case,
    L2CaseResult,
    L2Summary,
    PairwiseResult,
    PairwiseSummary,
    RunState,
    ScoreResult,
)

__all__ = [
    "BacktestCase",
    "BacktestResult",
    "BacktestSummary",
    "BenchmarkCase",
    "BenchmarkSummary",
    "CaseResult",
    "ExecutorResult",
    "FinanceBenchmarkRunner",
    "FinanceCase",
    "FinanceCaseResult",
    "FinanceCategorySummary",
    "FinanceSummary",
    "JudgeResult",
    "JudgeSummary",
    "L2Case",
    "L2CaseResult",
    "L2Summary",
    "Level1BenchmarkRunner",
    "Level2BenchmarkRunner",
    "Level3BacktestReporter",
    "Level3BenchmarkRunner",
    "PairwiseResult",
    "PairwiseSummary",
    "RunState",
    "ScoreResult",
    "finance_auto_score",
    "generate_finance_report",
    "generate_l2_report",
    "run_absolute_judge",
    "run_finance_judge",
    "run_pairwise_judge",
]
