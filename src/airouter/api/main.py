"""FastAPI 应用入口。"""

from fastapi import FastAPI

app = FastAPI(
    title="AI Router",
    description="企业级 AI 模型智能路由与 Token 精细化管控系统",
    version="0.1.0",
)


@app.get("/health")
async def health():
    return {"status": "ok"}
