"""因子覆盖看板页（Streamlit）。"""

from __future__ import annotations

import datetime as dt

import pandas as pd
import streamlit as st

from qdata.dashboard.factor_data import (
    available_factor_dates,
    available_factor_names,
    factor_coverage_day,
    factor_coverage_series,
    factor_matrix_latest,
    list_factor_watermarks,
)


def render_factor_page() -> None:
    st.caption("覆盖率 · 分位数 · 按日序列 · 只读 factor_value / daily_bar")

    @st.cache_data(ttl=30)
    def _names():
        return available_factor_names()

    @st.cache_data(ttl=30)
    def _marks():
        return list_factor_watermarks()

    names = _names()
    if not names:
        st.warning("暂无因子。请先：`python -m qdata.jobs.compute_factors --date <日>`")
        return

    with st.sidebar:
        st.subheader("因子筛选")
        factor = st.selectbox("因子", names, index=0, key="f_name")
        dates = available_factor_dates(factor, limit=60)
        if not dates:
            st.warning("该因子无日期")
            return
        date_labels = [d.isoformat() for d in dates]
        pick = st.selectbox("交易日", date_labels, index=0, key="f_date")
        trade_date = dt.date.fromisoformat(pick)
        series_n = st.slider("覆盖序列天数", 5, 60, 20, 1, key="f_series_n")
        if st.button("刷新", use_container_width=True, key="f_refresh"):
            st.cache_data.clear()

    @st.cache_data(ttl=30)
    def _day(fac: str, d: dt.date):
        return factor_coverage_day(fac, d)

    @st.cache_data(ttl=30)
    def _series(fac: str, n: int):
        return factor_coverage_series(fac, limit_days=n)

    @st.cache_data(ttl=30)
    def _matrix(d: dt.date):
        return factor_matrix_latest(d)

    cov = _day(factor, trade_date)
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("有效值", f"{cov['n_valid']:,}")
    m2.metric("日线 universe", f"{cov['universe']:,}")
    m3.metric("覆盖率", f"{cov['coverage']:.1%}")
    m4.metric(
        "均值",
        "—" if cov.get("mean") is None else f"{cov['mean']:.6g}",
    )

    st.subheader("因子水位")
    marks = _marks()
    st.dataframe(marks, use_container_width=True, hide_index=True)

    left, right = st.columns(2)
    with left:
        st.subheader(f"分位数 · {factor} @ {pick}")
        qs = cov.get("quantiles") or {}
        if qs:
            qdf = pd.DataFrame(
                [{"quantile": k, "value": v} for k, v in qs.items()]
            )
            st.dataframe(qdf, use_container_width=True, hide_index=True)
        else:
            st.info("无分位数")
    with right:
        st.subheader("分布")
        vals = cov.get("values")
        if vals is not None and len(vals) > 0:
            import numpy as np

            counts, edges = np.histogram(vals.to_numpy(dtype=float), bins=30)
            mid = (edges[:-1] + edges[1:]) / 2
            hdf = pd.DataFrame({"bin": mid, "count": counts}).set_index("bin")
            st.bar_chart(hdf)
        else:
            st.info("无样本")

    st.subheader(f"覆盖率序列 · {factor}")
    series = _series(factor, series_n)
    if series.empty:
        st.info("无序列")
    else:
        chart = series.copy()
        chart["trade_date"] = pd.to_datetime(chart["trade_date"])
        st.line_chart(
            chart.set_index("trade_date")[["coverage", "n_valid"]],
            height=260,
        )
        show = series.copy()
        show["coverage"] = show["coverage"].map(lambda x: f"{float(x):.1%}")
        st.dataframe(show.iloc[::-1], use_container_width=True, hide_index=True)

    st.subheader(f"全因子矩阵 @ {pick}")
    matrix = _matrix(trade_date)
    if matrix.empty:
        st.info("无矩阵")
    else:
        show_m = matrix.copy()
        show_m["coverage"] = show_m["coverage"].map(lambda x: f"{float(x):.1%}")
        st.dataframe(show_m, use_container_width=True, hide_index=True)
        # 覆盖率柱
        bar = matrix.set_index("factor")[["coverage"]]
        st.bar_chart(bar)
