"""治理配置与模型目录。"""

from __future__ import annotations

import streamlit as st

from airouter.web.data import governance_config, model_catalog
from airouter.web.ui import configure_page, note, page_header, require_login, section_label

configure_page("治理配置")
require_login()
page_header(
    "治理配置",
    "集中查看模型 Tier、价格、预算门禁和复杂度分析模式。",
)

config = governance_config()
metrics = st.columns(4)
metrics[0].metric("正式复杂度模式", str(config["complexity_mode"]).upper())
metrics[1].metric("Hybrid 阈值", f"{config['hybrid_threshold']:.2f}")
metrics[2].metric("月度预算", f"¥{config['monthly_budget']:,.0f}")
metrics[3].metric("单任务默认预算", f"¥{config['task_budget']:.2f}")

section_label("模型目录")
catalog = model_catalog()
tier_filter = st.multiselect("Tier", [1, 2, 3], default=[1, 2, 3])
st.dataframe(
    [row for row in catalog if row["Tier"] in tier_filter],
    use_container_width=True,
    hide_index=True,
)

left, right = st.columns(2, gap="large")
with left:
    st.markdown("### 复杂度融合")
    st.json({
        "mode": config["complexity_mode"],
        "bundle_dir": config["bundle_dir"] or "未通过配置指定",
        "confidence_threshold": config["hybrid_threshold"],
        "allow_upgrade": config["hybrid_allow_upgrade"],
        "allow_downgrade": config["hybrid_allow_downgrade"],
    })
with right:
    st.markdown("### Tier 约束")
    st.json(config["allowed_tiers"])

section_label("人工审核")
if config["human_review_tasks"]:
    st.write("、".join(config["human_review_tasks"]))
else:
    st.caption("没有按任务类型强制配置人工审核；Gate 仍会根据风险、降级和预算动态判断。")

note("该页当前为只读配置视图，避免演示环境误改生产路由。")
