# AirRouter 当前项目状态交接说明

本文档给没有上下文的新 agent 使用，目的是说明 AirRouter 当前真实状态：哪些是主线产品能力，哪些是 benchmark / 研究验证能力，哪些只是计划或文档占位。

如果与早期设计文档、开发计划或历史 changelog 口径不一致，以本文档和当前代码为准。

## 1. 一句话定位

AirRouter 当前是一个企业 AI 模型路由与治理 MVP。

核心价值不是“做一个通用聊天机器人”，而是：

1. 先分析用户任务。
2. 判断任务类型、复杂度、风险、可验证性和成本敏感性。
3. 推荐合适的模型和执行策略。
4. 必要时让 Judge 模型复核推荐。
5. 用户确认后再调用真实模型执行。
6. 用 benchmark 和回放结果持续校准路由策略。

当前最重要的可演示主线是：

- Web 工作台：`web/app.py`
- 路由引擎：`src/airouter/engine/router/`
- 模型配置：`data/models.yaml`
- OpenSquilla 复杂度增强：`src/airouter/engine/complexity/`
- Benchmark 证据链：`src/airouter/engine/benchmark/`

## 2. 当前主线产品能力

### 2.1 Router 引擎

核心文件：

- `src/airouter/engine/router/router.py`
- `src/airouter/engine/router/analyzer.py`
- `src/airouter/engine/router/classifier.py`
- `src/airouter/engine/router/selector.py`
- `src/airouter/engine/router/estimator.py`
- `src/airouter/engine/router/gate.py`
- `src/airouter/models/schemas.py`
- `src/airouter/models/enums.py`

真实流程：

```text
TaskAnalyzer / ComplexityAnalyzer
→ TaskFeatures
→ StrategyClassifier
→ ModelSelector
→ CostEstimator
→ RoutingGate
→ RoutingDecision
```

`TaskFeatures` 是当前 Router 的核心任务画像，包含 13 个主要字段：

- `category`
- `complexity`
- `risk_level`
- `sensitivity`
- `verifiability`
- `output_strictness`
- `context_requirement`
- `reasoning_intensity`
- `estimated_input_tokens`
- `estimated_output_tokens`
- `subtasks`
- `required_capabilities`
- `preferred_capabilities`

当前策略枚举是 4 种：

- `SINGLE_MODEL`
- `GUIDED_EXECUTE`
- `PLAN_EXECUTE`
- `PLAN_EXECUTE_REVIEW`

注意：

- Router 是项目主线能力。
- Router 本身不等于 Benchmark。
- Router 生成的是推荐决策，不直接代表模型一定能完成任务。

### 2.2 OpenSquilla 复杂度增强

核心文件：

- `src/airouter/engine/complexity/analyzer.py`
- `src/airouter/engine/complexity/ml_backend.py`
- `src/airouter/engine/complexity/types.py`
- `docs/opensquilla-router-calibration-report.md`
- `docs/system-design-ml-complexity-extension.md`
- `docs/opensquilla-router-provenance.md`

支持模式：

- `rules`
- `shadow`
- `opensquilla`
- `hybrid`

当前结论：

- OpenSquilla 可用，并且真实 ML bundle 推理验证通过。
- 它的价值主要是降低欠路由，尤其是高风险任务被低估的问题。
- 它不是对 rules 的全局无脑替代。
- `ml_raw` / `ml_final` 对 AirRouter 标签存在领域偏移，容易偏保守或过度升级。
- Web 工作台当前优先使用 `opensquilla` / `ml_final` 做用户可见分析；失败时回退 rules。

必须避免的误读：

- 不能说 OpenSquilla 已经证明“总体一定比规则更好”。
- 不能把 70 条复杂度标签校准当成最终路由质量证明。
- 真正的路由效果要看真实模型输出、成本、风险和成功率。

### 2.3 模型注册表

核心文件：

- `data/models.yaml`
- `src/airouter/models/model_registry.py`

当前可调用模型为 7 个：

- `qwen3.7-max`
- `deepseek-v4-pro`
- `kimi-k2.6`
- `qwen3.7-plus`
- `MiniMax-M3`
- `glm-5.1`
- `deepseek-v4-flash`

当前已删除：

- `claude-sonnet-4-6`

原因：

- 当前 API 侧不可用。
- 留在可执行配置中会误导前端和 Judge 默认配置。

价格状态：

- `qwen3.7-max`
- `qwen3.7-plus`
- `deepseek-v4-pro`
- `deepseek-v4-flash`
- `glm-5.1`

上述模型价格经过 CCH 历史账单校准。

- `kimi-k2.6`
- `MiniMax-M3`

这两个仍是临时估算价，需要后续导出 CCH usage CSV 对账。

## 3. Web 当前状态

详细文档：

- `docs/web-workbench-handoff.md`

核心文件：

- `web/app.py`
- `src/airouter/web/ui.py`
- `src/airouter/web/data.py`
- `web/pages/*.py`

