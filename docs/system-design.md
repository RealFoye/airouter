# AI Router 系统设计方案

> 企业级AI模型智能路由与Token精细化管控系统

---

## 一、项目背景与目标

### 1.1 问题

企业日均Token消耗3~4万美金（6月1日3万美金、6月2日4万美金），且呈上升趋势。核心矛盾：**既要用好模型，又要控制成本**。

### 1.2 解决思路

构建一套**智能路由系统**：
- 输入开发任务描述 → 自动分析任务特征 → 推荐最优模型组合 → 预估成本
- 贵的模型做规划推理，便宜的模型做执行落地
- Token消费透明可审计，浪费模式自动检测

### 1.3 模型无关的分层路由架构

本系统采用模型无关的分层路由架构，不绑定单一厂商。当前 MVP 阶段优先使用国产模型进行验证，将 Qwen、DeepSeek、GLM 等模型映射为 Tier 1 / Tier 2 / Tier 3 三个能力层级，用于复现企业中"强模型规划、低成本模型执行"的成本优化思路。后续可通过统一 Adapter 无缝接入 Claude、GPT、OpenRouter、LiteLLM 等模型源。

| 层级 | 角色 | MVP 验证模型 | 扩展模型 | 适用场景 |
|------|------|-------------|----------|----------|
| **Tier 1（重型）** | 规划、架构、复杂推理 | `qwen3.7-max`、`deepseek-v4-pro` | Claude Opus、GPT-4.1 | 任务分解、代码审查、架构设计、复杂Bug |
| **Tier 2（标准）** | 通用编码、文档生成 | `qwen3.7-plus`、`glm-5.1` | Claude Sonnet、GPT-4.1-mini | 标准代码生成、重构、文档 |
| **Tier 3（快速）** | 执行、批量、简单任务 | `deepseek-v4-flash` | Claude Haiku、GPT-4.1-nano | 代码补全、格式化、批量转换、测试生成 |

**分层执行策略：**
- COMPLEX/EXPERT任务 → Tier 1模型出执行计划 → Tier 3模型逐步执行 → **目标在可拆解、可验证的复杂任务中观察到20-60%成本下降**（具体取决于任务可拆解性和上下文局部化比例，详见4.5.3节）
- MODERATE任务 → Tier 2模型单模型处理（最佳性价比）
- SIMPLE任务 → Tier 3模型直接处理（最低成本）

### 1.4 Week 1 交付物覆盖

第 1 周交付物是可用于架构 Review 的《系统设计文档》，本文作为权威设计文档，配套调研材料如下：

| PDF 要求 | 覆盖位置 | 说明 |
|----------|----------|------|
| 竞品调研 | `docs/competitive-analysis.md` | OpenRouter / LiteLLM / Helicone / Langfuse / Claude Code 用量体系对比 |
| 6+ 大模型定价与统一成本模型 | `docs/competitive-analysis.md` + 本文 4.5 | 覆盖 Anthropic、OpenAI、DeepSeek、Gemini 与 MVP 国产模型配置 |
| Claude Prompt Caching / Extended Thinking / Batch API | `docs/competitive-analysis.md` 第五章 + 本文 4.5.2 | 记录适用场景、成本公式和决策树 |
| 任务分类体系 | 本文 4.1 | 13 维特征、10 类任务、4 级复杂度、能力需求映射 |
| 路由引擎架构与算法伪代码 | 本文第二章、第四章 | 五层决策架构、硬约束、评分、门禁、fallback |
| Token 采集与审计架构 | 本文第十章、7.2 | routing_decisions + execution_feedback + audit 查询链路 |
| 技术选型 | 本文第三章 | 选型表、对比决策、风险缓解 |
| 接口定义 | 本文 2.3、7.x CLI 设计 | REST API 摘要 + CLI 命令契约 |

> 说明：Prompt Caching 命中率、延迟、质量影响等“实测数据”需要真实 API 配额与运行样本。Week 1 交付先完成公式、实验方案和记录字段；Week 2-3 通过 Benchmark 与执行反馈补齐实测数据。

---

## 二、系统架构

### 2.1 整体架构

```
┌─────────────────────────────────────────────────────┐
│                Web Dashboard (Streamlit)             │
│   路由工作台 │ 消费看板 │ 优化中心 │ 规则管理       │
└────────────────────────┬────────────────────────────┘
                         │ HTTP
┌────────────────────────▼────────────────────────────┐
│                FastAPI Backend (REST API)             │
│   /api/route │ /api/audit │ /api/benchmark │ /api/rules │
└──┬──────────────┬──────────────┬────────────────────┘
   │              │              │
┌──▼──────┐  ┌───▼──────┐  ┌───▼──────────┐
│  Router │  │  Audit   │  │  Benchmark   │
│  Engine │  │  Engine  │  │  Engine      │
│         │  │          │  │              │
│ Analyzer│  │Collector │  │ Runner       │
│ Classify│  │Aggregate │  │ Evaluator    │
│ Select  │  │Detect    │  │ Generator    │
│ Estimate│  │Attribute │  │ Reporter     │
└──┬──────┘  └───┬──────┘  └───┬──────────┘
   │              │              │
   └──────┬───────┴──────────────┘
          │
┌─────────▼──────────────────────────┐
│      Model Adapter Layer            │
│    (OpenAI-compatible SDK)          │
└──┬──────┬──────┬──────┬────────────┘
   │      │      │      │
DeepSeek Qwen   GLM   (未来扩展)
   │
┌──▼─────────────────────────────────┐
│      SQLite Database (SQLAlchemy)   │
│  routing_decisions │ execution_feedback │ benchmark_results │ config_snapshots │
└────────────────────────────────────┘
```

