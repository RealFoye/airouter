# Week 1 交付物验收清单

> 对照《校招AI应用工程师·一个月任务清单.pdf》的第 1 周要求。  
> 当前目标：完成可评审的《系统设计文档》，并明确哪些内容需要 Week 2-3 通过真实 API / Benchmark 补实测数据。

---

## 结论

Week 1 的**架构设计与调研文档骨架已补齐**，可以进入架构 Review。  
仍需后续补齐的是“实测数据”：Prompt Caching 命中率、延迟、质量影响、Benchmark 真实调用结果。这些依赖真实 API 配额和样本运行，不应在 Week 1 文档中伪造。

---

## 1.1 深度竞品与技术调研

| 编号 | PDF 要求 | 当前状态 | 交付位置 | 后续动作 |
|------|----------|----------|----------|----------|
| 1.1a | 调研 6+ 大模型定价结构，建立统一成本模型 | 已完成设计版 | `docs/competitive-analysis.md` 第三、四章；`docs/system-design.md` 4.5 | Week 2 接真实 API 后校准 `models.yaml` |
| 1.1a | 成本对比矩阵 | 已完成 | `docs/competitive-analysis.md` 第三章 | 每次价格变更需更新配置快照 |
| 1.1a | 归一化定价公式 | 已完成 | `docs/competitive-analysis.md` 4.1、4.2 | CostEstimator 继续补 breakdown 输出 |
| 1.1a | 不同调用模式下月成本模拟 | 已完成示例版 | `docs/competitive-analysis.md` 4.3 | 用真实 usage_records / execution_feedback 替换示例 |
| 1.1b | Claude Prompt Caching 机制 | 已完成设计版 | `docs/competitive-analysis.md` 5.1；`docs/system-design.md` 4.5.2 | Week 2-3 实测命中率 |
| 1.1b | Extended Thinking 机制 | 已完成设计版 | `docs/competitive-analysis.md` 5.2 | Week 2 Benchmark 记录 thinking/output token |
| 1.1b | Batch API 机制 | 已完成设计版 | `docs/competitive-analysis.md` 5.3 | Week 2/3 离线 Benchmark 使用 Batch 场景 |
| 1.1b | 每种机制的实测数据 | 未完成，合理延期 | - | 需要 API 配额、样本任务和执行日志 |
| 1.1b | 场景决策树 | 已完成 | `docs/competitive-analysis.md` 5.4 | 根据实测数据调阈值 |
| 1.1c | OpenRouter / LiteLLM / Claude-tap / Helicone 等对比矩阵 | 已完成 | `docs/competitive-analysis.md` 第二章 | Claude-tap 类工具以 Claude Code 官方用量能力作基线 |
| 1.1c | Gap 分析与差异化 | 已完成 | `docs/competitive-analysis.md` 第二章 | 后续答辩可直接使用 |
| 1.1d | 任务分类体系 | 已完成 | `docs/system-design.md` 4.1 | Week 2 继续扩测试集 |
| 1.1d | 每级典型任务示例 | 已完成 | `docs/system-design.md` 4.1.1、4.1.4 | 可继续从真实任务中补样本 |
| 1.1d | 对应推荐模型和预估 Token | 已完成设计版 | `docs/system-design.md` 4.1.4 | 真实 token 用 execution_feedback 校准 |

---

## 1.2 系统架构设计

| 编号 | PDF 要求 | 当前状态 | 交付位置 | 后续动作 |
|------|----------|----------|----------|----------|
| 1.2a | 路由引擎架构 | 已完成 | `docs/system-design.md` 第二章、第四章 | Week 2 完整策略组合与 fallback |
| 1.2a | 架构图 | 已完成文本图 | `docs/system-design.md` 2.1、2.2 | 答辩 PPT 可转 Mermaid/图片 |
| 1.2a | 核心模块接口定义 / OpenAPI Spec | 已完成摘要版 | `docs/system-design.md` 2.3 | Week 2-3 由 FastAPI 自动生成真实 OpenAPI |
| 1.2a | 路由决策算法伪代码 | 已完成 | `docs/system-design.md` 4.8 | 与实现保持同步 |
| 1.2b | Token 消费采集与审计架构 | 已完成 | `docs/system-design.md` 第十章、7.2 | Week 2 实现 audit engine |
| 1.2b | API Proxy / Middleware 拦截设计 | MVP 降级为 routing_decisions + execution_feedback | `docs/system-design.md` 第十章 | 真实网关接入后新增 usage_records |
| 1.2b | 消费归因模型 | 已完成 | `docs/system-design.md` 10.2、10.4 | Week 2-3 加 collector/attribution |
| 1.2c | 技术选型方案 | 已完成 | `docs/system-design.md` 第三章 | 若 Web 复杂度上升，再评估 React |
| 1.2c | 选型对比表 | 已完成 | `docs/system-design.md` 3.1 | - |
| 1.2c | 技术风险与缓解 | 已完成 | `docs/system-design.md` 3.2、十三章 | 按执行情况更新 |

---

## Week 1 可交付文件

| 文件 | 作用 |
|------|------|
| `docs/system-design.md` | 权威系统设计文档 |
| `docs/competitive-analysis.md` | 竞品调研、模型定价、统一成本模型、Claude 降本机制 |
| `docs/development-plan.md` | 四周开发执行计划 |
| `docs/week1-delivery-checklist.md` | PDF 第 1 周要求对照表 |
| `data/models.yaml` | MVP 模型注册表与定价配置 |
| `data/routing_rules.yaml` | 路由规则配置 |
| `data/budgets.yaml` | 预算配置 |
| `data/quality_defaults.yaml` | 质量评分默认值 |
| `data/compression_policy.yaml` | 上下文压缩/缓存策略配置 |

