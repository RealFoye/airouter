# AirRouter 项目完整交接说明

本文给没有上下文的新 agent 使用。目标是让新 agent 快速理解 AirRouter 从最初设计、后端路由、Benchmark 证据链，到当前 Web 工作台的完整全貌。

如果本文与早期零散文档冲突，优先以本文、当前代码和最新报告为准。

## 1. 项目一句话定位

AirRouter 是一个企业 AI 模型路由与治理 MVP。

它不是单纯聊天机器人，也不是只做模型排行榜。核心目标是：

```text
用户提出任务
→ 系统先分析任务画像
→ 推荐模型和执行策略
→ 必要时让 Judge 大模型复核
→ 用户确认后再真实调用模型
→ 记录成本、质量、风险和评测结果
```

当前项目最重要的主线是：

- 后端 Router：根据任务选择模型和策略。
- OpenSquilla ML 复杂度分类：增强复杂度判断。
- Benchmark：用真实模型输出校准路由策略。
- Web 工作台：把“先分析、再执行”的流程做成普通用户可用的界面。

## 2. 新 agent 建议阅读顺序

请按这个顺序读，不要一上来只看某一个文件。

1. `docs/project-full-overview-handoff.md`：本文，项目全貌。
2. `docs/project-current-state-handoff.md`：当前状态和主线能力。
3. `docs/web-workbench-handoff.md`：Web 工作台细节。
4. `docs/system-design.md`：系统设计总文档。
5. `docs/opensquilla-router-calibration-report.md`：OpenSquilla 校准结论。
6. `/tmp/smoke_routing/20260615_192850/report.md`：当前最重要的 Routing Ground Truth 正式报告。
7. `docs/model-selection-report.md`：早期 Level 2 模型质量评测报告。
8. `runs/benchmarks/finance/20260610_084555/finance_report.md`：Finance Benchmark 正式报告。

## 3. 从头到现在做了什么

### 3.1 第一阶段：规则路由和基础治理

最初目标是做一个企业 AI Router，不是直接调用固定模型。

核心能力：

- 分析用户任务。
- 估算复杂度、风险、可验证性和成本。
- 从多个模型中选择合适模型。
- 根据预算、风险和人工确认规则决定是否执行。

主要文件：

- `src/airouter/engine/router/router.py`
- `src/airouter/engine/router/analyzer.py`
- `src/airouter/engine/router/classifier.py`
- `src/airouter/engine/router/selector.py`
- `src/airouter/engine/router/estimator.py`
- `src/airouter/engine/router/gate.py`
- `src/airouter/models/schemas.py`
- `src/airouter/models/enums.py`
- `data/models.yaml`
- `data/routing_rules.yaml`
- `data/budgets.yaml`

Router 管线是：

```text
TaskAnalyzer / ComplexityAnalyzer
→ TaskFeatures
→ StrategyClassifier
→ ModelSelector
→ CostEstimator
→ RoutingGate
→ RoutingDecision
```

`TaskFeatures` 是任务画像，关键维度包括：

- category
- complexity
- risk_level
- sensitivity
- verifiability
- output_strictness
- context_requirement
- reasoning_intensity
- estimated_input_tokens
- estimated_output_tokens
- subtasks
- required_capabilities
- preferred_capabilities

当前支持的策略类型在 `src/airouter/models/enums.py`：

- `SINGLE_MODEL`
- `GUIDED_EXECUTE`
- `PLAN_EXECUTE`
- `PLAN_EXECUTE_REVIEW`

### 3.2 第二阶段：Level 1 / Level 2 / LLM Judge

为了避免“看起来能路由，实际不可信”，项目引入 Benchmark。

Level 1：

- 40 条离线规则样例。
- 不调用真实 API。
- 验证路由规则是否基本正确。

数据和代码：

- `data/benchmarks/level1/router_cases.yaml`
- `tests/integration/test_benchmark_level1.py`
- `src/airouter/engine/benchmark/runner.py`
- `src/airouter/engine/benchmark/evaluator.py`

Level 2：

- 30 条模型质量任务。
- 后来扩展为 5 个模型参与真实 API 测试。
- 接入自动评分、Absolute Judge、Pairwise Judge。

数据和代码：

- `data/benchmarks/level2/router_quality_cases.yaml`
- `src/airouter/engine/benchmark/llm_judge_v2.py`
- `src/airouter/engine/benchmark/pairwise_judge.py`
- `src/airouter/engine/benchmark/l2_report.py`
- `docs/model-selection-report.md`

