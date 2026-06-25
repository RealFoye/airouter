# AirRouter PPT 演说文稿

> 对应文件：outputs/AirRouter-答辩演示-可编辑.pptx
> 正式主讲：第 1–22 页；第 18、20 页为演示视频，不计入讲解时间。
> 第 23–32 页仅用于答疑，不主动讲。
> 目标讲解时长：约 11 分 30 秒；压缩版可控制在 9 分 30 秒。

## 0. 整体讲法与时间分配

这场答辩不要讲成“我做了很多模块”，而要讲成一条因果链：

1. 多模型接入后，企业真正缺少的是任务级决策。
2. 我先用 13 维规则画像建立最小 Router。
3. 真实 Benchmark 暴露出规则对语义复杂度的欠路由。
4. 接入 OpenSquilla，只增强 complexity，不照搬模型绑定。
5. AirRouter 再根据能力、风险、成本和质量选择模型与策略。
6. 用 450 组真实输出和 Ground Truth 回放验证最终选择。
7. 最后把能力包装成 Web 与 CLI Agent，形成可使用的闭环。

标准版时间：

| 部分 | 页码 | 时间 |
|---|---:|---:|
| 问题、成果与演进 | 1–4 | 1 分 40 秒 |
| 路由流程与真实案例 | 5–6 | 1 分 15 秒 |
| 13 维、OpenSquilla 与选模算法 | 7–13 | 4 分 55 秒 |
| Benchmark 与真实结果 | 14–16 | 2 分 05 秒 |
| Web、CLI 与收尾 | 17–22 | 1 分 35 秒 |
| 合计 | 不含视频 | 约 11 分 30 秒 |

压缩到 10 分钟时：
- 第 4 页只讲一句项目演进。
- 第 11 页只讲“OpenSquilla 只负责 complexity”。
- 第 14 页 Finance 只作为一句方法来源。
- 第 21 页只讲一个限制和一个下一步。

---

## 第 1 页：封面

**主讲：10 秒**

大家好，我汇报的项目是 AirRouter。它解决的不是“如何调用一个大模型”，而是企业接入多个模型以后，如何根据每个任务的难度、风险、质量要求和成本，决定用哪个模型、用什么方式执行，以及是否需要人工确认。

**转场：** 先不讲实现，先看最终做出了什么。

---

## 第 2 页：项目结果总览

**主讲：30 秒**

项目目前形成了从任务分析、模型选择、真实执行到评测校准的完整闭环。Routing Ground Truth 完成了 90 个任务、5 个模型，共 450 组真实候选输出和 450 组 Judge 辅助审计；Finance 又完成了 36 个企业财务案例、5 个模型，共 180 次真实调用。

这些数据最终不是为了做模型排行榜，而是为了回答：在保证完成质量的前提下，哪些任务可以交给更便宜的模型。离线 Oracle 显示，相对全部使用最贵模型，存在约 96.1% 的理论节省空间。产品层则形成了 Web 和 CLI Agent 两类入口。

**转场：** 为什么企业不能直接固定使用最强模型？

---

## 第 3 页：企业问题与四个决策

**主讲：35 秒**

全用最强模型看似安全，但简单任务会产生大量浪费；只按价格降级，又会让代码、安全和生产任务欠路由。AirRouter 因此不只推荐一个模型名字，而是执行前回答四个问题：用哪个模型、采用单模型还是多阶段策略、是否需要人工确认，以及大约花多少钱。

这里的目标不是追求单项最高分，而是在质量、成本、风险和可验证性之间动态取舍。

**转场：** 这套思路不是一开始就完整设计出来的，而是被实验一步步纠正出来的。

---

## 第 4 页：项目演进路线

**主讲：25 秒**

第一阶段，我用 13 维规则画像建立最小 Router；第二阶段通过 L1、L2 和 Finance 真实 API 测试，发现规则泛化和评分口径问题；第三阶段接入 OpenSquilla 的 390 维复杂度分类器；第四阶段用 90 个任务、5 个模型建立路由真值；最后再做成 Web 工作台和 CLI Agent。

每次扩展都不是为了增加功能数量，而是上一阶段的实验证据说明原方案不够。

**转场：** 接下来先看一个任务进入系统以后，实际发生什么。

---

## 第 5 页：任务从输入到执行

**主讲：30 秒**

一个任务进入 AirRouter 后，系统先读取问题、附件、历史和用户约束；然后生成任务画像；再过滤不合格模型，比较模型和执行策略；随后由 Gate 判断是直接执行、先澄清、增加复核还是人工确认；最后才调用真实模型和工具，并记录输出、Token、延迟与修改。

执行后的测试、规则评分、Judge 和真实成本会成为下一轮校准的证据。OpenSquilla 只参与第二步的复杂度判断，不负责最终派工。

**转场：** 用一个可以复现的认证重构案例看这条链路。

---

## 第 6 页：认证重构真实案例

**主讲：45 秒**

案例要求重构用户认证模块，拆分登录和鉴权逻辑，并实现 Token 刷新。规则初判为 COMPLEX，OpenSquilla 根据语义和上下文把它提升为 R3，也就是 EXPERT，置信度约 69%。

但 R3 并没有直接绑定某个模型。AirRouter 继续比较单模型、Plan-Execute 和 Plan-Execute-Review。当前质量先验和成本估算下，deepseek-v4-pro 单模型的预计质量约 0.795，成本约 0.0752 元，比两种多阶段策略质量更高、成本更低，所以最终推荐单模型执行；任务又涉及认证和业务风险，因此 Gate 要求人工复核。

这一页要说明：复杂度、模型、策略和审批是四个不同决策。

**转场：** 那么系统究竟依据哪些信息形成任务画像？

---

## 第 7 页：完整 13 维任务画像

**主讲：40 秒**

13 维不是 13 个拍脑袋分数，也不会最后简单相加。它们分为四组。

