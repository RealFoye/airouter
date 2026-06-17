"""Unit tests for ground_truth_runner.py — resume/rerun/persistence."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from airouter.engine.benchmark.ground_truth_runner import (
    GroundTruthRunner,
    _append_results,
    _build_routing_text,
    _classify_decision,
    _estimate_cost,
    _gt_completed_pairs,
    _infer_dataset_label,
    _load_deduped_by_run,
    _ml_unavailable_result,
    _model_tier,
)
from airouter.engine.benchmark.ground_truth_schemas import (
    CANDIDATE_MODELS,
    GroundTruthCase,
    GroundTruthCaseResult,
)

# ── 辅助 ────────────────────────────────────────────────────────


def _case(case_id: str, domain: str = "GENERAL", risk: str = "LOW") -> GroundTruthCase:
    return GroundTruthCase(
        id=case_id,
        domain=domain,
        category="CODE_DEBUG",
        prompt=f"Fix bug in {case_id}",
        risk_level=risk,
    )


def _result(
    case_id: str,
    model: str,
    run_index: int = 0,
    status: str = "success",
    score: float = 0.9,
    cost: float = 0.01,
) -> GroundTruthCaseResult:
    return GroundTruthCaseResult(
        case_id=case_id,
        model=model,
        run_index=run_index,
        status=status,
        final_score=score,
        final_pass=score >= 0.8,
        estimated_cost_cny=cost,
    )


# ── _gt_completed_pairs ──────────────────────────────────────────


class TestGtCompletedPairs:
    """GT resume 逻辑：any-success 语义。"""

    def test_empty_file(self, tmp_path: Path):
        p = tmp_path / "results.jsonl"
        assert _gt_completed_pairs(p) == set()

    def test_success_pair_marked_completed(self, tmp_path: Path):
        p = tmp_path / "results.jsonl"
        r = _result("GT-001", "qwen3.7-max")
        p.write_text(r.model_dump_json() + "\n", encoding="utf-8")
        completed = _gt_completed_pairs(p)
        assert "GT-001::qwen3.7-max" in completed

    def test_failed_pair_not_completed(self, tmp_path: Path):
        p = tmp_path / "results.jsonl"
        r = _result("GT-001", "qwen3.7-max", status="failed")
        p.write_text(r.model_dump_json() + "\n", encoding="utf-8")
        completed = _gt_completed_pairs(p)
        assert "GT-001::qwen3.7-max" not in completed

    def test_success_then_fail_still_completed(self, tmp_path: Path):
        """run_index=0 成功后 rerun 失败 → 仍然完成（any-success）。"""
        p = tmp_path / "results.jsonl"
        r1 = _result("GT-001", "qwen3.7-max", run_index=0, status="success")
        r2 = _result("GT-001", "qwen3.7-max", run_index=1, status="failed")
        p.write_text(
            r1.model_dump_json() + "\n" + r2.model_dump_json() + "\n",
            encoding="utf-8",
        )
        completed = _gt_completed_pairs(p)
        assert "GT-001::qwen3.7-max" in completed

    def test_multiple_pairs(self, tmp_path: Path):
        p = tmp_path / "results.jsonl"
        lines = [
            _result("GT-001", "qwen3.7-max", status="success").model_dump_json(),
            _result("GT-001", "deepseek-v4-flash", status="failed").model_dump_json(),
            _result("GT-002", "qwen3.7-max", status="success").model_dump_json(),
        ]
        p.write_text("\n".join(lines) + "\n", encoding="utf-8")
        completed = _gt_completed_pairs(p)
        assert "GT-001::qwen3.7-max" in completed
        assert "GT-001::deepseek-v4-flash" not in completed
        assert "GT-002::qwen3.7-max" in completed


# ── _append_results ──────────────────────────────────────────────


class TestAppendResults:
    def test_creates_file(self, tmp_path: Path):
        p = tmp_path / "results.jsonl"
        _append_results(p, [_result("GT-001", "m1")])
        assert p.exists()
        lines = p.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1

    def test_appends_not_overwrites(self, tmp_path: Path):
        p = tmp_path / "results.jsonl"
        _append_results(p, [_result("GT-001", "m1")])
        _append_results(p, [_result("GT-002", "m2")])
        lines = p.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 2

    def test_multiple_results_in_one_call(self, tmp_path: Path):
        p = tmp_path / "results.jsonl"
        _append_results(p, [
            _result("GT-001", "m1"),
            _result("GT-002", "m2"),
        ])
        lines = p.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 2


# ── _load_deduped_by_run ─────────────────────────────────────────


class TestLoadDedupedByRun:
    def test_empty_path(self, tmp_path: Path):
        p = tmp_path / "results.jsonl"
        assert _load_deduped_by_run(p) == []

    def test_no_duplicates(self, tmp_path: Path):
        p = tmp_path / "results.jsonl"
        _append_results(p, [
            _result("GT-001", "m1", run_index=0),
            _result("GT-002", "m1", run_index=0),
        ])
        results = _load_deduped_by_run(p)
        assert len(results) == 2

    def test_dedup_keeps_last_entry(self, tmp_path: Path):
        """(case_id, model, run_index) 重复时保留最后一条。"""
        p = tmp_path / "results.jsonl"
        _append_results(p, [
            _result("GT-001", "m1", run_index=0, score=0.5),
            _result("GT-001", "m1", run_index=0, score=0.9),
        ])
        results = _load_deduped_by_run(p)
        assert len(results) == 1
        assert results[0].final_score == 0.9

    def test_different_run_indices_preserved(self, tmp_path: Path):
        """不同 run_index 的结果都保留。"""
        p = tmp_path / "results.jsonl"
        _append_results(p, [
            _result("GT-001", "m1", run_index=0),
            _result("GT-001", "m1", run_index=1),
            _result("GT-001", "m1", run_index=2),
        ])
        results = _load_deduped_by_run(p)
        assert len(results) == 3
        run_indices = {r.run_index for r in results}
        assert run_indices == {0, 1, 2}


# ── _model_tier / _estimate_cost ─────────────────────────────────


class TestHelpers:
    def test_model_tier_known(self):
        assert _model_tier("qwen3.7-max") == 1
        assert _model_tier("qwen3.7-plus") == 2
        assert _model_tier("deepseek-v4-flash") == 3

    def test_model_tier_unknown_defaults_to_2(self):
        assert _model_tier("unknown-model") == 2

    def test_estimate_cost_tier1_more_expensive(self):
        cost1 = _estimate_cost(1, 1000, 1000)
        cost3 = _estimate_cost(3, 1000, 1000)
        assert cost1 > cost3

    def test_estimate_cost_proportional_to_tokens(self):
        cost_1k = _estimate_cost(2, 1000, 1000)
        cost_2k = _estimate_cost(2, 2000, 2000)
        assert cost_2k == pytest.approx(cost_1k * 2)


# ── _infer_dataset_label ─────────────────────────────────────────


class TestInferDatasetLabel:
    def test_dev_arg_returns_dev(self):
        case = _case("GT-001", domain="GENERAL")
        assert _infer_dataset_label(case, "dev") == "dev"

    def test_holdout_arg_returns_holdout(self):
        case = _case("GT-001", domain="GENERAL")
        assert _infer_dataset_label(case, "holdout") == "holdout"

    def test_all_engineering_is_dev(self):
        case = _case("GT-001", domain="ENGINEERING")
        assert _infer_dataset_label(case, "all") == "dev"

    def test_all_general_is_holdout(self):
        case = _case("GT-001", domain="GENERAL")
        assert _infer_dataset_label(case, "all") == "holdout"


# ── Mock output ──────────────────────────────────────────────────


class TestMockOutput:
    def test_no_answer_leakage(self):
        """Mock 输出不复制 expected_behavior（防止答案泄漏）。"""
        runner = GroundTruthRunner(force_mock=True)
        case = _case("GT-001")
        # 设置 expected_behavior
        case = case.model_copy(update={"expected_behavior": ["找到 off-by-one bug"]})
        output = runner._generate_mock_output(case, "qwen3.7-max")
        parsed = json.loads(output)
        assert "找到 off-by-one bug" not in parsed.get("findings", [])
        assert parsed["findings"] == []

    def test_mock_output_has_required_fields(self):
        runner = GroundTruthRunner(force_mock=True)
        case = _case("GT-001")
        output = runner._generate_mock_output(case, "deepseek-v4-flash")
        parsed = json.loads(output)
        for field in ["action", "summary", "findings", "evidence", "patch"]:
            assert field in parsed

    def test_mock_evaluate_writes_raw_output(self, tmp_path: Path):
        """Mock 评估实际写入 raw output 文件。"""
        runner = GroundTruthRunner(force_mock=True, results_dir=tmp_path)
        case = _case("GT-001")
        raw_dir = tmp_path / "raw_outputs"
        raw_dir.mkdir(exist_ok=True)
        result = runner._mock_evaluate(case, "qwen3.7-max", "dev", raw_dir)
        assert result.status == "success"
        assert result.raw_output_path is not None
        assert Path(result.raw_output_path).exists()
        content = Path(result.raw_output_path).read_text(encoding="utf-8")
        assert "action" in content


# ── Runner.run() mock integration ────────────────────────────────


class TestRunnerMockIntegration:
    def test_mock_run_summary_fields(self, tmp_path: Path):
        """Mock 模式的 summary 应标记 is_mock_run=True, total_physical_api_calls=0。"""
        runner = GroundTruthRunner(force_mock=True, results_dir=tmp_path)
        summary = runner.run(dataset="dev")
        assert summary.is_mock_run is True
        assert summary.total_physical_api_calls == 0
        assert summary.mock_evaluations > 0

    def test_resume_skips_completed(self, tmp_path: Path):
        """Resume 不重复执行已完成的 pair。"""
        runner = GroundTruthRunner(force_mock=True, results_dir=tmp_path)
        # 首次运行
        s1 = runner.run(dataset="dev")
        # Resume
        s2 = runner.run(dataset="dev", resume=True, run_id=s1.run_id)
        # 没有新的 pair 被执行
        assert s2.candidate_initial_calls == 0


# ── _build_gt_messages ───────────────────────────────────────────


class TestBuildGtMessages:
    def test_basic_messages(self):
        """构建基础 system + user 消息。"""
        runner = GroundTruthRunner(force_mock=True)
        case = _case("GT-001")
        messages = runner._build_gt_messages(case)
        assert messages[0]["role"] == "system"
        assert "结构化 JSON" in messages[0]["content"]
        assert messages[-1]["role"] == "user"
        assert case.prompt in messages[-1]["content"]

    def test_with_input_context(self):
        """input_context 拼接到 user 消息前面。"""
        runner = GroundTruthRunner(force_mock=True)
        case = _case("GT-001")
        case = case.model_copy(update={"input_context": "Some context here"})
        messages = runner._build_gt_messages(case)
        user_content = messages[-1]["content"]
        assert "Some context here" in user_content
        assert user_content.index("Some context here") < user_content.index(case.prompt)

    def test_with_history_messages(self):
        """多轮历史消息正确插入。"""
        from airouter.engine.benchmark.ground_truth_schemas import (
            RoutingMessage,
            RoutingMetadata,
        )
        runner = GroundTruthRunner(force_mock=True)
        case = _case("GT-001")
        case = case.model_copy(update={
            "routing_metadata": RoutingMetadata(
                history_messages=[
                    RoutingMessage(role="user", content="first question"),
                    RoutingMessage(role="assistant", content="first answer"),
                ],
            ),
        })
        messages = runner._build_gt_messages(case)
        # system + 2 history + 1 user = 4
        assert len(messages) == 4
        assert messages[1]["role"] == "user"
        assert messages[1]["content"] == "first question"
        assert messages[2]["role"] == "assistant"
        assert messages[2]["content"] == "first answer"


# ── _real_evaluate without executor ──────────────────────────────


class TestRealEvaluateGuard:
    def test_no_executor_raises(self, tmp_path: Path):
        """force_mock=False + no executor → RuntimeError."""
        runner = GroundTruthRunner(force_mock=True, results_dir=tmp_path)
        # Manually set force_mock=False without executor
        runner._force_mock = False
        runner._executor = None
        case = _case("GT-001")
        raw_dir = tmp_path / "raw"
        raw_dir.mkdir()
        with pytest.raises(RuntimeError, match="executor not initialized"):
            runner._real_evaluate(case, "qwen3.7-max", "dev", raw_dir)


# ── AdapterFactory mock fallback ─────────────────────────────────


class TestAdapterFactoryMockFallback:
    def test_mock_fallback_disabled_raises(self):
        """allow_mock_fallback=False + missing key → AdapterAuthError."""
        from airouter.adapters.base import AdapterAuthError
        from airouter.adapters.factory import AdapterFactory
        from airouter.config import AppSettings, ModelEntry

        # Explicitly empty settings (no API keys)
        settings = AppSettings(
            dashscope_api_key="",
            deepseek_api_key="",
            zhipu_api_key="",
            kimi_api_key="",
            minimax_api_key="",
        )
        factory = AdapterFactory(
            settings=settings,
            allow_mock_fallback=False,
        )
        entry = ModelEntry(
            name="test-model",
            provider="deepseek",
            api_base="https://api.deepseek.com",
            input_price_per_1k=0.01,
            output_price_per_1k=0.02,
            tier=1,
            max_context_window=128000,
        )
        with pytest.raises(AdapterAuthError, match="mock fallback is disabled"):
            factory.get_adapter(entry)

    def test_mock_fallback_enabled_returns_mock(self):
        """allow_mock_fallback=True + missing key → MockAdapter."""
        from airouter.adapters.factory import AdapterFactory
        from airouter.adapters.mock import MockAdapter
        from airouter.config import AppSettings, ModelEntry

        settings = AppSettings(
            dashscope_api_key="",
            deepseek_api_key="",
            zhipu_api_key="",
            kimi_api_key="",
            minimax_api_key="",
        )
        factory = AdapterFactory(
            settings=settings,
            allow_mock_fallback=True,
        )
        entry = ModelEntry(
            name="test-model",
            provider="deepseek",
            api_base="https://api.deepseek.com",
            input_price_per_1k=0.01,
            output_price_per_1k=0.02,
            tier=1,
            max_context_window=128000,
        )
        adapter = factory.get_adapter(entry)
        assert isinstance(adapter, MockAdapter)


# ── _build_routing_text ─────────────────────────────────────────


class TestBuildRoutingText:
    def test_prompt_only(self):
        case = _case("GT-001")
        text = _build_routing_text(case)
        assert text == case.prompt
        assert "expected_behavior" not in text

    def test_with_input_context(self):
        case = _case("GT-001")
        case = case.model_copy(update={"input_context": "Some context here"})
        text = _build_routing_text(case)
        assert "Some context here" in text
        assert case.prompt in text
        assert text.index("Some context here") < text.index(case.prompt)


# ── _classify_decision ────────────────────────────────────────────


class TestClassifyDecision:
    def _make_decision(self, executor=None, requires_review=False, risk="LOW"):
        from airouter.models.enums import TaskCategory
        from airouter.models.schemas import ModelAssignment, RoutingDecision, TaskFeatures

        features = TaskFeatures(
            category=TaskCategory.BUG_ANALYSIS,
            complexity="MODERATE",
            risk_level=risk,
        )
        return RoutingDecision(
            task_hash="test",
            task_features=features,
            recommended_strategy="SINGLE_MODEL",
            models=ModelAssignment(executor=executor),
            estimated_cost=0.01 if executor else 0.0,
            baseline_cost=0.05,
            estimated_savings=0.8 if executor else 0.0,
            estimated_quality=0.9 if executor else 0.0,
            quality_loss_vs_baseline=0.0,
            risk_level=risk,
            requires_human_review=requires_review,
            reasons=[],
            alternatives=[],
            budget_status="OK",
            quality_gate=[],
            fallback_policy=[],
            config_version="v1",
        )

    def test_auto(self):
        """executor 存在 + 不需审查 → AUTO。"""
        decision = self._make_decision(executor="qwen3.7-plus")
        assert _classify_decision(decision) == "AUTO"

    def test_execute_with_review(self):
        """executor 存在 + 需审查 → EXECUTE_WITH_REVIEW。"""
        decision = self._make_decision(executor="qwen3.7-plus", requires_review=True, risk="HIGH")
        assert _classify_decision(decision) == "EXECUTE_WITH_REVIEW"

    def test_escalate_to_human(self):
        """无 executor → ESCALATE_TO_HUMAN。"""
        decision = self._make_decision(executor=None, requires_review=True)
        assert _classify_decision(decision) == "ESCALATE_TO_HUMAN"


# ── _ml_unavailable_result ────────────────────────────────────────


class TestMLUnavailableResult:
    def test_signal_layer(self):
        result = _ml_unavailable_result("ml_raw", "dev")
        assert result.strategy_name == "ml_raw"
        assert result.layer == "signal"
        assert result.dataset == "dev"
        assert result.ml_unavailable is True
        assert result.acceptable_match_rate == 0.0


# ── --limit 精确切片 ───────────────────────────────────────────


class TestLimitSlicing:
    """--limit N 语义：本次最多执行 N 个新 pair（resume 历史不计入 N）。"""

    def test_limit_slices_exact(self, tmp_path: Path):
        """limit=3 → new_pairs_this_run == 3。"""
        runner = GroundTruthRunner(force_mock=True, results_dir=tmp_path)
        summary = runner.run(dataset="dev", limit=3)
        assert summary.new_pairs_this_run == 3
        assert summary.expected_pairs == 3
        assert summary.completed_before == 0
        assert summary.completed_after == 3

    def test_limit_exceeds_remaining(self, tmp_path: Path):
        """limit=10000 但 dev 只有 150 pairs → new_pairs_this_run == 150。"""
        runner = GroundTruthRunner(force_mock=True, results_dir=tmp_path)
        summary = runner.run(dataset="dev", limit=10000)
        # dev = 30 cases × 5 models = 150
        assert summary.new_pairs_this_run == 150
        assert summary.remaining_pairs == 0
        assert summary.run_completed is True

    def test_limit_with_resume(self, tmp_path: Path):
        """resume 已有 3 pair + limit 2 → 新增 2 条。"""
        runner = GroundTruthRunner(force_mock=True, results_dir=tmp_path)
        # 首次跑 3 pair
        s1 = runner.run(dataset="dev", limit=3)
        assert s1.new_pairs_this_run == 3
        # resume + limit 2
        s2 = runner.run(dataset="dev", resume=True, run_id=s1.run_id, limit=2)
        assert s2.new_pairs_this_run == 2
        assert s2.completed_before == 3
        assert s2.completed_after == 5


# ── Oracle 完整 case 过滤 ─────────────────────────────────────


class TestOracleCompleteCaseFilter:
    """Oracle/Replay 只处理 5 个模型均 status=success 的完整 case。"""

    def test_oracle_deferred_when_no_complete_cases(self, tmp_path: Path):
        """limit=2 → 没有 case 有 5 个模型的完整结果 → analysis_deferred=True。"""
        runner = GroundTruthRunner(force_mock=True, results_dir=tmp_path)
        summary = runner.run(dataset="dev", limit=2)
        # 2 pairs 不可能有完整 case（需要 5 个模型）
        assert summary.analysis_deferred is True
        assert summary.oracle_results == []
        assert summary.signal_strategy_results == []
        assert summary.end_to_end_strategy_results == []
        assert summary.complete_cases == 0

    def test_oracle_runs_when_complete_cases_exist(self, tmp_path: Path):
        """全量运行 → 有完整 case → analysis_deferred=False。"""
        runner = GroundTruthRunner(force_mock=True, results_dir=tmp_path)
        summary = runner.run(dataset="dev")
        assert summary.analysis_deferred is False
        assert len(summary.oracle_results) > 0
        assert summary.complete_cases > 0


# ── CLI 互斥校验 ──────────────────────────────────────────────


class TestRoutingCLIMutualExclusion:
    """--rerun 与 --limit / --resume 互斥。"""

    def test_rerun_limit_rejected(self):
        """--rerun --limit 5 → exit 1。"""
        from typer.testing import CliRunner

        from airouter.cli.main import app
        runner = CliRunner()
        result = runner.invoke(
            app,
            ["benchmark", "--level", "routing", "--rerun", "--limit", "5",
             "--output-dir", "/tmp/test_routing_cli"],
        )
        assert result.exit_code == 1
        assert "rerun" in result.output.lower() or "不能" in result.output

    def test_rerun_resume_rejected(self):
        """--rerun --resume → exit 1。"""
        from typer.testing import CliRunner

        from airouter.cli.main import app
        runner = CliRunner()
        result = runner.invoke(
            app,
            ["benchmark", "--level", "routing", "--rerun", "--resume",
             "--output-dir", "/tmp/test_routing_cli"],
        )
        assert result.exit_code == 1
        assert "rerun" in result.output.lower() or "不能" in result.output

    def test_judge_requires_explicit_model(self):
        """--judge 无 --judge-model → exit 1。"""
        from typer.testing import CliRunner

        from airouter.cli.main import app
        runner = CliRunner()
        result = runner.invoke(
            app,
            ["benchmark", "--level", "routing", "--judge",
             "--output-dir", "/tmp/test_routing_cli"],
        )
        assert result.exit_code == 1
        assert "judge" in result.output.lower() or "model" in result.output.lower()


# ── Manifest 强校验 ──────────────────────────────────────────


class TestManifestValidation:
    """evaluation_manifest.json 强校验：缺失/篡改/版本不匹配 → RuntimeError。"""

    def _write_manifest(self, tmp_path: Path, data: dict) -> Path:
        import json
        p = tmp_path / "evaluation_manifest.json"
        p.write_text(json.dumps(data), encoding="utf-8")
        return p

    def _valid_manifest(self) -> dict:
        return {
            "frozen_at": "2026-06-14T00:00:00Z",
            "holdout_hash": "sha256:abc123",
            "holdout_case_count": 60,
            "schema_version": "1.0",
            "evaluator_version": "1.0",
            "config_version": "1.0",
        }

    def test_manifest_missing_raises(self, tmp_path: Path):
        from airouter.engine.benchmark.ground_truth_runner import validate_evaluation_manifest
        with pytest.raises(RuntimeError, match="不存在"):
            validate_evaluation_manifest(tmp_path / "nonexistent.json")

    def test_manifest_invalid_json_raises(self, tmp_path: Path):
        from airouter.engine.benchmark.ground_truth_runner import validate_evaluation_manifest
        p = tmp_path / "evaluation_manifest.json"
        p.write_text("{invalid json", encoding="utf-8")
        with pytest.raises(RuntimeError, match="JSON 格式错误"):
            validate_evaluation_manifest(p)

    def test_manifest_hash_mismatch_raises(self, tmp_path: Path):
        from airouter.engine.benchmark.ground_truth_runner import validate_evaluation_manifest
        data = self._valid_manifest()
        p = self._write_manifest(tmp_path, data)
        with pytest.raises(RuntimeError, match="holdout_hash 不匹配"):
            validate_evaluation_manifest(p, holdout_hash="sha256:different")

    def test_manifest_count_mismatch_raises(self, tmp_path: Path):
        from airouter.engine.benchmark.ground_truth_runner import validate_evaluation_manifest
        data = self._valid_manifest()
        p = self._write_manifest(tmp_path, data)
        with pytest.raises(RuntimeError, match="holdout_case_count 不匹配"):
            validate_evaluation_manifest(p, holdout_case_count=99)

    def test_manifest_version_check(self, tmp_path: Path):
        from airouter.engine.benchmark.ground_truth_runner import validate_evaluation_manifest
        data = self._valid_manifest()
        data["schema_version"] = "99.0"
        p = self._write_manifest(tmp_path, data)
        with pytest.raises(RuntimeError, match="不支持的 schema_version"):
            validate_evaluation_manifest(p)

    def test_manifest_frozen_at_required(self, tmp_path: Path):
        from airouter.engine.benchmark.ground_truth_runner import validate_evaluation_manifest
        data = self._valid_manifest()
        del data["frozen_at"]
        p = self._write_manifest(tmp_path, data)
        with pytest.raises(RuntimeError, match="缺少 frozen_at"):
            validate_evaluation_manifest(p)

    def test_manifest_valid_passes(self, tmp_path: Path):
        from airouter.engine.benchmark.ground_truth_runner import validate_evaluation_manifest
        data = self._valid_manifest()
        p = self._write_manifest(tmp_path, data)
        result = validate_evaluation_manifest(
            p, holdout_hash="sha256:abc123", holdout_case_count=60,
        )
        assert result["holdout_hash"] == "sha256:abc123"

    def test_dev_only_skips_manifest(self, tmp_path: Path):
        """dataset=dev 不触发 manifest 验证。"""
        runner = GroundTruthRunner(force_mock=True, results_dir=tmp_path)
        summary = runner.run(dataset="dev", limit=3)
        assert summary.holdout_hash is None
        assert summary.evaluation_manifest is None

    def test_summary_has_holdout_hash(self, tmp_path: Path):
        """dataset=all 时 summary 填充 holdout_hash。"""
        runner = GroundTruthRunner(force_mock=True, results_dir=tmp_path)
        summary = runner.run(dataset="all", limit=3)
        assert summary.holdout_hash is not None
        assert summary.holdout_hash.startswith("sha256:")
        assert summary.eval_frozen_at is not None
        assert summary.evaluation_manifest is not None


# ── 并发执行测试 ─────────────────────────────────────────────


class TestConcurrentExecution:
    """Real API 并发执行 + AdapterAuthError 取消。"""

    def test_mock_sequential(self, tmp_path: Path):
        """Mock 模式始终顺序执行。"""
        runner = GroundTruthRunner(force_mock=True, results_dir=tmp_path, workers=5)
        # Mock 模式下 _execute_and_evaluate 应该走顺序路径
        cases = [_case("GT-001"), _case("GT-002")]
        run_dir = tmp_path / "run_001"
        run_dir.mkdir(parents=True, exist_ok=True)
        results_path = run_dir / "results.jsonl"

        results = runner._execute_and_evaluate(
            cases, run_dir, set(), "dev", results_path, limit=5,
        )
        # 2 cases × 5 models = 10 pairs, limit=5 → 5 results
        assert len(results) == 5
        # Mock 模式下所有结果都是 success
        assert all(r.status == "success" for r in results)

    def test_concurrent_uses_thread_pool(self, tmp_path: Path):
        """Real API + workers > 1 → 使用 ThreadPoolExecutor。"""
        from unittest.mock import MagicMock

        # Mock executor
        mock_executor = MagicMock()
        mock_exec_result = MagicMock()
        mock_exec_result.response_content = '{"action": "answer", "summary": "test"}'
        mock_exec_result.input_tokens = 100
        mock_exec_result.output_tokens = 50
        mock_exec_result.latency_ms = 100
        mock_exec_result.cost_cny = 0.01
        mock_exec_result.attempts = 1
        mock_exec_result.api_params = {}
        mock_exec_result.raw_usage = {}
        mock_executor.execute.return_value = mock_exec_result

        runner = GroundTruthRunner(
            force_mock=False, results_dir=tmp_path, workers=3,
            executor=mock_executor, allow_mock_fallback=True,
        )

        cases = [_case("GT-001")]
        run_dir = tmp_path / "run_002"
        run_dir.mkdir(parents=True, exist_ok=True)
        results_path = run_dir / "results.jsonl"

        results = runner._execute_and_evaluate(
            cases, run_dir, set(), "dev", results_path, limit=5,
        )

        # 1 case × 5 models = 5 pairs
        assert len(results) == 5
        # 所有结果都是 success
        assert all(r.status == "success" for r in results)
        # executor.execute 被调用 5 次
        assert mock_executor.execute.call_count == 5

    def test_auth_error_cancels_pending(self, tmp_path: Path):
        """AdapterAuthError → 取消 pending futures 并停止。"""
        from unittest.mock import MagicMock

        from airouter.adapters.base import AdapterAuthError

        # Mock executor：第一次调用成功，第二次抛 auth error
        mock_executor = MagicMock()
        call_count = [0]

        def side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 2:
                raise AdapterAuthError("Invalid API key")
            mock_result = MagicMock()
            mock_result.response_content = '{"action": "answer", "summary": "test"}'
            mock_result.input_tokens = 100
            mock_result.output_tokens = 50
            mock_result.latency_ms = 100
            mock_result.cost_cny = 0.01
            mock_result.attempts = 1
            mock_result.api_params = {}
            mock_result.raw_usage = {}
            return mock_result

        mock_executor.execute.side_effect = side_effect

        runner = GroundTruthRunner(
            force_mock=False, results_dir=tmp_path, workers=2,
            executor=mock_executor, allow_mock_fallback=True,
        )

        cases = [_case("GT-001"), _case("GT-002"), _case("GT-003")]
        run_dir = tmp_path / "run_003"
        run_dir.mkdir(parents=True, exist_ok=True)
        results_path = run_dir / "results.jsonl"

        results = runner._execute_and_evaluate(
            cases, run_dir, set(), "dev", results_path, limit=10,
        )

        # 应该有结果（包括 auth error 的失败结果）
        # 并发执行顺序不确定，auth error 可能先完成，所以至少有 1 个结果
        assert len(results) >= 1
        # 至少有一个 auth_error
        auth_errors = [r for r in results if r.error_type == "auth_error"]
        assert len(auth_errors) >= 1
        # executor.execute 调用次数应该少于总 pair 数（因为取消了 pending）
        # 3 cases × 5 models = 15 pairs, workers=2, auth error at call 2
        # 实际调用次数应该在 2-4 之间（取决于并发调度）
        assert call_count[0] < 15, f"Expected < 15 calls, got {call_count[0]}"


# ── rebuild_analysis 回归测试 ──────────────────────────────────


class TestRebuildAnalysisPartialCase:
    """不完整 case（< 5 模型 success）不得进入 Oracle。"""

    def _make_cases_and_results(self, complete: bool = True):
        """构造 2 个 case：GT-001 完整，GT-002 部分（3/5 success）。"""
        cases = [
            _case("GT-001", domain="GENERAL", risk="LOW"),
            _case("GT-002", domain="GENERAL", risk="LOW"),
        ]
        models = list(CANDIDATE_MODELS)

        results = []
        # GT-001: all 5 models success
        for m in models:
            results.append(_result("GT-001", m, status="success", score=0.9))

        # GT-002: only 3 models success, 2 failed
        for i, m in enumerate(models):
            if i < 3:
                results.append(_result("GT-002", m, status="success", score=0.85))
            else:
                results.append(_result("GT-002", m, status="failed", score=0.0))

        return cases, results

    def test_partial_case_not_in_oracle(self, tmp_path: Path):
        """GT-002 只有 3/5 success → 不在 Oracle 中。"""
        runner = GroundTruthRunner(force_mock=True, results_dir=tmp_path)
        cases, results = self._make_cases_and_results()

        artifacts = runner.rebuild_analysis(cases, results, "dev")

        # 只有 GT-001 是完整 case
        assert len(artifacts.complete_cases) == 1
        assert artifacts.complete_cases[0].id == "GT-001"

        # Oracle 只包含 GT-001
        oracle_case_ids = {o.case_id for o in artifacts.oracles}
        assert "GT-001" in oracle_case_ids
        assert "GT-002" not in oracle_case_ids

    def test_partial_case_analysis_deferred_when_all_incomplete(self, tmp_path: Path):
        """所有 case 都不完整 → analysis_deferred=True。"""
        runner = GroundTruthRunner(force_mock=True, results_dir=tmp_path)

        # 只有 2 个模型的结果 → 没有完整 case
        cases = [_case("GT-001")]
        results = [
            _result("GT-001", CANDIDATE_MODELS[0], status="success"),
            _result("GT-001", CANDIDATE_MODELS[1], status="success"),
        ]

        artifacts = runner.rebuild_analysis(cases, results, "dev")
        assert artifacts.analysis_deferred is True
        assert artifacts.oracles == []

    def test_require_judge_filters_missing_judge_score(self, tmp_path: Path):
        """require_judge=True 时，缺少 judge_score 的 case 不算完整。"""
        runner = GroundTruthRunner(force_mock=True, results_dir=tmp_path)
        cases = [_case("GT-001")]
        models = list(CANDIDATE_MODELS)

        # 5 个模型都 success，但没有 judge_score
        results = [_result("GT-001", m, status="success") for m in models]

        artifacts = runner.rebuild_analysis(cases, results, "dev", require_judge=True)
        assert artifacts.analysis_deferred is True
        assert artifacts.complete_cases == []

    def test_require_judge_passes_with_judge_score(self, tmp_path: Path):
        """require_judge=True + 5 模型都有 judge_score → 完整。"""
        runner = GroundTruthRunner(force_mock=True, results_dir=tmp_path)
        cases = [_case("GT-001")]
        models = list(CANDIDATE_MODELS)

        results = []
        for m in models:
            r = _result("GT-001", m, status="success")
            r = r.model_copy(update={"judge_score": 0.8, "judge_model": "MiniMax-M3"})
            results.append(r)

        artifacts = runner.rebuild_analysis(cases, results, "dev", require_judge=True)
        assert artifacts.analysis_deferred is False
        assert len(artifacts.complete_cases) == 1

    def test_rerun_failure_does_not_overwrite_success(self, tmp_path: Path):
        """run 0 成功 + rerun 失败 → case 仍然完整（不被 last-entry-wins 覆盖）。"""
        runner = GroundTruthRunner(force_mock=True, results_dir=tmp_path)
        cases = [_case("GT-001")]

        results = []
        # run_index=0: all 5 models success
        for m in CANDIDATE_MODELS:
            results.append(_result("GT-001", m, run_index=0, status="success", score=0.9))
        # run_index=1 (rerun): 2 models failed
        results.append(_result("GT-001", CANDIDATE_MODELS[0], run_index=1, status="failed", score=0.0))
        results.append(_result("GT-001", CANDIDATE_MODELS[1], run_index=1, status="failed", score=0.0))

        artifacts = runner.rebuild_analysis(cases, results, "dev")

        # 即使有 rerun 失败，case 仍然完整（因为每个模型至少有一次 success）
        assert len(artifacts.complete_cases) == 1
        assert artifacts.complete_cases[0].id == "GT-001"

    def test_non_candidate_models_not_complete(self, tmp_path: Path):
        """5 个非候选模型不能构成完整 case。"""
        runner = GroundTruthRunner(force_mock=True, results_dir=tmp_path)
        cases = [_case("GT-001")]

        # 5 个完全不同的模型，数量=5 但不是 CANDIDATE_MODELS
        wrong_models = ["model-a", "model-b", "model-c", "model-d", "model-e"]
        results = [_result("GT-001", m, status="success") for m in wrong_models]

        artifacts = runner.rebuild_analysis(cases, results, "dev")

        assert artifacts.analysis_deferred is True
        assert artifacts.complete_cases == []

    def test_require_judge_rerun_failure_keeps_success_judge(self, tmp_path: Path):
        """require_judge=True: rerun 失败不能覆盖已有成功 Judge 结果。"""
        runner = GroundTruthRunner(force_mock=True, results_dir=tmp_path)
        cases = [_case("GT-001")]

        results = []
        # run_index=0: all 5 models success + judge_score
        for m in CANDIDATE_MODELS:
            r = _result("GT-001", m, run_index=0, status="success", score=0.9)
            r = r.model_copy(update={"judge_score": 0.8, "judge_model": "MiniMax-M3"})
            results.append(r)

        # run_index=1 (rerun): same models, failed, no judge
        for m in CANDIDATE_MODELS:
            results.append(_result("GT-001", m, run_index=1, status="failed", score=0.0))

        artifacts = runner.rebuild_analysis(cases, results, "dev", require_judge=True)

        # 每个模型至少有一次 success + judge_score → 仍然完整
        assert len(artifacts.complete_cases) == 1
        assert artifacts.analysis_deferred is False


class TestRebuildAnalysisDevHoldout:
    """rebuild_analysis() Dev/Holdout 分离：Oracle.dataset 永远不等于 'all'。"""

    def _make_dev_holdout_data(self):
        """构造 2 个 dev case + 2 个 holdout case，全部完整。

        _infer_dataset_label 用 domain 推断：ENGINEERING=dev, GENERAL=holdout。
        """
        models = list(CANDIDATE_MODELS)

        # Dev cases: domain=ENGINEERING → dev
        dev_cases = [
            GroundTruthCase(
                id=f"DEV-{i}", domain="ENGINEERING", category="CODE_DEBUG",
                prompt=f"Dev task {i}", risk_level="LOW",
            )
            for i in range(1, 3)
        ]
        # Holdout cases: domain=GENERAL → holdout
        holdout_cases = [
            GroundTruthCase(
                id=f"HO-{i}", domain="GENERAL", category="CODE_DEBUG",
                prompt=f"Holdout task {i}", risk_level="LOW",
            )
            for i in range(1, 3)
        ]

        all_cases = dev_cases + holdout_cases
        results = []
        for case in all_cases:
            for m in models:
                results.append(_result(case.id, m, status="success", score=0.9))

        return all_cases, results

    def test_dataset_all_separates_dev_holdout(self, tmp_path: Path):
        """dataset='all' → Oracle 有 dev 和 holdout 两种，无 'all'。"""
        runner = GroundTruthRunner(force_mock=True, results_dir=tmp_path)
        cases, results = self._make_dev_holdout_data()

        artifacts = runner.rebuild_analysis(cases, results, "all")

        # 4 个完整 case
        assert len(artifacts.complete_cases) == 4
        assert artifacts.analysis_deferred is False

        # Oracle 应该有数据
        assert len(artifacts.oracles) > 0

        # 所有 Oracle 的 dataset 都不是 "all"
        for oracle in artifacts.oracles:
            assert oracle.dataset in ("dev", "holdout"), f"Oracle dataset={oracle.dataset}"

        # dev_signal_results 和 holdout_signal_results 分别有数据
        assert len(artifacts.dev_signal_results) > 0 or len(artifacts.dev_e2e_results) > 0
        assert len(artifacts.holdout_signal_results) > 0 or len(artifacts.holdout_e2e_results) > 0

    def test_dataset_dev_only(self, tmp_path: Path):
        """dataset='dev' → 所有 case 都被标为 dev，holdout 结果为空。"""
        runner = GroundTruthRunner(force_mock=True, results_dir=tmp_path)
        cases, results = self._make_dev_holdout_data()

        artifacts = runner.rebuild_analysis(cases, results, "dev")

        # dataset="dev" 时所有 case 都算 dev → holdout 结果为空
        assert artifacts.holdout_signal_results == []
        assert artifacts.holdout_e2e_results == []
        # dev 结果非空
        assert len(artifacts.complete_cases) == 4  # 所有 case 都完整

    def test_dataset_holdout_only(self, tmp_path: Path):
        """dataset='holdout' → 所有 case 都被标为 holdout，dev 结果为空。"""
        runner = GroundTruthRunner(force_mock=True, results_dir=tmp_path)
        cases, results = self._make_dev_holdout_data()

        artifacts = runner.rebuild_analysis(cases, results, "holdout")

        # dataset="holdout" 时所有 case 都算 holdout → dev 结果为空
        assert artifacts.dev_signal_results == []
        assert artifacts.dev_e2e_results == []
        assert len(artifacts.complete_cases) == 4


# ── Judge 并发 + AuthError 回归测试 ─────────────────────────────


class TestJudgeConcurrency:
    """Judge 并发执行 + AuthError 传播。"""

    def test_judge_concurrent_workers(self, tmp_path: Path):
        """workers=3 + mock executor → 所有 pair 都有 judge 结果。"""
        from unittest.mock import MagicMock

        from airouter.engine.benchmark.ground_truth_judge import (
            run_ground_truth_judge,
        )

        # Mock executor that returns valid JSON
        mock_executor = MagicMock()
        mock_exec_result = MagicMock()
        mock_exec_result.response_content = (
            '{"task_completion": 4, "accuracy": 4, "safety": 4, "reasoning": "good"}'
        )
        mock_executor.execute.return_value = mock_exec_result

        case = GroundTruthCase(id="GT-001", category="TEST", prompt="task")
        results = [
            GroundTruthCaseResult(
                case_id="GT-001", model=m, run_index=0, status="success",
            )
            for m in ["m1", "m2", "m3", "m4", "m5"]
        ]

        new_judges, mock_count, api_count = run_ground_truth_judge(
            cases=[case],
            results=results,
            judge_model="MiniMax-M3",
            run_dir=tmp_path,
            force_mock=False,
            executor=mock_executor,
            workers=3,
        )

        assert api_count == 5
        assert mock_count == 0
        assert len(new_judges) == 5
        assert all(j.status == "success" for j in new_judges)

    def test_judge_auth_error_propagates(self, tmp_path: Path):
        """Judge AdapterAuthError → 向上传播，不静默失败。"""
        from unittest.mock import MagicMock

        from airouter.adapters.base import AdapterAuthError
        from airouter.engine.benchmark.ground_truth_judge import (
            run_ground_truth_judge,
        )

        mock_executor = MagicMock()
        mock_executor.execute.side_effect = AdapterAuthError("Invalid key")

        case = GroundTruthCase(id="GT-001", category="TEST", prompt="task")
        results = [
            GroundTruthCaseResult(
                case_id="GT-001", model="m1", run_index=0, status="success",
            ),
        ]

        with pytest.raises(AdapterAuthError, match="auth error|Invalid key|API key"):
            run_ground_truth_judge(
                cases=[case],
                results=results,
                judge_model="MiniMax-M3",
                run_dir=tmp_path,
                force_mock=False,
                executor=mock_executor,
                workers=1,
            )


class TestJudgeRetryStability:
    """Judge max_tokens=8192 + 内容级重试 + attempts 追踪。"""

    def test_judge_max_tokens_8192(self, tmp_path: Path):
        """executor.execute 被调用时 max_tokens=8192。"""
        from unittest.mock import MagicMock

        from airouter.engine.benchmark.ground_truth_judge import (
            run_ground_truth_judge,
        )

        mock_executor = MagicMock()
        mock_exec_result = MagicMock()
        mock_exec_result.response_content = (
            '{"task_completion": 4, "accuracy": 4, "safety": 4, "reasoning": "ok"}'
        )
        mock_executor.execute.return_value = mock_exec_result

        case = GroundTruthCase(id="GT-001", category="TEST", prompt="task")
        results = [
            GroundTruthCaseResult(
                case_id="GT-001", model="m1", run_index=0, status="success",
            ),
        ]

        run_ground_truth_judge(
            cases=[case], results=results, judge_model="judge-model",
            run_dir=tmp_path, force_mock=False, executor=mock_executor,
            workers=1,
        )

        # 验证 max_tokens=8192
        call_args = mock_executor.execute.call_args
        assert call_args.kwargs.get("max_tokens") == 8192 or (
            call_args.args[2] == 8192 if len(call_args.args) > 2 else False
        ), f"Expected max_tokens=8192, got {call_args}"

    def test_judge_json_parse_retry_succeeds(self, tmp_path: Path):
        """第一次 parse 失败、第二次成功 → status=success, attempts=2。"""
        from unittest.mock import MagicMock

        from airouter.engine.benchmark.ground_truth_judge import _real_judge_evaluate

        mock_executor = MagicMock()
        call_count = [0]

        def side_effect(*args, **kwargs):
            call_count[0] += 1
            result = MagicMock()
            if call_count[0] == 1:
                # 第一次返回无效 JSON
                result.response_content = "This is not JSON at all"
            else:
                # 第二次返回有效 JSON
                result.response_content = (
                    '{"task_completion": 4, "accuracy": 3, "safety": 5, '
                    '"reasoning": "retry worked"}'
                )
            return result

        mock_executor.execute.side_effect = side_effect

        case = GroundTruthCase(id="GT-001", category="TEST", prompt="task")
        jr = _real_judge_evaluate(
            case, "m1", "judge-model", 0, "raw output", mock_executor,
            max_retries=3,
        )

        assert jr.status == "success"
        assert jr.attempts == 2
        assert call_count[0] == 2

    def test_judge_all_retries_fail(self, tmp_path: Path):
        """全部重试失败 → status=failed, attempts=4 (1+3)。"""
        from unittest.mock import MagicMock

        from airouter.engine.benchmark.ground_truth_judge import _real_judge_evaluate

        mock_executor = MagicMock()
        mock_exec_result = MagicMock()
        mock_exec_result.response_content = "always invalid"
        mock_executor.execute.return_value = mock_exec_result

        case = GroundTruthCase(id="GT-001", category="TEST", prompt="task")
        jr = _real_judge_evaluate(
            case, "m1", "judge-model", 0, "raw output", mock_executor,
            max_retries=3,
        )

        assert jr.status == "failed"
        assert jr.attempts == 4
        # 总共调用 4 次（1 + 3 retries）
        assert mock_executor.execute.call_count == 4

    def test_judge_auth_error_no_retry(self, tmp_path: Path):
        """AdapterAuthError 不重试，直接抛出。"""
        from unittest.mock import MagicMock

        from airouter.adapters.base import AdapterAuthError
        from airouter.engine.benchmark.ground_truth_judge import _real_judge_evaluate

        mock_executor = MagicMock()
        mock_executor.execute.side_effect = AdapterAuthError("Invalid key")

        case = GroundTruthCase(id="GT-001", category="TEST", prompt="task")
        with pytest.raises(AdapterAuthError):
            _real_judge_evaluate(
                case, "m1", "judge-model", 0, "raw output", mock_executor,
                max_retries=3,
            )

        # 只调用 1 次（不重试）
        assert mock_executor.execute.call_count == 1

    def test_gtjudge_result_attempts_field(self):
        """GTJudgeResult 有 attempts 字段，to_dict/from_dict 正确。"""
        from airouter.engine.benchmark.ground_truth_judge import GTJudgeResult

        jr = GTJudgeResult(
            case_id="GT-001", model="m1", attempts=3,
        )
        d = jr.to_dict()
        assert d["attempts"] == 3

        jr2 = GTJudgeResult.from_dict(d)
        assert jr2.attempts == 3


# ── Physical Call Counting 回归测试 ────────────────────────────


class TestPhysicalCallCounting:
    """ModelExecutor 线程安全物理调用计数器。"""

    def test_counter_increments_on_call(self):
        """每次 execute 调用计数器 +1。"""
        from unittest.mock import MagicMock

        from airouter.engine.benchmark.executor import ModelExecutor

        mock_factory = MagicMock()
        mock_registry = MagicMock()
        mock_registry.all_models = []

        executor = ModelExecutor(
            adapter_factory=mock_factory,
            registry=mock_registry,
            force_mock=True,
        )

        assert executor.get_physical_call_count() == 0
        executor._increment_physical_calls()
        assert executor.get_physical_call_count() == 1
        executor._increment_physical_calls()
        assert executor.get_physical_call_count() == 2

    def test_snapshot_returns_current_count(self):
        """snapshot_physical_calls 返回当前值。"""
        from unittest.mock import MagicMock

        from airouter.engine.benchmark.executor import ModelExecutor

        executor = ModelExecutor(
            adapter_factory=MagicMock(),
            registry=MagicMock(),
            force_mock=True,
        )
        executor._increment_physical_calls()
        executor._increment_physical_calls()

        snapshot = executor.snapshot_physical_calls()
        assert snapshot == 2

        # 再增加
        executor._increment_physical_calls()
        assert executor.snapshot_physical_calls() == 3

    def test_reset_returns_old_value(self):
        """reset_physical_call_count 返回旧值并归零。"""
        from unittest.mock import MagicMock

        from airouter.engine.benchmark.executor import ModelExecutor

        executor = ModelExecutor(
            adapter_factory=MagicMock(),
            registry=MagicMock(),
            force_mock=True,
        )
        executor._increment_physical_calls()
        executor._increment_physical_calls()

        old = executor.reset_physical_call_count()
        assert old == 2
        assert executor.get_physical_call_count() == 0

    def test_counter_thread_safety(self):
        """多线程并发递增不丢数。"""
        import threading
        from unittest.mock import MagicMock

        from airouter.engine.benchmark.executor import ModelExecutor

        executor = ModelExecutor(
            adapter_factory=MagicMock(),
            registry=MagicMock(),
            force_mock=True,
        )

        n_threads = 10
        n_increments = 100

        def worker():
            for _ in range(n_increments):
                executor._increment_physical_calls()

        threads = [threading.Thread(target=worker) for _ in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert executor.get_physical_call_count() == n_threads * n_increments

