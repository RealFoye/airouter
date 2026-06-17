"""AI Router CLI 入口。"""

import os
import warnings

# 静默 sklearn 版本不一致 warning（OpenSquilla bundle pickle 版本差异）
warnings.filterwarnings("ignore", category=UserWarning, module="sklearn")
# 设置 matplotlib 缓存目录避免 cache warning
if "MPLCONFIGDIR" not in os.environ:
    os.environ["MPLCONFIGDIR"] = "/tmp/matplotlib"

import typer  # noqa: E402

from airouter.cli import analyze, audit, benchmark, optimize, run  # noqa: E402

app = typer.Typer(
    name="ai-router",
    help="AI Router - 企业级 AI 模型智能路由与 Token 精细化管控系统",
    no_args_is_help=True,
)

app.command("analyze")(analyze.analyze)
app.command("audit")(audit.audit)
app.command("benchmark")(benchmark.benchmark)
app.command("optimize")(optimize.optimize)
app.command("run")(run.run)


@app.callback()
def main():
    """AI Router - 企业级 AI 模型智能路由与 Token 精细化管控系统"""
    pass


if __name__ == "__main__":
    app()
