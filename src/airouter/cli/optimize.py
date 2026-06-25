"""ai-router optimize 命令：Prompt/上下文优化建议。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal, Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from airouter.config import load_models
from airouter.engine.optimize.optimizer import PromptOptimizer
from airouter.models.model_registry import ModelRegistry

app = typer.Typer()
console = Console()

VALID_SCENARIOS = (
    "SINGLE_TURN",
    "FIXED_PROMPT_TOOLS",
    "AGENT_MULTI_TURN",
    "SAME_PROJECT_REPEAT",
    "RANDOM_CONTEXT",
)


@app.callback(invoke_without_command=True)
def optimize(
    prompt: Optional[str] = typer.Option(None, "--prompt", "-p", help="Prompt 文本"),
    context_file: Optional[str] = typer.Option(None, "--context-file", "-c", help="Prompt 文件路径"),
    model: Optional[str] = typer.Option(None, "--model", "-m", help="当前使用的模型名称（可选）"),
    scenario: Literal[
        "SINGLE_TURN", "FIXED_PROMPT_TOOLS", "AGENT_MULTI_TURN", "SAME_PROJECT_REPEAT", "RANDOM_CONTEXT"
    ] = typer.Option(
        "SINGLE_TURN", "--scenario", "-s",
        help="使用场景: SINGLE_TURN/FIXED_PROMPT_TOOLS/AGENT_MULTI_TURN/SAME_PROJECT_REPEAT/RANDOM_CONTEXT",
    ),
    turns: Optional[int] = typer.Option(None, "--turns", "-t", help="预期对话轮数（默认按场景推断）"),
    output_format: Literal["rich", "json"] = typer.Option("rich", "--format", "-f", help="输出格式: rich/json"),
) -> None:
    """分析 Prompt 并给出上下文优化建议。"""
    # 校验 turns
    if turns is not None and turns < 1:
        console.print("[red]错误：--turns 必须 >= 1[/red]")
        raise typer.Exit(code=1)

    # 解析输入
    prompt_text = _resolve_input(prompt, context_file)
    if not prompt_text:
        console.print("[red]错误：请提供 --prompt 或 --context-file[/red]")
        raise typer.Exit(code=1)

    # 校验模型名
    if model:
        registry = ModelRegistry(load_models())
        if not registry.get_by_name(model):
            available = [m.name for m in registry.all_models]
            console.print(f"[red]错误：模型 '{model}' 不存在。可用模型: {', '.join(available)}[/red]")
            raise typer.Exit(code=1)

    optimizer = PromptOptimizer()
    result = optimizer.optimize(
        prompt=prompt_text,
        model_name=model,
        scenario=scenario,
        expected_turns=turns,
    )

    if output_format == "json":
        _output_json(result)
    else:
        _output_rich(result)


def _resolve_input(prompt: Optional[str], context_file: Optional[str]) -> str:
    """解析 prompt 输入：文件路径或直接文本。"""
    parts: list[str] = []

    if context_file:
        path = Path(context_file)
        if not path.exists():
            console.print(f"[red]错误：文件不存在 {context_file}[/red]")
            raise typer.Exit(code=1)
        parts.append(path.read_text(encoding="utf-8"))

    if prompt:
        parts.append(prompt)

    return "\n".join(parts)


def _output_rich(result) -> None:
    """Rich 格式化输出。"""
    # 分析结果
    models_desc = _format_models(result.current_models)
    analysis_text = Text()
    analysis_text.append("当前Token: ", style="bold")
    analysis_text.append(f"{result.input_breakdown.total} input + ~{result.estimated_output_tokens} output\n")
    analysis_text.append("当前方案: ", style="bold")
    analysis_text.append(f"{result.current_strategy.value} ({models_desc})\n")
    analysis_text.append("单轮成本: ", style="bold")
    analysis_text.append(f"¥{result.current_cost:.4f}\n")
    analysis_text.append(f"预计 {result.estimated_turns} 轮成本: ", style="bold")
    analysis_text.append(f"¥{result.scenario_cost:.4f} ({result.scenario})")
    console.print(Panel(analysis_text, title="[bold blue]分析结果[/bold blue]", border_style="blue"))

    # 输入组成分析
    bd = result.input_breakdown
    breakdown_text = Text()
    _add_breakdown_line(breakdown_text, "System Prompt", bd.system_prompt_tokens, "固定", "可缓存")
    _add_breakdown_line(breakdown_text, "Tool Definitions", bd.tool_definitions_tokens, "固定", "可缓存")
    _add_breakdown_line(breakdown_text, "项目上下文", bd.fixed_context_tokens, "半固定", "部分可缓存")
    _add_breakdown_line(breakdown_text, "对话历史", bd.conversation_history_tokens, "", "可摘要压缩")
    _add_breakdown_line(breakdown_text, "用户请求", bd.dynamic_query_tokens, "", "不可缓存")
    console.print(Panel(breakdown_text, title="[bold]输入组成分析[/bold]"))

    # 优化建议
    if result.suggestions:
        table = Table(title="优化建议")
        table.add_column("#", style="dim", width=3)
        table.add_column("类别", style="cyan", width=6)
        table.add_column("建议", style="bold")
        table.add_column("节省", justify="right", style="green")
        table.add_column("占比", justify="right")

        for i, s in enumerate(result.suggestions, 1):
            approval_tag = " [red]（需审批）[/red]" if s.details.get("requires_approval") else ""
            table.add_row(
                str(i),
                f"[{s.category}]{approval_tag}",
                s.title + "\n" + s.description,
                f"¥{s.estimated_savings:.4f}",
                f"{s.savings_percentage:.0%}",
            )
        console.print(table)

        # 压缩 3 策略对比（如果有压缩建议）
        for s in result.suggestions:
            if s.category == "压缩" and "comparison" in s.details:
                _print_compression_comparison(s)
            if s.category == "裁剪" and s.details.get("evidence"):
                _print_trimming_evidence(s)
    else:
        console.print("[dim]未发现有效的优化建议[/dim]")

    # 汇总
    summary_text = Text()
    summary_text.append(f"\n按 {result.estimated_turns} 轮估算，最佳参考路径节省: ", style="bold yellow")
    summary_text.append(f"¥{result.total_estimated_savings:.4f} ({result.total_savings_percentage:.0%})")
    summary_text.append("\n参考优化后成本: ", style="bold")
    summary_text.append(f"¥{result.optimized_cost:.4f}（不同路径不重复相加）")
    console.print(summary_text)

    # 警告
    if result.warnings:
        warn_text = "\n".join(f"  - {w}" for w in result.warnings)
        console.print(Panel(warn_text, title="[yellow]注意[/yellow]", border_style="yellow"))


def _add_breakdown_line(text: Text, label: str, tokens: int, tag: str, hint: str) -> None:
    """添加一行 breakdown 描述。"""
    text.append(f"  {label}: ", style="bold")
    text.append(f"{tokens} tokens")
    if tag:
        text.append(f" ({tag})")
    text.append(f"  ← {hint}\n", style="dim")


def _print_compression_comparison(suggestion) -> None:
    """打印压缩 3 策略对比表。"""
    comparison = suggestion.details.get("comparison", {})
    if not comparison:
        return

    table = Table(title="压缩策略对比")
    table.add_column("策略", style="cyan")
    table.add_column("压缩后 tokens", justify="right")
    table.add_column("压缩率", justify="right")

    for strategy_name, data in comparison.items():
        table.add_row(
            strategy_name,
            str(data["compressed_tokens"]),
            f"{data['reduction_rate']:.1%}",
        )

    console.print(table)
    auto = suggestion.details.get("auto_strategy", "")
    console.print(f"  推荐策略: [bold]{auto}[/bold]")


def _print_trimming_evidence(suggestion) -> None:
    """展示裁剪候选的来源、片段和启发式判定依据。"""
    evidence = suggestion.details.get("evidence", [])
    if not evidence:
        return

    table = Table(title="裁剪依据（启发式建议，执行前需确认）")
    table.add_column("位置", style="cyan", width=20)
    table.add_column("原文片段", overflow="fold")
    table.add_column("判定原因", overflow="fold")
    table.add_column("预计减少", justify="right", width=12)

    for item in evidence:
        start = int(item["line_start"])
        end = int(item["line_end"])
        line_range = f"第 {start} 行" if start == end else f"第 {start}-{end} 行"
        location = f"{item['source']}\n{line_range}"
        table.add_row(
            Text(location),
            Text(str(item["excerpt"])),
            Text(f"{item['reason']}（{item['confidence']}）"),
            f"约 {item['estimated_reduction_tokens']} tokens",
        )

    console.print(table)


def _format_models(models) -> str:
    """格式化模型分配信息。"""
    parts = []
    if models.planner:
        parts.append(f"planner:{models.planner}")
    if models.executor:
        parts.append(f"executor:{models.executor}")
    if models.reviewer:
        parts.append(f"reviewer:{models.reviewer}")
    return ", ".join(parts) if parts else "未指定"


def _output_json(result) -> None:
    """JSON 格式输出。"""
    data = result.model_dump(mode="json")
    print(json.dumps(data, indent=2, ensure_ascii=False))
