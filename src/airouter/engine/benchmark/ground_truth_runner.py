"""Ground Truth Benchmark Runner：执行模型调用 + 评分 + Oracle + 策略回放。

支持 mock 模式（不消耗真实 API）、断点续跑、Dev/Holdout 分离、并发执行。
"""

from __future__ import annotations

import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from airouter.engine.benchmark.ground_truth_evaluator import (
    compute_final_score,
    evaluate_case,
)
from airouter.engine.benchmark.ground_truth_loader import (
    load_dev_cases,
    load_holdout_cases,
)
from airouter.engine.benchmark.ground_truth_schemas import (
    CANDIDATE_MODELS,
    JUDGE_MODELS,
    AggregatedModelResult,
    GroundTruthCase,
    GroundTruthCaseResult,
    GroundTruthSummary,
    OracleResult,
)
from airouter.engine.benchmark.oracle_generator import (
    aggregate_results,
    generate_oracles,
    identify_rerun_candidates,
)
from airouter.engine.benchmark.runner import (
    _generate_run_id,
)
from airouter.engine.benchmark.strategy_replay import (
    EndToEndReplay,
    SignalLayerReplay,
    build_oracle_index,
    build_results_index,
)

log = logging.getLogger(__name__)


@dataclass
class AnalysisArtifacts:
    """Oracle + 策略回放分析产物。

    由 rebuild_analysis() 统一生成，run()、run_with_reruns()、Judge 重建共用。
    """
    aggregated: list[AggregatedModelResult]
    complete_cases: list[GroundTruthCase]
    oracles: list[OracleResult]
    signal_results: list[Any]
    e2e_results: list[Any]
    dev_signal_results: list[Any]
    dev_e2e_results: list[Any]
    holdout_signal_results: list[Any]
    holdout_e2e_results: list[Any]
    analysis_deferred: bool


class _MLUnavailableError(Exception):
    """Raised when ML backend is unavailable during strategy replay."""


def _build_routing_text(case: Any) -> str:
    """构建 routing_input：任务文本 + 上下文。不含评分标准/expected_behavior。"""
    text: str = case.prompt
    if case.input_context:
        text = case.input_context + "\n\n" + text
    return text


def _classify_decision(decision: Any) -> str:
    """分类路由决策：AUTO / EXECUTE_WITH_REVIEW / ESCALATE_TO_HUMAN。"""
    if decision.models.executor is None:
        return "ESCALATE_TO_HUMAN"
    if decision.requires_human_review:
        return "EXECUTE_WITH_REVIEW"
    return "AUTO"


def _ml_unavailable_result(strategy_name: str, dataset: Literal["dev", "holdout", "all"]) -> Any:
    """构造 ML 不可用时的策略回放结果。"""
    from airouter.engine.benchmark.ground_truth_schemas import StrategyReplayResult
    return StrategyReplayResult(
        strategy_name=strategy_name, layer="signal",
        dataset=dataset, ml_unavailable=True,
    )

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
DEFAULT_RESULTS_DIR = PROJECT_ROOT / "runs" / "benchmarks" / "routing_ground_truth"
DEFAULT_MANIFEST_PATH = PROJECT_ROOT / "data" / "benchmarks" / "routing_ground_truth" / "evaluation_manifest.json"

_SUPPORTED_SCHEMA_VERSIONS = {"1.0"}
_SUPPORTED_EVALUATOR_VERSIONS = {"1.0"}
_SUPPORTED_CONFIG_VERSIONS = {"1.0"}


