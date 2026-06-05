# AI Router 踩坑记录

> 记录项目中遇到的设计缺陷、实现陷阱和工程教训。每条包含：问题现象、根因分析、修复方案、教训总结。
> 用于后续复盘和团队知识传承。

---

## 坑 1：Selector/Gate 职责分裂导致管控门禁失效

**严重度：P1（企业管控核心）**
**发现时间：Week 1 检查点后**
**涉及文件：router.py, selector.py**

### 问题现象

"写一个FastAPI JWT鉴权中间件"的路由决策输出：

```json
{
  "risk_level": "HIGH",
  "executor": "qwen3.7-plus",  // Tier 2 模型
  "quality_gate": ["human_review", "syntax_check", "ast_parse"],
  "requires_human_review": false
}
```

系统内部有两个"人工审核"概念在打架：
- `quality_gate` 里有 `human_review`（说明结果质量验证阶段需要人工看）
- `requires_human_review` 为 false（说明路由推荐可以自动放行）

高风险任务推荐了 Tier 2 模型，却不要求人工确认。这是企业管控的硬 bug。

### 根因分析

不是"功能没做完"，而是架构问题：**Selector（评分推荐）和 Gate（管控门禁）的职责没有分离**。

代码中有三个平行方法各算各的：
- `_check_human_review()` — 从 features 推导，只实现了 3/7 条件
- `_build_quality_gate()` — 从 features 推导，有自己的规则
- `_check_budget()` — 在 Router 层后置检查，Selector 不知道

传参也暴露了未完成的意图：

```python
def _check_human_review(self, features, model, budget_status, quality):
    # model 和 quality 传进来了，但函数体里没用
```

这说明实现时已经意识到需要基于模型 tier 和质量损失做判断，但没收口。

### 修复方案

1. 创建独立的 `RoutingGate` 模块（`gate.py`）
2. `GateInput` dataclass 明确定义 Gate 需要的所有输入
3. `check_human_review()` 实现完整的 7 条规则（设计 4.6.2）
4. `build_quality_gate(features, requires_human_review)` — 接受 review 结果作为参数
5. 关键联动：`requires_human_review=true` → `human_review` 必须在 `quality_gate` 中
6. Router 移除内部门禁方法，改为调用 Gate

### 教训

**原则：Selector 可以推荐"性价比最优"，Gate 必须决定"能否自动执行"。**

- 不要让同一个模块既做推荐又做审核——两个职责的输入/输出/判断逻辑完全不同
- 如果两个字段语义相关（如 `quality_gate` 和 `requires_human_review`），它们必须由同一个模块产出，且有因果链
- 传了参数但不用 = 设计意图未完成的信号，应该在 code review 时抓住

---

## 坑 2：预算检查是"后置标签"不是"硬约束"

**严重度：P1/P2**
**发现时间：Week 1 检查点后**
**涉及文件：selector.py, router.py**

### 问题现象

Selector 只过滤能力、Tier、上下文、敏感性，不检查预算。预算只在 Router 选中最终模型后才检查一次。

结果：
- 替代方案列表不知道每个方案的预算状态
- 审计时无法解释"为什么推荐 A 而不是 B"
- Week 2 做 audit/optimize 时缺少候选级 metadata

### 根因分析

设计文档 4.2.3 明确写了 5 项硬约束，第 5 项是预算：

```python
# 5. 预算约束（两层：soft warning + hard approval，均不直接排除）
if estimated_cost > constraints.hard_budget_limit:
    model.budget_status = "OVER_HARD_BUDGET"
    model.requires_approval = True
elif estimated_cost > constraints.soft_budget_limit:
    model.budget_status = "WARNING"
```

但实现时只做了 4 项（能力、Tier、上下文、敏感性），预算被推到了 Router 层。

设计文档说的是"候选级标签"（每个候选都带 budget_status），实现做成了"后置单次检查"。

### 修复方案

1. `CandidateScore` 新增 `budget_status: BudgetStatus` 和 `requires_approval: bool`
2. `score_models()` 中为每个候选调用 `_compute_budget_status()`
3. Router 的 `budget_status` 直接用 `best.budget_status`（来自 Selector）
4. 替代方案列表展示预算状态
5. 新增 `BudgetStatus.OVER_HARD_BUDGET` 枚举值
6. 预算计算：`soft_budget = min(task_budget_default, max_cost_cny)`，`hard_budget = soft_budget × multiplier`

### 教训

**设计文档里的"硬约束清单"必须全部在过滤层实现，不能留到后面补。**

