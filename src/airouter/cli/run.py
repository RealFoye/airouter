"""ai-router run 命令：智能执行任务。"""

import json
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from airouter.adapters.factory import AdapterFactory
from airouter.config import AppSettings, load_all
from airouter.engine.agent.executor import AgentConfig, AgentExecutor
from airouter.engine.complexity.analyzer import ComplexityAnalyzer
from airouter.engine.router.analyzer import TaskAnalyzer
from airouter.engine.router.router import Router
from airouter.models.model_registry import ModelRegistry

app = typer.Typer()
console = Console()


@app.callback(invoke_without_command=True)
def run(
    task: str = typer.Argument(..., help="要执行的任务描述"),
    workdir: str = typer.Option(".", "--workdir", "-w", help="工作目录"),
    dry_run: bool = typer.Option(False, "--dry-run", help="只分析不执行"),
    max_cost: float = typer.Option(1.0, "--max-cost", help="成本上限(CNY)"),
    max_turns: int = typer.Option(10, "--max-turns", help="最大工具调用轮次"),
    yes: bool = typer.Option(False, "--yes", "-y", help="跳过人工确认"),
    output_format: str = typer.Option("rich", "--format", "-f", help="输出格式: rich/json"),
):
    """智能执行任务：分析 → 选模型 → 工具执行 → 验证。"""
    workdir_path = Path(workdir).resolve()

    if not workdir_path.exists():
        console.print(f"[red]工作目录不存在: {workdir}[/red]")
        raise typer.Exit(code=1)

    config = load_all()
    settings = AppSettings()
    registry = ModelRegistry(config.models)
    # Agent 真实执行不能静默降级到 Mock，否则用户会误以为任务已真实完成。
    factory = AdapterFactory(settings, allow_mock_fallback=False)

    # ai-router run 默认使用 OpenSquilla 模式（不修改全局 config）
    agent_complexity = config.complexity.model_copy(update={"mode": "opensquilla"})
    if agent_complexity.bundle_dir is None:
        # 从当前文件推导项目根目录
        project_root = Path(__file__).resolve().parents[3]
        default_bundle = (
            project_root
            / "opensquilla/src/opensquilla/squilla_router/models/v4.2_phase3_inference"
        )
        if default_bundle.exists():
            agent_complexity = agent_complexity.model_copy(
                update={"bundle_dir": default_bundle}
            )

    complexity_analyzer = ComplexityAnalyzer(
        agent_complexity,
        rule_analyzer=TaskAnalyzer(),
    )

    router = Router(
        config=config,
        complexity_analyzer=complexity_analyzer,
        model_registry=registry,
    )

    agent_config = AgentConfig(
        max_cost_cny=max_cost,
        max_turns=max_turns,
        skip_approval=yes,
        dry_run=dry_run,
    )

    executor = AgentExecutor(router, factory, registry, agent_config)

    with console.status("[bold cyan]AirRouter Agent 运行中...[/bold cyan]"):
        report = executor.run(task, workdir_path)

    if output_format == "json":
        _output_json(report)
    else:
        _output_rich(report)


