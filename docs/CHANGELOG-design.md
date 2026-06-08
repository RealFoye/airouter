# AI Router 设计方案变更记录

> 记录从初版方案到最终方案的所有讨论决策。每条变更记录：原来怎么做、现在改成什么、为什么改、改后好在哪。

---

## 变更总览

| # | 模块 | 变更标题 | 变更性质 |
|---|------|----------|----------|
| 1 | 项目定位 | 模型framing从"没有Claude"改为"模型无关架构" | 叙事调整 |
| 2 | 路由算法 | 从线性打分改为五层决策架构 | 架构重构 |
| 3 | 路由算法 | 新增硬约束过滤层 | 新增 |
| 4 | 能力匹配 | 从单层能力改为required/preferred双层 | 细化 |
| 5 | 能力匹配 | 额外能力bonus从无限改为上限0.05 | 修正 |
| 6 | 能力匹配 | 淘汰阈值从>0改为按复杂度分级 | 修正 |
| 7 | 成本效率 | 从单一归一化改为三档（linear/sqrt/log） | 细化 |
| 8 | 成本效率 | 成本权重从静态改为按任务类型动态调整 | 新增 |
| 9 | 延迟评分 | 公式从乘法改为加法（base + tokens × per_token） | 修正 |
| 10 | 历史质量 | 新增贝叶斯平滑 + 严重错误率 | 新增 |
| 11 | 质量公式 | Plan-Execute从乘法改为加权组合 | 修正 |
| 12 | Plan-Execute | 触发条件从"复杂就用"改为7条精确条件 | 细化 |
| 13 | Plan-Execute | 成本模型新增上下文局部化 | 重大修正 |
| 14 | 策略选择 | 新增PLAN_EXECUTE_REVIEW策略 | 新增 |
| 15 | 策略选择 | allowed_tiers从max_tier改为显式列表 | 修正 |
| 16 | 策略选择 | Top-K控制引入分层pre_score | 细化 |
| 17 | TaskFeatures | 从4个字段扩展到13个字段 | 扩展 |
| 18 | 企业管控 | 新增预算约束（budget_limit） | 新增 |
| 19 | 企业管控 | 新增人工审核触发规则（requires_human_review） | 新增 |
| 20 | 企业管控 | 新增质量门禁（quality_gate） | 新增 |
| 21 | 企业管控 | 新增Fallback策略（分MVP/扩展两期） | 新增 |
| 22 | 成本预估 | 从简单公式改为三层成本模型 | 架构重构 |
| 23 | 成本预估 | Prompt Caching从假设60%改为场景化精确模型 | 重大修正 |
| 24 | 审计追溯 | 新增routing_decisions完整字段 + execution_feedback表 | 新增 |
| 25 | 缓存机制 | 新增路由决策缓存（幂等性+版本绑定） | 新增 |
| 26 | Benchmark | 从120+条×5模型改为三级Benchmark（~260次调用） | 架构重构 |
| 27 | Benchmark | 评分从LLM-as-Judge为主改为混合评分+交叉验证 | 重大修正 |
| 28 | Context Rot | 实验规模从150次缩减到45次调用 | 缩减 |
| 29 | 策略质量 | 权重从固定公式改为按策略类型配置化 | 细化 |
| 30 | Guided Execute | 触发条件从简单判断改为多条件检查 | 细化 |
| 31 | Context Rot | 从"独立研究方向"降级为"上下文工程验证模块"，45→27次调用 | 降级+缩减 |
| 32 | 上下文工程 | 从"承诺型指标"改为"场景限定+离线验证+运行时保守执行" | 重大修正 |
| 33 | Web平台 | 从6页并列改为P0/P1/P2/P3四级分级+执行顺序 | 架构重构 |
| 34 | 数据存储 | 从产品化Schema改为YAML配置+4张运行表+控制面/数据面分离 | 架构重构 |
| 35 | 四周计划 | 从理想化排期改为"核心链路优先+每周检查点+上下文工程拆两周" | 重排 |
| 36 | 评分体系 | 从自定义8维度改回原任务6维度（15/20/20/15/15/15） | 重大修正 |
| 37 | Benchmark | 总调用量从~242次修正为~152次（数学错误修正） | 修正 |
| 38 | 交付物 | Benchmark验收标准从"6类×20+"改为区分离线/实测/回测 | 澄清 |
| 39 | 四周计划 | D14工作量拆分：DB schema提前到D8，种子数据提前到D10 | 修正 |
| 40 | Web平台 | 新增FastAPI降级方案（可直接调用engine层） | 新增 |
| 41 | 架构图 | SQLite标注补上config_snapshots（4张表完整展示） | 修正 |
| 42 | 硬约束 | 预算过滤从单层改为soft/hard两层 | 修正 |
| 43 | Plan-Execute | 成本公式新增overlap_factor防止子任务多时上下文重复读取 | 修正 |
| 44 | 能力匹配 | capability_score伪代码补preferred_coverage计算+除零保护 | 修正 |
| 45 | 特征提取 | LLM模式延迟从"<500ms承诺"改为"不承诺固定延迟" | 修正 |
| 46 | 设计原则 | "路由不依赖LLM"澄清为"策略选择不依赖，LLM仅用于可选特征提取" | 澄清 |
| 47 | 成本承诺 | "成本降低40-60%"改为条件性目标"20-60%，取决于可拆解性" | 修正 |
| 48 | Prompt Caching | 参数标注"待Week 1实测确认"+模型名标注为MVP角色占位 | 澄清 |
| 49 | 交付物 | 测试覆盖率从全项目80%改为"核心模块≥80%" | 修正 |
| 50 | 四周计划 | 新增MVP最小成功标准（7条） | 新增 |
| 51 | Web平台 | P0优先级说明：答辩优先级≠开发顺序 | 澄清 |
| 52 | 四周计划 | D21/D27预录视频口径统一：D21第一版备份，D27最终答辩版 | 澄清 |
| 53 | 能力匹配 | 4.4.1重复旧代码删除，统一引用4.2.1实现 | 修正 |
| 54 | 成本效率 | 三种归一化（linear/sqrt/log）全部Week 2实现，不再仅实现linear | 增强 |
| 55 | 硬约束 | hard_budget_limit从"直接排除"改为"标记需审批，保留为候选" | 修正 |
| 56 | 管控门禁 | Selector/Gate 职责分离：Gate 成为 requires_human_review 唯一决定者 | 架构重构 |
| 57 | 硬约束 | 预算过滤从"后置单次检查"改为"候选级标签" | 架构重构 |
| 58 | 测试策略 | 从"通路验证"补充"政策验证"：25 条管控规则测试 | 增强 |
| 59 | 质量基准 | quality_loss 从固定 0.90 改为候选集最高质量 | 重大修正 |
| 60 | 管控门禁 | soft budget 不再触发人工审核，仅 warning | 语义修正 |
| 61 | 管控门禁 | quality_loss 审核加 risk_level != LOW 前置条件 | 语义修正 |
| 62 | 设计原则 | cost baseline 和 quality baseline 故意不对称 | 澄清 |
| 63 | 策略选择 | StrategyClassifier 与 Selector 职责分离 | 架构重构 |
| 64 | 能力匹配 | 角色级能力过滤（executor 不要求 architecture） | 细化 |
| 65 | 策略选择 | Top-K 在角色池内执行，遍历组合替代 max() | 细化 |
| 66 | Schema | AlternativeStrategy 支持 planner/executor/reviewer 多角色 | 扩展 |
| 67 | 数据存储 | SQLite 外键强制 + ORM/Pydantic 命名对齐 | 修正 |
| 68 | 审计引擎 | Collector/Aggregator/Detector/Attribution 四层架构 + 5 类浪费模式 | 新增 |
| 69 | 审计引擎 | 种子数据参数化 + 浪费模式注入 | 新增 |
| 70 | 审计引擎 | CLI audit 命令（Rich 格式 + JSON 输出） | 新增 |
| 71 | 审计引擎 | P4 可降级逻辑修正（min → max）+ P5 缓存检测修正 + JSON 结构化输出 | 修正 |
| 72 | 审计引擎 | 种子数据从 load_models() 派生价格/tier/cache + P2/P5 时间戳有界 + 集成测试自包含 | 修正 |
| 73 | 审计引擎 | 种子数据 execution_feedback.created_at 有界化 + 不早于 routing_decisions | 修正 |
| 74 | 上下文工程 | B-1 优先级框架 + B-2 压缩引擎（6 层优先级 + 6 种摘要规则 + risk_level 绑定策略） | 新增 |
| 75 | 上下文工程 | ContextBlock 自动 protected + token_count + strategy 大小写归一化 + NONE 仍做冗余剔除 | 细化 |
| 76 | 上下文工程 | Review 修复：AssemblyResult dataclass + NONE 预算裁剪 + 对话关键词大小写 + AGGRESSIVE 首末行 | 修正 |
| 77 | 优化引擎 | Phase 7续 optimize CLI：5 类优化建议（缓存/压缩/降级/裁剪/分层）+ 3 策略对比 | 新增 |
| 78 | 压缩引擎 | strategy_override 参数：支持强制指定压缩策略用于 3 策略对比展示 | 新增 |
| 79 | 优化引擎 | Review 修复：治理语义约束（降级/分层过滤、escalate 检测、互斥节省） | 修正 |
| 80 | 优化引擎 | Review 二轮修复：Gate 审批语义全量消费 + Engine 模型校验 + CLI Literal 校验 | 修正 |
| 81 | 优化引擎 | Review 三轮修复：requires_approval 按建议后方案重新判断 + 汇总逻辑抽取 + Engine 参数校验 | 修正 |
| 82 | 优化引擎 | Review 四轮修复：审批提示浮到 CLI 顶层 + budget_status 用真实计算 + Rich 表审批标签 | 修正 |
| 83 | Benchmark | Level 1 离线规则 Benchmark：40 条 YAML case + 6 指标 + CLI + 零 API 成本 | 新增 |

---

## 详细变更记录

### #1 模型framing：从"没有Claude"改为"模型无关架构"

**原来：**
> "我们没有Claude/GPT，只有国产模型。但这不是劣势，而是创新点。"

**改为：**
> "本系统采用模型无关的分层路由架构，不绑定单一厂商。当前MVP阶段优先使用国产模型进行验证，将Qwen、DeepSeek、GLM等模型映射为Tier 1/2/3三个能力层级。后续可通过统一Adapter无缝接入Claude、GPT、OpenRouter、LiteLLM等模型源。"

**为什么改：**
原表述暴露了"因为条件不足所以妥协"的味道，答辩时评委会认为这是退而求其次。改为"模型无关架构"后，叙事翻转为：架构设计本身就是通用的，国产模型只是MVP的验证载体。

**改了之后好在哪：**
- 答辩时展示的是架构能力，不是资源限制
- 模型表格新增"扩展模型"列（Claude Opus/Sonnet/Haiku、GPT系列），展示可扩展性
- 去掉了"类似Opus"的措辞，不再暗示"替代品"

---

### #2 路由算法：从线性打分改为五层决策架构

**原来：**
```
Score(model, task) = w1 × 能力匹配度 + w2 × 成本效率 + w3 × 延迟评分 + w4 × 历史质量
```
线性流程：过滤 → 评分 → 选择 → 策略判定 → 输出

**改为：**
```
第1层：任务画像（13维特征提取）
第2层：硬约束过滤（排除不可用模型）
第3层：策略候选生成（生成可行策略+模型组合）
第4层：多目标评分（对每个候选策略计算四维得分）
第5层：决策输出+管控门禁（预算/审核/质量门禁/Fallback）
```