class GroundTruthRunner:
    """Ground Truth Benchmark 运行器。

    默认 force_mock=True，不调用真实 API。
    force_mock=False 时需要传入 executor 或允许自动创建。
    """

    DEFAULT_RESULTS_DIR = DEFAULT_RESULTS_DIR
    CANDIDATE_MODELS = CANDIDATE_MODELS
    JUDGE_MODELS = JUDGE_MODELS

    def __init__(
        self,
        results_dir: Path | None = None,
        force_mock: bool = True,
        workers: int = 5,
        executor: Any | None = None,
        rate_limit_rpm: int = 20,
        allow_mock_fallback: bool = True,
    ):
        self._results_dir = results_dir or DEFAULT_RESULTS_DIR
        self._force_mock = force_mock
        self._workers = workers
        self._results_dir.mkdir(parents=True, exist_ok=True)
        self._jsonl_lock = threading.Lock()

        if not force_mock:
            if executor is not None:
                self._executor = executor
            else:
                self._executor = self._create_executor(rate_limit_rpm, allow_mock_fallback)
            # 严格模式：验证候选模型的 adapter 不是 MockAdapter
            if not allow_mock_fallback:
                self._verify_no_mock_adapters()
        else:
            self._executor = None

    def _create_executor(self, rate_limit_rpm: int, allow_mock_fallback: bool) -> Any:
        """创建 ModelExecutor（真实 API 模式）。"""
        from airouter.adapters.factory import AdapterFactory
        from airouter.config import load_all, settings
        from airouter.engine.benchmark.executor import ModelExecutor
        from airouter.models.model_registry import ModelRegistry

        config = load_all()
        registry = ModelRegistry(config.models)
        factory = AdapterFactory(
            settings=settings,
            allow_mock_fallback=allow_mock_fallback,
        )
        return ModelExecutor(
            adapter_factory=factory,
            registry=registry,
            force_mock=False,
            rate_limit_rpm=rate_limit_rpm,
        )

    def _verify_no_mock_adapters(self) -> None:
        """验证所有候选模型的 adapter 不是 MockAdapter。"""
        from airouter.adapters.mock import MockAdapter
        from airouter.config import load_all
        from airouter.models.model_registry import ModelRegistry

        config = load_all()
        registry = ModelRegistry(config.models)
        for model_name in CANDIDATE_MODELS:
            entry = registry.get_by_name(model_name)
            if entry is None:
                raise RuntimeError(f"候选模型 {model_name} 未在 models.yaml 中找到")
            adapter = self._executor._factory.get_adapter(entry)
            if isinstance(adapter, MockAdapter):
                raise RuntimeError(
                    f"--real-api 模式：模型 {model_name} 的 adapter 降级为 MockAdapter。"
                    f"请检查 API key 配置。"
                )

    def rebuild_analysis(
        self,
        cases: list[GroundTruthCase],
        results: list[GroundTruthCaseResult],
        dataset: Literal["dev", "holdout", "all"],
        require_judge: bool = False,
    ) -> AnalysisArtifacts:
        """统一分析入口：完整 case 过滤 + Dev/Holdout 分离 + Oracle + 策略回放。

        run()、run_with_reruns()、Judge 重建必须全部调用此方法，
        不允许各自复制 Oracle/Replay 逻辑。

        require_judge: True 时，完整 case 还要求 judge_score is not None。
        """
        aggregated = aggregate_results(results)

        # ── 完整 case 过滤 ──
        # 按 (case_id, model) 收集全部 runs，避免 last-entry-wins 覆盖成功结果
        runs_by_case_model: dict[str, dict[str, list[GroundTruthCaseResult]]] = {}
        for r in results:
            runs_by_case_model.setdefault(r.case_id, {}).setdefault(r.model, []).append(r)

        candidate_set = set(CANDIDATE_MODELS)

        complete_case_ids: set[str] = set()
        for case in cases:
            model_runs = runs_by_case_model.get(case.id, {})

            # 必须覆盖全部 CANDIDATE_MODELS（不能只检查数量）
            if not candidate_set.issubset(set(model_runs.keys())):
                continue

            # 每个候选模型至少要有一次 status="success"
            all_valid = True
            for m in CANDIDATE_MODELS:
                runs = model_runs.get(m, [])
                has_success = any(r.status == "success" for r in runs)
                if not has_success:
                    all_valid = False
                    break
                if require_judge:
                    has_judge = any(
                        r.status == "success" and r.judge_score is not None
                        for r in runs
                    )
                    if not has_judge:
                        all_valid = False
                        break
            if not all_valid:
                continue

            complete_case_ids.add(case.id)

        complete_cases = [c for c in cases if c.id in complete_case_ids]

        # 过滤 aggregated：只保留完整 case
        complete_aggregated = [
            a for a in aggregated if a.case_id in complete_case_ids
        ]

        analysis_deferred = len(complete_cases) == 0

        if analysis_deferred:
            return AnalysisArtifacts(
                aggregated=complete_aggregated,
                complete_cases=[],
                oracles=[],
                signal_results=[],
                e2e_results=[],
                dev_signal_results=[],
                dev_e2e_results=[],
                holdout_signal_results=[],
                holdout_e2e_results=[],
                analysis_deferred=True,
            )

        # ── Dev/Holdout 分离 ──
        dev_complete = [c for c in complete_cases if _infer_dataset_label(c, dataset) == "dev"]
        holdout_complete = [c for c in complete_cases if _infer_dataset_label(c, dataset) == "holdout"]

        if dataset == "all":
            dev_oracles = generate_oracles(dev_complete, complete_aggregated, "dev") if dev_complete else []
            holdout_oracles = generate_oracles(holdout_complete, complete_aggregated, "holdout") if holdout_complete else []
            oracles = dev_oracles + holdout_oracles
        elif dataset == "dev":
            oracles = generate_oracles(complete_cases, complete_aggregated, "dev")
            dev_oracles = oracles
            holdout_oracles = []
        else:  # holdout
            oracles = generate_oracles(complete_cases, complete_aggregated, "holdout")
            dev_oracles = []
            holdout_oracles = oracles

        # ── 策略回放 ──
        results_index = build_results_index(complete_aggregated)

        if dataset == "all":
            if dev_oracles:
                dev_oi = build_oracle_index(dev_oracles)
                dev_signal = self._run_signal_replay(dev_complete, results_index, dev_oi, "dev")
                dev_e2e = self._run_e2e_replay(dev_complete, results_index, dev_oi, "dev")
            else:
                dev_signal, dev_e2e = [], []
            if holdout_oracles:
                ho_oi = build_oracle_index(holdout_oracles)
                ho_signal = self._run_signal_replay(holdout_complete, results_index, ho_oi, "holdout")
                ho_e2e = self._run_e2e_replay(holdout_complete, results_index, ho_oi, "holdout")
            else:
                ho_signal, ho_e2e = [], []
            signal_results = dev_signal + ho_signal
            e2e_results = dev_e2e + ho_e2e
        else:
            oracle_index = build_oracle_index(oracles)
            signal_results = self._run_signal_replay(complete_cases, results_index, oracle_index, dataset)
            e2e_results = self._run_e2e_replay(complete_cases, results_index, oracle_index, dataset)
            dev_signal = signal_results if dataset == "dev" else []
            dev_e2e = e2e_results if dataset == "dev" else []
            ho_signal = signal_results if dataset == "holdout" else []
            ho_e2e = e2e_results if dataset == "holdout" else []

        return AnalysisArtifacts(
            aggregated=complete_aggregated,
            complete_cases=complete_cases,
            oracles=oracles,
            signal_results=signal_results,
            e2e_results=e2e_results,
            dev_signal_results=dev_signal,
            dev_e2e_results=dev_e2e,
            holdout_signal_results=ho_signal,
            holdout_e2e_results=ho_e2e,
            analysis_deferred=False,
        )

    def run(
        self,
        dataset: Literal["dev", "holdout", "all"] = "all",
        resume: bool = False,
        run_id: str | None = None,
        limit: int | None = None,
    ) -> GroundTruthSummary:
        """执行完整 benchmark 流程：模型调用 → 评分 → Oracle → 策略回放 → 报告。

        dataset: "dev", "holdout", "all"
        resume: 断点续跑（从已有 JSONL 恢复）
        """
        run_id = run_id or _generate_run_id(self._results_dir)
        run_dir = self._results_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        # 加载用例
        cases = self._load_cases(dataset)
        log.info("loaded_%d_cases dataset=%s run_id=%s", len(cases), dataset, run_id)

        # Manifest 验证（dataset 含 holdout 时）
        manifest_data: dict[str, Any] | None = None
        holdout_hash_val: str | None = None
        eval_frozen_at_val: str | None = None
        if dataset in ("holdout", "all"):
            from airouter.engine.benchmark.ground_truth_loader import compute_holdout_hash
            actual_hash = compute_holdout_hash()
            holdout_count = sum(
                1 for c in cases if _infer_dataset_label(c, dataset) == "holdout"
            )
            manifest_data = validate_evaluation_manifest(
                holdout_hash=actual_hash,
                holdout_case_count=holdout_count,
            )
            holdout_hash_val = manifest_data.get("holdout_hash")
            eval_frozen_at_val = manifest_data.get("frozen_at")

        # 执行模型调用 + 评分
        results_path = run_dir / "results.jsonl"
        if resume and results_path.exists():
            completed = _gt_completed_pairs(results_path)
            log.info("resumed: %d completed pairs", len(completed))
        else:
            completed = set()

        completed_before = len(completed)
        total_pairs = len(cases) * len(CANDIDATE_MODELS)

        # Snapshot physical call counter before execution
        calls_before = (
            self._executor.snapshot_physical_calls()
            if self._executor else 0
        )

        new_results = self._execute_and_evaluate(
            cases, run_dir, completed, dataset, results_path, limit=limit,
        )
        new_pairs_this_run = len(new_results)

        # Delta = actual physical API calls this phase (includes retries)
        calls_after = (
            self._executor.snapshot_physical_calls()
            if self._executor else 0
        )
        physical_initial_calls = calls_after - calls_before

        # 从 JSONL 加载所有结果（含 resume 的旧结果）
        all_results = _load_deduped_by_run(results_path)
        # 只统计 status=success 的结果作为"完成"（failed/incomplete 不算完成）
        completed_after = sum(1 for r in all_results if r.status == "success")
        remaining_pairs = total_pairs - completed_after

        # 统一分析：完整 case 过滤 + Dev/Holdout 分离 + Oracle + 策略回放
        artifacts = self.rebuild_analysis(cases, all_results, dataset)

        # 保存聚合和 Oracle
        aggregated_path = run_dir / "aggregated.jsonl"
        self._save_aggregated(aggregated_path, artifacts.aggregated)
        oracle_path = run_dir / "oracles.jsonl"
        self._save_oracles(oracle_path, artifacts.oracles)

        # Dev/Holdout 分别计数
        dev_count = sum(1 for c in cases if _infer_dataset_label(c, dataset) == "dev")
        holdout_count = sum(1 for c in cases if _infer_dataset_label(c, dataset) == "holdout")

        # API 调用统计
        n_cases = len(cases)
        candidate_initial = len(new_results)  # 实际执行的 pair 数（不含 resume 跳过的）
        mock_evaluations = candidate_initial if self._force_mock else 0

        summary = GroundTruthSummary(
            run_id=run_id,
            eval_frozen_at=eval_frozen_at_val,
            holdout_hash=holdout_hash_val,
            evaluation_manifest=manifest_data,
            total_cases=n_cases,
            dev_cases=dev_count,
            holdout_cases=holdout_count,
            models=list(CANDIDATE_MODELS),
            judge_models=list(JUDGE_MODELS),
            n_runs_per_case=1,
            oracle_results=artifacts.oracles,
            signal_strategy_results=artifacts.signal_results,
            end_to_end_strategy_results=artifacts.e2e_results,
            dev_signal_results=artifacts.dev_signal_results,
            dev_e2e_results=artifacts.dev_e2e_results,
            holdout_signal_results=artifacts.holdout_signal_results,
            holdout_e2e_results=artifacts.holdout_e2e_results,
            is_mock_run=self._force_mock,
            mock_evaluations=mock_evaluations,
            candidate_initial_calls=candidate_initial,
            retry_attempts=max(0, physical_initial_calls - candidate_initial),
            total_physical_api_calls=physical_initial_calls,
            total_estimated_cost_cny=sum(r.estimated_cost_cny for r in all_results),
            expected_pairs=new_pairs_this_run,
            completed_before=completed_before,
            new_pairs_this_run=new_pairs_this_run,
            completed_after=completed_after,
            remaining_pairs=remaining_pairs,
            complete_cases=len(artifacts.complete_cases),
            run_completed=remaining_pairs == 0,
            analysis_deferred=artifacts.analysis_deferred,
        )

        # 保存 summary
        summary_path = run_dir / "summary.json"
        summary_path.write_text(
            summary.model_dump_json(indent=2),
            encoding="utf-8",
        )

        log.info("benchmark_complete run_id=%s cases=%d", run_id, n_cases)
        return summary

    def run_with_reruns(
        self,
        dataset: Literal["dev", "holdout", "all"] = "all",
        run_id: str | None = None,
    ) -> GroundTruthSummary:
        """首次运行 + 补跑（冻结候选集，补跑 2 次 = 总计 3 次）。"""
        # 首次运行 (run_index=0)
        summary = self.run(dataset=dataset, run_id=run_id)
        run_id = summary.run_id
        run_dir = self._results_dir / run_id

        # 加载首次结果
        results_path = run_dir / "results.jsonl"
        first_results = _load_deduped_by_run(results_path)

        # 识别补跑候选（冻结）
        cases = self._load_cases(dataset)
        aggregated = aggregate_results(first_results)
        rerun_ds: Literal["dev", "holdout"] = "dev" if dataset == "dev" else "holdout"
        oracles = generate_oracles(cases, aggregated, rerun_ds)
        rerun_candidates = identify_rerun_candidates(cases, first_results, oracles)

        if not rerun_candidates:
            log.info("no_rerun_candidates")
            return summary

        log.info("rerun_candidates: %d pairs", len(rerun_candidates))

        # 冻结候选集：两次补跑使用相同的 candidates
        frozen_candidates = list(rerun_candidates)

        # Snapshot physical call counter before reruns
        rerun_calls_before = (
            self._executor.snapshot_physical_calls()
            if self._executor else 0
        )

        # 补跑 2 次 (run_index=1, 2)，总计 3 次
        for run_idx in [1, 2]:
            rerun_results = self._execute_reruns(
                cases, frozen_candidates, run_dir, dataset, run_index=run_idx,
            )
            _append_results(results_path, rerun_results)

        # Delta = actual physical API calls for reruns (includes retries)
        rerun_calls_after = (
            self._executor.snapshot_physical_calls()
            if self._executor else 0
        )
        physical_rerun_calls = rerun_calls_after - rerun_calls_before

        # 从完整 JSONL 重建一切
        all_results = _load_deduped_by_run(results_path)
        aggregated = aggregate_results(all_results)

        # 保存全量聚合产物（含不完整 case）
        self._save_aggregated(run_dir / "aggregated.jsonl", aggregated)

        # 统一分析入口（完整 case 过滤 + Dev/Holdout 分离 + Oracle + 策略回放）
        artifacts = self.rebuild_analysis(cases, all_results, dataset)

        # 写回 Oracle 产物
        self._save_oracles(run_dir / "oracles.jsonl", artifacts.oracles)

        # 更新 summary
        logical_rerun_calls = len(frozen_candidates) * 2  # 2 次补跑

        summary.oracle_results = artifacts.oracles
        summary.signal_strategy_results = artifacts.signal_results
        summary.end_to_end_strategy_results = artifacts.e2e_results
        summary.dev_signal_results = artifacts.dev_signal_results
        summary.dev_e2e_results = artifacts.dev_e2e_results
        summary.holdout_signal_results = artifacts.holdout_signal_results
        summary.holdout_e2e_results = artifacts.holdout_e2e_results
        summary.complete_cases = len(artifacts.complete_cases)
        summary.analysis_deferred = artifacts.analysis_deferred
        summary.candidate_rerun_calls = logical_rerun_calls
        # Accumulate retry attempts: physical rerun calls beyond logical rerun pairs
        summary.retry_attempts += max(0, physical_rerun_calls - logical_rerun_calls)
        summary.total_physical_api_calls = (
            summary.total_physical_api_calls + physical_rerun_calls
        )
        summary.total_estimated_cost_cny = sum(r.estimated_cost_cny for r in all_results)

        # 保存 summary
        summary_path = run_dir / "summary.json"
        summary_path.write_text(
            summary.model_dump_json(indent=2),
            encoding="utf-8",
        )

        return summary

    # ── 内部方法 ──────────────────────────────────────────────

    def _load_cases(self, dataset: str) -> list[GroundTruthCase]:
        if dataset == "dev":
            return load_dev_cases()
        elif dataset == "holdout":
            return load_holdout_cases()
        else:
            cases = []
            try:
                cases.extend(load_dev_cases())
            except FileNotFoundError:
                pass
            try:
                cases.extend(load_holdout_cases())
            except FileNotFoundError:
                pass
            if not cases:
                raise FileNotFoundError("No benchmark cases found for dev or holdout")
            return cases

    def _execute_and_evaluate(
        self,
        cases: list[GroundTruthCase],
        run_dir: Path,
        completed: set[str],
        dataset: str,
        results_path: Path,
        limit: int | None = None,
    ) -> list[GroundTruthCaseResult]:
        """执行模型调用 + 评分（支持 mock）。每个 pair 完成后立即追加 JSONL。

        limit: 本次最多执行的新 pair 数（None = 不限制）。
        实际执行数 = min(limit, remaining_pending)。

        并发模式（real API + workers > 1）：
        - 使用 ThreadPoolExecutor 并行执行
        - AdapterAuthError → 立即取消 pending futures
        - 每个 pair 完成后用 lock 保护 JSONL 写入
        """
        raw_dir = run_dir / "raw_outputs"
        raw_dir.mkdir(exist_ok=True)

        # 构建 pending pairs 列表（按 case × model 顺序）
        pending_pairs: list[tuple[GroundTruthCase, str]] = [
            (case, model_name)
            for case in cases
            for model_name in CANDIDATE_MODELS
            if f"{case.id}::{model_name}" not in completed
        ]

        # 切片
        actual_limit = min(limit, len(pending_pairs)) if limit is not None else len(pending_pairs)
        work_items = pending_pairs[:actual_limit]

        # Mock 模式：顺序执行
        if self._force_mock:
            return self._execute_sequential(work_items, dataset, raw_dir, results_path)

        # Real API 模式：并发执行
        if self._workers > 1:
            return self._execute_concurrent(work_items, dataset, raw_dir, results_path)
        else:
            return self._execute_sequential(work_items, dataset, raw_dir, results_path)

    def _execute_sequential(
        self,
        work_items: list[tuple[GroundTruthCase, str]],
        dataset: str,
        raw_dir: Path,
        results_path: Path,
    ) -> list[GroundTruthCaseResult]:
        """顺序执行（mock 或 real API workers=1）。"""
        results = []
        for case, model_name in work_items:
            if self._force_mock:
                result = self._mock_evaluate(case, model_name, dataset, raw_dir)
            else:
                result = self._real_evaluate(case, model_name, dataset, raw_dir)

            results.append(result)
            # 每个 pair 完成后立即追加（支持断点续跑）
            with self._jsonl_lock:
                _append_results(results_path, [result])

        return results

    def _execute_concurrent(
        self,
        work_items: list[tuple[GroundTruthCase, str]],
        dataset: str,
        raw_dir: Path,
        results_path: Path,
    ) -> list[GroundTruthCaseResult]:
        """并发执行（real API + workers > 1）。

        AdapterAuthError → 立即取消 pending futures 并停止。
        保持最多 workers 个在途任务。
        """
        from airouter.adapters.base import AdapterAuthError

        results: list[GroundTruthCaseResult] = []
        auth_error_occurred = False

        with ThreadPoolExecutor(max_workers=self._workers) as pool:
            # 提交所有任务（ThreadPoolExecutor 会自动限制并发数）
            futures = {
                pool.submit(
                    self._real_evaluate, case, model_name, dataset, raw_dir,
                ): (case, model_name)
                for case, model_name in work_items
            }

            # 处理完成的任务
            for future in as_completed(futures):
                # Auth error occurred → skip remaining futures (they should be cancelled)
                if auth_error_occurred:
                    continue

                case, model_name = futures[future]

                try:
                    result = future.result()
                except AdapterAuthError as e:
                    # Auth error → 取消所有 pending futures
                    log.error("Auth error for %s/%s: %s", case.id, model_name, e)
                    auth_error_occurred = True
                    # 记录失败结果
                    result = GroundTruthCaseResult(
                        case_id=case.id, model=model_name, run_index=0,
                        dataset=_infer_dataset_label(case, dataset),
                        status="failed", error_type="auth_error",
                        error_message=str(e), final_score=0.0, final_pass=False,
                    )
                    # 取消所有 pending futures
                    for f in futures:
                        if not f.done():
                            f.cancel()
                except Exception as e:
                    # 其他异常 → 记录失败但继续
                    log.warning("Evaluation failed for %s/%s: %s", case.id, model_name, e)
                    result = GroundTruthCaseResult(
                        case_id=case.id, model=model_name, run_index=0,
                        dataset=_infer_dataset_label(case, dataset),
                        status="failed", error_type="api_error",
                        error_message=str(e), final_score=0.0, final_pass=False,
                    )

                results.append(result)
                # 用 lock 保护 JSONL 写入
                with self._jsonl_lock:
                    _append_results(results_path, [result])

        return results

    def _mock_evaluate(
        self,
        case: GroundTruthCase,
        model_name: str,
        dataset: str,
        raw_dir: Path,
        run_index: int = 0,
    ) -> GroundTruthCaseResult:
        """Mock 模式：生成模拟结果用于测试流程。"""
        # 生成模拟模型输出（不泄漏答案）
        mock_output = self._generate_mock_output(case, model_name)

        # 保存 raw output
        raw_path = raw_dir / f"{case.id}_{model_name}_run{run_index}.txt"
        raw_path.write_text(mock_output, encoding="utf-8")

        # 评分
        eval_result = evaluate_case(case, mock_output)

        # 模拟 token/cost（基于 tier）
        tier = _model_tier(model_name)
        input_tokens = max(100, len(case.prompt) // 3)
        output_tokens = max(50, len(mock_output) // 3)
        cost = _estimate_cost(tier, input_tokens, output_tokens)

        final = compute_final_score(
            deterministic_passed=eval_result.deterministic_passed,
            deterministic_score=eval_result.deterministic_score,
            rule_score_val=eval_result.rule_score,
            judge_score=None,  # mock 不跑 Judge
            hard_failure_ids=eval_result.hard_failure_ids,
            pass_threshold=case.pass_threshold,
        )

        # 推断 dataset 标签
        ds_label = _infer_dataset_label(case, dataset)

        return GroundTruthCaseResult(
            case_id=case.id,
            model=model_name,
            run_index=run_index,
            dataset=ds_label,
            status="success",
            deterministic_passed=eval_result.deterministic_passed,
            deterministic_score=eval_result.deterministic_score,
            rule_score=eval_result.rule_score,
            final_score=final,
            hard_failure_ids=eval_result.hard_failure_ids,
            soft_violation_ids=eval_result.soft_violation_ids,
            pass_threshold=case.pass_threshold,
            final_pass=final >= case.pass_threshold and not eval_result.hard_failure_ids,
            dimension_scores=eval_result.dimension_scores,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=50,
            estimated_cost_cny=cost,
            raw_output_path=str(raw_path),
        )

    def _build_gt_messages(self, case: GroundTruthCase) -> list[dict]:
        """构建多轮对话消息（含历史），用于真实 API 调用。"""
        system_prompt = (
            "你是一个 AI 路由系统的被测模型。请根据用户任务输出结构化 JSON。\n\n"
            "输出必须严格遵循以下格式（所有字段必须存在，可为空值）：\n"
            "{\n"
            '    "action": "answer | propose_change | clarify | refuse",\n'
            '    "summary": "一句话概述",\n'
            '    "findings": ["发现的问题列表"],\n'
            '    "evidence": [{"type": "file|line|log|stack", "ref": "引用"}],\n'
            '    "modified_files": ["修改的文件路径"],\n'
            '    "patch": "diff/代码变更（如适用）",\n'
            '    "validation": {\n'
            '        "executed": false,\n'
            '        "commands": ["建议执行的验证命令"],\n'
            '        "expected_outcome": "预测执行结果",\n'
            '        "results": ""\n'
            '    },\n'
            '    "clarification_questions": ["追问的问题"],\n'
            '    "approval_required": false,\n'
            '    "review_required": false,\n'
            '    "claims": ["做出的断言"]\n'
            "}\n\n"
            "## action 选择规则\n"
            '- clarify: 信息不足无法给出可靠答案时（如缺少关键日志、需求模糊、多种解读均合理），'
            '必须 action="clarify" 并在 clarification_questions 中列出需要补充的信息\n'
            "- propose_change: 需要修改代码或配置时\n"
            "- answer: 信息充分、可以直接回答时\n"
            "- refuse: 任务不合理或超出权限时\n\n"
            "## approval_required 判断规则\n"
            "只有涉及实际变更的操作才需要 approval_required=true：\n"
            "- 生产环境数据变更（DELETE/UPDATE/批量操作）\n"
            "- 权限、认证配置的修改（不是审查）\n"
            "- 不可逆操作（删除数据、修改线上配置）\n"
            "- 多系统/多用户影响的变更\n"
            "注意：纯代码审查、安全分析、日志诊断等只读任务不需要 approval\n\n"
            "## 重要约束\n"
            "- 你没有测试执行工具，不能实际运行代码或测试\n"
            "- validation.executed 必须为 false\n"
            "- validation.results 必须为空字符串（只有实际执行过才能填写）\n"
            "- validation.commands 仅填写建议执行的验证命令\n"
            "- 预测结果写入 validation.expected_outcome，不得写入 results\n"
            "- modified_files 只能包含你实际建议修改的文件，不要添加未修改的文件\n"
            "- 不要编造不存在的信息"
        )

        messages: list[dict] = [{"role": "system", "content": system_prompt}]

        # 多轮历史
        rm = case.routing_metadata
        for msg in rm.history_messages:
            messages.append({"role": msg.role, "content": msg.content})

        # workspace_files（代码文件等）
        user_content = ""
        if case.workspace_files:
            user_content += "## 工作区文件\n\n"
            for filename, content in case.workspace_files.items():
                user_content += f"### {filename}\n```python\n{content}\n```\n\n"

        # input_context + prompt
        if case.input_context:
            user_content += case.input_context + "\n\n"
        user_content += case.prompt
        messages.append({"role": "user", "content": user_content})

        return messages

    def _generate_mock_output(self, case: GroundTruthCase, model_name: str) -> str:
        """生成模拟结构化输出。不复制 expected_behavior（防止答案泄漏）。"""
        # Mock 输出只包含通用占位内容，不泄漏评测真值
        output = {
            "action": "answer",
            "summary": "Mock evaluation output.",
            "findings": [],
            "evidence": [],
            "modified_files": [],
            "patch": "",
            "validation": {"executed": False, "commands": [], "results": ""},
            "clarification_questions": [],
            "approval_required": False,
            "review_required": case.is_high_risk,
            "claims": [],
        }

        return json.dumps(output, ensure_ascii=False, indent=2)

    def _real_evaluate(
        self,
        case: GroundTruthCase,
        model_name: str,
        dataset: str,
        raw_dir: Path,
        run_index: int = 0,
    ) -> GroundTruthCaseResult:
        """真实 API 调用 + 沙箱验证 + 评分。

        流程：构建 messages → API 调用 → 保存 raw output → 解析 JSON →
        沙箱验证（如有 patch）→ 评分。
        sandbox 不可用 → status="incomplete"。
        API 失败 → status="failed"。
        AdapterAuthError → re-raise（让并发代码取消 pending futures）。
        """
        from airouter.adapters.base import AdapterAuthError

        if self._executor is None:
            raise RuntimeError(
                "Cannot run real API evaluation: executor not initialized. "
                "Use force_mock=True or pass an executor."
            )

        ds_label = _infer_dataset_label(case, dataset)

        # 构建 messages
        messages = self._build_gt_messages(case)

        # API 调用
        try:
            exec_result = self._executor.execute(
                model_name, messages, max_tokens=case.max_tokens,
            )
        except AdapterAuthError:
            # Auth error → re-raise so concurrent code can cancel pending futures
            raise
        except Exception as e:
            # API 失败 → status="failed"
            error_type = "auth_error" if "auth" in str(type(e).__name__).lower() else "api_error"
            return GroundTruthCaseResult(
                case_id=case.id, model=model_name, run_index=run_index,
                dataset=ds_label, status="failed",
                error_type=error_type, error_message=str(e),
                final_score=0.0, final_pass=False,
                input_tokens=0, output_tokens=0, latency_ms=0,
                estimated_cost_cny=0.0,
            )

        raw_output = exec_result.response_content
        # 保存 raw output
        raw_path = raw_dir / f"{case.id}_{model_name}_run{run_index}.txt"
        raw_path.write_text(raw_output, encoding="utf-8")

        # 解析 JSON 以提取 patch（用于沙箱验证）
        from airouter.engine.benchmark.ground_truth_evaluator import parse_structured_output
        from airouter.engine.benchmark.sandbox import run_harness_validation
        parsed, _ = parse_structured_output(raw_output)

        # L2.5: 沙箱验证（如果有 harness commands 且模型输出了 patch）
        sandbox_result = None
        has_harness = bool(case.harness_validation and case.harness_validation.commands)
        if has_harness and parsed:
            patch = parsed.get("patch", "")
            if patch:
                test_files = None
                if case.ground_truth and case.ground_truth.test_files:
                    test_files = [
                        {"filename": tf.filename, "content": tf.content}
                        for tf in case.ground_truth.test_files
                    ]
                sandbox_result = run_harness_validation(
                    workspace_files=case.workspace_files or {},
                    patch=patch,
                    harness_commands=case.harness_validation.commands,
                    expected_exit_code=case.harness_validation.expected_exit_code,
                    timeout_s=case.harness_validation.timeout_s,
                    test_files=test_files,
                )

        # 评分（含沙箱结果）
        eval_result = evaluate_case(case, raw_output, sandbox_result=sandbox_result)

        # 确定 status
        sandbox_unavail = (
            sandbox_result is not None and sandbox_result.sandbox_execution_unavailable
        )
        status: Literal["success", "failed", "incomplete"]
        if has_harness and sandbox_unavail:
            status = "incomplete"
        else:
            status = "success"

        final = compute_final_score(
            deterministic_passed=eval_result.deterministic_passed,
            deterministic_score=eval_result.deterministic_score,
            rule_score_val=eval_result.rule_score,
            judge_score=None,
            hard_failure_ids=eval_result.hard_failure_ids,
            pass_threshold=case.pass_threshold,
        )

        return GroundTruthCaseResult(
            case_id=case.id,
            model=model_name,
            run_index=run_index,
            dataset=ds_label,
            status=status,
            deterministic_passed=eval_result.deterministic_passed,
            deterministic_score=eval_result.deterministic_score,
            rule_score=eval_result.rule_score,
            final_score=final,
            hard_failure_ids=eval_result.hard_failure_ids,
            soft_violation_ids=eval_result.soft_violation_ids,
            pass_threshold=case.pass_threshold,
            final_pass=final >= case.pass_threshold and not eval_result.hard_failure_ids,
            dimension_scores=eval_result.dimension_scores,
            sandbox_executed=bool(sandbox_result and not sandbox_result.sandbox_execution_unavailable),
            sandbox_passed=sandbox_result.passed if sandbox_result else None,
            sandbox_unavailable=sandbox_unavail,
            input_tokens=exec_result.input_tokens,
            output_tokens=exec_result.output_tokens,
            latency_ms=exec_result.latency_ms,
            estimated_cost_cny=exec_result.cost_cny,
            raw_output_path=str(raw_path),
            response_metadata={
                "attempts": exec_result.attempts,
                "api_params": exec_result.api_params,
                "raw_usage": exec_result.raw_usage or {},
            },
        )

    def _execute_reruns(
        self,
        cases: list[GroundTruthCase],
        candidates: list[tuple[str, str]],
        run_dir: Path,
        dataset: str,
        run_index: int = 1,
    ) -> list[GroundTruthCaseResult]:
        """执行补跑。"""
        case_map = {c.id: c for c in cases}
        results = []
        raw_dir = run_dir / "raw_outputs"

        for case_id, model_name in candidates:
            case = case_map.get(case_id)
            if case is None:
                continue

            if self._force_mock:
                result = self._mock_evaluate(case, model_name, dataset, raw_dir, run_index)
            else:
                result = self._real_evaluate(case, model_name, dataset, raw_dir, run_index)
            results.append(result)

        return results

    def _run_signal_replay(
        self,
        cases: list[GroundTruthCase],
        results_index: dict,
        oracle_index: dict,
        dataset: Literal["dev", "holdout", "all"],
    ) -> list[Any]:
        """A 层策略回放：5 个策略共享 selector/estimator/candidate_models。

        策略：rules, ml_raw, ml_final, hybrid_050, hybrid_070。
        唯一变量是 feature_resolver 返回的 TaskFeatures（复杂度信号来源不同）。
        """
        from airouter.config import HybridConfig, load_all
        from airouter.engine.complexity.analyzer import ComplexityAnalyzer
        from airouter.engine.complexity.types import ROUTE_TO_COMPLEXITY
        from airouter.engine.router.analyzer import TaskAnalyzer
        from airouter.engine.router.estimator import CostEstimator
        from airouter.engine.router.selector import ModelSelector
        from airouter.models.model_registry import ModelRegistry

        config = load_all()
        base_config = config.complexity
        rule_analyzer = TaskAnalyzer()
        selector = ModelSelector()
        estimator = CostEstimator()

        # 候选模型池（通过 ModelRegistry 查找）
        registry = ModelRegistry(config.models)
        candidate_models = [
            entry for name in CANDIDATE_MODELS
            if (entry := registry.get_by_name(name)) is not None
        ]

        # 缓存 base features（所有策略共享，避免重复提取）
        base_features_cache: dict[str, Any] = {}

        def _get_base_features(case_id: str) -> Any:
            if case_id not in base_features_cache:
                case = case_map[case_id]
                text = _build_routing_text(case)
                base_features_cache[case_id] = rule_analyzer.extract_features(text)
            return base_features_cache[case_id]

        case_map = {c.id: c for c in cases}
        results = []

        # ── 策略 1: rules（纯规则，不修改 features）──
        def rules_feature_resolver(case: Any) -> Any:
            return _get_base_features(case.id)

        results.append(SignalLayerReplay().replay(
            "rules", rules_feature_resolver, cases,
            results_index, oracle_index,
            selector, estimator, candidate_models, dataset,
        ))

        # ── 策略 2-3: ml_raw / ml_final（共用 opensquilla analyzer）──
        try:
            ml_config = base_config.model_copy(
                update={"mode": "opensquilla", "require_runtime": True},
            )
            ml_analyzer = ComplexityAnalyzer(ml_config, rule_analyzer=rule_analyzer)

            for route_field, strategy_name in [
                ("raw_route_class", "ml_raw"),
                ("final_route_class", "ml_final"),
            ]:
                def make_ml_resolver(
                    _field: str = route_field,
                    _analyzer: ComplexityAnalyzer = ml_analyzer,
                ) -> Any:
                    def ml_feature_resolver(case: Any) -> Any:
                        text = _build_routing_text(case)
                        eval_result = _analyzer.analyze(text)
                        if eval_result.analysis.ml_prediction is None:
                            raise _MLUnavailableError(
                                f"ML prediction unavailable for case {case.id}"
                            )
                        pred = eval_result.analysis.ml_prediction
                        route_class = getattr(pred, _field)
                        complexity = ROUTE_TO_COMPLEXITY.get(
                            route_class,
                            eval_result.features.complexity,
                        )
                        base = _get_base_features(case.id)
                        return rule_analyzer.rebuild_complexity_dependent_features(
                            text, base, complexity, monotonic=False,
                        )
                    return ml_feature_resolver

                try:
                    r = SignalLayerReplay().replay(
                        strategy_name, make_ml_resolver(), cases,
                        results_index, oracle_index,
                        selector, estimator, candidate_models, dataset,
                    )
                except _MLUnavailableError:
                    r = _ml_unavailable_result(strategy_name, dataset)
                results.append(r)

        except Exception as e:
            log.warning("ML analyzer init failed: %s", e)
            for name in ("ml_raw", "ml_final"):
                results.append(_ml_unavailable_result(name, dataset))

        # ── 策略 4-5: hybrid（不同 confidence_threshold）──
        for threshold, name in [(0.50, "hybrid_050"), (0.70, "hybrid_070")]:
            try:
                hybrid_config = base_config.model_copy(update={
                    "mode": "hybrid", "require_runtime": True,
                    "hybrid": HybridConfig(confidence_threshold=threshold),
                })
                hybrid_analyzer = ComplexityAnalyzer(
                    hybrid_config, rule_analyzer=rule_analyzer,
                )

                def make_hybrid_resolver(
                    _a: ComplexityAnalyzer = hybrid_analyzer,
                ) -> Any:
                    def hybrid_feature_resolver(case: Any) -> Any:
                        text = _build_routing_text(case)
                        eval_result = _a.analyze(text)
                        if eval_result.analysis.ml_prediction is None:
                            raise _MLUnavailableError(
                                f"ML unavailable for hybrid case {case.id}"
                            )
                        return eval_result.features
                    return hybrid_feature_resolver

                try:
                    r = SignalLayerReplay().replay(
                        name, make_hybrid_resolver(), cases,
                        results_index, oracle_index,
                        selector, estimator, candidate_models, dataset,
                    )
                except _MLUnavailableError:
                    r = _ml_unavailable_result(name, dataset)
                results.append(r)

            except Exception as e:
                log.warning("Hybrid analyzer (%s) init failed: %s", name, e)
                results.append(_ml_unavailable_result(name, dataset))

        return results

    def _run_e2e_replay(
        self,
        cases: list[GroundTruthCase],
        results_index: dict,
        oracle_index: dict,
        dataset: Literal["dev", "holdout", "all"],
    ) -> list[Any]:
        """B 层端到端回放：多变体 Router（受限 SINGLE_MODEL + 5 候选模型池）。

        变体：rules_e2e, opensquilla_e2e, hybrid_050_e2e, hybrid_070_e2e。
        每个变体使用独立 complexity 配置。
        """
        from airouter.config import HybridConfig, ModelsConfig, load_all
        from airouter.engine.complexity.analyzer import ComplexityAnalyzer
        from airouter.engine.complexity.types import ComplexityContext
        from airouter.engine.router.analyzer import TaskAnalyzer
        from airouter.engine.router.router import Router
        from airouter.models.enums import StrategyType
        from airouter.models.model_registry import ModelRegistry

        base_config = load_all()
        results = []

        # 受限候选池（只有 5 个 benchmark 候选模型）
        registry = ModelRegistry(base_config.models)
        restricted_entries = [
            entry for name in CANDIDATE_MODELS
            if (entry := registry.get_by_name(name)) is not None
        ]
        restricted_registry = ModelRegistry(ModelsConfig(models=restricted_entries))

        e2e_variants: list[tuple[str, dict]] = [
            ("rules_e2e", {"mode": "rules"}),
            ("opensquilla_e2e", {"mode": "opensquilla", "require_runtime": True}),
            ("hybrid_050_e2e", {
                "mode": "hybrid", "require_runtime": True,
                "hybrid": HybridConfig(confidence_threshold=0.50),
            }),
            ("hybrid_070_e2e", {
                "mode": "hybrid", "require_runtime": True,
                "hybrid": HybridConfig(confidence_threshold=0.70),
            }),
        ]

        for variant_name, mode_overrides in e2e_variants:
            try:
                patched_complexity = base_config.complexity.model_copy(
                    update=mode_overrides,
                )
                patched_config = base_config.model_copy(
                    update={"complexity": patched_complexity},
                )
                ml_analyzer = ComplexityAnalyzer(
                    patched_complexity, rule_analyzer=TaskAnalyzer(),
                )
                router = Router(
                    config=patched_config,
                    complexity_analyzer=ml_analyzer,
                    model_registry=restricted_registry,
                    allowed_strategies=[StrategyType.SINGLE_MODEL],
                )

                def make_router_chooser(
                    _r: Router = router,
                ) -> Any:
                    def router_chooser(case: Any) -> tuple:
                        text = _build_routing_text(case)
                        rm = case.routing_metadata
                        user_texts = tuple(
                            m.content for m in rm.history_messages
                            if m.role == "user"
                        )
                        last_assistant = next(
                            (m.content for m in reversed(rm.history_messages)
                             if m.role == "assistant"),
                            None,
                        )
                        ctx = ComplexityContext.from_task(
                            text=text,
                            history=user_texts,
                            prev_assistant=last_assistant,
                            prev_assistant_usage=rm.prev_assistant_usage,
                            n_tools=rm.n_tools,
                            tool_result_length=rm.tool_result_length,
                        )
                        decision = _r.route(text, complexity_context=ctx)
                        executor_model = decision.models.executor
                        if executor_model and executor_model not in CANDIDATE_MODELS:
                            executor_model = None
                        action = _classify_decision(decision)
                        return executor_model, {
                            "selected_action": action,
                            "requires_human_review": decision.requires_human_review,
                            "strategy_type": decision.recommended_strategy.value,
                        }
                    return router_chooser

                replay = EndToEndReplay()
                r = replay.replay(
                    variant_name, cases, results_index, oracle_index,
                    make_router_chooser(), dataset,
                )
                results.append(r)

            except Exception as e:
                log.warning("B-layer variant %s failed: %s", variant_name, e)
                from airouter.engine.benchmark.ground_truth_schemas import (
                    StrategyReplayResult,
                )
                results.append(StrategyReplayResult(
                    strategy_name=variant_name, layer="end_to_end",
                    dataset=dataset, ml_unavailable=True,
                ))

        return results

    def _save_aggregated(self, path: Path, aggregated: list[AggregatedModelResult]) -> None:
        with open(path, "w", encoding="utf-8") as f:
            for a in aggregated:
                f.write(a.model_dump_json() + "\n")

    def _save_oracles(self, path: Path, oracles: list[OracleResult]) -> None:
        with open(path, "w", encoding="utf-8") as f:
            for o in oracles:
                f.write(o.model_dump_json() + "\n")


# ── 辅助函数 ─────────────────────────────────────────────────


def validate_evaluation_manifest(
    manifest_path: Path | None = None,
    holdout_hash: str | None = None,
    holdout_case_count: int | None = None,
) -> dict[str, Any]:
    """验证 evaluation_manifest.json 的完整性和一致性。

    dataset 含 holdout 时必须通过以下所有检查，否则 RuntimeError：
    - manifest 存在且为有效 JSON
    - holdout_hash 存在且匹配
    - holdout_case_count 存在且一致
    - schema_version / evaluator_version / config_version 受支持
    - frozen_at 存在

    返回 manifest dict。
    """
    path = manifest_path or DEFAULT_MANIFEST_PATH

    # 1. 存在性
    if not path.exists():
        raise RuntimeError(f"evaluation_manifest 不存在：{path}")

    # 2. JSON 格式
    try:
        manifest: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, ValueError) as e:
        raise RuntimeError(f"evaluation_manifest JSON 格式错误：{e}")

    # 3. holdout_hash
    expected_hash = manifest.get("holdout_hash")
    if not expected_hash:
        raise RuntimeError("evaluation_manifest 缺少 holdout_hash")
    if holdout_hash is not None and expected_hash != holdout_hash:
        raise RuntimeError(
            f"holdout_hash 不匹配：manifest={expected_hash}, computed={holdout_hash}"
        )

    # 4. holdout_case_count
    expected_count = manifest.get("holdout_case_count")
    if expected_count is None:
        raise RuntimeError("evaluation_manifest 缺少 holdout_case_count")
    if holdout_case_count is not None and expected_count != holdout_case_count:
        raise RuntimeError(
            f"holdout_case_count 不匹配：manifest={expected_count}, actual={holdout_case_count}"
        )

    # 5. 版本检查
    schema_ver = manifest.get("schema_version", "")
    if schema_ver not in _SUPPORTED_SCHEMA_VERSIONS:
        raise RuntimeError(f"不支持的 schema_version: {schema_ver}")
    eval_ver = manifest.get("evaluator_version", "")
    if eval_ver not in _SUPPORTED_EVALUATOR_VERSIONS:
        raise RuntimeError(f"不支持的 evaluator_version: {eval_ver}")
    config_ver = manifest.get("config_version", "")
    if config_ver not in _SUPPORTED_CONFIG_VERSIONS:
        raise RuntimeError(f"不支持的 config_version: {config_ver}")

    # 6. frozen_at
    if not manifest.get("frozen_at"):
        raise RuntimeError("evaluation_manifest 缺少 frozen_at")

    return manifest


def _gt_completed_pairs(jsonl_path: Path) -> set[str]:
    """GT 专用 resume：只要 (case_id, model) 曾出现 status='success'，就算完成。

    不使用 last-entry-wins：如果 run_index=0 成功、后续 rerun 失败，
    pair 仍然算完成（已有有效数据）。
    """
    completed: set[str] = set()
    if not jsonl_path.exists():
        return completed
    for line in jsonl_path.read_text(encoding="utf-8").strip().splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        key = f"{r['case_id']}::{r['model']}"
        if r.get("status") == "success":
            completed.add(key)  # 一旦成功，不会被后续失败覆盖
    return completed


def _append_results(path: Path, results: list[GroundTruthCaseResult]) -> None:
    """追加结果到 JSONL 文件（线程安全由调用者保证）。"""
    with open(path, "a", encoding="utf-8") as f:
        for r in results:
            f.write(r.model_dump_json() + "\n")


def _load_deduped_by_run(path: Path) -> list[GroundTruthCaseResult]:
    """从 JSONL 加载结果，按 (case_id, model, run_index) 去重，保留最后一条。"""
    if not path.exists():
        return []
    seen: dict[tuple[str, str, int], GroundTruthCaseResult] = {}
    for line in path.read_text(encoding="utf-8").strip().splitlines():
        if not line.strip():
            continue
        r = GroundTruthCaseResult.model_validate_json(line)
        key = (r.case_id, r.model, r.run_index)
        seen[key] = r
    return list(seen.values())


def _model_tier(model_name: str) -> int:
    """根据模型名返回 tier。"""
    tier_map = {
        "qwen3.7-max": 1,
        "deepseek-v4-pro": 1,
        "kimi-k2.6": 1,
        "qwen3.7-plus": 2,
        "glm-5.1": 2,
        "MiniMax-M3": 2,
        "deepseek-v4-flash": 3,
    }
    return tier_map.get(model_name, 2)


def _estimate_cost(tier: int, input_tokens: int, output_tokens: int) -> float:
    """估算成本（CNY）。"""
    # 简化价格表（每 1k tokens）
    prices = {
        1: (0.02, 0.10),  # (input, output)
        2: (0.005, 0.03),
        3: (0.001, 0.005),
    }
    inp_price, out_price = prices.get(tier, (0.005, 0.03))
    return (input_tokens / 1000 * inp_price) + (output_tokens / 1000 * out_price)


def _infer_dataset_label(case: Any, dataset_arg: str) -> Literal["dev", "holdout"]:
    """推断 case 属于 dev 还是 holdout。

    Engineering domain = dev, GENERAL domain with holdout categories = holdout.
    """
    if dataset_arg == "dev":
        return "dev"
    if dataset_arg == "holdout":
        return "holdout"
    # "all" → 按 domain 推断
    domain = getattr(case, "domain", "")
    if domain == "ENGINEERING":
        return "dev"
    return "holdout"


def rescore_run(
    run_dir: Path,
    cases_path: str | Path,
    output_name: str = "results.rescored.jsonl",
) -> Path:
    """离线重评分已有 run 的 results.jsonl。

    读取 results.jsonl + raw_outputs，用当前 evaluator 重新评分，
    写入 results.rescored.jsonl（不覆盖原始文件）。

    返回 rescored 文件路径。
    """
    from airouter.engine.benchmark.ground_truth_loader import (
        load_dev_cases,
        load_holdout_cases,
    )

    results_path = run_dir / "results.jsonl"
    if not results_path.exists():
        raise FileNotFoundError(f"results.jsonl not found: {results_path}")

    # Load cases based on path
    cases_path_obj = Path(cases_path) if isinstance(cases_path, str) else cases_path
    if "engineering" in str(cases_path_obj):
        cases = load_dev_cases(cases_path_obj)
    else:
        cases = load_holdout_cases(cases_path_obj)
    case_index = {c.id: c for c in cases}

    # Load existing results
    all_results = _load_deduped_by_run(results_path)

    # Rescore
    rescored: list[GroundTruthCaseResult] = []
    for r in all_results:
        case = case_index.get(r.case_id)
        if case is None:
            # Case not found in current cases file → keep original
            rescored.append(r)
            continue

        raw_path = r.raw_output_path
        if not raw_path or not Path(raw_path).exists():
            # No raw output → keep original
            rescored.append(r)
            continue

        raw_output = Path(raw_path).read_text(encoding="utf-8")

        # Re-evaluate with current evaluator
        eval_result = evaluate_case(case, raw_output)
        final = compute_final_score(
            deterministic_passed=eval_result.deterministic_passed,
            deterministic_score=eval_result.deterministic_score,
            rule_score_val=eval_result.rule_score,
            judge_score=r.judge_score,  # Preserve existing judge score
            hard_failure_ids=eval_result.hard_failure_ids,
            pass_threshold=r.pass_threshold,
        )

        # Build rescored result (preserve all original metadata)
        new_result = r.model_copy(update={
            "deterministic_passed": eval_result.deterministic_passed,
            "deterministic_score": eval_result.deterministic_score,
            "rule_score": eval_result.rule_score,
            "final_score": final,
            "hard_failure_ids": eval_result.hard_failure_ids,
            "soft_violation_ids": eval_result.soft_violation_ids,
            "final_pass": final >= r.pass_threshold and not eval_result.hard_failure_ids,
            "dimension_scores": eval_result.dimension_scores,
        })
        rescored.append(new_result)

    # Write rescored results
    output_path = run_dir / output_name
    with open(output_path, "w", encoding="utf-8") as f:
        for r in rescored:
            f.write(r.model_dump_json() + "\n")

    log.info(
        "Rescored %d pairs → %s",
        len(rescored), output_path,
    )
    return output_path
