"""ai-router analyze 命令。"""

import json

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from airouter.engine.router.router import Router

app = typer.Typer()
console = Console()


@app.callback(invoke_without_command=True)
def analyze(
    task: str = typer.Argument(..., help="任务描述"),
    output_format: str = typer.Option("rich", "--format", "-f", help="输出格式: rich/json"),
):
    """分析任务并推荐最优模型。"""
    router = Router()
    decision = router.route(task)

    if output_format == "json":
        _output_json(decision)
    else:
        _output_rich(decision)


def _output_rich(decision):
    """Rich 格式化输出。"""
    features = decision.task_features

    # 任务特征
    feature_text = Text()
    feature_text.append("类别: ", style="bold")
    feature_text.append(f"{features.category.value}\n")
    feature_text.append("复杂度: ", style="bold")
    feature_text.append(f"{features.complexity.value}\n")
    feature_text.append("风险等级: ", style="bold")
    feature_text.append(f"{features.risk_level.value}\n")
    feature_text.append("敏感性: ", style="bold")
    feature_text.append(f"{features.sensitivity.value}\n")
    feature_text.append("上下文需求: ", style="bold")
    feature_text.append(f"{features.context_requirement.value}\n")
    feature_text.append("推理强度: ", style="bold")
    feature_text.append(f"{features.reasoning_intensity.value}")

    console.print(Panel(feature_text, title="[bold blue]任务特征[/bold blue]", border_style="blue"))

    # 推荐方案
    if decision.models.executor or decision.models.planner:
        rec_text = Text()
        rec_text.append("策略: ", style="bold")
        rec_text.append(f"{decision.recommended_strategy.value}\n")
        if decision.models.planner:
            rec_text.append("规划模型: ", style="bold")
            rec_text.append(f"{decision.models.planner}\n")
        if decision.models.executor:
            rec_text.append("执行模型: ", style="bold")
            rec_text.append(f"{decision.models.executor}\n")
        if decision.models.reviewer:
            rec_text.append("审查模型: ", style="bold")
            rec_text.append(f"{decision.models.reviewer}\n")
        rec_text.append("预估成本: ", style="bold")
        rec_text.append(f"¥{decision.estimated_cost:.4f}\n")
        rec_text.append("基线成本: ", style="bold")
        rec_text.append(f"¥{decision.baseline_cost:.4f}\n")
        rec_text.append("节省比例: ", style="bold")
        rec_text.append(f"{decision.estimated_savings*100:.1f}%\n")
        rec_text.append("预估质量: ", style="bold")
        rec_text.append(f"{decision.estimated_quality:.2f}\n")
        rec_text.append("预算状态: ", style="bold")
        rec_text.append(f"{decision.budget_status.value}\n")

        if decision.requires_human_review:
            rec_text.append("\n⚠ 需要人工审核: ", style="bold red")
            rec_text.append(f"{decision.human_review_reason}", style="red")

        console.print(Panel(rec_text, title="[bold green]推荐方案[/bold green]", border_style="green"))
    else:
        console.print(Panel(
            f"[red]{decision.human_review_reason}[/red]",
            title="[bold red]需要人工介入[/bold red]",
            border_style="red"
        ))

    # 推荐理由
    if decision.reasons:
        reasons_text = "\n".join(f"• {r}" for r in decision.reasons)
        console.print(Panel(reasons_text, title="[bold]推荐理由[/bold]"))

    # 替代方案
    if decision.alternatives:
        table = Table(title="替代方案")
        table.add_column("策略", style="cyan")
        table.add_column("模型", style="magenta")
        table.add_column("成本", justify="right")
        table.add_column("质量", justify="right")
        table.add_column("备注")

        for alt in decision.alternatives:
            # 展示模型角色
            models_parts = []
            if alt.planner:
                models_parts.append(f"规划:{alt.planner}")
            if alt.executor:
                models_parts.append(f"执行:{alt.executor}")
            if alt.reviewer:
                models_parts.append(f"审查:{alt.reviewer}")
            models_text = ", ".join(models_parts) if models_parts else "-"

            table.add_row(
                alt.strategy.value,
                models_text,
                f"¥{alt.cost:.4f}",
                f"{alt.quality:.2f}",
                alt.note,
            )
        console.print(table)

    # 质量门禁
    if decision.quality_gate:
        gates_text = ", ".join(decision.quality_gate)
        console.print(f"\n[bold]质量门禁:[/bold] {gates_text}")


def _output_json(decision):
    """JSON 格式输出。"""
    data = decision.model_dump(mode="json")
    console.print(json.dumps(data, indent=2, ensure_ascii=False))