**为什么改：**
原来的流程没有约束层——分数再高，有些场景也不能让低成本模型执行。企业级路由不是简单打分，而是"先排除不能选的，再在可选范围内做成本质量最优"。

**改了之后好在哪：**
- 硬约束保证安全边界，避免"便宜模型分数高就选便宜模型"
- 策略本身也作为候选对象打分，而不是"先定策略再选模型"
- 管控门禁让系统从"推荐器"升级为"管控系统"

---

### #3 新增硬约束过滤层

**原来：** 没有独立的硬约束层，仅靠评分权重间接控制。

**改为：** 新增第2层硬约束过滤，包括：
- 能力覆盖率 ≥ 按复杂度分级的最低阈值
- Tier必须在允许范围内（allowed_tiers）
- 上下文窗口足够
- 数据敏感性限制
- 预算约束

**为什么改：**
没有硬约束，分数再高也可能突破安全边界。比如敏感数据任务，即使便宜模型分数高也不应该选。

**改了之后好在哪：**
- 答辩时可以回答"如果便宜模型分数高但任务很敏感怎么办"
- 不同复杂度有不同约束强度（EXPERT必须100%能力覆盖，SIMPLE允许50%）

---

### #4 能力匹配：required/preferred双层

**原来：** 只有一层 `required_capabilities`。

**改为：** 拆分为：
- `required_capabilities`：必须覆盖，缺失则按阈值淘汰
- `preferred_capabilities`：加分项，上限0.05，仅作tie-breaker

评分公式：`0.85 × required_coverage + 0.15 × preferred_coverage + preferred_bonus`

高风险任务必须100%覆盖required，低风险允许部分缺失。

**为什么改：**
有些能力是"锦上添花"而非"不可或缺"。比如代码生成任务的preferred是`{documentation}`，没有也能跑，但有了更好。

**改了之后好在哪：**
- 避免过度淘汰（部分能力缺失但够用的模型不会被误杀）
- 高风险任务有更强保障（required必须100%覆盖）

---

### #5 额外能力bonus从无限改为上限0.05

**原来：** `bonus = len(extra_capabilities) * 0.02`，无上限。

**改为：** `bonus = min(0.05, len(matched_preferred) * 0.01)`，且仅作tie-breaker。

**为什么改：**
Tier 1模型能力标签多（code_gen, code_review, architecture, complex_reasoning...），每个简单任务都会拿到额外bonus，导致高价模型在简单任务上也经常赢。这和"省Token"目标冲突。

**改了之后好在哪：**
- 简单任务不会被"全能型"高价模型抢走
- 真正体现了"成本优先"的设计目标

---

### #6 能力淘汰阈值从>0改为按复杂度分级

**原来：** `if not matched: return 0.0`（只要匹配一个能力就进入候选）。

**改为：**
```
SIMPLE → 最低覆盖率0.50
MODERATE → 0.70
COMPLEX → 0.85
EXPERT → 1.00
```

**为什么改：**
原来太宽松。比如架构任务需要`{architecture, complex_reasoning, security}`，某模型只有`{complex_reasoning}`就能进入候选，虽然缺了architecture能力。

**改了之后好在哪：**
- EXPERT任务必须完全覆盖，避免能力不足的模型执行关键任务
- 简单任务容忍度高，不会过度淘汰

---

### #7 成本归一化：从单一公式改为三档

**原来：** 统一使用 `min_cost / model_cost`（linear归一化）。

**改为：** 根据任务的 `cost_sensitivity` 选择归一化方式：
```
HIGH   → linear: min_cost / cost    （42x价差→得分0.024，强烈倾向便宜模型）
MEDIUM → sqrt:   sqrt(min_cost/cost)（42x价差→得分0.155，平衡）
LOW    → log:    1/(1+log(cost/min))（42x价差→得分0.212，不过度惩罚贵模型）
```

**为什么改：**
`cost_sensitivity`是**任务属性**不是模型属性。批量格式转换（HIGH）应该强烈倾向便宜模型，架构设计（LOW）不应该因为贵模型成本高就直接排除。单一linear公式会导致贵模型在所有任务上cost分都极低。

**改了之后好在哪：**
- 高成本敏感任务：低价模型有压倒性优势
- 低成本敏感任务：贵模型不会被过度惩罚，质量和能力可以发挥作用
- 答辩时可以演示同一模型在不同任务下cost分不同

---

### #8 成本权重从静态改为按任务类型动态调整

**原来：** 全局固定权重 `cost: 0.30`。

**改为：** 按任务类型覆盖：
```yaml
ARCHITECTURE:    cost: 0.15  # 架构设计：质量>成本
TEST_GENERATION: cost: 0.40  # 测试生成：成本>质量
BUG_ANALYSIS:    cost: 0.20  # Bug分析：能力+质量
default:         cost: 0.30
```

**为什么改：**
不是所有任务都同等重视成本。生产事故根因分析值得用贵模型，批量测试生成应该选便宜的。

**改了之后好在哪：**
- 系统能区分"值得花钱"和"不该浪费钱"的任务
- 答辩时演示"调整权重，实时看路由决策变化"就是规则管理功能

---

### #9 延迟公式修正

**原来：**
```python
output_factor = min(2.0, estimated_output_tokens / 1000)
estimated_latency = base_latency * output_factor
```

**改为：**
```python
estimated_latency = base_latency + output_tokens * per_output_token_ms
# Tier 1: base=1500ms, per_token=8ms
# Tier 2: base=900ms,  per_token=5ms
# Tier 3: base=500ms,  per_token=3ms
```

**为什么改：**
原公式在output_tokens<1000时（比如300），`output_factor=0.3`，延迟被压得过低。但即使输出很短，也有网络开销、排队、首token延迟。改为`base + tokens × per_token`更符合实际API行为（首token延迟+生成延迟）。

**改了之后好在哪：**
- 短输出不会被低估延迟
- 符合真实API的延迟构成（首token延迟 + 逐token生成）

---

### #10 历史质量：贝叶斯平滑 + 严重错误率

**原来：** 默认值硬编码在代码中，没有平滑机制，没有严重错误率。

**改为：**
1. 默认值放YAML配置，标注来源（模型能力假设+先验评估+Benchmark校准）
2. 贝叶斯平滑：`prior_weight = max(0, 20 - n_samples)`，样本越多越信任真实数据
3. 新增严重错误率：`effective_quality = avg_quality × (1 - severe_failure_rate)`

**为什么改：**
- 默认值硬编码会被问"怎么来的"
- 没有平滑机制会导致小样本偏差
- 只看平均质量不够：Tier 2平均0.78但5%严重错误率 vs Tier 3平均0.72但25%严重错误率，后者风险高很多

**改了之后好在哪：**
- 答辩可以说"冷启动先验+Benchmark后验"的渐进学习
- 企业场景不只关心平均分，更关心翻车概率

---

### #11 Plan-Execute质量公式：乘法改加权组合

**原来：**
```python
quality = plan_quality * executor_quality
# 0.85 * 0.75 = 0.6375 → 显得Plan-Execute质量很低
```

**改为：**
```yaml
strategy_quality_weights:
  PLAN_EXECUTE:         { plan: 0.55, execute: 0.45, review: 0.00 }
  PLAN_EXECUTE_REVIEW:  { plan: 0.45, execute: 0.35, review: 0.20 }
  GUIDED_EXECUTE:       { plan: 0.00, execute: 0.70, review: 0.30 }
```

**为什么改：**
乘法过度惩罚（两者任一低则整体很低）。实际上好计划可以显著提升Tier 3的执行质量，不应该完全相乘。不同策略的规划/执行/审查角色不同，权重也应该不同。

**改了之后好在哪：**
- 质量估算更合理，不会因为公式问题否决Plan-Execute
- PLAN_EXECUTE_REVIEW有review兜底，planning权重适当降低（0.55→0.45）
- 权重可配置，后续可以根据Benchmark数据调整

---

### #12 Plan-Execute触发条件：从粗糙到精确

**原来：** `complexity in ["COMPLEX", "EXPERT"] → Plan-Execute`

**改为：** 必须同时满足7条：
1. complexity ∈ {COMPLEX, EXPERT}
2. estimated_output_tokens ≥ 500
3. reasoning_intensity ∈ {HIGH, VERY_HIGH}
4. subtasks数量 ≥ 2（可分解）
5. verifiability ≥ MEDIUM 或 risk_level == LOW（可验证或低风险）
6. 预估成本节省率 ≥ 15%（break-even）
7. 预估质量损失 ≤ 15%

**为什么改：**
"复杂就用Plan-Execute"太粗糙。输出量小时规划开销不值得、不可分解的任务Tier 3无法独立执行、结果不可验证且高风险的任务不适合低价模型执行。

**改了之后好在哪：**
- 避免了"规划开销 > 节省"的反向情况
- 加入了可验证性条件：Plan-Execute最适合"复杂但可拆解、执行步骤明确、输出量大、结果可验证、执行风险不高"的任务

---

### #13 Plan-Execute成本模型：新增上下文局部化

**原来：**
```python
executor_input = input_tokens + planner_output + 300  # executor仍吃完整上下文！
```

**改为：**
```python
subtask_context_ratio = 0.35  # 每个子任务只需35%的全局上下文
executor_input_per_call = input_tokens * 0.35 + planner_output / num_subtasks + 300
total_executor_cost = executor_cost_per_call * num_subtasks
```

**为什么改：**
这是整个讨论中最大的修正。原来executor仍然吃完整输入上下文（12.3K tokens），这意味着Plan-Execute只是模型降级，没有体现上下文缩小的价值。真正的节省来自两个维度：**模型降级 + 上下文局部化**。"Tier 1看全局，Tier 3看局部"才是Plan-Execute的核心优势。

**改了之后好在哪：**
- 成本公式真正体现了拆分的价值
- 答辩时可以说"如果executor吃完整上下文，Plan-Execute只是降级；上下文局部化才是核心创新"
- 成本预估更准确

---

### #14 新增PLAN_EXECUTE_REVIEW策略

**原来：** 只有3种策略（SINGLE_MODEL / GUIDED_EXECUTE / PLAN_EXECUTE）。

**改为：** 4种策略，新增PLAN_EXECUTE_REVIEW：
```
SINGLE_MODEL:          单模型端到端
GUIDED_EXECUTE:        Tier 2执行 + Tier 1审查
PLAN_EXECUTE:          Tier 1规划 + Tier 2/3执行
PLAN_EXECUTE_REVIEW:   Tier 1规划 + Tier 2/3执行 + Tier 1审查
```

**为什么改：**
高风险的复杂任务既需要规划（Plan）又需要审查（Review）。原来只有PLAN_EXECUTE没有审查兜底，GUIDED_EXECUTE又只有审查没有规划。

**改了之后好在哪：**
- 覆盖了"高风险+复杂"的场景
- 执行模型根据风险选择（HIGH风险用Tier 2而非Tier 3）

---

### #15 allowed_tiers从max_tier改为显式列表

**原来：** `m.tier <= get_max_tier_for_complexity(features.complexity)`

**改为：**
```yaml
allowed_tiers:
  SIMPLE:   { default: [3], high_risk: [2, 3] }
  MODERATE: { default: [2, 3], high_risk: [1, 2] }
  COMPLEX:  { default: [1, 2] }
  EXPERT:   { default: [1] }
```

