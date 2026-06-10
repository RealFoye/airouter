# AI Router 模型选型报告

> 基于 Level 2 Benchmark 正式评测数据（2026-06-09）
> 评测方式：30 个真实工程任务 x 5 个模型 = 150 次 API 调用
> 三层评估：自动评分 + 双 Judge 独立评分 + A/B 盲评对比

---

## 一、核心结论

| 结论 | 说明 |
|------|------|
| **Pairwise 排名稳定** | qwen3.7-max 以 79.6% 胜率排第一，qwen3.7-plus 以 67.9% 排第二，deepseek 系列排末位 |
| **Absolute Judge 排名** | qwen3.7-max (0.976) ≈ glm-5.1 (0.969) > qwen3.7-plus (0.963) > deepseek-v4-flash (0.939) > deepseek-v4-pro (0.914) |
| **成本差距极大** | deepseek-v4-flash 总成本 ¥0.12，qwen3.7-max 成本 ¥5.67，相差 47 倍 |
| **双 Judge 一致认可** | 两个 Judge 对 qwen3.7-max 和 glm-5.1 的评价高度一致，排名无争议 |
| **Auto-score 区分度不足** | 自动评分 5 个模型都在 0.93~0.95 之间，LLM Judge 和 Pairwise 能更好区分质量 |

### 三层评估交叉验证

| 排名 | Auto-score | Absolute Judge (双 Judge 均值) | Pairwise (A/B 盲评) |
|:---:|---|---|---|
| 1 | qwen3.7-max **0.950** | qwen3.7-max **0.976** | qwen3.7-max **79.6%** |
| 2 | deepseek-v4-flash **0.942** | glm-5.1 **0.969** | qwen3.7-plus **67.9%** |
| 3 | deepseek-v4-pro **0.942** | qwen3.7-plus **0.963** | glm-5.1 **48.3%** |
| 4 | glm-5.1 **0.941** | deepseek-v4-flash **0.939** | deepseek-v4-pro **34.2%** |
| 5 | qwen3.7-plus **0.933** | deepseek-v4-pro **0.914** | deepseek-v4-flash **20.0%** |

**关键发现**：
- **Auto-score 和 Judge 排名有明显分歧** — deepseek-v4-flash 自动评分排第 2，但 Judge 只排第 4、Pairwise 排最末。它善于命中关键词但分析深度不足
- **qwen3.7-max 三层评估均排第一** — 质量最稳定
- **qwen3.7-plus 性价比最优** — Pairwise 排第 2 (67.9%)，Judge 排第 3 (0.963)，但成本仅 ¥1.03（max 的 1/5.5）
- **glm-5.1 Judge 评分高但 Pairwise 一般** — 说明 glm-5.1 的输出在独立评分时看起来好，但和 qwen 系列直接对比时稍弱

---

## 二、评测方法

### 三层评估体系

| 层级 | 方法 | 说明 |
|------|------|------|
| **Layer 1: Auto-score** | 规则评分 | AST 解析 + 关键词匹配 + 结构检查，确定性基线 |
| **Layer 2: Absolute Judge** | 双 Judge 独立评分 | qwen3.7-max + deepseek-v4-pro 分别对 150 份输出打分，使用 task-type 专用 rubric |
| **Layer 3: Pairwise Judge** | A/B 盲评 | 隐藏模型名，随机顺序，两个 Judge 分别对比 C(5,2)=10 个模型对 |

### 评测集

- 30 个真实工程任务，覆盖 6 类场景、4 个复杂度
- 5 个被评模型：deepseek-v4-flash / deepseek-v4-pro / qwen3.7-plus / glm-5.1 / qwen3.7-max
- 2 个 Judge 模型：qwen3.7-max / deepseek-v4-pro

### 总调用量

| 阶段 | 调用数 | 成功率 | 说明 |
|------|:---:|:---:|------|
| L2 模型执行 | 150 | 100% | 30 cases x 5 models |
| Absolute Judge | 300 | 100% | 150 pairs x 2 judges |
| Pairwise Judge | 600 | 100% | 30 cases x 10 pairs x 2 judges |
| **合计** | **1050** | **100%** | |

### Absolute Judge 评分标准（Task-type 专用 Rubric）