def _output_rich(report):
    """Rich 格式化执行报告。"""
    goal = report.goal
    decision = report.decision

    # 任务描述面板
    console.print(Panel(
        goal.task,
        title="[bold yellow]任务[/bold yellow]",
        border_style="yellow",
    ))

    # 路由分析面板
    route_text = Text()
    route_text.append("任务类型: ", style="bold")
    route_text.append(f"{goal.category.value}\n")
    route_text.append("复杂度: ", style="bold")
    route_text.append(f"{goal.complexity.value}\n")
    route_text.append("风险等级: ", style="bold")
    route_text.append(f"{goal.risk_level.value}\n")
    route_text.append("执行策略: ", style="bold")
    route_text.append(f"{goal.strategy.value}\n")

    diag = decision.complexity_analysis
    if diag and diag.ml_final_class:
        route_text.append("ML 复杂度: ", style="bold")
        route_text.append(f"{diag.ml_final_class} (mode={diag.mode})\n")

    if decision.models.planner:
        route_text.append("规划模型: ", style="bold")
        route_text.append(f"{decision.models.planner}\n")
    if decision.models.executor:
        route_text.append("执行模型: ", style="bold")
        route_text.append(f"{decision.models.executor}\n")
    if decision.models.reviewer:
        route_text.append("审查模型: ", style="bold")
        route_text.append(f"{decision.models.reviewer}\n")

    console.print(Panel(route_text, title="[bold blue]路由分析[/bold blue]", border_style="blue"))

    # 执行计划（Plan-Execute）
    if report.plan:
        console.print(Panel(report.plan, title="[bold magenta]执行计划[/bold magenta]", border_style="magenta"))

    # 工具调用面板
    if report.tool_history:
        tool_text = Text()
        for i, record in enumerate(report.tool_history, 1):
            args_short = str(record.args)
            if len(args_short) > 60:
                args_short = args_short[:57] + "..."
            tool_text.append(f"{i}. ", style="bold")
            tool_text.append(f"[{record.name}] ", style="cyan")
            status_str = "OK" if record.success else "FAIL"
            status_style = "green" if record.success else "red"
            tool_text.append(f"[{status_str}] ", style=status_style)
            tool_text.append(f"{args_short}\n")
            if not record.success and record.error:
                tool_text.append(f"   {record.error}\n", style="red")
            elif record.result and record.success:
                result_preview = record.result[:150].replace("\n", " ")
                tool_text.append(f"   → {result_preview}\n", style="dim")
        console.print(Panel(
            tool_text,
            title=f"[bold]工具调用 ({len(report.tool_history)} 次)[/bold]",
        ))

    # 审查结果面板（三态）
    if report.review:
        if report.review_passed is True:
            review_style, review_title = "green", "审查通过"
        elif report.review_passed is False:
            review_style, review_title = "red", "需修复"
        else:
            review_style, review_title = "yellow", "审查结果需要人工判断"
        console.print(Panel(
            report.review,
            title=f"[bold {review_style}]{review_title}[/bold {review_style}]",
            border_style=review_style,
        ))

    # 成本面板
    cost_text = Text()
    cost_text.append("实际成本: ", style="bold")
    cost_text.append(f"¥{report.cost.total_cost_cny:.4f}\n")
    cost_text.append("基线成本: ", style="bold")
    cost_text.append(f"¥{report.baseline_cost:.4f}\n")
    cost_text.append("节省率: ", style="bold")
    savings_pct = report.savings_vs_baseline * 100
    if savings_pct > 50:
        cost_text.append(f"{savings_pct:.1f}%", style="green")
    elif savings_pct > 20:
        cost_text.append(f"{savings_pct:.1f}%", style="yellow")
    else:
        cost_text.append(f"{savings_pct:.1f}%", style="red")
    cost_text.append("\n")
    cost_text.append("输入 Token: ", style="bold")
    cost_text.append(f"{report.cost.total_input_tokens}\n")
    cost_text.append("输出 Token: ", style="bold")
    cost_text.append(f"{report.cost.total_output_tokens}\n")
    cost_text.append("执行轮次: ", style="bold")
    cost_text.append(f"{report.turns}\n")
    cost_text.append("耗时: ", style="bold")
    cost_text.append(f"{report.elapsed_seconds:.1f}s")

    if report.cost.model_costs:
        cost_text.append("\n\n模型分布:\n")
        for model, cost in sorted(report.cost.model_costs.items(), key=lambda x: -x[1]):
            tokens = report.cost.model_tokens.get(model, {})
            cost_text.append(f"  {model}: ", style="bold")
            cost_text.append(
                f"¥{cost:.4f} (in={tokens.get('input', 0)}, out={tokens.get('output', 0)})\n"
            )

    console.print(Panel(cost_text, title="[bold green]成本报告[/bold green]", border_style="green"))

    # 最终输出
    if report.final_response:
        console.print(Panel(
            report.final_response,
            title="[bold]最终输出[/bold]",
            border_style="white",
        ))

    # Verdict 横幅
    if report.dry_run:
        verdict = "[bold cyan]仅分析，未执行[/bold cyan]"
        console.print(Panel(verdict, border_style="cyan"))
    elif report.cancelled:
        verdict = "[bold yellow]用户取消执行[/bold yellow]"
        console.print(Panel(verdict, border_style="yellow"))
    elif report.success:
        verdict = "[bold green]✓ 执行成功[/bold green]"
        console.print(Panel(verdict, border_style="green"))
    else:
        verdict = "[bold red]✗ 执行失败[/bold red]"
        console.print(Panel(verdict, border_style="red"))


def _output_json(report):
    """JSON 格式输出。"""
    data = {
        "goal": {
            "task": report.goal.task,
            "category": report.goal.category.value,
            "complexity": report.goal.complexity.value,
            "risk_level": report.goal.risk_level.value,
            "strategy": report.goal.strategy.value,
            "success_criteria": report.goal.success_criteria,
        },
        "decision": report.decision.model_dump(mode="json"),
        "execution": {
            "final_response": report.final_response,
            "turns": report.turns,
            "elapsed_seconds": report.elapsed_seconds,
            "plan": report.plan,
            "review": report.review,
            "review_passed": report.review_passed,
            "dry_run": report.dry_run,
            "cancelled": report.cancelled,
        },
        "cost": {
            "total_cost_cny": report.cost.total_cost_cny,
            "total_input_tokens": report.cost.total_input_tokens,
            "total_output_tokens": report.cost.total_output_tokens,
            "model_costs": report.cost.model_costs,
            "baseline_cost": report.baseline_cost,
            "savings_vs_baseline": report.savings_vs_baseline,
        },
        "tool_history": [
            {
                "name": r.name,
                "args": r.args,
                "success": r.success,
                "result_preview": r.result[:200] if r.result else "",
            }
            for r in report.tool_history
        ],
        "success": report.success,
    }
    print(json.dumps(data, indent=2, ensure_ascii=False))
