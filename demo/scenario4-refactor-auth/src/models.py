"""用户数据模型。"""

from dataclasses import dataclass


@dataclass
class User:
    """用户。"""
    username: str
    role: str = "user"
    token: str | None = None
