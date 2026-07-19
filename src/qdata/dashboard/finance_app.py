"""财务 PIT 质量看板页（Streamlit）。"""

from __future__ import annotations

import datetime as dt

import pandas as pd
import streamlit as st

from qdata.dashboard.finance_data import (
    ann_monthly_counts,
    finance_summary,
    lag_vs_daily_bar,
    pit_field_coverage,
)
from qdata.dashboard.universe_data import available_asof_dates


def render_finance_page() -> None:
    st.caption("公告水位 · PIT 异常 · 科目覆盖 · 相对日线滞后")

    dates = available_asof_dates(90)
    with st.sidebar:
        st.subheader("财务筛选")
        asof = dates[0] if dates else dt.date.today()
        if dates:
            pick = st.selectbox(
                "PIT as-of",
                [d.isoformat() for d in dates],
                index=0,
                key="fin_asof",
            )
            asof = dt.date.fromisoformat(pick)
        months = st.slider("月度序列月数", 6, 36, 18, 1, key="fin_months")
        if st.button("刷新", use_container_width=True, key="fin_refresh"):
            st.cache_data.clear()

    @st.cache_data(ttl=30)
    def _summary():
        return finance_summary()

    @st.cache_data(ttl=30)
    def _monthly(n: int):
        return ann_monthly_counts(n)

    @st.cache_data(ttl=30)
    def _cov(d: dt.date):
        return pit_field_coverage(d)

    @st.cache_data(ttl=30)
    def _lag():
        return lag_vs_daily_bar()

    s = _summary()
    lag = _lag()
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("财务行数", f"{s.get('rows', 0):,}")
    c2.metric("证券数", f"{s.get('securities', 0):,}")
    c3.metric("公告末日", s.get("max_ann") or "—")
    c4.metric("相对日线滞后", "—" if lag.get("lag_days") is None else f"{lag['lag_days']} 日")
    c5.metric("ann<report 异常", s.get("bad_ann_lt_report", 0))

    if lag.get("status") == "stale":
        st.warning(
            f"财务公告水位滞后日线 {lag.get('lag_days')} 天"
            f"（fin={lag.get('fin_max_ann')} / bar={lag.get('daily_bar_max')}）"
        )
    elif s.get("bad_ann_lt_report", 0) > 0:
        st.error(f"发现 {s['bad_ann_lt_report']} 条 ann_date < report_date（PIT 非法）")

    left, right = st.columns(2)
    with left:
        st.subheader("报表类型构成")
        mix = pd.DataFrame(
            [
                {"stmt_type": "income", "rows": s.get("n_income", 0)},
                {"stmt_type": "balance", "rows": s.get("n_balance", 0)},
                {"stmt_type": "cashflow", "rows": s.get("n_cashflow", 0)},
            ]
        )
        st.bar_chart(mix.set_index("stmt_type"))
        st.dataframe(mix, use_container_width=True, hide_index=True)
    with right:
        st.subheader(f"PIT 科目覆盖 @ {asof}")
        cov = _cov(asof)
        if cov.empty:
            st.info("无覆盖样本")
        else:
            show = cov.copy()
            show["coverage"] = show["coverage"].map(lambda x: f"{float(x):.1%}")
            st.dataframe(show, use_container_width=True, hide_index=True)
            st.bar_chart(cov.set_index("field")[["coverage"]])

    st.subheader("公告日按月行数")
    monthly = _monthly(months)
    if monthly.empty:
        st.info("无月度数据")
    else:
        chart = monthly.copy()
        chart["month"] = pd.to_datetime(chart["month"])
        st.line_chart(chart.set_index("month")[["rows", "securities"]], height=260)
        st.dataframe(monthly.iloc[::-1], use_container_width=True, hide_index=True)
