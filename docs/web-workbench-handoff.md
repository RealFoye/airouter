# AirRouter Web 工作台交接说明

本文档给没有上下文的新 agent 使用，说明当前 Web 工作台的产品设计、后端接线、关键文件、已完成修改、当前状态和后续检查点。

## 1. 当前产品形态

当前 Web 是一个面向普通用户的「先分析，再执行」AI 工作台，不是后台管理面板。

用户流程：

1. 用户输入自己的 API Key 登录。
2. 进入类似 ChatGPT/Claude 的对话页面。
3. 用户输入任务，点击「分析」。
4. AirRouter 本地 Router / OpenSquilla 分析任务，推荐模型和处理方式。
5. 用户可以：
   - 直接接受并执行。
   - 点击「深度复核」，让 MiniMax-M3 / qwen3.7-max 复核推荐是否合理。
   - 选择更省钱、更稳妥或手动调整模型。
6. 用户确认后才调用被推荐的执行模型；标题生成、深度复核和长上下文压缩会按需提前调用辅助模型。
7. 执行过程中可以切换模型，已有上下文继续保留。
8. 左侧保留该 API Key 下的历史对话，点击可回到旧对话继续问。

普通用户页面不直接暴露 benchmark 内部指标、Judge 覆盖率、450/450 这类工程数据。技术依据放进折叠区。

当前页面的核心定位：

> 对普通用户来说，它是一个「先判断该怎么做，再让用户确认执行」的 Chat 工作台；  
> 对项目汇报来说，它展示 AirRouter 的路由、成本、复核和治理闭环；  
> 对工程实现来说，它是 Streamlit MVP，不是最终生产级前端。

## 2. 关键文件

### Web 主入口

- `web/app.py`

职责：

- Streamlit 主页面。
- 用户会话状态。
- 对话历史。
- 分析按钮。
- 推荐方案卡片。
- 深度复核按钮。
- 接受并执行。
- 模型切换。
- 流式输出。
- 上下文压缩。
- 对话短标题生成。
- Markdown 渲染。
- 图片、表格、PDF 和文本附件上传。

### Web 公共 UI

- `src/airouter/web/ui.py`

职责：

- Streamlit 页面配置。
- 全局 CSS。
- API Key 登录。
- Sidebar 导航。
- 管理员入口折叠。
- 退出登录。

### Web 数据展示

- `src/airouter/web/data.py`

职责：

- 模型目录展示。
- 从配置和评测产物读取部分展示数据。

### 管理员页面

- `web/pages/1_route_workbench.py`
- `web/pages/2_consumption_dashboard.py`
- `web/pages/3_optimization_center.py`
- `web/pages/4_benchmark_results.py`
- `web/pages/5_governance_config.py`

职责：

- 保留原有治理后台能力。
- 当前不作为普通用户主流程。
- 统一放在 Sidebar 的「管理员入口」折叠区。
- 每个管理员页都通过公共 Sidebar 提供「智能工作台」入口，可以回到 Chat 页面。

### 路由后端核心

- `src/airouter/engine/router/router.py`

职责：

- AirRouter 路由入口。
- 输入任务文本，输出 `RoutingDecision`。
- 串起任务分析、策略分类、模型选择、成本估算和人工确认门禁。

### 复杂度分析 / OpenSquilla 接入

- `src/airouter/engine/complexity/analyzer.py`
- `src/airouter/engine/complexity/ml_backend.py`
- `src/airouter/engine/complexity/types.py`
- `src/airouter/config.py`

职责：

- 支持 `rules`、`shadow`、`opensquilla`、`hybrid` 四种复杂度模式。
- 当前 Web 分析阶段优先使用 `opensquilla` 模式，也就是 OpenSquilla 的 `final_route_class`。
- 如果 OpenSquilla 依赖或 bundle 不可用，自动回退 rules。

### 模型配置和调用

- `data/models.yaml`
- `src/airouter/adapters/openai_compat.py`
- `src/airouter/adapters/base.py`

职责：

- `data/models.yaml` 定义模型名、价格、上下文窗口、能力、API base。
- Web 登录时用户输入 API Key。
- 执行任务时使用用户 API Key + `models.yaml` 里的 `api_base` 调用模型。
- 当前 `claude-sonnet-4-6` 已从可调用模型注册表删除，因为当前 API 侧不可用。
- 当前可调用模型为：
  - `qwen3.7-max`
  - `deepseek-v4-pro`
  - `kimi-k2.6`
