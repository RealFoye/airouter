import re


def validate_email(email: str) -> bool:
    """验证邮箱格式是否合法。

    规则：
    - 包含一个 @ 符号
    - 本地部分（@ 之前）不为空
    - 域名部分（@ 之后）至少包含一个点号
    - 域名最后一部分（顶级域）至少 2 个字符
    - 只允许字母、数字、点、下划线、百分号、加号、减号
    - @ 前后不能以点号开头或结尾

    Args:
        email: 待验证的邮箱字符串

    Returns:
        bool: 合法返回 True，否则返回 False
    """
    if not isinstance(email, str):
        return False

    # 必须包含一个且仅一个 @
    if email.count("@") != 1:
        return False

    local, domain = email.split("@")

    # 本地部分和域名部分都不能为空
    if not local or not domain:
        return False

    # 本地部分不能以 . 开头或结尾
    if local.startswith(".") or local.endswith("."):
        return False

    # 域名必须包含 .
    if "." not in domain:
        return False

    # 分离域名各部分
    domain_parts = domain.split(".")
    # 域名各部分都不能为空
    if any(part == "" for part in domain_parts):
        return False
    # 顶级域至少 2 个字符
    if len(domain_parts[-1]) < 2:
        return False

    # 检查允许的字符
    allowed_pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
    if not re.match(allowed_pattern, email):
        return False

    return True