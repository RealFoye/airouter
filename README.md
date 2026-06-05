# AI Router

企业级 AI 模型智能路由与 Token 精细化管控系统。

## Quick Start

```bash
# 安装
pip install -e ".[dev]"

# 运行单元测试
make test-unit

# 查看 CLI 帮助
ai-router --help
```

## 项目结构

```
src/airouter/    核心代码
data/            YAML 配置 + 测试数据
tests/           单元测试 + 集成测试
docs/            设计文档
web/             Streamlit 前端
```

## 开发

```bash
make lint          # 代码检查
make test-unit     # 单元测试
make test-all      # lint + 全部测试
make dev           # 启动 API 服务
```
