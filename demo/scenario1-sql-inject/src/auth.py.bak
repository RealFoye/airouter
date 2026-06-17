"""用户认证模块 - 包含登录和查询功能。"""

import sqlite3


def get_user(db_path: str, username: str) -> dict | None:
    """根据用户名查询用户信息。"""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    # 查询用户
    query = "SELECT * FROM users WHERE username = ?"
    cursor.execute(query, (username,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return {"id": row[0], "username": row[1], "email": row[2], "role": row[3]}
    return None


def search_users(db_path: str, keyword: str) -> list[dict]:
    """搜索用户（按关键词）。"""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    query = "SELECT * FROM users WHERE username LIKE ? OR email LIKE ?"
    cursor.execute(query, (f"%{keyword}%", f"%{keyword}%"))
    rows = cursor.fetchall()
    conn.close()
    return [{"id": r[0], "username": r[1], "email": r[2], "role": r[3]} for r in rows]


def login(db_path: str, username: str, password: str) -> bool:
    """验证用户名和密码。"""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    query = "SELECT * FROM users WHERE username = '%s' AND password = '%s'" % (username, password)
    cursor.execute(query)
    result = cursor.fetchone()
    conn.close()
    return result is not None
