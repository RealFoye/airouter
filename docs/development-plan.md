# AI Router 开发执行计划

> 本文档是可执行的开发任务清单，配合 `docs/system-design.md` 使用。
> 任务按周排列，每周有可演示检查点。每个任务标注 MVP 等级和对应测试。
> 开发过程中如遇阻塞，优先降级而非跳过。

---

## 执行原则

1. **核心链路优先**：路由引擎 + CLI 是所有后续工作的基础，Week 2 结束前必须跑通
2. **每周末有可演示检查点**：不是"做完了多少模块"，而是"能演示什么"
3. **上下文工程拆两周**：Week 2 做 B-1/B-2 核心代码，Week 3 做 B-3 预算管理 + 验证实验
4. **Benchmark 分级落地**：Level 1 在 Week 2 跑通（0 成本），Level 2 在 Week 2 末后台启动，Week 3 收结果 + 跑 Level 3
5. **Week 4 不新增功能**：只交付文档、报告、演示稳定性
6. **audit 是后端能力**：Week 2 以 CLI 形式先跑通，Week 3 Web 看板复用其逻辑
7. **测试跟着开发走**：每个模块写完立即写测试，不攒到检查点前补
8. **Week 1 不等真实模型**：规则版 analyze 不依赖任何 API，MockAdapter 优先

---

## MVP 等级说明

| 标记 | 含义 | 处理方式 |
|------|------|----------|
| **MVP 必做** | 缺少则无法通过 MVP 最小成功标准 | 必须完成，不可降级 |
| **可降级** | 有价值但阻塞时可简化 | 先做最小版本，后续增强 |
| **可选增强** | 锦上添花，不影响核心交付 | 时间充裕时做，否则跳过 |

---

## MVP 最小成功标准（7条）

1. `analyze` / `audit` / `optimize` / `benchmark --level 1` 四个 CLI 命令可运行
2. 输入 20 条不同任务，能输出可解释路由决策（含模型推荐、成本预估、推荐理由）
3. Web 至少能展示路由工作台、消费看板、优化中心、Benchmark 对比（P0+P1 页面）
4. Level 2 至少完成 30 条核心用例中 80% 的实测
5. 回测能输出全程 Tier 1 vs 智能路由的成本/质量对比
6. Docker Compose 可启动 Web 和核心服务
7. 所有演示数据有离线备份，API 不可用时仍能演示

---

## 每周可演示检查点

| 周末 | 检查点 | 一句话演示 |
|------|--------|-----------|
| W1 末 | 规则版 CLI 能跑 | `ai-router analyze "写JWT鉴权"` → 输出模型推荐（基于关键词规则） |
| W2 末 | 完整 CLI 闭环 | `analyze`/`audit`/`optimize`/`benchmark --level 1` 全部可用 |
| W3 末 | Web + 实测数据 | `docker-compose up` → Streamlit 可演示，Level 2/3 有实测数据 |
| W4 末 | 完整交付 | PPT + 手册 + SOP + 预录视频 + 现场演示 |

---

## Week 1：规则版路由闭环（D1-D7）

**目标：`ai-router analyze` 可运行，不依赖真实模型 API**

### Phase 0：项目骨架

| # | 任务 | MVP | 产出文件 | 测试 |
|---|------|-----|----------|------|
| 0.1 | 项目初始化：pyproject.toml、Makefile、目录结构、.gitignore | 必做 | 项目根目录 | — |
| 0.2 | 配置管理：config.py + YAML 加载器（Pydantic Settings） | 必做 | `src/airouter/config.py` | `test_config.py`：验证 YAML 加载、缺字段报错 |
| 0.3 | 编写核心 YAML 配置文件最小版：models.yaml、routing_rules.yaml、budgets.yaml、quality_defaults.yaml | 必做 | `data/*.yaml` | config 测试验证加载 |
| 0.4 | 编写 compression_policy.yaml | 可降级 | `data/compression_policy.yaml` | Week 2 上下文工程时用 |

### Phase 1：数据模型

