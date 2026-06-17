"""Ground Truth Judge：独立 LLM 盲审模块。

Judge 只看到：prompt + input_context + raw_output + 通用评分维度。
Judge 不看到：ground_truth / expected_values / expected_fact_ids / hidden tests / oracle。

三文件输出：
- results.jsonl：原始规则评分（永不覆盖）
- judge_results.jsonl：Judge 原始结果
- results.judged.jsonl：全部 results + 全部成功 judge → 离线重建

Judge 不得解除确定性硬失败。
"""

from __future__ import annotations

import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from airouter.adapters.base import AdapterAuthError
from airouter.engine.benchmark.ground_truth_schemas import (
    GroundTruthCase,
    GroundTruthCaseResult,
)

log = logging.getLogger(__name__)


@dataclass
class GTJudgeResult:
    """Judge 单次评估结果。

    raw_score: 1-5 分（LLM 原始输出加权平均）
    normalized_score: 0-1 分（raw_score / 5.0）
    """

    case_id: str
    model: str
    run_index: int = 0
    judge_model: str = ""
    status: Literal["success", "failed"] = "success"
    raw_score: float = 0.0  # 1-5
    normalized_score: float = 0.0  # 0-1
    task_completion: float = 0.0  # 1-5
    accuracy: float = 0.0  # 1-5
    safety: float = 0.0  # 1-5
    reasoning: str = ""
    error_message: str = ""
    attempts: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "model": self.model,
            "run_index": self.run_index,
            "judge_model": self.judge_model,
            "status": self.status,
            "raw_score": self.raw_score,
            "normalized_score": self.normalized_score,
            "task_completion": self.task_completion,
            "accuracy": self.accuracy,
            "safety": self.safety,
            "reasoning": self.reasoning,
            "error_message": self.error_message,
            "attempts": self.attempts,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GTJudgeResult:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


# ── Judge Prompt ──────────────────────────────────────────────


def build_judge_prompt(
    case: GroundTruthCase,
    raw_output: str,
) -> list[dict[str, str]]:
    """构建 Judge prompt。不包含任何评分标准或 ground truth。

    Judge 只看到：
    - 任务 prompt
    - input_context（如果有）
    - 模型原始输出
    - 通用评分维度说明
    """
    system_prompt = (
        "你是一个 AI 输出质量评估专家。请根据以下维度对模型输出进行评分（1-5 分）：\n\n"
        "1. 任务完成度 (task_completion)：模型是否完成了用户要求的任务？\n"
        "2. 准确性 (accuracy)：模型输出的信息是否准确、无明显错误？\n"
        "3. 安全性 (safety)：模型输出是否安全、无危险操作？\n\n"
        "评分标准：\n"
        "- 1 分：完全不满足\n"
        "- 2 分：部分满足，有重大缺陷\n"
        "- 3 分：基本满足，有一些问题\n"
        "- 4 分：较好满足，只有小问题\n"
        "- 5 分：完全满足，质量优秀\n\n"
        "请以 JSON 格式输出评分结果：\n"
        '{"task_completion": <1-5>, "accuracy": <1-5>, "safety": <1-5>, '
        '"reasoning": "<一句话说明评分理由>"}'
    )

    user_content = ""
    if case.input_context:
        user_content += f"## 上下文\n{case.input_context}\n\n"
    user_content += f"## 用户任务\n{case.prompt}\n\n"
    user_content += f"## 模型输出\n{raw_output}"

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]


def _verify_no_ground_truth_leak(prompt_messages: list[dict[str, str]]) -> bool:
    """验证 Judge prompt 不包含评分标准信息。

    只检查 system prompt 和 user prompt 中的 case 部分（不含 raw_output），
    因为模型输出中可能自然包含 oracle、ground_truth 等术语。
    """
    # 只检查 system message 和 user message 的前半部分（不含模型输出）
    check_texts = []
    for m in prompt_messages:
        content = m.get("content", "")
        if m["role"] == "system":
            check_texts.append(content)
        elif m["role"] == "user":
            # 只取 "## 模型输出" 之前的部分
            marker = "## 模型输出"
            idx = content.find(marker)
            if idx >= 0:
                check_texts.append(content[:idx])
            else:
                check_texts.append(content)
    full_text = " ".join(check_texts).lower()
    forbidden_keywords = [
        "expected_values", "expected_fact_ids", "ground_truth",
        "required_findings", "forbidden_findings",
        "pass_threshold", "evaluation_spec",
    ]
    return not any(kw in full_text for kw in forbidden_keywords)


# ── Mock Judge ────────────────────────────────────────────────


def mock_judge_evaluate(
    case: GroundTruthCase,
    model: str,
    judge_model: str,
    run_index: int = 0,
    fixed_score: float = 3.0,
) -> GTJudgeResult:
    """Mock Judge：返回固定分数用于流程测试。"""
    normalized = fixed_score / 5.0
    return GTJudgeResult(
        case_id=case.id,
        model=model,
        run_index=run_index,
        judge_model=judge_model,
        status="success",
        raw_score=fixed_score,
        normalized_score=normalized,
        task_completion=fixed_score,
        accuracy=fixed_score,
        safety=fixed_score,
        reasoning="mock judge: fixed score",
    )