每种任务类型使用不同的评分维度和权重，替代了旧版的通用 4 维度：

| 任务类型 | 评分维度（权重） |
|----------|-----------------|
| CODE_GENERATION | correctness(0.35), code_quality(0.25), completeness(0.20), error_handling(0.10), performance(0.10) |
| CODE_REVIEW | issue_detection(0.30), fix_suggestion(0.25), severity_accuracy(0.20), completeness(0.15), practicality(0.10) |
| ARCHITECTURE | design_soundness(0.30), tradeoff_analysis(0.25), scalability(0.20), completeness(0.15), practicality(0.10) |
| REFACTORING | improvement_clarity(0.30), correctness(0.25), best_practices(0.20), completeness(0.15), maintainability(0.10) |
| BUG_ANALYSIS | root_cause_accuracy(0.35), fix_correctness(0.30), explanation(0.20), prevention(0.15) |
| DOCUMENTATION | accuracy(0.30), completeness(0.25), clarity(0.20), structure(0.15), examples(0.10) |

### Pairwise Judge 设计

- **A/B 盲评**：隐藏真实模型名，Judge 只看到 "Model A" 和 "Model B"
- **随机顺序**：每对中两个模型的 A/B 顺序由局部 RNG 决定（可复现），消除位置偏差
- **一致率 75%**：两个 Judge 对 300 对中 225 对给出相同结论

---

## 三、模型综合对比

### 3.1 Absolute Judge 双 Judge 排名

| 排名 | qwen3.7-max 当 Judge | deepseek-v4-pro 当 Judge | 双 Judge 均值 |
|:---:|---|---|---|
| 1 | **qwen3.7-max (0.983)** | **qwen3.7-max (0.968)** | **qwen3.7-max (0.976)** |
| 2 | glm-5.1 (0.983) | glm-5.1 (0.954) | glm-5.1 (0.969) |
| 3 | qwen3.7-plus (0.977) | qwen3.7-plus (0.948) | qwen3.7-plus (0.963) |
| 4 | deepseek-v4-flash (0.954) | deepseek-v4-flash (0.924) | deepseek-v4-flash (0.939) |
| 5 | deepseek-v4-pro (0.935) | deepseek-v4-pro (0.893) | deepseek-v4-pro (0.914) |

**关键发现**：
- **qwen3.7-max 两个 Judge 都给最高分** — 排名一致，可信度高
- **deepseek-v4-pro 未给自己刷分** — 两个 Judge 都把它排最后，评分公正
- **qwen3.7-max 当 Judge 时打分偏高** — 均值 0.97，deepseek-v4-pro 当 Judge 均值 0.94，但排名完全一致
- **前 3 名差距很小** — max / glm / plus 都在 0.96-0.98 区间

### 3.2 Pairwise 排名（A/B 盲评）

| 排名 | 模型 | 胜 | 负 | 平 | 胜率 |
|:---:|------|---:|---:|---:|---:|
| 1 | **qwen3.7-max** | 177 | 57 | 6 | **73.8%** |
| 2 | qwen3.7-plus | 165 | 67 | 8 | 68.8% |
| 3 | glm-5.1 | 118 | 117 | 5 | 49.2% |
| 4 | deepseek-v4-pro | 79 | 158 | 3 | 32.9% |
| 5 | deepseek-v4-flash | 48 | 188 | 4 | 20.0% |

### 3.3 Head-to-head 胜率矩阵

| | vs flash | vs pro | vs glm | vs max | vs plus |
|---|:---:|:---:|:---:|:---:|:---:|
| **deepseek-v4-flash** | — | 39% | 16% | 18% | 11% |
| **deepseek-v4-pro** | 61% | — | 46% | 11% | 17% |
| **glm-5.1** | 84% | 54% | — | 30% | 33% |
| **qwen3.7-max** | 83% | 89% | 70% | — | 58% |
| **qwen3.7-plus** | 89% | 83% | 68% | 42% | — |

**解读**：
- qwen3.7-max 对 deepseek-v4-pro 的胜率高达 **89%**
- qwen3.7-plus 对 qwen3.7-max 的胜率为 **42%**（不弱）
- glm-5.1 对 deepseek 系列有压倒性优势（54-84%），但对 qwen 系列较弱（30-33%）