| # | 任务 | MVP | 产出文件 | 测试 |
|---|------|-----|----------|------|
| 1.1 | 枚举定义：TaskCategory(10)、ComplexityLevel(4)、RiskLevel(3)、SensitivityLevel(3)、VerifiabilityLevel(3)、OutputStrictnessLevel(3)、ContextLevel(4)、ReasoningLevel(4) | 必做 | `src/airouter/models/enums.py` | `test_schemas.py` |
| 1.2 | TaskFeatures（13维特征）+ CAPABILITY_REQUIREMENTS 映射表（10类别×4复杂度=40条） | 必做 | `src/airouter/models/schemas.py` | 验证映射表完整性 |
| 1.3 | ModelConfig / RoutingDecision / ExecutionFeedback / BenchmarkResult / ConfigSnapshot Pydantic schemas | 必做 | `src/airouter/models/schemas.py` | 验证 schema 序列化 |
| 1.4 | ModelRegistry：从 models.yaml 加载 → ModelConfig 列表 | 必做 | `src/airouter/models/model_registry.py` | 验证加载 5 个模型 |

### Phase 2A：最小路由闭环

| # | 任务 | MVP | 产出文件 | 测试 |
|---|------|-----|----------|------|
| 2.1 | **关键词 TaskAnalyzer**：KEYWORD_RULES 匹配类别 + 规则推断复杂度/风险/推理强度/上下文需求 | 必做 | `src/airouter/engine/router/analyzer.py` | `test_analyzer.py`：20 条任务分类正确 |
| 2.4 | **基础 CostEstimator**：基础成本计算（input×price + output×price）+ 缓存调整层（可先简化） | 必做 | `src/airouter/engine/router/estimator.py` | `test_estimator.py`：成本计算准确 |
| 2.5 | **硬约束过滤**：capability_score + allowed_tiers + 上下文窗口 + 敏感性 + 预算两层（soft/hard） | 必做 | `src/airouter/engine/router/selector.py` | `test_selector.py`：过滤逻辑正确 |
| 2.7 | **单模型评分**：4 维权重 + 3 种成本归一化（linear/sqrt/log）+ 质量先验 + 延迟估计 | 必做 | 同上 | 验证评分排序合理 |
| 2.9 | **Router facade 最小版**：Analyzer → Selector → Estimator 串联 | 必做 | `src/airouter/engine/router/router.py` | `test_router.py`：端到端 20 条 |

### Phase 7（部分）：CLI 入口

| # | 任务 | MVP | 产出文件 | 测试 |
|---|------|-----|----------|------|
| 7.1 | **`ai-router analyze`** CLI（规则版）：Typer 入口 + analyze 子命令 | 必做 | `src/airouter/cli/main.py` + `analyze.py` | `test_cli.py`：CLI 输出格式 |

### 文档

| # | 任务 | MVP | 产出文件 |
|---|------|-----|----------|
| — | 建 docs/best-practices.md 空壳 + 9 章大纲 | 必做 | `docs/best-practices.md` |
| — | 建 docs/sop/ 目录 + 5 个 SOP 文件名 | 必做 | `docs/sop/` |

### Week 1 检查点

```bash
# 规则版 analyze 可运行
ai-router analyze "写一个FastAPI JWT鉴权中间件"
# 预期输出：任务类型/复杂度/风险/推荐模型/成本预估/推荐理由/替代方案

# 测试全部通过
make test-unit
```

### Week 1 交付物

- 可运行的规则版 CLI
- 系统设计文档
- 核心配置文件
- 核心模块单元测试

---

## Week 2：完整路由引擎 + CLI 四命令（D8-D14）

**目标：4 个 CLI 全部可用**

### Phase 3：模型适配器（✅ 已完成 2026-06-05）

| # | 任务 | MVP | 产出文件 | 测试 |
|---|------|-----|----------|------|
| 3.1 | BaseAdapter 抽象接口（4 类异常层次 + achat via to_thread） | 必做 | `src/airouter/adapters/base.py` | `test_adapters.py`（33 tests） |
| 3.3 | **MockAdapter**（hash-based 确定性延迟，测试用） | 必做 | `src/airouter/adapters/mock.py` | 验证稳定返回 |
| 3.2 | OpenAI 兼容适配器（client 注入 + 错误映射 + empty choices 防御） | 必做 | `src/airouter/adapters/openai_compat.py` | 连通性测试（5 个模型） |

### Phase 2B：策略增强（✅ 已完成 2026-06-06）

