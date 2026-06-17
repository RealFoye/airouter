# Scenario 4: 认证模块重构

## 场景说明

用户认证模块（`auth.py`）和中间件（`middleware.py`）职责混乱，需要拆分为独立的模块。

## 任务描述

```
重构用户认证模块，将登录和鉴权逻辑拆分为独立的中间件，以及实现 Token 刷新机制
```

此任务描述被 OpenSquilla 判断为 EXPERT 复杂度。Classifier 会生成 PE/PER 候选策略，
但 Selector 基于成本-质量评分后选择 SINGLE_MODEL（deepseek-v4-pro），因为当前 Tier 1 模型性价比高，
单模型执行比 Planner+Executor 组合更优。

**这正是系统的智能之处**：Router 不是死板套方案，而是根据实际成本-质量做最优选择。

## 初始状态

- `src/auth.py`: 登录、token 检查、权限管理混在一个文件
- `src/middleware.py`: 硬编码依赖 auth.check_token
- `src/models.py`: User dataclass（不需要修改）

## 成功标准

1. `src/middleware.py` 包含独立的 `AuthMiddleware` 类
2. `src/auth.py` 不再包含中间件逻辑
3. `pytest tests/` 全部通过

## 演示流程

```bash
# 1. 恢复初始状态
python demo/reset_scenarios.py

# 2. 查看路由分析（展示 PE/PER 作为替代方案）
ai-router analyze "重构用户认证模块，将登录和鉴权逻辑拆分为独立的中间件，以及实现 Token 刷新机制"
# 讲解要点：
# - classifier 识别 COMPLEX → PE/PER 合格
# - selector 评估 PE vs SINGLE_MODEL 的成本-质量
# - alternatives 列表展示 PE 和 PER 作为替代方案

# 3. dry-run 验证（展示 opensquilla 模式）
ai-router run "重构用户认证模块，将登录和鉴权逻辑拆分为独立的中间件，以及实现 Token 刷新机制" \
  --workdir demo/scenario4-refactor-auth \
  --dry-run
# 讲解要点：
# - opensquilla ML 复杂度分析
# - 策略选择逻辑（系统智能决策，不是硬编码触发）
# - 如果 PE 被选中：展示 planner + executor 双模型协作
# - 如果 SINGLE_MODEL 被选中：说明系统判断单模型更优

# 4. 真实执行（可选，需要 API Key）
ai-router run "重构用户认证模块，将登录和鉴权逻辑拆分为独立的中间件，以及实现 Token 刷新机制" \
  --workdir demo/scenario4-refactor-auth \
  --yes
```

**注意**：当前 models.yaml 配置下，系统可能选择 SINGLE_MODEL（因为 Tier 1 模型性价比高）。
PE/PER 会在以下条件下被优先选择：
- Tier 1 模型价格更高时（planner 用 Tier 1，executor 用 Tier 3 更省）
- 任务更复杂（EXPERT 级）
- 风险更高（触发 PER review）