- `qwen3.7-plus`
  - `MiniMax-M3`
  - `glm-5.1`
  - `deepseek-v4-flash`
- `MiniMax-M3` 带 `judge` capability，用作当前深度复核 / Judge 优先模型。
- `qwen3.7-plus` 带 `multimodal` / `vision` capability；Web 检测到图片附件时会走独立 `image_model` 路径，固定使用它执行。

### OpenSquilla bundle

- `opensquilla/src/opensquilla/squilla_router/models/v4.2_phase3_inference/`

职责：

- OpenSquilla ML 复杂度分类器 bundle。
- 该目录被 `.gitignore` 排除，不应该提交。

## 3. 当前 Web 的后端接线

### 3.1 登录

文件：`src/airouter/web/ui.py`

当前登录只需要 API Key，不需要账号、项目、部门。

实现方式：

- 明文 API Key 只存在当前 Streamlit session。
- 用 API Key 的 SHA256 前 16 位作为本地用户指纹。
- 对话历史按指纹分隔。
- 不保存明文 API Key。
- 退出登录只清当前登录状态和 API Key，不删除本地对话历史。
- 同一个 API Key 再登录，会按指纹重新加载自己的历史对话。

相关函数：

- `require_login()`
- `_sidebar_navigation()`

当前登录页文案需要保持诚实：

- 本地 Router 分析不调用大模型。
- 但生成对话标题、深度复核、执行任务、长上下文压缩会调用模型。

### 3.2 对话历史

文件：`web/app.py`

当前对话历史保存在：

- `runs/web/conversations.json`

说明：

- `runs/` 已在 `.gitignore` 中，不会提交。
- 保存对话内容、路由分析结果、复核结果、执行记录。
- 不保存 API Key。
- 同一个 API Key 再登录可以看到自己的历史。
- 不同 API Key 看到不同历史。
- 左侧历史按钮强制单行显示，超出宽度用 `...` 省略。
- 新对话第一次分析后，会用 `qwen3.7-max` 生成一个短标题。
- 如果标题生成失败，会退回本地截断标题，不影响分析和执行。

相关函数：

- `_blank_conversation()`
- `_serialize_conversation()`
- `_deserialize_conversation()`
- `_load_conversation_store()`
- `_save_conversation_store()`
- `_current_user_key()`
- `_load_user_conversations()`
- `_persist_user_conversations()`
- `_init_state()`
- `_save_current_conversation()`
- `_load_conversation()`
- `_new_conversation()`
- `_fallback_conversation_title()`
- `_clean_conversation_title()`
- `_generate_conversation_title()`
- `_render_conversation_sidebar()`

标题生成相关常量：

- `CONVERSATION_TITLE_MODEL = "qwen3.7-max"`

标题生成设计：

1. 用户点击「分析」。
2. 本地 Router 完成推荐。
3. Web 用用户 API Key 调用 `qwen3.7-max`，生成 6 到 12 个中文字的对话标题。
4. 标题写入当前 conversation。
5. 失败时 fallback 到本地截断标题。

注意：

- 标题生成会产生一次真实模型调用。
- 这是为了让左侧历史更像 ChatGPT / Claude 的会话列表，而不是直接展示一长串原始问题。
- 如果以后要降低成本，可以改成本地规则标题，或者只在用户停留超过一定时间后异步生成。

### 3.3 分析阶段

文件：`web/app.py`

相关函数：

- `_run_analysis()`

当前逻辑：

1. 合并用户任务和补充材料。
2. 构造 `ComplexityContext`。
3. 加载配置 `load_all()`。
4. 优先把复杂度配置改成：
   - `mode="opensquilla"`
   - `bundle_dir=opensquilla/src/opensquilla/squilla_router/models/v4.2_phase3_inference`
   - `require_runtime=False`
5. 调用 `Router(config=config).route(...)`。
6. 如果 OpenSquilla 可用，走 ML final。
7. 如果不可用，自动回退 rules。

注意：

- `_run_analysis()` 本身不调用 LLM API。
- OpenSquilla 是本地 ML 推理。
- 但是用户点击「分析」后，同一次提交会额外调用 `qwen3.7-max` 生成对话标题。
- 页面会在系统依据中显示：
  - `OpenSquilla ML final`
  - 或 `快速规则分析（ML 不可用）`