> **注意：** 模型配置、路由规则、预算配置等存储在YAML文件中，不进入数据库。详见[第十章：数据存储设计](#十数据存储设计)。

### 2.2 数据流：五层决策架构

```
用户输入任务描述
    ↓
第1层：任务画像
    TaskAnalyzer 提取13维特征
    (类别/复杂度/风险/敏感性/可验证性/输出严格度/上下文/推理强度/Token预估/能力需求/子任务)
    ↓
第2层：硬约束过滤
    排除不可用模型：能力覆盖率 < 阈值、Tier不在允许范围、上下文窗口不足、
    数据敏感限制、预算超限
    ↓
第3层：策略候选生成
    生成可行策略组合：SINGLE_MODEL / GUIDED_EXECUTE / PLAN_EXECUTE / PLAN_EXECUTE_REVIEW
    每个策略绑定具体模型组合，通过Top-K控制避免组合爆炸
    ↓
第4层：多目标评分
    对每个候选策略计算：能力匹配度 + 成本效率 + 历史质量 + 延迟表现
    权重按任务类型动态调整，成本归一化方式由cost_sensitivity决定
    ↓
第5层：决策输出 + 管控门禁
    预算检查 → 人工审核判断 → 质量门禁 → Fallback策略 → 持久化审计记录
    ↓
输出路由决策JSON：
    推荐策略+模型、成本预估、节省比例、质量风险、推荐理由、
    替代方案、预算状态、审核要求、质量门禁、兜底策略
```

### 2.2.1 当前实现补充：OpenSquilla 与 Web 工作台

截至当前版本，核心路由链路仍然保持“五层决策架构”，但复杂度判断与用户入口已经有两处重要扩展：

1. **复杂度判断增加 OpenSquilla ML 信号**
   - 旧链路：`TaskAnalyzer` 基于规则直接给出 `SIMPLE / MODERATE / COMPLEX / EXPERT`。
   - 新链路：`ComplexityAnalyzer` 在规则结果之外，可选加载 OpenSquilla 的 390 维特征 + BGE embedding + LightGBM/ONNX 推理结果，再把 R0-R3 映射为 AirRouter 四级复杂度。
   - 这只增强“复杂度”这一项任务画像；后续的模型能力过滤、策略生成、成本估算和 Gate 仍由 AirRouter 自己完成。

2. **普通用户入口从管理面板转为 Chat 工作台**
   - `web/app.py` 是当前主要体验：用户输入 API Key 后，像 ChatGPT 一样输入任务，先点“分析”，看到推荐模型/处理方式/成本对比，再决定是否执行。
   - 分析阶段默认走本地 Router + OpenSquilla `opensquilla` 模式；如果 OpenSquilla bundle 或依赖不可用，会回退到规则分析。
   - 执行阶段才调用用户 API Key 对应的真实模型；标题生成、深度复核、上下文压缩也会按需调用模型。
   - 原有 Streamlit 管理页仍保留在“管理员入口”，用于查看高级路由分析、消费审计、Benchmark 结果和治理配置，不是普通用户主流程。

相关文件：

| 能力 | 主要文件 |
|------|----------|
| OpenSquilla 复杂度扩展 | `src/airouter/engine/complexity/analyzer.py`、`src/airouter/engine/complexity/ml_backend.py`、`data/complexity.yaml` |
| OpenSquilla 增量设计 | `docs/system-design-ml-complexity-extension.md` |
| 普通用户 Web 工作台 | `web/app.py`、`src/airouter/web/ui.py` |
| Web 交接说明 | `docs/web-workbench-handoff.md` |

### 2.3 API 接口定义（OpenAPI 摘要）

FastAPI 会自动生成 OpenAPI Spec；本节定义 Week 1 架构评审需要的接口契约，Week 2-3 按此落地实现。

| Method | Path | 用途 | Request | Response |
|--------|------|------|---------|----------|
| GET | `/health` | 健康检查 | - | `{status: "ok"}` |
| POST | `/api/route/analyze` | 任务描述 -> 路由决策 | `RouteAnalyzeRequest` | `RoutingDecision` |
| GET | `/api/models` | 查询模型注册表 | `tier? provider? capability?` | `ModelConfig[]` |
| POST | `/api/feedback` | 写入执行反馈 | `ExecutionFeedbackCreate` | `ExecutionFeedback` |
| POST | `/api/audit/query` | 消费聚合查询 | `AuditQueryRequest` | `AuditSummary` |
| GET | `/api/audit/waste-patterns` | Top N 浪费模式 | `days, project_id?, user_id?` | `WastePattern[]` |
| POST | `/api/optimize/prompt` | Prompt/上下文优化建议 | `OptimizeRequest` | `OptimizeResult` |
| GET | `/api/benchmark/results` | Benchmark 结果查询 | `suite_name?, task_type?` | `BenchmarkResult[]` |
| GET | `/api/rules` | 读取路由规则 | - | `RoutingRulesSnapshot` |
| POST | `/api/rules/draft` | 生成规则变更草案 | `RuleDraftRequest` | `RuleDraft` |

核心请求/响应对象：

```python
class RouteAnalyzeRequest(BaseModel):
    task_description: str
    user_id: str | None = None
    project_id: str = "default"
    department: str | None = None
    client_type: str = "cli"
    max_cost_cny: float | None = None
    quality_requirement: float | None = None
    allow_human_review: bool = True

class AuditQueryRequest(BaseModel):
    start_date: date
    end_date: date
    group_by: list[str]  # day/user/department/project/model/task_type/client_type
    filters: dict[str, str] = {}
    use_actual_when_available: bool = True

class OptimizeRequest(BaseModel):
    prompt: str | None = None
    prompt_path: str | None = None
    model_name: str | None = None
    scenario: str = "SINGLE_TURN"
    expected_turns: int = 1
```

接口设计原则：

- API 返回的 `RoutingDecision` 与 CLI JSON 输出使用同一 Pydantic schema，避免两套契约。
- 所有成本相关响应必须带 `estimated` / `actual` 标识。
- 写反馈接口只追加，不修改原始路由决策，保证审计不可抵赖。
- 规则变更先生成 draft，不自动应用；管理员批准后才进入配置版本。

---

## 三、技术选型

| 组件 | 选择 | 理由 |
|------|------|------|
| **后端框架** | FastAPI | 异步支持、自动生成OpenAPI文档、Pydantic原生集成 |
| **前端** | Streamlit | Python原生零前端代码、内置图表组件、开发速度最快 |
| **CLI** | Typer | 类型提示驱动、基于Click、现代简洁 |
| **数据库** | SQLite + SQLAlchemy | 零配置部署简单、ORM支持无缝迁移PostgreSQL |
| **模型客户端** | openai Python SDK | 所有国产模型均支持OpenAI兼容API，一个SDK统一调用 |
| **测试** | pytest + pytest-asyncio | 标准Python测试方案 |
| **部署** | Docker Compose | `docker-compose up` 一键启动全部服务 |
| **配置** | Pydantic Settings | 环境变量 + YAML配置统一管理 |

### 为什么选Streamlit而非React/Vue？

- **4周时间紧迫**，引擎质量远比UI重要（评分中架构15%+路由20%+工程20%=55%，UI无独立评分项）
- Streamlit零前端代码，所有UI用Python写，节省至少5天开发时间
- 内置st.line_chart/st.bar_chart/st.dataframe，消费看板开箱即用
- 如果Week 3提前完成核心功能，可以再迁移到React（但优先级低）

### 3.1 选型对比与决策依据

| 维度 | 候选 | 最终选择 | 决策依据 |
|------|------|----------|----------|
| 后端 | FastAPI / Flask / Django / Go Fiber | FastAPI | Pydantic schema 与 OpenAPI 原生契合，适合快速暴露路由、审计、Benchmark API |
| 前端 | Streamlit / React / Vue / Next.js | Streamlit | 4 周交付优先验证路由和看板，Streamlit 能用 Python 直接复用 engine/service 层 |
| 数据库 | SQLite / PostgreSQL / ClickHouse | SQLite 起步，保留 PostgreSQL 迁移口 | MVP 调用量低，审计查询可控；SQLAlchemy 保留迁移空间 |
| 模型接入 | openai SDK / 各供应商 SDK / LiteLLM | openai SDK + Adapter | 国产模型大多支持 OpenAI-compatible API；后续可加 LiteLLM/OpenRouter adapter |
| 配置 | YAML / DB 管理后台 / 远程配置中心 | YAML | Week 1-2 规则频繁迭代，Git diff 可审查；Week 3 管理后台先做只读/草案 |
| 可观测性 | 自研 SQLite 聚合 / Langfuse / Helicone | MVP 自研，后续可接 Langfuse/Helicone | 当前核心是路由与审计闭环，不先引入外部平台复杂度 |

### 3.2 技术风险与缓解

| 风险 | 影响 | 缓解策略 |
|------|------|----------|
| Streamlit 不适合复杂权限/交互 | Week 3 Web 工作台扩展受限 | MVP 只做内部管控台；API 与 engine 分层清楚，未来可换 React |
| SQLite 写入并发有限 | 多用户高频调用时写锁竞争 | MVP 使用单机 SQLite；生产迁移 PostgreSQL，接口层不变 |
| 供应商价格和缓存语义变化 | 成本预估失真 | 所有价格进入 `models.yaml` 和 `config_snapshots`；审计时展示配置版本 |
| 规则分类冷启动不准 | 推荐质量波动 | 先规则可解释，Week 2-3 用 Benchmark 和 feedback 校准 |
| 外部 API 不可用 | Demo/测试阻塞 | MockAdapter + 离线 Benchmark + 预缓存演示数据 |

---

## 四、路由引擎核心算法

### 设计原则

路由**策略选择和评分**不依赖 LLM 判断，而是采用"**硬约束过滤 + 策略候选生成 + 多目标评分 + 预算/审核门禁 + 可审计反馈**"的五阶段算法。LLM 仅作为可选的任务特征提取器（TaskAnalyzer的LLM模式）；即使LLM不可用，系统仍可通过关键词/规则模式完成特征提取和路由决策。系统冷启动时通过规则+先验值运行，后续通过 Benchmark 数据渐进校准延迟和质量估计。

---

### 4.1 任务画像（13维特征）

#### 4.1.1 任务分类体系（4维度 × 10类别 × 4级别）

**维度1：任务类别**

| 类别 | 说明 | 典型任务 |
|------|------|----------|
| CODE_GENERATION | 从需求写新代码 | "写一个FastAPI的用户认证中间件" |
| CODE_REVIEW | 审查/审计代码 | "审查这段代码的安全漏洞" |
| REFACTORING | 重构已有代码 | "将这个God Class拆分为策略模式" |
| BUG_ANALYSIS | 诊断和修复Bug | "分析这个并发死锁问题" |
| DOCUMENTATION | 生成文档 | "为这个API生成OpenAPI文档" |
| ARCHITECTURE | 系统设计 | "设计一个支持百万并发的消息推送系统" |
| TEST_GENERATION | 编写测试 | "为这个用户服务写单元测试" |
| DATA_PROCESSING | 数据处理脚本 | "写一个ETL脚本处理CSV数据" |
| DEVOPS | 运维配置 | "编写Docker Compose部署方案" |
| CONVERSATION | 问答/解释 | "解释Python的GIL是什么" |

**维度2：复杂度**
- SIMPLE：单文件、明确需求、<100行输出
- MODERATE：多文件、有些模糊、100-500行输出
- COMPLEX：跨模块、架构决策、>500行输出
- EXPERT：系统级、深度领域知识、多步推理

**维度3：上下文需求**
- MINIMAL：任务自包含，<2K tokens
- STANDARD：需要相关文件内容，2K-10K tokens
- HEAVY：需要多文件代码理解，10K-50K tokens
- EXTREME：需要完整项目上下文，>50K tokens（触发上下文工程）

**维度4：推理强度**
- LOW：模式匹配、模板填充
- MEDIUM：标准逻辑、API使用
- HIGH：复杂逻辑、优化、安全分析
- VERY_HIGH：新算法、跨领域推理

#### 4.1.2 完整 TaskFeatures 定义

```python
class TaskFeatures:
    # 基础分类
    category: TaskCategory                    # 10种类别之一
    complexity: ComplexityLevel               # SIMPLE/MODERATE/COMPLEX/EXPERT

    # 风险与约束
    risk_level: RiskLevel                     # LOW/MEDIUM/HIGH — 综合风险（含业务风险+执行风险+返工成本）
    sensitivity: SensitivityLevel             # LOW/MEDIUM/HIGH — 数据敏感性（权限/财务/个人隐私等）
    verifiability: VerifiabilityLevel         # LOW/MEDIUM/HIGH — 结果是否可自动验证
    output_strictness: OutputStrictnessLevel  # LOW/MEDIUM/HIGH — 输出格式严格程度

    # 资源需求
    context_requirement: ContextLevel         # MINIMAL/STANDARD/HEAVY/EXTREME
    reasoning_intensity: ReasoningLevel       # LOW/MEDIUM/HIGH/VERY_HIGH
    estimated_input_tokens: int               # 预估输入Token数
    estimated_output_tokens: int              # 预估输出Token数

    # 结构特征
    subtasks: list[str]                       # 可分解的子任务列表（COMPLEX/EXPERT任务）
    required_capabilities: set[str]           # 必须具备的能力集合
    preferred_capabilities: set[str]          # 加分能力集合
```

**关键区分：** `risk_level` 是综合风险等级（模型输出错误后的业务影响、执行影响、外发/写入/生产变更和返工成本），`sensitivity` 专指数据敏感性（是否包含真实个人信息、密钥、财务/薪资等数据本体），`verifiability` 指结果能否通过自动手段验证，`output_strictness` 指输出格式要求的严格程度。

`sensitivity` 不能只靠关键词硬判。比如“写一个手机号格式化函数”只是代码示例，不等同于处理真实客户手机号；“批量脱敏客户手机号”是高敏数据处理，但如果不外发、不写生产，可以通过 `privacy_check` 自动执行；“导出全部客户手机号发给外部供应商”才是高敏 + 高风险，需要人工确认。

**示例对比：**

| 任务 | risk_level | sensitivity | verifiability | output_strictness |
|------|------------|-------------|---------------|-------------------|
| 写日报总结 | LOW | LOW | MEDIUM | LOW |
| 生成JSON配置 | MEDIUM | LOW | HIGH | HIGH |
| SQL迁移脚本 | HIGH | MEDIUM | HIGH | HIGH |
| 架构设计文档 | HIGH | LOW | LOW | MEDIUM |
| 权限模块修改 | HIGH | HIGH | MEDIUM | MEDIUM |
| 手机号格式化函数 | LOW | LOW | HIGH | MEDIUM |
| 客户手机号批量脱敏 | MEDIUM | HIGH | HIGH | HIGH |
| 客户手机号外发供应商 | HIGH | HIGH | MEDIUM | HIGH |

#### 4.1.3 特征提取（双模式）

**LLM模式（精确）**：用Tier 1模型提取结构化特征JSON，用于复杂任务或规则模式不确定时。MVP不承诺固定延迟，实际延迟取决于模型API响应速度。

**关键词模式（快速，默认）**：基于规则的启发式分类，延迟<10ms。作为默认模式和API不可用时的fallback。
```python
KEYWORD_RULES = {
    "ARCHITECTURE": ["设计", "架构", "系统", "微服务", "分布式"],
    "BUG_ANALYSIS": ["bug", "错误", "异常", "修复", "debug", "报错"],
    "CODE_REVIEW": ["审查", "review", "代码质量", "安全检查"],
    ...
}
```

#### 4.1.4 OpenSquilla ML 复杂度增强

OpenSquilla 接入后，AirRouter 的复杂度判断不再只有“关键词规则”一条路。当前实现把复杂度分析抽象为 `ComplexityAnalyzer`，支持四种 mode：

| mode | ML 加载 | 路由行为 | 适用场景 |
|------|---------|----------|----------|
| `rules` | 否 | 纯规则判断复杂度 | 默认配置、生产保守模式 |
| `shadow` | 是 | 规则结果生效，ML 只记录诊断 | 观察 ML 与规则差异，不改变路由 |
| `opensquilla` | 是 | 使用 OpenSquilla `final_route_class` 替换复杂度 | Web 分析体验、离线实验、演示 |
| `hybrid` | 是 | 使用 `raw_route_class` 在高置信时只升级不降级 | 生产增强候选，需要继续灰度验证 |

OpenSquilla 的 R0-R3 与 AirRouter 复杂度映射如下：

| OpenSquilla route class | AirRouter complexity | 常规候选 Tier |
|-------------------------|----------------------|---------------|
| R0 | SIMPLE | Tier 3 |
| R1 | MODERATE | Tier 2 / Tier 3 |
| R2 | COMPLEX | Tier 1 / Tier 2 |
| R3 | EXPERT | Tier 1 |

**边界说明：**

- OpenSquilla 只决定复杂度，不直接决定最终模型。
- 最终模型仍由 `ModelSelector` 根据能力、敏感性、上下文窗口、价格、质量先验和 Gate 共同决定。
- `ml_raw` / `ml_final` 不能绕过预算、敏感数据策略、人工确认和质量门禁。
- 当前 `data/complexity.yaml` 默认仍是 `rules`，因为 OpenSquilla 对 Engineering 任务有明显价值，但在 L1 普通任务上会产生过度升级；Web 工作台为了展示更强的语义分析能力，会在 `_run_analysis()` 中显式使用 `opensquilla`，不可用时回退 rules。
- 更详细的特征空间、bundle 校验、失败降级和四种 mode 语义见 `docs/system-design-ml-complexity-extension.md`。

#### 4.1.5 分类体系到模型推荐映射

任务分类不是为了展示标签，而是直接决定候选 Tier、预算、质量门禁和是否需要人工批准。

| 任务画像 | 典型任务 | 推荐策略 | 推荐 Tier | Token 预估 | 质量/管控要求 |
|----------|----------|----------|-----------|------------|---------------|
| SIMPLE + LOW risk + HIGH verifiability | 写回文函数、格式转换、简单单测 | SINGLE_MODEL | Tier 3 | 1K-3K input / 0.3K-1K output | syntax_check / ast_parse |
| SIMPLE + HIGH risk | 删除生产数据脚本、权限配置修改 | SINGLE_MODEL + pre-execution approval | Tier 2/Tier 1 | 1K-5K / 0.5K-2K | 人工批准 + human_review gate |
| MODERATE + MEDIUM risk | 重构登录模块、生成 API 文档 | SINGLE_MODEL | Tier 2 | 5K-15K / 1K-4K | 自动验证 + 可选 LLM judge |
| COMPLEX + HIGH reasoning | 并发 Bug 分析、跨模块重构 | PLAN_EXECUTE 或 Tier 1 SINGLE_MODEL | Tier 1 规划，Tier 2/3 执行 | 15K-50K / 3K-10K | fix_verification + human_review |
| ARCHITECTURE + LOW verifiability | 百万并发系统设计、微服务拆分 | PLAN_EXECUTE_REVIEW | Tier 1 + reviewer | 10K-30K / 4K-12K | llm_judge + human_review |
| HEAVY/EXTREME context | 全项目审查、长上下文代码理解 | 先 Context Budget，再路由 | Tier 1/Tier 2 | 50K+ input | 上下文裁剪日志 + 回退策略 |
| DOCUMENTATION 批量任务 | 批量生成 README/API 文档 | Batch + Tier 2/Tier 3 | Tier 2/3 | 单任务 3K-10K | 可走 Batch，允许较高延迟 |

---

### 4.2 第一层：硬约束过滤

目的：排除不可用模型，确保低成本模型不会突破安全边界。**分数再高，也不能突破硬约束。**

#### 4.2.1 能力覆盖率过滤

能力匹配采用 `required` / `preferred` 双层覆盖：

```python
def capability_score(model, task_features):
    # required_capabilities：必须具备，缺失则淘汰
    required = task_features.required_capabilities
    matched_required = model.capabilities & required

    # 带权重的覆盖率
    weights = {"code_gen": 0.3, "complex_reasoning": 0.3, "architecture": 0.2, ...}
    required_coverage = (
        sum(weights[c] for c in matched_required)
        / sum(weights[c] for c in required)
    )

    # preferred_capabilities：加分项，上限0.05，仅作tie-breaker
    preferred = task_features.preferred_capabilities
    matched_preferred = model.capabilities & preferred
    preferred_bonus = min(0.05, len(matched_preferred) * 0.01)
    preferred_coverage = (
        len(matched_preferred) / len(preferred) if preferred else 0.0
    )

    # 高风险任务必须100%覆盖required，低风险允许部分缺失
    min_coverage = MIN_COVERAGE_BY_COMPLEXITY[task_features.complexity]
    if required_coverage < min_coverage:
        return 0.0  # 淘汰

    return 0.85 * required_coverage + 0.15 * preferred_coverage + preferred_bonus
```

**最低覆盖率阈值：**

| 复杂度/风险 | 最低覆盖率 | 逻辑 |
|-------------|-----------|------|
| SIMPLE | 0.50 | 简单任务容忍能力不足 |
| MODERATE | 0.70 | 需要基本能力匹配 |
| COMPLEX | 0.85 | 需要较强能力覆盖 |
| EXPERT | 1.00 | 必须完全覆盖 |

**能力需求映射表：**

```python
CAPABILITY_REQUIREMENTS = {
    # (category, complexity) → (required, preferred)
    ("CODE_GENERATION", "SIMPLE"):   ({"code_gen"}, {"documentation"}),
    ("CODE_GENERATION", "COMPLEX"):  ({"code_gen", "complex_reasoning"}, {"architecture"}),
    ("BUG_ANALYSIS", "COMPLEX"):     ({"code_gen", "complex_reasoning"}, {"code_review"}),
    ("ARCHITECTURE", "EXPERT"):      ({"architecture", "complex_reasoning"}, {"security", "scalability"}),
    ...
}
```

#### 4.2.2 允许Tier过滤

不同复杂度/风险的任务只允许使用特定层级的模型：

```yaml
allowed_tiers:
  SIMPLE:
    default: [3]
    high_risk: [2, 3]
  MODERATE:
    default: [2, 3]
    high_risk: [1, 2]
  COMPLEX:
    default: [1, 2]
  EXPERT:
    default: [1]
```

**敏感数据兜底规则：** 如果任务被判为 `sensitivity == HIGH`，而复杂度规则只允许 Tier 3，Selector 会临时把 Tier 2 加入候选池。原因是部分 Tier 3 模型不允许处理敏感数据，若仍只允许 Tier 3，会把“内部手机号脱敏 / 清洗 / 校验”这类可自动处理的任务误判为无候选、需要人工复核。真正需要人工确认的是 `sensitivity == HIGH` 且 `risk_level == HIGH`，例如外发客户信息、生产写入、权限变更或不可逆操作。

#### 4.2.3 完整硬约束清单

```python
def filter_candidates(all_models, features):
    constraints = build_constraints(features)
    candidates = []
    for model in all_models:
        # 1. 能力覆盖率
        if capability_score(model, features) < constraints.min_capability_coverage:
            continue
        # 2. 允许Tier
        if model.tier not in constraints.allowed_tiers:
            continue
        # 3. 上下文窗口
        if model.max_context_window < features.estimated_input_tokens:
            continue
        # 4. 数据敏感性
        if features.sensitivity == "HIGH" and not model.allow_sensitive_data:
            continue
        # 5. 预算约束（两层：soft warning + hard approval，均不直接排除）
        estimated_cost = estimate_single_cost(model, features)
        if estimated_cost > constraints.hard_budget_limit:
            model.budget_status = "OVER_HARD_BUDGET"
            model.requires_approval = True  # 硬预算：不可自动执行，需审批
        elif estimated_cost > constraints.soft_budget_limit:
            model.budget_status = "WARNING"  # 软预算：标记预警但仍保留为候选
        else:
            model.budget_status = "OK"
        candidates.append(model)

    if not candidates:
        return fallback_to_human_review(features)
    return candidates
```

---

### 4.3 第二层：策略候选生成

#### 4.3.1 四种策略定义

| 策略 | 定义 | 适用场景 | 执行模型选择 |
|------|------|----------|-------------|
| **SINGLE_MODEL** | 单模型端到端 | SIMPLE任务，或低风险MODERATE | 评分最高的候选模型 |
| **GUIDED_EXECUTE** | Tier 2执行 + Tier 1审查 | MODERATE + 高风险/大输出量 | Tier 2模型执行 |
| **PLAN_EXECUTE** | Tier 1规划 + Tier 2/3执行 | COMPLEX + 可拆解 + 可验证 | 根据风险选Tier 2或3 |
| **PLAN_EXECUTE_REVIEW** | Tier 1规划 + Tier 2/3执行 + Tier 1审查 | COMPLEX/EXPERT + 高风险 | 根据风险选Tier 2或3 |

**PLAN_EXECUTE / PLAN_EXECUTE_REVIEW 的执行模型选择：**

| 风险等级 | 执行模型 | 理由 |
|----------|---------|------|
| LOW | Tier 3 | 低风险，最经济 |
| MEDIUM | Tier 2 | 平衡成本与质量 |
| HIGH | Tier 2（不建议Tier 3） | 即使有审查，Tier 3执行高风险任务仍不可靠 |

**角色级能力过滤（实现说明）：**
- planner/reviewer/single：使用任务级 `capability_score()`（全局能力需求）
- executor：使用 `EXECUTOR_CAPABILITY_REQUIREMENTS`（只检查执行级能力，如 `code_gen`，不要求 `architecture` 等全局能力）
- 这样 ARCHITECTURE 类任务的 PER 策略不会被"executor 缺 architecture 能力"误杀

#### 4.3.2 策略触发条件

> **实现说明**：触发条件判断由独立的 `StrategyClassifier` 模块完成（`classifier.py`），
> 只负责结构条件（输入 TaskFeatures，输出 ClassificationResult）。
> 成本节省率和质量损失率不在 Classifier 中判断，而是在 Selector 的 post-filter 阶段做硬性排除。

```python
class StrategyClassifier:
    def classify(self, features: TaskFeatures) -> ClassificationResult:
        # SINGLE_MODEL 始终包含
        # Plan-Execute: 5 个结构条件
        # Guided Execute: 4 个结构条件
        # PER: base_decomposable AND review_need
        ...
```

**Plan-Execute 触发条件（结构条件，必须全部满足）：**
1. `complexity` ∈ {COMPLEX, EXPERT}
2. `estimated_output_tokens` ≥ 500（输出量足够大，规划开销才值得）
3. `reasoning_intensity` ∈ {HIGH, VERY_HIGH}
4. `subtasks` 数量 ≥ 2（任务可分解）
5. `verifiability` ≥ MEDIUM 或 `risk_level` == LOW（结果可验证或风险低）

**Selector post-filter 硬性排除（在策略候选生成后执行）：**
6. 预估成本节省率 < 15%（相对 Tier 1 baseline，非 SINGLE 策略）
7. 预估质量损失 > 15%（相对候选集最高质量）

**Plan-Execute 最适合的不是"复杂任务"，而是：复杂但可拆解、执行步骤明确、输出量大、结果可验证、执行风险不高的任务。**

**Guided Execute 触发条件（结构条件）：**
1. `complexity` ∈ {MODERATE, COMPLEX}
2. `estimated_output_tokens` ≥ 800
3. `risk_level` != LOW（低风险不需要审查开销）
4. `verifiability` != LOW 或 `risk_level` != HIGH（不能同时低可验证+高风险）

> Selector post-filter 还会排除节省率 < 15% 的 Guided Execute 候选。

**Plan-Execute-Review 触发条件：**
- base_decomposable（Plan-Execute 条件 1-4）AND review_need：
  - `risk_level` == HIGH，或
  - `verifiability` == LOW，或
  - `category` 在 `human_review_required_tasks` 列表中

#### 4.3.3 Top-K 控制避免组合爆炸

每个角色模型池内按Tier做Top-K筛选，避免 planner × executor × reviewer 组合爆炸：

```python
# 在每个角色池内做 Top-K（不是全局）
for role in ["planner", "executor", "reviewer", "single"]:
    role_pool[role] = select_top_k_per_tier(role_pool[role], features)
```

```yaml
top_k_by_tier:
  tier1:
    k: 2
    pre_score:
      capability: 0.50
      quality: 0.35
      cost: 0.15
  tier2:
    k: 2
    pre_score:
      capability: 0.40
      quality: 0.30
      cost: 0.30
  tier3:
    k: 2
    pre_score:
      capability: 0.30
      quality: 0.20
      cost: 0.50
```

不同Tier的pre_score权重反映该层定位：Tier 1看重能力和质量，Tier 3看重成本。

---

### 4.4 第三层：多目标评分

对每个候选策略（策略类型 + 具体模型组合）计算四维得分：

```
Score(strategy) = w_capability × capability + w_cost × cost + w_quality × quality + w_latency × latency
```

**权重按任务类型动态调整：**

```yaml
routing_weights:
  default:
    capability: 0.35
    cost: 0.30
    quality: 0.20
    latency: 0.15
  ARCHITECTURE:           # 架构设计：质量 > 成本
    capability: 0.40
    quality: 0.35
    cost: 0.15
    latency: 0.10
  TEST_GENERATION:        # 测试生成：成本 > 质量
    capability: 0.25
    cost: 0.40
    quality: 0.20
    latency: 0.15
  BUG_ANALYSIS:           # Bug分析：能力 + 质量
    capability: 0.40
    quality: 0.30
    cost: 0.20
    latency: 0.10
```

#### 4.4.1 能力匹配度：集合覆盖率

> 完整实现见 [4.2.1 能力覆盖率过滤](#421-能力覆盖率过滤)。此处仅说明评分在多目标评分中的角色。

能力匹配度在多目标评分中权重较高（默认0.35），由硬约束层（4.2.1）计算后直接传入。硬约束层已淘汰不达标模型，因此进入评分阶段的候选模型能力匹配度均≥最低阈值。

**关键设计：** 额外能力bonus上限0.05且仅作为tie-breaker，防止"全能型"高价模型在简单任务上因能力标签多而占优。

#### 4.4.2 成本效率：三档归一化

`cost_sensitivity` 是**任务属性**而非模型属性——同一模型在不同任务下成本权重不同：

| 任务类型 | cost_sensitivity | 理由 |
|----------|-----------------|------|
| 批量格式转换、测试样例生成 | HIGH | 量大且价值密度低 |
| 普通代码生成、文档润色 | MEDIUM | 平衡成本和质量 |
| 架构设计、安全审查、生产事故分析 | LOW | 业务价值高，可接受成本 |

**三档归一化公式：**

```
cost_sensitivity = HIGH   → linear: cost_score = min_cost / model_cost
cost_sensitivity = MEDIUM → sqrt:   cost_score = sqrt(min_cost / model_cost)
cost_sensitivity = LOW    → log:    cost_score = 1 / (1 + log(model_cost / min_cost))
```

**效果对比（假设min_cost=¥0.01, model_cost=¥0.42, 即42x价差）：**

| 方式 | cost_score | 效果 |
|------|-----------|------|
| linear | 0.024 | 强烈惩罚高价模型 |
| sqrt | 0.155 | 适度平衡 |
| log | 0.212 | 不过度惩罚贵模型 |

**实现计划**：三种归一化公式代码量极小（约10行），Week 2全部实现，按`cost_sensitivity`配置自动选择。答辩时可演示同一任务切换cost_sensitivity后路由结果的变化。

#### 4.4.3 延迟评分：冷启动估算 + 历史数据渐进校准

```python
# 延迟由两部分构成：首token延迟 + 输出生成延迟
TIER_LATENCY = {
    1: {"base_ms": 1500, "per_output_token_ms": 8},
    2: {"base_ms": 900,  "per_output_token_ms": 5},
    3: {"base_ms": 500,  "per_output_token_ms": 3},
}

def latency_score(model, task_features):
    tier_config = TIER_LATENCY[model.tier]
    estimated = tier_config["base_ms"] + task_features.estimated_output_tokens * tier_config["per_output_token_ms"]

    # 有了Benchmark数据后，渐进切换
    real_latency = db.get_avg_latency(model.name, task_features.category)
    n_samples = db.get_sample_count(model.name, task_features.category)
    confidence = min(1.0, n_samples / 50)  # 50个样本后完全信任真实数据

    if real_latency:
        blended = confidence * real_latency + (1 - confidence) * estimated
    else:
        blended = estimated

    return max(0, 1.0 - blended / MAX_LATENCY_MS)  # MAX_LATENCY_MS = 5000
```

#### 4.4.4 历史质量：贝叶斯平滑 + 严重错误率

```python
# 默认先验值（放在YAML配置中，非代码硬编码）
# 来源：模型能力层级假设 + 少量人工先验评估 + Benchmark校准
default_quality:
  tier1: { architecture: 0.90, code_review: 0.85, bug_analysis: 0.85, code_generation: 0.80 }
  tier2: { code_generation: 0.70, documentation: 0.75, test_generation: 0.68 }
  tier3: { code_generation: 0.55, test_generation: 0.60, formatting: 0.75 }

def quality_score(model, task_features):
    # 贝叶斯平滑：先验(default) + 观测(benchmark)，样本越少越依赖先验
    prior = get_default_quality(model.tier, task_features.category)  # 默认0.65
    real_quality = db.get_avg_quality(model.name, task_features.category)
    n_samples = db.get_sample_count(model.name, task_features.category)

    prior_weight = max(0, 20 - n_samples)
    if real_quality is not None:
        avg_quality = (prior_weight * prior + n_samples * real_quality) / (prior_weight + n_samples)
    else:
        avg_quality = prior

    # 严重错误率惩罚：企业场景不只关心平均质量，更关心翻车概率
    failure_rate = db.get_severe_failure_rate(model.name, task_features.category) or get_default_failure_rate(model.tier)
    effective_quality = avg_quality * (1 - failure_rate)

    return effective_quality
```

**严重错误率默认值：**
```yaml
default_failure_rates:
  tier1: 0.03   # 3%严重错误率
  tier2: 0.08   # 8%
  tier3: 0.20   # 20%
```

#### 4.4.5 策略质量估算（非乘法）

不同策略使用不同质量组合权重，权重可配置：

```yaml
strategy_quality_weights:
  GUIDED_EXECUTE:
    plan: 0.00
    execute: 0.70
    review: 0.30
  PLAN_EXECUTE:
    plan: 0.55
    execute: 0.45
    review: 0.00
  PLAN_EXECUTE_REVIEW:
    plan: 0.45
    execute: 0.35
    review: 0.20
```

```python
def strategy_quality(strategy):
    w = STRATEGY_WEIGHTS[strategy.name]
    quality = (
        w["plan"] * get_plan_quality(strategy)
        + w["execute"] * get_execute_quality(strategy)
        + w["review"] * get_review_quality(strategy)
        - decomposition_penalty(strategy)
    )
    return quality
```

**Plan-Execute-Review 中 planning 权重从0.55降到0.45**：因为多了review兜底，规划错误的一部分可被审查发现。

---

### 4.5 成本预估模型

成本预估分为三层独立计算：**基础成本 → 缓存调整 → Plan-Execute上下文局部化**。三层互不干扰，最终叠加。

外部模型定价、竞品能力和统一成本公式的详细调研见 `docs/competitive-analysis.md`。本节只保留系统内的可执行估算模型；所有价格最终以 `data/models.yaml` 和 `config_snapshots` 中的配置快照为准。

#### 4.5.1 第一层：基础成本（不含缓存）

```python
def estimate_base_cost(model, input_tokens, output_tokens):
    """最基础的成本：input × input_price + output × output_price"""
    input_cost = (input_tokens / 1000) * model.input_price_per_1k
    output_cost = (output_tokens / 1000) * model.output_price_per_1k
    return input_cost + output_cost
```

**重要：输出token不参与任何缓存折扣**，始终按标准价格计费。

#### 4.5.2 第二层：Prompt Caching调整

Prompt Caching不是所有模型都支持，也不是"默认节省60%"。缓存收益取决于：模型是否支持、前缀稳定性、调用轮次和场景类型。

**模型缓存能力配置（models.yaml）：**

```yaml
# 模型价格以 data/models.yaml 中的 CCH 后台用量日志校准价为准
models:
  - name: "deepseek-v4-flash"
    supports_prompt_caching: true           # DeepSeek官方API支持Context Caching（待Week 1实测确认）
    cache_mode: implicit                    # 隐式缓存，无需显式创建
    cache_write_price_multiplier: 1.0       # 写入无额外成本（待实测确认）
    cache_read_price_ratio: 0.10            # 读取价格 = input_price × 0.10（待实测确认）
    cache_min_prefix_tokens: 1024
    cache_ttl_seconds: 300

  - name: "qwen3.7-max"
    supports_prompt_caching: true           # DashScope支持Context Cache（待Week 1实测确认）
    cache_mode: explicit_or_implicit        # 显式/隐式互斥，按场景选择
    cache_write_price_multiplier: 1.25      # 显式写入更贵（待实测确认）
    cache_read_price_ratio: 0.10
    cache_min_prefix_tokens: 1024
    cache_ttl_seconds: 300

  - name: "glm-5.1"
    supports_prompt_caching: unknown        # Z.AI有相关文档，但实际接口待验证
    # MVP阶段 unknown 按 false 处理，成本预估偏保守
    # 验证后改为 true/false
```

> **模型名称与价格以 models.yaml 的实际可调用配置为准。** 当前价格已用 CCH usage CSV 对账校准；Prompt Caching 参数仍需按更长上下文和多轮调用继续验证。

> **`unknown`处理规则：** MVP阶段`supports_prompt_caching: unknown`按`false`处理，不计算缓存收益。验证后改为`true`或`false`。这样成本预估偏保守，不会高估节省。

**输入Token组成拆分：**

```python
class InputBreakdown:
    system_prompt_tokens: int        # 通常固定 → 高缓存潜力
    tool_definitions_tokens: int     # 通常固定 → 高缓存潜力
    fixed_context_tokens: int        # 项目级上下文（CLAUDE.md等） → 中缓存潜力
    conversation_history_tokens: int # 多轮对话累积 → 前缀稳定时可缓存
    dynamic_query_tokens: int        # 每次不同的用户输入 → 不可缓存

    @property
    def stable_prefix(self):
        """稳定前缀 = system_prompt + tool_definitions（几乎每次调用都相同）"""
        return self.system_prompt_tokens + self.tool_definitions_tokens

    @property
    def total(self):
        return (self.system_prompt_tokens + self.tool_definitions_tokens
                + self.fixed_context_tokens + self.conversation_history_tokens
                + self.dynamic_query_tokens)
```

**场景缓存命中率预估：**

| 场景 | 预估cacheable ratio | 理由 |
|------|-------------------|------|
| 单次问答（SINGLE_TURN） | 0% | 没有后续调用，缓存写入反而更贵 |
| 固定system prompt + 固定工具定义 | 20%-40% | system prompt和tool定义稳定，但用户消息每次不同 |
| Agent多轮同工具调用 | 40%-70% | 工具定义+历史消息前缀高度稳定 |
| 同项目重复代码任务 | 30%-60% | 项目级上下文重复 |
| 随机上下文/消息顺序变化 | ≈0% | 前缀每次不同，无法命中 |

```python
SCENARIO_CACHE_RATIO = {
    "SINGLE_TURN": 0.0,
    "FIXED_PROMPT_TOOLS": 0.30,
    "AGENT_MULTI_TURN": 0.55,
    "SAME_PROJECT_REPEAT": 0.45,
    "RANDOM_CONTEXT": 0.0,
}

def estimate_cache_adjustment(model, input_breakdown, scenario):
    """计算缓存带来的净节省（可能为0甚至为负）"""
    # 不支持缓存或 unknown（MVP按false处理）
    if not model.supports_prompt_caching or model.supports_prompt_caching == "unknown":
        return CacheAdjustment(savings=0, detail="模型不支持或未验证Prompt Caching")

    stable_prefix = input_breakdown.stable_prefix

    # 前缀太短，不值得缓存
    if stable_prefix < model.cache_min_prefix_tokens:
        return CacheAdjustment(savings=0, detail=f"稳定前缀{stable_prefix}tokens < 最小缓存长度{model.cache_min_prefix_tokens}")

    cacheable_ratio = SCENARIO_CACHE_RATIO.get(scenario, 0)
    if cacheable_ratio == 0:
        return CacheAdjustment(savings=0, detail=f"场景{scenario}无缓存收益")

    estimated_turns = estimate_conversation_turns(scenario)
    base_input_price = model.input_price_per_1k / 1000

    # 首次缓存写入的额外成本（cache_write比普通input贵）
    cache_write_premium = stable_prefix * base_input_price * (model.cache_write_price_multiplier - 1)

    # 后续每次调用的缓存读取节省
    cache_read_savings_per_turn = stable_prefix * base_input_price * (1 - model.cache_read_price_ratio)

    # 净节省 = 后续调用 × 命中率 × 每次读取节省 - 首次写入额外成本
    net_savings = (
        (estimated_turns - 1) * cacheable_ratio * cache_read_savings_per_turn
        - cache_write_premium
    )

    return CacheAdjustment(
        savings=max(0, net_savings),
        detail=(
            f"稳定前缀{stable_prefix}tokens | 预估{estimated_turns}轮 | "
            f"命中率{cacheable_ratio:.0%} | "
            f"写入额外成本¥{cache_write_premium:.4f} | "
            f"净节省¥{max(0, net_savings):.4f}"
        )
    )
```

**关键认知：缓存不是"免费省钱"。** cache_write比普通input贵（通常1.25x），只有当后续调用足够多且前缀足够稳定时，cache_read的低价才能覆盖write的额外成本。单次调用的缓存收益为零甚至为负。

#### 4.5.3 第三层：Plan-Execute成本（含上下文局部化）

Plan-Execute 的成本优势来自两个独立维度：
1. **模型降级**：执行阶段从Tier 1降到Tier 2/3
2. **上下文局部化**：执行阶段只拿子任务相关的局部上下文，而不是全量上下文

```python
def estimate_plan_execute_cost(planner, executor, task_features, input_breakdown):
    num_subtasks = max(1, len(task_features.subtasks))

    # Planner（Tier 1）：看全局上下文
    planner_input = task_features.estimated_input_tokens + 500  # +system prompt
    planner_output = int(task_features.estimated_output_tokens * 0.15)  # 计划文本较短
    planner_cost = estimate_base_cost(planner, planner_input, planner_output)

    # Executor（Tier 2/3）：每个子任务只看局部上下文
    subtask_context_ratio = 0.35  # 每个子任务约需35%的全局上下文
    # 防止子任务多时总局部上下文超过全局上下文（重叠修正）
    overlap_factor = 0.7  # 子任务间共享上下文的重叠系数
    total_executor_context = min(
        task_features.estimated_input_tokens * 0.9,  # 硬上限：不超过全局的90%
        task_features.estimated_input_tokens * subtask_context_ratio * num_subtasks * overlap_factor
    )
    executor_input_per_call = int(
        total_executor_context / num_subtasks
        + planner_output / num_subtasks  # 相关的计划片段
        + 300                             # 指令token
    )
    executor_output_per_call = task_features.estimated_output_tokens / num_subtasks

    executor_cost_per_call = estimate_base_cost(executor, executor_input_per_call, executor_output_per_call)
    total_executor_cost = executor_cost_per_call * num_subtasks

    return planner_cost + total_executor_cost
```

**Break-even示例：**

```
任务: "构建WebSocket实时通知系统" (COMPLEX, 输入10K, 输出2K, 3个子任务)

全部用Tier 1 (qwen3.7-max):
  (10K × ¥0.02 + 2K × ¥0.06) = ¥0.32

Plan-Execute (qwen3.7-max规划 + deepseek-v4-flash执行):
  Planner: (10.5K × ¥0.02 + 300 × ¥0.06) = ¥0.228
  Executor: 3次 × ((3.5K+100+300) × ¥0.001 + 667 × ¥0.002) = 3 × ¥0.0052 = ¥0.016
  总计: ¥0.244
  节省: 23.7% ✓

但如果输出只有300 tokens且不可拆分:
  全部Tier 1: ¥0.218
  Plan-Execute: ¥0.235 ← 反而更贵（规划开销 > 节省）
  不触发 ✗
```

#### 4.5.4 总成本汇总

```python
def estimate_total_cost(strategy, models, task_features):
    """三层成本汇总"""
    input_breakdown = estimate_input_breakdown(task_features)
    scenario = detect_scenario(task_features)

    # 第一层：基础成本
    base_cost = estimate_strategy_base_cost(strategy, models, task_features)

    # 第二层：缓存调整
    cache_adj = estimate_cache_adjustment(models[0], input_breakdown, scenario)

    # 最终成本
    final_cost = base_cost - cache_adj.savings

    return CostEstimate(
        base_cost=base_cost,
        cache_savings=cache_adj.savings,
        cache_detail=cache_adj.detail,
        final_cost=final_cost,
        breakdown={
            "input_cost": ...,
            "output_cost": ...,
            "cache_write_premium": ...,
            "cache_read_savings": ...,
            "model_tier_savings": ...,
            "context_localization_savings": ...,
        }
    )
```

#### 4.5.5 成本估算接口

```python
def estimate_strategy_base_cost(strategy, models, task_features):
    """策略基础成本函数：显式传入模型组合，不依赖单个model对象"""
    if strategy.name == "SINGLE_MODEL":
        return estimate_base_cost(models[0],
            task_features.estimated_input_tokens,
            task_features.estimated_output_tokens)
    elif strategy.name == "GUIDED_EXECUTE":
        executor_cost = estimate_base_cost(models[0],
            task_features.estimated_input_tokens,
            task_features.estimated_output_tokens)
        review_cost = estimate_review_cost(models[1], task_features)
        return executor_cost + review_cost
    elif strategy.name == "PLAN_EXECUTE":
        return estimate_plan_execute_cost(models[0], models[1], task_features, None)
    elif strategy.name == "PLAN_EXECUTE_REVIEW":
        pe_cost = estimate_plan_execute_cost(models[0], models[1], task_features, None)
        review_cost = estimate_review_cost(models[2], task_features)
        return pe_cost + review_cost
```

**预估偏差目标：≤ 30%**（基于Benchmark历史数据校准）

---

### 4.6 第四层：企业管控门禁

路由结果在输出前需通过三道管控门禁：

| 能力 | 作用 |
|------|------|
| **budget_limit (soft/hard)** | 控成本 — soft超限标记WARNING，hard超限排除或需审批 |
| **requires_human_review** | 控风险 — 是否需要人工确认 |
| **audit trail** | 控责任与复盘 — 决策过程可追溯 |

#### 4.6.1 预算约束

MVP阶段采用静态配置预算，后续接入组织架构后支持部门→项目→任务的自动分摊。

```yaml
budgets:
  projects:
    ai-router:
      monthly_budget_cny: 3000
      task_budget_default_cny: 0.50
      task_budget_hard_limit_multiplier: 3.0  # hard = soft × 3
  task_type_limits:
    SIMPLE:   { max_cost_cny: 0.05 }
    MODERATE: { max_cost_cny: 0.30 }
    COMPLEX:  { max_cost_cny: 2.00 }
    EXPERT:   { max_cost_cny: 10.00 }
```

```python
task_soft_budget = min(
    project.task_budget_default,
    task_type_limits[complexity].max_cost_cny,
    user_override_budget  # 如果用户手动指定
)
task_hard_budget = task_soft_budget * project.task_budget_hard_limit_multiplier
```

**预算状态输出示例：**
```
当前推荐方案预计 ¥0.42，超过该任务预算 ¥0.30，建议：
1. 使用 Tier 2 单模型，预计 ¥0.18
2. 裁剪上下文至 8K，预计 ¥0.25
3. 保持强模型方案，但需要审批
```

#### 4.6.2 人工审核触发规则

`requires_human_review` 表示**执行前批准**（pre-execution approval）：路由系统已经给出推荐，但在真正调用模型或执行高风险方案前，需要人工确认。

MVP阶段，如果满足以下**任一条件**，则 `requires_human_review = true`：

1. `sensitivity == HIGH` 且 `risk_level == HIGH`（高敏数据同时存在外发、生产、写入、删除、权限或其他业务风险）
2. `risk_level == HIGH` 且使用了降级/拆分策略（即 `strategy != SINGLE_MODEL` 或 `executor_tier > 1`）
3. 选中模型的 `budget_status == "OVER_HARD_BUDGET"`（超硬预算，需审批才可执行）
4. 无候选模型满足所有硬约束（系统兜底）
5. `risk_level != LOW` 且 `quality_loss_vs_baseline > 0.20`（质量损失超过阈值）
6. 任务类型在 `human_review_required_tasks` 配置列表中

`sensitivity == MEDIUM/HIGH` 会追加 `privacy_check` 质量门禁；高敏但非高风险的任务（如内部脱敏、清洗、校验）不自动触发人工确认，但会避开不允许敏感数据的模型。

Soft budget 超限不在 MVP 阶段自动触发人工批准，只作为 warning 和替代方案提示；hard budget 才触发批准或过滤。后续若加入交互式“用户选择保持强模型方案”，可把 soft budget + user confirmation 作为审批条件。

`quality_loss_vs_baseline` 的 baseline 是**候选集内最高质量方案**，用于管控“在可执行方案中是否牺牲太多质量”；`estimated_savings` 的 baseline 是 Tier 1 成本基线，用于展示“相比强模型省多少钱”。两者故意不对称。

**关键：** 高风险任务只要没有全程使用 Tier 1，就需要人工确认。风险来自"执行错误后果"，不是"花钱多"。

#### 4.6.3 质量门禁

质量门禁表示**执行后验收**（post-execution review gate）：模型输出已经生成，系统需要通过自动检查、LLM judge 或人工验收来判断结果是否可接受。因此可能出现 `requires_human_review = false`，但 `quality_gate` 中仍包含 `human_review` 的情况，例如高风险任务使用 Tier 1 执行时不需要执行前批准，但结果仍需要人工验收。

质量门禁以 `task_type` 决定具体检查类型，`verifiability` 决定能否自动检查，`output_strictness` 和 `risk_level` 决定是否追加额外检查。

```python
BASE_GATE_BY_TASK_TYPE = {
    "CODE_GENERATION": ["syntax_check", "ast_parse"],
    "DATA_PROCESSING": ["json_schema_check"],
    "CODE_REVIEW":     ["issue_coverage_check"],
    "BUG_ANALYSIS":    ["llm_judge", "fix_verification"],
    "DOCUMENTATION":   ["llm_judge", "completeness_check"],
    "ARCHITECTURE":    ["human_review"],
}

def build_quality_gate(task_features):
    gates = list(BASE_GATE_BY_TASK_TYPE[task_features.category])
    if task_features.output_strictness == "HIGH":
        gates.append("format_check")
    if task_features.risk_level == "HIGH":
        gates.append("human_review")
    if task_features.verifiability == "LOW":
        # 低可验证性：只能靠LLM评分或人工
        if task_features.risk_level == "HIGH":
            gates = ["llm_judge", "human_review"]
        else:
            gates = ["llm_judge"]
    return list(set(gates))  # deduplicate
```

#### 4.6.4 Fallback策略

**MVP必须实现（4条）：**
```python
FALLBACK_POLICY_MVP = {
    "API_TIMEOUT":   "switch_to_same_tier_alternative",  # 同Tier备用模型
    "FORMAT_ERROR":  "retry_with_format_hint",            # 重试+格式提示
    "QUALITY_BELOW": "upgrade_tier",                      # 升级Tier
    "NO_CANDIDATE":  "escalate_to_human",                 # 人工兜底
}
```

**MVP可选（2条，后续扩展）：**
```python
FALLBACK_POLICY_EXTENDED = {
    "BUDGET_EXCEEDED":  "downgrade_or_request_approval",  # 降级或审批
    "CONTEXT_OVERFLOW": "trim_and_retry",                  # 裁剪重试（需上下文工程模块配合）
}
```

---

### 4.7 路由决策输出

#### 4.7.1 路由结果JSON Schema

```json
{
  "recommended_strategy": "PLAN_EXECUTE_REVIEW",
  "models": {
    "planner": "qwen3.7-max",
    "executor": "qwen3.7-plus",
    "reviewer": "qwen3.7-max"
  },
  "estimated_cost": 0.28,
  "baseline_cost": 0.74,
  "estimated_savings": 0.62,
  "estimated_quality": 0.83,
  "quality_loss_vs_baseline": 0.06,
  "risk_level": "HIGH",
  "requires_human_review": true,
  "human_review_reason": "任务涉及权限模块且风险等级为HIGH，使用降级执行策略",
  "reasons": [
    "任务复杂度为COMPLEX，需要强推理模型进行规划",
    "任务可拆分为4个子任务，适合分层执行",
    "结果可通过测试验证，执行风险可控",
    "相较全程Tier 1，预计节省62%成本",
    "由于任务涉及权限模块，建议人工确认后执行"
  ],
  "alternatives": [
    {
      "strategy": "SINGLE_MODEL",
      "model": "qwen3.7-max",
      "cost": 0.74,
      "quality": 0.89,
      "note": "质量最高但成本较高"
    },
    {
      "strategy": "GUIDED_EXECUTE",
      "cost": 0.36,
      "quality": 0.82,
      "note": "成本略高于推荐方案，但执行风险更低"
    }
  ],
  "budget_status": "OK",
  "quality_gate": ["syntax_check", "ast_parse", "human_review"],
  "fallback_policy": [
    {"trigger": "API_TIMEOUT", "action": "switch_to_deepseek-v4-pro"},
    {"trigger": "FORMAT_ERROR", "action": "retry_with_format_hint"},
    {"trigger": "QUALITY_BELOW", "action": "upgrade_to_tier1_single"}
  ]
}
```

#### 4.7.2 路由决策缓存

路由决策具有幂等性：**相同输入 + 相同配置 → 相同输出**。

```python
route_cache_key = hash(
    normalize(task_description)  # strip + lowercase + 合并空格
    + routing_rules_version      # 路由规则版本
    + models_config_version      # 模型配置版本
    + budget_policy_version      # 预算策略版本
)
# TTL=5分钟，配置变更时版本递增→缓存自动失效
```

---

### 4.8 路由决策伪代码（完整流程）

```python
def route(task_description: str) -> RoutingDecision:
    # ━━━ 第1层：任务画像 ━━━
    features = analyzer.extract_features(task_description)

    # ━━━ 第2-3层：策略分类 + 候选生成（Selector 内部完成） ━━━
    # StrategyClassifier：结构条件判断（TaskFeatures → 哪些策略有资格）
    classification = classifier.classify(features)

    # ModelSelector：基础过滤 → 角色池（含角色级能力过滤）→ Top-K → 策略候选 + 评分 + post-filter
    strategy_scores = selector.select_best_strategy(
        classification.strategies, all_models, features, estimator
    )
    # post-filter：quality_loss > 15% 排除，
    # 非 SINGLE 且 savings < 15%（相对 Tier 1 baseline）排除

    if not strategy_scores:
        return escalate_to_human_review(features, reason="NO_CANDIDATE")

    best = strategy_scores[0]

    # ━━━ 管控门禁 ━━━
    budget_status = check_budget(best.cost, features)
    requires_review, review_reason = gate.check_human_review(
        GateInput(features, best.model_assignment.executor, best.strategy, best.cost, best.quality, budget_status)
    )
    quality_gate = gate.build_quality_gate(features, requires_review)
    fallback = build_fallback_policy(strategy_scores)

    # ━━━ 输出 ━━━
    decision = build_routing_decision(best, strategy_scores, budget_status,
                                       requires_review, review_reason, quality_gate, fallback)

    # 持久化审计记录
    db.save_routing_decision(decision)

    return decision
```

---

## 五、补充研究方向

### 选择：B（上下文工程）+ D（Context Rot验证）+ 轻量A（可观测性）

#### 方向B：上下文工程（MVP必做 + 缓存能力条件启用，Week 2-3实现）

> **目标：** 在不承诺所有场景统一压缩率的前提下，通过上下文分层、预算管理和压缩策略，降低长上下文任务的输入Token消耗，并通过离线Benchmark、运行时质量门禁和用户反馈闭环控制质量风险。

**MVP必做（B-1 / B-2 / B-3）：**

| 任务 | 内容 | 交付标准 |
|------|------|----------|
| B-1 上下文优先级框架 | 按优先级分层组装：System Prompt > 任务描述 > 相关文件 > 历史对话 > 工具输出 > 辅助信息。每层设置Token预算和淘汰规则 | 代码实现+分层配置 |
| B-2 上下文压缩引擎 | 3种策略可独立开关：①规则摘要化（Week 2）→ LLM摘要化增强（Week 3可选）②工具输出截断 ③冗余文件/重复内容剔除 | 3种策略实现+独立配置 |

**B-2 规则摘要化策略（Rule-based Summarization，Week 2实现）：**

MVP阶段不调用LLM做摘要（避免"为省token反而再调模型"），而是基于结构规则的轻量摘要：

| 上下文类型 | 摘要规则 |
|-----------|----------|
| 历史对话 | 保留每轮首句、末句、包含"决定/结论/错误/TODO/修复"的句子 |
| 工具输出 | 保留命令、退出码、错误行、最后N行 |
| 报错日志 | 保留traceback首尾、异常类型、文件路径、行号 |
| 代码片段 | 保留函数签名、类定义、import、注释、关键分支 |
| 文档段落 | 保留标题、列表项、包含数字/限制/条件的句子 |

> Week 3可在此基础上接入LLM摘要化进行增强，但MVP阶段规则摘要已能演示"摘要化策略"的效果。
| B-3 上下文预算管理 | 按任务类型和上下文长度设置Token预算上限，超限自动裁剪，裁剪日志可审计 | 预算配置+自动裁剪+审计日志 |

**条件启用（B-4）：**

| 任务 | 内容 | 启用条件 |
|------|------|----------|
| B-4 Cache-Aware Trim | 固定System Prompt和工具定义在前部作为稳定前缀，动态上下文放后部，裁剪只作用于缓存前缀之后 | `supports_prompt_caching == true` |

- 若目标模型/网关支持Prompt Caching → 启用Cache-Aware Trim，监控`cache_hit_tokens / total_input_tokens`
- 若不支持或`unknown` → 降级为**稳定前缀保留策略**（保持上下文层次稳定，减少无关扰动），**不将缓存命中收益计入MVP成本节省**
- MVP阶段`supports_prompt_caching: unknown`按`false`处理，成本预估偏保守

**压缩策略分级（与risk_level打通）：**

| 等级 | 策略 | 适用条件 |
|------|------|----------|
| Conservative | 只剔除明显重复/无关内容 | `risk_level == HIGH` |
| Standard | 剔除 + 工具输出截断 + 历史摘要 | `risk_level == MEDIUM`，长上下文 |
| Aggressive | 大幅摘要 + 多文件局部化 + 只保留关键证据 | `risk_level == LOW`，超长上下文 |

运行时由`risk_level`决定压缩等级上限，`context_length`决定是否需要压缩。

**分层压缩目标（实验观察，非验收承诺）：**

| 上下文长度 | 压缩策略 | 目标Token减少 |
|------------|----------|--------------|
| < 5K tokens | 不主动压缩，仅做明显冗余剔除 | 不设定目标 |
| 5K - 10K tokens | 轻量压缩（Conservative） | 5% - 15% |
| 10K - 30K tokens | 标准压缩（Standard） | 20% - 30% |
| > 30K tokens | 激进压缩（Aggressive）或建议任务拆分 | 30%+，需质量门禁 |

**质量保障三层机制：**

1. **离线验证**：在Benchmark Level 2子集上测试"原始上下文 vs 轻量/标准/激进压缩"，记录Token减少率、质量分变化、严重错误率，生成按任务类型的推荐压缩策略表
2. **运行时质量门禁**：不做双跑对比（避免Token翻倍），仅在压缩后执行轻量检查（JSON合法性、AST解析、必要字段存在性）；门禁失败时按阶梯回退：放宽压缩 → 重试 → 升级模型 → 人工审核
3. **用户反馈闭环**：路由结果中展示压缩策略和可选项（`use_original_context` / `use_conservative` / `use_aggressive`），用户反馈质量差时记录到`execution_feedback`，后续自动降低该任务类型的压缩强度

**质量显著下降定义（配置化，不写死在文档中）：**

```yaml
context_compression:
  quality_drop_threshold:
    llm_judge_score_delta: 0.5        # 10分制下降0.5分
    severe_failure_rate_delta: 0.05   # 严重错误率上升5个百分点
    format_error_rate_delta: 0.10     # 格式错误率上升10个百分点
```

**选B的理由：** 直接用国产模型可实现、产出可量化数据、是路由引擎的核心功能而非独立模块。

#### 方向D：Context Rot验证实验（上下文工程验证模块，Week 3）

> **定位：这不是独立的研究方向，而是方向B（上下文工程）的验证实验。**
> 主线交付是上下文预算与裁剪策略，Context Rot实验用于验证其必要性。

| 任务 | 内容 | 交付标准 |
|------|------|----------|
| D-1 上下文长度对比实验 | 3个代表任务 × 3个代表模型 × 3个长度梯度（5K/20K/50K），观察质量变化趋势 | 趋势图+预算建议 |
| D-2 退化阈值预警 | 当输入Token超过实验发现的退化阈值时，路由引擎自动预警并建议裁剪策略 | 集成到上下文预算模块 |

**实验设计（3×3×3 = 27次API调用）：**

| 维度 | 选择 | 理由 |
|------|------|------|
| 任务 | 代码生成、重构、Bug分析 | 覆盖高/中/低上下文敏感度任务 |
| 模型 | qwen3.7-max(T1) / qwen3.7-plus(T2) / deepseek-v4-flash(T3) | 每Tier 1个代表，对比Tier间差异 |
| 长度 | 5K / 20K / 50K | 基线 / 中等上下文 / 长上下文 |

**上下文构造方式：** 核心任务描述 + 相关上下文文件（同项目其他源文件、历史对话记录、文档片段），模拟真实开发环境中的上下文积累，而非无意义padding。

**评价方式：** 复用Benchmark的混合评分（自动评分为主 + LLM Judge辅助），不单独设计评价体系。

**明确定位：**
- 这是**探索性实验**，用于验证上下文预算策略的必要性，**不作为模型排行榜**
- 不追求统计显著性，关注趋势方向而非精确数值
- 实验结论回馈到路由引擎的上下文预算参数配置

**与方向B的关系：** B负责构建（优先级框架+压缩引擎+预算管理+Cache-Aware Trim），D负责验证（上下文过长是否真的影响质量、预算参数设多少合理）。D-2的退化阈值预警直接集成到B-3预算管理模块中，不是独立系统。

#### 轻量A：可观测性（内建，不依赖Langfuse）

不部署独立Langfuse，而是在系统内建可观测性：
- 每次API调用记录完整metadata（user_id, task_type, model, tokens, cost, latency, client_type）
- Streamlit消费看板实现多维归因（按用户/部门/项目/模型/任务类型）
- 浪费模式自动检测（Top 10浪费模式 + 预估节省金额）

**不选C（KV Cache网关优化）的理由：** 需要真实CCH网关访问权限，没有网关层的话实现过于理论化。

---

## 六、Benchmark与测试数据设计

### 设计原则

Benchmark不追求"大而全"，而是分阶段、可控、有说服力。核心目标不是证明某个模型最强，而是证明：**智能路由策略比"全程用最贵模型"显著省钱，且质量可接受。**

**总API调用预算：~152次**（而非原设计的750+次）

| 层级 | 调用量 | 目的 |
|------|--------|------|
| Level 1 | 0次 | 验证路由引擎逻辑（40条离线规则测试） |
| Level 2 | ~150次 | 真实对比模型表现（30条核心用例 × 5模型） |
| Level 3 | 0次 | 策略回测：L1+L2 case 纯成本模拟 + 降级分类（quality_mode: routing_prior） |
| Context Rot验证 | ~27次 | 上下文长度对比实验（3×3×3） |
| 交叉验证 | ~10次 | 检验LLM-as-Judge偏见 |

---

### 6.1 Level 1：离线规则Benchmark（不调模型，成本=0）

**目的：** 验证路由引擎本身——分类器、特征提取器、策略选择器的逻辑是否正确。

**测试集：** 40条带标注的任务描述，每条包含期望输出。

```python
LEVEL_1_TEST_CASES = [
    {
        "input": "写一个Python函数检查回文",
        "expected_category": "CODE_GENERATION",
        "expected_complexity": "SIMPLE",
        "expected_risk_level": "LOW",
        "expected_allowed_tiers": [3],
        "expected_strategy": "SINGLE_MODEL",
    },
    {
        "input": "设计一个支持百万并发的消息推送系统架构",
        "expected_category": "ARCHITECTURE",
        "expected_complexity": "EXPERT",
        "expected_risk_level": "HIGH",
        "expected_allowed_tiers": [1],
        "expected_strategy": "SINGLE_MODEL",  # EXPERT不一定Plan-Execute
    },
    {
        "input": "重构用户登录模块，需要支持OAuth2和MFA，涉及10个文件",
        "expected_category": "REFACTORING",
        "expected_complexity": "COMPLEX",
        "expected_risk_level": "MEDIUM",
        "expected_allowed_tiers": [1, 2],
        "expected_strategy_candidates": ["PLAN_EXECUTE", "GUIDED_EXECUTE", "SINGLE_MODEL"],
    },
    # ... 40条
]
```

**指标（全部用pytest跑，不需要API调用）：**

| 指标 | 目标 | 说明 |
|------|------|------|
| classification_accuracy | ≥90% | 任务类别分类正确率 |
| complexity_accuracy | ≥85% | 复杂度判断正确率 |
| tier_recommendation_accuracy | ≥95% | 推荐Tier是否在允许范围内 |
| strategy_selection_accuracy | ≥85% | 策略选择是否合理 |
| cost_estimation_reasonableness | ≥90% | 成本预估是否在合理范围（非NaN、非负、数量级正确） |
| constraint_satisfaction | 100% | 硬约束必须100%满足（不允许Tier 3执行EXPERT任务） |

**MVP阶段先保证Level 1全通过，再跑Level 2。**

---

### 6.2 Level 2：小样本模型质量Benchmark（~150次API调用）

**目的：** 真实对比不同Tier模型的表现，建立任务-模型适配矩阵。

**测试集：30条核心用例**

| 任务类型 | 数量 | 难度分布 |
|----------|------|----------|
| 代码生成 | 6条 | 2 SIMPLE + 2 MODERATE + 2 COMPLEX |
| 代码审查 | 6条 | 2 安全 + 2 性能 + 2 设计 |
| Bug分析 | 6条 | 2 运行时 + 2 逻辑 + 2 并发 |
| 文档生成 | 4条 | 2 API文档 + 2 架构文档 |
| 重构 | 4条 | 2 提取方法 + 2 模式应用 |
| 架构设计 | 4条 | 2 MODERATE + 2 EXPERT |

**模型选择：全部 5 个 CCH 模型**

| 测试 | 模型 | 调用量 |
|------|------|--------|
| 主测试 | qwen3.7-max (T1) + deepseek-v4-pro (T1) + qwen3.7-plus (T2) + glm-5.1 (T2) + deepseek-v4-flash (T3) | 30 × 5 = 150次 |
| 小批量 smoke | 使用 `--limit` 或 `--models` 先跑少量 pair | 推荐全量前执行 |
| **合计** | | **150次** |

**每条用例结构：**

```python
{
    "id": "CG-003",
    "task_type": "CODE_GENERATION",
    "difficulty": "MODERATE",
    "description": "实现一个FastAPI的滑动窗口限流中间件",
    "input_context": "现有FastAPI应用代码...",
    "test_code": "# 用于自动验证的测试代码\ndef test_rate_limiter(): ...",
    "evaluation_criteria": {
        "must_have": ["sliding_window", "middleware_decorator", "rate_limit_check"],
        "nice_to_have": ["configurable_limits", "per_endpoint_config", "redis_backend"],
    },
    "expected_issues": [],  # 用于代码审查类任务
}
```

---

### 6.3 评估方法：混合评分（自动优先 + LLM辅助 + 人工抽检）

**核心原则：对可自动验证的任务优先使用规则/测试评分；对开放式任务使用LLM-as-Judge + 人工抽检。**

#### 6.3.1 按任务类型的评分方式

| 任务类型 | 自动评分（主要，60%权重） | LLM Judge（辅助，30%） | 人工抽检（兜底，10%） |
|----------|------------------------|----------------------|---------------------|
| 代码生成 | AST解析 + 单测运行 + 结构检查 | 需求满足度 | 抽检20% |
| 代码审查 | 预置漏洞命中率（精确匹配） | 解释质量和建议完整性 | 抽检20% |
| Bug分析 | 是否定位根因（关键词匹配） | 修复建议质量 | 抽检20% |
| 文档生成 | 结构完整性（标题/段落/代码块） | 可读性和准确性 | 抽检20% |
| 架构设计 | 关键点覆盖检查 | 方案合理性 | **必须人工评审** |

#### 6.3.2 自动评分实现

```python
def auto_score_code_generation(case, output):
    """代码生成的自动评分：不依赖LLM"""
    scores = {}

    # 1. 语法正确性（AST解析）
    try:
        ast.parse(extract_code(output))
        scores["syntax"] = 1.0
    except SyntaxError:
        scores["syntax"] = 0.0

    # 2. 可运行性（如果case提供了测试用例，直接运行）
    if case.test_code:
        scores["runnable"] = run_tests(output, case.test_code)
    else:
        scores["runnable"] = scores["syntax"]

    # 3. 结构完整性
    code = extract_code(output)
    checks = {
        "has_imports": bool(re.search(r"^(import|from)\s", code, re.MULTILINE)),
        "has_function_or_class": bool(re.search(r"^(def|class)\s", code, re.MULTILINE)),
        "has_error_handling": "try" in code or "raise" in code,
        "has_docstring": '"""' in code or "'''" in code,
    }
    scores["completeness"] = sum(checks.values()) / len(checks)

    # 4. 关键需求覆盖
    code_lower = code.lower()
    must_have_hits = sum(1 for kw in case.evaluation_criteria["must_have"] if kw in code_lower)
    scores["requirement_coverage"] = must_have_hits / len(case.evaluation_criteria["must_have"])

    return scores
```

```python
def auto_score_code_review(case, output):
    """代码审查的自动评分：检查是否发现了预置漏洞"""
    expected_issues = case.expected_issues  # 如 ["sql_injection", "hardcoded_secret", "n_plus_one"]
    output_lower = output.lower()

    hits = 0
    for issue in expected_issues:
        # 检查输出中是否提到了该问题的关键词
        if issue_keywords[issue].any_in(output_lower):
            hits += 1

    return {"issue_detection_rate": hits / len(expected_issues)}
```

#### 6.3.3 LLM-as-Judge + 交叉验证（避免偏见）

LLM-as-Judge存在偏见风险（如果用Tier 1模型当裁判给自己打分）。采用**交叉验证**机制：

```python
def llm_judge_with_cross_validation(case, output, primary_judge="qwen3.7-max"):
    """主裁判评分 + 副裁判交叉验证"""
    # 主裁判评分
    primary_score = llm_judge(primary_judge, case, output)

    # 对10条抽样case，用副裁判交叉验证
    if case.id in CROSS_VALIDATION_SUBSET:
        secondary_judge = "deepseek-v4-pro"  # 不同厂商的模型
        secondary_score = llm_judge(secondary_judge, case, output)

        # 如果两个judge评分差异 > 2分（满分10），标记争议
        if abs(primary_score - secondary_score) > 2:
            flag_as_disputed(case, primary_score, secondary_score)

        cross_validation_results.append({
            "case_id": case.id,
            "primary": primary_score,
            "secondary": secondary_score,
            "agreement": abs(primary_score - secondary_score) <= 1,
        })

    return primary_score
```

**交叉验证报告（答辩时展示）：**
```
LLM-as-Judge 偏见检验：
  抽样: 10条case
  主裁判: qwen3.7-max
  副裁判: deepseek-v4-pro
  评分一致率（差异≤1分）: 85%
  争议case: 1条（已人工复核）
  结论: 两个独立judge评分高度一致，偏见可控
```

#### 6.3.4 人工抽检规则

```python
HUMAN_SPOT_CHECK_RULES = {
    "routine": 0.20,        # 常规抽检20%
    "disputed": 1.00,       # 争议case 100%人工复核
    "architecture": 1.00,   # 架构设计100%人工评审
    "extreme_scores": 1.00, # 极端分数（最高/最低10%）人工复核
}
```

---

### 6.4 Level 3：路由策略回测（纯成本模拟 + 风险标注，零 API 调用）

**目的：** 回答项目最核心的问题——智能路由比"全程用最贵模型"省多少钱？哪些任务可以安全降级？

**方法：**
1. 用 Level 1 (40 条路由边界 case) + Level 2 (30 条真实任务 case) 作为输入
2. 对每条 case 调用 `Router.route()` 获取路由决策（零真实 API 调用）
3. 对比两条路线的成本：
   - **Baseline**：全部用 Tier 1 模型（默认 qwen3.7-max，`--baseline-model` 可覆盖，必须是 Tier 1）
   - **Smart Routing**：按路由推荐的策略执行，成本取 `decision.estimated_cost`
4. 质量评估使用 Router 先验风险标注（`quality_mode: routing_prior`），不做实测质量对比

**关键设计决定：**

- **无候选不算省钱**：Router 返回 `executor=None`（escalate_to_human）时，`effective_router_cost = baseline_cost`，`savings = 0`。避免把 `estimated_cost=0` 误算成"节省 100%"
- **savings 允许负数**：Router 比 baseline 更贵时暴露为 overspend
- **降级三态分类**：
  - `none`：executor 为 Tier 1 或无候选
  - `safe`：Tier > 1 + LOW risk + 无审批 + SIMPLE/MODERATE + quality_loss ≤ 0.15
  - `risky`：Tier > 1 但不满足 safe 条件
- **`has_executable_model` 和 `requires_human_review` 语义独立**：有候选模型 ≠ 可自动执行
- **Summary 成本汇总基于 `effective_router_cost`**，不用 `raw_router_cost`
- **case_set=all/l1/l2**：可选只跑 L1、只跑 L2、或全部（默认 all）

**方法论参考：** 借鉴 [PinchBench](https://pinchbench.com/about)（[skill repo](https://github.com/pinchbench/skill)）"真实任务 + 可评分 + 可追踪"评测方法论，case 与评分逻辑均自研。AI Router Benchmark 不评估通用 agent 能力，而是评估路由决策质量与成本节省。

**输出对比表：**

| 指标 | 全程 Tier 1 (Baseline) | 智能路由 (Smart Routing) | 说明 |
|------|----------------------|------------------------|------|
| 总成本 | ¥X.XX | ¥Y.YY | 基于 CostEstimator 模拟 |
| 节省率 | — | Z% | baseline - effective_router_cost |
| 超支 case 数 | — | N | Router 比 baseline 更贵的 case |
| 安全降级数 | — | N | 可安全使用低 Tier 模型的 case |
| 风险降级数 | — | N | 需关注的低 Tier 降级 case |
| 不可执行数 | — | N | Router 推荐人工兜底的 case |

**质量模式标注：** `quality_mode: routing_prior`，明确标注质量为路由先验估计，非实测。L2 实测质量分数可后续增强接入。

**Disclaimer：** "Level 3 MVP uses routing priors and cost simulation only. Quality is risk-estimated, not measured. Savings for approval-required cases are potential savings assuming approval is granted."

---

### 6.5 模拟消费数据

用`ConsumptionDataGenerator`生成30天 × 200条/天 = **6000条记录**：
- 8个虚拟用户（跨4个部门）
- 5个虚拟项目
- 5种客户端类型（claude-code、cursor、api-direct、custom-agent、web-ide）
- 注入浪费模式：15%过度配置模型、10%重复调用、8%过长上下文
- 幂律分布：2个重度用户消耗3-5倍

用于验证审计引擎（`ai-router audit`）和消费看板功能。

### 6.6 用户任务描述集（100+条）

中英混合的真实开发任务描述，覆盖所有类别和复杂度：
```python
[
    {"desc": "写一个Python装饰器，自动重试失败的HTTP请求，支持指数退避", "category": "CODE_GENERATION", "complexity": "MODERATE"},
    {"desc": "Implement a Redis-based distributed lock with automatic expiry", "category": "CODE_GENERATION", "complexity": "COMPLEX"},
    {"desc": "帮我写个FastAPI的用户认证中间件，支持JWT和API Key", "category": "CODE_GENERATION", "complexity": "MODERATE"},
    ...  # 100+条
]
```

用于Level 1离线规则Benchmark和路由引擎测试。

---

## 七、CLI工具集设计

### `ai-router analyze` — 任务分析与模型推荐

该命令只运行本地 Router，不调用候选大模型 API。默认启用 OpenSquilla
`opensquilla` 模式，使用 `ml_final` 校正规则复杂度；可通过 `--mode rules`、
`--mode shadow` 或 `--mode hybrid` 进行诊断对照。ML 运行时不可用时会明确提示，
并优雅回退到 Rules。

```bash
$ ai-router analyze "重构用户登录模块，需要支持OAuth2和MFA"

📋 任务画像:
  类别: REFACTORING | 复杂度: MODERATE | 风险: MEDIUM | 敏感性: LOW
  上下文: STANDARD (约8K tokens) | 推理强度: MEDIUM
  可验证性: HIGH | 输出严格度: MEDIUM
  能力需求: [code_gen, code_review] + [complex_reasoning]

🎯 推荐方案:
  策略: SINGLE_MODEL
  模型: qwen3.7-plus (Tier 2)
  预估: ~12K input + ~3K output tokens ≈ ¥0.084
  质量: 0.78 | 预算状态: OK (任务限额 ¥0.30)

💰 替代方案:
  1. deepseek-v4-pro:  ¥0.058 (成本-31%, 质量影响: 低)
  2. glm-5.1:          ¥0.075 (成本-11%, 质量影响: 低)
  3. deepseek-v4-flash: ¥0.018 (成本-79%, 质量影响: 中)

💡 建议: 启用Prompt Caching (预估额外节省40%)
   缓存分析: 稳定前缀3,200tokens | 模型支持缓存 | 场景MULTI_TURN_AGENT
   预估5轮对话 | cache_write额外¥0.008 | cache_read节省¥0.057 | 净节省¥0.049
vs 纯用 qwen3.7-max: ¥0.42 → 节省 80%
🔒 门禁: [syntax_check, ast_parse]
```

### `ai-router audit` — Token消费审计

```bash
$ ai-router audit --days 30

📊 Token消费汇总 (最近30天):
  总消费: ¥12,580 | 总调用: 6,000次 | 日均: ¥419

👤 按用户:
  alice (backend): ¥3,200 (25.4%) ⚠️
  bob (backend):   ¥2,800 (22.3%) ⚠️
  charlie (frontend): ¥1,200 (9.5%)
  ...

📦 按模型:
  qwen3.7-max:     ¥6,800 (54.1%) ← 占比过高
  deepseek-v4-pro:  ¥3,200 (25.4%)
  qwen3.7-plus:     ¥1,500 (11.9%)
  deepseek-v4-flash: ¥1,080 (8.6%)

🔥 Top 5 浪费模式:
  1. alice用qwen3.7-max执行了150次SIMPLE代码生成 → 建议用flash, 节省¥420
  2. bob的30次调用存在重复请求 (相同prompt) → 建议启用缓存, 节省¥180
  3. 前端项目平均上下文12K tokens，实际只需4K → 建议上下文裁剪, 节省¥320
  4. 20次DOCUMENTATION任务使用了Tier 1模型 → 建议降级到Tier 2, 节省¥240
  5. 夜间批量任务未使用Batch API → 建议改用批处理, 节省¥150

💰 总预估节省: ¥1,310/月 (节省10.4%)
```

### `ai-router optimize` — Prompt/上下文优化

```bash
$ ai-router optimize --prompt my_prompt.txt

🔍 分析结果:
  当前Token: 15,200 input + ~2,000 output
  当前成本: ¥0.42 (qwen3.7-max)

📊 输入组成分析:
  System Prompt: 4,200 tokens (固定)    ← 可缓存
  Tool Definitions: 1,800 tokens (固定) ← 可缓存
  项目上下文: 3,500 tokens (半固定)     ← 部分可缓存
  对话历史: 3,800 tokens               ← 可摘要压缩
  无关文件内容: 2,100 tokens            ← 可裁剪
  用户请求: ~800 tokens                ← 不可缓存

🛠️ 优化建议:
  1. [缓存] 固定前缀缓存 (6,000 tokens)
     模型支持: ✓ | 场景: Agent多轮 | 预估5轮
     cache_write: ¥0.015 | cache_read节省: ¥0.108 | 净节省: ¥0.093 (22%)
  2. [压缩] 对话历史摘要化 (3,800→800 tokens) → 节省 ¥0.072 (17%)
  3. [降级] 此任务适合Tier 2模型 → 节省 ¥0.27 (64%)
  4. [裁剪] 移除无关文件内容 (2,100 tokens) → 节省 ¥0.05 (12%)
  5. [分层] Plan-Execute策略 → 节省 ¥0.21 (50%)

  综合优化后: 预估成本 ¥0.08 (节省81%)
```

---

## 八、Web管控平台

### 8.0 当前 Web 实现状态

当前 Web 已经从早期“治理后台”演进为面向普通用户的 **Chat 工作台 + 管理员入口** 双层结构：

1. **普通用户主流程：先分析，再执行**
   - 用户只输入 API Key 登录，不需要账号、项目或部门。
   - 登录后进入 `web/app.py` 的 Chat 工作台。
   - 用户输入任务后先点击“分析”，系统用本地 Router 生成推荐方案。
   - 页面展示推荐模型、处理方式、完成把握、预计成本、相对 `qwen3.7-max` 的节省比例和注意事项。
   - 用户可以接受方案、手动改模型、选择更省钱/更稳妥，或先做深度复核。
   - 只有点击“接受并执行”后，才真正调用被选中的执行模型。

2. **分析阶段**
   - Web 分析阶段优先使用 `opensquilla` mode，即 OpenSquilla 的 `final_route_class` 参与复杂度判断。
   - 如果 OpenSquilla bundle、依赖或环境变量不可用，自动回退 rules。
   - 分析阶段本身不调用被推荐模型，因此速度会很快；这是本地 Router 推理，不是大模型回答。

3. **深度复核阶段**
   - 用户点击“深度复核”后，系统调用 `MiniMax-M3` 对本地 Router 的推荐进行二次审计。
   - 复核内容包括：任务是否被低估、是否漏掉业务风险、推荐模型是否过低/过高、是否需要先澄清、是否需要人工确认。
   - 若 `MiniMax-M3` 不可用，可回退 `qwen3.7-max`。
   - 复核结果不会自动覆盖原推荐，用户可以选择保留当前方案、采纳复核建议、恢复初始推荐或手动选择。

4. **执行阶段**
   - 执行模型使用用户 API Key 和 `data/models.yaml` 中对应的 OpenAI-compatible `api_base`。
   - 输出采用流式展示，并显示“正在思考/生成”的等待状态。
   - 执行中切换模型时，会保留当前对话上下文；后续消息用新模型继续。
   - 当对话过长时，会用 `qwen3.7-max` 压缩旧上下文，保留当前任务和近期消息。

5. **历史对话**
   - 对话历史保存在 `runs/web/conversations.json`。
   - 明文 API Key 不落盘，只用 API Key 的 SHA256 指纹隔离用户。
   - 同一个 API Key 再登录可以看到自己的历史对话；退出登录只清当前登录态，不删除历史。
   - 左侧历史列表使用模型生成短标题，并对长标题做单行省略。

6. **管理员入口**
   - 旧的治理页面仍保留在 Sidebar 的“管理员入口”折叠区。
   - 包括高级路由分析、消费审计、上下文优化、Benchmark 结果和治理配置。
   - 这些页面用于项目汇报和管理员诊断，不是普通用户必须理解的流程。

当前 Web 关键文件：

| 模块 | 文件 | 说明 |
|------|------|------|
| Chat 工作台 | `web/app.py` | 主流程、会话、附件、分析、复核、执行、流式输出 |
| 公共 UI / 登录 / Sidebar | `src/airouter/web/ui.py` | 页面配置、API Key 登录、管理员入口、返回工作台 |
| 管理页数据 | `src/airouter/web/data.py` | 读取模型、Benchmark、治理配置等展示数据 |
| 管理员页面 | `web/pages/*.py` | 高级路由分析、消费审计、优化中心、Benchmark、治理配置 |
| 路由核心 | `src/airouter/engine/router/router.py` | Router 五层决策链路 |
| OpenSquilla 复杂度 | `src/airouter/engine/complexity/*.py` | rules/shadow/opensquilla/hybrid 模式 |

### 8.0.1 附件、图片与多模态路径

当前 Chat 工作台支持文字、图片、表格、PDF 和常见文本/代码附件：

| 附件类型 | 处理方式 | 执行模型策略 |
|----------|----------|--------------|
| 图片（png/jpg/jpeg/webp） | 作为 multimodal content 传入模型 | 固定 `qwen3.7-plus` |
| CSV/TSV | 解析为文本表格摘要，注入任务上下文 | 由 Router 正常推荐 |
| XLSX/XLSM | 读取工作表与前若干行数据，注入任务上下文 | 由 Router 正常推荐 |
| PDF | 提取文本页内容，注入任务上下文 | 由 Router 正常推荐 |
| 文本/代码/日志 | 直接截断注入任务上下文 | 由 Router 正常推荐 |

设计原则：

- 图片任务走独立 `image_model` 路径，因为当前公司可用模型里只有 `qwen3.7-plus` 适合多模态。
- 有图片附件时，页面会锁定执行模型为 `qwen3.7-plus`，避免用户切到不支持视觉的模型后失败。
- 表格、PDF 和文本附件不是直接上传给所有模型，而是先提取为可读文本，再交给 Router 分析和执行模型处理。
- 附件有数量、大小和文本长度限制，避免一次性把超大文件塞进上下文。

### 8.1 页面优先级分级

按"答辩展示价值 + 实现复杂度 + 对评分项的支撑程度"分为四级：

| 优先级 | 页面 | 实现程度 | 主要展示 | 答辩价值 |
|--------|------|----------|----------|----------|
| **P0** | 路由工作台 | 完整交互 | 输入任务→模型推荐→成本对比→替代方案→审核/预算状态 | 证明核心路由闭环 |
| **P0** | 消费看板 | 完整交互 | 消费趋势+按用户/项目/模型/任务类型归因+预算预警 | 证明管控能力 |
| **P0** | Benchmark结果 | 完整展示 | 任务-模型适配矩阵+全Tier1 vs 路由策略成本/质量对比 | 证明数据驱动 |
| **P1** | 优化中心 | 展示为主+轻交互 | Top N浪费模式+节省金额+建议列表+导出报告+配置草案 | 证明优化闭环 |
| **P2** | 规则管理 | 只读展示 | 权重/阈值/allowed_tiers/预算/质量门禁/版本号 | 证明配置体系 |
| **P3** | 上下文工程验证 | 静态图表 | 长上下文压缩效果+质量变化+缓存能力条件启用 | 证明扩展亮点 |

> **注意：P0是答辩展示优先级，不等于开发顺序。** 例如Benchmark结果是P0，但因依赖Level 2实测数据，开发排在D17；消费看板是P0，且依赖的种子数据Week 2已就绪，开发排在D16最先。

### 8.2 各页面详细设计

#### P0：路由工作台

完整交互：输入任务描述 → 调用`/api/route` → 展示完整路由决策。

- 输入框（支持中英文任务描述）
- 模型推荐卡片（主模型+替代方案+策略类型）
- 成本对比柱状图（各候选模型成本对比）
- 评分明细（能力/成本/延迟/质量四维度雷达图）
- 预算状态和审核状态标注
- 历史记录列表

#### P0：消费看板

完整交互：实时聚合查询+多维下钻。

```
┌──────────────────────────────────────────────────────────┐
│  今日消费: ¥1,280  │  本月累计: ¥18,500  │  预算: 72%    │
├──────────────────────────────────────────────────────────┤
│                                                          │
│  消费趋势 (最近30天)                                      │
│  ╭──╮                                                    │
│  │  │  ╭──╮                                              │
│  │  ╰──╯  ╰──╮    ╭──                                   │
│  ╰────────────╰────╯                                     │
│                                                          │
│  按模型占比          按部门占比                             │
│  ┌─────┐           ┌─────┐                               │
│  │饼图  │           │饼图  │                               │
│  └─────┘           └─────┘                               │
└──────────────────────────────────────────────────────────┘
```

- 趋势折线图（日/周/月粒度切换）
- 多维下钻（按用户/部门/项目/模型/任务类型）
- 预算预警（当前月进度 vs 预算，超支预警红色标注）
- 消费归因（哪些任务/用户/项目贡献了多少消费）

#### P0：Benchmark结果

完整展示：数据驱动的可视化报告。

- 任务-模型适配矩阵热力图（task_type × model，颜色深浅表示质量分）
- Level 1离线测试结果（分类准确率、Tier推荐准确率）
- Level 2真实对比结果（质量分+成本+延迟三维对比表）
- Level 3策略回测对比（全程Tier1 vs 智能路由：成本降低XX%，降级建议分布）

#### P1：优化中心

展示为主 + 轻交互（导出/生成草案），**不做一键应用**。

页面分4块：

**第一块：节省概览卡片**
```
检测到浪费模式：12 类  |  涉及调用：1,284 次
当前月预估浪费：¥12,800  |  最高优先级建议可节省：¥4,200/月
```

**第二块：浪费模式Top N**

| 排名 | 浪费模式 | 涉及范围 | 发生次数 | 当前成本 | 预估节省 | 严重程度 |
|------|----------|----------|----------|----------|----------|----------|
| 1 | 高配模型滥用 | backend / code_generation | 420 | ¥6,800 | ¥4,200 | High |
| 2 | 过长上下文 | agent / bug_analysis | 180 | ¥3,200 | ¥1,100 | Medium |
| 3 | 重复调用 | custom-agent | 96 | ¥900 | ¥360 | Medium |
| 4 | 可降级未降级 | documentation | 75 | ¥600 | ¥420 | Low |

**第三块：优化建议列表**

每条建议包含：
```json
{
  "suggestion_type": "tier_down",
  "title": "SIMPLE任务过度使用Tier 1",
  "description": "过去30天SIMPLE任务中有150次使用Tier 1模型，平均成本为Tier 3的18倍",
  "affected_scope": {
    "users": ["alice", "bob"],
    "projects": ["backend-service"],
    "task_types": ["CODE_GENERATION", "TEST_GENERATION"]
  },
  "estimated_savings_cny": 4200,
  "risk": "low",
  "recommended_action": "将SIMPLE + LOW risk任务默认allowed_tiers改为[3]"
}
```

**第四块：优化建议草案**

生成`routing_rules_patch.yaml`建议，**不直接应用**：
```yaml
# draft_routing_rules_patch.yaml
# 仅作为管理员审批参考，不自动应用
rules:
  - name: simple_task_tier_limit
    condition:
      complexity: SIMPLE
      risk_level: LOW
    before:
      allowed_tiers: [2, 3]
    after:
      allowed_tiers: [3]
    estimated_monthly_savings_cny: 4200
    risk_note: "仅影响低风险SIMPLE任务"
```

**按钮：** 导出Markdown报告 | 生成YAML Patch建议 | 复制建议摘要

**不做：** 一键应用、修改生产配置、效果追踪、A/B测试、灰度回滚。

> MVP阶段记录每条建议的生成时间、影响范围和预估节省金额，为后续效果追踪提供基线数据。

#### P2：规则管理（只读）

只读展示系统配置体系，**不做在线编辑**。分5个Tab：

**Tab 1：Routing Weights**

| task_type | capability | cost | quality | latency |
|-----------|-----------|------|---------|---------|
| DEFAULT | 0.35 | 0.30 | 0.20 | 0.15 |
| ARCHITECTURE | 0.40 | 0.10 | 0.40 | 0.10 |
| TEST_GENERATION | 0.25 | 0.45 | 0.20 | 0.10 |

**Tab 2：Allowed Tiers**

| complexity | risk | allowed_tiers |
|-----------|------|--------------|
| SIMPLE | LOW | [3] |
| MODERATE | LOW | [2, 3] |
| COMPLEX | MEDIUM | [1, 2] |
| EXPERT | HIGH | [1] |

**Tab 3：Model Registry**

| model | tier | input price | output price | supports_cache | max_context |

**Tab 4：Budget Rules**

| scope | monthly_budget | task_limit | warning_threshold |

**Tab 5：Quality Gates**

| task_type | gates |
|-----------|-------|
| CODE_GENERATION | syntax_check, ast_parse, lint |
| DATA_PROCESSING | json_schema_check |
| ARCHITECTURE | human_review |

底部展示：`config_version: 2026-06-xx-v3` | `last_updated_at: ...`

#### P3：上下文工程验证（静态图表）

静态图表展示，不做复杂交互。回答一个问题：**上下文优化策略在长上下文场景下有没有观察到节省？**

- 长上下文压缩前后Token对比（>10K子集）
- 不同压缩策略的质量分变化
- `supports_prompt_caching: true/false`时的成本差异
- 3代表模型×3任务×3长度趋势图+退化阈值标注

### 8.3 实现执行顺序

D17（先做确定性高的页面）：
1. **消费看板**（依赖Week 2种子数据，数据已就绪，聚合查询+图表渲染确定性最高）
2. **优化中心**（依赖detector输出+模拟数据，不依赖Benchmark结果）
3. **路由工作台**（依赖route接口，路由引擎如有bug会卡页面开发）

D18（后做依赖Benchmark的页面）：
1. **规则管理**（只读YAML，最简单）
2. **Benchmark结果**（依赖测试数据，可用预缓存结果或示例数据）
3. **上下文工程验证**（静态图表，可用预生成结果）

**执行策略：** 先做所有页面的骨架和数据接口，再填P0/P1的真实数据。P2/P3使用静态配置和预生成图表。不要一页一页精雕细琢。

---

## 九、项目目录结构

```
airouter/
├── README.md                            # 项目概述和快速启动
├── docker-compose.yml                   # 一键部署
├── Dockerfile                           # API服务镜像
├── Dockerfile.web                       # Streamlit前端镜像
├── pyproject.toml                       # 依赖管理和工具配置
├── Makefile                             # 常用命令（make dev/test/lint）
│
├── docs/                                # 文档
│   ├── system-design.md                 # 系统设计文档（Week 1交付）
│   ├── competitive-analysis.md          # 竞品调研
│   ├── week1-delivery-checklist.md      # Week 1交付物对照表
│   ├── best-practices.md                # Token优化最佳实践手册（9章）
│   ├── sop/                             # 企业Token管控SOP（5个SOP）
│   └── benchmark-report.md             # Benchmark结果报告
│
├── src/airouter/                        # 源代码
│   ├── __init__.py
│   ├── config.py                        # 配置管理
│   │
│   ├── models/                          # 数据模型
│   │   ├── schemas.py                   # Pydantic请求/响应模型
│   │   ├── db.py                        # SQLAlchemy ORM模型
│   │   ├── enums.py                     # 枚举类型
│   │   └── model_registry.py            # 模型定义和定价 ← 核心
│   │
│   ├── engine/                          # 核心引擎
│   │   ├── router/                      # 路由引擎
│   │   │   ├── analyzer.py              # 任务特征提取
│   │   │   ├── classifier.py            # 任务分类
│   │   │   ├── selector.py              # 模型选择 ← 最核心
│   │   │   └── estimator.py             # 成本预估
│   │   ├── audit/                       # 审计引擎
│   │   │   ├── collector.py             # Token采集
│   │   │   ├── aggregator.py            # 多维聚合
│   │   │   └── detector.py              # 浪费模式检测 ← 核心
│   │   ├── context/                     # 上下文工程（方向B）
│   │   │   ├── priority.py              # 优先级框架
│   │   │   ├── compressor.py            # 压缩策略
│   │   │   ├── budget.py                # 预算管理
│   │   │   └── cache_aware_trim.py      # Cache-Aware Trim（条件启用）
│   │   └── benchmark/                   # Benchmark框架
│   │       ├── runner.py                # 测试执行器
│   │       ├── evaluator.py             # 多维评分器
│   │       ├── generator.py             # 数据生成器
│   │       └── reporter.py              # 报告生成器
│   │
│   ├── api/                             # FastAPI后端
│   │   ├── main.py                      # 应用入口
│   │   ├── deps.py                      # 依赖注入
│   │   └── routes/                      # API路由
│   │       ├── router.py                # /api/route/*
│   │       ├── audit.py                 # /api/audit/*
│   │       ├── benchmark.py             # /api/benchmark/*
│   │       ├── models.py               # /api/models/*
│   │       ├── rules.py                 # /api/rules/*
│   │       └── dashboard.py             # /api/dashboard/*
│   │
│   ├── cli/                             # CLI工具
│   │   ├── main.py                      # Typer入口
│   │   ├── analyze.py                   # ai-router analyze
│   │   ├── audit.py                     # ai-router audit
│   │   ├── optimize.py                  # ai-router optimize
│   │   └── benchmark.py                 # ai-router benchmark
│   │
│   └── adapters/                        # 模型适配器
│       ├── base.py                      # 抽象接口
│       ├── openai_compat.py             # OpenAI兼容适配器
│       └── mock.py                      # Mock适配器（测试用）
│
├── web/                                 # Streamlit前端
│   ├── app.py                           # 主页
│   └── pages/
│       ├── 1_route_workbench.py         # 路由工作台
│       ├── 2_consumption_dashboard.py   # 消费看板
│       ├── 3_optimization_center.py     # 优化中心
│       ├── 4_rule_management.py         # 规则管理
│       ├── 5_benchmark_results.py       # Benchmark结果
│       └── 6_context_budget_study.py     # 上下文工程验证
│
├── data/                                # 数据文件
│   ├── models.yaml                      # 模型注册表和定价
│   ├── routing_rules.yaml               # 路由规则（权重、阈值、allowed_tiers）
│   ├── budgets.yaml                     # 预算配置（项目/任务类型）
│   ├── quality_defaults.yaml            # 质量先验值 + 严重错误率
│   ├── compression_policy.yaml          # 压缩策略分级 + 质量阈值 + 分层目标
│   ├── benchmark_cases/                 # Benchmark测试集
│   │   ├── code_generation.json         # 20条
│   │   ├── code_review.json             # 20条
│   │   ├── bug_analysis.json            # 20条
│   │   ├── refactoring.json             # 20条
│   │   ├── documentation.json           # 20条
│   │   └── architecture.json            # 10条
│   ├── task_descriptions.json           # 100+用户任务描述
│   └── seed_data.py                     # 种子数据填充脚本
│
├── tests/                               # 测试
│   ├── conftest.py                      # 共享fixtures
│   ├── unit/                            # 单元测试
│   ├── integration/                     # 集成测试
│   └── benchmark/                       # Benchmark自测
│
└── scripts/                             # 工具脚本
    ├── generate_seed_data.py            # 生成模拟消费数据
    ├── run_benchmarks.py                # 运行完整Benchmark
    └── context_budget_experiment.py     # 上下文长度验证实验
```

---

## 十、数据存储设计

### 设计原则：控制面与数据面分离

AI Router 采用控制面与数据面分离设计。路由决策依赖配置文件和模型能力注册表，数据库仅用于记录决策过程、执行反馈和评测结果。**即使数据库不可用，路由引擎仍可完成模型推荐和成本预估**，只是暂时无法写入审计记录。

### 存储分层

| 类型 | 存储方式 | 内容 | 理由 |
|------|----------|------|------|
| 配置输入 | YAML | models.yaml / routing_rules.yaml / budgets.yaml / quality_defaults.yaml / compression_policy.yaml | 开发期频繁修改，YAML可Git版本控制，无需管理后台 |
| 静态测试集 | JSON | benchmark_cases/*.json | 测试用例是静态数据，改动了有Git历史 |
| 运行记录 | SQLite | routing_decisions / execution_feedback / benchmark_results / config_snapshots | 需要多维聚合查询和关联分析 |
| 分析结果 | 运行时生成 | 浪费模式检测 / 优化建议 / 配置变更草案 | 按需计算，不需要持久化 |

### MVP数据库表（4张）

```sql
-- 路由决策记录（完整审计轨迹，存预估值）
routing_decisions (
    id INTEGER PRIMARY KEY,
    task_hash TEXT,                       -- 任务描述hash（用于缓存幂等性）
    -- 常查字段（单独列，避免每次解析JSON）
    user_id TEXT,
    project_id TEXT,
    department TEXT,
    client_type TEXT,
    task_type TEXT,                       -- CODE_GENERATION / ARCHITECTURE / ...
    complexity TEXT,                      -- SIMPLE / MODERATE / COMPLEX / EXPERT
    risk_level TEXT,                      -- LOW / MEDIUM / HIGH
    selected_strategy TEXT,               -- SINGLE_MODEL / PLAN_EXECUTE / ...
    selected_models_json TEXT,            -- ["qwen3.7-max", "deepseek-v4-flash"]
    estimated_input_tokens INTEGER,
    estimated_output_tokens INTEGER,
    estimated_cost_cny REAL,
    budget_status TEXT,                   -- OK / WARNING / OVER_BUDGET
    requires_human_review BOOLEAN,
    config_version TEXT,                  -- 路由规则+模型配置版本
    config_snapshot_id INTEGER,           -- 关联配置快照
    created_at TIMESTAMP,
    -- 复杂信息（JSON存储）
    task_description TEXT,
    features_json TEXT,                   -- 13维任务画像
    constraints_json TEXT,                -- 硬约束参数
    strategy_candidates_json TEXT,        -- 所有候选策略及其评分
    selected_strategy_detail_json TEXT,   -- 最终选中策略完整信息
    score_breakdown_json TEXT,            -- 四维得分明细
    alternatives_json TEXT,               -- 替代方案列表
    quality_gate_json TEXT,               -- 质量门禁列表
    fallback_policy_json TEXT,            -- 兜底策略列表
    human_review_reason TEXT,
    reasoning TEXT                        -- 推荐理由（自然语言）
)

-- 路由执行反馈（存实际执行值，与routing_decisions的预估值形成对比）
execution_feedback (
    id INTEGER PRIMARY KEY,
    routing_decision_id INTEGER,          -- 关联路由决策
    executed_strategy TEXT,               -- 用户实际使用的策略
    executed_models_json TEXT,            -- 用户实际使用的模型
    actual_input_tokens INTEGER,
    actual_output_tokens INTEGER,
    actual_cost_cny REAL,
    actual_latency_ms INTEGER,
    quality_score REAL,
    quality_gate_passed BOOLEAN,
    user_accepted BOOLEAN,                -- 是否接受了路由推荐
    user_override_reason TEXT,            -- quality_concern/speed_concern/familiarity/cost_acceptable/testing/other
    user_override_note TEXT,              -- 自由补充说明
    actual_calls_json TEXT,               -- Plan-Execute多次调用明细（可选）
    error_type TEXT,                      -- 错误类型（可选）
    created_at TIMESTAMP
)

-- Benchmark运行结果（存模型/策略在测试集上的表现）
benchmark_results (
    id INTEGER PRIMARY KEY,
    suite_name TEXT,                      -- level1_offline / level2_comparison / level3_strategy
    suite_version TEXT,                   -- 测试集版本
    case_id TEXT,                         -- 测试用例ID
    case_version TEXT,                    -- 用例版本
    task_type TEXT,
    complexity TEXT,
    model_or_strategy TEXT,              -- 模型名或策略名
    models_json TEXT,                     -- 参与模型列表
    input_tokens INTEGER,
    output_tokens INTEGER,
    cost_cny REAL,
    latency_ms INTEGER,
    quality_score REAL,
    severe_failure BOOLEAN,
    gate_passed BOOLEAN,
    raw_output_path TEXT,                 -- 原始输出文件路径（不放DB）
    score_detail_json TEXT,               -- 评分明细
    created_at TIMESTAMP
)

-- 配置快照（审计用，记录每次决策时的完整配置）
config_snapshots (
    id INTEGER PRIMARY KEY,
    config_version TEXT,                  -- 配置版本号
    models_hash TEXT,
    routing_rules_hash TEXT,
    budgets_hash TEXT,
    quality_defaults_hash TEXT,
    compression_policy_hash TEXT,
    merged_config_json TEXT,              -- 所有配置合并后的完整JSON
    created_at TIMESTAMP
)
```

> **raw_output不放数据库：** 模型原始输出可能很长（代码生成结果可达数千tokens），存文件路径即可。实际文件放在`raw_outputs/benchmark_run_xxx/case_001_model_tier2.txt`。

### 消费看板查询策略

**数据来源优先级：有实际值用实际值，没有则用预估值。**

```sql
SELECT
    date(rd.created_at) AS day,
    rd.task_type,
    rd.selected_strategy,
    SUM(COALESCE(ef.actual_cost_cny, rd.estimated_cost_cny)) AS cost_cny,
    SUM(COALESCE(ef.actual_input_tokens, rd.estimated_input_tokens)) AS input_tokens,
    SUM(COALESCE(ef.actual_output_tokens, rd.estimated_output_tokens)) AS output_tokens,
    COUNT(*) AS task_count
FROM routing_decisions rd
LEFT JOIN execution_feedback ef
    ON rd.id = ef.routing_decision_id
WHERE rd.created_at >= date('now', '-30 days')
GROUP BY day, rd.task_type, rd.selected_strategy;
```

页面标注每条记录是`actual`还是`estimated`，管理层问"这是真实花费还是系统估算"时可明确回答。

### 浪费检测器查询链路

```python
# 浪费检测器直接查 routing_decisions + execution_feedback，不需要单独的 usage_records 表
waste_patterns = detector.detect(
    decisions=db.query(routing_decisions).filter(last_30_days),
    feedback=db.query(execution_feedback)
)
# 结果运行时生成，不存表
# 导出时写文件：reports/optimization_report_2026-06-xx.md
```

### execution_feedback 中的实际调用明细

Plan-Execute策略涉及多次模型调用，`actual_calls_json`记录每次调用的成本明细：

```json
[
    {"role": "planner", "model": "qwen3.7-max", "input_tokens": 10000, "output_tokens": 500, "cost_cny": 0.20},
    {"role": "executor", "model": "deepseek-v4-flash", "input_tokens": 3000, "output_tokens": 2000, "cost_cny": 0.02},
    {"role": "executor", "model": "deepseek-v4-flash", "input_tokens": 2800, "output_tokens": 1800, "cost_cny": 0.018}
]
```

支持策略级成本拆解，可回答"Plan-Execute中规划占多少成本、执行占多少"。

### 未来扩展：usage_records

当系统接入真实API Gateway / Langfuse / CCH网关后，或调用量达到百万级时，引入`usage_records`作为真实调用流水表：

| 表 | 语义 |
|---|------|
| routing_decisions | 系统推荐了什么 |
| usage_records | 真实调用流水（从网关导入） |
| execution_feedback | 质量与用户反馈 |

MVP阶段消费看板基于`routing_decisions + execution_feedback`聚合，后续`usage_records`可作为事实数据来源。

---

## 十一、四周执行计划

### 执行原则

1. **核心链路优先**：路由引擎+CLI是所有后续工作的基础，Week 2结束前必须跑通
2. **每周末有可演示检查点**：不是"做完了多少模块"，而是"能演示什么"
3. **上下文工程拆两周**：Week 2做B-1/B-2核心代码，Week 3做B-3预算管理+验证实验
4. **Benchmark分级落地**：Level 1在Week 2跑通（0成本），Level 2在Week 2末后台启动，Week 3收结果+跑Level 3
5. **Week 4不新增功能**：只交付文档、报告、演示稳定性
6. **audit是后端能力**：Week 2以CLI形式先跑通，Week 3 Web看板复用其逻辑

### 每周可演示检查点

| 周末 | 检查点 | 一句话演示 |
|------|--------|-----------|
| W1末 | 规则版CLI能跑 | `ai-router analyze "写JWT鉴权"` → 输出模型推荐（基于关键词规则） |
| W2末 | 完整CLI闭环 | `analyze`/`audit`/`optimize`/`benchmark --level 1`全部可用 |
| W3末 | Web+实测数据 | `docker-compose up` → Streamlit可演示，Level 2/3有实测数据 |
| W4末 | 完整交付 | PPT+手册+SOP+预录视频+现场演示 |

### Week 1：项目骨架 + 规则版路由（D1-D7）

| 天 | 任务 | 产出 |
|----|------|------|
| D1 | 收敛MVP范围；注册5个模型API并验证连通性和定价 | 竞品对比矩阵 + 定价验证表 |
| D2 | 设计models.yaml、routing_rules.yaml、budgets.yaml、quality_defaults.yaml；竞品调研（OpenRouter/LiteLLM/Helicone） | 核心配置文件 |
| D3 | 实现TaskFeatures（13维）、分类枚举（10类×4级）、能力required/preferred映射；30条Level 1测试样例 | 数据模型 + 任务样例 |
| D4 | 实现规则版TaskAnalyzer（关键词模式）+ Classifier | 分类器 |
| D5 | 实现ModelSelector第一版：硬约束过滤+单模型评分；CostEstimator第一版 | 选择器+预估器 |
| D6 | 项目骨架搭建（目录结构/pyproject.toml/Makefile）；配置加载器；RoutingDecision schema；Pydantic schemas | 可运行项目骨架 |
| D7 | CLI `ai-router analyze`（规则版）；20-30条Level 1测试运行；完善系统设计文档 | 规则版analyze可运行 |

**Week 1检查点：** `ai-router analyze "写一个FastAPI JWT鉴权中间件"` → 输出任务类型/复杂度/风险/推荐模型/成本预估/推荐理由/替代方案

**Week 1交付物：** 可运行的规则版CLI + 系统设计文档 + 核心配置文件

### Week 2：完整路由引擎 + CLI四命令（D8-D14）

| 天 | 任务 | 产出 |
|----|------|------|
| D8 | 完善硬约束层（allowed_tiers/capability threshold/human review/budget两层）；OpenAI兼容Adapter+MockAdapter；SQLite四张表schema定义 | 完整硬约束+适配器层+DB schema |
| D9 | 实现策略候选生成（SINGLE/GUIDED/PLAN_EXECUTE/PLAN_EXECUTE_REVIEW）；TaskAnalyzer LLM模式（关键词模式作为fallback） | 四策略+双模式分析器 |
| D10 | 生成种子数据6000条（供audit使用）；实现`ai-router audit`：消费归因+浪费模式Top N | 种子数据+审计命令 |
| D11 | 实现上下文工程B-1优先级框架 + Token分层预算 | 优先级框架 |
| D12 | 实现B-2压缩引擎：冗余剔除+截断+规则摘要化（5种上下文类型的结构化摘要规则） | 压缩引擎（3策略） |
| D13 | 实现`ai-router optimize`：上下文优化建议+压缩前后Token估算（展示3种策略对比）；CLI集成测试 | 优化命令 |
| D14 | 实现`ai-router benchmark --level 1`（40条规则测试）；**后台启动Level 2**（`benchmark --level 2 --resume`，支持断点续跑/失败重试/限速） | Benchmark L1+Level 2启动 |

**Week 2检查点：** `analyze`用真实LLM推荐 + `audit`找Top浪费模式 + `optimize`给上下文压缩建议 + `benchmark --level 1`跑通规则测试

**Week 2交付物：** 完整路由引擎 + 4个CLI命令 + 上下文工程B-1/B-2 + Level 1 Benchmark + SQLite DB + 种子数据

**Week 2降级预案（如果delay）：**
- 摘要化简化为规则版（保留首尾+关键行），真LLM摘要推到Week 3增强
- SQLite先写routing_decisions+config_snapshots，execution_feedback/benchmark_results可Week 3补
- Plan-Execute先支持成本预估，不真实执行多模型调用链

### Week 3：Web平台 + Benchmark收尾 + 上下文工程验证（D15-D21）

| 天 | 任务 | 产出 |
|----|------|------|
| D15 | FastAPI路由（route/audit/benchmark/optimize）+ 中间件；**检查Level 2结果，补跑失败case，清洗数据** | 后端API + Level 2数据就绪 |
| D16 | 生成Level 2报告（任务-模型适配矩阵、评分表）；Streamlit P0页面（消费看板→路由工作台）+ P1页面（优化中心） | L2报告 + Web核心页面 |
| D17 | Streamlit P0页面（Benchmark结果）+ P2页面（规则管理） | Web完整 |
| D18 | Streamlit P3页面（上下文工程验证）+ 剩余页面收尾 | 全部页面完成 |
| D19 | **Level 3策略回测**（L1+L2离线回测：全程Tier1 vs 智能路由成本对比 + 降级分类）+ **Context Rot验证实验**（3×3×3=27次API调用） | 回测报告 + 退化趋势数据 |
| D20 | **上下文工程B-3预算管理**（基于L2实测数据+ContextRot观察定规则）；长上下文策略验证 | B-3完成 + 预算配置 |
| D21 | Docker Compose + 集成测试 + 演示数据固化 + **预录第一版系统演示备份视频**（防止Week 4系统临时故障） | 可部署系统 + 备份视频 |

**Week 3检查点：** `docker-compose up` → 演示路由推荐→消费看板→优化建议→Benchmark对比→规则配置

**Week 3降级方案：** 若FastAPI接口开发延期，Streamlit可直接调用engine/service层（不经过HTTP），保证演示链路不受前后端分离影响。最终部署时再切换到HTTP调用。

**Week 3交付物：** 可部署Web平台 + Benchmark完整数据（L1+L2+L3）+ Context Rot验证 + Docker Compose + 预录备份视频

### Week 4：文档 + 打磨 + 答辩（D22-D28）

> **原则：不新增功能，只做交付物、报告、演示稳定性。**

| 天 | 任务 | 产出 |
|----|------|------|
| D22 | 系统设计文档最终版（架构/算法/数据流/Schema一致性检查） | 设计文档定稿 |
| D23 | Token优化最佳实践手册（含Benchmark实测数据） | 手册 |
| D24 | 企业Token管控SOP（5个SOP） | SOP文档 |
| D25 | Benchmark报告/回测报告/优化报告整理；系统Bug修复（缓冲日） | 报告+最终系统 |
| D26 | 答辩PPT + 演示脚本 + Q&A准备 | 演示材料 |
| D27 | 演示彩排 + 修复演示中发现的问题 + 备用数据准备 + **录制最终答辩版视频** | 彩排通过 |
| D28 | 最终Review + 答辩 | 通过考核 |

**Week 4交付物：** 最佳实践手册 + SOP + 答辩PPT + 预录视频 + 最终系统

### MVP最小成功标准

> 达到以下7条即为MVP通过，防止任务膨胀。

1. `analyze` / `audit` / `optimize` / `benchmark --level 1` 四个CLI命令可运行
2. 输入20条不同任务，能输出可解释路由决策（含模型推荐、成本预估、推荐理由）
3. Web至少能展示路由工作台、消费看板、优化中心、Benchmark对比（P0+P1页面）
4. Level 2至少完成30条核心用例中80%的实测
5. 回测能输出全程Tier 1 vs 智能路由的成本对比 + 降级分类（safe/risky）
6. Docker Compose可启动Web和核心服务
7. 所有演示数据有离线备份，API不可用时仍能演示

---

## 十二、评分对照

| 评分维度 | 权重 | 我们的应对 |
|----------|------|-----------|
| 架构设计 | 15% | 五层路由架构、模型无关Adapter、控制面/数据面分离、配置热更新 |
| 路由引擎质量 | 20% | 硬约束过滤、策略候选生成、多目标评分、Plan-Execute策略、可解释推荐理由 |
| 工程实现 | 20% | 4个CLI命令、Streamlit Web平台、SQLite审计、Docker一键部署、核心模块测试覆盖率≥80% |
| 数据驱动能力 | 15% | 三级Benchmark（40条离线+30条实测+70条策略回测）、混合评分、上下文工程验证、浪费模式检测 |
| 文档与SOP | 15% | 9章最佳实践手册（含实测数据）、5个SOP可直接推广、系统设计文档 |
| 答辩表现 | 15% | CLI+Web现场演示、Benchmark数据支撑、预录备份视频 |

---

## 十三、关键风险与应对

| 风险 | 影响 | 应对策略 |
|------|------|----------|
| 模型API限流 | 阻塞Benchmark | 分批跑、指数退避、结果缓存到DB |
| 模型间质量差异小 | 路由价值不明显 | 强调成本和延迟差异，用"性价比"作为主指标 |
| Context Rot实验不理想 | 验证实验趋势不明显 | 定位为探索性验证，不影响主线交付；结论仍可回馈到预算参数 |
| 4周时间紧 | 功能不完整 | 核心链路（路由+CLI）必须完成，Web和Benchmark可简化 |
| Demo现场失败 | 答辩扣分 | 预录备份视频、预缓存Benchmark结果 |
| 定价数据不准确 | 成本预估偏差 | Week 1核实官方定价，models.yaml集中管理 |

---

## 十四、最终交付物清单

| # | 交付物 | 形态 | 验收标准 |
|---|--------|------|----------|
| 1 | 系统设计文档 | Markdown | 架构评审通过 |
| 2 | 模型路由引擎 | Python代码仓库 | 核心模块（analyzer/selector/estimator/constraints/audit detector）测试覆盖率≥80% |
| 3 | CLI工具集(ai-router) | 可安装CLI包 | 4个核心命令均可用 |
| 4 | Web管控平台 | 前后端代码仓库 | Docker Compose一键部署 |
| 5 | 上下文工程模块 | 代码+文档 | 分层压缩+预算管理+质量门禁+长上下文20-30%减少（实验目标） |
| 6 | 自动化Benchmark套件 | 测试框架+数据集 | 离线规则测试集≥40条；静态测试用例库覆盖6类任务；真实模型实测子集30条核心用例；回测报告（全程Tier1 vs 智能路由成本对比+降级分类） |
| 7 | 上下文工程验证报告 | 数据+图表 | 3代表模型×3任务×3长度趋势图+预算建议 |
| 8 | Token优化最佳实践手册 | 文档（9章） | 含实测数据 |
| 9 | 企业Token管控SOP | 文档（5个SOP） | 可直接推广 |
| 10 | 答辩演示 | PPT+现场演示 | 3+面试官通过 |
