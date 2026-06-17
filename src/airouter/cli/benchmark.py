"""ai-router benchmark 命令：Level 1 离线规则 + Level 2 模型质量 + Level 3 策略回测 + Finance 企业财务 + Routing Ground Truth。"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Literal, NoReturn, Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from airouter.engine.benchmark.runner import (
    Level1BenchmarkRunner,
    Level2BenchmarkRunner,
    Level3BenchmarkRunner,
)
from airouter.engine.benchmark.scorer import METRIC_TARGETS

app = typer.Typer()
console = Console()


def _exit_error(message: str, output_format: str) -> NoReturn:
    """Print error to stderr (JSON mode: structured JSON) and exit 1."""
    if output_format == "json":
        print(json.dumps({"error": message}, ensure_ascii=False), file=sys.stderr)
    else:
        console.print(f"[red]{message}[/red]")
    raise typer.Exit(code=1)


@app.callback(invoke_without_command=True)
def benchmark(
    level: str = typer.Option(..., "--level", "-l", help="Benchmark level: 1, 2, 3, finance, or routing"),
    cases: Optional[str] = typer.Option(None, "--cases", "-c", help="Cases YAML 路径 (L1/L2 only)"),
    fail_fast: bool = typer.Option(False, "--fail-fast", help="首次失败即停止"),
    resume: bool = typer.Option(False, "--resume", help="断点续跑"),
    output_format: Literal["rich", "json"] = typer.Option("rich", "--format", "-f"),
    # Level 2 options
    models: Optional[str] = typer.Option(None, "--models", help="L2/Finance: 逗号分隔的模型列表"),
    rate_limit: int = typer.Option(20, "--rate-limit", help="L2/Finance: 每分钟最大请求数"),
    real_api: bool = typer.Option(False, "--real-api", help="L2/Finance: 使用真实 API（默认 mock）"),
    run_id: Optional[str] = typer.Option(None, "--run-id", help="L2/Finance: 续跑指定 run"),
    output_dir: Optional[str] = typer.Option(None, "--output-dir", help="L2/Finance: 结果输出目录"),
    limit: Optional[int] = typer.Option(None, "--limit", help="L2/Finance: 最大执行 pair 数"),
    workers: int = typer.Option(5, "--workers", help="L2/Finance: 并发 worker 数 (5-10)"),
    # Level 2 judge options
    judge: bool = typer.Option(False, "--judge", help="L2/Finance: 运行 LLM judge（absolute + pairwise）"),
    judge_models: Optional[str] = typer.Option(None, "--judge-model", "--judge-models", help="L2/Finance: judge 模型列表（逗号分隔，Finance v1 默认 MiniMax-M3）"),
    judge_workers: int = typer.Option(20, "--judge-workers", help="L2/Finance: judge/pairwise 并发数 (20+)"),
    skip_pairwise: bool = typer.Option(False, "--skip-pairwise", help="L2/Finance: 跳过 pairwise judge"),
    # Finance judge-existing options
    judge_existing: bool = typer.Option(False, "--judge-existing", help="Finance: 对已有 run 运行 LLM judge（不重跑模型）"),
    case_ids: Optional[str] = typer.Option(None, "--case-ids", help="Finance judge: 只审计指定 case（逗号分隔，如 FIN-POL-005,FIN-EXP-004）"),
    # Finance rescore options
    rescore: bool = typer.Option(False, "--rescore", help="Finance: 对已有 run 离线重评分（不调用 API）"),
    # Level 3 options
    case_set: str = typer.Option("all", "--case-set", help="L3: case set (all|l1|l2)"),
    baseline_model: str = typer.Option("qwen3.7-max", "--baseline-model", help="L3: baseline model"),
    # Routing options
    rerun: bool = typer.Option(False, "--rerun", help="Routing: 全量重跑（与 --limit/--resume 互斥）"),
) -> None:
    """运行 Benchmark 验证路由决策正确性。"""
    level_norm = str(level).lower().strip()
    if level_norm == "1":
        _run_level1(cases, fail_fast, resume, output_format)
    elif level_norm == "2":
        _run_level2(
            cases, fail_fast, resume, output_format,
            models, rate_limit, real_api, run_id, output_dir, limit,
            workers, judge, judge_models, judge_workers, skip_pairwise,
        )
    elif level_norm == "3":
        if cases:
            _exit_error("Level 3 不支持 --cases 参数，请使用 --case-set all|l1|l2", output_format)
        if case_set not in {"all", "l1", "l2"}:
            _exit_error(
                f"无效的 --case-set: {case_set}，可选值: all, l1, l2",
                output_format,
            )
        _run_level3(case_set, baseline_model, output_format)
    elif level_norm == "finance":
        _run_finance(
            cases, fail_fast, resume, output_format,
            models, rate_limit, real_api, run_id, output_dir, limit,
            workers, judge, judge_models, judge_workers, skip_pairwise,
            judge_existing, rescore, case_ids,
        )
    elif level_norm == "routing":
        _run_routing(
            cases, resume, output_format, real_api, run_id,
            output_dir, workers, limit, rate_limit, rerun,
            judge, judge_models, judge_workers, rescore,
        )
    else:
        _exit_error(
            f"不支持的 level: {level}。当前支持 --level 1, 2, 3, finance, 或 routing",
            output_format,
        )


def _run_level1(
    cases: str | None,
    fail_fast: bool,
    resume: bool,
    output_format: str,
) -> None:
    """Run Level 1 benchmark."""
    # --resume 提示（JSON 模式写 stderr，不污染 stdout）
    if resume:
        msg = "Level 1 为无状态运行，无需断点续跑，正常执行"
        if output_format == "json":
            print(json.dumps({"warning": msg}, ensure_ascii=False), file=sys.stderr)
        else:
            console.print(f"[yellow]{msg}[/yellow]")

    cases_path = Path(cases) if cases else None

    try:
        runner = Level1BenchmarkRunner(cases_path=cases_path)
        summary = runner.run(fail_fast=fail_fast)
    except (FileNotFoundError, ValueError) as e:
        if output_format == "json":
            print(json.dumps({"error": str(e)}, ensure_ascii=False), file=sys.stderr)
        else:
            console.print(f"[red]错误：{e}[/red]")
        raise typer.Exit(code=1)

    if output_format == "json":
        _output_l1_json(summary)
    else:
        _output_l1_rich(summary)

    if not summary.all_passed:
        raise typer.Exit(code=1)


def _run_level2(
    cases: str | None,
    fail_fast: bool,
    resume: bool,
    output_format: str,
    models_str: str | None,
    rate_limit: int,
    real_api: bool,
    run_id: str | None,
    output_dir: str | None,
    limit: int | None,
    workers: int = 5,
    judge: bool = False,
    judge_models_str: str | None = None,
    judge_workers: int = 20,
    skip_pairwise: bool = False,
) -> None:
    """Run Level 2 benchmark."""
    cases_path = Path(cases) if cases else None
    models_list = [m.strip() for m in models_str.split(",")] if models_str else None
    results_dir = Path(output_dir) if output_dir else None
    force_mock = not real_api

    # Judge mode requires real API
    if judge and force_mock:
        force_mock = False

    judge_models_list = (
        [m.strip() for m in judge_models_str.split(",")] if judge_models_str else None
    )

    try:
        runner = Level2BenchmarkRunner(
            cases_path=cases_path,
            models=models_list,
            force_mock=force_mock,
            rate_limit_rpm=rate_limit,
            results_base_dir=results_dir,
            workers=workers,
        )

        if judge:
            result = runner.run_with_judges(
                judge_models=judge_models_list,
                pairwise=not skip_pairwise,
                judge_workers=judge_workers,
                resume=resume,
                run_id=run_id,
                limit=limit,
            )
            l2_summary = result["l2_summary"]
            judge_results = result["judge_results"]
            pairwise_results = result.get("pairwise_results")

            if output_format == "json":
                data = {
                    "l2_summary": l2_summary.model_dump(mode="json"),
                    "judge_results": judge_results.model_dump(mode="json") if judge_results else None,
                    "pairwise_results": pairwise_results.model_dump(mode="json") if pairwise_results else None,
                }
                print(json.dumps(data, indent=2, ensure_ascii=False))
            else:
                _output_l2_rich(l2_summary)
                _output_judge_rich(judge_results, pairwise_results)

            if l2_summary.completed_pairs == 0:
                raise typer.Exit(code=1)
        else:
            summary = runner.run(
                resume=resume,
                run_id=run_id,
                fail_fast=fail_fast,
                max_pairs=limit,
            )
            if output_format == "json":
                _output_l2_json(summary)
            else:
                _output_l2_rich(summary)
            if summary.completed_pairs == 0:
                raise typer.Exit(code=1)

    except (FileNotFoundError, ValueError) as e:
        if output_format == "json":
            print(json.dumps({"error": str(e)}, ensure_ascii=False), file=sys.stderr)
        else:
            console.print(f"[red]错误：{e}[/red]")
        raise typer.Exit(code=1)


# ── Level 1 output ─────────────────────────────────────────


def _output_l1_rich(summary) -> None:
    """Rich 格式输出。"""
    verdict_style = "bold green" if summary.all_passed else "bold red"
    verdict_text = "PASSED" if summary.all_passed else "FAILED"
    overview = Text()
    overview.append("Level: ", style="bold")
    overview.append(f"{summary.level}\n")
    overview.append("Cases: ", style="bold")
    overview.append(f"{summary.passed_cases}/{summary.total_cases} passed\n")
    overview.append("Pass Rate: ", style="bold")
    overview.append(f"{summary.pass_rate:.0%}\n")
    overview.append("Verdict: ", style="bold")
    overview.append(verdict_text, style=verdict_style)
    console.print(Panel(overview, title="[bold blue]Benchmark 总览[/bold blue]", border_style="blue"))

    metric_table = Table(title="指标详情")
    metric_table.add_column("指标", style="cyan")
    metric_table.add_column("实际值", justify="right")
    metric_table.add_column("目标值", justify="right")
    metric_table.add_column("结果", justify="center")

    for name in METRIC_TARGETS:
        actual = summary.metrics.get(name, 0.0)
        target = METRIC_TARGETS[name]
        passed = summary.metric_passed.get(name, False)
        result_str = "[green]PASS[/green]" if passed else "[red]FAIL[/red]"
        metric_table.add_row(name, f"{actual:.1%}", f"{target:.0%}", result_str)
    console.print(metric_table)

    failed_results = [r for r in summary.case_results if not r.passed]
    if failed_results:
        fail_table = Table(title="失败 Case")
        fail_table.add_column("Case ID", style="cyan")
        fail_table.add_column("失败原因")

        for r in failed_results:
            reasons = "\n".join(r.failures[:3])
            if len(r.failures) > 3:
                reasons += f"\n... 共 {len(r.failures)} 条"
            fail_table.add_row(r.case_id, reasons)
        console.print(fail_table)

    if summary.all_passed:
        console.print(Panel("[bold green]ALL PASSED[/bold green]", border_style="green"))
    else:
        console.print(Panel("[bold red]BENCHMARK FAILED[/bold red]", border_style="red"))


def _output_l1_json(summary) -> None:
    """JSON 格式输出。"""
    data = summary.model_dump(mode="json")
    print(json.dumps(data, indent=2, ensure_ascii=False))


# ── Level 2 output ─────────────────────────────────────────


def _output_l2_rich(summary) -> None:
    """Rich 格式输出 Level 2 summary."""
    # Overview
    run_status = "[green]Completed[/green]" if summary.run_completed else "[yellow]Partial[/yellow]"
    quality_status = "[green]PASSED[/green]" if summary.quality_passed else "[red]FAILED[/red]"

    overview = Text()
    overview.append("Run ID: ", style="bold")
    overview.append(f"{summary.run_id}\n")
    overview.append("Cases: ", style="bold")
    overview.append(f"{summary.total_cases}\n")
    overview.append("Models: ", style="bold")
    overview.append(f"{summary.total_models}\n")
    overview.append("API Calls: ", style="bold")
    overview.append(f"{summary.total_api_calls}\n")
    overview.append("Total Cost: ", style="bold")
    overview.append(f"¥{summary.total_cost_cny:.4f}\n")
    overview.append("Total Latency: ", style="bold")
    overview.append(f"{summary.total_latency_ms}ms\n")
    overview.append("Completed: ", style="bold")
    overview.append(f"{summary.completed_pairs} success, {summary.failed_pairs} failed\n")
    overview.append("Run Status: ", style="bold")
    overview.append(f"{run_status}\n")
    overview.append("Quality: ", style="bold")
    overview.append(quality_status)
    console.print(Panel(overview, title="[bold blue]Level 2 总览[/bold blue]", border_style="blue"))

    # Model scores table
    if summary.model_scores:
        model_table = Table(title="模型分数")
        model_table.add_column("Model", style="cyan")
        model_table.add_column("Avg Score", justify="right")
        for model, score in sorted(summary.model_scores.items(), key=lambda x: -x[1]):
            model_table.add_row(model, f"{score:.3f}")
        console.print(model_table)

    # Task type scores
    if summary.task_type_scores:
        task_table = Table(title="任务类型分数")
        task_table.add_column("Task Type", style="cyan")
        task_table.add_column("Avg Score", justify="right")
        for task, score in sorted(summary.task_type_scores.items()):
            task_table.add_row(task, f"{score:.3f}")
        console.print(task_table)

    # Task-model matrix
    if summary.task_model_matrix:
        matrix_table = Table(title="任务-模型矩阵")
        matrix_table.add_column("Task Type", style="cyan")
        all_models = sorted({m for d in summary.task_model_matrix.values() for m in d})
        for m in all_models:
            matrix_table.add_column(m, justify="right")
        for task, model_dict in sorted(summary.task_model_matrix.items()):
            row = [task]
            for m in all_models:
                score = model_dict.get(m)
                row.append(f"{score:.3f}" if score is not None else "—")
            matrix_table.add_row(*row)
        console.print(matrix_table)

    # Failed pairs
    failed = [r for r in summary.case_results if r.status == "failed"]
    if failed:
        fail_table = Table(title="失败 Pairs")
        fail_table.add_column("Pair", style="cyan")
        fail_table.add_column("Error Type")
        fail_table.add_column("Attempts", justify="right")
        for r in failed[:20]:  # max 20 rows
            fail_table.add_row(
                f"{r.case_id} × {r.model}",
                r.error_type or "unknown",
                str(r.attempts),
            )
        if len(failed) > 20:
            console.print(f"[dim]... 共 {len(failed)} 条失败[/dim]")
        console.print(fail_table)

    # Quality verdict
    if summary.quality_passed:
        console.print(Panel("[bold green]QUALITY PASSED[/bold green]", border_style="green"))
    else:
        threshold = summary.quality_threshold
        console.print(
            Panel(
                f"[bold red]QUALITY FAILED[/bold red] (threshold: {threshold})",
                border_style="red",
            )
        )


def _output_l2_json(summary) -> None:
    """JSON 格式输出 Level 2."""
    data = summary.model_dump(mode="json")
    print(json.dumps(data, indent=2, ensure_ascii=False))


def _output_judge_rich(judge_results, pairwise_results) -> None:
    """Rich output for judge results."""
    if judge_results:
        jm = getattr(judge_results, 'judge_model', 'unknown')
        overview = Text()
        overview.append("Judge: ", style="bold")
        overview.append(f"{jm}\n")
        overview.append("Evaluations: ", style="bold")
        overview.append(f"{judge_results.successful}/{judge_results.total_evaluations}\n")
        overview.append("Model Truncated: ", style="bold")
        overview.append(f"{getattr(judge_results, 'model_truncated_count', 0)}\n")
        overview.append("Context Truncated: ", style="bold")
        overview.append(f"{getattr(judge_results, 'judge_context_truncated_count', 0)}\n")
        overview.append("Starved: ", style="bold")
        overview.append(f"{getattr(judge_results, 'starved_count', 0)}\n")
        overview.append("Cost: ", style="bold")
        overview.append(f"¥{getattr(judge_results, 'estimated_cost_cny', 0):.4f}")
        console.print(Panel(overview, title="[bold blue]Absolute Judge[/bold blue]", border_style="blue"))

        by_model = getattr(judge_results, 'by_model', {})
        if by_model:
            jtable = Table(title="Judge 模型分数")
            jtable.add_column("Model", style="cyan")
            jtable.add_column("Avg Score", justify="right")
            for model, stats in sorted(
                by_model.items(),
                key=lambda x: x[1].get("avg", 0) if isinstance(x[1], dict) else x[1],
                reverse=True,
            ):
                avg = stats.get("avg", 0) if isinstance(stats, dict) else stats
                jtable.add_row(model, f"{avg:.3f}")
            console.print(jtable)

    if pairwise_results:
        overview = Text()
        overview.append("Pairs: ", style="bold")
        overview.append(f"{pairwise_results.total_pairs}\n")
        overview.append("Calls: ", style="bold")
        overview.append(f"{pairwise_results.total_calls} ({pairwise_results.successful} ok, {pairwise_results.failed} failed)\n")
        overview.append("Agreement: ", style="bold")
        overview.append(f"{pairwise_results.agreement_rate:.1%}\n")
        overview.append("Cost: ", style="bold")
        overview.append(f"¥{pairwise_results.estimated_cost_cny:.4f}")
        console.print(Panel(overview, title="[bold blue]Pairwise Judge[/bold blue]", border_style="blue"))

        if pairwise_results.overall_ranking:
            ptable = Table(title="Pairwise 排名")
            ptable.add_column("Rank", justify="right")
            ptable.add_column("Model", style="cyan")
            ptable.add_column("Wins", justify="right")
            ptable.add_column("Losses", justify="right")
            ptable.add_column("Ties", justify="right")
            ptable.add_column("Win Rate", justify="right")
            for i, entry in enumerate(pairwise_results.overall_ranking, 1):
                ptable.add_row(
                    str(i),
                    entry["model"],
                    str(entry["wins"]),
                    str(entry["losses"]),
                    str(entry["ties"]),
                    f"{entry['win_rate']:.1%}",
                )
            console.print(ptable)

    # Reminder
    console.print(Panel(
        "models.yaml 当前是 CCH 历史账单校准价；新一轮 benchmark / judge 调用仍需导出 CCH usage CSV 对账。",
        title="[yellow]Reminder[/yellow]",
        border_style="yellow",
    ))


# ── Level 3 ─────────────────────────────────────────────────


def _run_level3(
    case_set: str,
    baseline_model: str,
    output_format: str,
) -> None:
    """Run Level 3 backtest."""
    try:
        runner = Level3BenchmarkRunner(
            case_set=case_set,
            baseline_model=baseline_model,
        )
        summary = runner.run()
    except ValueError as e:
        _exit_error(str(e), output_format)

    if output_format == "json":
        _output_l3_json(summary)
    else:
        _output_l3_rich(summary)


def _output_l3_rich(summary) -> None:
    """Rich 格式输出 Level 3 summary."""
    # Overview panel
    overview = Text()
    overview.append("Baseline: ", style="bold")
    overview.append(f"{summary.baseline_model}\n")
    overview.append("Quality Mode: ", style="bold")
    overview.append(f"{summary.quality_mode}\n")
    overview.append("Cases: ", style="bold")
    overview.append(f"{summary.total_cases} (L1: {summary.l1_cases}, L2: {summary.l2_cases})\n")
    overview.append("Baseline Cost: ", style="bold")
    overview.append(f"¥{summary.baseline_total_cost:.4f}\n")
    overview.append("Router Cost: ", style="bold")
    overview.append(f"¥{summary.router_total_cost:.4f}\n")
    overview.append("Savings: ", style="bold")
    overview.append(f"¥{summary.savings_total_cny:.4f} ({summary.savings_rate:.1%})\n")
    overview.append("Overspend: ", style="bold")
    overview.append(f"{summary.overspend_count} cases\n")
    overview.append("Non-executable: ", style="bold")
    overview.append(f"{summary.non_executable_count} cases\n")
    overview.append("Approval Required: ", style="bold")
    overview.append(f"{summary.approval_required_count} cases\n")
    overview.append("Safe Downgrades: ", style="bold")
    overview.append(f"{summary.safe_downgrade_count}\n")
    overview.append("Risky Downgrades: ", style="bold")
    overview.append(f"{summary.risky_downgrade_count}")
    console.print(Panel(overview, title="[bold blue]Level 3 策略回测总览[/bold blue]", border_style="blue"))

    # Strategy distribution
    if summary.strategy_distribution:
        strat_table = Table(title="策略分布")
        strat_table.add_column("Strategy", style="cyan")
        strat_table.add_column("Count", justify="right")
        for strategy, count in sorted(summary.strategy_distribution.items(), key=lambda x: -x[1]):
            strat_table.add_row(strategy, str(count))
        console.print(strat_table)

    # Tier distribution
    if summary.tier_distribution:
        tier_table = Table(title="Tier 分布")
        tier_table.add_column("Source", style="cyan")
        all_tiers = sorted({t for d in summary.tier_distribution.values() for t in d})
        for t in all_tiers:
            tier_table.add_column(t, justify="right")
        for source, tier_dict in sorted(summary.tier_distribution.items()):
            row = [source]
            for t in all_tiers:
                row.append(str(tier_dict.get(t, 0)))
            tier_table.add_row(*row)
        console.print(tier_table)

    # By source
    if summary.by_source:
        source_table = Table(title="按来源拆分")
        source_table.add_column("Source", style="cyan")
        source_table.add_column("Cases", justify="right")
        source_table.add_column("Baseline", justify="right")
        source_table.add_column("Router", justify="right")
        source_table.add_column("Savings", justify="right")
        for source, data in sorted(summary.by_source.items()):
            source_table.add_row(
                source,
                str(data["cases"]),
                f"¥{data['baseline_cost']:.4f}",
                f"¥{data['router_cost']:.4f}",
                f"{data['savings_rate']:.1%}",
            )
        console.print(source_table)

    # By task type
    if summary.by_task_type:
        task_table = Table(title="按任务类型拆分")
        task_table.add_column("Task Type", style="cyan")
        task_table.add_column("Cases", justify="right")
        task_table.add_column("Baseline", justify="right")
        task_table.add_column("Router", justify="right")
        task_table.add_column("Savings", justify="right")
        for task, data in sorted(summary.by_task_type.items()):
            task_table.add_row(
                task,
                str(data["cases"]),
                f"¥{data['baseline_cost']:.4f}",
                f"¥{data['router_cost']:.4f}",
                f"{data['savings_rate']:.1%}",
            )
        console.print(task_table)

    # Safe downgrades
    if summary.safe_downgrades:
        safe_table = Table(title="安全降级建议")
        safe_table.add_column("Case ID", style="cyan")
        safe_table.add_column("Source")
        safe_table.add_column("Executor")
        safe_table.add_column("Tier", justify="right")
        safe_table.add_column("Reason")
        for d in summary.safe_downgrades[:20]:
            safe_table.add_row(
                d["case_id"], d["source"],
                d.get("executor", "—"), str(d.get("tier", "—")),
                d["reason"],
            )
        console.print(safe_table)
        if len(summary.safe_downgrades) > 20:
            console.print(f"[dim]... 共 {len(summary.safe_downgrades)} 条安全降级，仅展示前 20 条[/dim]")

    # Risky downgrades
    if summary.risky_downgrades:
        risky_table = Table(title="风险降级")
        risky_table.add_column("Case ID", style="cyan")
        risky_table.add_column("Source")
        risky_table.add_column("Executor")
        risky_table.add_column("Tier", justify="right")
        risky_table.add_column("Reason")
        for d in summary.risky_downgrades[:20]:
            risky_table.add_row(
                d["case_id"], d["source"],
                d.get("executor", "—"), str(d.get("tier", "—")),
                d["reason"],
            )
        console.print(risky_table)
        if len(summary.risky_downgrades) > 20:
            console.print(f"[dim]... 共 {len(summary.risky_downgrades)} 条风险降级，仅展示前 20 条[/dim]")

    # Overspend cases
    if summary.overspend_cases:
        over_table = Table(title="超支 Case（Router > Baseline）")
        over_table.add_column("Case ID", style="cyan")
        over_table.add_column("Source")
        over_table.add_column("Baseline", justify="right")
        over_table.add_column("Router", justify="right")
        over_table.add_column("Overspend", justify="right")
        for d in summary.overspend_cases[:20]:
            over_table.add_row(
                d["case_id"], d["source"],
                f"¥{d['baseline_cost']:.4f}",
                f"¥{d['router_cost']:.4f}",
                f"¥{abs(d['savings_cny']):.4f}",
            )
        console.print(over_table)
        if len(summary.overspend_cases) > 20:
            console.print(f"[dim]... 共 {len(summary.overspend_cases)} 条超支，仅展示前 20 条[/dim]")

    # Disclaimer
    console.print(Panel(summary.disclaimer, title="[yellow]Disclaimer[/yellow]", border_style="yellow"))


def _output_l3_json(summary) -> None:
    """JSON 格式输出 Level 3."""
    data = summary.model_dump(mode="json")
    print(json.dumps(data, indent=2, ensure_ascii=False))


# ── Finance ─────────────────────────────────────────────────


def _run_finance_judge_existing(
    cases: str | None,
    output_format: str,
    run_id: str,
    output_dir: str | None,
    judge_models_str: str | None,
    judge_workers: int,
    limit: int | None,
    case_ids: str | None = None,
) -> None:
    """Run finance judge on an existing run without re-running models."""
    from airouter.config import AppSettings
    from airouter.engine.benchmark.finance_judge import DEFAULT_FINANCE_JUDGE, run_finance_judge
    from airouter.engine.benchmark.finance_report import generate_finance_report
    from airouter.engine.benchmark.finance_runner import FinanceBenchmarkRunner

    # Validate judge models: v1 only supports MiniMax-M3
    if judge_models_str:
        jm_list = [m.strip() for m in judge_models_str.split(",")]
        if len(jm_list) > 1:
            _exit_error("v1 仅支持单个 Judge 模型（MiniMax-M3）", output_format)
        if jm_list[0] != DEFAULT_FINANCE_JUDGE:
            _exit_error(
                f"v1 仅支持 {DEFAULT_FINANCE_JUDGE}，不支持 {jm_list[0]}",
                output_format,
            )
        judge_models = jm_list
    else:
        judge_models = [DEFAULT_FINANCE_JUDGE]

    # Validate API key exists — don't rely on AdapterFactory fallback
    settings = AppSettings()
    if not getattr(settings, "minimax_api_key", ""):
        _exit_error(
            "AIROUTER_MINIMAX_API_KEY 未设置，请在 .env 中配置",
            output_format,
        )

    # Resolve paths
    cases_path = str(
        Path(cases) if cases
        else settings.data_dir / "benchmarks" / "finance" / "finance_cases.yaml"
    )
    results_dir = Path(output_dir) if output_dir else FinanceBenchmarkRunner.DEFAULT_RESULTS_DIR
    run_dir = results_dir / run_id

    if not run_dir.exists():
        _exit_error(f"Run 目录不存在：{run_dir}", output_format)

    raw_dir = run_dir / "raw_outputs"
    if not raw_dir.exists():
        _exit_error(f"raw_outputs 目录不存在：{raw_dir}", output_format)

    # Prefer rescored results
    results_jsonl = run_dir / "results.rescored.jsonl"
    if not results_jsonl.exists():
        results_jsonl = run_dir / "results.jsonl"
    if not results_jsonl.exists():
        _exit_error(f"找不到 results.jsonl 或 results.rescored.jsonl：{run_dir}", output_format)

    console.print(f"[bold]Finance Judge（{DEFAULT_FINANCE_JUDGE}）[/bold]")
    console.print(f"  Run ID: {run_id}")
    console.print(f"  规则分数来源: {results_jsonl.name}")
    console.print(f"  Raw outputs: {raw_dir}")
    case_ids_list = None
    if case_ids:
        case_ids_list = [c.strip() for c in case_ids.split(",")]
        console.print(f"  🎯 TARGETED MODE: 仅审计 {len(case_ids_list)} 个 case")
    if limit:
        console.print(f"  ⚠ SMOKE MODE: 仅评测 {limit} 个 pair")
    console.print("")

    try:
        judge_summary = run_finance_judge(
            cases_path=cases_path,
            raw_dir=str(raw_dir),
            results_jsonl_path=str(results_jsonl),
            judge_models=judge_models,
            workers=judge_workers,
            limit=limit,
            case_ids=case_ids_list,
        )
    except Exception as e:
        _exit_error(f"Finance judge 执行失败：{e}", output_format)

    # Output results
    if output_format == "json":
        print(json.dumps(judge_summary.model_dump(mode="json"), indent=2, ensure_ascii=False))
    else:
        _output_judge_rich(judge_summary, None)

    # Regenerate report — but only for full runs (not smoke or targeted)
    if limit is None and case_ids is None:
        try:
            # Build finance summary using rescore_run to preserve case_catalog and models
            temp_runner = FinanceBenchmarkRunner(
                cases_path=Path(cases_path),
                force_mock=True,
                results_base_dir=results_dir,
            )
            finance_summary = temp_runner.rescore_run(run_id)
            report_path = generate_finance_report(
                finance_summary,
                judge_results=judge_summary,
                output_dir=run_dir,
            )
            console.print(f"\n[dim]报告已更新：{report_path}[/dim]")
        except Exception as e:
            console.print(f"[yellow]报告生成失败（judge 结果已保存）：{e}[/yellow]")
    else:
        console.print(
            f"\n[yellow]⚠ Smoke 模式：不覆盖正式报告。"
            f"Judge 结果已保存至 {run_dir}/finance_judge_minimax_m3.smoke.jsonl[/yellow]"
        )

    # CCH reminder
    console.print(Panel(
        "MiniMax-M3 Judge 调用已完成，请导出 CCH usage CSV 进行成本对账。\n"
        "models.yaml 价格是估算值，实际成本以 CCH 后台账单为准。",
        title="[yellow]成本对账提醒[/yellow]",
        border_style="yellow",
    ))


def _run_finance_rescore(
    cases: str | None,
    output_format: str,
    run_id: str,
    output_dir: str | None,
) -> None:
    """离线重评分已有 Finance run 并重建报告（不调用 API）。

    自动检测已有 Judge JSONL 并加载到报告中。
    """
    from airouter.engine.benchmark.finance_judge import load_judge_summary_from_jsonl
    from airouter.engine.benchmark.finance_report import generate_finance_report
    from airouter.engine.benchmark.finance_runner import FinanceBenchmarkRunner

    cases_path = Path(cases) if cases else None
    results_dir = Path(output_dir) if output_dir else None

    try:
        # Create runner with force_mock=True to ensure no API calls
        runner = FinanceBenchmarkRunner(
            cases_path=cases_path,
            force_mock=True,
            results_base_dir=results_dir,
        )

        # Locate run directory
        run_dir = runner._results_base_dir / run_id
        if not run_dir.exists():
            _exit_error(f"Run 目录不存在：{run_dir}", output_format)

        # Verify raw_outputs exists
        raw_dir = run_dir / "raw_outputs"
        if not raw_dir.exists():
            _exit_error(f"raw_outputs 目录不存在：{raw_dir}", output_format)

        # Re-score the run
        summary = runner.rescore_run(run_id)

        # Auto-detect existing Judge JSONL
        judge_summary = None
        for jm in ["MiniMax-M3", "minimax-m3"]:
            js = load_judge_summary_from_jsonl(run_dir, jm)
            if js is not None:
                judge_summary = js
                break

        # Regenerate report with Judge appendix if available
        report_path = generate_finance_report(
            summary, judge_results=judge_summary, output_dir=run_dir
        )

        if output_format == "json":
            _output_finance_json(summary)
        else:
            _output_finance_rich(summary)
            console.print(f"\n[dim]报告已更新：{report_path}[/dim]")
            if judge_summary:
                console.print(
                    f"[dim]Judge 附录已加载：{judge_summary.judge_model} "
                    f"({judge_summary.successful}/{judge_summary.total_evaluations})[/dim]"
                )

    except (FileNotFoundError, ValueError) as e:
        if output_format == "json":
            print(json.dumps({"error": str(e)}, ensure_ascii=False), file=sys.stderr)
        else:
            console.print(f"[red]错误：{e}[/red]")
        raise typer.Exit(code=1)


def _run_finance(
    cases: str | None,
    fail_fast: bool,
    resume: bool,
    output_format: str,
    models_str: str | None,
    rate_limit: int,
    real_api: bool,
    run_id: str | None,
    output_dir: str | None,
    limit: int | None,
    workers: int = 5,
    judge: bool = False,
    judge_models_str: str | None = None,
    judge_workers: int = 20,
    skip_pairwise: bool = False,
    judge_existing: bool = False,
    rescore: bool = False,
    case_ids: str | None = None,
) -> None:
    """运行 Finance Benchmark。"""
    from airouter.engine.benchmark.finance_report import generate_finance_report
    from airouter.engine.benchmark.finance_runner import FinanceBenchmarkRunner

    # Mutual exclusion checks for --rescore
    if rescore:
        if not run_id:
            _exit_error("--rescore 必须指定 --run-id", output_format)
        if real_api:
            _exit_error("--rescore 不得与 --real-api 混用", output_format)
        if judge_existing:
            _exit_error("--rescore 不得与 --judge-existing 混用", output_format)
        if resume:
            _exit_error("--rescore 不得与 --resume 混用", output_format)
        _run_finance_rescore(cases, output_format, run_id, output_dir)
        return

    if judge_existing:
        if not run_id:
            _exit_error("--judge-existing 必须指定 --run-id", output_format)
        _run_finance_judge_existing(
            cases, output_format, run_id, output_dir,
            judge_models_str, judge_workers, limit, case_ids,
        )
        return

    cases_path = Path(cases) if cases else None
    models_list = [m.strip() for m in models_str.split(",")] if models_str else None
    results_dir = Path(output_dir) if output_dir else None
    force_mock = not real_api

    if judge and force_mock:
        force_mock = False

    judge_models_list = (
        [m.strip() for m in judge_models_str.split(",")] if judge_models_str else None
    )

    try:
        runner = FinanceBenchmarkRunner(
            cases_path=cases_path,
            models=models_list,
            force_mock=force_mock,
            rate_limit_rpm=rate_limit,
            results_base_dir=results_dir,
            workers=workers,
        )

        if judge:
            result = runner.run_with_judges(
                judge_models=judge_models_list,
                pairwise=not skip_pairwise,
                judge_workers=judge_workers,
                resume=resume,
                run_id=run_id,
                limit=limit,
            )
            finance_summary = result["finance_summary"]
            judge_results = result["judge_results"]
            pairwise_results = result.get("pairwise_results")
            run_dir = result.get("run_dir")

            if output_format == "json":
                data = {
                    "finance_summary": finance_summary.model_dump(mode="json"),
                    "judge_results": judge_results.model_dump(mode="json") if judge_results else None,
                    "pairwise_results": pairwise_results.model_dump(mode="json") if pairwise_results else None,
                }
                print(json.dumps(data, indent=2, ensure_ascii=False))
            else:
                _output_finance_rich(finance_summary)
                _output_judge_rich(judge_results, pairwise_results)

                # Generate report
                if run_dir:
                    report_path = generate_finance_report(
                        finance_summary,
                        judge_results=judge_results,
                        pairwise_results=pairwise_results,
                        output_dir=Path(run_dir),
                    )
                    console.print(f"\n[dim]报告已生成：{report_path}[/dim]")

            if finance_summary.completed_pairs == 0:
                raise typer.Exit(code=1)
        else:
            summary = runner.run(
                resume=resume,
                run_id=run_id,
                fail_fast=fail_fast,
                max_pairs=limit,
            )

            if output_format == "json":
                _output_finance_json(summary)
            else:
                _output_finance_rich(summary)

                # Generate report
                run_dir_path = runner._find_latest_run_dir()
                if run_dir_path:
                    report_path = generate_finance_report(
                        summary, output_dir=run_dir_path,
                    )
                    console.print(f"\n[dim]报告已生成：{report_path}[/dim]")

                # CCH reminder for real API
                if real_api:
                    console.print(Panel(
                        "真实 API 调用已完成，请导出 CCH usage CSV 进行成本对账。\n"
                        "models.yaml 价格是估算值，实际成本以 CCH 后台账单为准。",
                        title="[yellow]成本对账提醒[/yellow]",
                        border_style="yellow",
                    ))

            if summary.completed_pairs == 0:
                raise typer.Exit(code=1)

    except (FileNotFoundError, ValueError) as e:
        if output_format == "json":
            print(json.dumps({"error": str(e)}, ensure_ascii=False), file=sys.stderr)
        else:
            console.print(f"[red]错误：{e}[/red]")
        raise typer.Exit(code=1)


_CATEGORY_NAMES = {
    "TABLE_CALCULATION": "表格计算",
    "REIMBURSEMENT_AUDIT": "报销审核",
    "AP_THREE_WAY_MATCH": "三单匹配",
    "BANK_RECONCILIATION": "银行对账",
    "BUDGET_VARIANCE": "预算分析",
    "POLICY_QA": "制度问答",
}


# ── Routing Ground Truth ─────────────────────────────────────


def _run_routing(
    cases: str | None,
    resume: bool,
    output_format: str,
    real_api: bool,
    run_id: str | None,
    output_dir: str | None,
    workers: int = 5,
    limit: int | None = None,
    rate_limit: int = 20,
    rerun: bool = False,
    judge: bool = False,
    judge_models_str: str | None = None,
    judge_workers: int = 20,
    rescore: bool = False,
) -> None:
    """运行 Routing Ground Truth Benchmark。"""
    from airouter.engine.benchmark.ground_truth_report import save_report
    from airouter.engine.benchmark.ground_truth_runner import GroundTruthRunner

    # CLI 互斥校验
    if rerun and limit is not None:
        _exit_error("--rerun 与 --limit 不能同时使用", output_format)
    if rerun and resume:
        _exit_error("--rerun 与 --resume 不能同时使用", output_format)

    # Rescore 互斥校验
    if rescore:
        if real_api:
            _exit_error("--rescore 不得与 --real-api 混用", output_format)
        if not output_dir:
            _exit_error("--rescore 必须指定 --output-dir", output_format)
        if not cases:
            _exit_error("--rescore 必须指定 --cases", output_format)

        from airouter.engine.benchmark.ground_truth_runner import rescore_run

        run_dir = Path(output_dir)
        console.print("[bold]Routing 离线重评分[/bold]")
        console.print(f"  Run dir: {run_dir}")
        console.print(f"  Cases: {cases}")

        try:
            output_path = rescore_run(run_dir, Path(cases))
            console.print(f"  [green]✓[/green] 重评分完成: {output_path.name}")

            # 简要统计
            import json as _json
            old_results = [
                _json.loads(line) for line in (run_dir / "results.jsonl").read_text().strip().split("\n")
            ]
            new_results = [
                _json.loads(line) for line in output_path.read_text().strip().split("\n")
            ]
            old_pass = sum(1 for r in old_results if r.get("final_pass"))
            new_pass = sum(1 for r in new_results if r.get("final_pass"))
            console.print(f"  Passing pairs: {old_pass} → {new_pass}")
        except Exception as e:
            _exit_error(f"重评分失败: {e}", output_format)
        return

    # Judge 需要显式指定 --judge-model
    if judge and not judge_models_str:
        _exit_error("--judge 需要 --judge-model", output_format)

    judge_models_list = (
        [m.strip() for m in judge_models_str.split(",")] if judge_models_str else None
    )

    results_dir = Path(output_dir) if output_dir else None
    force_mock = not real_api

    try:
        runner = GroundTruthRunner(
            results_dir=results_dir,
            force_mock=force_mock,
            workers=workers,
            rate_limit_rpm=rate_limit,
            allow_mock_fallback=not real_api,  # --real-api 时禁止 MockAdapter 降级
        )

        dataset: Literal["dev", "holdout", "all"] = "all"
        if cases:
            if "engineering" in cases:
                dataset = "dev"
            elif "routing_ground_truth" in cases:
                dataset = "holdout"

        if rerun:
            summary = runner.run_with_reruns(
                dataset=dataset,
                run_id=run_id,
            )
        else:
            summary = runner.run(
                dataset=dataset,
                resume=resume,
                run_id=run_id,
                limit=limit,
            )

        # Judge 阶段（可选）
        if judge and judge_models_list:
            from airouter.engine.benchmark.ground_truth_judge import (
                build_judged_results,
                load_judge_results,
                run_ground_truth_judge,
                save_judged_results,
            )
            from airouter.engine.benchmark.ground_truth_runner import (
                _load_deduped_by_run,
            )

            judge_model = judge_models_list[0]  # 暂时只支持一个 judge model
            run_dir = runner._results_dir / summary.run_id
            # Prefer rescored results if available
            results_path = run_dir / "results.rescored.jsonl"
            if not results_path.exists():
                results_path = run_dir / "results.jsonl"
            all_results = _load_deduped_by_run(results_path)
            all_cases = runner._load_cases(dataset)

            # 创建 judge executor（real API 模式）
            judge_executor = None
            if not force_mock:
                judge_executor = runner._executor

            # Snapshot physical call counter before judge
            judge_calls_before = (
                judge_executor.snapshot_physical_calls()
                if judge_executor else 0
            )

            new_judge_results, mock_judge_count, api_judge_count = run_ground_truth_judge(
                cases=all_cases,
                results=all_results,
                judge_model=judge_model,
                run_dir=run_dir,
                force_mock=force_mock,
                executor=judge_executor,
                limit=limit,
                workers=judge_workers,
            )

            # Delta = actual physical API calls for judge (includes retries)
            judge_calls_after = (
                judge_executor.snapshot_physical_calls()
                if judge_executor else 0
            )
            physical_judge_calls = judge_calls_after - judge_calls_before

            # 重建 judged results
            all_judge_results = load_judge_results(run_dir / "judge_results.jsonl")
            judged = build_judged_results(all_results, all_judge_results)
            save_judged_results(run_dir / "results.judged.jsonl", judged)

            # 从 judged results 重新生成 Oracle 和策略回放
            # 1. 保存 judged aggregated
            judged_artifacts = runner.rebuild_analysis(
                all_cases, judged, dataset, require_judge=True,
            )

            judged_aggregated_path = run_dir / "aggregated.judged.jsonl"
            with open(judged_aggregated_path, "w", encoding="utf-8") as f:
                for agg in judged_artifacts.aggregated:
                    f.write(agg.model_dump_json() + "\n")

            # 2. 保存 judged Oracle
            judged_oracle_path = run_dir / "oracles.judged.jsonl"
            with open(judged_oracle_path, "w", encoding="utf-8") as f:
                for oracle in judged_artifacts.oracles:
                    f.write(oracle.model_dump_json() + "\n")

            # 3. 更新 summary 的 Oracle 和策略回放结果
            summary.oracle_results = judged_artifacts.oracles
            summary.signal_strategy_results = judged_artifacts.signal_results
            summary.end_to_end_strategy_results = judged_artifacts.e2e_results
            summary.dev_signal_results = judged_artifacts.dev_signal_results
            summary.dev_e2e_results = judged_artifacts.dev_e2e_results
            summary.holdout_signal_results = judged_artifacts.holdout_signal_results
            summary.holdout_e2e_results = judged_artifacts.holdout_e2e_results
            summary.complete_cases = len(judged_artifacts.complete_cases)
            summary.analysis_deferred = judged_artifacts.analysis_deferred

            # 更新 summary
            summary.mock_judge_evaluations = mock_judge_count
            summary.judge_initial_calls = api_judge_count
            summary.judge_retry_attempts = max(0, physical_judge_calls - api_judge_count)
            summary.judge_degraded = (
                len(all_judge_results) > 0
                and all(jr.status == "failed" for jr in all_judge_results)
            )
            summary.judge_models = [judge_model]

            # 更新 total_physical_api_calls（累加 judge 物理调用）
            summary.total_physical_api_calls += physical_judge_calls

            # 保存更新后的 summary
            summary_path = run_dir / "summary.json"
            summary_path.write_text(
                summary.model_dump_json(indent=2),
                encoding="utf-8",
            )

        if output_format == "json":
            print(json.dumps(summary.model_dump(mode="json"), indent=2, ensure_ascii=False))
        else:
            _output_routing_rich(summary)

            # Generate Markdown report
            run_dir = runner._results_dir / summary.run_id
            report_path = run_dir / "report.md"
            save_report(summary, str(report_path))
            console.print(f"\n[dim]报告已生成：{report_path}[/dim]")

    except (FileNotFoundError, ValueError) as e:
        if output_format == "json":
            print(json.dumps({"error": str(e)}, ensure_ascii=False), file=sys.stderr)
        else:
            console.print(f"[red]错误：{e}[/red]")
        raise typer.Exit(code=1)


def _output_routing_rich(summary) -> None:
    """Rich 格式输出 Routing Ground Truth 结果。"""
    overview = Text()
    overview.append("Run ID: ", style="bold")
    overview.append(f"{summary.run_id}\n")
    overview.append("用例数: ", style="bold")
    overview.append(f"{summary.total_cases}（Dev: {summary.dev_cases}, Holdout: {summary.holdout_cases}）\n")
    overview.append("模型: ", style="bold")
    overview.append(f"{', '.join(summary.models)}\n")
    overview.append("API 调用: ", style="bold")
    overview.append(f"{summary.total_physical_api_calls}\n")
    overview.append("估算成本: ", style="bold")
    overview.append(f"¥{summary.total_estimated_cost_cny:.4f}\n")
    overview.append("Oracle 数: ", style="bold")
    overview.append(f"{len(summary.oracle_results)}")
    console.print(Panel(overview, title="[bold blue]Routing Ground Truth 总览[/bold blue]", border_style="blue"))

    # Oracle action 分布
    action_dist: dict[str, int] = {}
    for o in summary.oracle_results:
        action_dist[o.oracle_action] = action_dist.get(o.oracle_action, 0) + 1

    if action_dist:
        action_table = Table(title="Oracle Action 分布")
        action_table.add_column("Action", style="cyan")
        action_table.add_column("Count", justify="right")
        action_table.add_column("Pct", justify="right")
        total = len(summary.oracle_results)
        for action, count in sorted(action_dist.items(), key=lambda x: -x[1]):
            action_table.add_row(action, str(count), f"{count / total:.1%}")
        console.print(action_table)

    # A 层策略对比
    if summary.signal_strategy_results:
        strat_table = Table(title="A 层策略对比")
        strat_table.add_column("策略", style="cyan")
        strat_table.add_column("Acceptable Match", justify="right")
        strat_table.add_column("Cost Regret", justify="right")
        strat_table.add_column("Under-routing", justify="right")
        strat_table.add_column("Over-routing", justify="right")
        strat_table.add_column("Severe Under", justify="right")
        for s in summary.signal_strategy_results:
            strat_table.add_row(
                s.strategy_name,
                f"{s.acceptable_match_rate:.1%}",
                f"{s.cost_regret:+.1%}",
                f"{s.under_routing_rate:.1%}",
                f"{s.over_routing_rate:.1%}",
                f"{s.severe_under_routing_rate:.1%}",
            )
        console.print(strat_table)

    # B 层策略
    if summary.end_to_end_strategy_results:
        e2e_table = Table(title="B 层策略（端到端）")
        e2e_table.add_column("策略", style="cyan")
        e2e_table.add_column("Acceptable Match", justify="right")
        e2e_table.add_column("Cost Regret", justify="right")
        e2e_table.add_column("Under-routing", justify="right")
        for s in summary.end_to_end_strategy_results:
            e2e_table.add_row(
                s.strategy_name,
                f"{s.acceptable_match_rate:.1%}",
                f"{s.cost_regret:+.1%}",
                f"{s.under_routing_rate:.1%}",
            )
        console.print(e2e_table)

    # CCH reminder
    if summary.total_physical_api_calls > 0:
        console.print(Panel(
            "models.yaml 价格是估算值，实际成本以 CCH 后台账单为准。\n"
            "完成真实 API 调用后请导出 CCH usage CSV 进行对账。",
            title="[yellow]成本对账提醒[/yellow]",
            border_style="yellow",
        ))


def _output_finance_rich(summary) -> None:
    """Rich 格式输出 Finance Benchmark 结果。"""
    run_status = "[green]已完成[/green]" if summary.run_completed else "[yellow]部分完成[/yellow]"
    quality_status = "[green]达标[/green]" if summary.quality_passed else "[red]未达标[/red]"

    overview = Text()
    overview.append("Run ID: ", style="bold")
    overview.append(f"{summary.run_id}\n")
    overview.append("Case 数: ", style="bold")
    overview.append(f"{summary.total_cases}\n")
    overview.append("模型数: ", style="bold")
    overview.append(f"{summary.total_models}\n")
    overview.append("总调用数: ", style="bold")
    overview.append(f"{summary.total_api_calls}\n")
    overview.append("总成本: ", style="bold")
    overview.append(f"¥{summary.total_cost_cny:.4f}\n")
    overview.append("总耗时: ", style="bold")
    overview.append(f"{summary.total_latency_ms / 1000:.1f} 秒\n")
    overview.append("完成 pair 数: ", style="bold")
    overview.append(f"{summary.completed_pairs} 成功, {summary.failed_pairs} 失败\n")
    overview.append("运行状态: ", style="bold")
    overview.append(f"{run_status}\n")
    overview.append("质量达标: ", style="bold")
    overview.append(quality_status)
    console.print(Panel(overview, title="[bold blue]Finance Benchmark 总览[/bold blue]", border_style="blue"))

    # Model ranking table
    if summary.model_scores:
        model_table = Table(title="模型排名")
        model_table.add_column("排名", justify="right", style="bold")
        model_table.add_column("模型", style="cyan")
        model_table.add_column("综合分", justify="right")
        model_table.add_column("JSON 可解析率", justify="right")
        model_table.add_column("金额准确率", justify="right")
        model_table.add_column("违规项召回率", justify="right")
        model_table.add_column("决策准确率", justify="right")
        model_table.add_column("证据得分", justify="right")

        ranked = sorted(summary.model_scores.items(), key=lambda x: x[1], reverse=True)
        for rank, (model, score) in enumerate(ranked, 1):
            model_table.add_row(
                str(rank), model, f"{score:.3f}",
                f"{summary.avg_json_validity:.2f}",
                f"{summary.avg_amount_accuracy:.2f}",
                f"{summary.avg_finding_recall:.2f}",
                f"{summary.avg_decision_accuracy:.2f}",
                f"{summary.avg_evidence_quality:.2f}",
            )
        console.print(model_table)

    # Category scores
    if summary.category_scores:
        cat_table = Table(title="分类别得分")
        cat_table.add_column("类别", style="cyan")
        cat_table.add_column("平均分", justify="right")
        for cat, score in sorted(summary.category_scores.items()):
            cat_name = _CATEGORY_NAMES.get(cat, cat)
            cat_table.add_row(f"{cat_name} ({cat})", f"{score:.3f}")
        console.print(cat_table)

    # Category-model matrix
    if summary.category_model_matrix:
        matrix_table = Table(title="类别-模型矩阵")
        matrix_table.add_column("类别", style="cyan")
        all_models = sorted(
            {m for d in summary.category_model_matrix.values() for m in d}
        )
        for m in all_models:
            matrix_table.add_column(m, justify="right")
        for cat, model_dict in sorted(summary.category_model_matrix.items()):
            cat_name = _CATEGORY_NAMES.get(cat, cat)
            row = [cat_name]
            for m in all_models:
                score = model_dict.get(m)
                row.append(f"{score:.3f}" if score is not None else "—")
            matrix_table.add_row(*row)
        console.print(matrix_table)

    # Failed pairs
    failed = [r for r in summary.case_results if r.status == "failed"]
    if failed:
        fail_table = Table(title="失败 Pairs")
        fail_table.add_column("Pair", style="cyan")
        fail_table.add_column("Error Type")
        fail_table.add_column("Attempts", justify="right")
        for r in failed[:20]:
            fail_table.add_row(
                f"{r.case_id} × {r.model}",
                r.error_type or "unknown",
                str(r.attempts),
            )
        if len(failed) > 20:
            console.print(f"[dim]... 共 {len(failed)} 条失败[/dim]")
        console.print(fail_table)

    # Quality verdict
    if summary.quality_passed:
        console.print(Panel("[bold green]质量达标[/bold green]", border_style="green"))
    else:
        console.print(
            Panel(
                f"[bold red]质量未达标[/bold red]（阈值: {summary.quality_threshold}）",
                border_style="red",
            )
        )


def _output_finance_json(summary) -> None:
    """JSON 格式输出 Finance Benchmark."""
    data = summary.model_dump(mode="json")
    print(json.dumps(data, indent=2, ensure_ascii=False))