任务本身包括 category、complexity 和 subtasks；治理信号包括 risk、sensitivity、verifiability 和 output strictness；资源需求包括 context、reasoning、预计输入和输出 Token；模型能力则包括 required capabilities 和 preferred capabilities。

它们共同回答：这是什么任务、难在哪里、做错有什么影响、结果能否验证、需要多少上下文，以及模型必须具备什么能力。

**转场：** 这些字段又是怎样从一句自然语言需求中生成的？

---

## 第 8 页：认证重构任务如何逐项生成 13 维

**主讲：45 秒**

这一页不是再讲一次总体流程，而是用认证重构说明字段如何真正落出来。

系统首先从“重构、拆分、Token 刷新”和三个明确动作中得到任务类别、子任务与格式约束；OpenSquilla 单独根据当前请求、历史与上轮回答判断 complexity，得到 R3、约 69% 概率，映射为 EXPERT；治理规则再根据认证、权限和失败影响判断风险与是否需要复核；最后，类别、复杂度和子任务共同派生出重上下文、高推理、Token 规模以及架构和代码能力要求。

所以不是让一个模型一次猜完 13 个字段。能直接观察的先落字段，complexity 由 OpenSquilla 增强，剩余资源字段按依赖关系重新计算。

**转场：** 生成 13 维以后，并不是求一个总分，而是分阶段使用。

---

## 第 9 页：13 维如何驱动路由

**主讲：40 秒**

第一步，复杂度和风险限定允许的模型档位。普通 SIMPLE 默认只看 Tier 3；MODERATE 看 Tier 2 和 Tier 3；COMPLEX 看 Tier 1 和 Tier 2；EXPERT 只允许 Tier 1。高风险任务会采用更保守的档位。

第二步做硬过滤：能力覆盖率、上下文窗口和敏感数据策略不满足就直接淘汰。能力覆盖最低要求随复杂度从 50% 提升到 100%。

第三步生成单模型、Plan 和 Review 候选；第四步综合评分；最后 Gate 决定是否自动执行。

所以 R3 只缩小候选范围，不等于固定使用某个模型。

**转场：** 其中最难判断的是 complexity，下面重点解释 OpenSquilla 怎么得到 R0 到 R3。

---

## 第 10 页：OpenSquilla 的双路复杂度分类

**主讲：60 秒**

第一版规则快、可解释，但依赖显式关键词。在 70 条校准任务中，欠路由率达到 28.6%，所以我引入 OpenSquilla 补充语义和上下文判断。

它并不是 390 个关键词。390 维由八组特征拼成：51 维结构特征、102 维 TF-IDF 与 SVD 词法特征、10 维上下文、16 维历史轨迹、192 维三路 PCA-BGE 语义表示、12 维上一轮回答特征、2 维任务延续信号和 5 维推理信号。

推理时有两条支路。第一条把 390 维工程特征送进 LightGBM；第二条把当前问题、历史问题和上一轮回答各 512 维的原始 BGE 表示，也就是 1536 维，送入 ONNX MLP。两路分别输出 R0 到 R3 的概率，再按照类别权重融合，并结合置信度 margin、上下文信号和欠路由保护，得到 ml_final。

认证重构最终得到 R3 概率约 69%，映射为 EXPERT。这里输出的是难度概率和诊断，而不是某个公司模型名称。

**转场：** 但分类器只回答任务有多难，并不负责最终派工。

---

## 第 11 页：OpenSquilla 与 AirRouter 的边界

**主讲：25 秒**

OpenSquilla 输出 raw class、final class、置信度和 margin。AirRouter 只把 final class 映射成自身的 complexity，再重新计算上下文、推理强度、Token、子任务和能力要求，最后由 Selector 选择模型和策略，由 Gate 决定澄清、复核、人工确认或执行。

我复用了 OpenSquilla 的特征提取、已训练模型和后处理，但没有照搬它的模型绑定、价格表和生产策略。因为公司的模型池、网关价格、敏感数据政策和业务风险都不同。

**转场：** 最终具体模型是如何在候选池里选出来的？

---

## 第 12 页：候选模型过滤与综合评分

**主讲：50 秒**

候选模型先经过硬过滤：必需能力覆盖率、允许 Tier、上下文窗口、敏感数据策略和可用性必须满足。

剩余模型再计算综合分：能力覆盖、成本得分、质量先验和延迟得分按任务类别动态加权。架构和 Bug 分析更看能力与质量；文档和数据处理更看成本。

认证重构案例中，qwen3.7-max 和 deepseek-v4-pro 都满足 Tier 1 与能力要求。当前正式 Selector 的质量先验来自 Tier 乘任务类别，再扣除该 Tier 的默认严重错误率，两者约为 0.795；deepseek-v4-pro 成本更低，因此综合胜出。

这里要诚实说明：Ground Truth 已经用于离线验证路由策略，但还没有自动在线回写每个模型的 Selector 质量分，这是下一步工作。

**转场：** 模型选出来后，还要决定是一次完成还是拆分执行，以及能否直接放行。

---

## 第 13 页：执行策略与治理 Gate

**主讲：35 秒**

单模型始终作为候选。只有复杂或专家任务、推理较强、输出较长并且至少两个子任务时，Plan-Execute 才进入候选；在此基础上，如果任务高风险、低可验证或属于强制审核类型，Plan-Execute-Review 才进入候选。

策略生成后仍会比较质量和多阶段成本：质量损失超过 15% 的方案淘汰，这里的 15% 不是模型猜的，是我设的工程安全阈值。意思是：如果一个方案相比候选里质量最高的方案差超过 15 个百分点，即使它便宜，也不推荐，因为质量牺牲太大。

多阶段策略如果节省不足 15% 也淘汰。多阶段不是越多越好。它会增加调用次数和流程复杂度，所以我要求它至少带来 15% 的成本节省，否则就不值得拆。

