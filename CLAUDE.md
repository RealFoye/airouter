# CLAUDE.md

## 项目信息

这是 **AI Router**（企业级 AI 模型智能路由与 Token 精细化管控系统），一个为期 4 周的校招考核项目。

## 核心原则

**效果优先，不要害怕浪费 tokens。**

做每一个模块时，先想清楚怎么做效果最好，不要为了省 token 而走捷径。这个项目考核的是系统质量和工程能力，不是 token 消耗量。

## 开发规范

### 做每一块之前先想清楚

- 动手写代码之前，先读设计文档 `docs/system-design.md` 对应章节
- 确认输入/输出 schema、依赖关系、边界条件
- 不确定时问，不要猜
- 宁可多想 5 分钟，不要返工 2 小时

### 测试跟着代码走

- 每个模块写完立即写对应的单元测试，不攒
- 每天结束前跑 `make test-unit`
- 测试不是负担，是防止返工的工具

### 关注时间，但不要赶工

- 这是 4 周项目，时间紧但不是不可能
- 如果某个模块卡住超过预期，先做降级版本，不要死磕
- 降级不等于跳过：先跑通最小版本，后续再增强
- 每周末必须有可演示的检查点

### 代码质量

- 不要过度工程化，MVP 够用就行
- 不要提前优化，先跑通再优化
- 不要添加设计文档里没有的功能
- 类型提示、docstring 只在核心模块加，不要形式主义
- 配置和代码分离：YAML 存配置，Python 存逻辑

### 设计文档是真理来源

- `docs/system-design.md` 是系统设计的唯一权威
- `docs/development-plan.md` 是开发任务清单
- `docs/CHANGELOG-design.md` 是设计变更历史
- 如果发现代码和设计不一致，以设计文档为准，先对齐再写

## 技术栈

- 后端：FastAPI + SQLAlchemy + SQLite
- 前端：Streamlit
- CLI：Typer
- 模型调用：openai SDK（OpenAI 兼容 API）
- 测试：pytest + pytest-asyncio
- 配置：Pydantic Settings + YAML
- 部署：Docker Compose

## 关键路径

1. Week 1：规则版 `analyze` CLI 能跑（不依赖真实模型 API）
2. Week 2：4 个 CLI 命令全部可用
3. Week 3：`docker-compose up` 可演示 Web 平台
4. Week 4：文档 + 打磨 + 答辩，不新增功能

## 降级策略

- 真实模型 API 不可用 → 用 MockAdapter
- FastAPI 开发延期 → Streamlit 直接调用 engine 层
- Benchmark Level 2 失败 → 用 Level 1 离线数据 + Level 3 回测
- 时间不够 → 砍 P2/P3 页面，保 P0+P1
- 上下文工程复杂 → 先做规则版摘要，LLM 摘要推到后面

## 不要做的事

- 不要在没有读设计文档的情况下开始写代码
- 不要跳过测试
- 不要为了赶进度写 hack 代码
- 不要在 Week 4 新增功能
- 不要过度抽象，三个相似行再考虑抽象
- 不要添加设计文档里没有的"改进"
