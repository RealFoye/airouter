"""ai-router benchmark 命令：Level 1 离线规则 + Level 2 模型质量 Benchmark。"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Literal, Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from airouter.engine.benchmark.runner import Level1BenchmarkRunner, Level2BenchmarkRunner
from airouter.engine.benchmark.scorer import METRIC_TARGETS

app = typer.Typer()
console = Console()


@app.callback(invoke_without_command=True)
def benchmark(
    level: int = typer.Option(..., "--level", "-l", help="Benchmark level: 1 or 2"),
    cases: Optional[str] = typer.Option(None, "--cases", "-c", help="Cases YAML 路径"),
    fail_fast: bool = typer.Option(False, "--fail-fast", help="首次失败即停止"),
    resume: bool = typer.Option(False, "--resume", help="断点续跑"),
    output_format: Literal["rich", "json"] = typer.Option("rich", "--format", "-f"),
    # Level 2 options
    models: Optional[str] = typer.Option(None, "--models", help="L2: 逗号分隔的模型列表"),
    rate_limit: int = typer.Option(20, "--rate-limit", help="L2: 每分钟最大请求数"),
    real_api: bool = typer.Option(False, "--real-api", help="L2: 使用真实 API（默认 mock）"),
    run_id: Optional[str] = typer.Option(None, "--run-id", help="L2: 续跑指定 run"),
    output_dir: Optional[str] = typer.Option(None, "--output-dir", help="L2: 结果输出目录"),
    limit: Optional[int] = typer.Option(None, "--limit", help="L2: 最大执行 pair 数"),
) -> None:
    """运行 Benchmark 验证路由决策正确性。"""
    if level == 1:
        _run_level1(cases, fail_fast, resume, output_format)
    elif level == 2:
        _run_level2(
            cases, fail_fast, resume, output_format,
            models, rate_limit, real_api, run_id, output_dir, limit,
        )
    elif level == 3:
        console.print(f"[yellow]Level {level} 尚未实现，计划 Week 3[/yellow]")
        raise typer.Exit(code=1)
    else:
        console.print(f"[red]不支持的 level: {level}。当前支持 --level 1 或 --level 2[/red]")
        raise typer.Exit(code=1)


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
) -> None:
    """Run Level 2 benchmark."""
    cases_path = Path(cases) if cases else None
    models_list = [m.strip() for m in models_str.split(",")] if models_str else None
    results_dir = Path(output_dir) if output_dir else None
    force_mock = not real_api

    try:
        runner = Level2BenchmarkRunner(
            cases_path=cases_path,
            models=models_list,
            force_mock=force_mock,
            rate_limit_rpm=rate_limit,
            results_base_dir=results_dir,
        )
        summary = runner.run(
            resume=resume,
            run_id=run_id,
            fail_fast=fail_fast,
            max_pairs=limit,
        )
    except (FileNotFoundError, ValueError) as e:
        if output_format == "json":
            print(json.dumps({"error": str(e)}, ensure_ascii=False), file=sys.stderr)
        else:
            console.print(f"[red]错误：{e}[/red]")
        raise typer.Exit(code=1)

    if output_format == "json":
        _output_l2_json(summary)
    else:
        _output_l2_rich(summary)

    # Exit 1 only if 0 successful calls
    if summary.completed_pairs == 0:
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