| # | 任务 | MVP | 产出文件 | 测试 |
|---|------|-----|----------|------|
| 2.3 | StrategyClassifier：从 TaskFeatures 确定策略触发条件（Plan-Execute 5 结构条件、Guided 4 结构条件、PER = base_decomposable AND review_need） | 必做 | `src/airouter/engine/router/classifier.py` | `test_classifier.py`（34 tests） |
| 2.6 | **策略候选生成**：SINGLE / GUIDED / PLAN_EXECUTE / PLAN_EXECUTE_REVIEW（角色池 + Top-K + 组合遍历 + post-filter，成本预估不真实执行多模型调用链） | 必做 | `selector.py` 扩展 | `test_strategies.py`（26 tests） |
| 2.8 | **管控门禁**：独立 Gate 模块 + 预算检查 + 人工审核触发（7 条件）+ 质量门禁 + Fallback | 必做 | `gate.py` | `test_gate.py`（22 tests） |

### Phase 2C：LLM 增强

| # | 任务 | MVP | 产出文件 | 测试 |
|---|------|-----|----------|------|
| 2.2 | LLM TaskAnalyzer（调用 Tier 1 提取结构化特征 JSON，关键词模式作为 fallback） | 可选增强 | `analyzer.py` 扩展 | 真实 API 可用时测 |

### Phase 1（续）：数据库（✅ 已完成 2026-06-06）

| # | 任务 | MVP | 产出文件 | 测试 |
|---|------|-----|----------|------|
| 1.5 | SQLAlchemy DB models：4 张表（routing_decisions / execution_feedback / benchmark_results / config_snapshots） | 必做 | `src/airouter/models/db_models.py` | `test_db.py`（13 tests） |
| 1.6 | DB 初始化 + session 管理 | 必做 | `src/airouter/models/database.py` | 同上 |

### Phase 4：审计引擎（✅ 已完成 2026-06-06）

| # | 任务 | MVP | 产出文件 | 测试 |
|---|------|-----|----------|------|
| 4.1a | **轻量种子数据**：200 条模拟消费记录，快速测试 audit 逻辑 | 必做 | `scripts/generate_seed_data.py` | 验证数据可写入 DB |
| 4.1b | 完整种子数据：6000 条（30天×200条，8 用户/5 项目/5 客户端/浪费模式注入） | 必做 | 同上 | 同上 |
| 4.2 | Collector：Token 采集（从 routing_decisions + execution_feedback 聚合） | 必做 | `src/airouter/engine/audit/collector.py` | `test_audit.py` |
| 4.3 | Aggregator：多维聚合（按用户/项目/模型/任务类型/部门/时间） | 必做 | `src/airouter/engine/audit/aggregator.py` | 同上 |
| 4.4 | **Detector：5 类浪费模式检测**（高配滥用 / 重复调用 / 过长上下文 / 可降级未降级 / 缓存未命中） | 必做 | `src/airouter/engine/audit/detector.py` | 验证 5 类模式可识别 |
| 4.5 | Attribution：消费归因分析 | 必做 | `src/airouter/engine/audit/attribution.py` | 同上 |

### Phase 7（续）：CLI audit（✅ 已完成 2026-06-06）

| # | 任务 | MVP | 产出文件 | 测试 |
|---|------|-----|----------|------|
| 7.2 | **`ai-router audit`**：消费归因 + 浪费模式 Top N + 优化建议 | 必做 | `src/airouter/cli/audit.py` | `test_audit.py`（19 tests） |

### Phase 5（部分）：上下文工程 B-1/B-2（✅ 已完成 2026-06-08）

| # | 任务 | MVP | 产出文件 | 测试 |
|---|------|-----|----------|------|
| 5.1 | B-1 上下文优先级框架（System Prompt > 任务描述 > 相关文件 > 历史对话） | 必做 | `src/airouter/engine/context/priority.py` | `test_context_optimizer.py`（57 tests） |
| 5.2 | B-2 压缩引擎：冗余剔除 + 截断 + 规则摘要化（6 种上下文类型×结构化规则） | 必做 | `src/airouter/engine/context/compressor.py` | 同上 |
| 5.3 | B-2 压缩策略分级（Conservative/Standard/Aggressive × risk_level 绑定）+ 分层目标 | 必做 | 同上 | 同上 |

### Phase 7（续）：CLI optimize（✅ 已完成 2026-06-08）