早期重要经验：

- 自动规则容易误判复杂自然语言。
- Judge 也会出错，不能当绝对真值。
- Resume / limit / 重复调用必须严格测试，否则会浪费 API 成本。
- 成本必须用 CCH usage CSV 对账，不能只信 `models.yaml` 估算价。

### 3.3 第三阶段：Finance Benchmark

Finance Benchmark 是第一个企业业务场景样板。

它覆盖：

- 表格计算
- 报销审核
- 三单匹配
- 银行对账
- 预算分析
- 制度问答

数据和代码：

- `data/benchmarks/finance/finance_cases.yaml`
- `data/benchmarks/finance/artifacts/`
- `src/airouter/engine/benchmark/finance_runner.py`
- `src/airouter/engine/benchmark/finance_evaluator.py`
- `src/airouter/engine/benchmark/finance_report.py`
- `src/airouter/engine/benchmark/finance_judge.py`
- `runs/benchmarks/finance/20260610_084555/finance_report.md`

真实运行结果：

- Run ID：`20260610_084555`
- 36 个财务案例。
- 5 个模型。
- 180 pair 全部成功。
- MiniMax-M3 Judge 后续完成 180/180 辅助审计。

重要结论：

- `qwen3.7-plus` 财务综合分最高。
- `deepseek-v4-flash` 成本最低，适合低风险高可验证任务。
- 规则评分适合金额、字段、硬约束。
- LLM Judge 适合解释质量、误扣、证据不足和幻觉审计。
- 不能把自然语言关键词匹配直接做成硬失败，这一点后来也影响了 Engineering / Routing Ground Truth 的评分设计。

### 3.4 第四阶段：部门泛化与 Engineering Benchmark

为了证明 Finance 不是财务专用功能，项目抽象出部门级 Benchmark 方法论。

相关文档：

- `docs/department-benchmark-framework.md`
- `docs/engineering-benchmark-design.md`

Engineering Benchmark 设计了 30 条研发任务，覆盖：

- CODE_FIX
- CODE_REVIEW
- LOG_ANALYSIS
- SQL_SAFETY
- CONFIG_CHANGE
- ANTI_HALLUCINATION

数据文件：

- `data/benchmarks/engineering/engineering_cases.yaml`

核心思想：

- 不只是测代码能力。
- 更要测工程可控性：是否遵守指令、是否伪造文件/测试结果、是否识别高风险操作、是否需要澄清、是否要求人工确认。

### 3.5 第五阶段：OpenSquilla 复用

项目引入开源项目 OpenSquilla 的复杂度分类能力。

OpenSquilla 相关目录：

- `opensquilla/`
- `opensquilla/src/opensquilla/squilla_router/models/v4.2_phase3_inference/`

AirRouter 接入文件：

- `src/airouter/engine/complexity/analyzer.py`
- `src/airouter/engine/complexity/ml_backend.py`
- `src/airouter/engine/complexity/artifact_verifier.py`
- `src/airouter/engine/complexity/types.py`
- `docs/opensquilla-router-provenance.md`
- `docs/system-design-ml-complexity-extension.md`
- `docs/opensquilla-router-calibration-report.md`

OpenSquilla 的 R0-R3 与 AirRouter 映射：

```text
R0 → SIMPLE
R1 → MODERATE
R2 → COMPLEX
R3 → EXPERT
```

支持四种模式：

| mode | 含义 |
|---|---|
| `rules` | 纯规则，默认生产基线 |
| `shadow` | 运行 ML 但不改变路由，只记录诊断 |
| `opensquilla` | 直接使用 OpenSquilla final class |
| `hybrid` | 规则为主，ML 只做受控升级 |

70 条校准集结果见：

- `docs/opensquilla-router-calibration-report.md`

校准集：

- Level 1：40 条。
- Engineering：30 条。
- 总计：70 条。

结论：

- OpenSquilla 可真实加载和推理。
- 它不是全局替代规则的银弹。
- 它对工程复杂任务有价值，尤其能减少欠路由。
- 它也会带来过度路由和成本增加。
- 最终路由好不好不能只看复杂度标签，要看真实模型输出、成本和成功率。

### 3.6 第六阶段：Routing Ground Truth Benchmark

这是目前最重要的路由策略验证。

核心思想：

真正的路由真值不应该靠人拍脑袋写“简单/复杂”，而应该基于真实模型结果：

