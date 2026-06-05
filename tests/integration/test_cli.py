"""测试 CLI analyze 命令。"""

import json

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