| # | 任务 | MVP | 产出文件 | 测试 |
|---|------|-----|----------|------|
| 7.3 | **`ai-router optimize`**：上下文优化建议 + 压缩前后 Token 估算 + 3 策略对比 | 必做 | `src/airouter/cli/optimize.py` | `test_cli.py` |

### Phase 6（部分）：Benchmark Level 1 ✅ 2026-06-08

| # | 任务 | MVP | 产出文件 | 测试 |
|---|------|-----|----------|------|
| 6.1a | ~~Level 1 规则样例：先写 30 条（覆盖 10 类别×4 复杂度）~~ ✅ | 必做 | `data/benchmarks/level1/router_cases.yaml`（40 条 YAML） | — |
| 6.2 | ~~Level 1 runner：规则分类准确率 + Tier 推荐准确率（0 API 成本）~~ ✅ | 必做 | `src/airouter/engine/benchmark/runner.py` | `test_benchmark.py`（34 tests） |

### Phase 7（续）：CLI benchmark ✅ 2026-06-08

| # | 任务 | MVP | 产出文件 | 测试 |
|---|------|-----|----------|------|
| 7.4 | ~~**`ai-router benchmark --level 1`**（支持 `--resume`）~~ ✅ | 必做 | `src/airouter/cli/benchmark.py` | `test_benchmark_level1.py`（13 tests） |

### D14：后台启动 Level 2

| # | 任务 | MVP | 产出文件 | 测试 |
|---|------|-----|----------|------|
| — | `ai-router benchmark --level 2 --resume` 后台启动（支持断点续跑/失败重试/限速） | 必做 | — | 验证启动成功 |

### Week 2 降级预案

- 摘要化简化为规则版（保留首尾 + 关键行），真 LLM 摘要推到 Week 3 增强
- SQLite 先写 routing_decisions + config_snapshots，execution_feedback / benchmark_results 可 Week 3 补
- Plan-Execute 先支持成本预估，不真实执行多模型调用链

### Week 2 检查点

```bash
# 四个 CLI 命令全部可用
ai-router analyze "重构用户登录模块，支持OAuth2和MFA"
ai-router audit --days 30
ai-router optimize --context-file context.txt
ai-router benchmark --level 1

# 测试全部通过
make test-unit
```

### Week 2 交付物

- 完整路由引擎（4 策略 + 管控门禁）
- 4 个 CLI 命令
- 上下文工程 B-1/B-2
- Level 1 Benchmark
- SQLite DB + 种子数据
- 模型适配器（Mock + OpenAI 兼容）

---

## Week 3：Web 平台 + Benchmark 收尾 + 上下文工程验证（D15-D21）

**目标：`docker-compose up` 可演示**

### Phase 6（续）：Benchmark 完整

| # | 任务 | MVP | 产出文件 | 测试 |
|---|------|-----|----------|------|
| 6.1b | Level 1 样例扩充到 100 条 | 必做 | `data/benchmark_cases/*.json` | — |
| 6.1c | Level 2 核心实测用例 30 条（高质量，有评分规则和自动评分线索） **部分完成：30条YAML case已就绪** | 必做 | `data/benchmarks/level2/router_quality_cases.yaml` | ✅ 2026-06-08 |
| 6.3 | Level 2 runner：真实调用 3 模型 + --resume + 失败重试 + 限速 **部分完成：auto-score MVP，LLM-as-Judge 待 Week 3** | 必做 | `runner.py` Level2BenchmarkRunner | ✅ 2026-06-08（47 unit + 8 integration） |
| 6.4 | Evaluator：auto-score 评分（结构完整性 + 语法正确性 + 关键词匹配） **部分完成：6 类评分函数，LLM-as-Judge 待 Week 3** | 必做 | `src/airouter/engine/benchmark/evaluator.py` | ✅ 2026-06-08 |
| 6.5 | Level 3 策略回测：全程 Tier 1 vs 智能路由（成本/质量对比报告） | 必做 | `src/airouter/engine/benchmark/reporter.py` | 验证对比报告生成 |
| 6.6 | Context Rot 验证实验：3 模型×3 长度×3 任务=27 次调用 + 退化曲线 | 可降级 | `scripts/context_budget_experiment.py` | 验证退化趋势数据 |

### Phase 8：Web 平台

> **降级方案：** 若 FastAPI 接口延期，Streamlit 可直接调用 engine/service 层（不经过 HTTP），保证演示链路不受前后端分离影响。