- 如果一个属性影响"这个方案能不能用"，它应该在候选生成阶段就计算好
- 后置检查会导致：选中的方案可能不合规、替代方案缺少关键 metadata、审计链路不完整
- 配置文件中定义了 `task_budget_hard_limit_multiplier` 但代码没用 = 配置与代码脱节

---

## 坑 3：正则字符类 vs 词级匹配

**严重度：P2**
**发现时间：Week 1 检查点后**
**涉及文件：analyzer.py**

### 问题现象

"设计一个支持百万并发的消息推送系统"被拆成：
```python
["设计一个支持百万", "发的消息推送系统"]
```

"并发"被切成了"并" + "发"。

### 根因分析

```python
re.split(r'[和以及并且+，,]', desc)
```

方括号是**字符类**，匹配集合中的任意一个字符。实际含义是：

```
按以下任意一个字符拆分：和、以、及、并、且、+、，、,
```

所以：
- "并发" → 在"并"处拆开
- "以及" → 在"以"处拆开（"及"也可能拆）
- "所以" → 在"以"处拆开（完全不应该拆的词）

### 修复方案

```python
# 词级匹配（用 alternation 而非 character class）
re.split(r'(?:以及|并且|而且|和|及|\+|，|,)', desc)
```

`(?:...)` 是非捕获分组，`|` 是 alternation（或）。这样"以及"作为完整词匹配，不会拆单字。

### 教训

**正则方括号 `[abc]` 匹配单字符，不是词。多字符分隔符必须用 alternation `a|b|c`。**

- 中文分词场景下，很多"分隔符"其实是多字词（"以及"、"并且"），不能用字符类
- 测试只断言了 `len(subtasks) > 0`，没有断言内容合理性 → 漏掉了这个 bug
- 对于文本处理类代码，应该加一些"不应被拆开"的 negative test case

---

## 坑 4：Schema 命名混用 API 输出和 DB 审计

**严重度：P2**
**发现时间：Week 1 检查点后**
**涉及文件：schemas.py**

### 问题现象

`ExecutionFeedback` 和 `BenchmarkResult` 的 Pydantic 模型与设计文档第十章的 SQL schema 严重不一致：

| Pydantic 字段 | SQL schema 字段 | 问题 |
|---------------|-----------------|------|
| `model_name` (单数) | `executed_models_json` (列表) | 语义不同 |
| `latency_ms` | `actual_latency_ms` | 命名不一致 |
| — | `executed_strategy` | 缺失 |
| — | `user_accepted` | 缺失 |
| — | `quality_gate_passed` | 缺失 |
| — | `user_override_reason/note` | 缺失 |
| — | `actual_calls_json` | 缺失（Plan-Execute 多次调用明细） |

### 根因分析

Week 1 实现时把 Schema 当成了"轻量 API 输出对象"，没有对齐设计文档中的审计字段。

设计文档的 SQL schema 是为 Week 2/3 的审计、DB、benchmark 回测准备的，包含：
- 实际执行策略 vs 推荐策略（用于 override 分析）
- 用户是否接受推荐（用于路由信任度分析）
- 质量门禁是否通过（用于质量追踪）
- Plan-Execute 多次调用明细（用于成本拆解）

这些字段在 Week 1 的 CLI 阶段用不到，但如果不在 schema 中预留，Week 2 做 DB models 时会返工。

### 修复方案

1. 对照设计文档第十章 SQL schema 补齐所有字段
2. 统一命名：`actual_latency_ms`（而非 `latency_ms`）、`executed_models_json`（列表而非单数）
3. `BenchmarkResult` 补齐 `suite_name/version`、`case_version`、`severe_failure`、`gate_passed`、`raw_output_path`
4. 保持 Pydantic 模型和 SQL schema 的字段一一对应

### 教训

**Schema 应该从"数据审计需要什么"反推，而不是从"当前 API 输出什么"正推。**

- MVP 阶段可以先不填所有字段（Optional），但字段定义必须存在
- Pydantic 模型和 SQL 表结构应该一一对应，减少 ORM 映射的心智负担
- `ModelConfig`（设计文档）vs `ModelEntry`（代码）这类命名不一致要尽早统一

---

## 坑 5：测试偏"通路验证"，缺少"政策验证"

**严重度：隐性风险**
**发现时间：Week 1 检查点后**
**涉及文件：test_router.py**

### 问题现象

111 tests 全部通过，但没有发现上面 4 个设计缺陷。

关键测试 `test_router_high_risk_requires_review`：