最后 Gate 根据风险、敏感性、预算和质量损失决定自动执行或人工确认。自然语言关键词只做软信号，不能承担企业硬门禁。

**转场：** 这些阈值和策略不能只靠设计文档，需要真实 Benchmark 验证。

---

## 第 14 页：Benchmark 演进

**主讲：35 秒**

这一页讲的是 Benchmark 的演进。最开始我做 L1/L2，是为了把基础链路跑通：L1 测路由规则，L2 跑真实 API 看模型质量。  评测从 L1 离线规则开始，随后进入 L2 真实 API 和 Judge。

后来我做 Finance，是因为企业场景不能只看代码题。财务任务里有金额、制度、附件、证据和成本对账，适合验证“规则评分 + Judge 审计 + 成本核算”这套治理方法。

但 Finance 只是一个业务部门样板。为了验证这套方法能不能迁移到研发部门，我又做了 Engineering Benchmark，覆盖代码修复、代码审查、日志分析、SQL 安全、配置变更和反幻觉。它重点测的不是代码写得多好，而是模型能不能遵守指令、不伪造测试、不乱改文件、遇到高风险时要求确认。

最后我发现，真正评价路由器，不能只靠人工写“这个任务简单还是复杂”。所以我做了 Ground Truth：同一道任务让 5 个模型都真实回答，判断哪些模型达标，再找出最便宜的达标模型。这个才是路由真值。然后再用它比较 Rules、OpenSquilla 和 Hybrid 到底谁选得更接近真实最优。

所以这页的关键变化是：评测从“模型答得怎么样”，升级到了“路由选得对不对”。

**转场：** 真实路由标签具体怎样产生？

---

## 第 15 页：Routing Ground Truth

**主讲：45 秒**

这页是 Ground Truth 的核心。以前我们说任务是简单还是复杂，本质上还是人为标签。这里我换了一个更接近真实路由的问题：这道题最低用哪个模型能可靠完成。

做法是每道题先让 5 个模型都真实回答，然后通过结构解析、程序测试、规则评分、Judge 和人工抽检判断每个模型是 PASS 还是 FAIL。如果 flash 失败，plus 通过，pro 和 max 也通过，那这道题的真实路由答案就是 plus，因为它是最低成本可通过模型。

后面比较 Rules、ml_final、Hybrid 时，不能先看答案再挑最好的模型。真实上线时 Router 看不到答案，所以离线回放也必须先让策略根据任务输入选模型，再读取这个模型已有结果。

同一批 90 道题 × 5 模型等于 450 个输出，保存以后就可以反复离线回放不同策略，不需要重复调用 API。为了防止数据泄漏，Holdout、评分器版本和路由配置都在运行前冻结。这样评测的才是路由策略，而不是事后挑答案。

**转场：** 最终真实数据给出了什么结论？

---

## 第 16 页：真实 API 结果与最终选择

**主讲：45 秒**

90 个任务乘 5 个模型，共 450 个候选输出。qwen3.7-plus 的通过率最高，为 72.2%；deepseek-v4-pro 为 70%，但 90 题总成本只有约 0.59 元，性价比突出；qwen3.7-max 成本最高，但通过率并不是最高。这证明“最贵等于最好”在当前样本上不成立。

离线路由回放中，Rules 成本最低，但复杂任务欠路由明显；ml_final 在 Holdout 上的 平均质量差距最低，为 0.068，这里的 0.068 是平均质量差距，不是通过率。它表示 ml_final 策略选出来的模型，和 Ground Truth 中理想的最低可通过模型相比，平均质量只差 0.068。这个值越接近 0 越好，所以说 ml_final 的质量保持最好。

用户入口采用 ml_final 增强复杂度判断，Rules 作为失败兜底和基线对照。这样既利用 OpenSquilla 的语义判断能力，又保留规则系统的稳定性和可解释性。

**转场：** 这些后台能力最后被包装成两类真实用户入口。

---

## 第 17 页：Web 工作台

**主讲：20 秒**

Web 面向非技术用户，流程是先描述任务，系统给出推荐模型、完成把握、成本比较和注意事项；用户可以接受、选择更省钱或更稳妥、手动改模型，也可以付费进行深度复核，再真实流式执行和继续追问。

图片、PDF、表格和文本附件都能进入任务分析，内部 Benchmark 术语默认隐藏。

**转场：** 下面通过视频展示完整交互。

---

## 第 18 页：Web 演示视频

**视频，不计入讲解时间。建议 75–90 秒。**

视频顺序：
1. API Key 登录。
2. 输入一个带附件的真实任务。
3. 展示 ml_final 本地分析与推荐。
4. 展示成本和最贵模型对比。
5. 点击深度复核，提示额外 Token 费用。
6. 接受推荐并流式执行。
7. 切换模型后继续追问，展示上下文仍然保留。

**视频结束转场：** 普通用户需要的是方案确认；开发人员还需要模型真正读文件、改代码和跑测试。

---

## 第 19 页：CLI Agent

**主讲：20 秒**

CLI 面向开发人员。ai-router run 支持一次性任务，ai-router agent 支持类似 Claude Code 的多轮 REPL。每一轮重新分析并推荐模型，用户可以确认或手动切换，然后 Agent 在工作目录内读写文件、调用命令、运行测试并记录本轮和累计成本。

低风险操作自动执行，高风险命令由用户选择本次允许、会话允许或拒绝。

**转场：** 下面用视频展示真实代码修改流程。

---

## 第 20 页：CLI 演示视频

**视频，不计入讲解时间。建议 90–120 秒。**

视频顺序：
1. 在 Demo 项目启动交互式 Agent。
2. 输入修复任务。
3. 展示 OpenSquilla 复杂度、模型推荐和成本估算。
4. 用户确认模型。
5. Agent 读取文件、修改代码。
6. 测试命令需要授权，用户确认。
7. 展示测试通过、修改文件和真实累计成本。
8. 继续提出第二轮需求，证明会话上下文保留。