| # | 任务 | MVP | 产出文件 | 测试 |
|---|------|-----|----------|------|
| 8.1 | FastAPI app + 路由（/api/route /audit /benchmark /models /rules）+ 中间件 | 可降级 | `src/airouter/api/` | `test_api.py` |
| 8.2 | Streamlit 主页 + 路由工作台（P0）：输入→推荐→成本对比→评分雷达图 | 必做 | `web/app.py` + `web/pages/1_route_workbench.py` | 手动 smoke |
| 8.3 | Streamlit 消费看板（P0）：趋势图 + 多维下钻 + 预算预警 | 必做 | `web/pages/2_consumption_dashboard.py` | 手动 smoke |
| 8.4 | Streamlit 优化中心（P1）：浪费 Top N + 建议列表 + 导出 + 配置草案 | 必做 | `web/pages/3_optimization_center.py` | 手动 smoke |
| 8.5 | Streamlit Benchmark 结果（P0）：热力图 + L1/L2/L3 结果展示 | 必做 | `web/pages/5_benchmark_results.py` | 手动 smoke |
| 8.6 | Streamlit 规则管理（P2）：只读 5 tab（权重/阈值/tiers/预算/质量门禁） | 可降级 | `web/pages/4_rule_management.py` | 手动 smoke |
| 8.7 | Streamlit 上下文工程验证（P3）：静态图表展示退化趋势 | 可选增强 | `web/pages/6_context_budget_study.py` | 手动 smoke |

### Phase 5（续）：上下文工程 B-3

| # | 任务 | MVP | 产出文件 | 测试 |
|---|------|-----|----------|------|
| 5.4 | B-3 上下文预算管理：按任务类型设 Token 上限 + 超限自动裁剪（基于 L2 实测数据定规则） | 必做 | `src/airouter/engine/context/budget.py` | `test_context.py` |
| 5.5 | 三层质量保障闭环（离线验证→运行时检查→反馈闭环） | 可降级 | `src/airouter/engine/context/quality.py` | 先做运行时轻量检查 |

### Phase 9：部署与集成测试

| # | 任务 | MVP | 产出文件 | 测试 |
|---|------|-----|----------|------|
| 9.1 | Dockerfile + Dockerfile.web + docker-compose.yml | 必做 | 项目根目录 | `docker-compose up` |
| 9.3 | 集成测试（CLI + API + DB 端到端） | 必做 | `tests/integration/` | `make test-integration` |

### D21：预录备份视频

| # | 任务 | MVP | 产出 |
|---|------|-----|------|
| — | 预录第一版系统演示备份视频（防止 Week 4 系统临时故障） | 必做 | mp4 文件 |

### Week 3 检查点

```bash
# Docker 一键启动
docker-compose up
# → localhost:8501 可演示：路由推荐 → 消费看板 → 优化建议 → Benchmark 对比 → 规则配置

# 集成测试通过
make test-integration
```

### Week 3 交付物

- 可部署 Web 平台（P0+P1 页面）
- Benchmark 完整数据（L1+L2+L3）
- Context Rot 验证数据
- Docker Compose
- 预录备份视频

---

## Week 4：文档 + 打磨 + 答辩（D22-D28）

> **原则：不新增功能，只做交付物、报告、演示稳定性。**

### Phase 10：文档与答辩

| # | 任务 | MVP | 产出文件 | 时间 |
|---|------|-----|----------|------|
| 10.1 | 系统设计文档最终一致性检查（架构/算法/数据流/Schema 一致性） | 必做 | `docs/system-design.md` | D22 |
| 10.2 | Token 优化最佳实践手册（9 章，含 Benchmark 实测数据） | 必做 | `docs/best-practices.md` | D23 |
| 10.3 | 企业 Token 管控 SOP（5 个：开通/使用/复盘/迭代/汇报） | 必做 | `docs/sop/` | D24 |
| 10.4 | 答辩 PPT + 演示脚本 + Q&A 准备 | 必做 | `docs/presentation/` | D26 |
| 10.5 | 录制最终答辩版视频 | 必做 | mp4 | D27 |

### 打磨与修复

