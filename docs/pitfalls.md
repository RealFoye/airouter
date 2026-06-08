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
- Phase 2B 延续：Selector post-filter 的 savings baseline 也统一用 Tier 1 成本（`_compute_tier1_baseline()`），与 Router 的 `baseline_cost` 保持一致口径。质量 baseline 仍用候选集最高质量。两者在 post-filter 中各司其职

---

## 坑 8：`for`/`if` 包裹断言 = 空测试（条件式断言的变体）

**严重度：隐性风险（测试全绿但什么都没测到）**
**发现时间：Week 2 Phase 2B 第二轮审查**
**涉及文件：test_strategies.py, test_router.py**

### 问题现象

两个测试看起来都 pass，但断言从未真正执行：

**变体 A — `for` 循环在空列表上 no-op：**
```python
per_scores = [s for s in scores if s.strategy == StrategyType.PLAN_EXECUTE_REVIEW]
for s in per_scores:  # per_scores 是 []，循环体永远不执行
    assert s.model_assignment.planner is not None
    assert s.model_assignment.executor is not None
    assert s.model_assignment.reviewer is not None
```

**变体 B — `if` 分支不进入：**
```python
if decision.recommended_strategy == StrategyType.PLAN_EXECUTE_REVIEW:  # 当前永远是 False
    assert decision.models.planner is not None
    assert decision.models.executor is not None
    assert decision.models.reviewer is not None
```

根因相同：**PER raw 候选被 post-filter 全排除（成本不比 Tier 1 single 省），最终 SINGLE 胜出。** 测试看起来在测"PER 候选含全角色"，但实际上一行断言都没跑。

### 根因分析

这类问题的特征是：**测试的意图是验证某个中间产物的结构，但测试入口是端到端流程，中间产物可能被后续步骤过滤掉。**

坑 5 已经指出过 `if` 版本，但 `for` 版本更隐蔽：`for` 循环不报错，不像 `if` 那样有明显的"条件判断"视觉提示。

### 修复方案

**方案 1：绕过过滤层，直接测中间产物**
```python
# 直接测 _build_per_candidates raw 输出（绕过 post-filter）
per_raw = selector._build_per_candidates(role_pool, features, estimator, reasons)
assert per_raw, "PER raw candidates should not be empty"  # 显式非空断言
for s in per_raw:
    assert s.model_assignment.planner is not None
```

**方案 2：mock 下游，构造确定性输入**
```python
# mock selector 返回 PER StrategyScore → Router 应把三角色带到 decision
per_score = StrategyScore(
    strategy=StrategyType.PLAN_EXECUTE_REVIEW,
    model_assignment=ModelAssignment(
        planner="qwen3.7-max", executor="qwen3.7-plus", reviewer="deepseek-v4-pro",
    ),
    ...
)
with patch.object(router.selector, "select_best_strategy", return_value=[per_score]):
    decision = router.route("xxx")
assert decision.models.planner == "qwen3.7-max"  # 确定性断言
```

### 教训

**`for`/`if` 包裹断言 = 空测试。任何条件下才执行的断言都需要显式非空前置检查。**

- 写完测试后自问：如果列表是空的 / 条件不满足，这条测试还能失败吗？如果不能，它就是空测试
- 对于"验证中间产物结构"的测试，要么直接调中间方法（绕过过滤层），要么 mock 下游（构造确定性输入）
- 加一行 `assert result` 或 `assert len(result) > 0` 作为前置守卫，防止空列表静默通过

---

## 坑 9：SQLite 外键默认 OFF，FK 声明只是 metadata

**严重度：P1（数据完整性）**
**发现时间：Week 2 Phase 1 续 review**
**涉及文件：database.py, db_models.py**

### 问题现象

ORM 模型声明了 `ForeignKey("routing_decisions.id")`，但 `ExecutionFeedbackRecord(routing_decision_id=999)` 可以成功写入。`test_execution_feedback_fk` 用 inspector 验证了 FK 声明存在，但没验证坏 FK 会被拒绝。

### 根因分析

SQLite 默认 `PRAGMA foreign_keys=OFF`。FK 约束声明只影响 `CREATE TABLE` 的 DDL，不影响运行时 INSERT/UPDATE/DELETE 行为。必须显式开启：

```python
@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_conn, connection_record):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()
```

