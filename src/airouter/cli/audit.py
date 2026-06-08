"""CLI 审计命令：ai-router audit"""

import json
from datetime import datetime, timedelta
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from airouter.engine.audit.attribution import Attribution
from airouter.engine.audit.collector import Collector
from airouter.models.database import init_db

app = typer.Typer()
console = Console()


@app.callback(invoke_without_command=True)
def audit(
    days: int = typer.Option(30, "--days", "-d", help="审计时间范围（天）"),
    user_id: Optional[str] = typer.Option(None, "--user", help="按用户过滤"),
    project_id: Optional[str] = typer.Option(None, "--project", help="按项目过滤"),
    department: Optional[str] = typer.Option(None, "--department", help="按部门过滤"),
    output_format: str = typer.Option("rich", "--format", "-f", help="输出格式: rich/json"),
    db_url: str = typer.Option("sqlite:///seed.db", "--db", help="数据库 URL（默认 sqlite:///seed.db）"),
):
    """审计 Token 消费和浪费模式。"""
    # 初始化数据库
    init_db(db_url)

    # 计算时间范围
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days)

    # 采集消费记录
    collector = Collector()
    records = collector.collect(
        start_date=start_date,
        end_date=end_date,
        user_id=user_id,
        project_id=project_id,
        department=department,
    )

    if not records:
        console.print("[yellow]⚠ 没有找到消费记录。请确认数据库中有数据或调整时间范围。[/yellow]")
        console.print(f"当前数据库：{db_url}")
        raise typer.Exit(code=1)

    # 归因分析
    attribution = Attribution()
    result = attribution.analyze(records, top_n_waste=5)

    # 输出
    if output_format == "json":
        _output_json(result)
    else:
        _output_rich(result, days, user_id, project_id, department)


def _output_json(result: dict):
    """JSON 格式化输出（结构化）。"""
    output = {
        "total_cost": result["total_cost"],
        "total_calls": result["total_calls"],
        "total_input_tokens": result["total_input_tokens"],
        "total_output_tokens": result["total_output_tokens"],
        "daily_average": result["daily_average"],
        "by_user": [item.model_dump() for item in result["by_user"]],
        "by_model": [item.model_dump() for item in result["by_model"]],
        "by_project": [item.model_dump() for item in result["by_project"]],
        "by_department": [item.model_dump() for item in result["by_department"]],
        "by_task_type": [item.model_dump() for item in result["by_task_type"]],
        "top_waste_patterns": [p.model_dump() for p in result["top_waste_patterns"]],
        "total_estimated_savings": result["total_estimated_savings"],
        "heavy_users": result["heavy_users"],
    }
    # 使用 print 而非 console.print 避免 Rich 自动换行破坏 JSON 结构
    print(json.dumps(output, indent=2, ensure_ascii=False))