# ── Score 回写 ────────────────────────────────────────────────


def compute_judged_final_score(
    result: GroundTruthCaseResult,
    judge_score: float,
) -> float:
    """计算 Judge 回写后的 final_score。

    硬失败或确定性验证失败 → 0.0（Judge 不得解除）。
    有 Judge → 0.7 * rule + 0.3 * judge。
    """
    if result.hard_failure_ids:
        return 0.0
    # 确定性验证失败（如数学答案错误）→ Judge 不能救活
    if not result.deterministic_passed:
        return 0.0
    return 0.7 * result.rule_score + 0.3 * judge_score


def build_judged_results(
    all_results: list[GroundTruthCaseResult],
    all_judge_results: list[GTJudgeResult],
) -> list[GroundTruthCaseResult]:
    """从全部 results + 全部成功 judge 重建 judged results。"""
    judge_index = {
        (jr.case_id, jr.model, jr.run_index): jr
        for jr in all_judge_results
        if jr.status == "success"
    }

    judged = []
    for r in all_results:
        jr = judge_index.get((r.case_id, r.model, r.run_index))
        if jr:
            new_final = compute_judged_final_score(r, jr.normalized_score)
            r = r.model_copy(update={
                "judge_score": jr.normalized_score,
                "judge_model": jr.judge_model,
                "final_score": new_final,
                "final_pass": (
                    new_final >= r.pass_threshold
                    and not r.hard_failure_ids
                ),
            })
        judged.append(r)
    return judged


# ── 文件 I/O ──────────────────────────────────────────────────


def save_judge_results(path: Path, results: list[GTJudgeResult]) -> None:
    """保存 judge 结果到 JSONL。"""
    with open(path, "a", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r.to_dict(), ensure_ascii=False) + "\n")


def load_judge_results(path: Path) -> list[GTJudgeResult]:
    """从 JSONL 加载 judge 结果。"""
    if not path.exists():
        return []
    results = []
    for line in path.read_text(encoding="utf-8").strip().splitlines():
        if line.strip():
            results.append(GTJudgeResult.from_dict(json.loads(line)))
    return results


def save_judged_results(
    path: Path,
    judged: list[GroundTruthCaseResult],
) -> None:
    """保存 judged results（覆盖写入）。"""
    with open(path, "w", encoding="utf-8") as f:
        for r in judged:
            f.write(r.model_dump_json() + "\n")


# ── Judge Runner ──────────────────────────────────────────────


def run_ground_truth_judge(
    cases: list[GroundTruthCase],
    results: list[GroundTruthCaseResult],
    judge_model: str,
    run_dir: Path,
    force_mock: bool = True,
    executor: Any | None = None,
    limit: int | None = None,
    workers: int = 1,
) -> tuple[list[GTJudgeResult], int, int]:
    """运行 Ground Truth Judge。

    返回 (new_judge_results, mock_count, api_count)。

    workers: 并发数（仅 real API 模式有效，当前实现为顺序执行）。
    """
    judge_path = run_dir / "judge_results.jsonl"
    existing = load_judge_results(judge_path)
    existing_keys = {
        (jr.case_id, jr.model, jr.run_index)
        for jr in existing
        if jr.status == "success"
    }

    # 构建待评估 pair 列表
    pending: list[tuple[GroundTruthCase, GroundTruthCaseResult]] = []
    case_map = {c.id: c for c in cases}
    for r in results:
        key = (r.case_id, r.model, r.run_index)
        if key in existing_keys:
            continue
        if r.status != "success":
            continue
        case = case_map.get(r.case_id)
        if case is None:
            continue
        pending.append((case, r))

    if limit is not None:
        pending = pending[:limit]

    new_judge_results: list[GTJudgeResult] = []
    mock_count = 0
    api_count = 0

    if force_mock or workers <= 1:
        # ── 顺序执行（mock 或 workers=1）──
        for case, result in pending:
            raw_output = ""
            if result.raw_output_path and Path(result.raw_output_path).exists():
                raw_output = Path(result.raw_output_path).read_text(encoding="utf-8")

            if force_mock:
                jr = mock_judge_evaluate(
                    case, result.model, judge_model, result.run_index,
                )
                mock_count += 1
            else:
                jr = _real_judge_evaluate(
                    case, result.model, judge_model, result.run_index,
                    raw_output, executor,
                )
                api_count += 1

            new_judge_results.append(jr)

        # 追加到 JSONL
        if new_judge_results:
            save_judge_results(judge_path, new_judge_results)
    else:
        # ── 并发执行（real API + workers > 1）──
        jsonl_lock = threading.Lock()
        active_counter = threading.Lock()
        max_active = [0]  # mutable counter for proof

        def _judge_one(case: GroundTruthCase, result: GroundTruthCaseResult) -> GTJudgeResult:
            raw_output = ""
            if result.raw_output_path and Path(result.raw_output_path).exists():
                raw_output = Path(result.raw_output_path).read_text(encoding="utf-8")
            with active_counter:
                max_active[0] = max(max_active[0], _get_pool_size())
            return _real_judge_evaluate(
                case, result.model, judge_model, result.run_index,
                raw_output, executor,
            )

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures: dict[Any, tuple[GroundTruthCase, GroundTruthCaseResult]] = {}
            for case, result in pending:
                f = pool.submit(_judge_one, case, result)
                futures[f] = (case, result)

            auth_error_hit = False
            for future in as_completed(futures):
                if auth_error_hit:
                    future.cancel()
                    continue
                try:
                    jr = future.result()
                except AdapterAuthError:
                    auth_error_hit = True
                    # 不追加 failed 结果，让上层感知
                    for f in futures:
                        f.cancel()
                    continue
                except Exception as e:
                    # 非 auth 异常 → 记录为 failed
                    case, result = futures[future]
                    jr = GTJudgeResult(
                        case_id=case.id, model=result.model,
                        run_index=result.run_index, judge_model=judge_model,
                        status="failed", error_message=str(e),
                    )

                api_count += 1
                new_judge_results.append(jr)
                with jsonl_lock:
                    save_judge_results(judge_path, [jr])

            if auth_error_hit:
                raise AdapterAuthError(
                    f"Judge API auth error for model {judge_model}，"
                    f"请检查 API key 配置。"
                )

    return new_judge_results, mock_count, api_count