同理，ORM 级 `cascade="all, delete-orphan"` 只在 `session.delete()` 时生效，raw SQL `DELETE FROM routing_decisions` 不会级联删除子表。需要 DB 级 `ondelete="CASCADE"` 双重保险。

### 修复方案

1. `init_db()` 中 SQLite 连接加 `PRAGMA foreign_keys=ON`
2. FK 定义加 `ondelete="CASCADE"`
3. 新增 `test_fk_enforcement`：`routing_decision_id=999` 应抛 `IntegrityError`

### 教训

**SQLite 的 FK 声明不等于 FK 强制。必须显式 `PRAGMA foreign_keys=ON`。**

- ORM 声明了 FK ≠ 数据库会 enforce，尤其是 SQLite
- 每个 FK 都应该有对应的 enforcement 测试（不只是 inspector 看声明）
- PostgreSQL/MySQL 默认 enforce FK，SQLite 是例外——但这个例外在 MVP 阶段很常见

---

## 坑 10：Tier 数字方向混淆（min/max 语义反转）

**严重度：P2（审计误报/漏报）**
**发现时间：Week 2 Phase 4 review**
**涉及文件：detector.py**

### 问题现象

P4（可降级未降级）检测器使用 `min(allowed_tiers)` 推导"最低可用 tier"，但实际应该用 `max(allowed_tiers)`。

例如：MODERATE + LOW risk 的 allowed_tiers = [2, 3]：
- `min([2, 3])` = 2（Tier 2，更贵）
- `max([2, 3])` = 3（Tier 3，更便宜）

用 `min()` 推导出的"最低可用 tier"其实是最贵的可用 tier，导致 P4 漏报"Tier 1 本可降到 Tier 3"的浪费。

### 根因分析

Tier 编号方向与直觉相反：**数字越小越贵，数字越大越便宜**。

- Tier 1 = 重型/昂贵（qwen3.7-max）
- Tier 3 = 轻量/便宜（deepseek-v4-flash）

代码注释和变量名没有明确标注这个方向，导致 `min()`/`max()` 的选择凭直觉而非语义。

### 修复方案

1. `min(allowed_tiers)` → `max(allowed_tiers)`
2. 变量名 `min_tier` → `cheapest_tier`，明确语义
3. 注释标注："Tier 数字越大越便宜，所以 max() 是最便宜的"
4. 新增正例测试：MODERATE + LOW + Tier 1 应触发 P4

### 教训

**当编号方向与直觉相反时（数字越小越贵/越大越强），必须在变量名和注释中明确标注方向。**

- 不要假设阅读代码的人知道"Tier 1 是最贵的"
- 变量名应该包含方向信息：`cheapest_tier` 比 `min_tier` 更明确
- 对于涉及比较的逻辑，加一行注释说明"为什么用 max 而非 min"

---

## 坑 11：嵌套配置访问路径错误（getattr vs 属性链）

**严重度：P1（P5 永远检测不到）**
**发现时间：Week 2 Phase 4 review**
**涉及文件：detector.py**

### 问题现象

P5（缓存机会未利用）检测器使用 `getattr(m, "supports_prompt_caching", False)` 读取模型是否支持缓存，但 `ModelEntry` 的缓存配置在 `m.cache.supports_prompt_caching` 中，导致 P5 永远返回 False。

### 根因分析

`ModelEntry` 的结构是：
```python
class ModelEntry(BaseModel):
    cache: ModelCacheConfig = Field(default_factory=ModelCacheConfig)

class ModelCacheConfig(BaseModel):
    supports_prompt_caching: Union[bool, str] = False
    cache_min_prefix_tokens: int = 0
```

访问路径应该是 `m.cache.supports_prompt_caching`，但代码写成了 `getattr(m, "supports_prompt_caching", False)`，相当于在 `ModelEntry` 上找 `supports_prompt_caching` 属性，永远找不到，返回默认值 False。

### 修复方案

```python
# 原来
"supports": getattr(m, "supports_prompt_caching", False),
"min_prefix_tokens": getattr(m, "cache_min_prefix_tokens", 1024),

# 改为
"supports": m.cache.supports_prompt_caching is True,
"min_prefix_tokens": m.cache.cache_min_prefix_tokens,
```

注意 `is True` 而非直接布尔转换，因为 `supports_prompt_caching` 可能是 `"unknown"` 字符串。

