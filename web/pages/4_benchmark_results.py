"""Benchmark 结果中心。"""

from __future__ import annotations

import streamlit as st

from airouter.web.data import (
    benchmark_history,
    current_routing_progress,
    finance_category_summary,
    finance_model_summary,
    latest_finance_run,
    latest_routing_run,
    read_report,
    routing_run_summary,
    routing_strategy_summary,
)
from airouter.web.ui import (
    configure_page,
    note,
    page_header,
    require_login,
    section_label,
    status_line,
)

configure_page("Benchmark 结果")
require_login()
page_header(
    "Benchmark 结果",
    "查看真实模型质量、成本、路由策略回放和当前全量任务进度。",
)

progress = current_routing_progress()
if progress:
    status_line(f"当前 Routing Run · {progress.run_id}", progress.status)
    cols = st.columns(4)
    cols[0].metric("完成", f"{progress.completed}/{progress.expected}")
    cols[1].metric("成功", progress.succeeded)
    cols[2].metric("失败", progress.failed)
    cols[3].metric("估算成本", f"¥{progress.cost_cny:.2f}")
    st.progress(progress.progress)
    st.caption(f"最近写入：{progress.updated_at:%Y-%m-%d %H:%M:%S}")

finance_tab, routing_tab, history_tab = st.tabs(["Finance", "Routing Ground Truth", "运行历史"])

with finance_tab:
    finance_run = latest_finance_run()
    if finance_run:
        st.caption(f"Run ID: {finance_run.name}")
    finance_rows = finance_model_summary(finance_run)
    if finance_rows:
        st.dataframe(finance_rows, use_container_width=True, hide_index=True)
        chart_data = {row["模型"]: row["综合分"] for row in finance_rows}
        st.bar_chart(chart_data, y_label="综合分")
        with st.expander("分类别结果"):
            st.dataframe(
                finance_category_summary(finance_run),
                use_container_width=True,
                hide_index=True,
            )
        report_path = finance_run / "finance_report.md" if finance_run else None
        if report_path and report_path.exists():
            with st.expander("中文报告预览"):
                st.markdown(read_report(report_path))
    else:
        st.info("暂无 Finance Benchmark 结果。")

with routing_tab:
    routing_run = latest_routing_run()
    summary = routing_run_summary(routing_run)
    if routing_run:
        st.caption(f"最近已完成 Run ID: {routing_run.name}")
    if summary:
        metrics = st.columns(4)
        metrics[0].metric("Cases", summary.get("total_cases", 0))
        metrics[1].metric("模型调用", summary.get("total_physical_api_calls", 0))
        metrics[2].metric("估算成本", f"¥{float(summary.get('total_estimated_cost_cny', 0.0)):.2f}")
        metrics[3].metric("Run 状态", "完成" if summary.get("run_completed") else "分析中")
        strategy_rows = routing_strategy_summary(routing_run)
        st.dataframe(strategy_rows, use_container_width=True, hide_index=True)
        if routing_run and (routing_run / "report.md").exists():
            with st.expander("路由报告预览"):
                st.markdown(read_report(routing_run / "report.md"))
    else:
        st.info("暂无 Routing Benchmark 结果。")

with history_tab:
    st.dataframe(benchmark_history(), use_container_width=True, hide_index=True)

section_label("数据边界")
note("Benchmark 页面不会启动、续跑或修改任何任务。API 估算成本仅作实验分析，最终账单需用 CCH usage CSV 对账。")
