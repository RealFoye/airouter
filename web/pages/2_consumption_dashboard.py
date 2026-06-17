"""消费审计看板。"""

from __future__ import annotations

import streamlit as st

from airouter.web.data import audit_snapshot
from airouter.web.ui import configure_page, page_header, require_login, section_label

configure_page("消费审计")
require_login()
page_header(
    "消费审计",
    "从路由决策与执行反馈中追踪成本归因、模型集中度和可优化空间。",
)

days = st.radio(
    "时间范围",
    [7, 14, 30],
    index=2,
    horizontal=True,
    format_func=lambda value: f"{value} 天",
)
snapshot = audit_snapshot(int(days or 30))

metrics = st.columns(4)
metrics[0].metric("总消费", f"¥{snapshot['total_cost']:,.2f}")
metrics[1].metric("调用次数", f"{snapshot['total_calls']:,}")
metrics[2].metric(
    "Token 总量",
    f"{snapshot['total_input_tokens'] + snapshot['total_output_tokens']:,}",
)
metrics[3].metric("预估可节省", f"¥{snapshot['total_estimated_savings']:,.2f}")

model_tab, user_tab, project_tab, waste_tab = st.tabs(["模型", "用户", "项目", "浪费模式"])
with model_tab:
    rows = [item.model_dump() for item in snapshot["by_model"]]
    if rows:
        st.bar_chart({row["key"]: row["total_cost"] for row in rows}, y_label="成本（元）")
        st.dataframe(rows, use_container_width=True, hide_index=True)
with user_tab:
    rows = [item.model_dump() for item in snapshot["by_user"]]
    st.dataframe(rows, use_container_width=True, hide_index=True)
with project_tab:
    rows = [item.model_dump() for item in snapshot["by_project"]]
    st.dataframe(rows, use_container_width=True, hide_index=True)
with waste_tab:
    rows = [
        {
            "类型": item.pattern_type,
            "范围": f"{item.scope}: {item.scope_value}",
            "次数": item.occurrence_count,
            "当前成本": item.current_cost,
            "预估节省": item.estimated_savings,
            "严重度": item.severity,
            "建议": item.suggestion,
        }
        for item in snapshot["top_waste_patterns"]
    ]
    if rows:
        st.dataframe(rows, use_container_width=True, hide_index=True)
    else:
        st.info("当前范围内未发现明显浪费模式。")

section_label("口径")
st.caption("实际执行反馈优先；缺少反馈时使用路由阶段预估值。生产成本仍应以 CCH 后台账单为准。")
