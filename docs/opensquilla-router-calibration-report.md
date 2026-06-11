# OpenSquilla Router 校准报告

> 本文档记录 ML 复杂度路由在标准测试集上的校准结果。
> 运行方式：`python scripts/calibration_report.py --with-ml --output docs/calibration_data.json`

## 测试集

| 来源 | 用例数 | 说明 |
|------|--------|------|
| Level 1 (L1) | 40 | 离线规则基准用例 |
| Engineering (ENG) | 30 | IT/工程场景合成用例 |
| **总计** | **70** | |

### 复杂度分布

| 复杂度 | L1 | ENG | 总计 |
|--------|----|-----|------|
| SIMPLE | 15 | 7 | 22 |
| MODERATE | 11 | 17 | 28 |
| COMPLEX | 10 | 6 | 16 |
| EXPERT | 4 | 0 | 4 |

## Rules 基线结果

> 以下结果无需 ML 依赖即可复现。

| 指标 | 值 |
|------|-----|
| Accuracy | 68.6% |
| Under-routing | 20 (28.6%) |
| Severe under-routing | 3 (4.3%) |
| Over-routing | 2 (2.9%) |
| High-risk under-routing | 9/32 (28.1%) |
| Tier 1 rate | 5.7% (4 cases) |
| Estimated cost | ¥1.3325 * |

> *成本基于 models.yaml 中各 Tier 平均输出价格 × 2000 output tokens 估算，为代理成本，不是实际账单金额。

### Rules 混淆矩阵

| Expected \ Predicted | SIMPLE | MODERATE | COMPLEX | EXPERT |
|---------------------|--------|----------|---------|--------|
| SIMPLE | 21 | 0 | 1 | 0 |
| MODERATE | 16 | 11 | 1 | 0 |
| COMPLEX | 3 | 1 | 12 | 0 |
| EXPERT | 0 | 0 | 0 | 4 |

**关键发现**：规则系统将大量 MODERATE 任务（16/28 = 57%）错误分类为 SIMPLE，这是 ML 集成需要解决的核心问题。

## ML 模式结果

> 环境：`.venv` (Python 3.12, lightgbm 4.6.0, onnxruntime 1.24.4)
> Bundle：commit `5409a22`, cold start 1064ms, warm ~8ms/case
> ML 成功率：70/70 (100%)

### ml_raw（OpenSquilla argmax）

| 指标 | 值 | vs rules |
|------|-----|----------|
| Accuracy | 45.7% | -22.9pp |
| Under-routing | 15 (21.4%) | -5 |
| Severe under-routing | 2 (2.9%) | -1 |
| Over-routing | 23 (32.9%) | +21 |
| High-risk under-routing | 5/32 (15.6%) | -4 |
| Tier 1 rate | 30.0% (21) | +17 |

### ml_final（OpenSquilla postprocess）

| 指标 | 值 | vs rules |
|------|-----|----------|
| Accuracy | 45.7% | -22.9pp |
| Under-routing | 7 (10.0%) | -13 |
| Severe under-routing | 1 (1.4%) | -2 |
| Over-routing | 31 (44.3%) | +29 |
| High-risk under-routing | 1/32 (3.1%) | -8 |
| Tier 1 rate | 32.9% (23) | +19 |

### hybrid（max_steps=1, conf>=0.50）

| 指标 | 值 | vs rules |
|------|-----|----------|
| Accuracy | 64.3% | -4.3pp |
| Under-routing | 12 (17.1%) | -8 |
| Severe under-routing | 2 (2.9%) | -1 |
| Over-routing | 13 (18.6%) | +11 |
| High-risk under-routing | 7/32 (21.9%) | -2 |
| Tier 1 rate | 15.7% (11) | +7 |

## 验收标准

| 标准 | 阈值 | 结果 | 状态 |
|------|------|------|------|
| ML 成功率 | 70/70 | 70/70 | PASS |
| hybrid severe under-routing | <= rules (3) | 2 | PASS |
| hybrid high-risk under-routing | <= rules (9) | 7 | PASS |
| hybrid accuracy | >= rules - 5pp (63.6%) | 64.3% | PASS |
| 报告 Tier 1 推荐率和成本变化 | 必须 | 已报告 | PASS |

## 结论

### OpenSquilla 是否提升路由效果？

**是，但效果集中在减少欠路由，而非提高准确率。**

1. **Hybrid 模式有效减少了危险欠路由**：under-routing 从 28.6% 降至 17.1%（-11.5pp），severe under-routing 从 4.3% 降至 2.9%。高风险任务欠路由从 28.1% 降至 21.9%。

2. **代价是更高的成本和 over-routing**：hybrid 的 Tier 1 推荐率从 5.7% 升至 15.7%，代理成本增加 ¥0.73（+54.8%）。这是用成本换安全的策略。

3. **ML 原始输出倾向于高分类**：ml_raw/ml_final 的 over-routing 率分别为 32.9% 和 44.3%。OpenSquilla 的 R0-R3 分类器对 AirRouter 的 SIMPLE/MODERATE/COMPLEX/EXPERT 映射偏保守（倾向向上分类）。Hybrid 的"只升不降"策略有效限制了这种偏移。

4. **准确率下降在可接受范围**：hybrid accuracy 64.3% vs rules 68.6%（-4.3pp），在 ±5pp 阈值内。

### 建议

- **可进入 shadow 模式试运行**：记录 ML 诊断数据但不影响路由决策
- **如需上线 hybrid**：建议先在非关键路径小流量验证，观察实际成本变化
- **max_upgrade_steps=2 可能进一步减少 severe under-routing**，但需重新校准成本影响
- **长期**：OpenSquilla 的分类边界与 AirRouter 的规则边界存在系统性差异，需要针对 AirRouter 场景做微调或重新训练
