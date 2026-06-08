# AI Router 竞品调研与成本模型

> 调研日期：2026-06-05  
> 用途：支撑第 1 周《系统设计文档》的竞品调研、模型定价、成本模型和 Claude 降本机制章节。  
> 注意：模型价格变化很快，生产环境以供应商官方价格页和 `data/models.yaml` 的配置快照为准。

---

## 一、调研结论

AI Router 不定位为单纯的 LLM Gateway，也不定位为单纯的 Observability 工具，而是一个**任务语义驱动的企业级路由与管控系统**：

- Gateway 类产品解决“怎么统一调用模型”，但通常不理解开发任务的复杂度、风险、可验证性。
- Observability 类产品解决“发生了什么、花了多少钱”，但通常不在调用前做强制路由和预算门禁。
- AI Router 的差异化在于：**任务分类 -> 模型/策略推荐 -> 成本预估 -> 预算/审核门禁 -> 执行反馈 -> 规则迭代**。

---

## 二、竞品能力矩阵

| 方案 | 核心定位 | 已有强项 | 对 AI Router 的启发 | 主要缺口 |
|------|----------|----------|---------------------|----------|
| OpenRouter | 多模型访问与供应商路由 | Provider 顺序、fallback、价格/延迟偏好、数据保留约束、BYOK 路由；官方文档支持 `allow_fallbacks`、`max_price`、`zdr`、`preferred_max_latency` 等路由参数。来源：[OpenRouter Provider Routing](https://openrouter.ai/docs/guides/routing/provider-selection/) | Provider routing 的参数设计可借鉴；未来 Adapter 层可接 OpenRouter | 不内置企业开发任务 Taxonomy；缺少“任务风险 -> 人工批准 -> 质量门禁”的闭环 |
| LiteLLM | 统一 LLM Gateway / Proxy | OpenAI 格式统一 100+ 模型；Proxy 支持认证、预算、成本跟踪、Rate Limiting；SDK 有 retry/fallback。来源：[LiteLLM Docs](https://docs.litellm.ai/) | 统一接口、预算与虚拟 Key 管理值得借鉴 | 偏基础设施网关，不负责开发任务分类和质量-成本策略解释 |
| Helicone | AI Gateway + LLM Observability | Gateway、成本跟踪、Prompt 管理、Caching、自定义限流、Fallback；官方对比强调完整可观测性与成本追踪。来源：[Helicone AI Gateway](https://docs.helicone.ai/gateway/overview) | 观测维度、告警、缓存与限流可作为 Week 3 看板参考 | 不以“任务语义路由”作为核心，不负责按复杂度/风险生成模型组合 |
| Langfuse | LLM Observability / Tracing / Evals | Trace 捕获 prompt、response、token、latency、tool/retrieval step；支持 token/cost tracking、metrics API、prompt management、experiments。来源：[Langfuse Observability](https://langfuse.com/docs/observability/overview)、[Token & Cost Tracking](https://langfuse.com/docs/observability/features/token-and-cost-tracking) | Trace、dataset、eval 和 cost attribution 可作为后续集成方向 | 更偏事后观测与评测，不直接提供调用前强制路由决策 |
| Claude Code 原生用量能力 / Claude-tap 类工具 | Claude Code 使用量追踪 | Claude Code 官方提供成本管理、团队限额、用量追踪和 OpenTelemetry 指标；第三方本地工具常读取本地日志做成本展示。来源：[Claude Code Costs](https://code.claude.com/docs/en/costs)、[Claude Code Monitoring](https://code.claude.com/docs/en/monitoring-usage) | Agent 场景中必须按 client_type、project、tool、model 归因 | 通常只覆盖 Claude Code，不覆盖跨供应商模型路由与企业策略治理 |

### Gap 分析

现有工具通常只覆盖以下链路的一部分：

```text
统一调用模型 -> 记录 token/cost -> 看板展示
```

AI Router 要补齐的是：

```text
任务语义分类 -> 硬约束过滤 -> 成本/质量评分 -> 预算/审核门禁 -> 可解释决策 -> 执行反馈 -> 策略回测
```

这也是为什么本项目不直接采用 LiteLLM / OpenRouter 作为主系统：它们可以成为 Adapter 或 Gateway 插件，但不能替代路由引擎本身。

---

## 三、6+ 模型定价结构调研

单位说明：

- 海外模型价格按 USD / 1M tokens 记录。
- 国产模型 MVP 配置按 CNY / 1M tokens 记录，生产前必须再次核对控制台价格。
- `cached input`、`cache hit`、`cache write`、`Batch` 的语义在不同供应商之间不完全一致，不能直接混用，需要归一化到成本模型。

| Provider | 模型 | 输入 | 缓存写入 / 读取 | 输出 | Batch | 备注 |
|----------|------|------|-----------------|------|-------|------|
| Anthropic | Claude Opus 4.8 | $5.00 | 5m write $6.25；1h write $10.00；cache read $0.50 | $25.00 | $2.50 input / $12.50 output | 来源：[Anthropic Pricing](https://platform.claude.com/docs/en/about-claude/pricing) |
| Anthropic | Claude Sonnet 4.6 | $3.00 | 5m write $3.75；1h write $6.00；cache read $0.30 | $15.00 | $1.50 input / $7.50 output | 适合作为复杂编码默认强模型 |
| Anthropic | Claude Haiku 4.5 | $1.00 | 5m write $1.25；1h write $2.00；cache read $0.10 | $5.00 | $0.50 input / $2.50 output | 适合作为简单任务/批量执行层 |
| OpenAI | GPT-5.5 | $5.00 short context；$10.00 long context | cached input $0.50 / $1.00 | $30.00 / $45.00 | 标准价 50% 左右 | 来源：[OpenAI Pricing](https://developers.openai.com/api/docs/pricing) |
| OpenAI | GPT-5.4 nano | $0.20 | cached input $0.02 | $1.25 | $0.10 input / $0.625 output | 可作为低价分类/摘要参考 |
| DeepSeek | deepseek-v4-pro | cache miss $0.435 | cache hit $0.003625 | $0.87 | 未见官方 Batch 价 | 来源：[DeepSeek Pricing](https://api-docs.deepseek.com/quick_start/pricing) |
| DeepSeek | deepseek-v4-flash | cache miss $0.14 | cache hit $0.0028 | $0.28 | 未见官方 Batch 价 | 官方上下文长度 1M，输出上限 384K |
| Google | Gemini 3.5 Flash | $1.50 | context caching $0.15 + storage $1 / 1M tokens / hour | $9.00 | $0.75 input / $4.50 output | 来源：[Gemini Pricing](https://ai.google.dev/gemini-api/docs/pricing) |
| Google | Gemini 3.1 Flash-Lite | $0.25 | context caching $0.025 + storage $1 / 1M tokens / hour | $1.50 | 见官方 Batch/Flex/Priority 分层 | 高吞吐低价任务参考 |
| Alibaba Cloud | qwen3.7-max | MVP 配置：¥20.00 | MVP 配置：cache read 0.1x；write 1.25x | MVP 配置：¥60.00 | 待控制台复核 | 模型存在性来源：[阿里云模型列表](https://help.aliyun.com/zh/model-studio/models)，价格以控制台/合同为准 |
| Alibaba Cloud | qwen3.7-plus | MVP 配置：¥8.00 | MVP 配置：cache read 0.1x；write 1.25x | MVP 配置：¥20.00 | 待控制台复核 | 当前项目 Tier 2 主力 |
| Zhipu | glm-5.1 | MVP 配置：¥10.00 | 未启用 | MVP 配置：¥25.00 | 待官方价格页复核 | 来源入口：[智谱开放平台 Pricing](https://open.bigmodel.cn/pricing) |

### 关键观察

1. 输出 token 通常显著贵于输入 token，编码 Agent 的成本控制不能只盯上下文压缩，也要控制输出长度和重试次数。
2. Prompt Caching / Context Caching 的“读命中”很便宜，但首次写入、TTL、前缀稳定性和存储费会影响净收益。
3. Batch API 通常以更高延迟换 50% 左右价格折扣，适合离线评测、批量文档、夜间审计，不适合交互式 coding loop。
4. 国产模型的 OpenAI-compatible 接口适合 MVP 快速验证，但价格、缓存语义、上下文上限需要以实际控制台和 API response 校准。

---

## 四、统一成本模型

### 4.1 单次调用归一化公式

```text
base_input_cost =
  uncached_input_tokens / 1e6 * input_price

cache_write_cost =
  cache_write_tokens / 1e6 * input_price * cache_write_multiplier

cache_read_cost =
  cache_read_tokens / 1e6 * input_price * cache_read_ratio

output_cost =
  (visible_output_tokens + reasoning_tokens + thinking_tokens) / 1e6 * output_price

tool_cost =
  web_search_calls * search_unit_price
  + code_execution_minutes * container_unit_price
  + cache_storage_mtok_hours * storage_unit_price

batch_multiplier =
  0.5 when provider Batch API is used and officially supported, otherwise 1.0

total_cost =
  (base_input_cost + cache_write_cost + cache_read_cost + output_cost) * batch_multiplier
  + tool_cost
```

设计含义：

- 输出 token、reasoning token、thinking token 统一视为 output-side 成本。
- 缓存写入和缓存读取必须分开记录，不能只记录一个 `cached_tokens`。
- 工具调用费用独立于 token 费用，不应塞进模型单价。
- CNY 预算下使用 `exchange_rate_usd_cny` 转换，转换率必须作为配置快照入库。

### 4.2 多模型策略成本

```text
strategy_cost =
  planner_cost
  + sum(executor_step_cost_i)
  + reviewer_cost
  + retry_cost
```

Plan-Execute 的节省来自两点：

1. planner 只处理全局上下文和任务分解；
2. executor 每一步只拿局部上下文，且可使用低价模型。

因此不能只比较“同一 prompt 给强模型 vs 给弱模型”，必须建模上下文局部化。

### 4.3 月成本模拟

示例工作负载：

- 100,000 个开发任务 / 月
- 平均每任务 20K input + 4K output
- 月总量：2B input + 400M output
- 不含工具调用、重试和企业折扣

| 策略 | 估算月成本 | 相对全 Opus |
|------|------------|-------------|
| 全部 Claude Opus 4.8 | $20,000 | 基线 |
| 全部 Claude Sonnet 4.6 | $12,000 | 节省 40% |
| 全部 Claude Haiku 4.5 | $4,000 | 节省 80%，但质量风险高 |
| 智能路由：15% Opus + 55% Sonnet + 30% Haiku | $10,800 | 节省 46% |
| 智能路由 + 30% input 有效 cache read | $9,342 | 节省 53% |

如果企业当前真实消耗为 $30K-$40K / 天，则月基线约 $900K-$1.2M。即使只实现 20% 的净节省，也对应 $180K-$240K / 月；这就是本项目优先做路由、预算和审计的业务价值。

---

## 五、Claude 原生降本机制

### 5.1 Prompt Caching

官方定价语义：

- 5 分钟缓存写入：1.25x base input price。
- 1 小时缓存写入：2x base input price。
- 缓存读取命中：0.1x base input price。
- 可与 Batch API 等定价修饰叠加。

使用决策：

| 场景 | 是否启用 | 理由 |
|------|----------|------|
| 单次问答 | 不启用 | 没有后续读取，写入成本可能更高 |
| Agent 多轮编码 | 启用 | System prompt、工具定义、项目规则稳定，读命中收益大 |
| 大型固定文档反复问答 | 启用 | 固定前缀长且重复访问 |
| 每次上下文完全不同的随机任务 | 不启用 | 前缀不稳定，命中率低 |
| 长耗时任务 | 优先 1h cache | 5m TTL 可能在任务中途过期 |

### 5.2 Extended / Adaptive Thinking

官方文档说明，Claude 的 extended thinking / adaptive thinking用于复杂任务推理；`budget_tokens` 控制内部推理预算，当前/未来模型上 adaptive thinking 正在成为推荐路径。来源：[Claude Extended Thinking](https://platform.claude.com/docs/en/build-with-claude/extended-thinking)。

使用决策：

| 场景 | 建议 |
|------|------|
| SIMPLE / LOW risk | 不启用或低 effort，避免无意义 output-side 成本 |
| COMPLEX 代码审查、安全分析、架构设计 | 启用 adaptive thinking 或较高 effort |
| 需要严格成本上限的任务 | 设置 thinking/output budget，并纳入 hard budget |
| 交互式 CLI | 默认中等 effort，只有高风险/低可验证任务升档 |
| 批量 Benchmark | 记录 thinking token，避免把质量提升误判为免费 |

### 5.3 Batch API

Anthropic、OpenAI、Gemini 官方定价均存在 Batch 或类似异步低价模式。典型策略：

| 场景 | 是否使用 Batch |
|------|----------------|
| 离线 Benchmark | 使用 |
| 夜间 Token 审计 | 使用 |
| 批量文档生成 | 使用 |
| 用户实时 `analyze` | 不使用 |
| 交互式 Agent coding loop | 不使用 |

### 5.4 决策树

```text
任务是否实时交互？
  ├─ 否：优先 Batch
  └─ 是：
      是否存在稳定长前缀？
        ├─ 是：评估 Prompt Caching
        └─ 否：不计缓存收益
      是否复杂/高风险/低可验证？
        ├─ 是：启用强模型或 higher thinking effort
        └─ 否：降级到 Tier 2/Tier 3
      是否上下文 > 10K tokens？
        ├─ 是：先上下文预算与裁剪，再路由
        └─ 否：直接路由评分
```

---

## 六、落地到 AI Router 的设计要求

1. `ModelConfig` 必须显式记录 input/output/cache_write/cache_read/batch 能力，不允许把缓存折扣写死。
2. `CostEstimator` 必须输出 cost breakdown，至少包含 input、output、cache、batch、tool、retry 六类。
3. `RoutingDecision` 必须展示“与强模型基线相比的节省”和“相对候选最高质量的质量损失”，两者 baseline 不同。
4. `execution_feedback` 必须记录实际 token/cost，以便校准估算偏差。
5. Web 看板必须同时支持按 user、department、project、client_type、task_type、model 聚合。
6. 对于供应商价格页无法稳定抓取的模型，必须在 `config_snapshots` 里记录当时的定价版本和人工复核时间。

---

## 七、主要来源

- [Anthropic Claude API Pricing](https://platform.claude.com/docs/en/about-claude/pricing)
- [Anthropic Claude Extended Thinking](https://platform.claude.com/docs/en/build-with-claude/extended-thinking)
- [OpenAI API Pricing](https://developers.openai.com/api/docs/pricing)
- [DeepSeek Models & Pricing](https://api-docs.deepseek.com/quick_start/pricing)
- [Google Gemini Developer API Pricing](https://ai.google.dev/gemini-api/docs/pricing)
- [阿里云百炼模型列表](https://help.aliyun.com/zh/model-studio/models)
- [智谱 AI 开放平台 Pricing](https://open.bigmodel.cn/pricing)
- [OpenRouter Provider Routing](https://openrouter.ai/docs/guides/routing/provider-selection/)
- [LiteLLM Documentation](https://docs.litellm.ai/)
- [Helicone AI Gateway](https://docs.helicone.ai/gateway/overview)
- [Langfuse Observability](https://langfuse.com/docs/observability/overview)
- [Langfuse Token & Cost Tracking](https://langfuse.com/docs/observability/features/token-and-cost-tracking)
- [Claude Code Cost Management](https://code.claude.com/docs/en/costs)
- [Claude Code Monitoring](https://code.claude.com/docs/en/monitoring-usage)
