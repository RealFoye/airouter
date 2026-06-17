"""上下文优化中心。"""

from __future__ import annotations

import streamlit as st

from airouter.engine.optimize.optimizer import PromptOptimizer
from airouter.web.data import model_catalog
from airouter.web.ui import configure_page, note, page_header, require_login, section_label

configure_page("上下文优化")
require_login()
page_header(
    "上下文优化",
    "分析 Prompt 的 Token 组成，并评估缓存、压缩、裁剪、降级与分层策略。",
)

SCENARIOS = {
    "单轮任务": "SINGLE_TURN",
    "固定 Prompt + 工具": "FIXED_PROMPT_TOOLS",
    "Agent 多轮": "AGENT_MULTI_TURN",
    "同项目重复任务": "SAME_PROJECT_REPEAT",
    "随机上下文": "RANDOM_CONTEXT",
}

prompt = st.text_area(
    "Prompt / 上下文",
    value=(
        "System: 你是企业代码审查助手。\n"
        "工具定义：可以读取文件、运行测试、查看 git diff。\n"
        "用户：请审查支付回调模块，只指出问题，不要修改代码。\n"
        "项目上下文：该模块包含重复请求去重、签名校验和入账事务。"
    ),
    height=240,
)
controls = st.columns([1, 1, 1])
with controls[0]:
    scenario_label = st.selectbox("使用场景", list(SCENARIOS))
with controls[1]:
    models = ["自动路由"] + [row["模型"] for row in model_catalog()]
    selected_model = st.selectbox("当前模型", models)
with controls[2]:
    turns = st.number_input("预期轮数", min_value=1, value=5, step=1)
run = st.button("生成优化建议", type="primary")

note("优化器只做本地分析和成本估算，不会调用模型，也不会修改原始 Prompt。")

if run:
    if not prompt.strip():
        st.error("请输入 Prompt 或上下文。")
        st.stop()
    try:
        result = PromptOptimizer().optimize(
            prompt=prompt,
            model_name=None if selected_model == "自动路由" else selected_model,
            scenario=SCENARIOS[scenario_label],
            expected_turns=int(turns),
        )
    except Exception as exc:
        st.error(f"优化分析失败：{exc}")
        st.stop()

    metrics = st.columns(4)
    metrics[0].metric("Input Token", f"{result.input_breakdown.total:,}")
    metrics[1].metric("当前成本", f"¥{result.current_cost:.4f}")
    metrics[2].metric("参考优化成本", f"¥{result.optimized_cost:.4f}")
    metrics[3].metric("预估节省", f"{result.total_savings_percentage:.1%}")

    section_label("Token 组成")
    breakdown = result.input_breakdown
    token_rows = {
        "System Prompt": breakdown.system_prompt_tokens,
        "工具定义": breakdown.tool_definitions_tokens,
        "固定上下文": breakdown.fixed_context_tokens,
        "对话历史": breakdown.conversation_history_tokens,
        "动态请求": breakdown.dynamic_query_tokens,
    }
    st.bar_chart(token_rows, y_label="Token")

    section_label("优化建议")
    if result.suggestions:
        st.dataframe(
            [
                {
                    "类别": suggestion.category,
                    "建议": suggestion.title,
                    "说明": suggestion.description,
                    "预估节省（元）": round(suggestion.estimated_savings, 4),
                    "节省比例": round(suggestion.savings_percentage * 100, 1),
                    "需审批": "是" if suggestion.details.get("requires_approval") else "否",
                }
                for suggestion in result.suggestions
            ],
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("当前 Prompt 未发现明显优化空间。")

    for warning in result.warnings:
        st.caption(f"注意：{warning}")