### 3.4 推荐方案

文件：`web/app.py`

相关函数：

- `_render_recommendation()`
- `_primary_model()`
- `_friendly_strategy()`
- `_completion_label()`
- `_cost_comparison()`
- `_cost_saving_vs_most_expensive()`
- `_why_this_model()`
- `_dynamic_notices()`

推荐卡片显示：

- 推荐模型。
- 处理方式。
- 预计完成把握。
- 预计成本。
- 成本对比。
- 为什么推荐。
- 需要注意什么。
- 系统依据。

成本对比口径：

- 统一对比 `qwen3.7-max`。
- 如果推荐模型就是 `qwen3.7-max`，显示「已是最贵模型」。
- 否则显示「比最贵省 xx%」。

当前卡片有一个明确状态：

> 点击「接受并执行」将使用：某模型 · 某处理方式

这是当前唯一执行方案来源。

### 3.5 深度复核

文件：`web/app.py`

相关函数：

- `_review_recommendation()`
- `_render_deep_review()`
- `_extract_json_object()`
- `_review_model_name()`

当前逻辑：

1. 用户点击「深度复核」。
2. Web 使用用户 API Key 调用：
   - 优先 `MiniMax-M3`
   - 不可用时 fallback 到 `qwen3.7-max`
3. 复核模型只检查推荐方案，不执行用户任务。
4. 复核问题包括：
   - 任务是否被低估或高估。
   - 是否漏风险。
   - 推荐模型是否过低或过高。
   - 是否需要先澄清。
   - 是否建议人工确认。
5. 复核结果是建议态，不自动覆盖当前方案。

用户操作：

- `采用复核建议`：把当前执行方案改成复核建议。
- `不采用，保留当前方案`：关闭复核建议，不改方案。
- `恢复初始推荐`：回到第一次分析出的模型和处理方式。

重要语义：

- 点完深度复核后，如果用户直接点「接受并执行」，执行的仍然是页面上「将使用」显示的当前方案。
- 只有点「采用复核建议」才会改变当前执行方案。

### 3.6 执行阶段

文件：`web/app.py`

相关函数：

- `_execute_with_user_key()`
- `_build_execution_messages()`
- `_stream_model_response()`
- `_openai_error_message()`
- `_estimate_tokens()`
- `_estimate_stream_cost()`

当前逻辑：

1. 用户点击「接受并执行」或执行区的「执行」。
2. 读取当前执行模型。
3. 使用用户 API Key 和 `models.yaml` 中的 `api_base` 调用模型。
4. 使用 OpenAI-compatible streaming 接口。
5. 页面显示流式输出和「已思考 xxs」。
6. 记录估算 input/output tokens、耗时、成本。
7. 模型回答按 Markdown 渲染，标题、列表、加粗、代码块会编译后显示。

注意：

- streaming 当前使用估算 token，因为流式接口未必返回完整 usage。
- 模型自我介绍不可靠。比如用户问「你是什么模型」，模型可能自报错误身份。实际调用模型应以页面执行栏和请求参数为准。

Markdown 渲染改动：

- 用户消息仍用深色气泡，以 HTML escape 后展示，避免用户输入破坏页面结构。
- 助手 / 模型消息使用 `st.markdown(content)` 渲染。
- 流式生成时也使用 Markdown 渲染，不再把 `**标题**`、反引号原样展示。
- 代码块、行内代码、列表、blockquote 的视觉样式在 `src/airouter/web/ui.py` 中统一配置。

### 3.7 模型切换

文件：`web/app.py`

当前执行阶段的模型选择是「选择即生效」。

实现要点：

- 下拉框 key：`ar_execution_model_picker`
- 页面执行栏显示当前模型。
- 点击「执行」时使用下拉框当前值。
- 切换模型不会清空上下文。

这是为了解决旧问题：

- 旧版需要先下拉选择，再点「切换模型」。
- 用户容易以为下拉后已经切换，但执行时仍读旧的 `ar_selected_model`。
- 现在改成下拉即为下一次执行模型。

### 3.8 上下文记忆和压缩

文件：`web/app.py`

相关常量：

- `CONTEXT_COMPRESSION_CHAR_LIMIT = 16000`
- `CONTEXT_KEEP_RECENT_MESSAGES = 8`
- `CONTEXT_SUMMARY_MODEL = "qwen3.7-max"`

相关函数：