**视频结束转场：** Web 和 CLI 不是两个孤立 Demo，它们共用同一套路由和治理闭环。

---

## 第 21 页：Prompt 成本优化

**主讲：35 秒**

除了“选哪个模型”，项目里还有一条已经做出来的能力：Prompt 成本优化。

它解决的问题不是“模型选错了”，而是“我发给模型的内容本身有没有浪费”。比如系统提示过长、历史上下文重复、附件摘要太散、或者多轮 Agent 每轮都带了太多无关内容，都会让 token 成本上升。

`ai-router optimize` 会对 prompt 或上下文文件做成本估算，给出压缩建议、适用场景和预期节省。它和 Router 是互补关系：Router 负责“派给谁做”，Prompt Optimize 负责“交给模型之前先把输入整理得更省”。

这一页右侧我会放一张真实终端截图，展示 optimize 命令输出的原始成本、优化后成本和节省比例。

**转场：** 当前已经能减少不必要 token，下一步可以继续往缓存感知方向演进。

---

## 第 22 页：企业 Token 消费审计

**主讲：35 秒**

除了执行前的 Prompt 优化，项目还实现了执行后的企业 Token 消费审计。

`ai-router audit` 会读取路由决策和执行反馈，按用户、模型、项目、部门和任务类型汇总消费，并检测五类浪费：简单任务使用高价模型、短时间重复调用、上下文过长、可以降级但没有降级，以及本可以使用缓存却没有利用。

这一页必须把数据口径说清楚：截图里的 `alice、bob` 是虚拟用户，`¥430.53` 和预计节省 `42.5%` 来自 `seed.db` 模拟消费流水，用于验证审计链路，不是公司真实账单。

但审计能力是真实实现的。后续只需要把数据源替换成 CCH、API Gateway 或 Langfuse 的真实 usage 流水，就可以对账实际 Token、延迟、重试和费用，现有聚合和浪费检测逻辑不需要重写。

**转场：** Prompt 优化解决执行前少传内容，消费审计解决执行后钱花在哪里；下面再看项目未来如何进入真实工具链。

---

## 第 23 页：未来路线

**主讲：35 秒**

AirRouter 已经形成任务画像、路由执行、质量证据、真实成本和离线校准的闭环，但我不会把 MVP 说成生产终态。

下一步我不打算继续横向新增更多部门 Benchmark，而是把已有能力接进真实工具链。

第一是缓存感知路由。当前已经有上下文压缩和 Prompt 优化，后续可以进一步估算同一模型下 prompt cache 的命中机会。大白话说，就是稳定系统提示、附件摘要和工具结果尽量保持一致，让重复内容少花钱、也更快。

第二是接入开发者 Agent。不是重新造一个 Claude Code，而是让 Claude Code / Codex 这类工具使用 AirRouter 的选模、切换、审批、成本和证据记录能力。

第三是持续校准，用真实任务、Judge、测试和账单继续更新质量与成本先验。

**转场：** 最后用一句话总结项目。

---

## 第 24 页：结论

**主讲：20 秒**

AirRouter 最终证明的是：企业不需要为每个任务固定一个模型，而需要一套能够根据任务语义、风险、可验证性、历史表现和成本，动态选择模型、执行策略和审核机制的系统。

OpenSquilla 提供更强的语义复杂度信号，AirRouter 负责最终派工和治理，Benchmark 让这些选择能够被真实结果持续校准。谢谢。

---

# 答疑附录

## 第 25 页：13 维任务画像速查

**仅在评委追问“13 维具体是什么”时打开。**

不要逐行念表格。先回答四组：任务本体、治理信号、资源需求、模型能力，再指出 complexity 由 ml_final 增强，其余字段来自事实、规则和派生逻辑。

## 第 26 页：390 维为什么不能直接照搬

**仅在追问“维度越多是否一定更好”时打开。**

回答重点：390 维只有在预处理、模型资产和训练分布一致时才有意义；AirRouter 复用了分类器，没有照搬模型绑定和价格策略。

## 第 27 页：成本估算与真实账单

**仅在追问成本口径时打开。**

执行前对候选模型使用同一输入、输出 Token 假设，保证比较公平；执行后记录真实 input、output、reasoning tokens、重试和延迟，再与 CCH usage CSV 对账。

## 第 28 页：四种复杂度模式

**仅在追问 Rules、Shadow、OpenSquilla、Hybrid 时打开。**

用户入口使用 opensquilla / final class；Rules 是基线和失败降级；Shadow 只记录不改变路由；Hybrid 用于安全与成本折中实验。

## 第 29 页：模型池真实表现

**仅在追问具体模型数据时打开。**

强调这是当前 90 条样本的历史表现，不是对下一次任务的确定承诺。

## 第 30 页：Quality Regret 0.068

**仅在追问指标含义时打开。**

0.068 表示路由选中模型与该任务最佳模型之间，平均少拿 0.068 个标准化质量分。越接近 0 越好，不是准确率 6.8%。

## 第 31 页：Judge 的两种语境

**仅在追问“双 Judge”或 Judge 是否可靠时打开。**

早期 L2 使用 Absolute 和 Pairwise 两类 Judge；最终 Ground Truth 使用 MiniMax-M3 辅助审计。Judge 不能覆盖程序真值，也不能解除确定性硬失败。

## 第 32 页：评测可复现性

**仅在追问续跑、重复调用和数据泄漏时打开。**

说明 JSONL 断点续跑、raw outputs、manifest 冻结和同批输出离线回放。

## 第 33 页：Agent 权限设计

**仅在追问 CLI 安全时打开。**

低风险操作自动允许；影响环境或网络的操作由用户确认；明显破坏性操作始终拒绝。

## 第 34 页：Q&A 导航