| # | 任务 | MVP | 时间 |
|---|------|-----|------|
| — | Benchmark 报告 / 回测报告 / 优化报告整理 | 必做 | D25 |
| — | 系统 Bug 修复（缓冲日） | 必做 | D25 |
| — | 演示彩排 + 修复演示中发现的问题 | 必做 | D27 |
| — | 备用数据准备 + CLI 输出美化 | 必做 | D27 |
| — | 最终 Review + 答辩 | 必做 | D28 |

### Week 4 交付物

- 最佳实践手册（9 章，含实测数据）
- 企业 Token 管控 SOP（5 个）
- 答辩 PPT
- 预录视频（最终版）
- 最终系统

---

## 测试策略

### 测试节奏

```
每完成一个模块 → 跑对应 unit test
每天结束前     → make test-unit
每周末检查点前 → make test-all（Week 3 起）
```

### 各阶段必跑测试

| 阶段 | 必跑测试 | 验证点 |
|------|----------|--------|
| Phase 0 配置 | `pytest tests/unit/test_config.py` | YAML 能加载、缺字段报错 |
| Phase 1 模型 | `pytest tests/unit/test_schemas.py` | Pydantic schema、枚举、DB 表创建 |
| Phase 2 路由 | `pytest tests/unit/test_router.py` | 20 条任务路由结果符合预期 |
| Phase 3 Adapter | `pytest tests/unit/test_adapters.py` | MockAdapter 稳定返回 |
| Phase 4 Audit | `pytest tests/unit/test_audit.py` | 5 类浪费模式能被识别 |
| Phase 5 Context | `pytest tests/unit/test_context_optimizer.py` | 3 种压缩策略 token 数下降且保留关键内容 |
| Phase 6 Benchmark | `pytest tests/integration/test_benchmark_level1.py` | Level 1 能跑完并生成报告 |
| Phase 7 CLI | `pytest tests/integration/test_cli.py` | Typer runner 测 4 个命令 |
| Phase 8 Web/API | `pytest tests/integration/test_api.py` | 至少测 /api/route、/api/audit |
| Phase 9 Docker | `docker-compose up + smoke test` | 全部服务启动 |
| Phase 10 文档 | 手动 checklist | 一致性、完整性 |

### Makefile 命令

```makefile
test-unit:        pytest tests/unit/ -v --cov=src/airouter --cov-report=term-missing
test-integration: pytest tests/integration/ -v
test-cli:         pytest tests/integration/test_cli.py -v
smoke:            docker-compose up --build && curl health checks
lint:             ruff check src/ tests/ && mypy src/
test-all:         lint && test-unit && test-integration
```

---

## 开发顺序总览

```
Week 1:  0.1→0.3 → 1.1→1.4 → 2.1→2.4→2.5→2.7→2.9 → 7.1 → 检查点
Week 2:  3.1→3.3→3.2 → 2.3→2.6→2.8 → (2.2可选) → 1.5→1.6
         → 4.1a→4.1b→4.2→4.3→4.4→4.5 → 7.2
         → 5.1→5.2→5.3 → 7.3
         → 6.1a→6.2 → 7.4 → Level 2 后台启动 → 检查点
Week 3:  6.1b→6.1c→6.3→6.4→6.5→6.6
         → 8.1→8.2→8.3→8.4→8.5→(8.6)→(8.7)
         → 5.4→5.5 → 9.1→9.3 → 备份视频 → 检查点
Week 4:  10.1→10.2→10.3→10.4→10.5 → Bug fix → 彩排 → 答辩
```

---

## 关键风险与应对

| 风险 | 应对 |
|------|------|
| 模型 API 限流 | Benchmark 分批跑、指数退避、结果缓存 |
| 模型间质量差异小 | 强调成本和延迟差异，用性价比作为主指标 |
| Context Rot 难以复现 | 聚焦 5K-50K 区间，用人工 context padding |
| 4 周时间紧 | 核心链路（路由+CLI）必须完成，Web 和 Benchmark 可简化 |
| Demo 现场失败 | 预录备份视频、预缓存 Benchmark 结果 |
| FastAPI 开发延期 | Streamlit 直接调用 engine 层，不经过 HTTP |
| 种子数据生成慢 | 先 200 条轻量版验证逻辑，再扩 6000 条 |

---

## 文件清单

### 配置文件

