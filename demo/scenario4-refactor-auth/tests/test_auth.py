"""scenario4 认证模块测试。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from auth import USERS, login, check_token, check_permission, logout


class TestLogin:
    def test_valid_login(self):
        result = login("admin", "admin123")
        assert result is not None
        assert result["username"] == "admin"
        assert "token" in result

    def test_invalid_password(self):
        result = login("admin", "wrong")
        assert result is None

    def test_unknown_user(self):
        result = login("nobody", "pass")
        assert result is None


class TestToken:
    def test_valid_token(self):
        login_result = login("alice", "alice456")
        assert login_result is not None
        token = login_result["token"]
        user_info = check_token(token)
        assert user_info is not None
        assert user_info["username"] == "alice"

    def test_invalid_token(self):
        result = check_token("fake-token")
        assert result is None

    def test_empty_token(self):
        result = check_token("")
        assert result is None


class TestPermission:
    def test_admin_has_manage_users(self):
        assert check_permission("admin", "manage_users") is True

    def test_user_no_manage_users(self):
        assert check_permission("alice", "manage_users") is False

    def test_user_can_read(self):
        assert check_permission("alice", "read") is True

    def test_unknown_user(self):
        assert check_permission("nobody", "read") is False


class TestLogout:
    def test_logout(self):
        result = login("admin", "admin123")
        token = result["token"]
        assert check_token(token) is not None
        assert logout("admin") is True
        # 登出后 token 无效
        assert check_token(token) is None

    def test_logout_unknown(self):
        assert logout("nobody") is False
