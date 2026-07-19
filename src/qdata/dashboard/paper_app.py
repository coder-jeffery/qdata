"""Dashboard：Paper 运营页（A503 / A306 / A504）。"""

from __future__ import annotations

import datetime as dt
import json

import streamlit as st

from qdata.apps.paper_flow import mark_session_eod
from qdata.apps.paper_store import compare_sessions, list_sessions, load_session


def render_paper_page(*, embedded: bool = False) -> None:
    if not embedded:
        st.title("Paper 运营")

    sessions = list_sessions(limit=30)
    if not sessions:
        st.warning("暂无 Paper session。请先：`python -m qdata.jobs.paper_rebalance ...`")
        return

    # —— A504 多 session 对比 ——
    st.subheader("会话对比（A504）")
    id_labels = {
        f"{s.get('session_id', '?')[:28]} · filled={s.get('n_filled', '?')}": s.get("session_id", "")
        for s in sessions
    }
    compare_picks = st.multiselect(
        "选择 2+ 个 session 对比",
        list(id_labels.keys()),
        default=[],
        key="paper_compare_pick",
    )
    if len(compare_picks) >= 2:
        ids = [id_labels[x] for x in compare_picks if id_labels.get(x)]
        cmp = compare_sessions(ids)
        st.dataframe(cmp, use_container_width=True, hide_index=True)
        # 简易净值对比（若有盯市/总资产）
        if "total_asset" in cmp.columns and cmp["total_asset"].notna().any():
            chart_df = cmp.set_index("session_id")[["total_asset", "mark_total_asset"]].dropna(how="all")
            if not chart_df.empty:
                st.bar_chart(chart_df)

    st.divider()
    labels = [
        f"{s.get('session_id', '?')[:28]} · filled={s.get('n_filled', '?')} "
        f"rej={s.get('n_rejected', '?')}"
        for s in sessions
    ]
    pick = st.selectbox("选择 session（明细）", labels, index=0, key="paper_pick")
    sid = sessions[labels.index(pick)].get("session_id", "")
    data = load_session(sid)
    meta = data["meta"]
    account = data["account"]

    st.caption(f"session_id `{sid}` · asof `{meta.get('asof', '—')}`")
    fe = meta.get("from_experiment") or {}
    if fe.get("enabled"):
        cell = fe.get("selected_cell") or {}
        st.info(
            f"A308 实验挂钩 · `{fe.get('experiment_id')}` → "
            f"{cell.get('factor')}/{cell.get('weight_method')} "
            f"({fe.get('rank_by')}={cell.get('rank_value')})"
        )

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("现金", f"{account.get('cash', 0):,.0f}")
    c2.metric("市值", f"{account.get('market_value', 0):,.0f}")
    c3.metric("总资产", f"{account.get('total_asset', 0):,.0f}")
    c4.metric("成交/拒单", f"{meta.get('n_filled', 0)}/{meta.get('n_rejected', 0)}")

    st.subheader("日终盯市")
    mark_latest = data.get("mark_latest") or {}
    asof_s = str(meta.get("asof") or "")
    default_mark = None
    if asof_s:
        try:
            default_mark = dt.date.fromisoformat(asof_s)
        except ValueError:
            default_mark = None
    col_a, col_b = st.columns([2, 1])
    with col_a:
        mark_date = st.date_input(
            "盯市日",
            value=default_mark or dt.date.today(),
            key="paper_mark_date",
        )
    with col_b:
        do_mark = st.button("执行盯市", type="primary", key="paper_mark_btn")

    if do_mark:
        try:
            mark = mark_session_eod(sid, mark_date=mark_date, persist=True)
            st.success(
                f"盯市完成 · 总资产 {mark.get('total_asset', 0):,.0f} · "
                f"相对初始 {mark.get('pnl_vs_initial', 0):+,.0f}"
            )
            data = load_session(sid)
            meta = data["meta"]
            mark_latest = data.get("mark_latest") or {}
        except Exception as e:
            st.error(f"盯市失败: {e}")

    if mark_latest:
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("盯市日", str(mark_latest.get("mark_date", "—")))
        m2.metric("盯市总资产", f"{mark_latest.get('total_asset', 0):,.0f}")
        m3.metric("相对初始盈亏", f"{mark_latest.get('pnl_vs_initial', 0):+,.0f}")
        m4.metric("相对调仓盈亏", f"{mark_latest.get('pnl_vs_rebalance', 0):+,.0f}")
        if mark_latest.get("pnl_vs_prev_mark") is not None:
            st.caption(f"相对上一盯市日：{mark_latest['pnl_vs_prev_mark']:+,.0f}")
    else:
        st.info("尚未盯市。可用按钮或 `python -m qdata.jobs.paper_mark --session ...`")

    marks = data.get("marks")
    if marks is not None and not marks.empty:
        with st.expander("盯市历史", expanded=False):
            show = marks.drop(
                columns=[c for c in marks.columns if c in ("session_id", "note")],
                errors="ignore",
            )
            st.dataframe(show, use_container_width=True, hide_index=True)

    st.subheader("持仓")
    pos = data["positions"]
    if pos.empty:
        st.info("无持仓")
    else:
        st.dataframe(pos, use_container_width=True, hide_index=True)

    st.subheader("成交")
    orders = data["orders"]
    if orders.empty:
        st.info("无成交")
    else:
        st.dataframe(orders, use_container_width=True, hide_index=True, height=280)

    rejects = data["rejects"]
    if rejects is not None and not rejects.empty:
        st.subheader("拒单 / 风控")
        st.dataframe(rejects, use_container_width=True, hide_index=True, height=200)

    with st.expander("meta JSON"):
        st.code(json.dumps(meta, ensure_ascii=False, indent=2, default=str), language="json")