### 教训

**嵌套对象的属性访问必须沿着正确的路径，不能用 getattr 在顶层对象上找。**

- 写完代码后，手动构造一个测试对象，打印出访问路径验证是否正确
- 对于 Pydantic 模型，IDE 的类型提示可以帮助发现路径错误
- `getattr(obj, "field", default)` 的 default 会掩盖"字段不存在"的错误，应该谨慎使用

---

## 坑 12：Rich console.print() 破坏 JSON 结构

**严重度：P1（CLI JSON 输出不可解析）**
**发现时间：Week 2 Phase 4 review**
**涉及文件：audit.py**

### 问题现象

`ai-router audit --format json` 的输出无法被 `json.loads()` 解析：

```
json.decoder.JSONDecodeError: Invalid control character at: line 200 column 53
```

原因是 JSON 字符串中插入了换行符：
```json
"suggestion": "用户 alice 有 3 条任务上下文过长（平均 38868 
tokens），建议裁剪到合理范围"
```

### 根因分析

Rich 的 `console.print()` 会自动换行以适应终端宽度。当 JSON 字符串超过终端宽度时，Rich 会在字符串中间插入换行符，破坏 JSON 结构。

```python
console.print(json.dumps(output, indent=2, ensure_ascii=False))
# Rich 自动换行 → JSON 字符串中插入 \n → json.loads() 失败
```

### 修复方案

JSON 输出使用 `print()` 而非 `console.print()`：

```python
# 使用 print 而非 console.print 避免 Rich 自动换行破坏 JSON 结构
print(json.dumps(output, indent=2, ensure_ascii=False))
```

或者使用 Rich 的 `soft_wrap=True` 和 `crop=False`：

```python
console.print(json.dumps(...), soft_wrap=True, crop=False)
```

但 `print()` 更简单，且 JSON 输出不需要 Rich 的格式化功能。

### 教训

**机器可读输出（JSON/XML/CSV）应该用 `print()` 而非 Rich 的 `console.print()`。**

- Rich 的自动换行对人可读输出（表格、面板）是特性，对机器可读输出是 bug
- 如果一个命令有 `--format json` 模式，JSON 分支应该用 `print()` 或 `sys.stdout.write()`
- 测试时不仅要验证 JSON 能输出，还要验证 `json.loads()` 能解析

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

### 5. `if` / `for` 在政策测试中是隐蔽的空测试

```python
# 看起来在测试，但 reasons 里天然包含 "Tier 1"（"相比 Tier 1 基线节省 XX%"）
# 所以 "Tier 1" not in str(decision.reasons) 永远为 false，if 分支永远不执行
if decision.models.executor and "Tier 1" not in str(decision.reasons):
    assert decision.requires_human_review is True  # 永远不会执行
```

`for` 版本更隐蔽：`for s in []:` 不报错，循环体永远不执行，测试照样 pass（见坑 8）。

**改进：政策测试用确定性断言，不用 `if`/`for` 条件包裹。选择一个确定会触发特定行为的 case，直接断言。**

```python
executor = router.registry.get_by_name(decision.models.executor)
assert executor.tier == 2
assert decision.risk_level == RiskLevel.HIGH
assert decision.requires_human_review is True
```

### 6. 不要用拍脑袋的常量作为基准值

`0.90` 作为 quality baseline 看起来合理，但系统里可能根本没有 0.90 的模型。

**改进：baseline 应该来自系统的实际状态（配置或候选集），而不是硬编码常量。**

### 7. 编号方向与直觉相反时，必须在变量名中标注

Tier 1 = 最贵，Tier 3 = 最便宜。`min(tiers)` 取到的是最贵的，不是最便宜的。

**改进：变量名包含方向信息（`cheapest_tier` 而非 `min_tier`），注释说明"为什么用 max 而非 min"。**

### 8. 嵌套配置访问必须沿正确路径，不能用 getattr 在顶层找

`m.cache.supports_prompt_caching` 不等于 `getattr(m, "supports_prompt_caching", False)`。后者永远返回 default。

**改进：手动构造测试对象验证访问路径，或用 Pydantic 的类型提示检查。**

### 9. 机器可读输出用 `print()`，人可读输出用 `console.print()`

Rich 的自动换行会破坏 JSON 结构。JSON/XML/CSV 输出应该用 `print()` 或 `sys.stdout.write()`。

