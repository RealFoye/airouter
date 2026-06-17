"""Unit tests for ground_truth_judge.py."""

from __future__ import annotations

from pathlib import Path

import pytest

from airouter.engine.benchmark.ground_truth_judge import (
    GTJudgeResult,
    _verify_no_ground_truth_leak,
    build_judge_prompt,
    build_judged_results,
    compute_judged_final_score,
    load_judge_results,
    mock_judge_evaluate,
    run_ground_truth_judge,
    save_judge_results,
)
from airouter.engine.benchmark.ground_truth_schemas import (
    GroundTruthCase,
    GroundTruthCaseResult,
)

# ── Judge Prompt 安全性测试 ─────────────────────────────────


class TestJudgePromptSafety:
    """Judge prompt 不得泄漏评分标准或 ground truth。"""

    def test_judge_prompt_no_ground_truth(self):
        """Judge prompt 中不含 ground_truth 相关关键词。"""
        case = GroundTruthCase(
            id="GT-001",
            category="CODE_DEBUG",
            prompt="修复这个 bug",
            input_context="def foo(): return 1",
        )
        raw_output = '{"action": "propose_change", "patch": "..."}'
        messages = build_judge_prompt(case, raw_output)

        # 验证不含 ground truth 泄漏
        assert _verify_no_ground_truth_leak(messages) is True

        # 手动检查不含关键词
        full_text = " ".join(m["content"] for m in messages).lower()
        forbidden = [
            "expected_values", "expected_fact_ids", "ground_truth",
            "required_findings", "forbidden_findings", "oracle",
            "pass_threshold", "evaluation_spec",
        ]
        for kw in forbidden:
            assert kw not in full_text, f"Judge prompt contains {kw}"

    def test_judge_prompt_contains_task(self):
        """Judge prompt 应包含任务描述。"""
        case = GroundTruthCase(
            id="GT-001",
            category="CODE_DEBUG",
            prompt="修复这个 bug",
        )
        messages = build_judge_prompt(case, "output")
        full_text = " ".join(m["content"] for m in messages)
        assert "修复这个 bug" in full_text

    def test_judge_prompt_contains_output(self):
        """Judge prompt 应包含模型输出。"""
        case = GroundTruthCase(id="GT-001", category="TEST", prompt="task")
        raw_output = '{"action": "answer", "summary": "done"}'
        messages = build_judge_prompt(case, raw_output)
        full_text = " ".join(m["content"] for m in messages)
        assert raw_output in full_text


# ── Judge 分数归一化测试 ─────────────────────────────────────


class TestJudgeScoreNormalization:
    """Judge 输出 1-5 分，回写前必须归一化到 0-1。"""

    def test_judge_score_normalized(self):
        """raw_score=4.0 → normalized_score=0.8"""
        case = GroundTruthCase(id="GT-001", category="TEST", prompt="task")
        jr = mock_judge_evaluate(
            case, "qwen3.7-max", "MiniMax-M3", 0, fixed_score=4.0,
        )
        assert jr.raw_score == 4.0
        assert jr.normalized_score == pytest.approx(0.8)

    def test_judge_score_normalized_perfect(self):
        """raw_score=5.0 → normalized_score=1.0"""
        case = GroundTruthCase(id="GT-001", category="TEST", prompt="task")
        jr = mock_judge_evaluate(
            case, "qwen3.7-max", "MiniMax-M3", 0, fixed_score=5.0,
        )
        assert jr.normalized_score == pytest.approx(1.0)

    def test_judge_score_normalized_low(self):
        """raw_score=1.0 → normalized_score=0.2"""
        case = GroundTruthCase(id="GT-001", category="TEST", prompt="task")
        jr = mock_judge_evaluate(
            case, "qwen3.7-max", "MiniMax-M3", 0, fixed_score=1.0,
        )
        assert jr.normalized_score == pytest.approx(0.2)


# ── Judge 硬失败不可解除测试 ─────────────────────────────────


class TestJudgeHardFailure:
    """Judge 不得解除确定性硬失败。"""

    def test_judge_hard_failure_not_cleared(self):
        """硬失败 + judge 高分 → final=0"""
        result = GroundTruthCaseResult(
            case_id="GT-001",
            model="qwen3.7-max",
            status="success",
            rule_score=0.9,
            hard_failure_ids=["forbidden_output_detected"],
            pass_threshold=0.80,
        )
        # Judge 给高分
        judge_score = 0.95
        final = compute_judged_final_score(result, judge_score)
        assert final == 0.0, "Hard failure should result in final=0"

    def test_judge_no_hard_failure_normal(self):
        """无硬失败且确定性通过时正常计算。"""
        result = GroundTruthCaseResult(
            case_id="GT-001",
            model="qwen3.7-max",
            status="success",
            deterministic_passed=True,
            rule_score=0.9,
            hard_failure_ids=[],
            pass_threshold=0.80,
        )
        judge_score = 0.8
        final = compute_judged_final_score(result, judge_score)
        # 0.7 * 0.9 + 0.3 * 0.8 = 0.63 + 0.24 = 0.87
        assert final == pytest.approx(0.87)

    def test_judge_deterministic_failure_not_cleared(self):
        """确定性验证失败 + judge 高分 → final=0"""
        result = GroundTruthCaseResult(
            case_id="GT-001",
            model="qwen3.7-max",
            status="success",
            deterministic_passed=False,
            rule_score=0.9,
            hard_failure_ids=[],
            pass_threshold=0.80,
        )
        judge_score = 0.95
        final = compute_judged_final_score(result, judge_score)
        assert final == 0.0, "Deterministic failure should result in final=0"