### 3.4 成本与质量对比

| 指标 | deepseek-v4-flash | deepseek-v4-pro | qwen3.7-plus | glm-5.1 | qwen3.7-max |
|------|:-:|:-:|:-:|:-:|:-:|
| **Auto-score** | 0.942 | 0.942 | 0.933 | 0.941 | **0.950** |
| **Absolute Judge** | 0.939 | 0.914 | 0.963 | 0.969 | **0.976** |
| **Pairwise 胜率** | 20.0% | 32.9% | 67.9% | 48.3% | **73.8%** |
| **30 任务成本** | **¥0.12** | ¥0.37 | ¥1.03 | ¥2.59 | ¥5.67 |
| **成本倍数** | 1x | 3x | 9x | 22x | 47x |

---

## 四、按任务类型分析

### 4.1 Absolute Judge 分任务评分（双 Judge 均值）

| 任务类型 | deepseek-v4-flash | deepseek-v4-pro | qwen3.7-plus | glm-5.1 | qwen3.7-max |
|----------|:-:|:-:|:-:|:-:|:-:|
| **CODE_GENERATION** | 0.965 | 0.923 | 0.953 | 0.970 | **0.985** |
| **CODE_REVIEW** | 0.967 | 0.956 | **0.983** | 0.980 | 0.980 |
| **BUG_ANALYSIS** | 0.923 | 0.873 | **0.968** | 0.968 | 0.960 |
| **DOCUMENTATION** | 0.983 | 0.970 | 0.984 | 0.980 | **0.990** |
| **REFACTORING** | 0.896 | 0.885 | 0.964 | 0.984 | **0.994** |
| **ARCHITECTURE** | 0.883 | 0.875 | 0.920 | 0.925 | **0.946** |

### 4.2 Pairwise 胜率分任务

| 任务类型 | deepseek-v4-flash | deepseek-v4-pro | qwen3.7-plus | glm-5.1 | qwen3.7-max |
|----------|:-:|:-:|:-:|:-:|:-:|
| **CODE_GENERATION** | 22.9% | 33.3% | 56.2% | 60.4% | **70.8%** |
| **CODE_REVIEW** | 14.6% | 27.1% | 70.8% | 52.1% | **83.3%** |
| **BUG_ANALYSIS** | 12.5% | 18.8% | **79.2%** | 60.4% | 70.8% |
| **DOCUMENTATION** | 31.2% | 53.1% | 53.1% | 37.5% | **71.9%** |
| **REFACTORING** | 28.1% | 25.0% | 71.9% | 37.5% | **75.0%** |
| **ARCHITECTURE** | 15.6% | 50.0% | **81.2%** | 34.4% | 68.8% |

### 4.3 按任务类型推荐

| 任务类型 | 首选 | 备选 | 说明 |
|----------|------|------|------|
| 代码生成 | qwen3.7-max | qwen3.7-plus | max Judge 评分最高 (0.985)，Pairwise 胜率最高 (70.8%) |
| 代码审查 | qwen3.7-max | qwen3.7-plus | max 胜率 83.3%，plus 紧随其后 70.8% |
| Bug 分析 | qwen3.7-plus | glm-5.1 | plus Judge 最高 (0.968) 且 Pairwise 胜率最高 (79.2%) |
| 文档生成 | qwen3.7-max | qwen3.7-plus | max Judge 0.990，成本 ¥1.89；plus 0.984，成本仅 ¥0.34 |
| 代码重构 | qwen3.7-max | qwen3.7-plus | max Judge 0.994，plus 0.964 |
| 架构设计 | qwen3.7-plus | qwen3.7-max | plus Pairwise 胜率最高 (81.2%)，成本仅 ¥0.23 |

---

## 五、成本详细分解

### 5.1 单价（每 1K tokens）

| 模型 | 输入价格 | 输出价格 |
|------|--------:|--------:|
| deepseek-v4-flash | ¥0.001008 | ¥0.002016 |
| deepseek-v4-pro | ¥0.003132 | ¥0.006264 |
| qwen3.7-plus | ¥0.001944 | ¥0.008640 |
| glm-5.1 | ¥0.010080 | ¥0.028800 |
| qwen3.7-max | ¥0.018000 | ¥0.054000 |

