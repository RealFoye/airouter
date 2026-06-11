# OpenSquilla ML 复杂度路由 — 架构扩展设计

> 本文档是 `system-design.md` 中"任务复杂度推断"部分的增量设计。
> 其他路由、成本、Gate 和审计架构保持不变。

## 1. 新旧架构对比

### 改动前（纯规则）
```
TaskAnalyzer（关键词）→ ComplexityLevel → Router 管道
```

### 改动后（规则 + 可选 ML）
```
ComplexityAnalyzer
  ├─ TaskAnalyzer（规则特征提取，委托）
  └─ OpenSquillaBackend（可选 ML 分类）
      → resolved ComplexityLevel → Router 管道
```

## 2. 特征空间

- **390 维 LightGBM 输入**：51 HC + 102 TF-IDF + 10 Context + 16 History + 192 PCA-BGE + 12 Assistant + 2 Continuation + 5 Reasoning
- **1536 维原始三通道 BGE**：单独输入 ONNX MLP（当前用户 + 历史用户 + 上轮助手，各 512 维）

## 3. raw/final class 区别

| 概念 | 含义 | 使用场景 |
|------|------|----------|
| `raw_route_class` | ML argmax 原始分类（R0-R3） | hybrid 模式使用 |
| `final_route_class` | 安全层后分类（margin upgrade / flag override） | opensquilla 模式使用 |

**为什么 hybrid 用 raw 不用 final**：OpenSquilla 的 flag override 会根据 high_risk 升级到 R2+，AirRouter Gate 也会因 HIGH risk 触发 human review。用 final 会导致同一 risk 信号被升级两次。

## 4. 四种 mode 语义

| mode | ML 加载 | 路由行为 | 适用场景 |
|------|---------|----------|----------|
| `rules` | 否 | 纯规则 | 默认，生产 |
| `shadow` | 是 | 规则生效，ML 仅记录 | 观测，不影响路由 |
| `opensquilla` | 是 | 使用 final class 替换 | 离线实验 |
| `hybrid` | 是 | 使用 raw class 升级（只升不降） | 生产增强 |

## 5. Hybrid 决策表

| ML 可用 | raw_confidence >= threshold | 行为 |
|---------|---------------------------|------|
| Yes | Yes | 使用 raw class 升级，受 max_upgrade_steps 限制 |
| Yes | No | 不升级（置信度不够） |
| No | - | 根据 require_runtime 降级或抛错 |

## 6. Tier 映射

| OpenSquilla | AirRouter 复杂度 | default Tier | high_risk Tier |
|-------------|----------------|-------------|---------------|
| R0 (c0/S) | SIMPLE | [3] | [2, 3] |
| R1 (c1/M) | MODERATE | [2, 3] | [1, 2] |
| R2 (c2/L) | COMPLEX | [1, 2] | [1, 2] |
| R3 (c3/XL) | EXPERT | [1] | [1] |

## 7. Runtime 生命周期和失败降级

- Backend 初始化失败 → 抛 `ComplexityBackendUnavailable`
- Analyzer 根据 `require_runtime` 决定降级或传播
- `rules` 模式不创建 Backend

## 8. sys.modules 驻留限制

- 上游代码使用 `src.router.*` 绝对导入，加载后驻留 sys.modules
- 进程内只允许一个 bundle path
- 已有 `sys.modules["src"]` 冲突时拒绝初始化

## 9. Bundle 部署方式

- 仅通过环境变量 `AIROUTER_OPENSQUILLA_BUNDLE_DIR` 引用
- 不提交 `opensquilla/` 到 AirRouter repo
- 不创建空的 bundle 目录

## 10. 安全

- Artifact SHA-256 校验（manifest integrity + runtime_src tree + artifact files）
- 拒绝 symlink 和意外 binary
- Hash 锚点硬编码在 AirRouter 代码中

## 11. 与 Analyzer/Selector/Gate 的职责边界

- **ComplexityAnalyzer**：决定复杂度（可被 ML 增强）
- **ModelSelector**：按 features 选模型（不受 ML 影响）
- **RoutingGate**：按 risk/budget 门禁（不受 ML 影响）

## 12. Python 版本要求

- AirRouter 基础：Python 3.11+
- ML 后端（OpenSquilla）：Python 3.12+