当前 Web 是 Streamlit MVP，不是最终生产级前端。

已补充附件能力：

- 普通文本任务仍走 Web 的 OpenSquilla / Router 分析。
- 用户可上传图片、CSV/TSV、Excel、PDF、代码、日志和文本附件。
- CSV/TSV、Excel、PDF、文本会尽量提取正文并注入分析与执行上下文。
- 图片附件走独立 `image_model` 路径，执行模型固定为 `qwen3.7-plus`。
- `qwen3.7-plus` 在 `data/models.yaml` 中已标注 `multimodal` / `vision` capability。
- PDF 正文提取依赖 `pypdf`；Excel 读取依赖 `openpyxl`。

已完成：

- API Key 登录。
- 普通用户 Chat 工作台。
- 先分析，再执行。
- OpenSquilla ml_final + Router 推荐。
- MiniMax-M3 / qwen3.7-max 深度复核。
- 用户确认后真实调用模型。
- 流式输出。
- Markdown 渲染。
- 执行中切换模型并保留上下文。
- 长上下文自动压缩。
- 左侧历史对话。
- 大模型生成短对话标题。
- 管理员页面折叠入口。

当前已知限制：

- `runs/web/conversations.json` 是本地 JSON 文件，没有并发写锁。
- 登录只有 API Key，没有正式账号、权限、团队隔离。
- streaming 路径为了流式体验直接使用 OpenAI client，没有走统一 `BaseAdapter.chat()`。
- streaming 的 token / cost 是估算，不是 provider usage 精确值。
- “更省钱”“更稳妥”按钮目前仍有硬编码模型名，后续应改成从模型目录和 benchmark 表动态选择。
- Web 层测试还偏少，主要是 `src/airouter/web/data.py` 有测试，`web/app.py` 本身缺少完整交互测试。

不要误读：

- Web 的管理员页不是主产品体验，只是保留治理查看能力。
- Web 当前重点是演示 AirRouter 的用户流程，不是完成生产级多用户平台。

## 4. Benchmark 与研究验证能力

Benchmark 是项目证据链，不是生产请求路径。

### 4.1 Level 1 / Level 2 / Level 3

核心文件：

- `src/airouter/engine/benchmark/runner.py`
- `src/airouter/engine/benchmark/evaluator.py`
- `src/airouter/engine/benchmark/llm_judge_v2.py`
- `src/airouter/engine/benchmark/pairwise_judge.py`
- `src/airouter/engine/benchmark/l2_report.py`

定位：

- Level 1：规则链路离线验证。
- Level 2：真实模型输出 + 自动评分 + LLM Judge。
- Level 3：策略回测。

注意：

- 这些是评测框架，不是 Web 用户每次请求都会走的路径。
- 历史运行结果可作为策略和报告依据，但不能和实时生产质量混为一谈。

### 4.2 Finance Benchmark

核心文件：

- `src/airouter/engine/benchmark/finance_*.py`
- `docs/model-selection-report.md`

定位：

- 企业财务场景样板。
- 证明“业务案例 + 规则评分 + Judge 审计 + 成本对账 + 错误归因”的方法可行。

注意：

- Finance 排名不能直接推广成所有部门的模型排名。
- Finance 的可复用价值是方法论，不是某个模型在财务题上的绝对排名。

### 4.3 Routing Ground Truth Benchmark

核心文件：

- `src/airouter/engine/benchmark/ground_truth_*.py`
- `src/airouter/engine/benchmark/oracle_generator.py`
- `src/airouter/engine/benchmark/strategy_replay.py`
- `data/benchmarks/routing_ground_truth/`

定位：

- 通过真实模型输出生成 Oracle。
- 回放不同路由策略，比较是否选中“足够便宜且能完成任务”的模型。
- 用于判断 rules、ml_raw、ml_final、hybrid 等策略到底是不是改善了真实任务质量/成本。

当前数据口径：

- Dev / Engineering：30 cases。
- Holdout / General：60 cases。
- 候选模型：5 个候选模型参与主要全量评测。
- 完整运行过 450 pair + Judge 的正式报告链路。

注意：

- “Oracle” 在这里不是数据库，而是 benchmark 中根据模型真实输出生成的路由真值。
- Oracle 是评测术语：某任务最便宜的 passing model / 是否需要 HUMAN。
- Oracle 不是线上数据库，也不是生产服务。

### 4.4 Sandbox

核心文件：

- `src/airouter/engine/benchmark/sandbox.py`
- `infra/sandbox/Dockerfile`

定位：

- 只服务于 Benchmark 中的代码修复验证。
- 用于 pre-patch / post-patch 测试，防止模型靠文本解释冒充代码修复。

注意：

- Sandbox 不是主 Router 的生产执行环境。
- 如果 Docker daemon 未启动或镜像未构建，CODE_DEBUG 类评测不可信。
- 不能简单说“容器沙箱安全加固到位”就代表所有代码任务都已生产级安全执行。

## 5. CLI 当前状态

入口：