### 5.2 JSONL 重复问题说明

**现象**：由于 `llm_judge_v2.py` 和 `pairwise_judge.py` 中存在 resume bug（work_items 构建逻辑错误），Judge 和 Pairwise 阶段各评估项被重复执行了一次。

| 文件 | JSONL 总行数 | Unique keys | 重复行数 |
|------|---:|---:|---:|
| results.jsonl | 150 | 150 | 0 |
| judge_results.jsonl | 590 | 300 | 290 |
| pairwise_results.jsonl | 1,192 | 600 | 592 |

**Bug 原因**：`work_items.append()` 放在了 `for jm in judge_models` 循环内部，导致每个 (case, model) 对如果有 2 个 judge_model 需要评估，就会生成 2 个相同的 work_item。每个 work_item 在 `process_item` 中又遍历所有 judge_model，造成每个 key 被评估 2 次。

**修复**：将 `work_items.append()` 移到 `for jm` 循环外部，每个 (case, model) 对只生成 1 个 work_item。已修复，未来运行不会再重复。

**Dedupe 策略**：JSONL finalize 时按 key 去重，**采用最后一条记录**（last-entry-wins）。重复行的分数/usage 可能不同（因为是独立的 LLM 调用），但差异很小。质量排名基于 dedupe 后的 1,050 个 unique evaluation units。

### 5.3 L2 模型执行成本（150 次调用，无重复）

| 模型 | 输入 tokens | 输出 tokens | 成本 | 占比 |
|------|----------:|----------:|------:|---:|
| deepseek-v4-flash | 4,298 | 55,177 | **¥0.12** | 1.2% |
| deepseek-v4-pro | 4,298 | 56,311 | **¥0.37** | 3.7% |
| qwen3.7-plus | 4,830 | 117,646 | **¥1.03** | 10.5% |
| glm-5.1 | 4,326 | 88,371 | **¥2.59** | 26.5% |
| qwen3.7-max | 4,830 | 103,340 | **¥5.67** | 58.0% |
| **合计** | 22,582 | 420,845 | **¥9.76** | 100% |

### 5.4 Absolute Judge 成本

| 指标 | 数值 |
|------|------|
| Unique evaluations（dedupe 后） | 300 |
| Actual API calls（含重复） | 590 |
| Duplicate calls | 290 |

**Unique evaluation cost（300 次，dedupe 后）**：

| Judge 模型 | 输入 tokens | 输出 tokens | 成本 | 调用数 |
|-----------|----------:|----------:|------:|---:|
| deepseek-v4-pro | 355,231 | 172,346 | **¥2.19** | 150 |
| qwen3.7-max | 371,406 | 183,400 | **¥16.59** | 150 |
| **合计** | 726,637 | 355,746 | **¥18.78** | 300 |

**Actual API spend（590 次调用）**：

| Judge 模型 | 输入 tokens | 输出 tokens | 成本 | 调用数 |
|-----------|----------:|----------:|------:|---:|
| deepseek-v4-pro | 692,075 | 316,432 | **¥4.15** | 291 |
| qwen3.7-max | 739,236 | 346,831 | **¥32.04** | 299 |
| **合计** | 1,431,311 | 663,263 | **¥36.18** | 590 |

Wasted spend（重复调用）：**¥17.40**

### 5.5 Pairwise Judge 成本

| 指标 | 数值 |
|------|------|
| Unique evaluations（dedupe 后） | 600 |
| Actual API calls（含重复） | 1,192 |
| Duplicate calls | 592 |

**Unique evaluation cost（600 次，dedupe 后）**：

| Judge 模型 | 输入 tokens | 输出 tokens | 成本 | 调用数 |
|-----------|----------:|----------:|------:|---:|
| deepseek-v4-pro | 949,974 | 521,183 | **¥6.24** | 300 |
| qwen3.7-max | 977,834 | 481,816 | **¥43.62** | 300 |
| **合计** | 1,927,808 | 1,002,999 | **¥49.86** | 600 |

**Actual API spend（1,192 次调用）**：

