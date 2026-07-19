"""单票研究台（Streamlit）。"""

from __future__ import annotations

import datetime as dt

import pandas as pd
import streamlit as st

from qdata.dashboard.research_data import (
    default_range,
    load_factor_series,
    load_fundamentals,
    load_industry,
    load_price,
    latest_basic,
    seed_factors,
)


def render_research_page() -> None:
    st.caption("单票行情 · 估值 · 行业 · 因子时序 · DataAPI")

    start0, end0 = default_range()
    with st.sidebar:
        st.subheader("研究筛选")
        code = st.text_input("代码", value="600000.SH", key="r_code").strip().upper()
        start = st.date_input("开始", value=start0, key="r_start")
        end = st.date_input("结束", value=end0, key="r_end")
        adjust = st.selectbox("复权", ["post", "none", "pre"], index=0, key="r_adj")
        factor = st.selectbox("因子", seed_factors(), index=0, key="r_fac")
        if st.button("刷新", use_container_width=True, key="r_refresh"):
            st.cache_data.clear()

    if isinstance(start, dt.datetime):
        start = start.date()
    if isinstance(end, dt.datetime):
        end = end.date()
    if start > end:
        st.error("开始日不能晚于结束日")
        return

    @st.cache_data(ttl=60)
    def _px(c: str, a: dt.date, b: dt.date, adj: str):
        return load_price(c, a, b, adjust=adj)

    @st.cache_data(ttl=60)
    def _fac(c: str, f: str, a: dt.date, b: dt.date):
        return load_factor_series(c, f, a, b)

    @st.cache_data(ttl=60)
    def _meta(c: str, asof: dt.date):
        return {
            "industry": load_industry(c, asof),
            "fund": load_fundamentals(c, asof),
            "basic": latest_basic(c, asof),
        }

    px = _px(code, start, end, adjust)
    meta = _meta(code, end)
    ind = meta["industry"]
    fund = meta["fund"]
    basic = meta["basic"]

    st.markdown(
        f"**{code}** · L1 `{ind.get('sw_l1') or '—'}` · L2 `{ind.get('sw_l2') or '—'}`"
    )

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("PE_TTM", _fmt(basic.get("pe_ttm")))
    m2.metric("PB", _fmt(basic.get("pb")))
    m3.metric("总市值(万)", _fmt(basic.get("total_mv")))
    m4.metric("换手率", _fmt(basic.get("turnover_rate")))

    f1, f2, f3 = st.columns(3)
    f1.metric("净利润 PIT", _fmt(fund.get("net_profit")))
    f2.metric("净资产 PIT", _fmt(fund.get("equity")))
    f3.metric("营收 PIT", _fmt(fund.get("revenue")))

    st.subheader("价格")
    if px is None or px.empty:
        st.warning("无行情（检查代码 / 区间）")
    else:
        chart = px.copy()
        chart["trade_date"] = pd.to_datetime(chart["trade_date"])
        cols = [c for c in ("close", "open", "high", "low") if c in chart.columns]
        st.line_chart(chart.set_index("trade_date")[cols], height=280)
        with st.expander("行情明细"):
            st.dataframe(px, use_container_width=True, hide_index=True)

    st.subheader(f"因子 · {factor}")
    fac = _fac(code, factor, start, end)
    if fac.empty:
        st.info("该区间无因子值")
    else:
        fchart = fac.copy()
        fchart["trade_date"] = pd.to_datetime(fchart["trade_date"])
        st.line_chart(fchart.set_index("trade_date")[["value"]], height=220)
        st.dataframe(fac.iloc[::-1], use_container_width=True, hide_index=True)


def _fmt(v) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    try:
        x = float(v)
        if abs(x) >= 1000:
            return f"{x:,.2f}"
        return f"{x:.4g}"
    except Exception:
        return str(v)