- `_compress_context_if_needed()`
- `_history_as_text()`
- `_build_execution_messages()`

当前逻辑：

1. 每次执行都会把用户输入和模型回复加入 `ar_execution_messages`。
2. 切换模型时不清空 `ar_execution_messages`。
3. 当上下文超过阈值，自动调用 `qwen3.7-max` 压缩较早对话。
4. 压缩后保留最近 8 条原始消息。
5. 压缩摘要作为 system message 注入后续执行。

注意：

- 压缩会调用真实模型 API。
- 只有上下文很长时才触发。
- 压缩失败不会中断当前执行，会保留原始上下文继续。

### 3.9 图片、表格、PDF 和附件

文件：`web/app.py`

相关常量：

- `IMAGE_MODEL = "qwen3.7-plus"`
- `MAX_ATTACHMENTS = 4`
- `MAX_ATTACHMENT_BYTES = 4 * 1024 * 1024`
- `MAX_TEXT_ATTACHMENT_CHARS = 12000`

相关函数：

- `_process_uploaded_files()`
- `_extract_delimited_table()`
- `_extract_spreadsheet()`
- `_extract_pdf()`
- `_attachment_text_block()`
- `_build_task_with_materials()`
- `_build_multimodal_user_content()`
- `_has_image_attachments()`

当前支持：

- 图片：`png`、`jpg`、`jpeg`、`webp`
- 表格：`csv`、`tsv`、`xlsx`、`xlsm`
- PDF：`pdf`
- 文本/代码/日志：`txt`、`md`、`json`、`jsonl`、`log`、`py`、`sql`、`yaml`、`xml`、`html`、`css`、`js`、`ts` 等

处理逻辑：

1. 用户在「补充材料」里上传附件。
2. 文本、CSV/TSV、Excel、PDF 会尽量提取正文，和用户任务一起进入 Router 分析。
3. 图片不会转文字；执行时会用 OpenAI-compatible 多模态消息格式随请求发送。
4. 只要当前对话包含图片，执行模型固定为 `qwen3.7-plus`。
5. 图片场景会禁用「更省钱」「更稳妥」「手动选择」，避免用户误选不支持图片的模型。
6. 继续追问时可以继续上传附件；新附件会进入当前对话上下文。

依赖说明：

- Excel 读取依赖 `openpyxl`。
- PDF 读取依赖 `pypdf`。
- 两者已写入 `pyproject.toml`。
- 如果当前运行环境没有安装 `pypdf`，PDF 会显示明确提示，不会假装读取了 PDF 正文。

重要边界：

- 单个附件最多 4MB，最多保留 4 个附件。
- Excel 默认提取前 3 个工作表、每个工作表前 40 行、最多 16 列。
- PDF 默认提取前 6 页。
- 附件内容过长会截断，并在上下文中标注。
- 扫描件 PDF 可能无法提取文字，需要后续 OCR 能力。
- 当前图片只在执行阶段真正发送给模型；深度复核只看到附件摘要和可提取文本，不直接读取图片内容。

## 4. 视觉设计现状

文件：`src/airouter/web/ui.py`

当前设计目标：

- 更像 ChatGPT / Claude / Gemini 的普通用户聊天界面。
- 不做传统后台 dashboard。
- 主区域居中，左侧保留历史对话。
- 管理员页面收进「管理员入口」折叠区。
- 推荐方案以轻量卡片呈现。
- 技术细节折叠，不直接干扰普通用户。

当前视觉特征：

- 背景：浅暖白 `#faf9f6`
- 文本：接近黑色 `#171717`
- Sidebar：浅灰米色
- 主聊天区最大宽度约 880px
- 用户消息：深色气泡
- 助手消息：透明文本，按 Markdown 渲染
- 推荐卡：白底、圆角、轻阴影
- 主按钮：黑色圆角
- 次按钮：白底圆角
- 左侧对话历史：单行显示，超长用 `...` 省略
- Sidebar 顶部固定有「智能工作台」入口，管理员页也能回到 Chat 页面

主要 CSS 类：

- `.ar-workspace`
- `.ar-chat-header`
- `.ar-chat-subtitle`
- `.ar-chat-thread`
- `.ar-chat-message`
- `.ar-plan-card`
- `.ar-plan-metrics`
- `.ar-active-plan`
- `.ar-review-card`
- `.ar-execution-bar`
- `.ar-stream-box`
- `.ar-input-shell`
- `.ar-assistant-message`