用于快速定位追问，不主动展示。

---

## 附录 A：演说时必须守住的口径

1. 不说“390 维一定比 13 维更准”，只说它补充了语义复杂度信号，并经过当前模型池真实验证。
2. 不说“Judge 是标准答案”，只说它辅助评价解释、证据和幻觉。
3. 不说“质量先验已经实时学习每个模型”，当前 Selector 主要使用 Tier × 任务类型先验。
4. 不说“96.1% 是生产承诺”，它是当前 90 条任务下 Oracle 相对全用 max 的理论节省空间。
5. 不说“R3 直接选择强模型”，R3 只限定复杂度，最终模型仍经过过滤与综合评分。
6. 不说“复杂任务一定 Plan-Execute”，策略仍要比较质量与多阶段成本。
7. 不说“当前已经生产可用”，准确表述是可运行、可验证、可演示的治理 MVP。

## 41. 运行前准备

下面所有命令都在 macOS / zsh 下使用。代码块里只放可执行命令，不要把说明文字或以 `#` 开头的注释一起复制进终端。

### 41.1 进入项目并激活虚拟环境

```bash
cd /Users/foye/Desktop/airouter
source .venv/bin/activate
```

看到命令行前出现 `(.venv)`，说明虚拟环境已激活。

### 41.2 新环境第一次安装

已经安装过时不需要每次执行。

```bash
cd /Users/foye/Desktop/airouter
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,ml]"
```

必须包含 `ml`，否则 OpenSquilla 运行环境缺失，复杂度分析会回退 Rules。

### 41.3 检查 CLI 是否安装成功

```bash
ai-router --help
```

正常情况下会显示六个命令：

- `analyze`：离线路由分析。
- `optimize`：Prompt 与上下文成本优化。
- `audit`：Token 消费审计。
- `benchmark`：多级 Benchmark。
- `run`：一次性 Agent 执行。
- `agent`：交互式多轮 Agent。

### 41.4 检查 OpenSquilla bundle

通常 `analyze`、`run`、`agent` 会自动定位项目内 bundle。如果终端提示 bundle 未配置，可在当前终端执行：

```bash
export AIROUTER_OPENSQUILLA_BUNDLE_DIR="$PWD/opensquilla/src/opensquilla/squilla_router/models/v4.2_phase3_inference"
```

验证时可以运行：

```bash
ai-router analyze "重构认证模块并运行完整测试" --show-complexity
```

输出中应看到：

```text
mode=opensquilla
ML final 或 R0-R3
ML 可用
```

如果显示 fallback 或 Rules，需要检查 ML 依赖和 bundle 路径。

### 41.5 API Key

`analyze`、`optimize`、`audit`、Level 1 Benchmark 和 `run --dry-run` 不需要 API Key。

真实 `run`、`agent`、真实 API Benchmark 需要模型提供商对应的 Key。CLI 可以从项目根目录 `.env` 读取，例如：

```text
AIROUTER_DASHSCOPE_API_KEY=你的Key
AIROUTER_DEEPSEEK_API_KEY=你的Key
AIROUTER_ZHIPU_API_KEY=你的Key
AIROUTER_KIMI_API_KEY=你的Key
AIROUTER_MINIMAX_API_KEY=你的Key
```

不要把真实 Key 放进 PPT、Git 或演示录屏。

---

## 42. Web 网页版运行命令

### 42.1 启动 Web

新开一个终端窗口，执行：

```bash
cd /Users/foye/Desktop/airouter
source .venv/bin/activate
streamlit run web/app.py --server.port 8501 --server.headless true --server.fileWatcherType none
```

浏览器访问：

```text
http://localhost:8501
```

### 42.2 8501 端口被占用

换成 8502：

```bash
cd /Users/foye/Desktop/airouter
source .venv/bin/activate
streamlit run web/app.py --server.port 8502 --server.headless true --server.fileWatcherType none
```

浏览器访问：

```text
http://localhost:8502
```

### 42.3 停止 Web

回到运行 Streamlit 的终端，按：

```text
Control + C
```

### 42.4 Web 演示操作顺序

1. 输入自己的 API Key 登录。
2. 新建对话。
3. 输入任务或上传 PDF、表格、图片、代码文件。
4. 点击“分析”。本地 Router / OpenSquilla 分析不会调用执行模型。
5. 查看推荐模型、执行方式、成本与推荐理由。
6. 可选：点击“深度复核”。该步骤会调用大模型并产生费用。
7. 选择接受、改成更省钱、更稳妥，或手动选模型。
8. 点击执行，观察流式输出。
9. 继续追问或切换模型，验证上下文保留。

---

## 43. `ai-router analyze`：离线路由分析

用途：只分析任务、推荐模型和策略，不调用执行模型 API，适合答辩现场快速展示。

### 43.1 最简单用法

```bash
ai-router analyze "写一个 FastAPI JWT 鉴权中间件"
```

### 43.2 显示 OpenSquilla 复杂度详情

```bash
ai-router analyze "修复 auth.py 中的 SQL 注入漏洞，并运行测试验证" --show-complexity
```

重点观察：

- Rules complexity。
- ML raw / final。
- R0-R3 与置信度。
- ML 推理耗时和路由总耗时。
- 推荐模型、策略、预估成本。

### 43.3 手动对比四种复杂度模式

```bash
ai-router analyze "重构用户认证模块，支持 OAuth2 和 MFA" --mode rules --show-complexity
```

```bash
ai-router analyze "重构用户认证模块，支持 OAuth2 和 MFA" --mode shadow --show-complexity
```

```bash
ai-router analyze "重构用户认证模块，支持 OAuth2 和 MFA" --mode opensquilla --show-complexity
```

```bash
ai-router analyze "重构用户认证模块，支持 OAuth2 和 MFA" --mode hybrid --show-complexity
```

