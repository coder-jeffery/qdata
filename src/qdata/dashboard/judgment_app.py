"""个股研判看板页（Streamlit）— P0 打分 + P1 因子画像/可交易性。"""

from __future__ import annotations

import datetime as dt

import pandas as pd
import streamlit as st

from qdata.dashboard.universe_data import available_asof_dates
from qdata.research.judgment import DIMENSIONS, judge_stock


def render_judgment_page() -> None:
    st.caption("五维打分 · 相对强弱 · 因子画像 · 可交易性 · 规则简报（非 LLM）")

    dates = available_asof_dates(90)
    # A207 从信号台跳转时预填
    default_code = str(st.session_state.get("j_code") or "600000.SH")
    with st.sidebar:
        st.subheader("研判筛选")
        code = st.text_input("代码", value=default_code, key="j_code").strip().upper()
        asof = dates[0] if dates else dt.date.today()
        if dates:
            asof_options = [d.isoformat() for d in dates]
            pref = str(st.session_state.get("j_asof") or asof_options[0])
            idx = asof_options.index(pref) if pref in asof_options else 0
            pick = st.selectbox(
                "as-of",
                asof_options,
                index=idx,
                key="j_asof",
            )
            asof = dt.date.fromisoformat(pick)
        bench = st.selectbox(
            "相对强弱基准",
            ["000905.SH", "000300.SH", "000852.SH"],
            index=0,
            key="j_bench",
        )
        window = st.slider("强弱窗口(交易日)", 5, 40, 20, 1, key="j_win")
        uni = st.selectbox(
            "分位宇宙",
            ["ALL", "000905.SH", "000300.SH"],
            index=0,
            key="j_uni",
        )
        ind_lv = st.selectbox("行业分位层级", ["sw_l1", "sw_l2"], index=0, key="j_ind")
        lookback = st.slider("事件回看(日)", 5, 40, 20, 1, key="j_evt")
        if st.button("刷新", use_container_width=True, key="j_refresh"):
            st.cache_data.clear()

    @st.cache_data(ttl=60)
    def _card(c: str, d: dt.date, b: str, w: int, u: str, lv: str, lb: int):
        return judge_stock(
            c,
            d,
            benchmark=b,
            window=w,
            universe=u,
            industry_level=lv,
            event_lookback=lb,
            include_p1=True,
        )

    card = _card(code, asof, bench, window, uni, ind_lv, lookback)

    stance_color = {"偏强": "🟢", "中性": "🟡", "偏弱": "🔴", "unknown": "⚪"}
    tb = card.tradability or {}
    st.markdown(
        f"**{card.code}** @ `{card.asof}` · 立场 "
        f"{stance_color.get(card.stance, '')} **{card.stance}** · "
        f"可交易 **{tb.get('status', '—')}** · "
        f"L1 `{card.industry.get('sw_l1') or '—'}`"
    )

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("综合分", _fmt_score(card.composite))
    c2.metric(
        f"相对强弱({card.window}d)",
        _fmt_pct(card.relative_strength),
        help=f"个股收益 − {card.benchmark} 成分等权",
    )
    c3.metric("个股收益", _fmt_pct(card.stock_return))
    c4.metric("基准收益", _fmt_pct(card.bench_return))

    if card.tags:
        st.write("标签：" + " · ".join(f"`{t}`" for t in card.tags))

    brief = card.brief or {}
    if brief:
        st.subheader("研判简报")
        st.info(brief.get("headline") or "")
        for b in brief.get("bullets") or []:
            st.markdown(f"- {b}")
        with st.expander("简报正文", expanded=True):
            for i, para in enumerate(brief.get("paragraphs") or [], 1):
                st.markdown(f"{i}. {para}")
        st.download_button(
            "下载 Markdown 简报",
            data=brief.get("markdown") or "",
            file_name=f"judgment_{card.code}_{card.asof}.md",
            mime="text/markdown",
            key="j_dl_brief",
        )
        st.caption(brief.get("disclaimer") or "")

    st.subheader("五维分数")
    score_rows = []
    for dim in DIMENSIONS:
        score_rows.append(
            {
                "维度": dim,
                "分数": card.scores.get(dim),
                "分位": card.percentiles.get(dim),
                "原始因子": card.meta.get("factor_map", {}).get(dim, ""),
                "因子值": card.raw_factors.get(
                    card.meta.get("factor_map", {}).get(dim, ""), None
                ),
            }
        )
    sdf = pd.DataFrame(score_rows)
    show = sdf.copy()
    show["分数"] = show["分数"].map(_fmt_score)
    show["分位"] = show["分位"].map(_fmt_pct_rank)
    show["因子值"] = show["因子值"].map(_fmt_num)
    st.dataframe(show, use_container_width=True, hide_index=True)

    chart_df = pd.DataFrame(
        {
            "维度": DIMENSIONS,
            "分数": [card.scores.get(d) or 0.0 for d in DIMENSIONS],
        }
    ).set_index("维度")
    st.bar_chart(chart_df, height=240)

    # ----- P1 -----
    st.subheader("因子画像（全市场 / 行业内）")
    profile = card.factor_profile or []
    if not profile:
        st.info("无因子画像")
    else:
        pdf = pd.DataFrame(profile)
        show_p = pdf.copy()
        show_p["pct_market"] = show_p["pct_market"].map(_fmt_pct_rank)
        show_p["pct_industry"] = show_p["pct_industry"].map(_fmt_pct_rank)
        show_p["value"] = show_p["value"].map(_fmt_num)
        st.dataframe(
            show_p[
                [
                    "factor",
                    "value",
                    "pct_market",
                    "pct_industry",
                    "n_market",
                    "n_industry",
                ]
            ],
            use_container_width=True,
            hide_index=True,
        )
        # 双分位对比图
        plot = pdf.set_index("factor")[["pct_market", "pct_industry"]].fillna(0.0) * 100
        st.bar_chart(plot, height=260)

    st.subheader("事件与可交易性")
    if not tb:
        st.info("无可交易性数据")
    else:
        t1, t2, t3, t4, t5 = st.columns(5)
        t1.metric("状态", str(tb.get("status", "—")))
        t2.metric("涨停次数", tb.get("n_limit_up", 0))
        t3.metric("跌停次数", tb.get("n_limit_down", 0))
        t4.metric("停牌次数", tb.get("n_suspended", 0))
        lag = tb.get("finance_ann_lag_days")
        t5.metric("财务滞后(日)", "—" if lag is None else lag)
        if tb.get("notes"):
            st.write("说明：" + " · ".join(f"`{n}`" for n in tb["notes"]))
        ev = tb.get("events") or []
        if ev:
            st.dataframe(pd.DataFrame(ev), use_container_width=True, hide_index=True)
        else:
            st.caption(f"近 {tb.get('lookback_days', '—')} 日无涨跌停/停牌事件")

    with st.expander("规则说明"):
        st.markdown(
            """
**P0**
- **momentum**：`mom_20` 截面分位（越高越好）
- **volatility**：`vol_20` 反向分位
- **valuation / quality**：`ep` / `bp` 分位
- **turnover**：`turn_20` 反向分位
- **立场**：综合分 ± 相对强弱；当日不可交易时倾向偏弱

**P1**
- **因子画像**：六种子因子全市场分位 + 同行业分位
- **可交易性**：近端涨跌停/停牌/ST/个股财务公告滞后 → ok / caution / blocked

**P2**
- **简报**：固定中文模板，由分数/强弱/画像/可交易性拼装（非 LLM）
- 本模块为辅助研判，**不是**自动荐股或收益预测
            """
        )


def _fmt_score(v) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    return f"{float(v):.1f}"


def _fmt_pct(v) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    return f"{float(v):.2%}"


def _fmt_pct_rank(v) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    return f"{float(v):.0%}"


def _fmt_num(v) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    try:
        return f"{float(v):.6g}"
    except Exception:
        return str(v)