特别注意：

- 不要在普通用户主页面直接展示 `450/450`、`Judge 覆盖率`、`候选输出` 这类 benchmark 内部指标。
- 这些内容可以留在管理员页或折叠技术依据里。
- 普通用户关心的是：推荐哪个模型、为什么、能省多少钱、是否需要先确认、点接受后会用哪个方案执行。

## 5. 我们是如何一步一步改到现在的

### 第一步：从后台页面改成普通用户工作台

原来 Web 更像治理后台，侧边栏有很多页面：

- 高级路由分析
- 消费审计
- 上下文优化
- Benchmark 结果
- 治理配置

问题：

- 普通用户不需要看到这些。
- 页面不像 AI Chat。
- 用户会被 benchmark 内部指标干扰。

修改：

- 主页面改成「先分析，再执行」。
- 管理页面放进 Sidebar 的「管理员入口」折叠区。
- 删除普通用户右侧的 benchmark 指标展示。

### 第二步：登录改成只输入 API Key

原想法包括账号、API Key、项目。

后来判断：

- 当前 MVP 不需要账号。
- 用户不一定在处理项目任务。
- 只输入 API Key 更自然。

修改：

- 登录页只保留 API Key。
- API Key 不保存到磁盘。
- 历史按 API Key 指纹分隔。

### 第三步：引入对话历史

需求：

- 左侧要有之前的对话。
- 用户可以点回之前对话继续问。
- 同一个用户重复登录能看到自己的历史。

修改：

- 新增 `runs/web/conversations.json`。
- 新增会话序列化/反序列化。
- Sidebar 渲染历史对话。
- 新对话按钮。

### 第四步：分析阶段改用 OpenSquilla ml_final

原来页面分析走 `rules`。

问题：

- 之前 benchmark 显示 `ml_final` 在质量和欠路由上更好。
- 用户会疑惑为什么不用已经验证过的 OpenSquilla。

修改：

- `_run_analysis()` 默认设置 `mode="opensquilla"`。
- 使用 OpenSquilla `final_route_class`。
- 不可用时自动回退 rules。

### 第五步：统一成本口径

原来问题：

- 卡片里显示「比最贵省 82%」。
- 推荐理由里显示「预计节省 91%」。

原因：

- 一个来自页面 benchmark 成本表。
- 一个来自 Router 内部估算 baseline。

修改：

- 统一用 `qwen3.7-max` 作为最贵模型参照。
- 推荐理由和成本对比使用同一口径。

### 第六步：执行接真实 API

修改：

- 接受并执行后才调用真实模型 API。
- 使用用户输入的 API Key。
- 使用 OpenAI-compatible streaming。
- 显示「已思考 xxs」。

### 第七步：模型切换保留上下文

问题：

- 用户中途切换模型时，应该继续保留上下文。

修改：

- 执行历史存在 `ar_execution_messages`。
- 模型切换不清空历史。
- 上下文过长时用 `qwen3.7-max` 压缩。

### 第八步：修复模型切换歧义

问题：

- 旧版下拉选模型后，还要点「切换模型」。
- 用户可能选了 qwen，但实际执行仍用旧模型。

修改：

- 下拉框选择即生效。
- 执行时直接读取 `ar_execution_model_picker`。
- 执行栏同步显示当前模型。

### 第九步：补深度复核

需求：

- 本地 Router 分析后，用户可以让强模型复核推荐。

修改：

- 新增「深度复核」按钮。
- 调用 MiniMax-M3，fallback qwen3.7-max。
- 复核推荐是否合理。
- 复核结果不自动覆盖当前方案。
- 用户可采用、忽略或恢复初始推荐。

### 第十步：视觉重做

问题：

- 原页面卡片多、后台感强、不够简洁。

修改：

- 去掉右侧说明栏。
- 主区域居中。
- 推荐卡轻量化。
- 技术依据折叠。
- 按钮主次区分。

### 第十一步：修复 Markdown 显示

问题：

- 模型回答中的 `**标题**`、反引号、列表没有渲染。
- 用户看到的是原始 Markdown 文本，像调试输出，不像正式 AI 聊天界面。

修改：

- 用户消息继续转义后放进深色气泡。
- 助手消息改为 `st.markdown(content)`。
- 流式输出也改为 Markdown 渲染。
- CSS 补充标题、列表、行内代码、代码块样式。

