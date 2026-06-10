"""Level 1, Level 2, and Level 3 benchmark runners."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

from airouter.adapters.base import AdapterAuthError, AdapterError
from airouter.adapters.factory import AdapterFactory
from airouter.config import AppSettings, load_models
from airouter.engine.benchmark.evaluator import auto_score
from airouter.engine.benchmark.executor import SYSTEM_PROMPT_VERSION, ModelExecutor
from airouter.engine.benchmark.loader import load_cases, load_l2_cases
from airouter.engine.benchmark.reporter import Level3BacktestReporter
from airouter.engine.benchmark.schemas import (
    BacktestCase,
    BacktestResult,
    BacktestSummary,
    BenchmarkSummary,
    CaseResult,
    FailedPair,
    L2Case,
    L2CaseResult,
    L2Summary,
    RunState,
)
from airouter.engine.benchmark.scorer import METRIC_TARGETS, compute_case_failures, compute_metrics
from airouter.engine.router.router import Router
from airouter.models.model_registry import ModelRegistry

logger = logging.getLogger(__name__)


class Level1BenchmarkRunner:
    """Run Level 1 offline benchmark against Router."""

    def __init__(self, cases_path: Path | None = None):
        self.cases_path = cases_path
        self.router = Router()
        self.registry = ModelRegistry(load_models())

    def run(self, fail_fast: bool = False) -> BenchmarkSummary:
        """Run all cases and return summary."""
        cases = load_cases(self.cases_path)
        results: list[CaseResult] = []

        for case in cases:
            result = self._run_case(case)
            results.append(result)
            if fail_fast and not result.passed:
                break

        # fail_fast 可能截断 results，metrics 分母应与执行的 case 数一致
        executed_cases = cases[: len(results)]
        return self._build_summary(executed_cases, results)

    def _run_case(self, case) -> CaseResult:
        """Run a single case through Router and score it."""
        decision = self.router.route(case.prompt)

        # Extract typed values from decision (avoid dict union-type issues)
        task_type: str = decision.task_features.category.value
        complexity: str = decision.task_features.complexity.value
        risk: str = decision.risk_level.value
        strategy: str = decision.recommended_strategy.value
        executor: str | None = decision.models.executor
        executor_tier: int | None = self._get_tier(decision.models.executor)
        planner: str | None = decision.models.planner
        planner_tier: int | None = self._get_tier(decision.models.planner)
        reviewer: str | None = decision.models.reviewer
        reviewer_tier: int | None = self._get_tier(decision.models.reviewer)
        requires_human_review: bool = decision.requires_human_review
        quality_gate: list[str] = decision.quality_gate
        estimated_cost: float = decision.estimated_cost
        budget_status: str = decision.budget_status.value
        sensitivity: str = decision.task_features.sensitivity.value
        task_hash: str = decision.task_hash
        fallback_triggers: list[str] = [p.trigger for p in decision.fallback_policy]

        actuals: dict[str, object] = {
            "task_type": task_type,
            "complexity": complexity,
            "risk": risk,
            "strategy": strategy,
            "executor": executor,
            "executor_tier": executor_tier,
            "planner": planner,
            "planner_tier": planner_tier,
            "reviewer": reviewer,
            "reviewer_tier": reviewer_tier,
            "requires_human_review": requires_human_review,
            "quality_gate": quality_gate,
            "estimated_cost": estimated_cost,
            "budget_status": budget_status,
            "sensitivity": sensitivity,
            "task_hash": task_hash,
            "fallback_triggers": fallback_triggers,
        }

        failures = compute_case_failures(case, actuals)

        return CaseResult(
            case_id=case.id,
            passed=len(failures) == 0,
            failures=failures,
            actual_task_type=task_type,
            actual_complexity=complexity,
            actual_risk=risk,
            actual_strategy=strategy,
            actual_executor=executor,
            actual_executor_tier=executor_tier,
            actual_planner=planner,
            actual_planner_tier=planner_tier,
            actual_reviewer=reviewer,
            actual_reviewer_tier=reviewer_tier,
            actual_requires_human_review=requires_human_review,
            actual_quality_gate=quality_gate,
            actual_estimated_cost=estimated_cost,
            actual_budget_status=budget_status,
            actual_sensitivity=sensitivity,
            actual_task_hash=task_hash,
            actual_fallback_triggers=fallback_triggers,
        )

    def _get_tier(self, model_name: str | None) -> int | None:
        """Look up model tier by name."""
        if not model_name:
            return None
        entry = self.registry.get_by_name(model_name)
        return entry.tier if entry else None

    def _build_summary(self, cases, results: list[CaseResult]) -> BenchmarkSummary:
        """Build summary with metrics."""
        passed = sum(1 for r in results if r.passed)
        failed = len(results) - passed
        failed_ids = [r.case_id for r in results if not r.passed]

        metrics = compute_metrics(cases, results)

        # Check if all metrics pass targets
        metric_passed = {}
        for name, value in metrics.items():
            target = METRIC_TARGETS.get(name, 0.0)
            metric_passed[name] = value >= target

        all_metrics_pass = all(metric_passed.values())
        all_cases_pass = failed == 0

        return BenchmarkSummary(
            level=1,
            total_cases=len(results),
            passed_cases=passed,
            failed_cases=failed,
            pass_rate=passed / len(results) if results else 0.0,
            metrics=metrics,
            metric_targets=dict(METRIC_TARGETS),
            metric_passed=metric_passed,
            failed_case_ids=failed_ids,
            case_results=results,
            all_passed=all_metrics_pass and all_cases_pass,
        )


# ── System prompts for L2 ──────────────────────────────────

SYSTEM_PROMPTS: dict[str, str] = {
    "code_generation": "你是一名高级软件工程师。请编写干净、生产级的代码，包含适当的错误处理和文档字符串。",
    "code_review": "你是一名高级代码审查员。请识别所有问题，包括安全漏洞、性能问题和设计缺陷。",
    "bug_analysis": "你是一名调试专家。请分析 bug 报告，定位根因，并给出修复建议。",
    "documentation": "你是一名技术文档工程师。请编写清晰、结构良好的文档。",
    "refactoring": "你是一名重构专家。请改进代码结构，同时保持行为不变。",
    "architecture": "你是一名软件架构师。请设计一个全面的解决方案，包含清晰的组件边界。",
}


# ── Utility functions ──────────────────────────────────────


def _sanitize_filename(name: str) -> str:
    """Sanitize a string for use as a filename."""
    return re.sub(r"[^\w\-.]", "_", name)


def _generate_run_id(base_dir: Path) -> str:
    """Generate a unique run_id (YYYYMMDD_HHMMSS with dedup suffix)."""
    base = datetime.now().strftime("%Y%m%d_%H%M%S")
    candidate = base
    suffix = 2
    while (base_dir / candidate).exists():
        candidate = f"{base}_{suffix}"
        suffix += 1
    return candidate


def _normalize_models(models: list[str]) -> list[str]:
    """Deduplicate, strip whitespace, sort."""
    return sorted({m.strip() for m in models if m.strip()})


def _compute_file_hash(path: Path) -> str:
    """Compute MD5 hash of a file."""
    content = path.read_bytes()
    return hashlib.md5(content).hexdigest()


def _dedup_results_from_jsonl(jsonl_path: Path) -> list[dict]:
    """Dedup JSONL by (case_id, model), keeping last record."""
    seen: dict[str, dict] = {}
    if not jsonl_path.exists():
        return []
    text = jsonl_path.read_text(encoding="utf-8").strip()
    if not text:
        return []
    for line in text.split("\n"):
        if line.strip():
            record = json.loads(line)
            key = f"{record['case_id']}::{record['model']}"
            seen[key] = record
    return list(seen.values())


def _completed_success_pairs(jsonl_path: Path) -> set[str]:
    """Get pair keys whose last status is 'success'."""
    records = _dedup_results_from_jsonl(jsonl_path)
    return {
        f"{r['case_id']}::{r['model']}"
        for r in records
        if r.get("status") == "success"
    }


# ── Level 2 Runner ─────────────────────────────────────────


class Level2BenchmarkRunner:
    """Run Level 2 benchmark: real model calls + auto-scoring."""

    DEFAULT_RESULTS_DIR = Path(__file__).resolve().parents[4] / "runs" / "benchmarks" / "level2"

    def __init__(
        self,
        cases_path: Path | None = None,
        models: list[str] | None = None,
        force_mock: bool = True,
        rate_limit_rpm: int = 20,
        results_base_dir: Path | None = None,
        workers: int = 5,
    ):
        self.cases_path = cases_path
        self._models_override = models
        self._force_mock = force_mock
        self._rate_limit_rpm = rate_limit_rpm
        self._results_base_dir = results_base_dir or self.DEFAULT_RESULTS_DIR
        self._workers = workers
        self._jsonl_lock = threading.Lock()

        settings = AppSettings()
        registry = ModelRegistry(load_models())
        factory = AdapterFactory(settings)
        self._registry = registry
        self._executor = ModelExecutor(
            adapter_factory=factory,
            registry=registry,
            force_mock=force_mock,
            rate_limit_rpm=rate_limit_rpm,
        )

    def run(
        self,
        resume: bool = False,
        run_id: str | None = None,
        fail_fast: bool = False,
        max_pairs: int | None = None,
    ) -> L2Summary:
        """Execute all (case, model) pairs and return L2Summary."""
        # 1. Load cases
        cases = load_l2_cases(self.cases_path)
        if self.cases_path is not None:
            cases_path = self.cases_path
        else:
            from airouter.engine.benchmark.loader import DEFAULT_L2_CASES_PATH
            cases_path = DEFAULT_L2_CASES_PATH

        # 2. Determine models
        if self._models_override:
            models = _normalize_models(self._models_override)
        else:
            # Read from YAML top-level 'models' key
            import yaml
            with open(cases_path, encoding="utf-8") as f:
                yaml_data = yaml.safe_load(f)
            models = _normalize_models(yaml_data.get("models", []))

        # 3. Validate models
        if not models:
            raise ValueError("Level 2 benchmark requires at least one model")
        self._executor.validate_models(models)

        # 4. Compute cases hash
        cases_hash = _compute_file_hash(cases_path)

        # 5. Ensure results base dir exists
        self._results_base_dir.mkdir(parents=True, exist_ok=True)

        # 6. Resume or new run
        completed_set: set[str] = set()

        if resume:
            run_dir, jsonl_path, completed_set = self._find_resume_run(
                run_id, cases_hash, models
            )
        else:
            run_dir = self._results_base_dir / _generate_run_id(self._results_base_dir)
            run_dir.mkdir(parents=True, exist_ok=True)
            jsonl_path = run_dir / "results.jsonl"

        raw_dir = run_dir / "raw_outputs"
        raw_dir.mkdir(exist_ok=True)

        # 7. Build pairs
        all_pairs = [(case, model) for case in cases for model in models]
        total_pairs = len(all_pairs)

        # 8. Filter completed (success only)
        pending_pairs = [
            (c, m) for c, m in all_pairs
            if f"{c.id}::{m}" not in completed_set
        ]

        # 9. Apply limit
        if max_pairs is not None:
            pending_pairs = pending_pairs[:max_pairs]

        # 10. Initialize state
        now = datetime.now().isoformat(timespec="seconds")
        api_params = {
            "temperature": 0.0,
            "default_max_tokens": 2048,
            "system_prompt_version": SYSTEM_PROMPT_VERSION,
        }
        state = RunState(
            run_id=run_dir.name,
            cases_path=str(cases_path),
            cases_hash=cases_hash,
            started_at=now,
            last_updated_at=now,
            status="running",
            models=models,
            api_params=api_params,
            total_pairs=total_pairs,
            completed_pairs=len(completed_set),
            failed_pairs=0,
        )

        # Write initial state
        self._write_state(run_dir, state)

        # 11. Execute pairs (concurrent)
        auth_aborted = False
        run_count = 0
        run_lock = threading.Lock()

        def _execute_pair(case: L2Case, model: str) -> None:
            nonlocal run_count, auth_aborted
            pair_key = f"{case.id}::{model}"
            started_at = datetime.now().isoformat(timespec="seconds")

            try:
                messages = self._build_messages(case)
                exec_result = self._executor.execute(
                    model, messages, max_tokens=case.max_tokens
                )
                completed_at = datetime.now().isoformat(timespec="seconds")

                # Save raw output
                raw_name = _sanitize_filename(f"{case.id}_{model}") + ".txt"
                raw_path = raw_dir / raw_name
                with self._jsonl_lock:
                    raw_path.write_text(exec_result.response_content, encoding="utf-8")

                # Build response_metadata from raw_usage (BEFORE auto_score)
                response_metadata: dict = {}
                if exec_result.raw_usage:
                    ru = exec_result.raw_usage
                    response_metadata = {
                        k: ru[k]
                        for k in ("finish_reason", "reasoning_tokens", "reasoning_starved")
                        if k in ru
                    }
                # Add model_truncated flag
                response_metadata["model_truncated"] = response_metadata.get("finish_reason") == "length"

                # Save metadata file for judge consumption
                meta_path = raw_dir / (_sanitize_filename(f"{case.id}_{model}") + "_meta.json")
                with self._jsonl_lock:
                    meta_path.write_text(json.dumps(response_metadata, ensure_ascii=False), encoding="utf-8")

                # Auto-score (with response_metadata for truncation penalty)
                score = auto_score(case, exec_result.response_content, response_metadata)

                # Build result
                case_result = L2CaseResult(
                    case_id=case.id,
                    model=model,
                    status="success",
                    scoring_type=case.scoring_type,
                    overall_score=score.overall_score,
                    dimension_scores=score.dimension_scores,
                    input_tokens=exec_result.input_tokens,
                    output_tokens=exec_result.output_tokens,
                    latency_ms=exec_result.latency_ms,
                    cost_cny=exec_result.cost_cny,
                    raw_output_path=str(raw_path),
                    api_params=exec_result.api_params,
                    attempts=exec_result.attempts,
                    started_at=started_at,
                    completed_at=completed_at,
                    details=score.details,
                    response_metadata=response_metadata,
                )

                # Thread-safe JSONL write
                with self._jsonl_lock:
                    self._append_jsonl(jsonl_path, case_result)

                # Progress
                with run_lock:
                    run_count += 1
                    self._progress(run_count, len(pending_pairs), case.id, model, score.overall_score)

            except AdapterAuthError as e:
                logger.error("Auth error for model=%s: %s — aborting run", model, e)
                with self._jsonl_lock:
                    self._append_jsonl(jsonl_path, L2CaseResult(
                        case_id=case.id, model=model, status="failed",
                        scoring_type=case.scoring_type,
                        error_type="AdapterAuthError",
                        error_message=str(e),
                        started_at=started_at,
                        completed_at=datetime.now().isoformat(timespec="seconds"),
                    ))
                with run_lock:
                    auth_aborted = True

            except (AdapterError, Exception) as e:
                completed_at = datetime.now().isoformat(timespec="seconds")
                error_type = type(e).__name__
                logger.warning("pair=%s error=%s: %s", pair_key, error_type, e)

                case_result = L2CaseResult(
                    case_id=case.id,
                    model=model,
                    status="failed",
                    scoring_type=case.scoring_type,
                    error_type=error_type,
                    error_message=str(e),
                    attempts=getattr(e, "attempts", 1),
                    started_at=started_at,
                    completed_at=completed_at,
                )
                with self._jsonl_lock:
                    self._append_jsonl(jsonl_path, case_result)

                with run_lock:
                    run_count += 1
                    if fail_fast:
                        auth_aborted = True  # signal to stop

        if self._workers <= 1:
            for case, model in pending_pairs:
                if auth_aborted:
                    break
                _execute_pair(case, model)
        else:
            with ThreadPoolExecutor(max_workers=self._workers) as pool:
                futures = {
                    pool.submit(_execute_pair, case, model): (case, model)
                    for case, model in pending_pairs
                }
                for future in as_completed(futures):
                    if auth_aborted:
                        break
                    try:
                        future.result()
                    except Exception as e:
                        logger.error("Worker exception: %s", e)

        # 12. Finalize — rebuild state from deduped JSONL (source of truth)
        deduped = _dedup_results_from_jsonl(jsonl_path)
        final_success = [r for r in deduped if r.get("status") == "success"]
        final_failed = [r for r in deduped if r.get("status") == "failed"]

        state.completed = [
            f"{r['case_id']}::{r['model']}" for r in final_success
        ]
        state.completed_pairs = len(final_success)
        state.failed = [
            FailedPair(
                pair=f"{r['case_id']}::{r['model']}",
                error=r.get("error_message", "unknown"),
                attempts=r.get("attempts", 1),
            )
            for r in final_failed
        ]
        state.failed_pairs = len(final_failed)
        state.status = "completed" if not auth_aborted else "auth_aborted"
        state.last_updated_at = datetime.now().isoformat(timespec="seconds")
        self._write_state(run_dir, state)

        # 13. Build summary from JSONL
        all_pairs_done = (state.completed_pairs + state.failed_pairs) >= state.total_pairs
        no_failures = state.failed_pairs == 0
        run_completed = not auth_aborted and all_pairs_done and no_failures
        return self._build_l2_summary(
            jsonl_path, run_dir.name, cases, models,
            run_completed=run_completed,
        )

    def run_with_judges(
        self,
        judge_models: list[str] | None = None,
        pairwise: bool = True,
        judge_workers: int = 20,
        resume: bool = False,
        run_id: str | None = None,
        limit: int | None = None,
    ) -> dict:
        """Run L2 full pipeline: model execution → auto-score → absolute judge → pairwise judge."""
        # Step 1: Run models + auto-score
        l2_summary = self.run(resume=resume, run_id=run_id, max_pairs=limit)

        # Find the run directory
        run_dir = self._find_latest_run_dir()
        if run_dir is None:
            raise RuntimeError("Cannot find run directory for judge phase")

        raw_dir = str(run_dir / "raw_outputs")
        cases_path = str(self.cases_path) if self.cases_path else str(
            Path(__file__).resolve().parents[4] / "data" / "benchmarks" / "level2" / "router_quality_cases.yaml"
        )

        # Step 2: Absolute Judge
        from airouter.engine.benchmark.llm_judge_v2 import run_absolute_judge
        judge_results = run_absolute_judge(
            cases_path=cases_path,
            raw_dir=raw_dir,
            judge_models=judge_models,
            output_path=str(run_dir / "judge_results.jsonl"),
            workers=judge_workers,
        )

        # Step 3: Pairwise Judge (optional)
        pairwise_results = None
        if pairwise:
            from airouter.engine.benchmark.pairwise_judge import run_pairwise_judge
            pairwise_results = run_pairwise_judge(
                cases_path=cases_path,
                raw_dir=raw_dir,
                judge_models=judge_models,
                output_path=str(run_dir / "pairwise_results.jsonl"),
                workers=judge_workers,
            )

        return {
            "l2_summary": l2_summary,
            "judge_results": judge_results,
            "pairwise_results": pairwise_results,
            "run_dir": str(run_dir),
        }

    def _find_latest_run_dir(self) -> Path | None:
        """Find the most recent run directory."""
        if not self._results_base_dir.exists():
            return None
        dirs = sorted(
            [d for d in self._results_base_dir.iterdir() if d.is_dir()],
            key=lambda d: d.stat().st_mtime,
            reverse=True,
        )
        return dirs[0] if dirs else None

    def _build_messages(self, case: L2Case) -> list[dict]:
        """Construct messages list from case."""
        system_prompt = SYSTEM_PROMPTS.get(
            case.scoring_type,
            "你是一名高级软件工程师。请提供高质量的回答。"
        )
        messages: list[dict] = [{"role": "system", "content": system_prompt}]

        if case.input_context:
            user_content = f"{case.input_context}\n\n{case.prompt}"
        else:
            user_content = case.prompt

        messages.append({"role": "user", "content": user_content})
        return messages

    def _find_resume_run(
        self,
        run_id: str | None,
        cases_hash: str,
        models: list[str],
    ) -> tuple[Path, Path, set[str]]:
        """Find a matching run to resume. Returns (run_dir, jsonl_path, completed_set)."""
        if run_id:
            run_dir = self._results_base_dir / run_id
            if not run_dir.exists():
                raise ValueError(f"Run directory not found: {run_id}")
        else:
            # Find latest matching run
            found = self._find_latest_matching_run(cases_hash, models)
            if found is None:
                raise ValueError("无可续跑的 run（无匹配的 cases_hash + models）")
            run_dir = found

        jsonl_path = run_dir / "results.jsonl"
        completed_set = _completed_success_pairs(jsonl_path)

        # Validate state
        state_path = run_dir / "run_state.json"
        if state_path.exists():
            state_data = json.loads(state_path.read_text(encoding="utf-8"))
            if state_data.get("cases_hash") != cases_hash:
                raise ValueError(
                    f"cases_hash 不匹配: state={state_data.get('cases_hash')[:8]}... "
                    f"current={cases_hash[:8]}... 请使用新的 run"
                )
            state_models = _normalize_models(state_data.get("models", []))
            if state_models != models:
                raise ValueError(
                    f"models 不匹配: state={state_models} current={models}"
                )

        return run_dir, jsonl_path, completed_set

    def _find_latest_matching_run(
        self, cases_hash: str, models: list[str]
    ) -> Path | None:
        """Scan results dir for the latest run matching hash + models."""
        if not self._results_base_dir.exists():
            return None

        candidates = []
        for d in sorted(self._results_base_dir.iterdir(), reverse=True):
            if not d.is_dir():
                continue
            state_path = d / "run_state.json"
            if not state_path.exists():
                continue
            try:
                state_data = json.loads(state_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            if state_data.get("cases_hash") != cases_hash:
                continue
            state_models = _normalize_models(state_data.get("models", []))
            if state_models != models:
                continue
            candidates.append(d)

        return candidates[0] if candidates else None

    def _write_state(self, run_dir: Path, state: RunState) -> None:
        """Atomic write of run_state.json."""
        state_path = run_dir / "run_state.json"
        tmp_path = state_path.with_suffix(".tmp")
        tmp_path.write_text(
            state.model_dump_json(indent=2), encoding="utf-8"
        )
        os.replace(tmp_path, state_path)

    def _append_jsonl(self, jsonl_path: Path, result: L2CaseResult) -> None:
        """Append a single result to JSONL."""
        line = result.model_dump_json() + "\n"
        with open(jsonl_path, "a", encoding="utf-8") as f:
            f.write(line)

    def _progress(
        self, done: int, total: int, case_id: str, model: str, score: float
    ) -> None:
        """Print progress to stderr."""
        print(
            f"[{done}/{total}] {case_id} × {model} → score={score:.3f}",
            file=sys.stderr,
        )

    def _build_l2_summary(
        self,
        jsonl_path: Path,
        run_id: str,
        cases: list[L2Case],
        models: list[str],
        run_completed: bool,
    ) -> L2Summary:
        """Build L2Summary from deduped JSONL records."""
        records = _dedup_results_from_jsonl(jsonl_path)
        success_records = [r for r in records if r.get("status") == "success"]
        failed_records = [r for r in records if r.get("status") == "failed"]

        # Aggregate
        total_api_calls = sum(r.get("attempts", 1) for r in success_records)
        total_input_tokens = sum(r.get("input_tokens", 0) for r in success_records)
        total_output_tokens = sum(r.get("output_tokens", 0) for r in success_records)
        total_cost = sum(r.get("cost_cny", 0.0) for r in success_records)
        total_latency = sum(r.get("latency_ms", 0) for r in success_records)

        # Model scores
        model_scores: dict[str, list[float]] = {}
        task_type_scores: dict[str, list[float]] = {}
        complexity_scores: dict[str, list[float]] = {}
        task_model_matrix: dict[str, dict[str, list[float]]] = {}

        case_map = {c.id: c for c in cases}

        for r in success_records:
            score = r.get("overall_score", 0.0)
            model = r["model"]
            case_id = r["case_id"]
            case = case_map.get(case_id)

            model_scores.setdefault(model, []).append(score)
            if case:
                task_type_scores.setdefault(case.task_type, []).append(score)
                complexity_scores.setdefault(case.complexity, []).append(score)
                task_model_matrix.setdefault(case.task_type, {}).setdefault(model, []).append(score)

        # Average
        avg_model_scores = {
            m: sum(s) / len(s) for m, s in model_scores.items() if s
        }
        avg_task_scores = {
            t: sum(s) / len(s) for t, s in task_type_scores.items() if s
        }
        avg_complexity_scores = {
            c: sum(s) / len(s) for c, s in complexity_scores.items() if s
        }
        avg_matrix: dict[str, dict[str, float]] = {}
        for task, model_dict in task_model_matrix.items():
            avg_matrix[task] = {
                m: sum(s) / len(s) for m, s in model_dict.items() if s
            }

        # Quality check: average score >= threshold
        threshold = 0.5
        all_scores = [r.get("overall_score", 0.0) for r in success_records]
        avg_score = sum(all_scores) / len(all_scores) if all_scores else 0.0
        quality_passed = avg_score >= threshold and run_completed

        # Build case results
        case_results = [
            L2CaseResult(**r) for r in records
        ]

        return L2Summary(
            run_id=run_id,
            total_cases=len(cases),
            total_models=len(models),
            total_api_calls=total_api_calls,
            total_input_tokens=total_input_tokens,
            total_output_tokens=total_output_tokens,
            total_cost_cny=total_cost,
            total_latency_ms=total_latency,
            model_scores=avg_model_scores,
            task_type_scores=avg_task_scores,
            complexity_scores=avg_complexity_scores,
            task_model_matrix=avg_matrix,
            completed_pairs=len(success_records),
            failed_pairs=len(failed_records),
            case_results=case_results,
            run_completed=run_completed,
            quality_passed=quality_passed,
            quality_threshold=threshold,
        )


# ── Level 3 Runner ─────────────────────────────────────────


class Level3BenchmarkRunner:
    """Run Level 3 backtest: pure cost simulation using Router decisions."""

    def __init__(
        self,
        l1_cases_path: Path | None = None,
        l2_cases_path: Path | None = None,
        case_set: str = "all",
        baseline_model: str = "qwen3.7-max",
    ):
        if case_set not in {"all", "l1", "l2"}:
            raise ValueError("case_set must be one of: all, l1, l2")
        self._l1_cases_path = l1_cases_path
        self._l2_cases_path = l2_cases_path
        self._case_set = case_set
        self._router = Router()
        self._registry = ModelRegistry(load_models())
        self._reporter = Level3BacktestReporter(self._registry, baseline_model)

    def run(self) -> BacktestSummary:
        """Load cases, route each, compute costs, and return BacktestSummary."""
        backtest_cases = self._load_cases()
        if not backtest_cases:
            raise ValueError(f"No cases loaded for case_set={self._case_set}")
        results = [self._run_case(c) for c in backtest_cases]
        return self._reporter.build_summary(results)

    def _load_cases(self) -> list[BacktestCase]:
        """Load cases based on case_set selection."""
        cases: list[BacktestCase] = []

        if self._case_set in ("all", "l1"):
            l1_cases = load_cases(self._l1_cases_path)
            for c in l1_cases:
                cases.append(BacktestCase(
                    id=c.id,
                    source="L1",
                    prompt=c.prompt,
                    input_context="",
                    task_type=c.expected_task_type,
                    complexity=c.expected_complexity,
                ))

        if self._case_set in ("all", "l2"):
            l2_cases = load_l2_cases(self._l2_cases_path)
            for lc in l2_cases:
                cases.append(BacktestCase(
                    id=lc.id,
                    source="L2",
                    prompt=lc.prompt,
                    input_context=lc.input_context,
                    task_type=lc.task_type,
                    complexity=lc.complexity,
                ))

        return cases

    def _run_case(self, case: BacktestCase) -> BacktestResult:
        """Route a single case and compute backtest result."""
        # L2 cases include input_context
        route_text = (
            f"{case.input_context}\n\n{case.prompt}"
            if case.input_context
            else case.prompt
        )
        decision = self._router.route(route_text)

        # Baseline cost
        baseline_cost = self._reporter.compute_baseline_cost(decision.task_features)

        # Router cost
        raw_router_cost = decision.estimated_cost
        has_executable_model = decision.models.executor is not None

        if has_executable_model:
            effective_router_cost = raw_router_cost
            savings_cny = baseline_cost - effective_router_cost
            savings_rate = savings_cny / baseline_cost if baseline_cost > 0 else 0.0
            exclusion_reason = ""
        else:
            effective_router_cost = baseline_cost
            savings_cny = 0.0
            savings_rate = 0.0
            exclusion_reason = decision.human_review_reason or "no executable model"

        # Downgrade classification
        downgrade_type, downgrade_reason = self._reporter.classify_downgrade(decision)

        # Extract typed values from decision
        strategy = decision.recommended_strategy.value
        risk = decision.risk_level.value
        executor = decision.models.executor
        executor_tier = self._get_tier(executor)
        planner = decision.models.planner
        reviewer = decision.models.reviewer

        return BacktestResult(
            case_id=case.id,
            source=case.source,
            result_id=f"{case.source}:{case.id}",
            prompt_hash=decision.task_hash,
            has_executable_model=has_executable_model,
            task_type=case.task_type,
            complexity=case.complexity,
            router_strategy=strategy,
            router_executor=executor,
            router_executor_tier=executor_tier,
            router_planner=planner,
            router_reviewer=reviewer,
            raw_router_cost=raw_router_cost,
            effective_router_cost=effective_router_cost,
            router_quality_prior=decision.estimated_quality,
            router_quality_loss_prior=decision.quality_loss_vs_baseline,
            baseline_model=self._reporter.baseline_model,
            baseline_cost=baseline_cost,
            savings_cny=savings_cny,
            savings_rate=savings_rate,
            risk_level=risk,
            requires_human_review=decision.requires_human_review,
            downgrade_type=downgrade_type,
            downgrade_reason=downgrade_reason,
            exclusion_reason=exclusion_reason,
        )

    def _get_tier(self, model_name: str | None) -> int | None:
        """Look up model tier by name."""
        if not model_name:
            return None
        entry = self._registry.get_by_name(model_name)
        return entry.tier if entry else None

