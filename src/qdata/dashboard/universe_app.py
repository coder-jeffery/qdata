"""选股域 / 行业 PIT 看板页（Streamlit）。"""

from __future__ import annotations

import datetime as dt

import pandas as pd
import streamlit as st

from qdata.dashboard.universe_data import (
    DEFAULT_INDEXES,
    available_asof_dates,
    index_size_history,
    index_universe_sizes,
    industry_coverage,
    industry_distribution,
)


def render_universe_page() -> None:
    st.caption("指数成分 PIT · 行业分布 · 覆盖率 · 只读 index_member / industry_member")

    dates = available_asof_dates(90)
    if not dates:
        st.warning("无 daily_bar 交易日，无法做 as-of 切片")
        return

    with st.sidebar:
        st.subheader("选股域筛选")
        pick = st.selectbox(
            "as-of 日",
            [d.isoformat() for d in dates],
            index=0,
            key="u_date",
        )
        trade_date = dt.date.fromisoformat(pick)
        level = st.selectbox("行业层级", ["sw_l1", "sw_l2"], index=0, key="u_level")
        idx_opts = ["ALL", *DEFAULT_INDEXES]
        scope = st.selectbox("行业分布范围", idx_opts, index=0, key="u_scope")
        hist_idx = st.selectbox("规模序列指数", list(DEFAULT_INDEXES), index=1, key="u_hist")
        hist_n = st.slider("规模序列天数", 10, 90, 40, 5, key="u_hist_n")
        if st.button("刷新", use_container_width=True, key="u_refresh"):
            st.cache_data.clear()

    @st.cache_data(ttl=30)
    def _sizes(d: dt.date):
        return index_universe_sizes(d)

    @st.cache_data(ttl=30)
    def _cov(d: dt.date, lv: str):
        return industry_coverage(d, level=lv)

    @st.cache_data(ttl=30)
    def _dist(d: dt.date, lv: str, scope_idx: str):
        code = None if scope_idx == "ALL" else scope_idx
        return industry_distribution(d, level=lv, index_code=code)

    @st.cache_data(ttl=30)
    def _hist(idx: str, n: int):
        return index_size_history(idx, limit_days=n)

    sizes = _sizes(trade_date)
    cov = _cov(trade_date, level)

    cols = st.columns(max(len(sizes), 1))
    for i, row in sizes.iterrows():
        cols[int(i) % len(cols)].metric(str(row["index_code"]), f"{int(row['members']):,}")

    c1, c2, c3 = st.columns(3)
    c1.metric("行业映射覆盖", f"{cov['coverage']:.1%}")
    c2.metric("已映射", f"{cov['mapped']:,} / {cov['universe']:,}")
    c3.metric("行业数", cov["n_industries"])

    left, right = st.columns(2)
    with left:
        st.subheader(f"行业分布 · {level} · {scope} @ {pick}")
        dist = _dist(trade_date, level, scope)
        if dist.empty:
            st.info("无行业数据（可 sync_industry_member）")
        else:
            show = dist.copy()
            show["weight"] = show["weight"].map(lambda x: f"{float(x):.1%}")
            st.dataframe(
                show[["industry_name", "members", "weight", "industry"]],
                use_container_width=True,
                hide_index=True,
                height=360,
            )
    with right:
        st.subheader("家数柱状图")
        if not dist.empty:
            top = dist.head(25).set_index("industry_name")[["members"]]
            st.bar_chart(top, height=360)
        else:
            st.info("无图")

    st.subheader(f"指数成分规模序列 · {hist_idx}")
    hist = _hist(hist_idx, hist_n)
    if hist.empty:
        st.info("无序列")
    else:
        chart = hist.copy()
        chart["trade_date"] = pd.to_datetime(chart["trade_date"])
        st.line_chart(chart.set_index("trade_date")[["members"]], height=260)
        st.dataframe(hist.iloc[::-1], use_container_width=True, hide_index=True)
