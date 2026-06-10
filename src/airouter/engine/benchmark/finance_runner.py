"""Finance benchmark runner: model execution + rule-based scoring."""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import yaml

from airouter.adapters.base import AdapterAuthError, AdapterError
from airouter.adapters.factory import AdapterFactory
from airouter.config import AppSettings, load_models
from airouter.engine.benchmark.executor import SYSTEM_PROMPT_VERSION, ModelExecutor
from airouter.engine.benchmark.finance_evaluator import (
    _is_amount_applicable,
    finance_auto_score,
)
from airouter.engine.benchmark.finance_loader import DEFAULT_FINANCE_CASES_PATH, load_finance_cases
from airouter.engine.benchmark.finance_schemas import (
    FinanceCase,
    FinanceCaseResult,
    FinanceCategorySummary,
    FinanceSummary,
)
from airouter.engine.benchmark.runner import (
    _completed_success_pairs,
    _compute_file_hash,
    _dedup_results_from_jsonl,
    _generate_run_id,
    _normalize_models,
    _sanitize_filename,
)
from airouter.engine.benchmark.schemas import FailedPair, RunState
from airouter.models.model_registry import ModelRegistry

logger = logging.getLogger(__name__)

FINANCE_SYSTEM_PROMPT = (
    "你是一名专业的企业财务分析助手。请根据提供的数据和制度，"
    "准确完成财务分析任务。只输出 JSON，不要添加额外解释。"
    "JSON 应包含以下字段：decision, amounts, findings, evidence, confidence。"
)