def _output_rich(
    result: dict,
    days: int,
    user_id: Optional[str],
    project_id: Optional[str],
    department: Optional[str],
):
    """Rich 格式化输出。"""
    # 标题
    filter_parts = []
    if user_id:
        filter_parts.append(f"用户: {user_id}")
    if project_id:
        filter_parts.append(f"项目: {project_id}")
    if department:
        filter_parts.append(f"部门: {department}")

    filter_str = f"（{', '.join(filter_parts)}）" if filter_parts else ""
    title = f"Token 消费审计报告 - 最近 {days} 天{filter_str}"

    console.print()
    console.print(Panel(title, style="bold blue"))
    console.print()

    # 1. 汇总
    summary_text = Text()
    summary_text.append("总消费: ", style="bold")
    summary_text.append(f"¥{result['total_cost']:,.2f}")
    summary_text.append(" | 总调用: ", style="bold")
    summary_text.append(f"{result['total_calls']:,} 次")
    summary_text.append(" | 日均: ", style="bold")
    summary_text.append(f"¥{result['daily_average']:,.2f}")
    summary_text.append(" | Token 总量: ", style="bold")

    total_tokens = result["total_input_tokens"] + result["total_output_tokens"]
    summary_text.append(f"{total_tokens:,} tokens")

    console.print(Panel(summary_text, title="消费汇总", border_style="blue"))

    # 2. 按用户
    if result["by_user"]:
        user_table = Table(title="按用户消费", show_lines=False)
        user_table.add_column("用户", style="cyan", no_wrap=True)
        user_table.add_column("消费 (¥)", justify="right", style="magenta")
        user_table.add_column("调用次数", justify="right")
        user_table.add_column("占比", justify="right")

        for item in result["by_user"]:
            # 标记重度用户
            is_heavy = item.key in result["heavy_users"]
            user_name = f"{item.key} ⚠️" if is_heavy else item.key
            user_style = "bold red" if is_heavy else "cyan"

            user_table.add_row(
                Text(user_name, style=user_style),
                f"{item.total_cost:,.2f}",
                f"{item.total_calls:,}",
                f"{item.percentage:.1f}%",
            )

        console.print(user_table)
        console.print()

    # 3. 按模型
    if result["by_model"]:
        model_table = Table(title="按模型消费", show_lines=False)
        model_table.add_column("模型", style="cyan", no_wrap=True)
        model_table.add_column("消费 (¥)", justify="right", style="magenta")
        model_table.add_column("调用次数", justify="right")
        model_table.add_column("占比", justify="right")

        for item in result["by_model"]:
            # 标记占比过高（> 50%）
            is_concentrated = item.percentage > 50.0
            model_name = f"{item.key} <-- 占比过高" if is_concentrated else item.key
            model_style = "bold yellow" if is_concentrated else "cyan"

            model_table.add_row(
                Text(model_name, style=model_style),
                f"{item.total_cost:,.2f}",
                f"{item.total_calls:,}",
                f"{item.percentage:.1f}%",
            )

        console.print(model_table)
        console.print()

    # 4. Top 5 浪费模式
    if result["top_waste_patterns"]:
        waste_table = Table(title="Top 5 浪费模式", show_lines=True)
        waste_table.add_column("#", style="bold", width=3)
        waste_table.add_column("类型", style="cyan", no_wrap=True)
        waste_table.add_column("范围", style="magenta")
        waste_table.add_column("次数", justify="right")
        waste_table.add_column("当前成本 (¥)", justify="right")
        waste_table.add_column("预估节省 (¥)", justify="right", style="green")
        waste_table.add_column("严重度", justify="center")
        waste_table.add_column("建议", max_width=60)

        for idx, pattern in enumerate(result["top_waste_patterns"], 1):
            # 严重度颜色
            severity_colors = {"High": "bold red", "Medium": "yellow", "Low": "green"}
            severity_style = severity_colors.get(pattern.severity, "white")

            waste_table.add_row(
                str(idx),
                pattern.pattern_type,
                f"{pattern.scope}: {pattern.scope_value}",
                str(pattern.occurrence_count),
                f"{pattern.current_cost:,.2f}",
                f"{pattern.estimated_savings:,.2f}",
                Text(pattern.severity, style=severity_style),
                pattern.suggestion,
            )

        console.print(waste_table)
        console.print()

    # 5. 总预估节省
    if result["total_estimated_savings"] > 0:
        savings_pct = (
            result["total_estimated_savings"] / result["total_cost"] * 100
            if result["total_cost"] > 0
            else 0
        )

        savings_text = Text()
        savings_text.append("总预估节省: ", style="bold")
        savings_text.append(f"¥{result['total_estimated_savings']:,.2f}/月", style="bold green")
        savings_text.append(f" (节省 {savings_pct:.1f}%)")

        console.print(Panel(savings_text, title="优化建议", border_style="green"))
    else:
        console.print(Panel("未发现明显浪费模式 🎉", title="优化建议", border_style="green"))
