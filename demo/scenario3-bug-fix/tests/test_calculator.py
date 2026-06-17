"""calculator 测试。"""

import pytest
from src.calculator import add, subtract, multiply, divide, power


def test_add():
    assert add(2, 3) == 5


def test_subtract():
    assert subtract(5, 3) == 2


def test_multiply():
    assert multiply(3, 4) == 12


def test_divide():
    assert divide(10, 2) == 5.0


def test_divide_by_zero():
    """除数为 0 应该抛出 ValueError 而不是 ZeroDivisionError。"""
    with pytest.raises(ValueError, match="除数不能为零"):
        divide(10, 0)


def test_divide_negative_zero():
    """负零也应该被拦截。"""
    with pytest.raises(ValueError, match="除数不能为零"):
        divide(10, -0.0)


def test_power():
    assert power(2, 3) == 8


def test_power_zero():
    assert power(5, 0) == 1
