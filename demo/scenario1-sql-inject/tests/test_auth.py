"""auth 模块测试。"""

import os
import sqlite3
import tempfile

import pytest

from src.auth import get_user, search_users, login


@pytest.fixture
def db():
    """创建临时测试数据库。"""
    fd, path = tempfile.mkstemp(suffix=".db")
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT, email TEXT, role TEXT, password TEXT)"
    )
    conn.execute(
        "INSERT INTO users VALUES (1, 'alice', 'alice@example.com', 'admin', 'secret123')"
    )
    conn.execute(
        "INSERT INTO users VALUES (2, 'bob', 'bob@example.com', 'user', 'pass456')"
    )
    conn.commit()
    conn.close()
    yield path
    os.close(fd)
    os.unlink(path)


def test_get_user_exists(db):
    user = get_user(db, "alice")
    assert user is not None
    assert user["username"] == "alice"


def test_get_user_not_exists(db):
    user = get_user(db, "nobody")
    assert user is None


def test_search_users(db):
    results = search_users(db, "alice")
    assert len(results) == 1


def test_login_success(db):
    assert login(db, "alice", "secret123") is True


def test_login_wrong_password(db):
    assert login(db, "alice", "wrong") is False


def test_sql_injection_get_user(db):
    """SQL 注入测试：恶意输入不应该返回非预期数据。"""
    # 这个输入在存在 SQL 注入漏洞时会返回所有用户
    user = get_user(db, "' OR '1'='1")
    # 修复后应该返回 None（没有这个用户名的用户）
    assert user is None


def test_sql_injection_login(db):
    """SQL 注入测试：恶意输入不应该绕过认证。"""
    # 这个输入在存在 SQL 注入漏洞时会绕过认证
    result = login(db, "' OR '1'='1' --", "")
    # 修复后应该返回 False
    assert result is False
