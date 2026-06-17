# AirRouter 答辩演示脚本

> 每次演示前先运行 `python demo/reset_scenarios.py` 恢复 demo 初始状态。

---

## 演示 1：路由分析（零成本）

**命令**：
```bash
ai-router analyze "写一个 FastAPI JWT 鉴权中间件"
```

**讲解要点**：
- 展示路由决策流程：任务类型、复杂度、风险等级
- ML 复杂度分析（OpenSquilla 模式）
- 模型选择理由和替代方案
- 质量门禁和降级策略

**预期输出**：Rich 面板展示路由分析结果，包含推荐模型、成本估算、节省率。

**备用方案**：如果 OpenSquilla 加载失败，会 fallback 到 rules 模式，功能不受影响。

---

## 演示 2：成本优化（零成本）

**命令**：
```bash
ai-router optimize --prompt "你是一个专业的代码审查专家，擅长发现安全漏洞和性能问题。请对以下代码进行审查，输出问题列表和修复建议。代码量约 500 行，需要同时检查 SQL 注入、XSS、CSRF 等安全问题。"
```

**讲解要点**：
- Prompt 压缩和优化策略
- Token 成本对比（优化前 vs 优化后）
- 上下文工程的三层架构（B-1 优先级 / B-2 压缩 / B-3 预算）

---

## 演示 3：Benchmark 准确率（零成本）

**命令**：
```bash
ai-router benchmark --level 1
```

**讲解要点**：
- 路由准确率、模型匹配率
- 分级评测体系（L1 规则 / L2 真实 / L3 回测）
- Ground Truth 数据集规模（1181 cases）

---

## 演示 4：Agent 执行 — SQL 注入修复

**前置**：
```bash
python demo/reset_scenarios.py
```

**Step 1 — Dry-run**：
```bash
ai-router run "修复 auth.py 中的 SQL 注入漏洞" \
  --workdir demo/scenario1-sql-inject \
  --dry-run
```

**讲解要点**：
- 任务面板 → 路由面板 → "仅分析，未执行" verdict
- ML 复杂度模式（opensquilla）
- 预估成本和节省率

**Step 2 — 真实执行**（需要 API Key）：
```bash
ai-router run "修复 auth.py 中的 SQL 注入漏洞" \
  --workdir demo/scenario1-sql-inject \
  --yes
```

**讲解要点**：
- Agent 自主探索项目结构（ls/read_file）
- 定位漏洞（read_file 找到 SQL 拼接）
- 精确修复（edit_file 替换为参数化查询）
- 验证修复（pytest 全部通过）
- 成本报告和节省率

**备用方案**：如果 API 不可用，展示 dry-run 输出 + 预录的执行结果截图。

---

## 演示 5：智能路由决策 — 为什么不用 Plan-Execute

**前置**：
```bash
python demo/reset_scenarios.py
```

**Step 1 — 查看路由分析**：
```bash
ai-router analyze "重构用户认证模块，将登录和鉴权逻辑拆分为独立的中间件，以及实现 Token 刷新机制"
```

**讲解要点**：
- OpenSquilla 判断为 EXPERT 复杂度
- Classifier 识别 PE/PER 作为合格候选（alternatives 可见）
- Selector 评估成本-质量后选择 SINGLE_MODEL（deepseek-v4-pro）
- **这正是系统的智能之处**：不是死板套方案，而是根据实际成本-质量评分做最优选择
- 当 Tier 1 模型性价比足够高时，单模型反而优于 Planner+Executor 组合

**Step 2 — Dry-run 确认**：
```bash
ai-router run "重构用户认证模块，将登录和鉴权逻辑拆分为独立的中间件，以及实现 Token 刷新机制" \
  --workdir demo/scenario4-refactor-auth \
  --dry-run
```

**讲解要点**：
- OpenSquilla ML 复杂度分析（EXPERT / R3）
- 路由面板显示 PE/PER 在 alternatives 中
- 最终选择 SINGLE_MODEL + deepseek-v4-pro
- 成本报告中显示预估成本和基线对比

**Step 3 — 真实执行**（可选，需要 API Key）：
```bash
ai-router run "重构用户认证模块，将登录和鉴权逻辑拆分为独立的中间件，以及实现 Token 刷新机制" \
  --workdir demo/scenario4-refactor-auth \
  --yes
```

**讲解要点**：
- 单模型 Agent 自主完成跨模块重构
- 工具调用链：探索 → 读取 → 修改 → 验证
- 成本报告：实际成本 vs Tier 1 基线

**Q&A 准备**：
- "Plan-Execute 什么时候会被选中？" — 当 Tier 1 模型更贵、任务更复杂、PE 组合能省 >15% 成本时
- "PER 实现了吗？" — 已实现，reviewer 阶段、成本追踪、审查解析都已编码并测试通过

---

## 演示 6：Web 平台（可选）

```bash
streamlit run web/app.py
```

**讲解要点**：
- Chat 工作台：输入任务 → 路由分析 → 执行
- 消费仪表盘：Token 消耗趋势、模型使用分布
- 优化中心：Prompt 优化建议
- Benchmark 结果页：准确率趋势、失败案例分析
- 治理配置页：规则管理、安全策略

---

## 演示注意事项

1. **sklearn warning**：OpenSquilla 加载时会有 InconsistentVersionWarning，功能不受影响。答辩时可用 `.venv` 消除。
2. **API 成本**：演示 4/5 真实执行会消耗 API 额度（约 ¥0.01-0.05/次）。建议先用 dry-run，确认可演示后再真实执行。
3. **Demo 恢复**：每次真实执行后运行 `python demo/reset_scenarios.py` 恢复初始状态。
4. **网络要求**：演示 4/5 需要网络访问模型 API。离线环境只展示演示 1-3。
