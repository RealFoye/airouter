"""ai-router analyze 命令。"""

import json
from enum import Enum
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from airouter.config import load_all
from airouter.engine.router.router import Router

app = typer.Typer()
console = Console()


class ComplexityMode(str, Enum):
    """CLI 可选的复杂度分析模式。"""

    RULES = "rules"
    SHADOW = "shadow"
    OPENSQUILLA = "opensquilla"
    HYBRID = "hybrid"


def _build_router(mode: ComplexityMode) -> Router:
    """构建分析 Router；默认 Bundle 与 Agent 入口保持一致。"""
    config = load_all()
    complexity = config.complexity.model_copy(update={"mode": mode.value})

    if mode is not ComplexityMode.RULES and complexity.bundle_dir is None:
        project_root = Path(__file__).resolve().parents[3]
        default_bundle = (
            project_root
            / "opensquilla/src/opensquilla/squilla_router/models/v4.2_phase3_inference"
        )
        if default_bundle.exists():
            complexity = complexity.model_copy(update={"bundle_dir": default_bundle})

    return Router(config=config.model_copy(update={"complexity": complexity}))


@app.callback(invoke_without_command=True)
def analyze(
    task: str = typer.Argument(..., help="任务描述"),
    output_format: str = typer.Option("rich", "--format", "-f", help="输出格式: rich/json"),
    show_complexity: bool = typer.Option(False, "--show-complexity", help="显示复杂度分析详情"),
    mode: ComplexityMode = typer.Option(
        ComplexityMode.OPENSQUILLA,
        "--mode",
        help="复杂度模式；默认使用 OpenSquilla ml_final",
    ),
):
    """分析任务并推荐最优模型。"""
    router = _build_router(mode)
    decision = router.route(task)

    if output_format == "json":
        _output_json(decision)
    else:
        _output_rich(decision)
        if show_complexity:
            _output_complexity(decision)


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

    diag = decision.complexity_analysis
    if diag and diag.mode != ComplexityMode.RULES.value and not diag.ml_available:
        reason = diag.fallback_reason or diag.resolution_reason
        console.print(f"\n[yellow]OpenSquilla 不可用，已回退 Rules：{reason}[/yellow]")


def _output_json(decision):
    """JSON 格式输出。"""
    data = decision.model_dump(mode="json")
    print(json.dumps(data, indent=2, ensure_ascii=False))


def _output_complexity(decision):
    """显示复杂度分析详情。"""
    diag = decision.complexity_analysis
    if diag is None:
        console.print("[dim]无复杂度分析数据[/dim]")
        return

    text = Text()
    text.append("模式: ", style="bold")
    text.append(f"{diag.mode}\n")
    text.append("规则复杂度: ", style="bold")
    text.append(f"{diag.rule_complexity}\n")
    text.append("最终复杂度: ", style="bold")
    text.append(f"{diag.resolved}\n")
    text.append("解析原因: ", style="bold")
    text.append(f"{diag.resolution_reason}\n")

    if diag.ml_available:
        text.append("\nML 可用: ", style="bold green")
        text.append("是\n")
        if diag.ml_raw_class:
            text.append("ML raw class: ", style="bold")
            text.append(f"{diag.ml_raw_class}")
            if diag.ml_raw_confidence is not None:
                text.append(f" (conf={diag.ml_raw_confidence:.2f})")
            text.append("\n")
        if diag.ml_final_class:
            text.append("ML final class: ", style="bold")
            text.append(f"{diag.ml_final_class}")
            if diag.ml_final_class_probability is not None:
                text.append(f" (prob={diag.ml_final_class_probability:.2f})")
            text.append("\n")
        if diag.ml_probabilities:
            probs = ", ".join(f"{k}={v:.2f}" for k, v in sorted(diag.ml_probabilities.items()))
            text.append("概率分布: ", style="bold")
            text.append(f"{probs}\n")
        if diag.ml_margin is not None:
            text.append("Margin: ", style="bold")
            text.append(f"{diag.ml_margin:.3f}\n")
        if diag.ml_latency_ms is not None:
            text.append("推理耗时: ", style="bold")
            text.append(f"{diag.ml_latency_ms:.1f}ms\n")
    else:
        text.append("\nML 可用: ", style="bold yellow")
        text.append("否\n")
        if diag.fallback_reason:
            text.append("Fallback 原因: ", style="bold")
            text.append(f"{diag.fallback_reason}\n")

    console.print(Panel(text, title="[bold cyan]复杂度分析[/bold cyan]", border_style="cyan"))
