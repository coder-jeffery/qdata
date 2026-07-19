"""数据健康看板页（Streamlit）。"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from qdata.dashboard.health_data import (
    daily_bar_series,
    extras_lag_vs_daily_bar,
    health_summary,
    list_table_watermarks,
    recent_publications,
)


def render_health_page() -> None:
    st.caption("水位 · 发布 · 日线漂移 · extras 滞后 · 只读 CH")

    with st.sidebar:
        st.subheader("健康筛选")
        limit = st.slider("日线序列天数", 7, 90, 30, 1, key="h_days")
        pub_n = st.slider("发布记录条数", 5, 50, 15, 5, key="h_pub")
        if st.button("刷新", use_container_width=True, key="h_refresh"):
            st.cache_data.clear()

    @st.cache_data(ttl=30)
    def _summary():
        return health_summary()

    @st.cache_data(ttl=30)
    def _series(n: int):
        return daily_bar_series(n)

    @st.cache_data(ttl=30)
    def _pubs(n: int):
        return recent_publications(limit=n)

    @st.cache_data(ttl=30)
    def _lag():
        return extras_lag_vs_daily_bar()

    @st.cache_data(ttl=30)
    def _marks():
        return list_table_watermarks()

    summary = _summary()
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("证券主数据", f"{summary['security_master']:,}")
    c2.metric("日线末日", summary["daily_bar_max"] or "—")
    c3.metric("日线交易日", summary["daily_bar_days"])
    c4.metric("最新发布", summary["latest_published"] or "—")
    drift = summary.get("last_drift_pct")
    c5.metric(
        "末日漂移",
        "—" if drift is None else f"{drift:.2%}",
        help="相对上一交易日日线行数",
    )

    st.subheader("表水位")
    marks = _marks()
    mdf = pd.DataFrame(
        [
            {
                "table": m.name,
                "min_date": m.min_date,
                "max_date": m.max_date,
                "rows": m.rows,
                "days": m.days,
                "ok": m.ok,
                "note": m.note,
            }
            for m in marks
        ]
    )
    st.dataframe(mdf, use_container_width=True, hide_index=True)

    left, right = st.columns(2)
    with left:
        st.subheader("extras / 因子滞后")
        lag = _lag()
        if lag.empty:
            st.info("无滞后数据")
        else:
            st.dataframe(lag, use_container_width=True, hide_index=True)
            stale = lag[lag["status"] == "stale"]
            if not stale.empty:
                st.warning(
                    "滞后天数 > 3："
                    + ", ".join(stale["table"].astype(str).tolist())
                )
    with right:
        st.subheader("dataset_version（daily_bar）")
        pubs = _pubs(pub_n)
        if pubs.empty:
            st.info("无发布记录")
        else:
            st.dataframe(pubs, use_container_width=True, hide_index=True)

    st.subheader("日线行数与漂移")
    series = _series(limit)
    if series.empty:
        st.warning("daily_bar 为空")
        return
    chart = series.copy()
    chart["trade_date"] = pd.to_datetime(chart["trade_date"])
    st.line_chart(
        chart.set_index("trade_date")[["row_count"]],
        height=260,
    )
    show = series.copy()
    if "drift_pct" in show.columns:
        show["drift_pct"] = show["drift_pct"].map(
            lambda x: "" if pd.isna(x) else f"{float(x):.2%}"
        )
    st.dataframe(show.iloc[::-1], use_container_width=True, hide_index=True, height=320)