**为什么改：**
原代码有逻辑错误。Tier 1 < Tier 2 < Tier 3的编号下，`max_tier=3`意味着所有Tier都允许。但SIMPLE任务应该**只用**Tier 3，不是"允许到Tier 3"。

**改了之后好在哪：**
- 语义正确：SIMPLE只能[3]，EXPERT只能[1]
- 支持risk_level覆盖（高风险SIMPLE允许[2,3]）

---

### #16 Top-K控制：引入分层pre_score

**原来：**
```python
tier1_candidates = top_k(tier=1, sort_by="capability_score")
tier3_candidates = top_k(tier=3, sort_by="cost_efficiency")
```

**改为：** 每个Tier有不同的pre_score权重：
```yaml
tier1: { capability: 0.50, quality: 0.35, cost: 0.15 }  # 看重能力和质量
tier2: { capability: 0.40, quality: 0.30, cost: 0.30 }  # 均衡
tier3: { capability: 0.30, quality: 0.20, cost: 0.50 }  # 看重成本
```

**为什么改：**
不同Tier定位不同。Tier 2是性价比核心，只按capability排序不合理。

**改了之后好在哪：**
- 预排序更符合各层定位
- 避免组合爆炸（每个Tier只取Top-2）

---

### #17 TaskFeatures从4个字段扩展到13个

**原来：**
```python
category, complexity, context_requirement, reasoning_intensity
```

**改为：**
```python
# 基础分类
category, complexity
# 风险与约束（新增）
risk_level, sensitivity, verifiability, output_strictness
# 资源需求
context_requirement, reasoning_intensity, estimated_input_tokens, estimated_output_tokens
# 结构特征
subtasks, required_capabilities, preferred_capabilities
```

**为什么改：**
原来只有4个字段，无法支持路由算法所需的风险约束、策略选择和质量门禁。关键缺失：
- `risk_level`：决定能否用低价模型
- `verifiability`：决定能否Plan-Execute
- `output_strictness`：决定是否需要格式校验
- `sensitivity`：决定能否使用某些模型

**改了之后好在哪：**
- 路由算法有完整的任务画像支撑
- 每个字段都有明确的用途（文档中标注了"用途"列）

---

### #18 新增预算约束（budget_limit）

**原来：** 没有预算概念。

**改为：** 三层预算体系（MVP用静态配置）：
```yaml
budgets:
  projects:
    ai-router: { monthly_budget_cny: 3000, task_budget_default_cny: 0.50 }
  task_type_limits:
    SIMPLE:   { max_cost_cny: 0.05 }
    MODERATE: { max_cost_cny: 0.30 }
    COMPLEX:  { max_cost_cny: 2.00 }
    EXPERT:   { max_cost_cny: 10.00 }
```

超预算时输出替代方案：降级模型 / 裁剪上下文 / 申请审批。

**为什么改：**
没有budget_limit，系统只是"推荐器"；有了它，系统才是"管控系统"。企业做Token管控的核心问题之一就是"这个任务能不能花这么多钱"。

**改了之后好在哪：**
- CLI输出可以展示预算状态和替代方案
- 答辩时演示超预算场景非常有说服力

---

### #19 新增人工审核触发规则

**原来：** 没有人工审核概念。

**改为：** MVP阶段，满足任一条件触发 `requires_human_review = true`：
1. sensitivity == HIGH（敏感数据）
2. risk_level == HIGH 且使用了降级/拆分策略
3. estimated_cost > budget_limit 且用户选择保持强模型
4. 无候选模型满足硬约束
5. quality_loss_vs_baseline > 0.20
6. 任务类型在人工审核配置列表中

**为什么改：**
高风险任务只要没有全程使用Tier 1，就需要人工确认。风险来自"执行错误后果"而非"花钱多"。

**改了之后好在哪：**
- 企业场景的安全网
- 不用"当且仅当"而用"满足任一条件"，规则可扩展

---

### #20 新增质量门禁（quality_gate）

**原来：** 没有质量门禁概念。

**改为：** 以task_type决定具体检查类型，verifiability/output_strictness/risk_level叠加额外检查：
```python
BASE_GATE = {
    "CODE_GENERATION": ["syntax_check", "ast_parse"],
    "DATA_PROCESSING": ["json_schema_check"],
    "ARCHITECTURE":    ["human_review"],
    ...
}
# output_strictness=HIGH → 追加format_check
# risk_level=HIGH → 追加human_review
# verifiability=LOW → 降级为llm_judge或human_review
```

**为什么改：**
不同任务的可验证方式完全不同。JSON用schema校验，代码用AST+单测，架构设计只能人工评审。不能一刀切。

**改了之后好在哪：**
- 质量验证精确匹配任务类型
- 高风险任务自动追加人工审查

---

### #21 新增Fallback策略（MVP/扩展两期）

**原来：** 没有失败兜底机制。

**改为：**
```python
# MVP必须实现（4条）
"API_TIMEOUT":   → 同Tier备用模型
"FORMAT_ERROR":  → 重试+格式提示
"QUALITY_BELOW": → 升级Tier
"NO_CANDIDATE":  → 人工兜底

# 后续扩展（2条）
"BUDGET_EXCEEDED":  → 降级或审批
"CONTEXT_OVERFLOW": → 裁剪重试
```

**为什么改：**
路由不是一次选择完就结束。真实系统要考虑API超时、格式错误、质量不合格等情况。FORMAT_ERROR从"可选"提升到"MVP必做"，因为实现简单（prompt重试）且非常常见。

**改了之后好在哪：**
- 系统有韧性，不会一次失败就中断
- 答辩时演示"降级后自动升级"很有说服力

---

### #22 成本预估：从简单公式改为三层成本模型

**原来：**
```
单模型成本 = input × price + output × price
Plan-Execute = Planner成本 + Executor成本
缓存预估节省 = cacheable_tokens × 0.9 × model_cache_discount（假设60%输入可缓存）
```

**改为：** 三层独立计算：
- 第一层：基础成本（input × price + output × price）
- 第二层：Prompt Caching调整（考虑模型是否支持、前缀稳定性、场景命中率）
- 第三层：Plan-Execute上下文局部化节省

**为什么改：**
原公式有多个问题：0.9和model_cache_discount语义重叠、60%命中率是拍脑袋、输出token不参与缓存、不是所有模型都支持缓存。

---

### #23 Prompt Caching：从假设60%改为场景化精确模型

**原来：** `缓存预估节省 = cacheable_tokens × 0.9 × model_cache_discount（假设60%输入可缓存）`

**改为：**
1. models.yaml新增缓存能力配置：`supports_prompt_caching`、`cache_write_price_multiplier`、`cache_read_price_ratio`、`cache_min_prefix_tokens`
2. 输入Token拆分为5部分（system_prompt / tool_definitions / fixed_context / conversation_history / dynamic_query）
3. 场景缓存命中率预估表（单次0%、Agent多轮40-70%、随机上下文≈0%）
4. 净收益 = 后续调用×命中率×读取节省 - 首次写入额外成本

**为什么改：**
- 不是所有国产模型都支持Prompt Caching（glm-5.1不支持）
- cache_write比普通input贵（1.25x），单次调用的缓存收益为零甚至为负
- 命中率取决于前缀稳定性，不是固定60%
- 输出token不参与缓存

**改了之后好在哪：**
- 成本预估更可信，不会被追问"60%怎么来的"
- 能正确识别"缓存不划算"的场景（单次调用、不支持的模型）
- CLI输出展示缓存详情（前缀长度、命中率、写入成本、净节省）

---

### #24 审计追溯：routing_decisions扩展 + execution_feedback新表

**原来：**
```sql
routing_decisions (id, task_description, extracted_features_json,
                   classification_result_json, selected_models_json,
                   cost_estimate_json, reasoning, created_at)
```

**改为：**
```sql
routing_decisions (id, task_hash, task_description, features_json,
    constraints_json, strategy_candidates_json, selected_strategy_json,
    score_breakdown_json, alternatives_json, cost_estimate_cny,
    budget_status, requires_human_review, human_review_reason,
    quality_gate_json, fallback_policy_json, config_version, created_at)

execution_feedback (id, routing_decision_id, selected_strategy,
    selected_models_json, actual_input_tokens, actual_output_tokens,
    actual_cost_cny, actual_latency_ms, quality_score,
    quality_gate_passed, user_accepted, override_reason, override_note, created_at)
```

**为什么改：**
- 原表只存了结果，没有存决策过程（候选策略、各维度得分、约束参数）
- 没有记录"路由推荐 vs 实际执行"的差异（用户可能override路由建议）
- 需要支撑后续的回测、调参和审计

**改了之后好在哪：**
- 回测：证明路由策略比全程Tier 1省钱
- 调参：分析哪些任务推荐错了，调整权重
- 审计：管理层问"为什么这个任务用了强模型"可追溯
- override分析：发现用户不信任路由推荐的原因

---

### #25 路由决策缓存（幂等性+版本绑定）

**原来：** 没有缓存机制。

**改为：**
```python
route_cache_key = hash(
    normalize(task_description)  # strip + lowercase + 合并空格
    + routing_rules_version
    + models_config_version
    + budget_policy_version
)
# TTL=5分钟，配置变更时版本递增→缓存自动失效
```

**为什么改：**
- 相同输入+相同配置应该返回相同结果（幂等性）
- 避免短时间内重复调用LLM做特征提取
- 只按task_description缓存不够，规则/价格/预算改了结果应该变

**改了之后好在哪：**
- CLI连续调用同一任务不会每次都调LLM
- 配置变更自动失效，不会返回过时结果

---

### #26 Benchmark：从120+条×5模型改为三级Benchmark

**原来：**
6类 × 20+条 × 5模型 = **600+次API调用**，加上Context Rot还要更多。

**改为：** 三级Benchmark，总计**~260次调用**：

| 层级 | 调用量 | 目的 |
|------|--------|------|
| Level 1 | 0次 | 100条离线规则测试（分类准确率、Tier推荐准确率） |
| Level 2 | ~115次 | 30条×3代表模型 + 5条×5模型横评 |
| Level 3 | 复用L2 | 路由策略回测（全程Tier 1 vs 智能路由） |
| Context Rot | ~45次 | 3模型×3任务×5长度梯度 |

**为什么改：**
- 600+次调用在4周内跑不完，评分也处理不过来
- Level 1（离线规则）成本为0，能验证路由引擎逻辑正确性
- Level 3（策略回测）才是项目核心论点，但之前没有设计

**改了之后好在哪：**
- API预算从750+降到260，4周内可完成
- Level 1先保证引擎逻辑正确，再跑Level 2
- Level 3直接证明"智能路由比全程Tier 1省钱65%"
- MVP阶段先过Level 1，渐进推进

---

### #27 评分方法：从LLM-as-Judge为主改为混合评分+交叉验证

**原来：**
```
需求满足度 → LLM-as-Judge（qwen3.7-max打分1-10）→ 权重40%
```

**改为：**
```
自动评分优先（60%）：AST解析+单测运行+漏洞命中率+结构检查
LLM Judge辅助（30%）：需求满足度+解释质量+修复建议质量
人工抽检兜底（10%）：20%常规抽检+争议case 100%复核+架构设计100%人工
交叉验证：10条case用deepseek-v4-pro做副裁判，检验评分一致率
```

**为什么改：**
- qwen3.7-max当裁判给自己打分，评委会质疑公正性
- LLM-as-Judge 40%权重太高，完全依赖LLM评分
- 代码任务可以用AST+单测自动评分，不需要LLM
- 没有人工兜底，评分可信度不足

