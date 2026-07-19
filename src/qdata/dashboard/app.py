"""qdata 统一 Dashboard（Streamlit）。

页：数据健康 · 因子覆盖 · 选股域/行业 · 财务 PIT · 单票研究 · 个股研判 · 回测报告
     · 实验矩阵 · 信号台 · 因子监控 · Paper运营

启动：
  python -m qdata.jobs.dashboard
  streamlit run src/qdata/dashboard/app.py
"""

from __future__ import annotations

import streamlit as st

from qdata.dashboard.backtest_app import render_backtest_page
from qdata.dashboard.experiment_app import render_experiment_page
from qdata.dashboard.factor_app import render_factor_page
from qdata.dashboard.finance_app import render_finance_page
from qdata.dashboard.health_app import render_health_page
from qdata.dashboard.judgment_app import render_judgment_page
from qdata.dashboard.monitor_app import render_monitor_page
from qdata.dashboard.paper_app import render_paper_page
from qdata.dashboard.research_app import render_research_page
from qdata.dashboard.signal_app import render_signal_page
from qdata.dashboard.universe_app import render_universe_page

PAGES = {
    "数据健康": ("health", render_health_page),
    "因子覆盖": ("factors", render_factor_page),
    "选股域/行业": ("universe", render_universe_page),
    "财务 PIT": ("finance", render_finance_page),
    "单票研究": ("research", render_research_page),
    "个股研判": ("judgment", render_judgment_page),
    "回测报告": ("backtest", None),
    "实验矩阵": ("experiment", render_experiment_page),
    "信号台": ("signal", render_signal_page),
    "因子监控": ("monitor", render_monitor_page),
    "Paper运营": ("paper", render_paper_page),
}


def main() -> None:
    st.set_page_config(
        page_title="qdata Dashboard",
        page_icon=None,
        layout="wide",
        initial_sidebar_state="expanded",
    )
    st.markdown(
        """
        <style>
        .block-container { padding-top: 1.2rem; max-width: 1200px; }
        h1 { font-weight: 600; letter-spacing: -0.02em; }
        div[data-testid="stMetricValue"] { font-variant-numeric: tabular-nums; }
        </style>
        """,
        unsafe_allow_html=True,
    )

    # A207：信号台跳转研判等
    if "pending_nav" in st.session_state:
        st.session_state["nav_page"] = st.session_state.pop("pending_nav")

    with st.sidebar:
        st.title("qdata")
        page_label = st.radio("页面", list(PAGES.keys()), index=0, key="nav_page")
        st.divider()

    key, renderer = PAGES[page_label]
    st.title(page_label)
    if key == "backtest":
        render_backtest_page(embedded=True)
    elif renderer is not None:
        renderer()


if __name__ == "__main__":
    main()