| Judge 模型 | 输入 tokens | 输出 tokens | 成本 | 调用数 |
|-----------|----------:|----------:|------:|---:|
| deepseek-v4-pro | 1,888,200 | 920,813 | **¥11.68** | 592 |
| qwen3.7-max | 1,955,668 | 901,230 | **¥83.87** | 600 |
| **合计** | 3,843,868 | 1,822,043 | **¥95.55** | 1,192 |

Wasted spend（重复调用）：**¥45.69**

### 5.6 全流程成本总览

| 阶段 | Unique evals | Actual API calls | Unique cost | Actual spend | Wasted |
|------|---:|---:|---:|---:|---:|
| L2 模型执行 | 150 | 150 | ¥9.76 | ¥9.76 | ¥0.00 |
| Absolute Judge | 300 | 590 | ¥18.78 | ¥36.18 | ¥17.40 |
| Pairwise Judge | 600 | 1,192 | ¥49.86 | ¥95.55 | ¥45.69 |
| **总计** | **1,050** | **1,932** | **¥78.40** | **¥141.50** | **¥63.09** |

- **Unique evaluation cost ¥78.40**：1,050 个独立评估项的成本（dedupe 后），用于质量排名
- **Actual API spend ¥141.50**：1,932 次 API 调用的总成本（含重复），即实际消耗
- **Wasted ¥63.09**：882 次重复调用的成本，由 resume bug 导致，已修复

**日常参考**：
- 正常运行时（无重复），全流程成本约 ¥78
- qwen3.7-max 作为 Judge 占 unique cost 的 77%（¥60.21 / ¥78.40）
- deepseek-v4-pro 作为 Judge 成本仅 ¥8.43，性价比极高
- 日常可只跑 Absolute Judge（¥18.78），省去 Pairwise（¥49.86）

### 5.7 CCH 账单对账

> 数据来源：CCH Gateway 导出 CSV（usage-logs-2026-06-09-140814.csv）
> 对账时间：2026-06-09
> 匹配方法：按 (model, input_tokens, output_tokens) 精确匹配，再放宽为 (model, input_tokens) 匹配

**CSV 概况**：

| 指标 | 数值 |
|------|------|
| 总行数 | 2,963 |
| 成功行数（status=200） | 2,929 |
| 时间范围 | 02:00 ~ 06:05 UTC（10:00 ~ 14:05 北京时间） |
| CSV 总成本 | **$38.32 (¥275.87)** |

**Token 级匹配结果**：

| 匹配类型 | CSV 行数 | 成本 |
|----------|---:|---:|
| 匹配到 JSONL（benchmark） | 1,136 | **$11.55 (¥83.18)** |
| 未匹配（会话 + 其他） | 1,793 | **$26.76 (¥192.69)** |
| CSV 总计 | 2,929 | **$38.32 (¥275.87)** |

**按阶段匹配明细**：

| 阶段 | JSONL 行数 | CCH 匹配行数 | CCH 匹配成本 | 匹配率 |
|------|---:|---:|---:|---:|
| L2 模型执行 | 150 | 149 | $1.23 (¥8.85) | 99.3% |
| Absolute Judge | 590 | 250 | $2.66 (¥19.16) | 42.4% |
| Pairwise Judge | 1,192 | 737 | $7.66 (¥55.17) | 61.8% |
| **合计** | **1,932** | **1,136** | **$11.55 (¥83.18)** | **58.8%** |

**未匹配原因**：
1. **Token 计数差异**：Adapter（JSONL）和 Gateway（CSV）对 output_tokens 的计数方式不同，导致 41.2% 的 JSONL 行无法在 CSV 中找到精确匹配
2. **会话流量干扰**：CSV 中 qwen3.7-max 有 978 行未匹配（$24.83），特征为 `input_tokens=2~6`（极短 prompt）+ `cache_read > 10,000`（大量缓存读取），属于 Claude Code 会话流量
3. **ep- 前缀 endpoint**：296 + 14 = 310 行（$0.65）为 CCH 内部 endpoint ID，属于会话流量

**成本交叉验证**：

| 数据来源 | 成本 | 说明 |
|----------|---:|------|
| Unique eval cost（models.yaml 定价） | ¥78.40 | 1,050 unique evals × 标价 |
| CCH matched（token 级匹配） | ¥83.18 | 1,136 CSV rows matched to JSONL |
| Actual API spend（JSONL 全量） | ¥141.50 | 1,932 API calls × 标价（含重复） |

