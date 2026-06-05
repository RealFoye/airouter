import typer

app = typer.Typer(
    name="ai-router",
    help="AI Router - 企业级 AI 模型智能路由与 Token 精细化管控系统",
    no_args_is_help=True,
)


@app.callback()
def main():
    """AI Router - 企业级 AI 模型智能路由与 Token 精细化管控系统"""
    pass


if __name__ == "__main__":
    app()
