"""ai-router benchmark 命令：Level 1 离线规则 Benchmark。"""

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

from airouter.engine.benchmark.runner import Level1BenchmarkRunner
from airouter.engine.benchmark.scorer import METRIC_TARGETS

app = typer.Typer()
console = Console()


@app.callback(invoke_without_command=True)
def benchmark(
    level: int = typer.Option(..., "--level", "-l", help="Benchmark level: 1"),
    cases: Optional[str] = typer.Option(None, "--cases", "-c", help="Cases YAML 路径"),
    fail_fast: bool = typer.Option(False, "--fail-fast", help="首次失败即停止"),
    resume: bool = typer.Option(False, "--resume", help="断点续跑（Level 1 无状态，提示后正常运行）"),
    output_format: Literal["rich", "json"] = typer.Option("rich", "--format", "-f"),
) -> None:
    """运行 Benchmark 验证路由决策正确性。"""
    # Level 2/3 尚未实现
    if level in (2, 3):
        console.print(f"[yellow]Level {level} 尚未实现，计划 Week 3[/yellow]")
        raise typer.Exit(code=1)

    if level != 1:
        console.print(f"[red]不支持的 level: {level}。当前仅支持 --level 1[/red]")
        raise typer.Exit(code=1)

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
    except FileNotFoundError as e:
        if output_format == "json":
            print(json.dumps({"error": str(e)}, ensure_ascii=False), file=sys.stderr)
        else:
            console.print(f"[red]错误：{e}[/red]")
        raise typer.Exit(code=1)
    except ValueError as e:
        if output_format == "json":
            print(json.dumps({"error": str(e)}, ensure_ascii=False), file=sys.stderr)
        else:
            console.print(f"[red]错误：{e}[/red]")
        raise typer.Exit(code=1)

    if output_format == "json":
        _output_json(summary)
    else:
        _output_rich(summary)

    if not summary.all_passed:
        raise typer.Exit(code=1)


def _output_rich(summary) -> None:
    """Rich 格式输出。"""
    # 总览
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

    # 指标表
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
        metric_table.add_row(
            name,
            f"{actual:.1%}",
            f"{target:.0%}",
            result_str,
        )
    console.print(metric_table)

    # 失败 case 列表
    failed_results = [r for r in summary.case_results if not r.passed]
    if failed_results:
        fail_table = Table(title="失败 Case")
        fail_table.add_column("Case ID", style="cyan")
        fail_table.add_column("失败原因")

        for r in failed_results:
            reasons = "\n".join(r.failures[:3])  # 最多显示 3 条
            if len(r.failures) > 3:
                reasons += f"\n... 共 {len(r.failures)} 条"
            fail_table.add_row(r.case_id, reasons)
        console.print(fail_table)

    # 最终 verdict
    if summary.all_passed:
        console.print(Panel("[bold green]ALL PASSED[/bold green]", border_style="green"))
    else:
        console.print(Panel("[bold red]BENCHMARK FAILED[/bold red]", border_style="red"))


def _output_json(summary) -> None:
    """JSON 格式输出。"""
    data = summary.model_dump(mode="json")
    print(json.dumps(data, indent=2, ensure_ascii=False))