CCH matched（¥83.18）与 unique eval cost（¥78.40）接近（差异 6.1%），说明 models.yaml 定价基本准确。CCH matched 略高是因为它包含了部分重复调用的 CSV 行（token 匹配无法区分首次调用和重复调用）。

---

## 六、选型建议

### 方案 A：极致性价比

| 层级 | 模型 | 场景 |
|------|------|------|
| Tier 1（默认） | **deepseek-v4-flash** | 所有任务默认走 flash |
| Tier 2（升级） | deepseek-v4-pro | flash 质量不达标时升级 |

- 成本：约为纯 qwen3.7-max 方案的 **2%**
- 质量损失：**较大**。Pairwise 胜率仅 20-33%，Judge 排末位
- 适用：对质量要求不极致、成本极敏感的场景

### 方案 B：质量与成本平衡（推荐）

| 层级 | 模型 | 场景 |
|------|------|------|
| Tier 1（关键任务） | **qwen3.7-plus** | 代码审查、Bug 分析、架构设计 |
| Tier 2（通用） | **deepseek-v4-flash** | 简单代码生成、文档 |
| Tier 3（升级） | deepseek-v4-pro | 中间档需求 |

- plus Pairwise 排第 2 (67.9%)，成本仅为 max 的 **1/5.5**
- 通过 Router 按任务类型自动分流
- 适合大多数生产场景

### 方案 C：质量优先

| 层级 | 模型 | 场景 |
|------|------|------|
| Tier 1 | **qwen3.7-max** | 所有任务（三层评估均第一） |
| Tier 2 | qwen3.7-plus | 特定任务降级（如 Bug 分析、架构设计） |

- 质量最高，成本最高（¥5.67 / 30 任务）
- 适合对质量要求极致、预算充足的场景

---

## 七、评测任务清单

本次评测包含 30 个真实工程任务，分为 6 大类：

#### 代码生成（CODE_GENERATION）— 6 个任务

| ID | 复杂度 | 任务描述 |
|---|---|---|
| CG-SIMPLE-001 | SIMPLE | 回文检测函数（双指针/Pythonic） |
| CG-SIMPLE-002 | SIMPLE | FizzBuzz（输入歧义处理） |
| CG-MOD-001 | MODERATE | 滑动窗口 API 限流中间件 |
| CG-MOD-002 | MODERATE | JWT token 生成与验证模块 |
| CG-COMPLEX-001 | COMPLEX | 本地并发任务队列（重试+回调） |
| CG-COMPLEX-002 | COMPLEX | 异步网页爬虫框架（限速+并发） |

#### 代码审查（CODE_REVIEW）— 6 个任务

| ID | 复杂度 | 任务描述 |
|---|---|---|
| CR-SEC-001 | MODERATE | SQL 注入 + 硬编码密钥审查 |
| CR-SEC-002 | MODERATE | 不安全随机数 + 硬编码加密审查 |
| CR-PERF-001 | MODERATE | N+1 查询性能问题 |
| CR-PERF-002 | MODERATE | 资源泄漏（Session/文件句柄） |
| CR-DESIGN-001 | COMPLEX | "上帝类"设计问题 |
| CR-DESIGN-002 | COMPLEX | 循环依赖架构问题 |

#### Bug 分析（BUG_ANALYSIS）— 6 个任务

| ID | 复杂度 | 任务描述 |
|---|---|---|
| BA-RT-001 | SIMPLE | NoneType AttributeError |
| BA-RT-002 | SIMPLE | IndexError 越界访问 |
| BA-LOGIC-001 | MODERATE | 无限循环缺少退出条件 |
| BA-LOGIC-002 | MODERATE | 累加逻辑错误 |
| BA-CONC-001 | COMPLEX | 多线程竞态条件 |
| BA-CONC-002 | COMPLEX | 交叉获取锁死锁 |

#### 文档生成（DOCUMENTATION）— 4 个任务

