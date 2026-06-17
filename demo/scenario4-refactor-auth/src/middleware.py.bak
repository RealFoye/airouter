"""中间件 — 初始硬编码版本。"""


class SimpleMiddleware:
    """简单中间件：硬编码 token 检查。"""

    def __init__(self, app):
        self.app = app

    def __call__(self, request: dict) -> dict:
        token = request.get("headers", {}).get("Authorization", "")
        if token.startswith("Bearer "):
            token = token[7:]
        # 硬编码：直接调用 auth.check_token
        from . import auth
        user_info = auth.check_token(token)
        if not user_info:
            return {"status": 401, "error": "Unauthorized"}
        request["user"] = user_info
        return self.app(request)