当前默认模式是 `opensquilla`，也就是使用 OpenSquilla `ml_final` 作为正式复杂度。

### 43.4 JSON 输出

```bash
ai-router analyze "分析一段生产事故日志并给出排查方案" --show-complexity --format json
```

JSON 输出适合脚本接入或答辩时证明数据不是页面硬编码。

---

## 44. `ai-router optimize`：Prompt 与上下文成本优化

用途：分析 Prompt 中哪些内容固定、重复、可缓存、可摘要，并估算多轮使用时的节省空间。它是离线分析，不真实改写业务答案。

### 44.0 PPT 截图推荐命令

建议优先运行这一条，输出最适合放到第 21 页截图位：既能看到 Agent 多轮场景，也能看到原始成本、优化后成本和预计节省。

```bash
ai-router optimize --context-file docs/examples/optimize-agent-context.txt --scenario AGENT_MULTI_TURN --turns 10
```

如果想要更短的截图，可以使用直接传 Prompt 的版本：

```bash
ai-router optimize --prompt "你是一个代码审查专家。请检查输入代码中的安全漏洞、逻辑错误和性能问题，并按严重程度给出修改建议。" --scenario AGENT_MULTI_TURN --turns 10
```

### 44.1 直接传 Prompt

```bash
ai-router optimize --prompt "你是一个专业的代码审查专家，请检查输入代码中的安全漏洞、逻辑错误和性能问题，并输出问题位置、严重程度、原因和修改建议。"
```

### 44.2 从文件读取 Prompt

```bash
ai-router optimize --context-file docs/examples/optimize-agent-context.txt
```

### 44.3 指定当前模型

```bash
ai-router optimize --prompt "你是一个代码审查专家，请检查下面的代码。" --model deepseek-v4-pro
```

作用：使用指定模型的价格估算当前 Prompt 成本和优化空间。

### 44.4 单轮任务

```bash
ai-router optimize --prompt "请总结下面的会议纪要。" --scenario SINGLE_TURN --turns 1
```

### 44.5 固定 Prompt + 工具

```bash
ai-router optimize --context-file docs/examples/optimize-agent-context.txt --scenario FIXED_PROMPT_TOOLS --turns 10
```

### 44.6 Agent 多轮场景

```bash
ai-router optimize --context-file docs/examples/optimize-agent-context.txt --scenario AGENT_MULTI_TURN --turns 10
```

### 44.7 同一项目重复使用

```bash
ai-router optimize --context-file docs/examples/optimize-agent-context.txt --scenario SAME_PROJECT_REPEAT --turns 20
```

### 44.8 随机上下文场景

```bash
ai-router optimize --prompt "请分析用户每次随机提交的文档。" --scenario RANDOM_CONTEXT --turns 10
```

### 44.9 JSON 输出

```bash
ai-router optimize --context-file docs/examples/optimize-agent-context.txt --scenario AGENT_MULTI_TURN --turns 10 --format json
```

输出重点解释：

- 原始 Token：当前 Prompt 大致占多少 Token。
- 固定部分：适合缓存或复用的 System Prompt / 工具定义。
- 可压缩部分：可摘要、去重或按需注入的内容。
- 原始成本与优化后成本：基于当前模型价格和轮数的估算，不是实际账单。
- 节省率：在指定场景和轮数假设下的理论节省。

---

## 45. `ai-router audit`：消费审计

用途：读取本地审计数据库，分析 Token 消费、浪费模式和用户/项目/部门分布，不调用大模型。

### 45.1 默认最近 30 天

```bash
ai-router audit
```

### 45.2 最近 7 天指定用户

```bash
ai-router audit --user alice --days 7
```

### 45.3 指定项目

```bash
ai-router audit --project airouter --days 30
```

### 45.4 指定部门

```bash
ai-router audit --department engineering --days 90
```

### 45.5 JSON 输出

```bash
ai-router audit --days 30 --format json
```

### 45.6 指定数据库

```bash
ai-router audit --db sqlite:///seed.db --days 30
```

默认数据库就是 `sqlite:///seed.db`。答辩时应说明当前主要使用种子审计数据演示治理分析，不要声称它已经接入生产账单流水。

---

## 46. `ai-router benchmark`：Benchmark 命令

Benchmark 命令较多，答辩现场建议只运行 Level 1。真实 API 全量测试已经有结果文件，不要在现场重新启动。

### 46.1 Level 1 离线规则测试

```bash
ai-router benchmark --level 1
```

特点：零 API 成本，适合现场展示测试链路。

### 46.2 Level 1 首次失败即停止

```bash
ai-router benchmark --level 1 --fail-fast
```

### 46.3 Level 1 JSON 输出

```bash
ai-router benchmark --level 1 --format json
```

### 46.4 Level 2 默认 Mock

```bash
ai-router benchmark --level 2
```

不加 `--real-api` 时不应把结果说成真实模型质量。

### 46.5 Level 2 少量真实 API Smoke

下面会产生真实费用，只在确认 API Key 和输出目录后运行：

```bash
ai-router benchmark --level 2 --real-api --models deepseek-v4-flash,qwen3.7-plus --limit 4 --workers 2 --rate-limit 10
```

`--limit 4` 表示本次最多执行 4 个 case-model pair，不是每个模型 4 条。

### 46.6 Level 2 带 Judge

会额外调用 Judge 并产生费用：

```bash
ai-router benchmark --level 2 --real-api --models deepseek-v4-flash,qwen3.7-plus --limit 4 --judge --judge-models MiniMax-M3 --workers 2 --judge-workers 2
```

### 46.7 Level 3 离线路由策略回放

```bash
ai-router benchmark --level 3
```

```bash
ai-router benchmark --level 3 --case-set l1 --baseline-model qwen3.7-max
```

### 46.8 Finance 默认或 Mock 链路

```bash
ai-router benchmark --level finance
```

### 46.9 Finance 真实 API