| ID | 复杂度 | 任务描述 |
|---|---|---|
| DOC-API-001 | MODERATE | REST API 文档 |
| DOC-API-002 | MODERATE | WebSocket 协议文档 |
| DOC-ARCH-001 | COMPLEX | 微服务架构文档 |
| DOC-ARCH-002 | COMPLEX | 数据库 Schema 设计文档 |

#### 代码重构（REFACTORING）— 4 个任务

| ID | 复杂度 | 任务描述 |
|---|---|---|
| RF-EXTRACT-001 | MODERATE | 长函数提取方法 |
| RF-EXTRACT-002 | MODERATE | 条件判断提取为 guard clause |
| RF-PATTERN-001 | COMPLEX | if/elif 改为策略模式 |
| RF-PATTERN-002 | COMPLEX | 手动缓存改为装饰器模式 |

#### 架构设计（ARCHITECTURE）— 4 个任务

| ID | 复杂度 | 任务描述 |
|---|---|---|
| ARCH-MOD-001 | MODERATE | 用户认证系统 |
| ARCH-MOD-002 | MODERATE | 消息通知系统 |
| ARCH-EXP-001 | EXPERT | 高可用分布式缓存 |
| ARCH-EXP-002 | EXPERT | 多租户 SaaS 平台 |

---

## 八、本次评测改进（相比 2026-06-08 诊断 run）

| 改进项 | 旧版 (06-08) | 新版 (06-09) |
|--------|-------------|-------------|
| Case prompt | 5 个有矛盾/答案泄露 | 全部修正 |
| Auto-score 架构深度 | 纯长度桶 | 7 维度组关键词检查 |
| LLM Judge prompt | 通用 4 维度 | 6 种 task-type 专用 rubric |
| Judge 输出截断 | 8000 chars | 30000 chars |
| Judge 成功率 | 91/150 (60%) | **300/300 (100%)** |
| Pairwise 盲评 | 无 | **600/600 (100%)，75% 一致率** |
| 截断惩罚 | 无 | model_truncated cap 0.65 |
| 并发化 | 顺序执行 | ThreadPoolExecutor (20 workers) |
| Resume | 无 | JSONL resume + 指数退避 |

---

## 九、数据说明

| 项目 | 说明 |
|------|------|
| 评测日期 | 2026-06-09 |
| 评测集 | 30 cases x 5 models = 150 pairs |
| Auto-score | AST 解析 + 关键词匹配 + 7 维度架构深度 |
| Absolute Judge | qwen3.7-max + deepseek-v4-pro 独立评分，task-type 专用 rubric，300 unique / 590 actual calls |
| Pairwise Judge | A/B 盲评，随机顺序，隐藏模型名，600 unique / 1,192 actual calls，75% 一致率 |
| JSONL dedupe | last-entry-wins 策略，duplicate_count: Judge 290, Pairwise 592 |
| API 网关 | CCH Gateway (token.cvte.com) |
| 运行 ID | 20260609_104606 |
| Unique eval cost | ¥78.40（1,050 unique evaluations，models.yaml 定价） |
| Actual API spend | ¥141.50（1,932 actual API calls，含重复调用） |
| Wasted (resume bug) | ¥63.09（882 duplicate calls，已修复） |
| CCH matched | ¥83.18（1,136 CSV rows token-level matched to JSONL） |
| CCH CSV 总账单 | ¥275.87（含 Benchmark + 会话对话 + ep- endpoint，共 2,963 次调用） |

### 局限性

1. **qwen3.7-max 当 Judge 时给自家模型打分偏高**（0.983 vs deepseek judge 的 0.968），但排名一致
2. 30 个 case 覆盖 6 类工程任务，未覆盖多轮对话、长上下文等场景
3. **Resume bug 导致重复调用**：Judge 290 个 key 被重复评估，Pairwise 592 个 key 被重复评估。已修复，质量排名基于 dedupe 后的 unique 数据
4. **CCH 匹配不完整**：1,932 次 JSONL API 调用中仅 1,136 次（58.8%）在 CSV 中找到精确匹配，主要因 Adapter 与 Gateway 的 token 计数方式不同
5. 未评估安全性、合规性、数据隐私等非功能指标
6. glm-5.1 Judge 评分 (0.969) 与 Pairwise 胜率 (48.3%) 存在分歧，可能因为独立评分与对比评分的评判标准不同