**改进：`--format json` 分支用 `print()`，测试时验证 `json.loads()` 能解析。**

### 10. 种子数据的配置（价格/tier/能力）必须从单一来源派生，不能硬编码

`generate_seed_data.py` 里硬编码了 `MODEL_PRICING` 字典，和 `models.yaml` 差了 5 倍。`select_model()` 和 P5 的 `cache_models` 也硬编码了模型名。当 `models.yaml` 修改后，种子数据不会同步。

**改进：用 `@lru_cache` + `load_models()` 派生所有配置（价格、tier 池、cache 模型池）。`models.yaml` 是单一来源，种子脚本不维护副本。**

### 11. 时间偏移注入（P2/P5）必须做有界 delta，防止生成未来时间戳

P2 加 1-9 分钟、P5 加 2-24 小时到 base 时间戳。如果 base 接近 `now`，偏移后会进入未来。Collector 按 `created_at < end_date` 过滤，导致写入数 ≠ 采集数。

**改进：计算 `remaining = (now - 1s) - base_timestamp`，`max_delta = min(上限, remaining)`。如果 remaining 不够最小间隔，skip 这条注入。**

### 12. 集成测试不能依赖本地 gitignored 文件

`test_cli.py` 直接读 `sqlite:///seed.db`，但 `seed.db` 被 `.gitignore` 排除。CI 或干净 checkout 上测试必然失败。

**改进：用 `tmp_path_factory` 创建临时 DB + 调用数据生成函数造数据。测试自包含，不依赖本地状态。**

### 13. Pydantic v2 `field_validator` 不会对默认值触发

`ContextBlock` 的 `protected` 和 `token_count` 用了 `field_validator(mode="before"/"after")`，但因为字段有默认值（`False` / `0`），Pydantic v2 不会调用 validator。导致 `SYSTEM_PROMPT` 的 `protected` 始终为 `False`。

**改进：改用 `model_validator(mode="after")`，在所有字段赋值后统一修改。`field_validator` 只在调用方显式传值时才生效，不适合"自动补默认值"的场景。**

### 14. 压缩策略的"额外截断"需要排除 CONSERVATIVE

`Compressor.compress()` 对 `TOOL_OUTPUT` 类型做了额外截断（`max_lines = 20 if STANDARD else 5`），但 `else` 分支把 `CONSERVATIVE` 也按 AGGRESSIVE 处理（5 行）。CONSERVATIVE 的设计意图是"只去空行，不截断"。

**改进：截断条件加 `strategy != CONSERVATIVE` 前置判断。每个策略级别的"额外处理"都需要显式检查是否应该跳过。**

### 15. NONE 策略不能 early return，必须走完预算裁剪

`Compressor.compress(NONE + total_budget)` 直接 return 了，导致 `PriorityAssembler` 预算裁剪被跳过。`total_budget` 是公开参数，语义是"最终不超过这个预算"，所有策略都应该走到 assembler。

**改进：NONE 策略跳过摘要/截断（用 `if strategy != NONE` 包裹），但不 early return，继续执行预算裁剪。测试覆盖 `NONE + total_budget=1` 场景。**

### 16. 中间模块丢弃信息会导致下游无法解释

`PriorityAssembler._evict()` 返回 `(retained, dropped)`，但 `assemble()` 只返回 `retained`，dropped 被 `_` 丢掉。`Compressor` 只记录冗余剔除的 dropped，不记录预算裁剪的 dropped。结果 `optimize` CLI 无法解释"为什么删了这个块"。

**改进：引入 `AssemblyResult` dataclass（`retained`、`dropped`、`actions`），`assemble()` 返回完整结果。每个中间步骤的丢弃/截断都要记录到 actions，最终汇总到 `CompressionResult.applied_actions`。**

### 17. 计划/文档承诺的功能必须落地或显式降级

计划和文档说冗余剔除用"hash + Jaccard"，但实现只有 hash 精确去重。如果功能未实现，文档/计划/测试要一致；否则就是功能承诺未落地。

**改进：要么补实现，要么改文档明确降级为"仅 hash 精确去重"。MVP 阶段选择降级（Jaccard ROI 太低），文档/计划/CHANGELOG 同步修改。**

---

### 18. optimize 降级/分层建议必须用完整路由硬约束过滤

