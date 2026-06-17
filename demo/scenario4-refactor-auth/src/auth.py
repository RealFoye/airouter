"""用户认证模块 — 初始混乱版本（登录+鉴权+权限混在一起）。"""

import hashlib
import time

# 硬编码用户数据（demo 用）
USERS = {
    "admin": {"password_hash": hashlib.sha256(b"admin123").hexdigest(), "role": "admin", "token": None},
    "alice": {"password_hash": hashlib.sha256(b"alice456").hexdigest(), "role": "user", "token": None},
}

# 硬编码权限表
PERMISSIONS = {
    "admin": ["read", "write", "delete", "manage_users"],
    "user": ["read", "write"],
}


def login(username: str, password: str) -> dict | None:
    """登录验证。"""
    user = USERS.get(username)
    if not user:
        return None
    pw_hash = hashlib.sha256(password.encode()).hexdigest()
    if pw_hash != user["password_hash"]:
        return None
    # 生成简单 token
    token = hashlib.sha256(f"{username}:{time.time()}".encode()).hexdigest()
    user["token"] = token
    return {"username": username, "token": token, "role": user["role"]}


def check_token(token: str) -> dict | None:
    """检查 token 是否有效（硬编码在中间件里）。"""
    for username, user in USERS.items():
        if user.get("token") == token:
            return {"username": username, "role": user["role"]}
    return None


def check_permission(username: str, action: str) -> bool:
    """检查用户权限。"""
    user = USERS.get(username)
    if not user:
        return False
    role = user["role"]
    allowed = PERMISSIONS.get(role, [])
    return action in allowed


def logout(username: str) -> bool:
    """登出。"""
    user = USERS.get(username)
    if user:
        user["token"] = None
        return True
    return False
