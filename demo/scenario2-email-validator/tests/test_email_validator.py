import pytest

from src.email_validator import validate_email


class TestValidateEmail:
    """validate_email 函数单元测试"""

    # --- 合法邮箱 ---
    @pytest.mark.parametrize("email", [
        "user@example.com",
        "user.name@example.com",
        "user_name@example.com",
        "user+tag@example.com",
        "user%tag@example.com",
        "user@sub.example.com",
        "a@b.co",
        "123@test.com",
        "hello@world.cn",
    ])
    def test_valid_emails(self, email):
        assert validate_email(email) is True

    # --- 非法邮箱 ---
    @pytest.mark.parametrize("email", [
        "",                       # 空字符串
        "notanemail",             # 没有 @
        "@domain.com",            # 本地部分为空
        "user@",                  # 域名部分为空
        "user@.com",              # 域名以点开头
        "user@domain",            # 域名没有点
        "user@domain.c",          # 顶级域少于 2 字符
        "user@domain..com",       # 域名包含连续点
        ".user@domain.com",       # 本地部分以点开头
        "user.@domain.com",       # 本地部分以点结尾
        "user@domain.c",          # 顶级域长度不足
        "user name@domain.com",   # 包含空格
        "user@domain,com",        # 包含逗号
        "a" + "@" * 2 + "b.com",  # 多个 @
        None,                     # None
        123,                      # 非字符串
    ])
    def test_invalid_emails(self, email):
        assert validate_email(email) is False

    # --- 边界情况 ---
    def test_single_char_local(self):
        """本地部分只有一个字符"""
        assert validate_email("a@b.cd") is True

    def test_long_domain(self):
        """多层子域名"""
        assert validate_email("user@a.b.c.d.e.co") is True