`_suggest_downgrade()` 和 `_suggest_plan_execute()` 只用了 `Selector._filter_base()`（仅 context window + sensitivity），跳过了 `allowed_tiers`、`capabilities`、`quality post-filter`。结果 EXPERT+HIGH 任务（routing_rules 只允许 Tier 1）被建议降到 Tier 2，且不具备所需能力的模型也被推荐。

**改进：改用 `Selector.filter_candidates()` 做完整硬约束过滤（capabilities + allowed_tiers + context window + sensitivity）。降级/分层建议不应绕过路由治理规则。**

### 19. Plan-Execute 建议要求 subtasks >= 2

PE 只有 1 个 subtask 时，planner 的额外开销不划算（planner 看全量上下文 + executor 调用），总成本反而更高。

**改进：`_suggest_plan_execute()` 加 `len(features.subtasks) >= 2` 守卫。1 个 subtask 不如直接单模型执行。**

### 20. 无效 --model 不能静默变成成本 0

`ai-router optimize --model nonexistent` exit 0 并输出 `current_cost=0.0`，用户会误以为模型很便宜。

**改进：CLI 入口校验模型名，不存在就 `Exit(1)` + 列出可用模型。所有接受模型名的 CLI 命令都应该做这个校验。**

### 21. 互斥优化建议不能简单求和

降级和分层（Plan-Execute）是互斥方案（一个改模型，一个改策略），不能同时应用。直接求和所有建议的 savings 会严重高估。

**改进：正交建议（缓存/压缩/裁剪）可叠加，互斥建议（降级/分层）取 max。输出标签改为"独立建议合计"而非"综合优化后成本"，并在 warnings 中明确标注互斥关系。**

### 22. Gate 审批语义必须全量消费，不能只看"空 models"

Router 返回 `requires_human_review=True` 时，`optimize` 原来只在 models 为空（escalate）时 warning。但高风险任务即使有候选模型（如 `qwen3.7-max`），降级/分层建议也需要审批才能执行。原来的逻辑会让用户误以为"既然给了建议就可以直接执行"。

**改进：escalate 检测改为所有 `requires_human_review=True` 都 warning。降级/分层建议的 `details` 标 `requires_approval=True`。区分两种 warning 文案：空 models → "无候选策略，仅供参考"；非空 models → "需经审批后方可执行"。**

### 23. Engine 层必须自己做输入校验，不能依赖 CLI

`PromptOptimizer.optimize(model_name="nonexistent")` 原来静默返回 `cost=0.0`，CLI 挡住了但 Web/API 直接调用 Engine 时会漏过。校验逻辑如果只在边界层（CLI），内层调用者永远绕得过。

**改进：Engine 层 `optimize()` 校验 `model_name` 存在性，不存在 raise ValueError。CLI 保留前置校验作为 defense-in-depth（更好的错误格式），但 Engine 是最终防线。**

### 24. CLI 参数用 Literal/Enum 做硬校验，不要用 str + 静默忽略

`--scenario BAD_SCENARIO` / `--format yaml` 原来是裸 `str`，不报错但产生误导性输出（scenario 无缓存收益、format 走 Rich 分支）。`--turns -5` 也没下限。

**改进：`scenario` 和 `output_format` 改为 `Literal[...]` 类型（Typer 自动拒绝非法值并列出可选项），`turns` 加 `turns < 1` 手动校验。参数非法时立即给出清晰错误，不要等结果出来再让用户猜。**

### 25. requires_approval 必须基于建议后的方案重新判断，不能继承 Router 原始 decision

`optimize` 原来把 `decision.requires_human_review` 直接传给降级/分层建议的 `requires_approval`。但 Router 评估的是原始推荐方案（如 Tier 1），降级建议是 Tier 2 — Gate 条件不同。结果 HIGH risk 任务降级到 Tier 2 后按 Gate 条件 2 应该审批，但 `requires_approval=False`。

**改进：新增 `_check_suggestion_approval()` 方法，对每条建议基于 suggested model/strategy/cost/quality 构建 `GateInput`，独立调用 `RoutingGate.check_human_review()`。审批判断的粒度是"建议后的方案"，不是"Router 原始推荐"。**

### 26. Engine 层参数校验必须和 CLI 对齐