相关文件：

- `web/app.py`
- `src/airouter/web/ui.py`

### 第十二步：删除不可用 Claude 模型

问题：

- `claude-sonnet-4-6` 在 `data/models.yaml` 中存在，但当前 API 侧不可用。
- 留在模型注册表里会让前端下拉或 Judge 默认值误导用户。

修改：

- 从 `data/models.yaml` 删除 `claude-sonnet-4-6`。
- 给 `MiniMax-M3` 补 `judge` capability。
- 旧 L2 Judge 默认模型改为 `MiniMax-M3`。
- 注册表测试更新为 7 个可调用模型。

相关文件：

- `data/models.yaml`
- `src/airouter/engine/benchmark/llm_judge.py`
- `tests/unit/test_model_registry.py`

注意：

- 文档里的 Claude 竞品调研 / 可扩展模型叙述没有必要全部删除，那些不是可执行配置。
- 真正影响 Web 可选模型的是 `data/models.yaml`。

### 第十三步：修复管理员页回不去 Chat

问题：

- 用户点进「管理员入口」里的页面后，侧边栏没有明显的返回普通 Chat 入口。
- 用户会误以为聊天记录消失了。

修改：

- 公共 Sidebar 顶部固定显示 `智能工作台` 页面链接。
- 管理员页面仍在折叠区中。
- 退出登录不再清空 `ar_` 对话状态，只清登录凭证。

相关文件：

- `src/airouter/web/ui.py`

### 第十四步：优化左侧历史标题

问题：

- 左侧历史直接展示原始用户问题，太长、会换行、很丑。
- 用户希望像主流 AI Chat 一样显示一行短标题。

修改：

- 新对话分析后，用 `qwen3.7-max` 生成短标题。
- 侧边栏按钮强制单行显示，超出宽度用 `...`。
- 标题生成失败时 fallback 到本地截断，不影响主流程。

相关文件：

- `web/app.py`
- `src/airouter/web/ui.py`

## 6. 当前完成程度

已经完成：

- API Key 登录。
- Sidebar 历史对话。
- 按 API Key 指纹区分历史。
- 左侧历史单行省略。
- 大模型短标题生成。
- 分析阶段优先 OpenSquilla ml_final。
- 推荐方案展示。
- 成本口径统一。
- 深度复核。
- 接受并执行真实 API。
- 流式输出。
- Markdown 渲染。
- 模型切换保留上下文。
- 长上下文自动压缩。
- 图片、表格、PDF 和文本附件上传。
- 图片任务固定使用 `qwen3.7-plus`，表格/PDF/文本附件尽量提取正文后进入分析和执行。
- 管理员页可一键回到智能工作台。
- 管理页面折叠。
- 删除不可用 `claude-sonnet-4-6` 可执行配置。
- 基础视觉重做。

已验证：

- `python -m py_compile web/app.py src/airouter/web/ui.py`
- `python -m ruff check web/app.py src/airouter/web/ui.py`
- `python -m pytest tests/unit/test_model_registry.py tests/unit/test_ground_truth_judge.py tests/unit/test_ground_truth_runner.py -q`
- 本地 Streamlit 可启动。
- 本地样例确认 `_run_analysis()` 可走 `mode=opensquilla`、`ml_available=True`、`ml_final=R2`。

当前服务启动命令：

```bash
streamlit run web/app.py --server.port 8501 --server.headless true --server.fileWatcherType none
```

本地访问：

```text
http://localhost:8501
```

## 7. 当前已知问题和注意事项

### 7.1 还不是生产级认证

当前只有 API Key 输入，没有账号体系、权限体系、服务端会话隔离。

适合 MVP 和演示，不适合直接多用户生产。

### 7.2 对话历史是本地文件

保存位置：

```text
runs/web/conversations.json
```

优点：

- 简单。
- 不保存 API Key。
- 可跨退出恢复。

限制：

- 没有加密。
- 没有数据库。
- 不适合真实多人环境。

### 7.3 深度复核会真实调用 API

用户点击「深度复核」时，会调用 MiniMax-M3 或 qwen3.7-max。

这会产生真实成本。

### 7.4 对话标题生成会真实调用 API

用户第一次点击「分析」后，会调用 `qwen3.7-max` 生成短标题。

这会产生一次小额真实成本。

如果标题生成失败，会使用本地 fallback，不影响分析和执行。

### 7.5 长上下文压缩会真实调用 API

