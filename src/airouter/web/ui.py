"""Streamlit 页面公共样式与小组件。"""

from __future__ import annotations

import hashlib

import streamlit as st


def configure_page(title: str) -> None:
    st.set_page_config(
        page_title=f"{title} | AirRouter",
        layout="wide",
        initial_sidebar_state="auto",
    )
    st.markdown(
        """
        <style>
        :root {
            --ar-ink: #171717;
            --ar-muted: #6f6f6f;
            --ar-line: #e7e5e1;
            --ar-surface: #ffffff;
            --ar-bg: #faf9f6;
            --ar-teal: #0f766e;
            --ar-green: #2f855a;
            --ar-amber: #a65f00;
            --ar-red: #b84343;
        }
        .stApp { background: var(--ar-bg); color: var(--ar-ink); }
        [data-testid="stHeader"] { background: rgba(250, 249, 246, .92); }
        [data-testid="stSidebar"] {
            background: #f3f2ee;
            border-right: 1px solid var(--ar-line);
        }
        [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p {
            color: #40505c;
        }
        [data-testid="stSidebar"] .stButton > button {
            justify-content: flex-start;
            text-align: left;
            overflow: hidden;
        }
        [data-testid="stSidebar"] .stButton > button p {
            width: 100%;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }
        [data-testid="stSidebar"] div[data-testid="stPopover"] button {
            justify-content: center;
            text-align: center;
            min-height: 2.55rem;
            padding-left: 0;
            padding-right: 0;
        }
        [data-testid="stSidebar"] div[data-testid="stPopover"] button p {
            width: auto;
            white-space: nowrap;
            overflow: hidden;
            text-align: center;
            line-height: 1;
        }
        .block-container {
            max-width: 960px;
            padding-top: 2.4rem;
            padding-bottom: 3rem;
        }
        h1, h2, h3 { letter-spacing: 0; color: var(--ar-ink); }
        h1 { font-size: 1.75rem !important; margin-bottom: .25rem !important; }
        h2 { font-size: 1.2rem !important; margin-top: 1.5rem !important; }
        h3 { font-size: 1rem !important; }
        [data-testid="stMetric"] {
            background: var(--ar-surface);
            border: 1px solid var(--ar-line);
            border-radius: 6px;
            padding: .85rem 1rem;
            min-height: 104px;
        }
        [data-testid="stMetricLabel"] { color: var(--ar-muted); }
        [data-testid="stMetricValue"] { color: var(--ar-ink); font-size: 1.55rem; }
        [data-testid="stMetricValue"] > div {
            white-space: normal;
            overflow-wrap: anywhere;
            line-height: 1.2;
        }
        [data-testid="stDataFrame"] {
            border: 1px solid var(--ar-line);
            border-radius: 6px;
            overflow: hidden;
        }
        .ar-kicker {
            color: var(--ar-teal);
            font-size: .75rem;
            font-weight: 700;
            letter-spacing: .08em;
            text-transform: uppercase;
            margin-bottom: .25rem;
        }
        .ar-subtitle { color: var(--ar-muted); margin: 0 0 1.2rem 0; }
        .ar-status {
            display: inline-flex;
            align-items: center;
            gap: .4rem;
            color: #40505c;
            font-size: .78rem;
        }
        .ar-dot {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            display: inline-block;
            background: var(--ar-green);
        }
        .ar-dot.running { background: var(--ar-amber); }
        .ar-dot.waiting { background: var(--ar-red); }
        .ar-note {
            padding: .8rem 1rem;
            border-left: 3px solid var(--ar-teal);
            background: #eaf4f3;
            color: #294842;
            border-radius: 0 4px 4px 0;
            font-size: .88rem;
        }
        .ar-section-label {
            color: var(--ar-muted);
            font-size: .78rem;
            font-weight: 700;
            margin: 1.4rem 0 .5rem;
            text-transform: uppercase;
        }
        .ar-login-title {
            font-size: 1.55rem;
            font-weight: 700;
            color: var(--ar-ink);
            margin-bottom: .35rem;
        }
        .ar-login-copy {
            color: var(--ar-muted);
            margin-bottom: 1.2rem;
        }
        .ar-user-context {
            padding: .65rem .75rem;
            border: 1px solid var(--ar-line);
            border-radius: 6px;
            background: var(--ar-surface);
            color: #40505c;
            font-size: .82rem;
            margin-bottom: .75rem;
        }
        .ar-result-band {
            padding: .8rem 1rem;
            border: 1px solid #b9d8d4;
            border-radius: 6px;
            background: #eaf4f3;
            color: #204a45;
            margin: .4rem 0 1rem;
        }
        .ar-workspace {
            max-width: 880px;
            margin: 0 auto;
        }
        .ar-chat-header {
            font-size: 2rem;
            font-weight: 720;
            color: var(--ar-ink);
            margin: 1.2rem 0 .15rem;
            text-align: center;
        }
        .ar-chat-subtitle {
            color: var(--ar-muted);
            font-size: .98rem;
            margin-bottom: 1.45rem;
            text-align: center;
        }
        .ar-chat-thread {
            display: flex;
            flex-direction: column;
            gap: .85rem;
            margin: 0 auto 1.15rem;
        }
        .ar-chat-message {
            max-width: 76%;
            padding: .82rem 1rem;
            border-radius: 18px;
            line-height: 1.58;
            font-size: .96rem;
            color: #252525;
        }
        .ar-chat-message.user {
            margin-left: auto;
            background: #242424;
            color: white;
        }
        .ar-chat-message.assistant {
            margin-right: auto;
            background: transparent;
            padding-left: 0;
            max-width: 86%;
        }
        .ar-assistant-message {
            max-width: 86%;
            margin: 0 auto .9rem 0;
            color: #222222;
            line-height: 1.68;
            overflow-wrap: anywhere;
        }
        .ar-workspace [data-testid="stMarkdownContainer"] p {
            line-height: 1.68;
        }
        .ar-workspace [data-testid="stMarkdownContainer"] h1,
        .ar-workspace [data-testid="stMarkdownContainer"] h2,
        .ar-workspace [data-testid="stMarkdownContainer"] h3 {
            margin-top: 1rem !important;
            margin-bottom: .45rem !important;
            line-height: 1.28;
        }
        .ar-workspace [data-testid="stMarkdownContainer"] h1 {
            font-size: 1.42rem !important;
        }
        .ar-workspace [data-testid="stMarkdownContainer"] h2 {
            font-size: 1.22rem !important;
        }
        .ar-workspace [data-testid="stMarkdownContainer"] h3 {
            font-size: 1.04rem !important;
        }
        .ar-workspace [data-testid="stMarkdownContainer"] ul,
        .ar-workspace [data-testid="stMarkdownContainer"] ol {
            margin: .45rem 0 .8rem 1.25rem;
            padding-left: .75rem;
        }
        .ar-workspace [data-testid="stMarkdownContainer"] li {
            margin-bottom: .36rem;
            line-height: 1.62;
        }
        .ar-workspace [data-testid="stMarkdownContainer"] code {
            background: #eeeae2;
            color: #242424;
            border-radius: 5px;
            padding: .08rem .28rem;
            font-size: .9em;
        }
        .ar-workspace [data-testid="stMarkdownContainer"] pre {
            background: #232323;
            color: #f7f7f7;
            border-radius: 14px;
            padding: .95rem 1rem;
            overflow-x: auto;
            border: 1px solid #333333;
            margin: .75rem 0 1rem;
        }
        .ar-workspace [data-testid="stMarkdownContainer"] pre code {
            background: transparent;
            color: inherit;
            padding: 0;
            font-size: .9rem;
        }
        .ar-workspace [data-testid="stMarkdownContainer"] blockquote {
            border-left: 3px solid #d5d2cc;
            color: #4d4d4d;
            padding: .15rem 0 .15rem .8rem;
            margin: .75rem 0;
        }
        .ar-plan-card {
            border: 1px solid var(--ar-line);
            border-radius: 18px;
            background: #ffffff;
            padding: 1.05rem 1.1rem;
            margin: .9rem 0 1.1rem;
            box-shadow: 0 10px 28px rgba(25, 25, 25, .04);
        }
        .ar-plan-topline {
            display: flex;
            justify-content: space-between;
            gap: 1rem;
            color: var(--ar-muted);
            font-size: .78rem;
            margin-bottom: .3rem;
        }
        .ar-plan-title {
            font-size: 1.55rem;
            font-weight: 740;
            color: var(--ar-ink);
        }
        .ar-plan-subtitle {
            color: var(--ar-muted);
            margin: .15rem 0 1rem;
        }
        .ar-plan-metrics {
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: .55rem;
            margin: .65rem 0 1rem;
        }
        .ar-plan-metrics div {
            border: 1px solid var(--ar-line);
            border-radius: 12px;
            padding: .65rem .7rem;
            background: #fbfbfa;
        }
        .ar-plan-metrics span {
            display: block;
            color: var(--ar-muted);
            font-size: .75rem;
            margin-bottom: .2rem;
        }
        .ar-plan-metrics strong {
            display: block;
            color: var(--ar-ink);
            font-size: .98rem;
            overflow-wrap: anywhere;
        }
        .ar-plan-metrics small {
            display: block;
            color: var(--ar-muted);
            font-size: .7rem;
            line-height: 1.35;
            margin-top: .2rem;
        }
        .ar-active-plan {
            display: flex;
            align-items: center;
            gap: .55rem;
            flex-wrap: wrap;
            border: 1px solid #dedbd4;
            border-radius: 999px;
            padding: .62rem .78rem;
            margin: .2rem 0 1rem;
            background: #f6f5f0;
            color: #3b3b38;
            font-size: .88rem;
        }
        .ar-active-plan strong {
            color: #171717;
            font-weight: 760;
        }
        .ar-active-plan em {
            color: var(--ar-muted);
            font-style: normal;
        }
        .ar-review-cost-note {
            border: 1px solid #e8dfcf;
            border-radius: 12px;
            background: #fffaf0;
            color: #6e4f18;
            padding: .48rem .68rem;
            margin: .45rem 0 .95rem;
            font-size: .78rem;
            line-height: 1.45;
        }
        .ar-reason-grid {
            display: grid;
            grid-template-columns: minmax(0, 1.1fr) minmax(0, .9fr);
            gap: 1rem;
            margin-top: .5rem;
        }
        .ar-reason-grid h4 {
            font-size: .92rem;
            margin: 0 0 .35rem;
            color: var(--ar-ink);
        }
        .ar-review-card {
            border: 1px solid #d9e6e2;
            border-radius: 14px;
            background: #f7fbfa;
            padding: .85rem .9rem;
            margin: .85rem 0;
        }
        .ar-review-topline {
            color: var(--ar-teal);
            font-size: .76rem;
            font-weight: 720;
            margin-bottom: .25rem;
        }
        .ar-review-title {
            color: var(--ar-ink);
            font-size: 1rem;
            font-weight: 720;
            margin-bottom: .25rem;
        }
        .ar-review-copy {
            color: #3f4d49;
            line-height: 1.52;
        }
        .ar-execution-bar {
            display: flex;
            justify-content: space-between;
            gap: 1rem;
            padding: .74rem .9rem;
            border: 1px solid var(--ar-line);
            border-radius: 14px;
            background: #ffffff;
            color: #262626;
            margin: .8rem 0 1rem;
        }
        .ar-stream-box {
            border: 1px solid #bfd8d5;
            border-radius: 16px;
            background: #ffffff;
            color: #263642;
            line-height: 1.58;
            padding: .85rem .95rem;
            margin: .7rem 0 1rem;
            white-space: normal;
            overflow-wrap: anywhere;
        }
        .ar-thinking {
            color: var(--ar-teal);
            font-size: .78rem;
            font-weight: 720;
            margin-bottom: .45rem;
        }
        .ar-side-panel {
            border: 1px solid var(--ar-line);
            border-radius: 8px;
            background: var(--ar-surface);
            padding: 1rem;
            position: sticky;
            top: 1rem;
        }
        .ar-input-shell {
            border: 1px solid var(--ar-line);
            border-radius: 24px;
            background: #ffffff;
            padding: .78rem;
            box-shadow: 0 14px 34px rgba(25, 25, 25, .06);
            margin: 1rem 0 1.05rem;
        }
        .ar-input-shell .stTextArea textarea {
            border-radius: 18px;
            border-color: #edf0ef;
            background: #f5f8f8;
            font-size: .98rem;
            line-height: 1.55;
        }
        .ar-input-shell .stTextArea textarea:focus {
            border-color: #8ab8b2;
            box-shadow: 0 0 0 1px #8ab8b2;
        }
        .ar-composer-row {
            display: flex;
            align-items: center;
            gap: .55rem;
            color: var(--ar-muted);
            font-size: .82rem;
            margin: .15rem 0 .55rem;
        }
        .ar-composer-hint {
            color: var(--ar-muted);
            font-size: .78rem;
            margin: -.15rem 0 .45rem;
        }
        .ar-attachment-chips {
            display: flex;
            gap: .45rem;
            flex-wrap: wrap;
            margin: .15rem 0 .65rem;
        }
        .ar-attachment-chips span {
            display: inline-flex;
            align-items: center;
            max-width: 100%;
            border: 1px solid #dcd8d0;
            border-radius: 999px;
            background: #f6f5f1;
            color: #30302e;
            padding: .34rem .62rem;
            font-size: .78rem;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }
        .ar-tool-strip {
            display: flex;
            align-items: center;
            gap: .42rem;
            flex-wrap: wrap;
            border: 1px solid #d8e7e4;
            border-radius: 16px;
            background: #f3faf8;
            color: #294842;
            padding: .5rem .62rem;
            margin: .12rem 0 .68rem;
            font-size: .78rem;
        }
        .ar-tool-strip em {
            color: var(--ar-teal);
            font-style: normal;
            font-weight: 740;
            margin-right: .08rem;
        }
        .ar-tool-strip span {
            display: inline-flex;
            align-items: center;
            gap: .3rem;
            border: 1px solid #cce0dc;
            border-radius: 999px;
            background: #ffffff;
            padding: .28rem .52rem;
        }
        .ar-tool-strip strong {
            color: #173f3a;
            font-weight: 760;
        }
        div[data-testid="stPopover"] button {
            border-radius: 999px;
        }
        div[data-testid="stFileUploader"] section {
            border: 1px dashed #cfd7d5;
            border-radius: 18px;
            background: #f6faf9;
        }
        div[data-testid="stFileUploader"] small {
            color: var(--ar-muted);
        }
        .stButton > button {
            border-radius: 999px;
            border: 1px solid var(--ar-line);
            background: #ffffff;
            color: #242424;
            min-height: 2.55rem;
        }
        .stButton > button:hover {
            background: #f2f1ed;
            border-color: #d8d5cf;
            color: #171717;
        }
        [data-testid="stBaseButton-primary"] {
            background: #171717 !important;
            border-color: #171717 !important;
            color: white !important;
        }
        [data-testid="stBaseButton-primary"]:hover {
            background: #303030 !important;
            border-color: #303030 !important;
            color: white !important;
        }
        .stTabs [data-baseweb="tab-list"] { gap: 1rem; border-bottom: 1px solid var(--ar-line); }
        .stTabs [data-baseweb="tab"] { padding-left: 0; padding-right: 0; }
        div[data-testid="stExpander"] {
            border: 1px solid var(--ar-line);
            border-radius: 6px;
            background: var(--ar-surface);
        }
        @media (max-width: 700px) {
            .block-container { padding: 1rem .75rem 2rem; }
            h1 { font-size: 1.45rem !important; }
            [data-testid="stMetric"] { min-height: 92px; }
            .ar-chat-message { max-width: 100%; }
            .ar-execution-bar { flex-direction: column; }
            .ar-plan-metrics, .ar-reason-grid { grid-template-columns: 1fr; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _sidebar_navigation() -> None:
    with st.sidebar:
        st.markdown("### AirRouter")
        st.caption("先分析，再执行")
        st.divider()
        user = st.session_state.get("user_context", {})
        st.markdown(
            '<div class="ar-user-context">'
            f"<strong>{user.get('label', '当前会话')}</strong><br>"
            "API Key 已加载"
            "</div>",
            unsafe_allow_html=True,
        )
        st.page_link("app.py", label="智能工作台")
        st.caption("你的对话记录会在智能工作台里按 API Key 保留。")
        st.divider()
        with st.expander("管理员入口"):
            st.page_link("pages/1_route_workbench.py", label="高级路由分析")
            st.page_link("pages/2_consumption_dashboard.py", label="消费审计")
            st.page_link("pages/3_optimization_center.py", label="上下文优化")
            st.page_link("pages/4_benchmark_results.py", label="Benchmark 结果")
            st.page_link("pages/5_governance_config.py", label="治理配置")
        if st.button("退出登录", use_container_width=True):
            for key in {
                "authenticated",
                "user_context",
                "api_key",
                "api_key_fingerprint",
            }:
                st.session_state.pop(key, None)
            st.rerun()


def require_login() -> dict[str, str]:
    """本地 MVP 登录门禁；用户只需要输入自己的 API Key。"""
    if st.session_state.get("authenticated"):
        _sidebar_navigation()
        return dict(st.session_state.get("user_context", {}))

    left, center, right = st.columns([0.55, 1.4, 0.55])
    with center:
        st.markdown('<div class="ar-kicker">AirRouter Workspace</div>', unsafe_allow_html=True)
        st.markdown('<div class="ar-login-title">登录 AirRouter</div>', unsafe_allow_html=True)
        st.markdown(
            '<div class="ar-login-copy">输入 API Key 后进入工作台。本地 Router 会先分析；生成标题、深度复核或执行时会按需调用模型。</div>',
            unsafe_allow_html=True,
        )
        with st.form("login_form"):
            api_key = st.text_input("API Key", type="password", placeholder="sk-...")
            submitted = st.form_submit_button("进入", use_container_width=True)
        if submitted:
            if not api_key.strip():
                st.error("请输入 API Key。")
            else:
                fingerprint = hashlib.sha256(api_key.strip().encode("utf-8")).hexdigest()[:16]
                st.session_state["authenticated"] = True
                st.session_state["api_key"] = api_key.strip()
                st.session_state["api_key_fingerprint"] = fingerprint
                st.session_state["user_context"] = {
                    "label": f"API Key · {fingerprint[:6]}",
                }
                st.rerun()
    st.stop()


def page_header(title: str, subtitle: str, kicker: str = "Governance Workspace") -> None:
    st.markdown(f'<div class="ar-kicker">{kicker}</div>', unsafe_allow_html=True)
    st.title(title)
    st.markdown(f'<p class="ar-subtitle">{subtitle}</p>', unsafe_allow_html=True)


def status_line(label: str, status: str) -> None:
    status_class = "running" if status == "运行中" else ("waiting" if status == "等待续跑" else "")
    st.markdown(
        f'<div class="ar-status"><span class="ar-dot {status_class}"></span>'
        f"{label} · {status}</div>",
        unsafe_allow_html=True,
    )


def note(text: str) -> None:
    st.markdown(f'<div class="ar-note">{text}</div>', unsafe_allow_html=True)


def section_label(text: str) -> None:
    st.markdown(f'<div class="ar-section-label">{text}</div>', unsafe_allow_html=True)