```text
同一道题让 5 个模型都回答
→ 用规则、沙箱、Judge 判断每个模型是否通过
→ 找出能通过的最便宜模型
→ 这个最便宜可通过模型就是 Oracle
→ 再比较 rules / ml_raw / ml_final / hybrid 选得是否接近 Oracle
```

数据：

- Dev：`data/benchmarks/engineering/engineering_cases.yaml`，30 条。
- Holdout：`data/benchmarks/routing_ground_truth/general_cases.yaml`，60 条。
- Manifest：`data/benchmarks/routing_ground_truth/evaluation_manifest.json`

核心代码：

- `src/airouter/engine/benchmark/ground_truth_loader.py`
- `src/airouter/engine/benchmark/ground_truth_runner.py`
- `src/airouter/engine/benchmark/ground_truth_evaluator.py`
- `src/airouter/engine/benchmark/ground_truth_judge.py`
- `src/airouter/engine/benchmark/oracle_generator.py`
- `src/airouter/engine/benchmark/strategy_replay.py`
- `src/airouter/engine/benchmark/ground_truth_report.py`
- `src/airouter/engine/benchmark/sandbox.py`

最终正式产物：

- `/tmp/smoke_routing/20260615_192850/report.md`
- `/tmp/smoke_routing/20260615_192850/results.jsonl`
- `/tmp/smoke_routing/20260615_192850/results.rescored.jsonl`
- `/tmp/smoke_routing/20260615_192850/results.judged.jsonl`
- `/tmp/smoke_routing/20260615_192850/judge_results.jsonl`
- `/tmp/smoke_routing/20260615_192850/aggregated.judged.jsonl`
- `/tmp/smoke_routing/20260615_192850/oracles.judged.jsonl`
- `/tmp/smoke_routing/20260615_192850/raw_outputs/`

正式结果：

- Run ID：`20260615_192850`
- 总 case：90 = Dev 30 + Holdout 60。
- 候选模型：5 个。
- 总评估 pair：450。
- 成功 pair：450/450。
- Judge：450/450。
- 总体通过率：303/450 = 67.3%。

模型总体表现：

| 模型 | 通过率 | 平均分 | 总成本 |
|---|---:|---:|---:|
| qwen3.7-plus | 72.2% | 0.826 | ¥1.48 |
| deepseek-v4-pro | 70.0% | 0.800 | ¥0.59 |
| glm-5.1 | 65.6% | 0.800 | ¥4.19 |
| qwen3.7-max | 64.4% | 0.799 | ¥8.16 |
| deepseek-v4-flash | 64.4% | 0.786 | ¥0.20 |

策略回放重点结论：

- 质量优先：`ml_final` 表现最好，Quality Regret 最低。
- 成本优先：`rules` 成本最低。
- Hybrid 在这轮正式报告里没有明显优于 `ml_final`。
- Oracle 最优路由相比始终使用 `qwen3.7-max` 节省约 96.1%。

必须注意：

- `/tmp/smoke_routing/20260615_192850/results.jsonl` 有 490 行，因为包含补跑/失败重试记录。
- 去重后的正式 pair 是 450。
- 判断正式结果请看 `results.rescored.jsonl`、`results.judged.jsonl`、`oracles.judged.jsonl` 和 `report.md`。
- CCH 账单尚需导出 usage CSV 对账。

## 4. 当前模型配置

模型注册表：

- `data/models.yaml`
- `src/airouter/models/model_registry.py`

当前可用模型：

- `qwen3.7-max`
- `qwen3.7-plus`
- `deepseek-v4-pro`
- `deepseek-v4-flash`
- `glm-5.1`
- `MiniMax-M3`
- `kimi-k2.6`

已删除：

- `claude-sonnet-4-6`

原因：当前 API 侧不可用，保留会误导前端和 Judge 配置。

当前模型定位：

- `qwen3.7-plus`：质量综合最好，且支持图片/多模态，Web 中图片任务固定使用它。
- `deepseek-v4-pro`：性价比较好。
- `deepseek-v4-flash`：最低成本。
- `qwen3.7-max`：最高档/最贵模型，用作成本对比锚点和部分辅助能力。
- `MiniMax-M3`：主要用于深度复核和 Judge。
- `kimi-k2.6`：已加入模型池，但需要更多价格和能力校准。

注意：

- `MiniMax-M3` 和 `kimi-k2.6` 的价格仍需 CCH 对账。
- Web 里“成本对比”以 `qwen3.7-max` 为最贵锚点。

## 5. 当前 Web 工作台