当执行历史超过阈值时，会调用 qwen3.7-max 生成摘要。

这也会产生真实成本。

### 7.6 流式 token 成本是估算

当前 streaming 不一定能拿到完整 usage，因此 input/output tokens 和 cost 是估算。

### 7.7 模型自我介绍不可靠

用户问「你现在是什么模型」时，模型可能自报错误身份。

判断实际调用模型，应看：

- 页面执行栏显示的模型。
- `_stream_model_response()` 实际传入的 `model_name`。

### 7.8 OpenSquilla 加载有 sklearn 版本 warning

停止或加载服务时可能看到 sklearn pickle 版本警告。

目前属于 warning，不是页面运行错误。

### 7.9 Streamlit 可做 MVP，但不是最终最佳前端形态

Streamlit 可以快速做工作台，但精细交互、稳定状态管理、多人会话和视觉控制不如 React/Next.js。

如果后续要做真正产品化前端，建议迁移到：

- FastAPI / API backend
- React / Next.js frontend
- 数据库存储对话和审计记录
- 服务端统一管理 API Key 或企业凭证

## 8. 新 agent 建议检查顺序

新 agent 接手后建议按这个顺序检查：

1. 打开 `web/app.py`，先看页面主流程。
2. 看 `_run_analysis()`，确认分析阶段如何接 OpenSquilla。
3. 看 `_render_recommendation()`，确认推荐卡和当前执行方案。
4. 看 `_review_recommendation()` 和 `_render_deep_review()`，确认深度复核不会自动覆盖方案。
5. 看执行阶段：
   - `_execute_with_user_key()`
   - `_build_execution_messages()`
   - `_stream_model_response()`
6. 看 `_generate_conversation_title()`，确认标题生成失败不会影响主流程。
7. 看 `_render_message()`，确认 Markdown 渲染路径。
8. 看 `src/airouter/web/ui.py`，确认视觉、登录、Sidebar 返回入口。
9. 看 `data/models.yaml`，确认模型名和价格。
10. 看 `src/airouter/engine/router/router.py`，确认 Router 输出 `RoutingDecision`。
11. 看 `src/airouter/engine/complexity/analyzer.py`，确认 OpenSquilla mode 行为。
12. 本地运行 Streamlit，手动测试：
    - 登录。
    - 新建对话。
    - 分析任务。
    - 左侧历史是否生成短标题。
    - 左侧历史是否单行省略。
    - 深度复核。
    - 采用/不采用复核建议。
    - 接受并执行。
    - 模型回答 Markdown 是否正常渲染。
    - 切换模型后继续执行。
    - 进入管理员页后点击「智能工作台」回到 Chat。
    - 退出再登录，确认历史还在。

## 9. 后续可以问新 agent 的问题

可以让新 agent 重点回答：

1. 当前 Web 的状态管理是否有隐藏 bug？
2. 深度复核的 JSON 解析是否足够稳？
3. 模型切换是否在所有路径都真正生效？
4. `runs/web/conversations.json` 是否应该迁移到 SQLite？
5. Streamlit 是否已经到上限，是否应该开始迁移 React/Next.js？
6. OpenSquilla `ml_final` 作为默认分析是否应该增加用户可见的 fallback 提示？
7. 成本估算是否应该改成执行完成后从 provider usage 精确读取？
8. 普通用户是否能理解「深度复核」「恢复初始推荐」这些词？
9. 对话标题生成是否值得继续用强模型，还是改成本地规则或异步生成？
10. 管理员入口是否应该在演示时默认隐藏，只保留给内部人员？

## 10. 当前结论

当前 Web 已经从后台式 dashboard 变成一个可演示的普通用户 AI 工作台：

- 用户先提交任务。
- 系统用 OpenSquilla ml_final + Router 推荐模型。
- 系统用 qwen3.7-max 生成短对话标题，便于历史管理。
- 用户可让 MiniMax-M3 / qwen3.7-max 复核推荐。
- 用户确认后调用真实模型。
- 执行中可切换模型并保留上下文。
- 模型回答按 Markdown 正常渲染。
- 管理员页面仍保留，但不干扰普通用户主流程。

它已经适合演示 AirRouter 的核心价值：

> 不是直接问模型，而是先判断任务，再推荐模型和策略，必要时复核，最后由用户确认执行。

但它仍是 Streamlit MVP，不是最终生产前端。