```
data/models.yaml                    # 模型注册表和定价
data/routing_rules.yaml             # 路由规则（权重、阈值、allowed_tiers）
data/budgets.yaml                   # 预算配置（项目/任务类型）
data/quality_defaults.yaml          # 质量先验值 + 严重错误率
data/compression_policy.yaml        # 压缩策略分级 + 质量阈值 + 分层目标
```

### 源代码

```
src/airouter/
├── config.py                       # 配置管理
├── models/
│   ├── enums.py                    # 枚举定义
│   ├── schemas.py                  # Pydantic schemas
│   ├── model_registry.py           # 模型注册表加载器
│   ├── db_models.py                # SQLAlchemy DB models
│   └── database.py                 # DB 初始化 + session
├── engine/
│   ├── router/
│   │   ├── analyzer.py             # 任务特征提取（关键词 + LLM 双模式）
│   │   ├── classifier.py           # 策略触发条件
│   │   ├── selector.py             # 硬约束过滤 + 评分（含候选级预算标签）
│   │   ├── estimator.py            # 成本预估（3 层）
│   │   ├── gate.py                 # 管控门禁（人工审核 + 质量门禁的唯一决定者）
│   │   └── router.py               # Router facade
│   ├── audit/
│   │   ├── collector.py            # Token 采集
│   │   ├── aggregator.py           # 多维聚合
│   │   ├── detector.py             # 浪费模式检测（5 类）
│   │   └── attribution.py          # 消费归因
│   ├── context/
│   │   ├── priority.py             # B-1 优先级框架
│   │   ├── compressor.py           # B-2 压缩引擎 + 策略分级
│   │   ├── budget.py               # B-3 上下文预算管理
│   │   └── quality.py              # 三层质量保障
│   └── benchmark/
│       ├── runner.py               # L1/L2 runner
│       ├── evaluator.py            # 混合评分
│       └── reporter.py             # L3 回测报告
├── api/                            # FastAPI 路由
│   ├── app.py
│   └── routes/
│       ├── router.py               # /api/route/*
│       ├── audit.py                # /api/audit/*
│       ├── benchmark.py            # /api/benchmark/*
│       ├── models.py               # /api/models/*
│       ├── rules.py                # /api/rules/*
│       └── dashboard.py            # /api/dashboard/*
├── cli/                            # CLI 工具
│   ├── main.py                     # Typer 入口
│   ├── analyze.py                  # ai-router analyze
│   ├── audit.py                    # ai-router audit
│   ├── optimize.py                 # ai-router optimize
│   └── benchmark.py                # ai-router benchmark
└── adapters/                       # 模型适配器
    ├── base.py                     # 抽象接口
    ├── openai_compat.py            # OpenAI 兼容适配器
    └── mock.py                     # Mock 适配器
```

### Web 前端

```
web/
├── app.py                          # Streamlit 主页
└── pages/
    ├── 1_route_workbench.py        # 路由工作台（P0）
    ├── 2_consumption_dashboard.py  # 消费看板（P0）
    ├── 3_optimization_center.py    # 优化中心（P1）
    ├── 4_rule_management.py        # 规则管理（P2）
    ├── 5_benchmark_results.py      # Benchmark 结果（P0）
    └── 6_context_budget_study.py   # 上下文工程验证（P3）
```

### 测试数据

```
data/benchmark_cases/
├── code_generation.json            # 20 条
├── code_review.json                # 20 条
├── bug_analysis.json               # 20 条
├── refactoring.json                # 20 条
├── documentation.json              # 20 条
└── architecture.json               # 10 条
```

### 测试

```
tests/
├── conftest.py                     # 共享 fixtures
├── unit/                           # 单元测试
│   ├── test_config.py
│   ├── test_schemas.py
│   ├── test_analyzer.py
│   ├── test_estimator.py
│   ├── test_selector.py
│   ├── test_classifier.py
│   ├── test_strategies.py
│   ├── test_router.py
│   ├── test_gate.py
│   ├── test_adapters.py
│   ├── test_audit.py
│   ├── test_context_optimizer.py
│   ├── test_evaluator.py
│   ├── test_benchmark.py
│   └── test_db.py
└── integration/                    # 集成测试
    ├── test_cli.py
    ├── test_api.py
    └── test_benchmark_level1.py
```

### 部署

```
Dockerfile                          # 后端服务
Dockerfile.web                      # Streamlit 前端
docker-compose.yml                  # 一键启动
```
