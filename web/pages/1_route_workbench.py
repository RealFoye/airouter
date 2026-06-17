"""路由工作台。"""

from __future__ import annotations

import streamlit as st

from airouter.config import load_all
from airouter.engine.complexity.types import ComplexityContext
from airouter.engine.router.router import Router
from airouter.web.ui import configure_page, note, page_header, require_login, section_label

configure_page("路由工作台")
require_login()
page_header(
    "高级路由分析",
    "查看 Rules、Shadow 与 Hybrid 如何形成任务画像、模型组合和治理门禁。",
)

MODE_LABELS = {
    "规则基线": "rules",
    "Shadow 诊断": "shadow",
    "Hybrid 0.70": "hybrid",
}

left, right = st.columns([1.35, 1], gap="large")
with left:
    mode_label = st.radio(
        "复杂度分析模式",
        list(MODE_LABELS),
        index=0,
        horizontal=True,
        help="Shadow 只记录 ML 判断；Hybrid 只允许保守升级。",
    )
    task = st.text_area(
        "任务描述",
        value="修复生产环境支付回调的重复入账问题，只分析原因，不要直接修改代码。",
        height=180,
    )
    with st.expander("多轮与工具上下文"):
        history = st.text_area("历史用户消息", height=90, placeholder="每行一条历史请求")
        prev_assistant = st.text_area("上一轮助手回复", height=90)
        context_cols = st.columns(3)
        with context_cols[0]:
            turn_index = st.number_input("当前轮次", min_value=0, value=0, step=1)
        with context_cols[1]:
            n_tools = st.number_input("可用工具数", min_value=0, value=0, step=1)
        with context_cols[2]:
            tool_result_length = st.number_input("工具结果字符数", min_value=0, value=0, step=100)
    run = st.button("分析并生成路由决策", type="primary", use_container_width=True)

with right:
    note("本页面只运行本地 Router，不调用被推荐模型，不产生真实 API 成本。")
    st.markdown("#### 关注信号")
    st.caption("任务类型与复杂度决定候选池，风险和敏感性决定门禁，成本与质量决定最终策略。")

if run:
    if not task.strip():
        st.error("请输入任务描述。")
        st.stop()
    try:
        config = load_all()
        selected_mode = MODE_LABELS.get(mode_label or "规则基线", "rules")
        config.complexity.mode = selected_mode
        if selected_mode == "hybrid":
            config.complexity.hybrid.confidence_threshold = 0.70
        context = ComplexityContext.from_task(
            task,
            history=tuple(line for line in history.splitlines() if line.strip()),
            prev_assistant=prev_assistant or None,
            turn_index=int(turn_index),
            n_tools=int(n_tools),
            tool_result_length=int(tool_result_length),
        )
        decision = Router(config=config).route(task, complexity_context=context)
    except Exception as exc:
        st.error(f"路由分析失败：{exc}")
        st.stop()

    features = decision.task_features
    section_label("路由结论")
    metrics = st.columns(5)
    metrics[0].metric("任务类别", features.category.value)
    metrics[1].metric("复杂度", features.complexity.value)
    metrics[2].metric("风险", features.risk_level.value)
    metrics[3].metric("预估成本", f"¥{decision.estimated_cost:.4f}")
    metrics[4].metric("相对节省", f"{decision.estimated_savings:.1%}")

    plan_col, governance_col = st.columns([1.2, 1], gap="large")
    with plan_col:
        st.markdown("### 推荐执行方案")
        assignment = [
            {"角色": "Planner", "模型": decision.models.planner or "-"},
            {"角色": "Executor", "模型": decision.models.executor or "-"},
            {"角色": "Reviewer", "模型": decision.models.reviewer or "-"},
        ]
        st.dataframe(assignment, use_container_width=True, hide_index=True)
        st.caption(
            f"策略 {decision.recommended_strategy.value} · "
            f"预估质量 {decision.estimated_quality:.3f} · "
            f"基线成本 ¥{decision.baseline_cost:.4f}"
        )
    with governance_col:
        st.markdown("### 治理门禁")
        review_text = "需要人工复核" if decision.requires_human_review else "允许自动执行"
        st.metric("执行状态", review_text, decision.human_review_reason)
        st.write("质量门禁：" + "、".join(decision.quality_gate or ["无"]))
        st.write("预算状态：" + decision.budget_status.value)

    reason_col, diag_col = st.columns(2, gap="large")
    with reason_col:
        st.markdown("### 决策依据")
        for reason in decision.reasons:
            st.markdown(f"- {reason}")
    with diag_col:
        st.markdown("### 复杂度诊断")
        diag = decision.complexity_analysis
        if diag:
            diag_rows = [
                {"信号": "规则复杂度", "值": diag.rule_complexity},
                {"信号": "ML raw", "值": diag.ml_raw_class or "-"},
                {"信号": "ML final", "值": diag.ml_final_class or "-"},
                {"信号": "最终复杂度", "值": diag.resolved},
                {"信号": "ML 可用", "值": "是" if diag.ml_available else "否"},
                {"信号": "解析原因", "值": diag.resolution_reason},
            ]
            st.dataframe(diag_rows, use_container_width=True, hide_index=True)

    if decision.alternatives:
        st.markdown("### 替代方案")
        st.dataframe(
            [
                {
                    "策略": alt.strategy.value,
                    "Executor": alt.executor or "-",
                    "Planner": alt.planner or "-",
                    "Reviewer": alt.reviewer or "-",
                    "成本": alt.cost,
                    "质量": alt.quality,
                    "备注": alt.note,
                }
                for alt in decision.alternatives
            ],
            use_container_width=True,
            hide_index=True,
        )