Web 是当前最重要的展示层。

核心文件：

- `web/app.py`
- `src/airouter/web/ui.py`
- `src/airouter/web/data.py`
- `web/pages/1_route_workbench.py`
- `web/pages/2_consumption_dashboard.py`
- `web/pages/3_optimization_center.py`
- `web/pages/4_benchmark_results.py`
- `web/pages/5_governance_config.py`

当前用户流程：

```text
用户输入 API Key 登录
→ 进入智能工作台
→ 输入任务或上传附件
→ 点击“分析”
→ 本地 Router + OpenSquilla 生成推荐方案
→ 用户可接受、深度复核、更省钱、更稳妥、手动选择
→ 用户点击接受后才真实调用模型
→ 模型流式输出
→ 后续可继续追问并切换模型
```

当前 Web 特性：

- API Key 登录。
- 按 API Key 指纹保存本地会话历史。
- 左侧历史对话。
- 历史对话可重命名、删除。
- 大模型自动生成对话标题。
- 支持 Markdown 渲染。
- 支持流式输出。
- 支持执行中切换模型。
- 支持长上下文自动压缩。
- 支持深度复核。
- 支持文件解析工具。
- 支持报告整理工具。
- 支持图片、PDF、表格、文本、代码、日志附件。

附件路径：

- 图片：固定走 `qwen3.7-plus`。
- PDF：依赖 `pypdf` 提取正文。
- Excel：依赖 `openpyxl`。
- 文本、代码、日志、CSV/TSV：直接读取并截断注入上下文。

Web 的当前执行不是 Agent Loop。

现在是：

```text
直接 API 调用 + Web 自己维护上下文
```

上下文如何接上：

- API 本身没有记忆。
- Web 每次调用模型时，会重新拼接 system prompt、历史执行消息、压缩摘要、本轮输入和附件内容。
- 相关函数在 `web/app.py`：
  - `_build_execution_messages`
  - `_execute_with_user_key`
  - `_compress_context_if_needed`

当前还没有真正的 Agent Loop：

```text
模型思考
→ 主动选择工具
→ 工具返回
→ 模型继续思考
→ 再调用工具
→ 最终回答
```

现在的“工具”是预处理/辅助：

- 文件解析：执行前把附件变成可用上下文。
- 报告整理：给模型加报告结构指令。
- 深度复核：额外调用 Judge 模型复核推荐。

后续如果要做 Agent，建议先做受控的 `Plan → Execute → Review`，不要一开始做无限循环。

## 6. Web 当前 UI 近期改动

这些是最新修改点，新 agent 不要以旧截图为准。

1. 普通用户主界面改成 ChatGPT/Claude 风格。
2. 管理员入口收进侧栏折叠菜单。
3. 左侧历史对话支持重命名和删除。
4. 旧附件不会每轮都显示成本轮新文件，但仍保留在当前会话上下文。
5. 文件上传入口改成更明显的 `+ 添加文件`。
6. 工具提示会显示“文件解析”“报告整理”。
7. 推荐卡片的成本对比会显示：

```text
省 xx%
qwen3.7-max 约 ¥x，少花 ¥y
```

8. 深度复核按钮下方提示：

```text
深度复核会调用大模型，点击后会消耗 token 并产生少量费用。
```

## 7. CLI 与 API

CLI 入口：

- `src/airouter/cli/main.py`
- `src/airouter/cli/analyze.py`
- `src/airouter/cli/audit.py`
- `src/airouter/cli/optimize.py`
- `src/airouter/cli/benchmark.py`

主要命令：

- `ai-router analyze`
- `ai-router audit`
- `ai-router optimize`
- `ai-router benchmark`

API 入口：

- `src/airouter/api/main.py`
- `src/airouter/api/routes/`

当前重点不在 API server，而在 CLI、Benchmark 和 Streamlit Web。

## 8. 测试与质量

测试目录：

- `tests/unit/`
- `tests/integration/`

重点测试：

- Router：`tests/unit/test_router.py`
- Analyzer：`tests/unit/test_analyzer.py`
- Selector：`tests/unit/test_selector.py`
- Gate：`tests/unit/test_gate.py`
- OpenSquilla：`tests/unit/test_ml_backend.py`、`tests/integration/test_opensquilla_runtime.py`
- Finance：`tests/unit/test_finance_*`
- Ground Truth：`tests/unit/test_ground_truth_*`
- Strategy Replay：`tests/unit/test_strategy_replay.py`
- Web 数据：`tests/unit/test_web_data.py`