CLI 用 `Literal` 挡住了非法 `scenario`/`format`，但 `PromptOptimizer.optimize(scenario="BAD")` 仍正常返回。Web/API 直接调用 Engine 时绕过了 CLI 的 `Literal` 保护。

**改进：Engine 层 `optimize()` 新增 `scenario` 白名单校验和 `expected_turns >= 1` 校验，非法值 raise ValueError。校验逻辑必须下沉到 Engine，CLI 的 `Literal` 只是 defense-in-depth。**

### 27. 测试要打到生产代码，不能手写公式代替

互斥 savings 测试手写了一遍汇总公式验证数学，没调用 `optimize()` 里的真实汇总逻辑。如果生产代码把降级+分层又加总了，这条测试不会失败。

**改进：汇总逻辑抽为 `_summarize_savings()` static method，测试直接调用生产代码。手工构造 suggestions + 固定 current_cost，验证 `total_savings == 3.5`（不是 5.5）。**

### 28. 审批信息必须浮到用户可见层，不能只存在 details 里

`requires_approval` 修好了（按建议后方案判断），但只写在 `suggestion.details` 里，CLI warnings 和 Rich 表格都不展示。用户看 CLI 输出时仍不知道这条降级建议不能直接执行。

**改进：Engine 层 `optimize()` 汇总后检查 `any(s.details.requires_approval)`，有则插入顶层 warning。Rich 表对需审批建议在类别列追加 "（需审批）" 标签。审批信息不能只藏在结构化数据里，必须在用户一眼能看到的地方展示。**

### 29. Gate 审批检查的 budget_status 必须真实计算，不能写死 OK

`_check_suggestion_approval()` 写死 `budget_status=BudgetStatus.OK`，建议后成本超硬预算时 Gate 条件 3（超硬预算需审批）不会触发。降级通常更便宜，但大上下文/多轮场景下仍可能超预算。

**改进：改用 `selector._compute_budget_status(suggested_cost, features)` 计算真实 budget_status。Gate 的每个输入字段都应该反映建议后方案的真实状态，不能假设"降级后一定不超预算"。**

### 30. Benchmark expected 值必须来自设计文档，不能校准到 Router 行为

写 benchmark case 时容易犯的错：先看 Router 输出什么，然后把 expected 写成一样的值。这样 benchmark 只能验证"Router 行为稳定"，不能验证"Router 行为正确"。

**改进：expected 值必须来自 system-design / routing_rules.yaml / gate.py 的设计语义。case fail 时按诊断顺序排查：① Router bug（代码逻辑与设计不符）→ 修代码 ② prompt 歧义（关键词命中了错误分类）→ 改 prompt 措辞 ③ expected 写错（与设计文档不符）→ 改 expected 并记录原因。**

### 31. PE/PER 策略在 Selector 评分中通常不如 SINGLE_MODEL

Plan-Execute 和 Plan-Execute-Review 虽然满足结构触发条件（COMPLEX/EXPERT + output≥500 + reasoning HIGH/VERY_HIGH + subtasks≥2），但在 Selector 多目标评分中 SINGLE_MODEL 几乎总是胜出。原因：PE 使用相同 Tier 1 模型但多了 planner 的额外成本，质量提升不足以补偿。

**改进：Benchmark case 对 PE/PER 的 expected_strategy 应反映实际 Selector 行为（SINGLE_MODEL），不强制期望 PE 胜出。PE/PER 的价值在于作为候选池中的备选方案，在 fallback 场景或特定任务类型中可能更优。未来可通过调整 strategy_quality_weights 或引入 coordination_penalty 来平衡 PE 评分。**

### 32. 关键词权重冲突导致任务分类错误

Analyzer 的 KEYWORD_RULES 中，同一个词可能出现在多个类别中（如"高并发"在 ARCHITECTURE 权重 3），导致某些 prompt 被误分类。例如"实现跨模块的高并发鉴权中间件"中"实现"给 CODE_GENERATION 3 分，"高并发"给 ARCHITECTURE 3 分，平局时 ARCHITECTURE 因字典序靠前而胜出。

**改进：写 benchmark prompt 时避免使用跨类别的高权重关键词。如需明确触发 CODE_GENERATION，去掉"高并发"（ARCHITECTURE 关键词）改用"鉴权中间件"（仅 CODE_GENERATION 关键词）。诊断时对照 KEYWORD_RULES 逐词计算分数，确认分类是否符合预期。**
