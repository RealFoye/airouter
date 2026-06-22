"""ai-router agent 命令：交互式 REPL Agent。"""

from pathlib import Path
from types import ModuleType

import typer
from rich.cells import cell_len
from rich.console import Console
from rich.padding import Padding
from rich.text import Text

from airouter.engine.agent.session import AgentSession

console = Console()

_readline: ModuleType | None
try:
    import readline as _readline
except ImportError:  # pragma: no cover - Windows fallback
    _readline = None


def _configure_line_editing() -> bool:
    """启用光标移动、行内编辑和上下键历史；不可用时保持普通输入。"""
    if _readline is None:
        return False
    _readline.parse_and_bind("set editing-mode emacs")
    return True


def _render_user_message(message: str) -> None:
    """将刚提交的输入重绘为浅灰背景消息块，区分用户问题与 Agent 回答。"""
    if not console.is_terminal:
        return

    # input() 已经把原始输入留在终端中。先按实际显示宽度清除该行（含自动换行），
    # 再绘制消息块，避免同一句问题显示两遍。
    terminal_width = max(1, console.width)
    display_rows = max(1, (cell_len(f"> {message}") - 1) // terminal_width + 1)
    console.file.write("\x1b[1A\r\x1b[2K" * display_rows)
    console.file.flush()

    console.print(
        Padding(
            Text(message, style="black"),
            (0, 1),
            style="on grey93",
            expand=True,
        )
    )


def agent(
    workdir: str = typer.Option(".", "--workdir", "-w", help="工作目录"),
    resume: str = typer.Option(None, "--resume", help="恢复会话: latest 或 session_id"),
    model: str = typer.Option(None, "--model", "-m", help="覆盖执行模型"),
    yes: bool = typer.Option(False, "--yes", "-y", help="跳过人工确认"),
    max_cost: float = typer.Option(5.0, "--max-cost", help="会话总成本上限(CNY)"),
    max_turns: int = typer.Option(30, "--max-turns", help="每轮最大工具调用次数"),
):
    """启动交互式 Agent 会话（多轮对话）。"""
    workdir_path = Path(workdir).resolve()

    if not workdir_path.exists():
        console.print(f"[red]工作目录不存在: {workdir}[/red]")
        raise typer.Exit(code=1)

    session = AgentSession(
        workdir=workdir_path,
        model_override=model,
        skip_approval=yes,
        max_cost=max_cost,
        max_turns=max_turns,
    )

    if resume:
        if not session.restore(resume):
            raise typer.Exit(code=1)

    session.print_banner()
    _configure_line_editing()

    while True:
        try:
            user_input = console.input("[bold green]> [/bold green]")
        except (EOFError, KeyboardInterrupt):
            session.save()
            console.print("\n[dim]会话已保存，再见！[/dim]")
            break

        if not user_input.strip():
            continue

        if user_input.startswith("/"):
            if session.handle_slash(user_input):
                break
            continue

        _render_user_message(user_input)
        session.execute_turn(user_input)
        session.save()