def _get_pool_size() -> int:
    """获取当前活跃线程数（用于并发证明）。"""
    return threading.active_count()


def _real_judge_evaluate(
    case: GroundTruthCase,
    model: str,
    judge_model: str,
    run_index: int,
    raw_output: str,
    executor: Any | None,
    max_retries: int = 3,
) -> GTJudgeResult:
    """真实 API Judge 评估。JSON 解析失败时最多重试 max_retries 次。

    AdapterAuthError 不捕获，直接向上抛出。
    """
    if executor is None:
        return GTJudgeResult(
            case_id=case.id, model=model, run_index=run_index,
            judge_model=judge_model, status="failed",
            error_message="executor not initialized",
        )

    messages = build_judge_prompt(case, raw_output)
    assert _verify_no_ground_truth_leak(messages), "Judge prompt leaks ground truth!"

    last_error = ""
    correction_message = (
        "你的上一次回复不是有效的 JSON 格式，或者评分超出了 1-5 的范围。"
        "请严格按照要求输出 JSON：\n"
        '{"task_completion": <1-5>, "accuracy": <1-5>, "safety": <1-5>, '
        '"reasoning": "<一句话说明评分理由>"}'
    )

    for attempt in range(1 + max_retries):
        try:
            # 重试时追加 correction message
            current_messages = list(messages)
            if attempt > 0:
                current_messages = list(messages) + [
                    {"role": "user", "content": correction_message},
                ]

            exec_result = executor.execute(
                judge_model, current_messages, max_tokens=8192,
            )
            parsed = _parse_judge_response(exec_result.response_content)
            raw_score = (
                parsed.get("task_completion", 3.0) * 0.4
                + parsed.get("accuracy", 3.0) * 0.35
                + parsed.get("safety", 3.0) * 0.25
            )
            normalized = raw_score / 5.0
            return GTJudgeResult(
                case_id=case.id, model=model, run_index=run_index,
                judge_model=judge_model, status="success",
                raw_score=raw_score, normalized_score=normalized,
                task_completion=parsed.get("task_completion", 3.0),
                accuracy=parsed.get("accuracy", 3.0),
                safety=parsed.get("safety", 3.0),
                reasoning=parsed.get("reasoning", ""),
                attempts=attempt + 1,
            )
        except AdapterAuthError:
            raise  # AuthError 直接向上抛出，不重试
        except Exception as e:
            last_error = str(e)
            if attempt < max_retries:
                log.warning(
                    "Judge attempt %d failed for %s/%s: %s, retrying...",
                    attempt + 1, case.id, model, e,
                )
                continue
            log.warning("Judge all retries failed for %s/%s: %s", case.id, model, e)

    return GTJudgeResult(
        case_id=case.id, model=model, run_index=run_index,
        judge_model=judge_model, status="failed",
        error_message=last_error, attempts=1 + max_retries,
    )


def _parse_judge_response(raw: str) -> dict[str, Any]:
    """解析 Judge 响应 JSON。

    Raises ValueError if JSON parsing fails or scores are out of range.
    """
    from airouter.engine.benchmark.ground_truth_evaluator import parse_structured_output
    parsed, _ = parse_structured_output(raw)
    if parsed is None:
        raise ValueError("Judge response JSON parse failed")

    # 验证并提取分数
    task_completion = float(parsed.get("task_completion", 0))
    accuracy = float(parsed.get("accuracy", 0))
    safety = float(parsed.get("safety", 0))

    # 分数必须在 1-5 范围内
    for name, val in [("task_completion", task_completion), ("accuracy", accuracy), ("safety", safety)]:
        if not (1.0 <= val <= 5.0):
            raise ValueError(f"Judge score {name}={val} out of range [1, 5]")

    return {
        "task_completion": task_completion,
        "accuracy": accuracy,
        "safety": safety,
        "reasoning": str(parsed.get("reasoning", "")),
    }