# ── Judged Results 重建测试 ──────────────────────────────────


class TestJudgedResultsRebuild:
    """results.judged.jsonl 从全部 results + 全部成功 judge 重建。"""

    def test_judged_results_rebuilt_from_all(self):
        """包含历史 + 新增 judge。"""
        # 3 个 results
        results = [
            GroundTruthCaseResult(
                case_id="GT-001", model="m1", run_index=0,
                status="success", deterministic_passed=True,
                rule_score=0.8, pass_threshold=0.80,
            ),
            GroundTruthCaseResult(
                case_id="GT-001", model="m2", run_index=0,
                status="success", deterministic_passed=True,
                rule_score=0.7, pass_threshold=0.80,
            ),
            GroundTruthCaseResult(
                case_id="GT-001", model="m3", run_index=0,
                status="success", deterministic_passed=True,
                rule_score=0.9, pass_threshold=0.80,
            ),
        ]

        # 2 个 judge（m1, m2 有 judge，m3 没有）
        judges = [
            GTJudgeResult(
                case_id="GT-001", model="m1", run_index=0,
                judge_model="MiniMax-M3", status="success",
                raw_score=4.0, normalized_score=0.8,
            ),
            GTJudgeResult(
                case_id="GT-001", model="m2", run_index=0,
                judge_model="MiniMax-M3", status="success",
                raw_score=3.0, normalized_score=0.6,
            ),
        ]

        judged = build_judged_results(results, judges)

        # 应该有 3 个结果
        assert len(judged) == 3

        # m1 有 judge → final_score 更新
        m1_judged = next(r for r in judged if r.model == "m1")
        assert m1_judged.judge_score == pytest.approx(0.8)
        assert m1_judged.judge_model == "MiniMax-M3"
        # 0.7 * 0.8 + 0.3 * 0.8 = 0.80
        assert m1_judged.final_score == pytest.approx(0.80)

        # m2 有 judge → final_score 更新
        m2_judged = next(r for r in judged if r.model == "m2")
        assert m2_judged.judge_score == pytest.approx(0.6)
        # 0.7 * 0.7 + 0.3 * 0.6 = 0.49 + 0.18 = 0.67
        assert m2_judged.final_score == pytest.approx(0.67)

        # m3 无 judge → 保持原 final_score
        m3_judged = next(r for r in judged if r.model == "m3")
        assert m3_judged.judge_score is None
        assert m3_judged.final_score == 0.0  # 默认值

    def test_judged_results_failed_judge_excluded(self):
        """status=failed 的 judge 不参与重建。"""
        results = [
            GroundTruthCaseResult(
                case_id="GT-001", model="m1", run_index=0,
                status="success", rule_score=0.8,
            ),
        ]
        judges = [
            GTJudgeResult(
                case_id="GT-001", model="m1", run_index=0,
                judge_model="MiniMax-M3", status="failed",
                error_message="API error",
            ),
        ]

        judged = build_judged_results(results, judges)
        assert len(judged) == 1
        assert judged[0].judge_score is None


# ── Mock Judge 测试 ──────────────────────────────────────────


class TestMockJudge:
    """Mock Judge 返回固定分数。"""

    def test_mock_judge_evaluations(self, tmp_path: Path):
        """mock 模式 → mock_judge_evaluations=5, total_physical_api_calls=0"""
        # 1 case × 5 models = 5 pairs
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
            force_mock=True,
            executor=None,
            limit=None,
        )

        assert mock_count == 5
        assert api_count == 0
        assert len(new_judges) == 5
        # 每个 judge 都是 success
        assert all(j.status == "success" for j in new_judges)

    def test_mock_judge_fixed_score(self):
        """Mock judge 返回固定 3.0 分。"""
        case = GroundTruthCase(id="GT-001", category="TEST", prompt="task")
        jr = mock_judge_evaluate(case, "m1", "MiniMax-M3", 0)
        assert jr.raw_score == 3.0
        assert jr.normalized_score == pytest.approx(0.6)


# ── Judge Degraded 测试 ──────────────────────────────────────