会产生较多真实费用，答辩现场不要运行：

```bash
ai-router benchmark --level finance --real-api --workers 5 --rate-limit 20
```

### 46.10 Finance 断点续跑

```bash
ai-router benchmark --level finance --real-api --resume --run-id 你的run_id --workers 5 --rate-limit 20
```

### 46.11 Finance 对已有结果离线重评分

不会重新调用被测模型：

```bash
ai-router benchmark --level finance --rescore --run-id 你的run_id
```

### 46.12 Finance 对已有结果运行 Judge

会调用 Judge，但不会重跑五个候选模型：

```bash
ai-router benchmark --level finance --judge-existing --run-id 你的run_id --judge-model MiniMax-M3 --judge-workers 5
```

### 46.13 Routing Ground Truth Mock 验证

Routing 策略回放需要显式提供 OpenSquilla bundle，先执行：

```bash
export AIROUTER_OPENSQUILLA_BUNDLE_DIR="$PWD/opensquilla/src/opensquilla/squilla_router/models/v4.2_phase3_inference"
```

再运行：

```bash
ai-router benchmark --level routing --limit 5 --format json
```

### 46.14 Routing 真实 API Smoke

会产生真实费用，必须先使用较小 `--limit`：

```bash
ai-router benchmark --level routing --real-api --limit 5 --workers 5 --rate-limit 20 --format json
```

### 46.15 Routing 断点续跑

```bash
ai-router benchmark --level routing --real-api --resume --run-id 你的run_id --workers 5 --rate-limit 20 --format json
```

### 46.16 Routing 全量重跑

`--rerun` 会重新执行全部目标 pair，与 `--limit`、`--resume` 互斥。除非明确需要重新付费，否则不要运行：

```bash
ai-router benchmark --level routing --real-api --rerun --workers 5 --rate-limit 20 --format json
```

### Benchmark 重要参数

| 参数 | 作用 |
|---|---|
| `--level` | 选择 1、2、3、finance 或 routing |
| `--real-api` | 使用真实 API；不写通常走 Mock 或离线流程 |
| `--models` | 指定候选模型，逗号分隔 |
| `--limit` | 限制本次新执行 pair 数，用于 Smoke |
| `--workers` | 候选模型并发数 |
| `--rate-limit` | 每分钟请求上限 |
| `--resume` | 断点续跑，只补缺失/失败结果 |
| `--run-id` | 指定已有 run |
| `--judge` | 本轮同时运行 Judge |
| `--judge-existing` | 对已有 Finance 输出运行 Judge |
| `--rescore` | 对已有 Finance 输出离线重评分 |
| `--rerun` | Routing 全量重跑，谨慎使用 |

---

## 47. `ai-router run`：一次性 Agent

用途：接收一个任务，完成“分析 → 推荐模型/策略 → 工具执行 → 验证 → 报告”，任务结束后退出。

### 47.1 只分析，不调用 API

```bash
ai-router run "修复 auth.py 中的 SQL 注入漏洞，并运行测试验证" --workdir demo/scenario1-sql-inject --dry-run
```

适合答辩现场先展示 OpenSquilla 和 Router 决策。

### 47.2 真实执行并保留确认

```bash
ai-router run "修复 auth.py 中的 SQL 注入漏洞，并运行测试验证" --workdir demo/scenario1-sql-inject --max-cost 1.0
```

系统会展示推荐方案，并询问是否执行。

### 47.3 跳过首轮人工确认

```bash
ai-router run "修复 auth.py 中的 SQL 注入漏洞，并运行测试验证" --workdir demo/scenario1-sql-inject --max-cost 1.0 --yes
```

`--yes` 会降低人工确认保护，只适合可重复 Demo，不建议用于陌生项目。

### 47.4 限制工具循环轮数

```bash
ai-router run "检查并修复计算函数的边界条件" --workdir demo/scenario3-divide-by-zero --max-turns 8 --max-cost 1.0
```

### 47.5 JSON 输出

```bash
ai-router run "修复 auth.py 中的 SQL 注入漏洞" --workdir demo/scenario1-sql-inject --dry-run --format json
```

### 47.6 在自己的项目中使用

先进入自己的项目：

```bash
cd /Users/foye/Desktop/111
```

再运行：

```bash
ai-router run "把当前网页改成支持流式输出的 AI Chatbot，先检查现有文件和技术栈，再修改并运行必要检查" --workdir . --max-cost 2.0
```

**正确：**

```bash
ai-router run "任务" --workdir .
```

**错误：**

```text
ai-router run "任务" --workdir /Users/foye/Desktop/111 .
```

最后多出的 `.` 会被 Typer 当成意外参数，出现 `Got unexpected extra argument (.)`。

---

## 48. `ai-router agent`：交互式多轮 Agent

用途：像 Claude Code 一样启动持续会话。每轮用户提出任务，系统重新分析和推荐模型，然后模型与工具循环执行，完成后用户可以继续追问。

### 48.1 在 Demo 项目启动

```bash
cd /Users/foye/Desktop/airouter
source .venv/bin/activate
ai-router agent --workdir demo/scenario1-sql-inject --max-cost 2.0
```

进入以后直接输入自然语言：

```text
帮我修复 auth.py 里的 SQL 注入漏洞，并运行测试验证
```

下一轮可以继续输入：

```text
解释一下你修改了什么，再补一个恶意输入测试
```

### 48.2 在自己的项目启动

```bash
cd /Users/foye/Desktop/111
source /Users/foye/Desktop/airouter/.venv/bin/activate
ai-router agent --workdir . --max-cost 5.0
```

然后输入：

```text
先检查当前项目结构，再把它改成一个网页版 AI Chatbot。API Key 由用户在前端输入，回答需要流式展示。完成后运行语法检查或测试。
```

### 48.3 固定执行模型