**改了之后好在哪：**
- 自动评分优先，不依赖LLM来证明自己的价值
- 交叉验证可以报告"两个独立judge评分一致率85%，偏见可控"
- 不同任务用不同评分方式（代码跑测试、审查看命中率、架构必须人工）

---

### #28 Context Rot实验规模缩减

**原来：** 5模型 × 5任务 × 6长度梯度 = **150次调用**

**改为：** 3代表模型（每Tier 1个） × 3任务 × 5梯度 = **45次调用**

**为什么改：**
- 150次调用成本太高
- 核心目标不是测所有模型，而是对比不同Tier的退化差异
- "Tier 3模型是否在更短的上下文就开始退化"比"每个模型各自的退化曲线"更有价值

**改了之后好在哪：**
- 调用量减少70%
- 仍能产出有意义的Tier间对比数据
- 后续进一步降级为27次调用（见#31）

---

### #29 策略质量权重：从固定公式改为按策略类型配置化

**原来：** 所有策略用同一个质量公式。

**改为：**
```yaml
strategy_quality_weights:
  GUIDED_EXECUTE:      { plan: 0.00, execute: 0.70, review: 0.30 }
  PLAN_EXECUTE:        { plan: 0.55, execute: 0.45, review: 0.00 }
  PLAN_EXECUTE_REVIEW: { plan: 0.45, execute: 0.35, review: 0.20 }
```

**为什么改：**
不同策略中规划/执行/审查的角色不同。Plan-Execute-Review有review兜底，planning权重可以从0.55降到0.45。GUIDED_EXECUTE没有规划阶段，plan=0。

**改了之后好在哪：**
- 质量估算更精确
- 权重可配置，后续可根据Benchmark数据调整

---

### #30 Guided Execute触发条件细化

**原来：** `complexity == "MODERATE" and estimated_output_tokens > 800`

**改为：** 多条件检查：
1. complexity ∈ {MODERATE, COMPLEX}
2. estimated_output_tokens ≥ 800
3. risk_level != LOW（低风险不需要审查开销）
4. 预估成本节省率 ≥ 20%
5. verifiability != LOW 或 risk_level != HIGH（不能同时低可验证+高风险）

**为什么改：**
原来只看复杂度和输出量，没有考虑风险、可验证性和节省比例。低风险的MODERATE任务不需要审查开销，高风险+低可验证的任务不应该用弱模型执行。

**改了之后好在哪：**
- 避免在低风险任务上浪费审查成本
- 避免在高风险+低可验证任务上使用弱模型

---

### #31 Context Rot：从"独立研究方向"降级为"上下文工程验证模块"

**原来：**
方向D作为独立研究方向，包含4个子任务：
- D-1 退化曲线实验（3×3×5=45次调用）
- D-2 蠢笨区检测（实时监控+自动预警）
- D-3 治理策略（会话生命周期管理+上下文预算+渐进式裁剪+多会话协作）
- D-4 干扰物研究（量化无关文件影响）

**改为：**
方向D降级为方向B的验证实验模块，只保留2个子任务：
- D-1 上下文长度对比实验（3×3×3=27次调用，5K/20K/50K三档）
- D-2 退化阈值预警（集成到B-3预算管理模块，非独立系统）
- D-3 砍掉（治理策略已被方向B的B-3预算管理+B-4 Safe-Trim吸收）
- D-4 砍掉（干扰物研究4周内无法严谨完成）

**叙事从：** "Context Rot是独立的探索性研究方向"
**改为：** "主线是上下文工程（B），Context Rot实验验证其必要性"

**为什么改：**
1. **风险收益比不对**：45次API调用换"5梯度退化曲线"，严谨性不够，评审追问统计显著性就卡住
2. **时间挤占主线**：4周内Context Rot实验+评分+分析至少吃掉3-4天，影响核心路由引擎和Web平台
3. **D-3和方向B重复**：治理策略（会话管理、上下文预算、裁剪）本身就是方向B在做的东西
4. **D-4锦上添花**：干扰物研究需要更多实验轮次，4周内做不完
5. **两种结果都能用**：退化明显→证明预算策略有价值；不明显→说明模型能力强、参数可放宽

**改了之后好在哪：**
- API预算从260降到242，实验更可控
- 不会被评审追问"样本量够吗""p-value多少"——明确定位为探索性验证
- 方向B和D的关系清晰：B构建，D验证
- D-2不再是独立系统，直接回馈到路由引擎的上下文预算参数
- 答辩叙事更通顺："我们建了上下文预算系统→做了个小实验验证必要性→实验结果支持了我们的策略"
- 即使实验结果不理想，也不影响主线交付

---

### #32 上下文工程：从"承诺型指标"改为"场景限定+离线验证+运行时保守执行"

**原来：**
```
B-2 上下文压缩引擎 | Token减少30%+质量下降≤5%
B-4 Safe-Trim算法 | 算法实现+实测数据
```
四个子任务并列，B-4作为必做承诺。

**改为：**

1. **B-1/B-2/B-3为MVP必做**，B-4改为**条件启用**（仅当`supports_prompt_caching == true`时启用）
2. **压缩目标分层**：
   - < 5K tokens：不主动压缩，仅做冗余剔除
   - 5K-10K：轻量压缩，目标5-15%
   - 10K-30K：标准压缩，目标20-30%
   - > 30K：激进压缩或任务拆分，目标30%+
3. **压缩策略分级**（与risk_level打通）：
   - HIGH risk → Conservative（只剔除明显冗余）
   - MEDIUM risk → Standard（剔除+截断+摘要）
   - LOW risk → Aggressive（大幅摘要+局部化）
4. **质量保障三层机制**：
   - 离线验证：在Benchmark子集上测试各压缩策略的质量影响
   - 运行时质量门禁：不做双跑，只做轻量检查+失败时阶梯回退
   - 用户反馈闭环：路由结果展示压缩选项，反馈记录到execution_feedback
5. **质量阈值配置化**：`llm_judge_score_delta: 0.5`，不写死在文档中
6. **models.yaml增加caching字段**：`supports_prompt_caching: true/false/unknown`，`unknown`按`false`处理
7. **实验目标表述**："在Benchmark Level 2的长上下文子集（>10K tokens）中，观察20-30% Token减少"——**不作为所有任务的统一验收承诺**

**为什么改：**
1. "质量下降≤5%"是陷阱承诺——没有定义基线、测试集、测量方法，答辩现场被追问就卡住
2. B-4 Safe-Trim的前提是Prompt Caching支持，如果模型不支持就变成了"优化不存在的问题"
3. 30%压缩率对SIMPLE任务（2-5K tokens）不现实，只有长上下文场景（>10K）才有意义
4. 运行时双跑对比（完整版vs压缩版）成本翻倍，违背Token管控目标
5. 国产模型caching支持需要按供应商/接口分别验证，不能假设全部支持

**改了之后好在哪：**
- 不会被评委抓住"5%怎么测的"——质量评估是实验目标，不是验收承诺
- B-4不会因模型不支持caching而变成废模块——降级为稳定前缀策略仍有价值
- 压缩目标分场景，短上下文不强压，长上下文有明确目标
- 压缩策略和risk_level打通，高风险任务自动保守压缩
- 成本模型第二层按模型实际caching能力启用，`unknown`按保守处理
- 三层质量保障（离线→运行时→反馈）比双跑对比更现实

---

### #33 Web平台：从6页并列改为P0/P1/P2/P3四级分级+执行顺序

**原来：**
6个页面并列，每个都做完整交互：
- 路由工作台（完整交互）
- 消费看板（完整交互）
- 优化中心（一键应用+效果追踪）
- 规则管理（在线编辑+版本历史+变更日志）
- Benchmark结果（热力图+对比表）
- Context Rot研究（5模型退化曲线+蠢笨区+干扰物）

D17-18两天做完所有页面。

**改为：**

四级分级：
| 优先级 | 页面 | 实现程度 |
|--------|------|----------|
| P0 | 路由工作台/消费看板/Benchmark | 完整交互/展示 |
| P1 | 优化中心 | 展示为主+轻交互（导出报告+生成草案） |
| P2 | 规则管理 | 只读展示（5个Tab，不做在线编辑） |
| P3 | 上下文工程验证 | 静态图表 |

关键边界：
- 优化中心不做一键应用/效果追踪/A/B测试/灰度回滚
- 规则管理不做在线编辑，只展示配置体系
- 执行顺序：D17消费看板→优化中心→路由工作台，D18规则管理→Benchmark→上下文工程验证

**为什么改：**
1. 6页并列在D17-18两天做不完，每页不到半天必然粗糙
2. 优化中心"一键应用"危险——涉及修改生产配置+追踪效果，MVP不该做
3. 规则管理在线编辑YAML在Streamlit中别扭且demo易出错
4. 优化中心承载浪费模式检测（评分项"可观测性10%"的核心载体），不应降为低优先级
5. 路由工作台依赖route接口，如果引擎有bug会卡页面开发，不应第一个做

**改了之后好在哪：**
- P0页面有充足时间做精（2天做3个核心页面）
- 优化中心从"简化页"提升为P1，保留浪费检测+节省金额+建议列表的业务冲击力
- 配置变更草案比一键应用更安全："系统生成草案，管理员审批后合并"符合企业变更管理
- D17先做确定性高的页面（消费看板依赖种子数据，已就绪），推迟风险页面（路由工作台）
- 规则管理虽只读但5个Tab展示"配置治理能力"，证明系统可配置

---

### #34 数据存储：从产品化Schema改为YAML配置+4张运行表+控制面/数据面分离

**原来：**
完整产品化数据库Schema，8张表：
- models（模型注册表）
- task_classifications（任务分类配置）
- routing_rules（路由规则）
- routing_decisions（路由决策记录，17字段）
- usage_records（Token消费记录）
- benchmark_cases（测试用例）
- benchmark_results（评测结果）
- optimization_suggestions（优化建议）

所有配置和运行数据都通过SQLAlchemy ORM管理。

**改为：**

控制面与数据面分离：