```python
def test_router_high_risk_requires_review(router):
    decision = router.route("设计一个支持百万并发的消息推送系统")
    assert decision.requires_human_review is True
```

这个测试通过了，但原因不对：它通过是因为 `ARCHITECTURE` 在 `human_review_required_tasks` 配置列表中（条件7），而不是因为系统正确实现了"高风险 + Tier 2 降级需要审核"（条件2）。

如果用 `CODE_GENERATION + HIGH risk + Tier 2` 的任务测试，就会发现 `requires_human_review=false`。

### 根因分析

测试策略偏"通路验证"（能跑、能输出、不报错），缺少"政策验证"（管控规则是否正确）。

两种测试的区别：

| 类型 | 目的 | 断言方式 |
|------|------|----------|
| 通路测试 | 证明"能跑" | `assert decision is not None` |
| 政策测试 | 证明"规则正确" | `assert requires_human_review == True` when condition X |

### 修复方案

新增 25 条政策验证测试（`test_gate.py` + `test_router.py`）：

- 逐条测试 Gate 的 7 个条件（正例 + 反例）
- 端到端政策测试：高风险+Tier 2、质量损失阈值、Gate/quality_gate 一致性
- 关键测试：`test_policy_high_risk_tier2_must_review` — 直接覆盖最大 bug case

### 教训

**测试不只证明"能跑"，更要证明"规则正确"。**

- 如果一个测试通过了，但原因不是你期望的那个，它就是假阳性
- 企业管控系统需要"政策测试"：输入特定条件 → 断言特定规则被触发
- 每个政策测试都应该有注释说明"这条测试证明什么规则"
- 反例测试同样重要：`HIGH risk + Tier 1 → 不应触发降级审核`

---

## 坑 6：quality_loss_vs_baseline 公式写死 0.90 导致 SIMPLE 任务误触发审核

**严重度：P1（Gate 误杀省钱路径）**
**发现时间：Week 1 第二轮审查**
**涉及文件：router.py**

### 问题现象

```python
quality_loss = round(max(0, 0.90 - quality), 4)
```

"写一个Python函数检查回文"（SIMPLE/LOW/Tier 3）：
- 推荐模型：deepseek-v4-flash（Tier 3），quality = 0.44
- 公式输出：quality_loss = 0.90 - 0.44 = 0.46（46%）
- Gate 条件 6 触发：`quality_loss 46% > 20%` → `requires_human_review = True`

这直接和 Week 1 "简单任务直接 Tier 3"的设计目标冲突。SIMPLE/LOW/Tier 3 的核心省钱路径被 Gate 锁死。

### 根因分析

`0.90` 是一个拍脑袋的"理想质量基准"，不是真实的 baseline。

真实语义应该是：**在系统允许选择的方案里，质量牺牲了多少？**

不同任务的 allowed_tiers 不同，所以 baseline 应该来自候选集本身：

| 任务 | allowed_tiers | 真实 baseline 来源 | 推荐 | quality_loss |
|------|--------------|-------------------|------|-------------|
| SIMPLE | [3] | Tier 3 ≈ 0.44 | Tier 3 | ≈ 0 |
| MODERATE | [2,3] | Tier 2 ≈ 0.644 | Tier 3 | 0.204 |
| COMPLEX+HIGH | [1,2] | Tier 1 = 0.776 | Tier 2 = 0.644 | 0.132 |
| EXPERT | [1] | Tier 1 = 0.776 | Tier 1 | 0 |

用 0.90 作为固定基准，所有 Tier 3 任务都会被误报。

### 修复方案

```python
# quality baseline = 候选集中最高质量（通过硬约束后的所有候选）
scored = selector.score_models(candidates, features)
baseline_quality = max(cs.quality for cs in scored) if scored else quality
quality_loss = round(max(0, baseline_quality - quality), 4)
```

同时，Gate 条件 6 加前置条件 `risk_level != LOW`：

```python
if f.risk_level != RiskLevel.LOW and gate_input.quality_loss_vs_baseline > 0.20:
    reasons.append(...)
```

LOW risk 的 SIMPLE/LOW/Tier 3 省钱路径不应被 Gate 锁死。复杂度管"做起来难不难"，风险管"错了痛不痛"——Gate 是管控层，应该看风险。

### 教训

**不要用拍脑袋的常量作为基准值。baseline 应该来自系统的实际可选范围。**

- `0.90` 看起来像"理想质量"，但系统里可能根本没有质量 0.90 的模型
- 如果一个阈值判断影响了门禁行为，它的基准必须是可追溯的（来自配置或候选集）
- `risk_level != LOW` 前置条件避免了"复杂就审批"的粗糙规则

