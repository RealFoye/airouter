# AirRouter CLI 设计方案

> 本文档面向新加入项目的开发者（包括 AI Agent），详细描述 CLI 层的每一个命令、每一个参数、每一个内部类的职责和数据流。读完本文档应能完全理解 CLI 层的代码结构和运行逻辑。

---

## 目录

1. [整体架构](#1-整体架构)
2. [入口：main.py](#2-入口mainpy)
3. [命令一：analyze — 路由分析](#3-命令一analyze--路由分析)
4. [命令二：optimize — 成本优化](#4-命令二optimize--成本优化)
5. [命令三：benchmark — 基准测试](#5-命令三benchmark--基准测试)
6. [命令四：audit — 消费审计](#6-命令四audit--消费审计)
7. [命令五：run — 单次 Agent 执行](#7-命令五run--单次-agent-执行)
8. [命令六：agent — 交互式 Agent](#8-命令六agent--交互式-agent)
9. [Agent 子系统详解](#9-agent-子系统详解)
10. [路由子系统概览](#10-路由子系统概览)
11. [公共数据结构](#11-公共数据结构)
12. [配置系统](#12-配置系统)
13. [错误处理](#13-错误处理)

---

## 1. 整体架构

```
用户输入
  │
  ▼
┌─────────────────────────────────────────────────┐
│                  CLI 层 (Typer)                   │
│  main.py → analyze / optimize / benchmark /      │
│             audit / run / agent                   │
└─────────┬─────────┬──────────┬─────────┬────────┘
          │         │          │         │
          ▼         ▼          ▼         ▼
    ┌─────────┐ ┌────────┐ ┌────────┐ ┌──────────────┐
    │ Router  │ │Optimizer│ │Benchmark│ │ AgentExecutor│
    │(路由分析)│ │(成本优化)│ │Runner  │ │ (Agent执行)  │
    └────┬────┘ └────┬───┘ └────┬───┘ └──────┬───────┘
         │           │          │              │
         ▼           ▼          ▼              ▼
    ┌────────────────────────────────────────────────┐
    │              Engine 层                          │
    │  router/ │ optimize/ │ benchmark/ │ agent/      │
    │  audit/  │ complexity/                            │
    └────────────────────┬───────────────────────────┘
                         │
                         ▼
    ┌────────────────────────────────────────────────┐
    │              Adapters 层                        │
    │  openai_compat.py │ base.py │ factory.py        │
    └────────────────────────────────────────────────┘
```

**分层原则**：
- **CLI 层**：只负责参数解析、输入校验、输出格式化（Rich/JSON）。不含业务逻辑。
- **Engine 层**：核心业务逻辑。路由分析、成本优化、基准测试、Agent 执行。
- **Adapters 层**：模型 API 适配器。统一接口对接不同 LLM 提供商。

**技术选型**：
- CLI 框架：**Typer**（基于 Click，类型注解驱动）
- 输出美化：**Rich**（Panel、Table、Text）
- 数据模型：**Pydantic v2**（所有配置和数据结构）

---

## 2. 入口：main.py

**文件**：`src/airouter/cli/main.py`

### 启动前的环境处理

在任何 import 之前，main.py 做了两件事来消除 demo 时的噪音输出：

```python
import warnings
warnings.filterwarnings("ignore", category=UserWarning, module="sklearn")
```
- **为什么**：OpenSquilla ML 模型的 pickle 与当前环境 sklearn 版本不一致时会输出 `InconsistentVersionWarning`。项目的 `ml` 可选依赖已经固定匹配版本，这里只是避免非标准环境污染终端输出。

```python
import os
if "MPLCONFIGDIR" not in os.environ:
    os.environ["MPLCONFIGDIR"] = "/tmp/matplotlib"
```
- **为什么**：matplotlib 在某些环境下会因为缓存目录权限问题输出警告。设置可写临时目录避免此问题。

### Typer 应用创建

```python
app = typer.Typer(
    name="ai-router",
    help="AI Router - 企业级 AI 模型智能路由与 Token 精细化管控系统",
    no_args_is_help=True,
)
```

- `no_args_is_help=True`：用户直接输入 `ai-router` 不带参数时，打印帮助信息而不是报错。

### 命令注册方式

每个命令模块导出一个函数，通过 `app.command(name)(function)` 注册：

```python
from airouter.cli import agent, analyze, audit, benchmark, optimize, run

app.command("analyze")(analyze.analyze)
app.command("audit")(audit.audit)
app.command("benchmark")(benchmark.benchmark)
app.command("optimize")(optimize.optimize)
app.command("run")(run.run)
app.command("agent")(agent.agent)
```

- **为什么不用装饰器**：各命令模块的函数定义时不依赖 Typer，注册逻辑集中在 main.py。方便模块独立测试。

### @app.callback()

Typer 要求有 callback 才能在顶层显示 help。callback 本身不做任何事。

### 入口函数

通过 `pyproject.toml` 的 `[project.scripts]` 配置 `ai-router = "airouter.cli.main:app"` 后，`pip install -e .` 会生成 `ai-router` 可执行文件。

---

## 3. 命令一：analyze — 路由分析

**文件**：`src/airouter/cli/analyze.py`

### 职责

接受一段任务描述文本，通过路由系统分析应该用什么策略和模型执行，输出路由决策详情。**不调用任何模型 API，纯离线分析**。

### 参数定义

| 参数名 | Python 类型 | Typer 类型 | 默认值 | 说明 |
|--------|------------|-----------|--------|------|
| `task` | `str` | `typer.Argument` | (必填) | 任务描述文本 |
| `output_format` | `str` | `typer.Option` | `"rich"` | `--format`, `-f`。输出格式 |
| `show_complexity` | `bool` | `typer.Option` | `False` | `--show-complexity`。显示 ML 复杂度详情 |

### 执行流程

```
用户输入 task 文本
     │
     ▼
Router()               ← 实例化路由门面
     │
     ▼
router.route(task)     ← 返回 RoutingDecision
     │
     ├── format=json → _output_json(decision)
     │                  └── decision.model_dump(mode="json") → json.dumps
     │
     └── format=rich → _output_rich(decision)
                        ├── 任务特征面板（蓝色边框）
                        ├── 推荐方案面板（绿色边框）
                        ├── 推荐理由面板
                        ├── 替代方案表格
                        └── 质量门禁行
                        （如果 show_complexity=True）
                        └── _output_complexity(decision)
                             └── ML 复杂度分析面板（青色边框）
```

### 内部依赖：Router

**文件**：`src/airouter/engine/router/router.py`

`Router` 是路由系统的门面类，内部协调 5 个组件：

```
task 文本
  │
  ▼
┌──────────────────┐
│ ComplexityAnalyzer│ ← 1. 提取任务特征 + 复杂度分析
│ (含 TaskAnalyzer) │    输出：TaskFeatures + ComplexityDiagnostics
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ StrategyClassifier│ ← 2. 根据特征判断候选策略
│                   │    输出：list[StrategyType]
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ ModelSelector    │ ← 3. 过滤模型 → 评分 → 选最优策略
│ (含 ModelRegistry)│    输出：(best_strategy, model_assignment, alternatives)
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ CostEstimator    │ ← 4. 估算各策略的成本
│                   │    输出：estimated_cost, baseline_cost, savings
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ RoutingGate      │ ← 5. 判断是否需要人工审查 + 质量门禁
│                   │    输出：requires_human_review, quality_gate
└────────┬─────────┘
         │
         ▼
RoutingDecision    ← 最终路由决策（Pydantic model）
```

**关键数据流**：
- `ComplexityAnalyzer` 产出 `TaskFeatures`（category, complexity, risk_level 等）和 `ComplexityDiagnostics`（ML 模式下的分类概率、置信度等）
- `StrategyClassifier` 根据 `TaskFeatures` 判断哪些策略合格（如 COMPLEX 以上才触发 PLAN_EXECUTE）
- `ModelSelector` 对每个合格策略，按模型能力过滤 + 成本-质量评分，选出最优
- `CostEstimator` 计算选定策略的预估成本和基线成本
- `RoutingGate` 根据风险等级和策略决定是否需要人工审批

### Rich 输出格式

**任务特征面板**（蓝色边框）：显示 category, complexity, risk_level, sensitivity, context_requirement, reasoning_intensity。

**推荐方案面板**（绿色边框）：显示 strategy, 模型分配, estimated_cost, baseline_cost, savings%, estimated_quality, budget_status。

如果 `requires_human_review=True`，面板末尾追加红色警告。如果模型分配为空，显示红色"人工介入"面板。

**替代方案表格**：显示备选策略及其模型、成本、质量。

**ML 复杂度面板**（`--show-complexity`，青色边框）：显示 mode, rule_complexity, resolved_complexity, resolution_reason, ML raw/final class, confidence, probability distribution, latency。

### JSON 输出

`decision.model_dump(mode="json")` 序列化全部字段。

---

## 4. 命令二：optimize — 成本优化

**文件**：`src/airouter/cli/optimize.py`

### 职责

分析 Prompt 的 Token 组成，结合路由分析，给出 5 类优化建议。**不调用模型 API，纯离线分析。**

### 参数定义

| 参数名 | Python 类型 | 默认值 | Flag | 说明 |
|--------|------------|--------|------|------|
| `prompt` | `Optional[str]` | `None` | `--prompt`, `-p` | Prompt 文本 |
| `context_file` | `Optional[str]` | `None` | `--context-file`, `-c` | Prompt 文件路径 |
| `model` | `Optional[str]` | `None` | `--model`, `-m` | 当前模型名 |
| `scenario` | `Literal[...]` | `"SINGLE_TURN"` | `--scenario`, `-s` | 使用场景 |
| `turns` | `Optional[int]` | `None` | `--turns`, `-t` | 预期对话轮数 |
| `output_format` | `Literal["rich","json"]` | `"rich"` | `--format`, `-f` | 输出格式 |

### 输入校验

1. `turns` 如果提供，必须 >= 1
2. `prompt` 和 `context_file` 至少提供一个
3. 如果 `context_file` 存在，读取并拼接
4. 如果 `model` 提供，验证存在于 ModelRegistry

### 执行流程

```
_resolve_input() → PromptOptimizer() → optimizer.optimize() → Rich/JSON 输出
```

### 内部依赖：PromptOptimizer

**文件**：`src/airouter/engine/optimize/optimizer.py`

`PromptOptimizer.__init__()` 创建：Router, CostEstimator, ModelRegistry, ModelSelector, Compressor。

**optimize() 11 步管线**：

| 步骤 | 名称 | 做什么 |
|------|------|--------|
| 1 | 参数校验 | scenario 必须在 SCENARIO_CACHE_RATIO 中 |
| 2 | 路由分析 | `router.route(prompt)` → TaskFeatures + 推荐策略 |
| 3 | 行分类 | 把 prompt 每行归入 5 类（system/tool/context/history/query） |
| 4 | Token 分析 | 计算每类 Token 数 |
| 5 | 覆盖特征 | 用实际 breakdown 替换路由的 estimated_input_tokens |
| 6 | 确定策略 | 指定 model 用 SINGLE_MODEL；否则用路由推荐 |
| 7 | 升级检测 | requires_human_review → 生成 escalate 警告 |
| 8 | 确定轮数 | expected_turns 或场景默认值 |
| 9 | 当前成本 | `estimator.estimate_strategy_cost()` |
| 10 | 生成建议 | 5 类 _suggest_*() 方法 |
| 11 | 汇总 | 正交建议求和 + 互斥建议取 max |

**行分类的 5 个类别**：

| 类别 | 识别规则 |
|------|---------|
| `system_prompt` | "你是"/"You are" 等开头的系统指令 |
| `tool_definitions` | JSON 代码块或 `| `tool_definitions` | JSON 代码块或 function 标签区域 |
| `fixed_context` | "## 背景"/"## Context"/"项目结构" 等 |
| `conversation_history` | "User:"/"Assistant:"/"历史对话" 等 |
| `dynamic_query` | 以上都不匹配，兜底类别 |

**5 类优化建议**：

| 建议 | 前提条件 | 计算逻辑 |
|------|---------|---------|
| **缓存** `_suggest_cache` | 模型支持 cache_read，可缓存 prefix 够长 | (turns-1) × cacheable_tokens × cache_savings_rate |
| **压缩** `_suggest_compression` | 对话历史 Token > 0 | Compressor 三策略（保守/标准/激进）自动选择 |
| **降级** `_suggest_downgrade` | 当前模型不是最低 Tier | 找更便宜 Tier 模型，检查是否需审批 |
| **裁剪** `_suggest_trimming` | 上下文为 HEAVY/EXTREME | HEAVY 裁 30%，EXTREME 裁 50% |
| **Plan-Execute** `_suggest_plan_execute` | 非 PE 策略 + subtasks >= 2 | 找最便宜 planner + executor，估算 PE 成本 |

**汇总逻辑**：正交建议（cache + compression + trimming）求和；互斥建议（downgrade vs plan_execute）取 max。

### Rich 输出格式

- **分析结果面板**（蓝色）：当前 Token、当前方案、当前成本
- **输入组成分析面板**：5 类 Token 分布 + 优化提示
- **优化建议表格**：#、类别（含"需审批"标签）、建议描述、节省金额和比例
- **压缩策略对比表**（如有）：三种策略的压缩效果
- **汇总行**：独立建议合计 + 参考优化成本
- **警告面板**（黄色）：重叠/互斥说明

---

## 5. 命令三：benchmark — 基准测试

**文件**：`src/airouter/cli/benchmark.py`

### 职责

运行不同级别的基准测试来验证路由系统的准确率和模型质量。

### 参数定义

#### 通用参数

| 参数名 | 默认值 | Flag | 说明 |
|--------|--------|------|------|
| `level` | (必填) | `--level`, `-l` | 评测级别：1/2/3/finance/routing |
| `output_format` | `"rich"` | `--format`, `-f` | 输出格式 |

#### Level 1 参数

| 参数名 | 默认值 | Flag | 说明 |
|--------|--------|------|------|
| `cases` | `None` | `--cases`, `-c` | 自定义 cases YAML 路径 |
| `fail_fast` | `False` | `--fail-fast` | 遇到失败立即停 |

#### Level 2 / Finance 参数

| 参数名 | 默认值 | Flag | 说明 |
|--------|--------|------|------|
| `models` | `None` | `--models` | 逗号分隔模型列表 |
| `rate_limit` | `20` | `--rate-limit` | RPM 限制 |
| `real_api` | `False` | `--real-api` | 使用真实 API |
| `run_id` | `None` | `--run-id` | 恢复指定 run |
| `output_dir` | `None` | `--output-dir` | 结果目录 |
| `limit` | `None` | `--limit` | 最大执行 pair 数 |
| `workers` | `5` | `--workers` | 并发 worker 数 |
| `resume` | `False` | `--resume` | 从断点恢复 |
| `judge` | `False` | `--judge` | 运行 LLM Judge |
| `judge_models` | `None` | `--judge-model` | Judge 模型列表 |
| `judge_workers` | `20` | `--judge-workers` | Judge 并发数 |
| `skip_pairwise` | `False` | `--skip-pairwise` | 跳过成对比较 |

#### Finance 专属参数

| 参数名 | 默认值 | Flag | 说明 |
|--------|--------|------|------|
| `judge_existing` | `False` | `--judge-existing` | 对已有 run 跑 Judge |
| `case_ids` | `None` | `--case-ids` | 只审计指定 case |
| `rescore` | `False` | `--rescore` | 离线重新评分 |

#### Level 3 参数

| 参数名 | 默认值 | Flag | 说明 |
|--------|--------|------|------|
| `case_set` | `"all"` | `--case-set` | 数据集：all/l1/l2 |
| `baseline_model` | `"qwen3.7-max"` | `--baseline-model` | 基线模型 |

#### Routing 参数

| 参数名 | 默认值 | Flag | 说明 |
|--------|--------|------|------|
| `rerun` | `False` | `--rerun` | 完整重跑（与 --limit/--resume 互斥） |

### 执行分发

```python
level_normalized = level.lower().strip()
if level_normalized == "1": _run_level1(...)
elif level_normalized == "2": _run_level2(...)
elif level_normalized == "3": _run_level3(...)
elif level_normalized == "finance": _run_finance(...)
elif level_normalized == "routing": _run_routing(...)
```

### Level 1：离线规则评测

**Runner**：`Level1BenchmarkRunner`

加载 cases YAML → 对每个 case 调用 Router.route() → 用断言规则验证 → 汇总 pass_rate。

**指标体系**：strategy_match, model_tier, cost_within_range, quality_gate。

**退出码**：全部通过 → 0，有失败 → 1。

### Level 2：模型质量评测

**Runner**：`Level2BenchmarkRunner`

**两种模式**：
1. 标准模式：`runner.run()` → 自动评分 → model_scores, task_type_scores
2. Judge 模式：`runner.run_with_judges()` → 额外 Absolute Judge + Pairwise Judge

**数据持久化**：JSONL 格式保存到 `data/benchmarks/results/{run_id}/`，支持 `--resume` 断点恢复。

### Level 3：策略回测

**Runner**：`Level3BenchmarkRunner`

用历史数据回测路由策略：如果按路由建议执行，成本会怎样。

**输出指标**：savings_rate, overspend_count, safe/risky_downgrade_count, strategy/tier_distribution。

### Finance：企业财务评测

**Runner**：`FinanceBenchmarkRunner`

**三种子模式**：标准 / `--judge-existing` / `--rescore`。

**评测维度**：JSON 有效性、金额准确性、发现召回率、决策准确性、证据质量。

### Routing：路由 Ground Truth 评测

**Runner**：`GroundTruthRunner`

加载 Ground Truth 数据集 → 路由对比 → 可选 Judge → 生成 Oracle + Strategy Replay 产物。

---

## 6. 命令四：audit — 消费审计

**文件**：`src/airouter/cli/audit.py`

### 职责

查询 SQLite 数据库中的消费记录，进行多维度归因分析。**不调用模型 API。**

### 参数定义

| 参数名 | 默认值 | Flag | 说明 |
|--------|--------|------|------|
| `days` | `30` | `--days`, `-d` | 审计时间范围 |
| `user_id` | `None` | `--user` | 按用户过滤 |
| `project_id` | `None` | `--project` | 按项目过滤 |
| `department` | `None` | `--department` | 按部门过滤 |
| `output_format` | `"rich"` | `--format`, `-f` | 输出格式 |
| `db_url` | `"sqlite:///seed.db"` | `--db` | 数据库 URL |

### 执行流程

```
init_db(db_url) → Collector().collect(...) → Attribution().analyze(records, top_n_waste=5)
→ Rich/JSON 输出
```

### 内部依赖：Collector

**文件**：`src/airouter/engine/audit/collector.py`

SQL 查询 `routing_decision_records` LEFT JOIN `execution_feedback_records`。COALESCE 优先使用实际 token/cost 值。

### 内部依赖：Attribution

**文件**：`src/airouter/engine/audit/attribution.py`

- **基础统计**：total_cost, total_calls, daily_average, total_tokens
- **多维度分组**（Aggregator）：by_user, by_model, by_project, by_department, by_task_type
- **浪费模式检测**（Detector）：Top N 浪费模式 + severity + suggestion
- **重度用户识别**：消费 > 30% 总成本

### Rich 输出格式

- 标题面板（过滤条件）
- 汇总面板（总成本、调用次数、日均、Token 数）
- 按用户/模型表（重度用户标红 + ⚠）
- Top 5 浪费模式表（severity 颜色：High=红, Medium=黄, Low=绿）
- 优化建议面板（预估月节省）

---

## 7. 命令五：run — 单次 Agent 执行

**文件**：`src/airouter/cli/run.py`

### 职责

启动 Agent 自主完成开发任务。Agent 通过工具与项目代码交互。

### 参数定义

| 参数名 | 默认值 | Flag | 说明 |
|--------|--------|------|------|
| `task` | (必填) | positional | 任务描述 |
| `workdir` | `"."` | `--workdir`, `-w` | 工作目录 |
| `dry_run` | `False` | `--dry-run` | 只分析不执行 |
| `max_cost` | `1.0` | `--max-cost` | 成本上限（元） |
| `max_turns` | `10` | `--max-turns` | 最大工具调用轮数 |
| `yes` | `False` | `--yes`, `-y` | 跳过人工确认 |
| `output_format` | `"rich"` | `--format`, `-f` | 输出格式 |

### 执行流程

```
解析 workdir → load_all() → AppSettings + ModelRegistry + AdapterFactory
→ 强制 OpenSquilla 模式 → ComplexityAnalyzer → Router
→ AgentConfig → AgentExecutor
→ console.status spinner → executor.run(task, workdir)
→ Rich/JSON 输出
```

**强制 OpenSquilla 模式**：`run` 命令强制 `config.complexity.mode = "opensquilla"`，因为 Agent 执行需要更准确的复杂度判断。`bundle_dir` 从项目根目录推导。

### Rich 输出面板（按顺序渲染）

1. **任务面板**（黄色）：任务描述文本
2. **路由分析面板**（蓝色）：category, complexity, risk, strategy, ML 复杂度, model
3. **Verdict 横幅**：dry_run→"仅分析，未执行"(cyan) / cancelled→"用户取消"(yellow) / success→"✓ 执行成功"(green) / failure→"✗ 执行失败"(red)
4. **工具调用面板**：序号 + 工具名 + OK/FAIL + 参数 + result 预览（前 150 字符）
5. **成本报告面板**（绿色）：实际成本、基线成本、节省率（渐变色：>50%绿, >20%黄, ≤20%红）、Token 数、轮次、耗时、模型分布
6. **最终输出面板**（白色）：Agent 的最终回复
7. **Review 面板**（仅 PER）：PASS→绿色 / NEEDS_FIX→红色 / None→黄色

### JSON 输出结构

```json
{
    "goal": { "task", "category", "complexity", "risk_level", "strategy", "success_criteria" },
    "decision": { ... },
    "execution": { "final_response", "turns", "elapsed_seconds", "plan", "review", "review_passed", "dry_run", "cancelled" },
    "cost": { "total_cost_cny", "total_input_tokens", "total_output_tokens", "model_costs" },
    "baseline_cost": 0.0,
    "savings_vs_baseline": 0.0,
    "success": true,
    "tool_history": [ { "name", "args", "result", "success" } ]
}
```

---

## 8. 命令六：agent — 交互式 Agent

**文件**：`src/airouter/cli/agent.py`

### CLI 参数

```python
def agent(
    workdir: str = "--workdir, -w",         # 工作目录，默认 "."
    resume: str = "--resume",               # 恢复会话: latest 或 session_id
    model: str = "--model, -m",             # 覆盖执行模型
    yes: bool = "--yes, -y",                # 跳过所有确认
    max_cost: float = "--max-cost",         # 会话总成本上限，默认 5.0
    max_turns: int = "--max-turns",         # 每轮最大工具调用次数，默认 30
)
```

### REPL 主循环

```
┌─ console.input("> ") 获取用户输入
│
├─ 空输入 → 跳过
├─ /开头 → handle_slash() → 可能退出
├─ 普通文本 → 回显带底色 → execute_turn() → save()
└─ EOFError/Ctrl+C → save() → 退出
```

### 核心类：AgentSession

**文件**：`src/airouter/engine/agent/session.py`

```
AgentSession
├── __init__(workdir, model_override, skip_approval, max_cost, max_turns)
│   ├── 初始化 Router, AdapterFactory, ModelRegistry（强制 OpenSquilla 模式）
│   ├── 生成 session_id（微秒精度）
│   └── 初始化累积状态（history_messages, cost, tool_exec, touched_files）
│
├── execute_turn(user_input)
│   ├── _ensure_session_dir()
│   ├── _build_routing_text(user_input)  ← 包含上下文摘要和已修改文件
│   ├── router.route(routing_text)       ← 带 spinner "分析任务中..."
│   ├── GoalBuilder.build(decision, user_input, workdir)
│   ├── _apply_model_override(decision)
│   ├── 首轮模型确认（turn_count == 0 时）
│   ├── requires_approval 确认
│   ├── _build_runtime_messages(goal, user_input)
│   ├── run_agent_loop(...)              ← 共享 agent loop
│   │   ├── on_turn_start → "思考中..." spinner
│   │   └── on_tool_call → 实时显示 ✓/✗ 工具状态
│   ├── 更新 history_messages = result.messages[1:]
│   ├── _append_tool_records() → tools.jsonl
│   └── _append_event() → events.jsonl
│
├── handle_slash(input) → bool
│   ├── /exit → save() → return True
│   ├── /help → 打印命令表
│   ├── /model [name] → 编号菜单选择模型，或按名称直接切换
│   ├── /cost → 打印成本面板
│   ├── /files → 打印已修改文件
│   ├── /summary → 打印上下文摘要
│   ├── /compact → 手动压缩上下文
│   └── /reset → 清空上下文（保留成本/文件）
│
├── save()
│   ├── _save_session_json() → session.json
│   ├── _save_messages_current() → messages.current.json
│   ├── _save_cost() → cost.json
│   └── _save_touched_files() → touched_files.json
│
└── restore(resume_id) → bool
    ├── "latest" → _find_latest_session()（只选有 session.json 的目录）
    ├── 恢复 history_messages, cost, tool_exec.history, touched_files
    └── 恢复 last_turn_summary, context_summary
```

### 共享 Agent Loop

**文件**：`src/airouter/engine/agent/loop.py`

`run` 和 `agent` 共用同一套 agent loop：

```python
run_agent_loop(
    adapter, model_entry, messages, workdir, allowed_tools, config,
    existing_tool_exec=None,      # REPL 续接时传入
    existing_cost=None,           # REPL 续接时传入
    on_tool_call=None,            # 工具调用后回调
    on_turn_start=None,           # 模型调用前回调（spinner）
) → LoopResult
```

**LoopResult 关键字段**：
- `new_tool_history`: 仅本轮新增的工具调用（用于持久化 tools.jsonl）
- `cost_delta_cny`: 本轮新增成本（cost_after - cost_before）
- `messages`: 完整运行时消息（含 system + history + 当前轮）

### 上下文压缩

`_get_history_messages()` 在消息 token 数超过阈值（60k）时自动触发：

```
1. _split_into_blocks(history) → 按 user message 切分为 turn blocks
2. 保留最近 4 个 blocks
3. 旧 blocks → _summarize_blocks()（按价格选择最便宜且 Key 可用的模型生成摘要）
4. 组装 [summary] + recent_blocks
5. _remove_orphan_tool_messages() → 确保无孤立 tool message
```

摘要优先调用已配置的轻量模型，Token 和费用会记入当前 `CostSummary`。如果相应提供商没有 API Key，则尝试下一个轻量模型；全部不可用时使用本地截断摘要。

### PE/PER 在 REPL 中的边界

`AgentSession` 会保留 Router 的 `PLAN_EXECUTE` / `PLAN_EXECUTE_REVIEW` 判断并向用户提示，但交互式 REPL 当前只执行单模型 Agent Loop。完整 Planner → Executor → Reviewer 多模型协作只在一次性 `ai-router run` 中实现。

### Session 目录结构

```
.airouter/sessions/<session_id>/
  session.json              # 元数据
  messages.current.json     # 对话历史（不含 system prompt）
  events.jsonl              # 审计日志
  tools.jsonl               # 工具调用记录
  cost.json                 # 累积成本
  touched_files.json        # 被修改的文件列表
```

### run vs agent 对比

| 特性 | `run` | `agent` |
|------|-------|---------|
| 交互方式 | 单次输入 | REPL 多轮对话 |
| 上下文 | 无历史 | 累积 history_messages |
| 模型确认 | 仅高风险确认 | 首轮确认 + 高风险确认 |
| 持久化 | 无 | session 目录 |
| 会话恢复 | 不支持 | `--resume` |
| 上下文压缩 | 不需要 | 自动 + `/compact` |
| 默认 max_turns | 10 | 30 |
| 默认 max_cost | 1.0 | 5.0 |
| Slash 命令 | 无 | 8 个 |

---

## 9. Agent 子系统详解

**目录**：`src/airouter/engine/agent/`

### 文件清单

| 文件 | 职责 |
|------|------|
| `executor.py` | 主执行器：路由、目标构建、Agent 循环、Plan-Execute-Review |
| `loop.py` | 共享 agent loop（run 和 agent 共用） |
| `session.py` | AgentSession：REPL 管理、持久化、slash 命令、上下文压缩 |
| `goal.py` | ExecutionGoal 数据类 + GoalBuilder 构建器 |
| `report.py` | ExecutionReport 数据类 + CostSummary 成本追踪 |
| `tools.py` | 4 个工具定义 + ToolExecutor + ToolCallRecord |
| `safety.py` | SafetyGate 安全门 + SafetyConfig |
| `text_parser.py` | TextToolParser 文本格式工具调用解析（fallback） |

---

### 9.1 executor.py — AgentExecutor

**构造函数**：
```python
def __init__(self, router: Router, factory: AdapterFactory,
             registry: ModelRegistry, config: AgentConfig | None = None)
```

**核心方法**：`run(task: str, workdir: Path) -> ExecutionReport`

#### run() 完整流程

```
run(task, workdir)
  → _route(task)                    ← router.route(task)
  → GoalBuilder.build(decision, task, workdir, ...)
  → dry_run? → _dry_run_report()
  → requires_approval? → 等待 y/N → 取消则 make_cancelled()
  → 策略分发：
      PE/PER → _run_plan_execute()
      其他   → _run_single_agent()
```

#### _run_single_agent() — 单模型 Agent 循环

1. 获取 adapter + SafetyGate + ToolExecutor + CostSummary
2. 过滤 TOOL_DEFINITIONS 为 allowed_tools
3. 构建 system prompt（AGENT_SYSTEM_PROMPT.format()）
4. 初始化 messages = [system, user]
5. **Agent 循环**（最多 max_turns 轮）：
   - `adapter.chat(model, messages, tools, tool_choice="auto")`
   - `cost.record(model_entry, response)`
   - 提取 tool_calls（优先原生 function calling，回退 TextToolParser）
   - 追加 assistant 消息
   - 无 tool_calls → 任务完成，break
   - 成本检查：超限则停止
   - `tool_exec.execute(tool_calls)` → 追加 tool 结果
6. max_turns 耗尽 → 使用最后内容
7. `_compute_agent_baseline(cost)` 计算基线
8. 返回 ExecutionReport

**关键设计点**：
- 工具调用提取的双路径：原生 function calling → TextToolParser fallback
- 每次 chat 后立即 cost.record()
- 成本检查在工具执行之前

#### _run_plan_execute() — Plan-Execute-Review

```
统一 CostSummary 贯穿三阶段：
  Phase 1: _planning_phase(goal, planner_name, cost) → plan 文本
  Phase 2: _execution_phase(goal, decision, executor_name, plan, cost) → report
  Phase 3: (仅 PER) _review_phase(goal, reviewer_name, response, history, cost)
           → review_text + review_passed
  → _compute_agent_baseline(cost)
```

**_planning_phase()**：PLANNER_SYSTEM_PROMPT + 单次 chat → plan 文本。

**_execution_phase()**：与 _run_single_agent 相同，但 system prompt 注入 plan，user message 改为 "请根据执行计划完成任务"。

**_review_phase()**：REVIEWER_SYSTEM_PROMPT + 审查请求（原始任务 + 工具记录 + 最终输出 + 成功标准）→ 单次 chat → review 文本。

#### _parse_review_result()

```python
@staticmethod
def _parse_review_result(review_text: str) -> bool | None:
```

找 "审查结论" 行 → 取下一个非空行 → PASS/通过 → True / NEEDS_FIX/需要修复/不通过 → False / 其他 → None。

三态设计：True=通过，False=失败，None=不干预 success。

#### _build_system_prompt()

AGENT_SYSTEM_PROMPT.format(category, complexity, risk_level, workdir, success_criteria)。

追加 TEXT_TOOL_SYSTEM_PROMPT（JSON 示例中花括号已用 `{{` `}}` 转义）。

#### _dry_run_report()

返回只含路由分析的 report，设置 `dry_run=True`，turns=0，无 tool_history。

#### _compute_agent_baseline()

假设用同 Tier 最贵模型处理相同 Token，成本是多少。用于 savings_vs_baseline 计算。

---

### 9.2 goal.py — ExecutionGoal + GoalBuilder

#### ExecutionGoal

```python
@dataclass
class ExecutionGoal:
    task: str
    category: TaskCategory
    complexity: ComplexityLevel
    risk_level: RiskLevel
    strategy: StrategyType
    success_criteria: list[str]
    allowed_tools: list[str] | None
    constraints: GoalConstraints

@dataclass
class GoalConstraints:
    workdir: Path
    max_cost_cny: float
    max_turns: int
    requires_approval: bool
```

#### GoalBuilder.build()

**max_turns 自动调整**：HIGH 风险 → min 15；COMPLEX/EXPERT → min 12。

**success_criteria 按 TaskCategory 生成**：
- CODE_GENERATION："语法正确且可运行" + "包含错误处理"
- BUG_ANALYSIS："定位到 bug 根因" + "修复后通过相关测试"
- REFACTORING："重构后功能不变" + "通过所有现有测试"
- TEST_GENERATION："测试覆盖目标函数" + "pytest 全部通过"
- CODE_REVIEW："识别出代码问题" + "给出修复建议"
- DOCUMENTATION："文档准确完整" + "格式规范"
- CONVERSATION："回答用户问题"
- HIGH 风险追加："所有变更可在 git diff 中追溯"

**allowed_tools 选择**：
- 基础：read_file + edit_file + run_command
- CODE_GENERATION / REFACTORING / TEST_GENERATION 追加：write_file
- LOW 风险 + SIMPLE：非工程任务移除 run_command；代码生成、审查、重构、缺陷分析、测试生成和 DevOps 仍允许受控验证命令

---

### 9.3 report.py — ExecutionReport + CostSummary

#### CostSummary

```python
@dataclass
class CostSummary:
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cost_cny: float = 0.0
    total_latency_ms: int = 0
    model_costs: dict[str, ModelCostDetail] = field(default_factory=dict)

    def record(self, model_entry, response: AdapterResponse):
        input_cost = response.input_tokens * model_entry.input_price_per_1k / 1000
        output_cost = response.output_tokens * model_entry.output_price_per_1k / 1000
        self.total_cost_cny += input_cost + output_cost
        ...
```

多模型独立追踪（Planner + Executor + Reviewer 各计一笔）。

#### ExecutionReport

```python
@dataclass
class ExecutionReport:
    goal: ExecutionGoal
    decision: RoutingDecision
    final_response: str
    tool_history: list[ToolCallRecord]
    cost: CostSummary
    turns: int
    elapsed_seconds: float
    baseline_cost: float
    plan: str | None = None
    review: str | None = None
    review_passed: bool | None = None
    dry_run: bool = False
    cancelled: bool = False
```

**success 属性**：
```python
if dry_run or cancelled: return False
if not final_response: return False
if tool_history and all(not t.success for t in tool_history): return False
if review_passed is False: return False
return True
```

**make_cancelled()**：静态工厂方法（不用 `cancelled()` 因为和字段名冲突）。

---

### 9.4 tools.py — 工具定义 + ToolExecutor

#### 4 个工具（OpenAI function calling 格式）

| 工具 | 参数 | 说明 |
|------|------|------|
| `read_file` | path, offset?, limit? | 读取文件，支持行范围 |
| `write_file` | path, content | 创建/覆盖，自动备份 .bak |
| `edit_file` | path, old_text, new_text | 精确替换，必须唯一匹配 |
| `run_command` | command | 安全沙箱执行，60s 超时 |

#### ToolExecutor.execute() 流程

对每个 tool_call：
1. 工具白名单检查
2. JSON 参数解析
3. safety.check()
4. _dispatch() → _read_file / _write_file / _edit_file / _run_command
5. 记录到 self.history

**_edit_file 安全机制**：0 匹配→报错，>1 匹配→报错，恰好 1 匹配→替换+备份。

**_run_command 实现**：shlex.split + subprocess.run(shell=False, timeout=60, cwd=workdir)。输出超 8000 字符截断。

---

### 9.5 safety.py — SafetyGate

#### SafetyConfig

```python
allowed_command_prefixes = [
    ("pytest",), ("python", "-m", "pytest"),
    ("ruff", "check"), ("ruff", "format"),
    ("git", "status"), ("git", "log"), ("git", "diff"),
    ("ls",), ("wc",), ("head",), ("tail",),
]

forbidden_patterns = [
    r"rm\s+-rf", r"git\s+push\s+--force", r"DROP\s+TABLE",
    r"sudo\s+", r"chmod\s+777", r"curl.*\|.*sh", ...
]

max_file_size_bytes = 5 * 1024 * 1024  # 5 MB
```

#### check() 三层防御

```
文件操作 → _check_path()：路径不为空 + 路径在 workdir 内

命令执行 →
  第一层：forbidden_patterns 正则匹配 → 危险命令拦截
  第二层：allowed_command_prefixes 白名单 → 不允许的命令
  第三层：路径参数检查 → 绝对路径拦截 + 路径越界拦截
```

---

### 9.6 text_parser.py — TextToolParser

为不支持 OpenAI function calling 的模型提供文本格式 fallback。

**格式**：

```
**文本格式**：
```


tool_name
{"arg1": "value1"}

```

**TEXT_TOOL_SYSTEM_PROMPT**：追加到 AGENT_SYSTEM_PROMPT 末尾，告知模型此格式。JSON 示例中花括号用 `{{` `}}` 转义。

**parse() 方法**：
```python
@staticmethod
def parse(text: str) -> list[dict] | None:
```

正则提取 `

---

## 10. 路由子系统概览

**目录**：`src/airouter/engine/router/`

| 文件 | 类 | 职责 |
|------|-----|------|
| `router.py` | `Router` | 门面类，协调 5 个组件 |
| `analyzer.py` | `TaskAnalyzer` | 规则分析：category, complexity, risk |
| `classifier.py` | `StrategyClassifier` | 候选策略判定 |
| `selector.py` | `ModelSelector` | 模型过滤 + 评分 + 选最优 |
| `gate.py` | `RoutingGate` | 人工审查 + 质量门禁 |
| `estimator.py` | `CostEstimator` | 成本估算 |

### TaskAnalyzer

分析任务文本，提取 TaskFeatures：
- `category`：关键词匹配（"修复"→BUG_ANALYSIS，"重构"→REFACTORING，"测试"→TEST_GENERATION 等）
- `complexity`：SIMPLE/MODERATE/COMPLEX/EXPERT，基于文本特征（长度、关键词、subtask 数）
- `risk_level`：LOW/MEDIUM/HIGH，基于安全关键词（"SQL注入"、"鉴权"等）
- `sensitivity`：敏感数据关键词
- `context_requirement`：LOW/MEDIUM/HIGH/HEAVY/EXTREME
- `reasoning_intensity`：LOW/MEDIUM/HIGH
- `subtask_count`：分号/"以及"/"并且"等分隔符计数

### ComplexityAnalyzer

包装 TaskAnalyzer + ML 后端（OpenSquilla）：
- `mode` 配置："rules"（仅规则）/"opensquilla"（ML 优先）
- ML 模式：先跑规则得到 rule_complexity，再跑 ML 得到 ml_class + probability
- 解决策略：高置信度（>0.7）→ ML 结果覆盖规则；低置信度 → 保留规则
- 输出 ComplexityDiagnostics（mode, rule_complexity, ml_raw_class, ml_final_class, confidence, probabilities, margin, latency_ms）

### StrategyClassifier

根据 TaskFeatures 判定候选策略：
- SIMPLE → [SINGLE_MODEL]
- MODERATE → [SINGLE_MODEL, PLAN_EXECUTE]
- COMPLEX → [SINGLE_MODEL, PLAN_EXECUTE, PLAN_EXECUTE_REVIEW]
- EXPERT → [SINGLE_MODEL, PLAN_EXECUTE, PLAN_EXECUTE_REVIEW]

HIGH 风险自动追加 PLAN_EXECUTE_REVIEW。

### ModelSelector

**过滤链**：
1. `capabilities` 过滤：模型必须支持任务需要的能力（如 function_calling）
2. `allowed_tiers` 过滤：按策略限制 Tier 范围
3. `context_window` 过滤：模型上下文窗口必须够大
4. `sensitivity` 过滤：敏感任务只能用安全认证的模型

**评分**：对每个合格 (strategy, model) 组合，计算 cost_quality_score = quality - cost_penalty * cost_ratio。

**选择**：`select_best_strategy()` 比较所有合格方案的 score，选出最优。

### CostEstimator

根据 model_entry 的价格和预估 Token 数计算成本：
- `input_cost = estimated_input_tokens * input_price_per_1k / 1000`
- `output_cost = estimated_output_tokens * output_price_per_1k / 1000`
- 考虑 cache_read 折扣（如果有）
- baseline_cost = 最贵 Tier 1 模型处理相同 Token 的成本

### RoutingGate

- `requires_human_review`：HIGH 风险 + PE/PER 策略 → True
- `quality_gate`：根据策略和风险生成检查项列表（如 "unit_tests_pass", "security_scan"）
- `fallback_policy`：模型不可用时的降级方案

---

## 11. 公共数据结构

### 枚举类型（`src/airouter/models/enums.py`）

```python
class TaskCategory(str, Enum):
    CODE_GENERATION = "CODE_GENERATION"
    BUG_ANALYSIS = "BUG_ANALYSIS"
    REFACTORING = "REFACTORING"
    TEST_GENERATION = "TEST_GENERATION"
    CODE_REVIEW = "CODE_REVIEW"
    DOCUMENTATION = "DOCUMENTATION"
    CONVERSATION = "CONVERSATION"

class ComplexityLevel(str, Enum):
    SIMPLE = "SIMPLE"
    MODERATE = "MODERATE"
    COMPLEX = "COMPLEX"
    EXPERT = "EXPERT"

class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"

class StrategyType(str, Enum):
    SINGLE_MODEL = "SINGLE_MODEL"
    PLAN_EXECUTE = "PLAN_EXECUTE"
    PLAN_EXECUTE_REVIEW = "PLAN_EXECUTE_REVIEW"
    ESCALATE = "ESCALATE"
```

### 核心数据模型（`src/airouter/models/schemas.py`）

```python
class TaskFeatures(BaseModel):
    category: TaskCategory
    complexity: ComplexityLevel
    risk_level: RiskLevel
    sensitivity: bool = False
    context_requirement: str = "MEDIUM"
    reasoning_intensity: str = "MEDIUM"
    subtask_count: int = 1

class ModelAssignment(BaseModel):
    planner: str | None = None
    executor: str | None = None
    reviewer: str | None = None

class RoutingDecision(BaseModel):
    task_hash: str
    task_features: TaskFeatures
    recommended_strategy: StrategyType
    models: ModelAssignment
    estimated_cost: float
    baseline_cost: float
    estimated_savings: float
    estimated_quality: float
    quality_loss_vs_baseline: float
    risk_level: RiskLevel
    requires_human_review: bool
    reasons: list[str]
    alternatives: list[dict]
    budget_status: str
    quality_gate: list[str]
    fallback_policy: list[str]
    config_version: str
    complexity_analysis: dict | None = None
```

### AdapterResponse（`src/airouter/adapters/base.py`）

```python
@dataclass
class AdapterResponse:
    content: str
    input_tokens: int
    output_tokens: int
    latency_ms: int
    model: str
    tool_calls: list[dict] | None = None
    finish_reason: str | None = None
```

- `tool_calls`：OpenAI function calling 格式的工具调用列表
- `finish_reason`："stop" / "tool_calls" / "length"

### AgentConfig（`src/airouter/engine/agent/executor.py`）

```python
@dataclass
class AgentConfig:
    max_cost_cny: float = 1.0
    max_turns: int = 10
    skip_approval: bool = False
    dry_run: bool = False
```

---

## 12. 配置系统

### AppSettings（pydantic-settings）

**文件**：`src/airouter/config.py`

```python
class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AIROUTER_",
        env_file=".env",
        env_file_encoding="utf-8",
    )

    # API Keys
    dashscope_api_key: str = ""
    deepseek_api_key: str = ""
    zhipu_api_key: str = ""
    kimi_api_key: str = ""
    minimax_api_key: str = ""

    data_dir: Path
    db_url: str
    debug: bool
    opensquilla_bundle_dir: str
```

**环境变量命名规则**：`AIROUTER_` + 字段名大写。例如 `deepseek_api_key` → `AIROUTER_DEEPSEEK_API_KEY`。

**.env 文件**：项目根目录的 `.env` 文件会被自动加载。

### models.yaml

**文件**：`data/models.yaml`

定义所有可用模型的配置：

```yaml
models:
  - name: deepseek-v4-pro
    provider: deepseek
    tier: 1
    api_base: https://token.cvte.com/v1
    input_price_per_1k: 0.003132
    output_price_per_1k: 0.006264
    max_context_window: 1000000
    capabilities: [code_gen, complex_reasoning, code_review]
    allow_sensitive_data: true
    cache:
      supports_prompt_caching: true
      cache_mode: implicit
      cache_read_price_ratio: 0.10
```

每个模型包含：name、provider、tier、API 地址、输入/输出价格、`max_context_window`、capabilities、敏感数据策略和嵌套的 cache 配置。

### load_all()

`AppSettings` 负责环境变量、API Key 和数据目录；`load_all()` 读取 models、routing_rules、budgets、quality_defaults、compression_policy、complexity 等 YAML，返回 `AppConfig`。CLI 命令会分别构造二者。

---

## 13. 错误处理

### CLI 层错误处理

所有 CLI 命令使用 `typer.Exit(code=1)` 退出错误，配合 `console.print("[red]错误：...[/red]")` 显示错误信息。

常见错误场景：
- 参数校验失败（如缺少必填参数、无效值）
- 模型名不存在
- 文件路径不存在
- 数据库连接失败

### Engine 层错误处理

- **路由失败**：Router.route() 返回降级 RoutingDecision（ESCALATE 策略），不抛异常
- **模型调用失败**：Adapter 层把网络、认证、限流和超时异常转换为项目自定义异常并向上抛出
- **工具执行失败**：ToolExecutor 捕获异常，记录到 ToolCallRecord(success=False)，Agent 可以看到错误并调整策略
- **安全拦截**：SafetyGate 抛 SafetyError，ToolExecutor 捕获并记录

### Agent 执行中的容错

- JSON 参数解析失败 → 返回错误消息给模型，模型可能重试
- 工具执行异常 → 返回异常信息，模型可以换方法
- 成本超限 → 停止循环，返回当前结果
- 轮次耗尽 → 停止循环，返回当前结果
- 模型不支持 function calling → TextToolParser fallback

### Adapter 层错误处理

`OpenAICompatAdapter.chat()` 将上游异常转换为：
- `AdapterAuthError`：API Key 无效
- `AdapterRateLimitError`：请求被限流
- `AdapterTimeoutError`：请求超时
- `AdapterError`：其他 API 或响应错误

异常会继续向上抛出，由 Benchmark、`run` 或交互式 `agent` 的执行边界决定是否终止、重试或向用户显示错误。`run` 和 `agent` 的真实执行禁止缺 Key 时静默回退 Mock。