- `src/airouter/cli/main.py`

命令：

- `ai-router analyze`
- `ai-router audit`
- `ai-router optimize`
- `ai-router benchmark`

注意：

- CLI 是后端能力演示和评测工具。
- `benchmark.py` 很大，承担多个 level 的命令分发，后续可以拆，但目前不是 Web 收尾的最高优先级。

## 6. 文档当前状态

重要文档：

- `docs/system-design.md`：早期权威系统设计，内容很全，但部分 Web / OpenSquilla / Benchmark 最新状态滞后。
- `docs/web-workbench-handoff.md`：当前 Web 工作台最新交接文档。
- `docs/opensquilla-router-calibration-report.md`：OpenSquilla 校准结果。
- `docs/department-benchmark-framework.md`：跨部门 benchmark 方法论。
- `docs/engineering-benchmark-design.md`：工程 benchmark 设计说明。
- `docs/model-selection-report.md`：模型选择与 Finance 相关报告。
- `docs/CHANGELOG-design.md`：历史变更日志，很长，不适合作为新 agent 第一入口。

明确文档缺口：

- `docs/best-practices.md` 目前仍是 9 章空壳。
- `docs/sop/*.md` 目前仍是 SOP 占位。
- 根目录缺少 `docker-compose.yml`。
- `docs/system-design.md` 中部分 Week 3 / Week 4 计划项没有完全同步当前真实实现。

这些缺口是真实存在的，但它们不是当前 Web 演示主线的阻塞项。

## 7. 对外部 agent 总结的校正

### 7.1 基本正确的部分

以下判断大体正确：

- Router 的职责分离比较清楚。
- 当前任务画像确实以 13 个 `TaskFeatures` 字段为核心。
- 当前有 7 个可调用模型和 3 个 tier。
- OpenSquilla 接入支持 rules / shadow / opensquilla / hybrid。
- Web 仍是 MVP，有本地 JSON、并发写、成本估算、硬编码按钮等问题。
- best-practices、SOP、docker-compose 确实还没收口。
- kimi-k2.6 和 MiniMax-M3 价格还没有 CCH 对账。

### 7.2 需要纠正或收敛的部分

以下说法需要修正：

1. **不要把 Benchmark 系统说成生产能力。**

   Finance、Ground Truth、Judge、Oracle、Sandbox 是评测和证据链，不是普通用户每次请求都会走的线上生产路径。

2. **不要说 Sandbox 已经让工程执行生产级安全。**

   Sandbox 是 Benchmark 的验证环境；Docker 不可用时 CODE_DEBUG 评测就不完整。

3. **不要说 adapter 层几乎没测试。**

   `tests/unit/test_adapters.py` 和 `tests/unit/test_executor.py` 都覆盖了 adapter / executor 的关键行为。更准确的说法是：Web streaming 这条路径绕过了统一 adapter 接口，缺少单独测试。

4. **不要把 OpenSquilla 说成“明显更好，可以替代 rules”。**

   当前结论是：OpenSquilla 可降低欠路由，但可能增加过度路由和成本；更适合作为增强信号或 Web 分析默认，而不是全局生产替代。

5. **不要把文档计划项当成当前交付项。**

   `development-plan.md` 和 `system-design.md` 有早期计划，包括 docker-compose、SOP、最佳实践手册。是否完成要看当前文件内容和代码，而不是计划表。

6. **不要把 Web 的问题上升为整个项目不可用。**

   Web 是 MVP，确实有改进点；但 Router、benchmark、OpenSquilla、CLI 是独立层，不应因为 Web 状态管理问题否定整个引擎层。

## 8. 当前优先级建议

现在不建议继续扩展新 benchmark 或新部门。

优先级应该是：

1. 收口 Web 演示体验。
2. 修少量会影响用户理解的 Web 问题。
3. 明确报告和文档口径。
4. 准备最终演示、日报、PPT 或答辩材料。

可以延后：

- docker-compose。
- 生产级账号体系。
- SQLite / Postgres 对话存储。
- Web 全量交互测试。
- best-practices 和 SOP 完整填充。
- OpenSquilla 重新训练。
- 新部门 benchmark。

## 9. 新 agent 应该怎么继续看项目

建议阅读顺序：

1. `docs/project-current-state-handoff.md`
2. `docs/web-workbench-handoff.md`
3. `web/app.py`
4. `src/airouter/web/ui.py`
5. `src/airouter/engine/router/router.py`
6. `src/airouter/models/schemas.py`
7. `data/models.yaml`
8. `docs/opensquilla-router-calibration-report.md`
9. `src/airouter/engine/benchmark/ground_truth_runner.py`
10. `docs/CHANGELOG-design.md` 只作为查历史，不作为第一入口。

判断一个功能是否“完成”，不要只看文档计划，要同时看：

- 代码是否存在。
- CLI / Web 是否接线。
- 是否有单元测试或集成测试。
- 是否跑过真实 API。
- 是否有报告产物。
- 是否只是 stub 文档。
