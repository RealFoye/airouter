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

## 未完结的讨论项

> 以下话题尚未深入讨论，后续如有修改再补充。
> 优先级标注 ⚠️ 的为Week 2开始前需要确定的，其余可在对应开发周再定。

- ⚠️ **轻量A（可观测性）的浪费模式检测算法** — 支撑audit命令和优化中心
- ⚠️ **CLI工具的完整命令设计**（参数、输出格式、子命令） — Week 2要交付4个CLI
- Docker部署方案细节 — Week 3 D21实现
- 最佳实践手册9章的具体内容规划 — Week 4 D23写
- SOP 5个的具体内容规划 — Week 4 D24写
