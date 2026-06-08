"""测试 CLI analyze 和 audit 命令。"""

import json
import os
import tempfile

import pytest
from typer.testing import CliRunner

from airouter.cli.main import app

runner = CliRunner()


def test_analyze_rich_output():
    result = runner.invoke(app, ["analyze", "写一个简单的函数"])
    assert result.exit_code == 0
    assert "任务特征" in result.output
    assert "推荐方案" in result.output
    assert "推荐理由" in result.output


def test_analyze_json_output():
    result = runner.invoke(app, ["analyze", "写一个简单的函数", "--format", "json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert "task_features" in data
    assert "recommended_strategy" in data
    assert "models" in data
    assert "estimated_cost" in data


def test_analyze_complex_task():
    result = runner.invoke(app, ["analyze", "设计一个支持百万并发的消息推送系统"])
    assert result.exit_code == 0
    assert "ARCHITECTURE" in result.output
    assert "人工审核" in result.output


def test_analyze_simple_task():
    result = runner.invoke(app, ["analyze", "解释Python的GIL是什么"])
    assert result.exit_code == 0
    assert "CONVERSATION" in result.output


def test_analyze_help():
    result = runner.invoke(app, ["analyze", "--help"])
    assert result.exit_code == 0
    assert "分析任务并推荐最优模型" in result.output


# ── Audit CLI 测试 ────────────────────────────────────────────


@pytest.fixture(scope="module")
def seed_db_url(tmp_path_factory):
    """创建一个临时 DB 并注入种子数据，返回 db_url。"""
    from scripts.generate_seed_data import generate_seed_data

    tmpdir = tmp_path_factory.mktemp("audit_test")
    db_path = str(tmpdir / "test_audit.db")
    generate_seed_data(days=1, rows_per_day=20, output_db=db_path)
    return f"sqlite:///{db_path}"


def test_audit_rich_output(seed_db_url):
    """测试 audit 命令 Rich 输出。"""
    result = runner.invoke(app, ["audit", "--days", "30", "--db", seed_db_url])
    assert result.exit_code == 0
    assert "消费汇总" in result.output
    assert "按用户消费" in result.output
    assert "按模型消费" in result.output


def test_audit_json_output(seed_db_url):
    """测试 audit 命令 JSON 输出（结构化）。"""
    result = runner.invoke(app, ["audit", "--days", "30", "--format", "json", "--db", seed_db_url])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert "total_cost" in data
    assert "total_calls" in data
    assert data["total_calls"] > 0
    assert "by_user" in data
    assert "by_model" in data
    assert "top_waste_patterns" in data
    # 验证 by_user 是结构化数据（不是字符串）
    assert isinstance(data["by_user"], list)
    assert len(data["by_user"]) > 0
    assert "key" in data["by_user"][0]
    assert "total_cost" in data["by_user"][0]


def test_audit_empty_db():
    """测试空数据库应该给出警告。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "empty.db")
        result = runner.invoke(app, ["audit", "--days", "30", "--db", f"sqlite:///{db_path}"])
        assert result.exit_code == 1
        assert "没有找到消费记录" in result.output


def test_audit_help():
    """测试 audit --help。"""
    result = runner.invoke(app, ["audit", "--help"])
    assert result.exit_code == 0
    assert "审计 Token 消费和浪费模式" in result.output


# ── Optimize CLI 测试 ────────────────────────────────────────


def test_optimize_rich_output():
    """测试 optimize 命令 Rich 输出。"""
    result = runner.invoke(app, ["optimize", "--prompt", "写一个简单的函数"])
    assert result.exit_code == 0
    assert "分析结果" in result.output


def test_optimize_json_output():
    """测试 optimize 命令 JSON 输出（结构化）。"""
    result = runner.invoke(app, ["optimize", "--prompt", "写一个简单的函数", "--format", "json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert "current_strategy" in data
    assert "current_models" in data
    assert "suggestions" in data
    assert "optimized_cost" in data
    assert "warnings" in data
    assert isinstance(data["warnings"], list)
    assert len(data["warnings"]) > 0


def test_optimize_from_file():
    """测试 optimize --context-file 从文件读取。"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("你是一个代码审查助手\nUser: 请检查安全性\n请给出修复方案")
        f.flush()
        result = runner.invoke(app, ["optimize", "--context-file", f.name, "--format", "json"])
    os.unlink(f.name)
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert "input_breakdown" in data


def test_optimize_help():
    """测试 optimize --help。"""
    result = runner.invoke(app, ["optimize", "--help"])
    assert result.exit_code == 0
    assert "Prompt" in result.output or "上下文优化" in result.output


def test_optimize_invalid_model():
    """P2-2: 无效 --model 应该 exit 1。"""
    result = runner.invoke(app, ["optimize", "--prompt", "写一个函数", "--model", "nonexistent"])
    assert result.exit_code == 1
    assert "不存在" in result.output


def test_optimize_invalid_scenario():
    """P3: 无效 --scenario 应该 exit 非 0。"""
    result = runner.invoke(app, ["optimize", "--prompt", "写一个函数", "--scenario", "BAD_SCENARIO"])
    assert result.exit_code != 0


def test_optimize_invalid_format():
    """P3: 无效 --format 应该 exit 非 0。"""
    result = runner.invoke(app, ["optimize", "--prompt", "写一个函数", "--format", "yaml"])
    assert result.exit_code != 0


def test_optimize_invalid_turns():
    """P3: --turns < 1 应该 exit 1。"""
    result = runner.invoke(app, ["optimize", "--prompt", "写一个函数", "--turns", "0"])
    assert result.exit_code == 1