| 类型 | 存储方式 | 内容 |
|------|----------|------|
| 配置输入 | YAML | models.yaml / routing_rules.yaml / budgets.yaml / quality_defaults.yaml / compression_policy.yaml |
| 静态测试集 | JSON | benchmark_cases/*.json |
| 运行记录 | SQLite | routing_decisions / execution_feedback / benchmark_results / config_snapshots |
| 分析结果 | 运行时生成 | 浪费模式检测 / 优化建议 / 配置变更草案 |

数据库从8张表缩减到4张：
- routing_decisions：存**预估值**，常查字段单独列+复杂信息JSON存储
- execution_feedback：存**实际执行值**，新增actual_calls_json支持Plan-Execute成本拆解
- benchmark_results：新增suite_version/case_version，raw_output存文件路径不进DB
- config_snapshots：记录每次决策时的完整配置快照（merged_config_json），支持历史审计

**为什么改：**
1. 模型定价、路由规则在开发期频繁修改，YAML比数据库更方便修改+Git版本控制
2. 路由引擎是核心路径，不应依赖数据库——DB挂了路由仍应能工作
3. usage_records和routing_decisions字段大量重复，MVP数据量几千条不需要单独事实表
4. optimization_suggestions是浪费检测器按需计算的结果，不需要持久化
5. 消费看板需要区分"预估值"和"实际值"，原来routing_decisions没有明确区分
6. 配置快照可以回答"这个决策当时是基于什么规则做的"，审计说服力强

**改了之后好在哪：**
- 路由引擎不依赖数据库，控制面与数据面分离，架构更清晰
- 配置文件可Git管理变更历史，开发调试改YAML比重启DB方便
- 消费看板用COALESCE(actual, estimated)确保有真实数据用真实、没有用预估
- config_snapshots让审计可追溯——答辩时可以展示"当时的配置是XX版本，规则是XX"
- Plan-Execute的actual_calls_json支持策略级成本拆解
- 减少了一半的表（8→4），MVP实现量大幅降低
- 明确写出usage_records的扩展条件，不会被问"真实生产数据怎么接入"时没后路

---

### #35 四周计划：从理想化排期改为"核心链路优先+每周检查点+降级预案"

**原来：**
- Week 1：纯调研+设计文档，无可运行产出
- Week 2：完整引擎+上下文工程+CLI+测试+种子数据（严重超载）
- Week 3：FastAPI+Streamlit+Benchmark+Context Rot+Docker（不可控）
- Week 4：手册+SOP+答辩（紧凑）
- `ai-router audit`未排入计划
- 上下文工程全部堆Week 2
- Benchmark笼统写"30-50条"

**改为：**

6条执行原则：
1. 核心链路优先——路由引擎+CLI在Week 2结束前必须跑通
2. 每周末有可演示检查点
3. 上下文工程拆两周（W2做B-1/B-2，W3做B-3+验证）
4. Benchmark分级落地（L1在W2，L2在W2末启动，L3在W3）
5. Week 4不新增功能
6. audit是后端能力——Week 2 CLI先跑通，Week 3 Web复用

关键排期调整：
- Week 1每天细化到具体模块（D3数据模型→D4分类器→D5选择器→D6骨架→D7规则版analyze）
- Week 2：D8硬约束+Adapter→D9策略生成→D10 audit→D11 B-1优先级框架→D12 B-2压缩引擎（含规则摘要化）→D13 optimize→D14 benchmark L1+DB+启动L2
- Week 3：D15 API+检查L2补跑→D16 L2报告+P0/P1页面→D17 P0/P2→D18 P3+页面收尾→D19 L3回测+ContextRot→D20 B-3预算管理→D21 Docker+预录
- Week 4：D22设计文档→D23手册→D24 SOP→D25报告+缓冲→D26 PPT→D27彩排→D28答辩

关键设计决策：
- B-2规则摘要化（Rule-based Summarization）在Week 2实现，不调LLM做摘要，基于5种上下文类型的结构化规则
- Level 2 Benchmark支持`--resume`断点续跑，D14后台启动，D15检查补跑，D16生成报告
- B-3预算管理放D20（基于L2实测数据+ContextRot观察定规则，不拍脑袋）

Week 2降级预案：
- 摘要化简化为规则版（保留首尾+关键行），真LLM摘要推Week 3
- SQLite先写routing_decisions+config_snapshots，其余Week 3补
- Plan-Execute先支持成本预估，不真实执行多模型调用

**为什么改：**
1. 原Week 2把引擎+上下文工程+CLI+测试全塞一周，任何一环delay就崩盘
2. `ai-router audit`原来没排入，但审计是"管控"故事的核心
3. 上下文工程全部堆Week 2导致路由引擎开发被挤压
4. Benchmark不分级导致Week 3同时跑API+做Web+跑实验，风险极高
5. Level 2需要D14启动而非D16，给API限流/故障留2天buffer

**改了之后好在哪：**
- Week 1就有可演示的规则版CLI，可验证分类体系和模型矩阵
- audit在Week 2完成，"企业管控"故事W2末就能讲
- 上下文工程分两周+降级预案，不会挤爆Week 2
- Level 2 D14启动→D15收结果，比D16启动多2天buffer
- Context Rot D18和Level 3 D19分开，不挤同一天
- Week 4 D25作为缓冲日，吸收Week 3溢出
- 每周检查点确保"delay了至少能演示当前进度"

---

### #36-#52 定稿前一致性修复（批量）

本轮修复解决文档内部不一致、隐性工作量过大、指标口径不统一等问题。

**#36 评分体系改回6维度**
- 原来：自定义8维度（12/15/15/12/12/10/12/12），含"上下文工程能力""可观测性建设"等独立维度
- 改为：原任务的6维度（架构15%/路由引擎20%/工程实现20%/数据驱动15%/文档SOP 15%/答辩15%），上下文工程和可观测性归入对应维度
- 原因：答辩时评委按原评分表打分，自定义维度与任务书不一致

**#37 Benchmark调用量修正**
- 原来：总预算~242次
- 改为：~152次（0+115+0+27+10=152）
- 原因：242次无法解释多出的90次来源，属于数学错误

**#38 Benchmark交付物歧义修正**
- 原来："6类×20+用例"
- 改为：明确区分离线规则测试集≥100条、静态测试用例库6类、真实模型实测子集30条、回测报告
- 原因：避免误解为"120条全部跑真实模型"

**#39 D14工作量拆分**
- 原来：D14一天要完成benchmark L1 + SQLite四张表 + 种子数据6000条 + 启动Level 2
- 改为：DB schema提前到D8，种子数据提前到D10（audit本身就需要模拟数据），D14只做L1测试+启动L2
- 原因：D14原来承载4件大事，风险过高

**#40 FastAPI降级方案**
- 新增：若FastAPI接口开发延期，Streamlit可直接调用engine/service层
- 原因：前后端分离增加工程复杂度，MVP首要目标是演示链路通畅

**#41 架构图补config_snapshots**
- 原来：架构图只写了`routing_decisions | feedback | benchmark_results`
- 改为：`routing_decisions | execution_feedback | benchmark_results | config_snapshots`
- 原因：与第十章4张表的描述不一致

**#42 预算过滤soft/hard两层**
- 原来：`if cost > budget_limit: continue`（单层，直接排除）
- 改为：`hard_budget_limit`超限排除，`soft_budget_limit`超限标记WARNING但保留候选
- 原因：单层过滤会误杀"超预算但可审批保留"的强模型方案

**#43 Plan-Execute上下文重叠修正**
- 原来：`executor_input = input_tokens * 0.35 + planner_output/n + 300`，子任务多时总读取量超过全局上下文
- 改为：新增`overlap_factor=0.7`和硬上限`input_tokens * 0.9`，防止重复读取
- 原因：5个子任务时0.35×5=1.75倍全局上下文，逻辑不成立

**#44 capability_score preferred_coverage修复**
- 原来：返回`0.85 * required_coverage + 0.15 * preferred_coverage`但`preferred_coverage`未计算
- 改为：补充`preferred_coverage = len(matched_preferred) / len(preferred) if preferred else 0.0`
- 原因：伪代码变量未定义，实现时会报错

**#45 LLM模式延迟承诺修正**
- 原来：`延迟<500ms`
- 改为：`MVP不承诺固定延迟，实际延迟取决于模型API响应速度`
- 原因：Tier 1模型base_ms就是1500ms，与<500ms矛盾

**#46 "路由不依赖LLM"澄清**
- 原来：`路由决策不依赖 LLM 判断`
- 改为：`路由策略选择和评分不依赖 LLM 判断。LLM 仅作为可选的任务特征提取器；即使LLM不可用，系统仍可通过关键词/规则模式完成特征提取和路由决策`
- 原因：原文与TaskAnalyzer的LLM模式存在表述矛盾

**#47 成本降低承诺修正**
- 原来：`成本降低40-60%`（无条件承诺）
- 改为：`目标在可拆解、可验证的复杂任务中观察到20-60%成本下降（具体取决于任务可拆解性和上下文局部化比例）`
- 原因：Plan-Execute示例中节省只有23.7%，40-60%过于乐观

**#48 Prompt Caching参数标注**
- 原来：模型缓存参数直接写死
- 改为：所有参数标注"待Week 1实测确认"，并注明"模型名称与价格以models.yaml的实际可调用配置为准，表中名称为MVP角色占位"
- 原因：企业内部API/网关转发层的实际行为可能不同于公开文档

**#49 测试覆盖率限定范围**
- 原来：`测试覆盖率≥80%`（全项目）
- 改为：`核心模块（analyzer/selector/estimator/constraints/audit detector）测试覆盖率≥80%`
- 原因：Streamlit页面、脚本、实验代码都纳入覆盖率不现实

**#50 MVP最小成功标准**
- 新增：7条MVP成功标准（4个CLI可运行、20条任务可路由、4个P0/P1页面可展示、L2完成80%、回测有对比、Docker可启动、离线备份可用）
- 原因：防止任务膨胀，明确"做到什么程度算完"

**#51 P0优先级说明**
- 新增：在页面优先级表下注明"P0是答辩展示优先级，不等于开发顺序"
- 原因：Benchmark是P0但因依赖数据排在D17，不说明会引发疑问

**#52 D21/D27预录视频口径统一**
- D21：预录**第一版系统演示**备份视频（防止Week 4系统临时故障）
- D27：录制**最终答辩版**视频+现场演示彩排
- 原因：两处都写"预录视频"容易被认为是重复工作

**#53 4.4.1重复旧代码删除**
- 原来：4.2.1和4.4.1各有一版capability_score伪代码，4.4.1版本未计算preferred_coverage且变量名不一致
- 改为：4.4.1删除重复伪代码，改为引用4.2.1实现，仅说明能力匹配度在多目标评分中的角色
- 原因：两处代码不一致，实现时容易混淆

**#54 三种归一化全部Week 2实现**
- 原来："MVP阶段代码先实现linear，配置文件支持切换"
- 改为：三种归一化（linear/sqrt/log）代码量极小（约10行），Week 2全部实现
- 原因：答辩时演示同一任务切换cost_sensitivity后路由结果变化，展示效果强

**#55 hard_budget_limit改为标记需审批**
- 原来：`if cost > hard_budget_limit: continue`（直接排除）
- 改为：`model.budget_status = "OVER_HARD_BUDGET"; model.requires_approval = True`（保留为候选但标记需审批）
- 同时：人工审核触发规则新增条件#3"选中模型budget_status == OVER_HARD_BUDGET"
- 原因：如果高风险任务唯一的Tier 1候选超硬预算，直接排除会丢失"可用但需审批"选项，变成"无候选→人工兜底"

---

### #56-#58 Week 1 检查点后管控门禁重构

Week 1 检查点通过（CLI 能跑、111 tests pass），但发现 4 个设计缺陷。根因不是"功能没做完"，而是 **Selector（评分推荐）和 Gate（管控门禁）的职责没有分离**。

**#56 Selector/Gate 职责分离**
- 原来：`router.py` 内部有 `_check_human_review()` 和 `_build_quality_gate()` 两个方法，各自独立从 features 推导，互相不知道对方结论。`quality_gate` 里有 `human_review`，但 `requires_human_review` 可以为 false。
- 改为：创建独立的 `gate.py` 模块（`RoutingGate` 类），作为 `requires_human_review` 和 `quality_gate` 的**唯一决定者**。`router.py` 移除内部门禁方法，改为调用 Gate。
- 新增 `GateInput` dataclass：明确定义 Gate 需要的所有输入（features、model_tier、strategy、cost、quality_loss、budget_status、forced_review_task）。
- 关键联动：`build_quality_gate(features, requires_human_review)` — 如果 `requires_human_review=true`，`human_review` 必须在 `quality_gate` 中。
- 原因：企业管控的核心原则是"Selector 可以推荐性价比最优，Gate 必须决定能否自动执行"。原来 Selector 做到了前半句，Gate 只做了一部分。
- 改了之后好在哪：
  - `requires_human_review` 和 `quality_gate` 不再矛盾
  - Gate 可独立测试（`test_gate.py` 21 条政策测试）
  - 后续 Week 2 加策略候选（PLAN_EXECUTE 等）时，Gate 逻辑可复用

**#57 预算过滤从"后置单次检查"改为"候选级标签"**
- 原来：预算只在 `router.py` 的 `_check_budget()` 中检查一次，只针对最终选中的模型。Selector 不知道预算信息，替代方案列表也不带预算状态。
- 改为：
  - `selector.py` 的 `CandidateScore` 新增 `budget_status` 和 `requires_approval` 字段
  - `score_models()` 中为每个候选计算预算状态（`_compute_budget_status`）
  - Router 的 `budget_status` 直接来自 `best.budget_status`（Selector 产出）
  - 替代方案列表中展示预算状态（如"超硬预算，需审批"）
- 预算计算：`soft_budget = min(task_budget_default, max_cost_cny)`，`hard_budget = soft_budget × multiplier`
- 新增 `BudgetStatus.OVER_HARD_BUDGET` 枚举值
- 原因：Week 2 做 audit/optimize 时，如果预算不是候选级 metadata，后面很难解释"为什么推荐这个而不是那个"。
- 改了之后好在哪：
  - 每个候选方案都有预算标签，替代方案可对比
  - 审计时可追溯："当时 Tier 1 方案超硬预算，所以推荐了 Tier 2"

**#58 测试策略从"通路验证"补充"政策验证"**
- 原来：111 tests 主要证明 CLI 能输出、schemas 能序列化、router 能返回完整对象。`test_router_high_risk_requires_review` 用的是 ARCHITECTURE 任务，靠 `human_review_required_tasks` 配置通过，完全没测到"高风险 + Tier 2 降级"这个真正危险的 case。
- 改为：新增 25 条政策验证测试：
  - `test_gate.py`（21 条）：逐条测试 Gate 的 7 个条件（敏感数据、高风险降级、硬预算、软预算、质量损失、强制审核）+ 质量门禁构建 + 一致性检查
  - `test_router.py`（4 条）：端到端政策测试（高风险+Tier 2、质量损失阈值、Gate/quality_gate 一致性、高风险+Tier 1 不误触发）
- 关键测试：`test_policy_high_risk_tier2_must_review` — 直接覆盖 Week 1 最大 bug case
- 原因：通路测试证明"能跑"，政策测试证明"管控规则正确"。企业级系统需要后者。

---

### #59-#62 quality_loss 语义修正与不对称 baseline

Week 1 第二轮审查发现 quality_loss 公式错误，并确立了 cost/quality baseline 不对称的设计原则。

**#59 quality_loss 从固定 0.90 改为候选集最高质量**
- 原来：`quality_loss = max(0, 0.90 - quality)`，0.90 是拍脑袋的"理想质量基准"
- 改为：`baseline_quality = max(scored_candidates.quality)`，`quality_loss = max(0, baseline_quality - selected_quality)`
- 原因：0.90 不是真实 baseline。SIMPLE 任务只允许 Tier 3（质量 ≈ 0.44），用 0.90 做基准会算出 46% 的质量损失，触发 Gate 误杀省钱路径。正确语义是"在系统允许的候选范围内，质量牺牲了多少"。
- 改了之后好在哪：
  - SIMPLE/LOW/Tier3：baseline = Tier3，quality_loss ≈ 0，不触发审核
  - COMPLEX+HIGH/Tier2：baseline = Tier1（在候选中），quality_loss = 0.132，真实反映降级差距
  - EXPERT/Tier1：baseline = Tier1，quality_loss = 0，不误报

**#60 soft budget 不再触发人工审核**
- 原来：Gate 条件 4 把 `OVER_BUDGET`（soft）加入人工审核原因
- 改为：`OVER_BUDGET` 只标记 warning 状态，不触发 `requires_human_review`。只有 `OVER_HARD_BUDGET` 触发审核。
- 原因：设计文档原话是"超过软预算**且用户选择保持强模型方案**"才触发。MVP 无用户交互，不应替用户默认选择"保持强模型"。soft limit 语义是"提醒、引导、记录"，不是"卡死"。
- 改了之后好在哪：演示更顺滑，不会让略超软预算的任务直接需要审批

**#61 quality_loss 审核加 risk_level != LOW 前置条件**
- 原来：`quality_loss > 0.20` 无条件触发审核
- 改为：`risk_level != LOW and quality_loss > 0.20` 才触发
- 原因：复杂度管"做起来难不难"，风险管"错了痛不痛"。Gate 是管控层，应该看风险。LOW risk 的 SIMPLE/LOW/Tier3 省钱路径不应被 Gate 锁死。
- 改了之后好在哪：避免系统变成"复杂就审批、简单就放行"的粗糙规则

**#62 cost baseline 和 quality baseline 故意不对称**
- 原来：未明确区分，容易被误解为"不一致"
- 改为：明确记录两种 baseline 的设计意图：
  - `cost baseline = Tier 1 最贵模型成本` → 回答"相对全程强模型，省了多少钱？"（演示/商业口径）
  - `quality baseline = 候选集最高质量` → 回答"在可选范围内，质量牺牲了多少？"（管控/风险口径）
- 原因：两个问题本来就不是同一个问题。如果统一用 Tier 1 做 baseline，SIMPLE 任务会被误报 quality_loss（Tier 1 不在可选范围内）。如果统一用候选集，cost savings 永远是 0（没有对比）。
- 改了之后好在哪：未来维护者不会试图"统一 baseline 让代码更干净"而破坏语义。详见 `pitfalls.md` 坑 7。

**#63 StrategyClassifier 与 Selector 职责分离**
- 原来：设计文档将"触发条件判断"和"候选生成"放在一起，成本/质量阈值写在触发条件里（条件6/7）
- 改为：独立 `StrategyClassifier` 模块只做结构条件判断（5 个 Plan-Execute 条件、4 个 Guided 条件、PER = base_decomposable AND review_need），成本节省率和质量损失率下沉到 Selector 的 post-filter 阶段
- 原因：结构条件是"这个任务有没有资格用这个策略"，成本/质量是"这个策略组合值不值得用"。分离后 Classifier 可以独立测试，不需要 mock estimator
- 改了之后好在哪：Classifier 34 个测试全确定性，不依赖模型成本数据。Selector post-filter 用 Tier 1 baseline 做统一口径

**#64 角色级能力过滤（executor 不要求 architecture）**
- 原来：所有角色（planner/executor/reviewer）共用同一套任务级能力过滤
- 改为：executor 使用 `EXECUTOR_CAPABILITY_REQUIREMENTS`（按 TaskCategory 映射，如 CODE_GENERATION 只要求 code_gen），planner/reviewer/single 继续用全局 `_capability_score()`
- 原因：ARCHITECTURE 类任务要求 `architecture` 能力，但 executor 只负责执行代码片段，不需要架构能力。共用全局过滤会误杀 Tier 2/3 executor
- 改了之后好在哪：ARCHITECTURE + EXPERT + HIGH risk 的 PER 策略能正确生成 raw 候选（角色级能力过滤不再误杀）；最终是否推荐仍取决于 post-filter 的成本/质量门槛

**#65 Top-K 在角色池内执行，遍历组合替代 max()**
- 原来：策略候选生成用 `max()` 取每个角色池的最优模型，只生成一个组合
- 改为：在每个角色池内做 `select_top_k_per_tier()`，然后遍历 planner × executor × reviewer 所有 Top-K 组合
- 原因：单模型最优不等于组合最优。planner 能力最强的 + executor 成本最低的 可能比 两者都中等的 总评分更高
- 改了之后好在哪：候选集更丰富，post-filter 有更多选择余地

**#66 AlternativeStrategy schema 支持多角色**
- 原来：`AlternativeStrategy` 只有 `model: Optional[str]` 字段
- 改为：`planner`, `executor`, `reviewer` 三个 Optional[str] 字段
- 原因：PER/PE/GE 策略有多个角色模型，单字段无法表达
- 改了之后好在哪：CLI 和 Web 可以展示"规划: qwen-max, 执行: qwen-plus, 审查: qwen-max"

**#67 SQLite 外键强制 + ORM/Pydantic 命名对齐**
- 原来：SQLite 默认 `PRAGMA foreign_keys=OFF`，FK 声明只是 metadata；ORM 字段名与 Pydantic schema 有两处不一致（`latency_ms` vs `actual_latency_ms`，`models_hash` vs `models_config_hash`）
- 改为：`init_db()` 中加 `PRAGMA foreign_keys=ON`；FK 加 `ondelete="CASCADE"`；Pydantic 字段名向 DB schema 对齐（设计文档 §10 是真理来源）
- 原因：FK 不 enforce 等于形同虚设，`routing_decision_id=999` 可以写入；命名不一致在 audit/benchmark 阶段会需要特殊映射
- 改了之后好在哪：DB 级参照完整性 + ORM/Pydantic 一套命名，后续 audit Collector 和 benchmark runner 不需要 mapper

**#68 审计引擎：Collector/Aggregator/Detector/Attribution 四层架构**
- 原来：设计文档 §4.8 定义了审计引擎的 5 类浪费模式（P1-P5），但没有具体实现架构
- 改为：四层架构：
  - **Collector**：从 routing_decisions + execution_feedback 聚合消费记录，COALESCE(actual, estimated) 确保有真实数据用真实、没有用预估
  - **Aggregator**：多维分组（user/project/model/task_type/department/day/client_type），返回 CostBreakdown 列表
  - **Detector**：5 类浪费模式检测（P1 高配滥用/P2 重复调用/P3 过长上下文/P4 可降级未降级/P5 缓存机会未利用），每类有独立的严重度分级和节省估算
  - **Attribution**：消费归因分析（汇总+多维分解+重度用户识别+Top N 浪费模式）
- 关键设计：
  - P1 触发条件：SIMPLE 用 Tier 1，或 MODERATE 用 Tier 1 但 risk != HIGH
  - P2 时间窗口：10 分钟内相同 (user_id, project_id, task_hash)
  - P3 阈值：max(10000, task_type_median * 2)
  - P4 基于 routing_rules.allowed_tiers 推导最低可用 tier
  - P5 需要模型 supports_prompt_caching=true + input > cache_min_prefix_tokens
- 原因：企业级 Token 管控的核心是"谁花了多少钱、哪里浪费了、怎么省"
- 改了之后好在哪：CLI 和 Web 可以复用同一套审计逻辑，答辩时展示浪费模式检测+节省建议非常有说服力

**#69 种子数据：参数化 + 浪费模式注入**
- 原来：设计文档提到需要种子数据，但没有具体方案
- 改为：参数化生成器 `scripts/generate_seed_data.py`：
  - 支持 `--days N --rows-per-day N` 或 `--rows N` 两种模式
  - 固定随机种子 seed=42，确保可重复
  - 8 用户/4 部门/5 项目/5 客户端类型
  - 2 个重度用户（alice, bob）占 70% 消费，模拟真实分布
  - 注入全部 5 类浪费模式：P1 15%、P2 10%、P3 8%、P4 5%、P5 3%
  - 80% 记录有 execution_feedback（actual 与 estimated 偏差 10-20%）
- 验证：200 行种子数据 → 275 条总记录（含 feedback），P1 模式可检测到 9 条 SIMPLE + qwen3.7-max
- 原因：没有种子数据，audit CLI 无法演示；手工写数据太慢且容易遗漏浪费模式
- 改了之后好在哪：快速生成任意规模的测试数据，浪费模式注入确保 Detector 有东西可检测

**#70 CLI audit 命令（Rich 格式 + JSON 输出）**
- 原来：设计文档 §7.3 定义了 `ai-router audit` 命令，但没有具体参数和输出格式
- 改为：
  - 参数：`--days N`、`--user`、`--project`、`--department`、`--format rich/json`
  - Rich 输出 5 个区块：消费汇总、按用户消费（标记重度用户 ⚠️）、按模型消费（标记占比过高）、Top 5 浪费模式表格、优化建议面板
  - JSON 输出：完整 AuditSummary 序列化，支持程序化处理
- 原因：CLI 是 Week 2 检查点的必交付物，Rich 格式在答辩时视觉冲击力强
- 改了之后好在哪：`ai-router audit --days 30` 一键生成审计报告，JSON 模式支持 Web 看板复用

**#71 P4 可降级逻辑修正 + P5 缓存检测修正 + JSON 结构化输出**
- 原来：
  - P4 使用 `min(allowed_tiers)` 推导"最低可用 tier"，但 Tier 数字越大越便宜，`min()` 取到的是最贵的 tier
  - P5 使用 `getattr(m, "supports_prompt_caching", False)` 读取缓存支持，但 ModelEntry 的缓存配置在 `m.cache.supports_prompt_caching` 中
  - JSON 输出使用 `console.print(json.dumps(...))`，Rich 自动换行导致 JSON 字符串中插入换行符，破坏 JSON 结构
  - 种子数据重复运行会追加数据而非覆盖
  - audit CLI 空库时静默返回 0 而非提示用户
- 改为：
  - P4：`min(allowed_tiers)` → `max(allowed_tiers)`，变量名改为 `cheapest_tier`，注释明确"Tier 数字越大越便宜"
  - P5：`getattr(m, "supports_prompt_caching", False)` → `m.cache.supports_prompt_caching is True`
  - JSON 输出：`console.print()` → `print()`，避免 Rich 自动换行
  - 种子数据：默认清空 DB，新增 `--append` 参数显式追加
  - audit CLI：空库时输出警告并退出（exit code 1），新增 `--db` 参数指定数据库路径
  - P5 种子注入：强制使用支持 caching 的模型（qwen3.7-max/qwen3.7-plus/deepseek-v4-flash），确保 input_tokens > 1024
- 原因：Review 发现 P4 语义反了（应该用 max 而非 min），P5 读取路径错误导致永远检测不到缓存机会，JSON 输出不是结构化数据
- 改了之后好在哪：
  - P4 正确检测"Tier 1 本可降到 Tier 3"的浪费（MODERATE+LOW 场景）
  - P5 正确检测所有支持 caching 的模型的缓存机会
  - JSON 输出可被 `json.loads()` 正确解析，支持程序化处理
  - 种子数据可重复运行，默认覆盖避免数据累积
  - 空库有明确提示，`--db` 参数支持指定不同数据库

**#72 种子数据从 load_models() 派生 + P2/P5 时间戳有界 + 集成测试自包含**
- 原来：
  - `generate_seed_data.py` 硬编码 `MODEL_PRICING` 字典（价格偏离真实配置 5 倍，glm-5.1 tier 错误）
  - `select_model()` 硬编码 Tier 1/2/3 模型名，`cache_models` 硬编码支持 caching 的模型列表
  - P2 注入 `timedelta(minutes=1-9)` 和 P5 注入 `timedelta(hours=2-24)` 都可能产生未来时间戳
  - `test_cli.py` 的 audit 测试直接读本地 `seed.db`（被 .gitignore 排除），CI 上必然失败
  - Rich 汇总"实际值占比"后面跟的是 token 总量，语义不匹配
- 改为：
  - 删除 `MODEL_PRICING` 硬编码，新增 `@lru_cache` 的 `_get_model_catalog()`、`_get_tier_pools()`、`_get_cache_model_names()`
  - `estimate_cost()` 从 `_get_model_catalog()` 读取定价
  - `select_model()` 从 `_get_tier_pools()` 读取 tier 池
  - P5 注入从 `_get_cache_model_names()` 读取支持 caching 的模型
  - P2 和 P5 注入都加了 bounded delta：`max_minutes = min(9, int(remaining // 60))`，`max_hours = min(24, int(remaining // 3600))`
  - `test_cli.py` 新增 `seed_db_url` fixture：用 `tmp_path_factory` 创建临时 DB + 调用 `generate_seed_data()` 造数据
  - Rich 文案"实际值占比"改为"Token 总量"
- 原因：硬编码价格和 tier 与 `models.yaml` 脱节导致审计金额偏差 5 倍；P2/P5 生成未来时间戳导致 Collector 过滤后记录数不一致；集成测试依赖本地 gitignored 文件
- 改了之后好在哪：
  - `models.yaml` 修改后种子数据自动同步（价格、tier、cache 支持）
  - 276 条写入 = 276 条采集，无未来记录
  - 集成测试在任何环境可运行（CI、干净 checkout）

**#73 种子数据 execution_feedback.created_at 有界化**
- 原来：`generate_seed_data.py` 第 315 行给 `execution_feedback.created_at` 加 `timedelta(seconds=rng.randint(10, 300))`，当 routing decision 时间戳接近 `now` 时，feedback 会进入未来
- 改为：`created_at=min(rec["timestamp"] + timedelta(seconds=rng.randint(10, 300)), now - timedelta(seconds=1))`
- 原因：虽然 audit 按 `routing_decisions.created_at` 过滤（不影响总调用数），但种子数据里有"未来反馈"是数据一致性瑕疵
- 改了之后好在哪：`routing_decisions` 和 `execution_feedback` 两张表都零未来记录，种子数据时间完全一致

**#74 B-1 优先级框架 + B-2 压缩引擎**
- 原来：Phase 5 未实现，上下文工程模块为空
- 改为：
  - `priority.py`：`PriorityAssembler` 实现 6 层优先级（System Prompt > 任务描述 > 相关文件 > 历史对话 > 工具输出 > 辅助信息），保护层不可淘汰，非保护层超预算从最低优先级开始淘汰
  - `compressor.py`：`Compressor` 实现 3 种压缩策略（冗余剔除 + 工具输出截断 + 规则摘要化），6 种 `ContentType` 各有独立摘要规则，策略由 `risk_level` 定上限、`context_length` 定是否触发
  - 新增 `ContextBlock`、`InputBreakdown`、`CompressionResult` 三个 Pydantic schema
  - 新增 `ContextLayer`、`ContentType`、`CompressionStrategy` 三个枚举
- 原因：设计文档 4.6 节定义了上下文工程 B-1/B-2 的能力，需要为 `ai-router optimize` CLI 和 Week 3 B-3 预算管理提供底层支撑
- 改了之后好在哪：
  - 上下文可按优先级和预算自动组装/淘汰
  - 3 种压缩策略（Conservative/Standard/Aggressive）与 risk_level 绑定，高风险任务自动保守压缩
  - 57 个单元测试覆盖核心逻辑

**#75 ContextBlock 自动 protected + strategy 大小写归一化 + NONE 仍做冗余剔除**
- 原来：`ContextBlock.protected` 需要调用方手动传 `True`；`NONE` 策略跳过所有处理（含冗余剔除）；YAML 配置里 strategy 用小写（`"conservative"`），枚举用大写（`CONSERVATIVE`），可能不匹配
- 改为：
  - `ContextBlock` 用 `model_validator(mode="after")` 自动设置 `protected=True`（`SYSTEM_PROMPT` 和 `TASK_DESCRIPTION`）和 `token_count`
  - `NONE` 策略仍执行冗余剔除，只跳过摘要/截断（对应配置里 `<5K` 的"仅做明显冗余剔除"）
  - `select_strategy()` 内部做 `.upper()` 归一化
  - `estimate_tokens()` 用 `max(1, ceil(len/3))`，非空文本至少 1 token
  - `CompressionResult` 新增 `applied_actions`、`dropped_blocks`、`warnings` 解释字段
  - `PLAIN_TEXT` 处理规则：只去连续空行，不做摘要
- 原因：Review 发现 4 个 P2 问题（token 估算 0、NONE 跳过冗余、protected 手动传、大小写不匹配）+ 2 个 P3（缺解释字段、PLAIN_TEXT 未定义）
- 改了之后好在哪：
  - 调用方无需关心 protected 和 token_count，减少出错
  - 冗余剔除在所有策略级别生效
  - `optimize` CLI 可以直接读 `applied_actions` 展示优化建议

**#76 Review 修复：AssemblyResult + NONE 预算裁剪 + 对话摘要语义**
- 原来：
  - `PriorityAssembler.assemble()` 返回 `list[ContextBlock]`，淘汰的 dropped 被丢弃
  - `Compressor.compress(NONE + total_budget)` 直接 return，跳过 PriorityAssembler
  - 对话摘要关键词 `"TODO"` 大写，但 `line.lower()` 后匹配不到
  - AGGRESSIVE 对话摘要注释说"只保留关键词句"但实现仍保留首末行
  - 计划/文档说"hash + Jaccard"冗余剔除，实现只有 hash
- 改为：
  - 新增 `AssemblyResult` dataclass（`retained`、`dropped`、`actions`），`assemble()` 返回 `AssemblyResult`
  - `NONE` 策略不再 early return，fall through 到 PriorityAssembler 执行预算裁剪
  - `Compressor` 收集 `assembly_result.dropped` 和 `.actions` 到 `CompressionResult`
  - 对话关键词全部小写（`"TODO"` → `"todo"`）
  - AGGRESSIVE 对话摘要不再保留首末行，只保留关键词句
  - 冗余剔除降级为"仅 hash 精确去重"（不实现 Jaccard）
- 原因：Review 发现 1 个 P1（lint）+ 3 个 P2（NONE 预算裁剪、dropped 丢失、Jaccard 未实现）+ 1 个 P3（对话摘要语义不一致）
- 改了之后好在哪：
  - `total_budget` 参数在所有策略级别生效（NONE 也能裁剪到预算内）
  - `optimize` CLI 可以完整展示"删了什么、为什么删"（含预算裁剪）
  - 对话摘要行为与注释一致，关键词匹配不受大小写影响

**#77 Phase 7续：`ai-router optimize` CLI — Prompt/上下文优化建议**
- 新增 `PromptOptimizer` 引擎（`src/airouter/engine/optimize/optimizer.py`）
- 新增 `OptimizationSuggestion` 和 `OptimizeResult` Pydantic schema
- 新增 `ai-router optimize` CLI 命令（`src/airouter/cli/optimize.py`），支持 `--prompt`、`--context-file`、`--model`、`--scenario`、`--turns`
- 5 类优化建议：缓存、压缩（3 策略对比）、降级、裁剪、Plan-Execute
- `Compressor.compress()` 新增 `strategy_override` 参数，支持强制指定压缩策略
- 原因：设计文档 7.3 节定义了 optimize CLI，development-plan D13 要求实现
- 改了之后好在哪：
  - 用户可以拿到 prompt 级的成本优化建议（5 类独立估算）
  - 压缩建议真正调用 Phase 5 的 Compressor，展示 3 策略对比
  - 降级/Plan-Execute 建议用真实 prompt token 重新计算成本（不依赖 Router 粗映射）
  - `warnings` 字段明确标注"理论估算、各优化可能重叠"
- 关键设计决定：
  - 真实 prompt token 做基准（覆盖 `features.estimated_input_tokens`）
  - `_classify_prompt_lines()` 统一行分类，breakdown 和 ContextBlock 共用
  - `dynamic_query → TASK_DESCRIPTION`（protected，不会被裁掉）
  - Token 对齐：`dynamic = max(0, global_total - accounted)`
  - 降级/Plan-Execute 复用 `Selector._filter_base()` 过滤（context window + sensitivity）
  - 综合节省 `min(current_cost, sum(...))`，标注为"理论最大节省"

**#78 Compressor strategy_override 参数**
- 原来：`Compressor.compress()` 只能通过 `risk_level + context_length` 自动选策略，无法强制指定
- 改为：新增 `strategy_override: CompressionStrategy | None = None` 参数，非 None 时覆盖自动选择
- 原因：`optimize` CLI 需要展示 3 策略对比（CONSERVATIVE/STANDARD/AGGRESSIVE），必须能强制指定策略
- 改了之后好在哪：CLI 可以展示每种策略的压缩效果，用户可以选择更激进或更保守的策略

**#79 Review 修复：治理语义约束（降级/分层过滤、escalate 检测、互斥节省）**
- 原来：
  - `_suggest_downgrade()` 和 `_suggest_plan_execute()` 用 `Selector._filter_base()`（仅 context window + sensitivity），跳过 allowed_tiers 和 capabilities
  - EXPERT+HIGH 任务（routing_rules 只允许 Tier 1）被建议降到 Tier 2
  - Plan-Execute 建议只检查 `features.subtasks` 非空，1 个 subtask 也建议分层（开销不划算）
  - Router escalate（无候选策略）时 optimize 静默输出 cost=0，不提示用户
  - 无效 `--model nonexistent` exit 0 + cost=0，误导用户
  - "综合优化后成本" 对所有建议求和，降级+分层互斥导致严重高估
- 改为：
  - 降级/分层建议改用 `Selector.filter_candidates()` 做完整硬约束过滤（capabilities + allowed_tiers + context window + sensitivity）
  - Plan-Execute 要求 `len(subtasks) >= 2`
  - Router escalate（requires_human_review + 空 models）→ warnings 首条提示"需要人工审核"
  - CLI 入口校验模型名，不存在就 Exit(1) + 列出可用模型
  - 正交建议（缓存/压缩/裁剪）可叠加，互斥建议（降级/分层）取 max
  - 输出标签改为"独立建议合计"+"参考优化成本"
- 原因：Review 发现 2 个 P1（治理语义 bug）+ 3 个 P2（UX 误导）
- 改了之后好在哪：
  - optimize 建议不再绕过路由治理规则（allowed_tiers、capabilities）
  - 高风险任务不会被错误建议降级到不允许的 Tier
  - Router escalate 时用户能看到原因，不会误以为"成本为 0 所以不需要优化"
  - 节省金额不再严重高估（互斥取 max，不叠加）
  - 新增 5 个测试覆盖这些修复

**#80 Review 二轮修复：Gate 审批语义全量消费 + Engine 层校验 + CLI 硬校验**
- 原来：
  - escalate 检测只在 `requires_human_review AND 空 models` 时 warning，高风险但有候选模型时降级/分层建议没有审批提示
  - `PromptOptimizer.optimize(model_name="nonexistent")` 静默返回 cost=0，CLI 挡住了但 Engine 层没防护
  - CLI `--scenario BAD` / `--format yaml` / `--turns -5` 不报错，静默忽略或产生误导性输出
  - 互斥 savings 测试的 `if len(exclusive_items) >= 2:` 分支从未真正执行（prompt 只产生 1 个互斥建议）
- 改为：
  - escalate 检测改为所有 `requires_human_review=True` 都 warning；降级/分层 suggestion.details 标 `requires_approval=True`
  - Engine 层 `optimize()` 校验 model_name 存在性，不存在 raise ValueError（CLI 仍保留前置校验作为 defense-in-depth）
  - CLI `scenario` 和 `output_format` 改为 `Literal[...]` 类型（Typer 自动拒绝非法值），`turns` 加 `turns < 1` 手动校验
  - 互斥 savings 测试改为手工设 savings 值 + 验证数学，不依赖 prompt 触发
- 原因：Review 二轮发现 1 个 P1（Gate 语义漏洞）+ 1 个 P2（Engine 层防护）+ 2 个 P3（输入校验 + 测试覆盖率）
- 改了之后好在哪：
  - 高风险任务的降级/分层建议明确标注"需审批"，不会被误当成"可直接执行"
  - Web/API 直接调用 Engine 时也能拦住无效模型名
  - CLI 参数非法时用户立即得到清晰错误，不会得到误导性优化结果
  - 互斥 savings 测试不再依赖 prompt 触发（确定性验证）

**#81 Review 三轮修复：requires_approval 按建议后方案重新判断 + 汇总抽取 + Engine 参数校验**
- 原来：
  - `requires_approval` 继承 Router 原始 `decision.requires_human_review`，不基于建议后的方案重新判断。Router 推荐 Tier 1（不需要审批）时，降级到 Tier 2 的建议也标 `requires_approval=False`，但 HIGH risk + Tier 2 按 Gate 条件 2 应该需要审批
  - Engine 层仍接受非法 `scenario` 和负 `expected_turns`，CLI `Literal` 保护不到 Web/API 直接调用
  - 互斥 savings 测试手写汇总公式，没打到生产代码的 `_summarize_savings` 逻辑
- 改为：
  - 新增 `_check_suggestion_approval()` 方法：对每条降级/分层建议，基于 suggested model/strategy 构建 `GateInput`，调用 `RoutingGate.check_human_review()` 独立判断 `requires_approval`
  - Engine 层 `optimize()` 新增 scenario 白名单校验和 `expected_turns >= 1` 校验，非法值 raise ValueError
  - 汇总逻辑抽为 `_summarize_savings()` static method，测试直接调用生产代码
  - 新增 5 个测试：`test_downgrade_approval_based_on_suggestion_not_router`（P1）、`test_engine_validates_scenario/turns`（P2）、`test_summarize_savings_cap/zero`（P3）
- 原因：Review 三轮发现 1 个 P1（审批语义继承 bug）+ 1 个 P2（Engine 参数校验缺口）+ 1 个 P3（测试不覆盖生产代码）
- 改了之后好在哪：
  - `requires_approval` 准确反映建议后方案的治理约束，不再误导用户"降级到 Tier 2 可以直接执行"
  - Engine 层参数校验补齐，Web/API 直接调用也能拦住非法输入
  - 汇总逻辑独立可测，后续修改汇总公式时测试能真正失败

**#82 Review 四轮修复：审批提示浮到 CLI 顶层 + budget_status 真实计算**
- 原来：
  - 建议 `details.requires_approval=True` 但 CLI warnings 不提示，Rich 表也不展示，用户看 CLI 时不知道这条降级建议不能直接执行
  - `_check_suggestion_approval()` 写死 `budget_status=BudgetStatus.OK`，建议后成本超硬预算时 Gate 条件 3 不会触发
- 改为：
  - `optimize()` 汇总后检查 `any(s.details.requires_approval)`，有则插入 warning "部分优化建议（降级/分层）需审批后方可执行"
  - Rich 表对 `requires_approval=True` 的建议在类别列追加红色 "（需审批）" 标签
  - `_check_suggestion_approval()` 改用 `selector._compute_budget_status(suggested_cost, features)` 计算真实 budget_status
  - 新增 `test_approval_warning_when_router_ok_but_suggestion_needs_approval` 测试
- 原因：Review 四轮发现审批信息只存在 suggestion details 里，没有浮到用户可见的顶层；budget_status 硬编码导致超预算场景漏审批
- 改了之后好在哪：
  - 用户在 CLI 输出中一眼就能看到哪些建议需要审批（warning + 表格标签），不会误操作
  - 建议后成本超硬预算时 Gate 条件 3 正确触发，审批语义完整

---

### #83 Benchmark Level 1：离线规则 Benchmark（零 API 成本）

**原来：**
> 设计文档规划的 Benchmark 三级体系（Level 1 离线规则 / Level 2 真实 API / Level 3 策略回测），但没有实现。

**改为：**
> 实现 Level 1 离线规则 Benchmark：40 条 YAML 测试样例 → Router 规则引擎 → 6 指标评分。零 API 调用，证明路由决策逻辑正确、稳定、可回归。

**设计决策：**

1. **YAML 格式**（非 JSON）：统一文件 `data/benchmarks/level1/router_cases.yaml`，设计文档原为 `data/benchmark_cases/*.json`
2. **6 个指标**：
   - `classification_accuracy` >= 90%（任务分类准确率）
   - `complexity_accuracy` >= 85%（复杂度准确率）
   - `role_tier_accuracy` >= 95%（角色 tier 匹配，覆盖 executor/planner/reviewer 三角色）
   - `strategy_selection_accuracy` >= 85%（策略选择准确率）
   - `cost_estimation_reasonableness` >= 90%（成本合理性，跳过 no_candidate case）
   - `constraint_satisfaction` = 100%（硬约束，3 条规则带前提条件）
3. **Exit code 严格模式**：0 = 所有 case passed 且所有 metric 达标；否则 1
4. **expected 值来源**：来自设计文档 / routing_rules.yaml / Gate 规则，不为匹配 Router 行为而校准
5. **诊断顺序**：Router bug → prompt 歧义 → expected 错误
6. **PE/PER 策略**：当前 Selector 评分中 SINGLE_MODEL 通常优于 PE/PER（Tier 1 质量相同但 PE 有额外成本），benchmark case 反映实际行为

**约束规则（constraint_satisfaction 100%）：**
- EXPERT 任务不用 Tier 3 executor
- SIMPLE + LOW risk + sensitivity != HIGH + category 不在 forced review → 不触发 requires_human_review
- requires_human_review=true → quality_gate 含 "human_review"

**文件结构：**
- `src/airouter/engine/benchmark/schemas.py`：BenchmarkCase / CaseResult / BenchmarkSummary
- `src/airouter/engine/benchmark/loader.py`：YAML 加载 + enum 校验
- `src/airouter/engine/benchmark/scorer.py`：6 指标计算 + case failure 检测
- `src/airouter/engine/benchmark/runner.py`：Level1BenchmarkRunner
- `src/airouter/cli/benchmark.py`：CLI 命令（Rich/JSON 输出 + --level + --resume）
- `data/benchmarks/level1/router_cases.yaml`：40 条测试样例
- `tests/unit/test_benchmark.py`：34 个单元测试
- `tests/integration/test_benchmark_level1.py`：13 个集成测试

**改了之后好在哪：**
- 零 API 成本验证路由规则正确性，可纳入 CI 回归测试
- 40 条样例覆盖 8 个维度（简单/中等/复杂/高风险/PE/Gate/Context/Budget）
- 6 指标量化路由质量，硬约束保证安全底线
- CLI 支持 Rich/JSON 双格式输出，便于自动化和人工审查

---

## 未完结的讨论项

> 以下话题尚未深入讨论，后续如有修改再补充。
> 优先级标注 ⚠️ 的为 Week 2 开始前需要确定的，其余可在对应开发周再定。

- ~~⚠️ **轻量A（可观测性）的浪费模式检测算法**~~ — 已在 Phase 4 实现（P1-P5，见 CHANGELOG #68-#72）
- ~~⚠️ **CLI工具的完整命令设计**（参数、输出格式、子命令）~~ — analyze/audit 已实现，optimize/benchmark 待 Week 2 后半段
- Docker部署方案细节 — Week 3 D21实现
- 最佳实践手册9章的具体内容规划 — Week 4 D23写
- SOP 5个的具体内容规划 — Week 4 D24写