---

## 坑 7：cost baseline 和 quality baseline 故意不对称

**严重度：设计决策（不是 bug，但容易被误改）**
**决定时间：Week 1 第二轮审查**
**涉及文件：router.py**

### 设计决策

Router 使用两个不同的 baseline，回答两个不同的问题：

```text
cost baseline = Tier 1 最贵/强模型成本
→ 回答：相对全程强模型，省了多少钱？（演示/商业口径）

quality baseline = 当前可行候选中的最高质量
→ 回答：在系统允许选择的方案里，质量牺牲了多少？（管控/风险口径）
```

### 为什么不对称是正确的

这两个问题本来就不是同一个问题：

- **成本 baseline** 用 Tier 1（即使 Tier 1 不在 allowed_tiers 中）—— 因为用户想知道"和最强模型比，我省了多少"。这是一个商业价值展示。
- **质量 baseline** 用候选集最高（只在 allowed_tiers 中）—— 因为 Gate 关心的是"在系统认为安全的方案里，质量有没有被牺牲太多"。如果 Tier 1 不在 allowed_tiers 中，它不是一个"可选方案"，不应该作为质量比较基准。

举例：SIMPLE 任务 allowed_tiers=[3]，Tier 1 成本 0.45，Tier 3 成本 0.01：
- savings = (0.45 - 0.01) / 0.45 = 98%（和 Tier 1 比省了 98%）
- quality_loss = 0（Tier 3 就是 baseline，没有质量牺牲）

如果"统一 baseline"都用 Tier 1：
- quality_loss = 0.776 - 0.44 = 0.336（误报：Tier 1 本来就不在 SIMPLE 的可选范围内）

如果"统一 baseline"都用候选集：
- savings = 0（只有一个 Tier 3 候选，没有成本对比）

### 教训

**当两个指标回答不同的问题时，用不同的 baseline 是语义成熟的标志，不是不一致。**

- 未来维护者可能会试图"统一 baseline 让代码更干净"——这会破坏语义
- 在代码注释中标注："cost baseline 和 quality baseline 使用不同基准（见 pitfalls.md 坑7）"
- 如果后续要改 baseline 逻辑，先想清楚"改的是哪个问题的答案"

---

## 通用教训总结

### 1. 先分析再动手

Week 1 检查点后的 4 个缺陷，根因都是"实现时没有仔细对照设计文档"。CLAUDE.md 里写了"动手写代码之前，先读设计文档对应章节"，但实际执行时为了赶进度跳过了这一步。

**改进：每个模块开始前，花 10 分钟读设计文档对应章节，确认输入/输出/边界条件。**

### 2. 参数传了但不用 = 设计意图未完成

`_check_human_review(features, model, budget_status, quality)` 中 `model` 和 `quality` 传了但函数体没用。这是明显的信号。

**改进：code review 时检查所有未使用的参数，要么用上，要么删掉。**

### 3. 配置文件中定义了但代码没用 = 配置与代码脱节

`budgets.yaml` 有 `task_budget_hard_limit_multiplier: 3.0`，但代码中从未引用。

**改进：写完一个模块后，grep 检查对应的配置文件是否都被引用了。**

### 4. 测试通过不等于正确

111 tests pass 但没发现 4 个设计缺陷。测试覆盖率和测试质量是两回事。

**改进：测试应该覆盖"规则"而不仅是"通路"。每个测试问自己：如果这条测试通过了但原因不对，它能发现吗？**

### 5. `if` 在政策测试中是隐蔽的空测试

```python
# 看起来在测试，但 reasons 里天然包含 "Tier 1"（"相比 Tier 1 基线节省 XX%"）
# 所以 "Tier 1" not in str(decision.reasons) 永远为 false，if 分支永远不执行
if decision.models.executor and "Tier 1" not in str(decision.reasons):
    assert decision.requires_human_review is True  # 永远不会执行
```

**改进：政策测试用确定性断言，不用 `if`。选择一个确定会触发特定行为的 case，直接断言。**

```python
executor = router.registry.get_by_name(decision.models.executor)
assert executor.tier == 2
assert decision.risk_level == RiskLevel.HIGH
assert decision.requires_human_review is True
```

### 6. 不要用拍脑袋的常量作为基准值

`0.90` 作为 quality baseline 看起来合理，但系统里可能根本没有 0.90 的模型。

**改进：baseline 应该来自系统的实际状态（配置或候选集），而不是硬编码常量。**