class FinanceBenchmarkRunner:
    """Run finance benchmark: real model calls + rule-based scoring."""

    DEFAULT_RESULTS_DIR = (
        Path(__file__).resolve().parents[4] / "runs" / "benchmarks" / "finance"
    )

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
    ) -> FinanceSummary:
        """Execute all (case, model) pairs and return FinanceSummary."""
        # 1. Load cases
        cases = load_finance_cases(self.cases_path)
        if self.cases_path is not None:
            cases_path = self.cases_path
        else:
            cases_path = DEFAULT_FINANCE_CASES_PATH

        # 2. Determine models
        if self._models_override:
            models = _normalize_models(self._models_override)
        else:
            with open(cases_path, encoding="utf-8") as f:
                yaml_data = yaml.safe_load(f)
            models = _normalize_models(yaml_data.get("models", []))

        # 3. Validate models
        if not models:
            raise ValueError("Finance benchmark requires at least one model")
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
        self._write_state(run_dir, state)

        # 11. Execute pairs (concurrent)
        auth_aborted = False
        run_count = 0
        run_lock = threading.Lock()

        def _execute_pair(case: FinanceCase, model: str) -> None:
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

                # Build response_metadata
                response_metadata: dict = {}
                if exec_result.raw_usage:
                    ru = exec_result.raw_usage
                    response_metadata = {
                        k: ru[k]
                        for k in ("finish_reason", "reasoning_tokens", "reasoning_starved")
                        if k in ru
                    }
                response_metadata["model_truncated"] = (
                    response_metadata.get("finish_reason") == "length"
                )

                # Save metadata
                meta_path = raw_dir / (
                    _sanitize_filename(f"{case.id}_{model}") + "_meta.json"
                )
                with self._jsonl_lock:
                    meta_path.write_text(
                        json.dumps(response_metadata, ensure_ascii=False),
                        encoding="utf-8",
                    )

                # Finance auto-score
                score = finance_auto_score(case, exec_result.response_content)

                # Build result
                case_result = FinanceCaseResult(
                    case_id=case.id,
                    model=model,
                    status="success",
                    category=case.category,
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

                with self._jsonl_lock:
                    self._append_jsonl(jsonl_path, case_result)

                with run_lock:
                    run_count += 1
                    self._progress(
                        run_count, len(pending_pairs), case.id, model, score.overall_score
                    )

            except AdapterAuthError as e:
                logger.error("Auth error for model=%s: %s — aborting run", model, e)
                with self._jsonl_lock:
                    self._append_jsonl(
                        jsonl_path,
                        FinanceCaseResult(
                            case_id=case.id,
                            model=model,
                            status="failed",
                            category=case.category,
                            scoring_type=case.scoring_type,
                            error_type="AdapterAuthError",
                            error_message=str(e),
                            started_at=started_at,
                            completed_at=datetime.now().isoformat(timespec="seconds"),
                        ),
                    )
                with run_lock:
                    auth_aborted = True

            except (AdapterError, Exception) as e:
                completed_at = datetime.now().isoformat(timespec="seconds")
                error_type = type(e).__name__
                logger.warning("pair=%s error=%s: %s", pair_key, error_type, e)

                case_result = FinanceCaseResult(
                    case_id=case.id,
                    model=model,
                    status="failed",
                    category=case.category,
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
                        auth_aborted = True

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

        # 12. Finalize
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

        # 13. Build summary
        all_pairs_done = (state.completed_pairs + state.failed_pairs) >= state.total_pairs
        no_failures = state.failed_pairs == 0
        run_completed = not auth_aborted and all_pairs_done and no_failures
        return self._build_finance_summary(
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
        """Run finance benchmark + absolute judge + pairwise judge."""
        summary = self.run(resume=resume, run_id=run_id, max_pairs=limit)

        run_dir = self._results_base_dir / summary.run_id
        if not run_dir.exists():
            raise RuntimeError(f"Cannot find run directory for judge phase: {run_dir}")

        raw_dir = str(run_dir / "raw_outputs")
        cases_path = str(self.cases_path) if self.cases_path else str(DEFAULT_FINANCE_CASES_PATH)

        from airouter.engine.benchmark.llm_judge_v2 import run_absolute_judge

        judge_results = run_absolute_judge(
            cases_path=cases_path,
            raw_dir=raw_dir,
            judge_models=judge_models,
            output_path=str(run_dir / "judge_results.jsonl"),
            workers=judge_workers,
        )

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
            "finance_summary": summary,
            "judge_results": judge_results,
            "pairwise_results": pairwise_results,
            "run_dir": str(run_dir),
        }

    # ── Internal helpers ───────────────────────────────────────

    def _build_messages(self, case: FinanceCase) -> list[dict]:
        """Construct messages for finance tasks."""
        messages: list[dict] = [{"role": "system", "content": FINANCE_SYSTEM_PROMPT}]

        parts: list[str] = []
        if case.input_context:
            parts.append(case.input_context)
        artifact_context = self._load_artifact_context(case)
        if artifact_context:
            parts.append(artifact_context)
        parts.append(case.prompt)
        schema_hint = self._build_schema_hint(case)
        if schema_hint:
            parts.append(schema_hint)

        messages.append({"role": "user", "content": "\n\n".join(parts)})
        return messages

    def _load_artifact_context(self, case: FinanceCase) -> str:
        """Load small text artifacts referenced by a case into the prompt.

        Finance tasks often depend on CSV/policy files. The benchmark runner must
        pass their contents to the model because the API cannot see local paths.
        """
        if not case.artifacts:
            return ""

        cases_path = self.cases_path or DEFAULT_FINANCE_CASES_PATH
        root = cases_path.parent
        chunks: list[str] = []
        for artifact in case.artifacts:
            artifact_path = root / artifact
            if not artifact_path.exists() or not artifact_path.is_file():
                continue
            try:
                text = artifact_path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            if len(text) > 20000:
                text = text[:20000] + "\n...[truncated]"
            chunks.append(f"附件 {artifact} 内容：\n{text}")
        return "\n\n".join(chunks)

    def _build_schema_hint(self, case: FinanceCase) -> str:
        """Build schema hint with explicit field keys for amounts/top_item/top_items.

        Merges field sources from exact_amounts, expected_answer.amounts.keys(),
        expected_answer.top_item.keys(), and expected_answer.top_items[0].keys().
        Does NOT leak standard answer values, only tells field names.
        """
        lines = [
            "",
            "【输出结构要求】",
            "- 只输出一个 JSON 对象，不要 Markdown。",
            "- 顶层字段必须包含：decision, amounts, findings, evidence, confidence。",
        ]

        # Collect amount keys from multiple sources
        amount_keys: list[str] = []
        # 1. exact_amounts (list of strings from evaluation)
        amount_keys.extend(case.exact_amounts)
        # 2. expected_answer.amounts.keys()
        expected = case.expected_answer or {}
        amounts_dict = expected.get("amounts", {})
        if isinstance(amounts_dict, dict):
            amount_keys.extend(amounts_dict.keys())
        amount_keys = list(dict.fromkeys(amount_keys))  # dedupe, preserve order

        if amount_keys:
            keys_str = ", ".join(amount_keys)
            lines.append(f"- amounts 中请使用以下 key（不要改写 key 名）：{keys_str}。")
        else:
            lines.append("- amounts 应使用结构化 key（如 raw_total_cny），明确数值和币种。")

        # top_item keys
        top_item = expected.get("top_item", {})
        if isinstance(top_item, dict) and top_item:
            keys_str = ", ".join(top_item.keys())
            lines.append(f"- 如需要输出排序/Top 项，请使用 top_item 字段，并包含这些 key: {keys_str}。")

        # top_items keys (array, each element has these keys)
        top_items = expected.get("top_items", [])
        if isinstance(top_items, list) and top_items and isinstance(top_items[0], dict):
            keys_str = ", ".join(top_items[0].keys())
            lines.append(
                f"- 如需要输出 Top-N 排序，请使用 top_items 字段（数组），"
                f"每个元素包含这些 key: {keys_str}。"
            )

        lines.append("- 不要改写 key 名；无法判断时可填 null，并在 findings/evidence 中说明原因。")

        return "\n".join(lines)

    def rescore_run(
        self,
        run_id: str,
        output_name: str = "results.rescored.jsonl",
    ) -> FinanceSummary:
        """Re-score an existing finance run from saved raw_outputs without API calls."""
        cases = load_finance_cases(self.cases_path)
        cases_path = self.cases_path or DEFAULT_FINANCE_CASES_PATH
        run_dir = self._results_base_dir / run_id
        if not run_dir.exists():
            raise ValueError(f"Run directory not found: {run_id}")

        state_path = run_dir / "run_state.json"
        if state_path.exists():
            state_data = json.loads(state_path.read_text(encoding="utf-8"))
            models = _normalize_models(state_data.get("models", []))
        else:
            with open(cases_path, encoding="utf-8") as f:
                yaml_data = yaml.safe_load(f)
            models = _normalize_models(yaml_data.get("models", []))
        if not models:
            raise ValueError("Finance benchmark requires at least one model")

        old_records = _dedup_results_from_jsonl(run_dir / "results.jsonl")
        old_by_pair = {
            f"{r.get('case_id')}::{r.get('model')}": r
            for r in old_records
        }

        raw_dir = run_dir / "raw_outputs"
        output_path = run_dir / output_name
        if output_path.exists():
            backup_path = run_dir / f"{output_name}.bak"
            output_path.replace(backup_path)

        for case in cases:
            for model in models:
                pair_key = f"{case.id}::{model}"
                raw_name = _sanitize_filename(f"{case.id}_{model}") + ".txt"
                raw_path = raw_dir / raw_name
                old = old_by_pair.get(pair_key, {})

                if not raw_path.exists():
                    result = FinanceCaseResult(
                        case_id=case.id,
                        model=model,
                        status="failed",
                        category=case.category,
                        scoring_type=case.scoring_type,
                        raw_output_path=str(raw_path),
                        error_type="RawOutputMissing",
                        error_message=f"raw output not found: {raw_path}",
                    )
                    self._append_jsonl(output_path, result)
                    continue

                output = raw_path.read_text(encoding="utf-8")
                score = finance_auto_score(case, output)

                meta_path = raw_dir / (
                    _sanitize_filename(f"{case.id}_{model}") + "_meta.json"
                )
                response_metadata: dict = {}
                if meta_path.exists():
                    try:
                        response_metadata = json.loads(meta_path.read_text(encoding="utf-8"))
                    except json.JSONDecodeError:
                        response_metadata = {}

                result = FinanceCaseResult(
                    case_id=case.id,
                    model=model,
                    status="success",
                    category=case.category,
                    scoring_type=case.scoring_type,
                    overall_score=score.overall_score,
                    dimension_scores=score.dimension_scores,
                    input_tokens=old.get("input_tokens", 0),
                    output_tokens=old.get("output_tokens", 0),
                    latency_ms=old.get("latency_ms", 0),
                    cost_cny=old.get("cost_cny", 0.0),
                    raw_output_path=str(raw_path),
                    api_params=old.get("api_params", {}),
                    attempts=old.get("attempts", 1),
                    started_at=old.get("started_at", ""),
                    completed_at=old.get("completed_at", ""),
                    details=score.details,
                    response_metadata=response_metadata,
                )
                self._append_jsonl(output_path, result)

        summary = self._build_finance_summary(
            output_path,
            run_id,
            cases,
            models,
            run_completed=True,
        )
        summary.run_notes.append(
            "本报告由 raw_outputs 离线重评分生成，未重新调用真实 API。"
        )
        if run_id == "20260609_170910":
            summary.run_notes.append(
                "注意：该 run 的原始模型输出生成于 artifact 自动注入修复前；"
                "依赖 CSV 附件字段的 case（如 FIN-TAB-002）应谨慎解读，"
                "后续真实重跑会自动把 artifact 内容加入 prompt。"
            )
        return summary

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

    def _find_resume_run(
        self,
        run_id: str | None,
        cases_hash: str,
        models: list[str],
    ) -> tuple[Path, Path, set[str]]:
        """Find a matching run to resume."""
        if run_id:
            run_dir = self._results_base_dir / run_id
            if not run_dir.exists():
                raise ValueError(f"Run directory not found: {run_id}")
        else:
            found = self._find_latest_matching_run(cases_hash, models)
            if found is None:
                raise ValueError("无可续跑的 run（无匹配的 cases_hash + models）")
            run_dir = found

        jsonl_path = run_dir / "results.jsonl"
        completed_set = _completed_success_pairs(jsonl_path)

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
        tmp_path.write_text(state.model_dump_json(indent=2), encoding="utf-8")
        os.replace(tmp_path, state_path)

    def _append_jsonl(self, jsonl_path: Path, result: FinanceCaseResult) -> None:
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

    def _build_finance_summary(
        self,
        jsonl_path: Path,
        run_id: str,
        cases: list[FinanceCase],
        models: list[str],
        run_completed: bool,
    ) -> FinanceSummary:
        """Build FinanceSummary from deduped JSONL records."""
        records = _dedup_results_from_jsonl(jsonl_path)
        success_records = [r for r in records if r.get("status") == "success"]
        failed_records = [r for r in records if r.get("status") == "failed"]

        total_api_calls = sum(r.get("attempts", 1) for r in success_records)
        total_input_tokens = sum(r.get("input_tokens", 0) for r in success_records)
        total_output_tokens = sum(r.get("output_tokens", 0) for r in success_records)
        total_cost = sum(r.get("cost_cny", 0.0) for r in success_records)
        total_latency = sum(r.get("latency_ms", 0) for r in success_records)

        # Model scores
        model_scores: dict[str, list[float]] = {}
        category_scores: dict[str, list[float]] = {}
        category_model_matrix: dict[str, dict[str, list[float]]] = {}

        # Per-dimension tracking
        dim_scores: dict[str, list[float]] = {
            "json_validity": [],
            "amount_accuracy": [],
            "finding_recall": [],
            "decision_accuracy": [],
            "evidence_quality": [],
        }
        category_dim_scores: dict[str, dict[str, list[float]]] = {}

        case_map = {c.id: c for c in cases}

        for r in success_records:
            score = r.get("overall_score", 0.0)
            model = r["model"]
            case_id = r["case_id"]
            case = case_map.get(case_id)
            dims = r.get("dimension_scores", {})
            amount_applicable = bool(
                case and _is_amount_applicable(case.expected_answer, case.exact_amounts)
            )

            model_scores.setdefault(model, []).append(score)

            if case:
                cat = case.category
                category_scores.setdefault(cat, []).append(score)
                category_model_matrix.setdefault(cat, {}).setdefault(model, []).append(score)

                for dim_key in dim_scores:
                    if dim_key in dims:
                        if dim_key != "amount_accuracy" or amount_applicable:
                            dim_scores[dim_key].append(dims[dim_key])
                        category_dim_scores.setdefault(cat, {}).setdefault(
                            dim_key, []
                        ).append(dims[dim_key])
                if amount_applicable and "amount_accuracy" in dims:
                    category_dim_scores.setdefault(cat, {}).setdefault(
                        "_amount_applicable", []
                    ).append(dims["amount_accuracy"])

        # Average model scores
        avg_model_scores = {
            m: sum(s) / len(s) for m, s in model_scores.items() if s
        }
        avg_category_scores = {
            c: sum(s) / len(s) for c, s in category_scores.items() if s
        }
        avg_matrix: dict[str, dict[str, float]] = {}
        for cat, model_dict in category_model_matrix.items():
            avg_matrix[cat] = {
                m: sum(s) / len(s) for m, s in model_dict.items() if s
            }

        # Average dimension scores
        avg_dims = {
            k: sum(v) / len(v) if v else 0.0
            for k, v in dim_scores.items()
        }

        # Build category summaries
        cat_summaries: list[FinanceCategorySummary] = []
        for cat in sorted(category_scores.keys()):
            scores = category_scores[cat]
            cat_model = {
                m: sum(s) / len(s)
                for m, s in category_model_matrix.get(cat, {}).items()
                if s
            }
            cat_dim = category_dim_scores.get(cat, {})
            cat_case_ids: set[str] = set()
            for r in success_records:
                cid = r.get("case_id")
                if not isinstance(cid, str):
                    continue
                mapped_case = case_map.get(cid)
                if mapped_case and mapped_case.category == cat:
                    cat_case_ids.add(cid)
            cat_amount_applicable = cat_dim.get("_amount_applicable", [])
            cat_summaries.append(
                FinanceCategorySummary(
                    category=cat,
                    total_cases=len(cat_case_ids),
                    total_pairs=len(scores),
                    avg_score=sum(scores) / len(scores),
                    model_scores=cat_model,
                    json_parse_rate=(
                        sum(cat_dim.get("json_validity", [])) / len(cat_dim.get("json_validity", []))
                        if cat_dim.get("json_validity") else 0.0
                    ),
                    amount_accuracy=(
                        sum(cat_amount_applicable) / len(cat_amount_applicable)
                        if cat_amount_applicable else 0.0
                    ),
                    amount_applicable_pairs=len(cat_amount_applicable),
                    finding_recall=(
                        sum(cat_dim.get("finding_recall", [])) / len(cat_dim.get("finding_recall", []))
                        if cat_dim.get("finding_recall") else 0.0
                    ),
                    decision_accuracy=(
                        sum(cat_dim.get("decision_accuracy", [])) / len(cat_dim.get("decision_accuracy", []))
                        if cat_dim.get("decision_accuracy") else 0.0
                    ),
                    evidence_quality=(
                        sum(cat_dim.get("evidence_quality", [])) / len(cat_dim.get("evidence_quality", []))
                        if cat_dim.get("evidence_quality") else 0.0
                    ),
                )
            )

        # Quality check
        threshold = 0.5
        all_scores = [r.get("overall_score", 0.0) for r in success_records]
        avg_score = sum(all_scores) / len(all_scores) if all_scores else 0.0
        quality_passed = avg_score >= threshold and run_completed

        case_results = [FinanceCaseResult(**r) for r in records]
        all_amount_scores = [
            r.get("dimension_scores", {}).get("amount_accuracy", 0.0)
            for r in success_records
            if "amount_accuracy" in r.get("dimension_scores", {})
        ]
        case_catalog = [
            {
                "id": c.id,
                "category": c.category,
                "complexity": c.complexity,
                "prompt": c.prompt,
                "scoring_type": c.scoring_type,
                "tags": c.tags,
                "expected_answer": c.expected_answer,
                "exact_amounts": c.exact_amounts,
                "required_findings": c.required_findings,
                "output_format": c.output_format,
                "amount_applicable": _is_amount_applicable(c.expected_answer, c.exact_amounts),
                "artifact_count": len(c.artifacts),
            }
            for c in cases
        ]

        return FinanceSummary(
            run_id=run_id,
            total_cases=len(cases),
            total_models=len(models),
            total_api_calls=total_api_calls,
            total_input_tokens=total_input_tokens,
            total_output_tokens=total_output_tokens,
            total_cost_cny=total_cost,
            total_latency_ms=total_latency,
            model_scores=avg_model_scores,
            category_scores=avg_category_scores,
            category_model_matrix=avg_matrix,
            category_summaries=cat_summaries,
            avg_json_validity=avg_dims.get("json_validity", 0.0),
            avg_amount_accuracy=avg_dims.get("amount_accuracy", 0.0),
            avg_amount_accuracy_all=(
                sum(all_amount_scores) / len(all_amount_scores)
                if all_amount_scores else 0.0
            ),
            amount_applicable_pairs=len(dim_scores.get("amount_accuracy", [])),
            avg_finding_recall=avg_dims.get("finding_recall", 0.0),
            avg_decision_accuracy=avg_dims.get("decision_accuracy", 0.0),
            avg_evidence_quality=avg_dims.get("evidence_quality", 0.0),
            completed_pairs=len(success_records),
            failed_pairs=len(failed_records),
            case_results=case_results,
            case_catalog=case_catalog,
            run_completed=run_completed,
            quality_passed=quality_passed,
            quality_threshold=threshold,
        )