```bash
ai-router agent --workdir . --model qwen3.7-max --max-cost 5.0
```

固定模型后，Router 仍可分析任务，但执行模型保持手动指定。进入会话后使用 `/model auto` 恢复智能推荐。

### 48.4 跳过确认

```bash
ai-router agent --workdir . --max-cost 5.0 --yes
```

`--yes` 会跳过首轮模型确认及部分授权确认，风险更高，不建议在自己的重要项目中使用。

### 48.5 限制每轮工具调用次数

```bash
ai-router agent --workdir . --max-cost 5.0 --max-turns 20
```

### 48.6 恢复最近会话

在原工作目录或明确指定工作目录执行：

```bash
ai-router agent --workdir . --resume latest --max-cost 5.0
```

### 48.7 恢复指定会话

```bash
ai-router agent --workdir . --resume 20260618_102250_455713 --max-cost 5.0
```

恢复后会续接历史上下文、模型设置、修改文件和累计成本。

### 48.8 `agent` 与 `run` 的区别

| 对比项 | `ai-router run` | `ai-router agent` |
|---|---|---|
| 用户交互 | 一次任务，完成后退出 | 多轮 REPL，可继续追问 |
| 每轮路由 | 仅初始任务 | 每轮任务重新分析 |
| 会话恢复 | 不强调 | 支持 `--resume` |
| 模型切换 | 本次路由方案 | `/model` 随时切换 |
| PE/PER | 支持完整多阶段执行基础 | 当前 REPL 主要执行单模型工具循环 |
| 适合场景 | 单次自动化、可复现 Demo | 日常开发与持续修改 |

---

## 49. 交互式 Agent 的 Slash 命令

进入 `ai-router agent` 后使用，不是在普通 zsh 提示符中使用。

### 49.1 查看帮助

```text
/help
```

### 49.2 打开模型选择菜单

```text
/model
```

终端会列出候选模型，输入编号即可切换。

### 49.3 直接切换模型

```text
/model deepseek-v4-pro
```

```text
/model qwen3.7-plus
```

```text
/model qwen3.7-max
```

模型切换只影响下一次回答。标准化后的用户请求和最终回答会继续保留，底层不兼容的 `tool_calls` 轨迹不会直接传给新模型。

### 49.4 恢复自动路由

```text
/model auto
```

之后每轮由 OpenSquilla `ml_final` + AirRouter 重新推荐执行模型。

### 49.5 查看累计成本

```text
/cost
```

### 49.6 查看本会话修改文件

```text
/files
```

### 49.7 查看上下文摘要

```text
/summary
```

### 49.8 手动压缩上下文

```text
/compact
```

压缩可能调用轻量模型并产生少量费用；没有可用模型时回退本地摘要。

### 49.9 清空当前对话上下文

```text
/reset
```

它会清空对话上下文，但成本和修改文件记录仍保留。

### 49.10 退出并保存

```text
/exit
```

也可以按 `Control + C`，系统会尝试保存当前会话后退出。

---

## 50. 答辩现场推荐命令顺序

### 50.1 演示前重置 Demo

```bash
cd /Users/foye/Desktop/airouter
source .venv/bin/activate
python demo/reset_scenarios.py
```

### 50.2 展示零成本路由分析

```bash
ai-router analyze "修复 auth.py 中的 SQL 注入漏洞，并运行测试验证" --show-complexity
```

### 50.3 展示 Prompt 成本优化

```bash
ai-router optimize --context-file docs/examples/optimize-agent-context.txt --scenario AGENT_MULTI_TURN --turns 10
```

### 50.4 展示零成本 Benchmark

```bash
ai-router benchmark --level 1
```

### 50.5 展示一次性 Agent Dry Run

```bash
ai-router run "修复 auth.py 中的 SQL 注入漏洞，并运行测试验证" --workdir demo/scenario1-sql-inject --dry-run
```

### 50.6 展示交互式 Agent

```bash
ai-router agent --workdir demo/scenario1-sql-inject --max-cost 2.0
```

进入后输入：

```text
帮我修复 auth.py 里的 SQL 注入漏洞，并运行测试验证
```

完成后继续输入：

```text
解释一下你修改了什么，再补一个恶意输入测试
```

### 50.7 恢复 Demo

```bash
python demo/reset_scenarios.py
```

---

## 51. 常见命令错误

### `zsh: command not found: #`

原因：把文档里的注释行一起复制到了终端。只复制代码块中真正的命令，不要复制说明文字。

### `Got unexpected extra argument (.)`

原因：已经给了 `--workdir /某个路径`，后面又多写一个 `.`。删除多余的点。

### `ai-router: command not found`

执行：

```bash
cd /Users/foye/Desktop/airouter
source .venv/bin/activate
pip install -e ".[dev,ml]"
```

### 显示 `mode=rules` 或 ML unavailable

先确认虚拟环境和 ML 依赖，再设置 bundle：

```bash
cd /Users/foye/Desktop/airouter
source .venv/bin/activate
export AIROUTER_OPENSQUILLA_BUNDLE_DIR="$PWD/opensquilla/src/opensquilla/squilla_router/models/v4.2_phase3_inference"
ai-router analyze "重构认证模块" --show-complexity
```

### Web 打不开

确认运行 Streamlit 的终端没有退出，并尝试更换端口：

```bash
streamlit run web/app.py --server.port 8502 --server.headless true --server.fileWatcherType none
```

### Agent 提示缺少 API Key

说明本地路由已经完成，但执行模型所属提供商没有可用 Key。检查 `.env`，或先使用 `run --dry-run` 演示零成本链路。

### Agent 一直使用手动模型

进入会话后执行：

```text
/model auto
```

恢复每轮智能推荐。

### 真实 Benchmark 跑得比预期多

立即检查是否缺少 `--limit`。Smoke 必须显式写较小限制；`--rerun` 不得和 `--limit`、`--resume` 一起使用。