class TestJudgeDegraded:
    """Judge 全部失败 → judge_degraded=True。"""

    def test_judge_degraded_flag(self, tmp_path: Path):
        """全部失败 → judge_degraded=True"""
        # 这个测试需要模拟 _real_judge_evaluate 失败
        # 由于我们无法轻易 mock executor，这里通过传入 force_mock=False + executor=None 触发失败
        case = GroundTruthCase(id="GT-001", category="TEST", prompt="task")
        results = [
            GroundTruthCaseResult(
                case_id="GT-001", model="m1", run_index=0, status="success",
            ),
        ]

        new_judges, mock_count, api_count = run_ground_truth_judge(
            cases=[case],
            results=results,
            judge_model="MiniMax-M3",
            run_dir=tmp_path,
            force_mock=False,
            executor=None,  # executor=None 会导致 _real_judge_evaluate 失败
            limit=None,
        )

        # executor=None → 全部失败
        assert len(new_judges) == 1
        assert new_judges[0].status == "failed"
        assert api_count == 1
        assert mock_count == 0


# ── Judge 文件 I/O 测试 ──────────────────────────────────────


class TestJudgeFileIO:
    """Judge 结果 JSONL 读写。"""

    def test_save_and_load_judge_results(self, tmp_path: Path):
        """保存后加载 judge 结果。"""
        path = tmp_path / "judge_results.jsonl"
        judges = [
            GTJudgeResult(
                case_id="GT-001", model="m1", run_index=0,
                judge_model="MiniMax-M3", status="success",
                raw_score=4.0, normalized_score=0.8,
            ),
            GTJudgeResult(
                case_id="GT-002", model="m2", run_index=0,
                judge_model="MiniMax-M3", status="failed",
                error_message="timeout",
            ),
        ]

        save_judge_results(path, judges)
        loaded = load_judge_results(path)

        assert len(loaded) == 2
        assert loaded[0].case_id == "GT-001"
        assert loaded[0].status == "success"
        assert loaded[1].status == "failed"

    def test_load_nonexistent(self, tmp_path: Path):
        """文件不存在返回空列表。"""
        path = tmp_path / "nonexistent.jsonl"
        loaded = load_judge_results(path)
        assert loaded == []


# ── Judge Resume 测试 ────────────────────────────────────────


class TestJudgeResume:
    """Judge 支持 resume，跳过已完成的 pair。"""

    def test_judge_resume_skips_existing(self, tmp_path: Path):
        """已有 judge 结果的 pair 不重复评估。"""
        # 先保存 1 个 judge 结果
        judge_path = tmp_path / "judge_results.jsonl"
        existing = GTJudgeResult(
            case_id="GT-001", model="m1", run_index=0,
            judge_model="MiniMax-M3", status="success",
            raw_score=4.0, normalized_score=0.8,
        )
        save_judge_results(judge_path, [existing])

        # 运行 judge，包含 m1（已有）和 m2（新）
        case = GroundTruthCase(id="GT-001", category="TEST", prompt="task")
        results = [
            GroundTruthCaseResult(
                case_id="GT-001", model="m1", run_index=0, status="success",
            ),
            GroundTruthCaseResult(
                case_id="GT-001", model="m2", run_index=0, status="success",
            ),
        ]

        new_judges, mock_count, api_count = run_ground_truth_judge(
            cases=[case],
            results=results,
            judge_model="MiniMax-M3",
            run_dir=tmp_path,
            force_mock=True,
            executor=None,
            limit=None,
        )

        # 只新增了 m2 的 judge
        assert len(new_judges) == 1
        assert new_judges[0].model == "m2"
        assert mock_count == 1


# ── Judge Limit 测试 ─────────────────────────────────────────


class TestJudgeLimit:
    """Judge 支持 limit 参数。"""

    def test_judge_limit_slices(self, tmp_path: Path):
        """limit=2 → 只评估 2 个 pair。"""
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
            force_mock=True,
            executor=None,
            limit=2,
        )

        assert len(new_judges) == 2
        assert mock_count == 2


# ── GTJudgeResult Dataclass 测试 ─────────────────────────────


class TestGTJudgeResult:
    """GTJudgeResult 数据类测试。"""

    def test_to_dict(self):
        """转换为 dict。"""
        jr = GTJudgeResult(
            case_id="GT-001",
            model="m1",
            run_index=0,
            judge_model="MiniMax-M3",
            status="success",
            raw_score=4.0,
            normalized_score=0.8,
            task_completion=4.0,
            accuracy=4.0,
            safety=4.0,
            reasoning="good",
        )
        d = jr.to_dict()
        assert d["case_id"] == "GT-001"
        assert d["raw_score"] == 4.0
        assert d["normalized_score"] == 0.8

    def test_from_dict(self):
        """从 dict 恢复。"""
        d = {
            "case_id": "GT-001",
            "model": "m1",
            "run_index": 0,
            "judge_model": "MiniMax-M3",
            "status": "success",
            "raw_score": 4.0,
            "normalized_score": 0.8,
        }
        jr = GTJudgeResult.from_dict(d)
        assert jr.case_id == "GT-001"
        assert jr.raw_score == 4.0

    def test_from_dict_extra_fields(self):
        """多余字段被忽略。"""
        d = {
            "case_id": "GT-001",
            "model": "m1",
            "extra_field": "ignored",
        }
        jr = GTJudgeResult.from_dict(d)
        assert jr.case_id == "GT-001"
        assert not hasattr(jr, "extra_field")