常用验证命令：

```bash
python -m py_compile web/app.py src/airouter/web/ui.py
python -m ruff check web/app.py src/airouter/web/ui.py
python -m pytest tests/unit/test_web_data.py tests/unit/test_model_registry.py -q
python -m pytest tests/ -q
make lint
```

注意：

- 全量测试可能较久。
- 真实 API benchmark 不要随便跑。
- 不要未经用户确认就重跑 Finance / Routing Ground Truth 全量。

## 9. 运行 Web

当前本地 Streamlit 常用命令：

```bash
streamlit run web/app.py --server.port 8502 --server.headless true --server.fileWatcherType none
```

当前使用的本地地址：

```text
http://localhost:8502
```

注意：

- 8501 可能被旧服务占用。
- `--server.fileWatcherType none` 时，代码改完需要手动重启服务。

## 10. 已知限制和风险

### 10.1 Web 限制

- `runs/web/conversations.json` 是本地 JSON 文件，没有并发写锁。
- 没有正式账号系统，只有 API Key 指纹隔离。
- streaming 调用为了实时输出直接使用 OpenAI client，没有完整走 adapter 抽象。
- token 和成本在 streaming 路径中是估算，不是 provider usage 精确值。
- Web 交互测试还少。

### 10.2 Benchmark 限制

- Judge 不是标准答案，只能辅助审计。
- 规则评分适合确定性事实，不适合把自然语言关键词直接做硬门禁。
- Routing Ground Truth 的正式结果需要 CCH usage CSV 对账。
- `/tmp/smoke_routing/20260615_192850/summary.json` 中个别旧字段可能与最终 report 不一致；正式口径请看 `report.md` 和 `.judged.jsonl` 产物。

### 10.3 OpenSquilla 限制

- OpenSquilla bundle 依赖本地 ML 包，可能有 sklearn 版本 warning。
- `opensquilla/` 和 bundle 目录不要误提交。
- ML 复杂度分类只是路由信号之一，不应绕过风险门禁和用户确认。

### 10.4 未来开发限制

当前只剩收口时间，不建议继续新增大方向。

不要继续扩展更多部门 benchmark。
不要重新训练 OpenSquilla。
不要重做前端技术栈，除非明确进入下一阶段。
不要直接做无限 Agent Loop。

## 11. 后续建议路线

优先级从高到低：

1. 收口 Web 体验，让普通用户能看懂并真实使用。
2. 把当前 Web 的关键能力整理成演示脚本。
3. 增加受控 Agent 模式：`Plan → Execute → Review`。
4. 设计 AirRouter Local Proxy，用于接入 Claude Code / cc switch。
5. 完成 CCH usage CSV 成本对账。
6. 如果继续做开发者场景，再考虑接入代码沙箱、项目文件工具和更完整的 agent loop。

## 12. 如果新 agent 要回答问题，应先确认的事实

新 agent 回答问题前，建议先确认：

1. 问题是在问后端 Router、Benchmark、Web，还是未来 Agent/Proxy？
2. 是否需要真实 API 调用？
3. 是否会写 `runs/benchmarks/` 或 `/tmp/smoke_routing/`？
4. 是否会影响当前 Web 服务？
5. 结果是面向普通用户、开发人员，还是项目汇报？

如果只是改 Web：

- 主要看 `web/app.py` 和 `src/airouter/web/ui.py`。
- 改完至少跑 `py_compile`、`ruff`、Web 相关单测。
- 重启 Streamlit 8502。

如果只是分析 Routing Ground Truth：

- 主要看 `/tmp/smoke_routing/20260615_192850/report.md`。
- 不要重新调用真实 API。

如果只是分析 Finance：

- 主要看 `runs/benchmarks/finance/20260610_084555/finance_report.md`。
- 不要重跑 Finance benchmark。

## 13. 项目当前最适合对外讲的故事

对外汇报时，可以这样讲：

```text
AirRouter 不是简单按价格选模型。
它先判断任务复杂度、风险、可验证性和上下文需求，
再结合真实 Benchmark 结果、成本、模型能力和人工确认门禁，
推荐合适的模型与执行策略。

Finance Benchmark 证明了业务场景治理能力；
Engineering / Routing Ground Truth Benchmark 证明了开发和通用任务的路由校准能力；
OpenSquilla 提供了更强的语义复杂度信号；
Web 工作台把这一套能力包装成普通用户可理解的“先分析，再执行”体验。
```

