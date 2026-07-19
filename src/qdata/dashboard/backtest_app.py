"""回测报告 Dashboard（Streamlit）。

启动：
  python -m qdata.jobs.backtest_dashboard
  # 或
  streamlit run src/qdata/dashboard/backtest_app.py
"""

from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from qdata.dashboard.data import list_runs, load_run_detail, runs_metrics_matrix


def _fmt_metric(v) -> str:
    try:
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return "—"
        x = float(v)
        if abs(x) >= 0.01 or x == 0:
            return f"{x:.4f}"
        return f"{x:.6g}"
    except Exception:
        return str(v)


def _run_label(r) -> str:
    name = r.run_name or r.factor or "run"
    short = r.run_id[:20] + ("…" if len(r.run_id) > 20 else "")
    return f"{name} · {r.factor} · {short}"


def render_backtest_page(*, embedded: bool = False) -> None:
    """回测报告页。``embedded=True`` 时由统一 app 调用（不再 set_page_config）。"""
    if not embedded:
        st.title("qdata Backtest")
        st.caption("消费 backtest_run / Lake runs · 只读研究界面")

    with st.sidebar:
        st.subheader("回测筛选")
        limit = st.slider("最近 N 条", 5, 100, 30, 5, key="bt_limit")
        factor = st.text_input("因子过滤（空=全部）", value="", key="bt_factor")
        factor_f = factor.strip() or None
        show_matrix = st.checkbox("显示指标矩阵", value=True, key="bt_matrix")
        if st.button("刷新列表", use_container_width=True, key="bt_refresh"):
            st.cache_data.clear()

    @st.cache_data(ttl=30)
    def _cached_list(lim: int, fac: str | None):
        return list_runs(limit=lim, factor=fac)

    @st.cache_data(ttl=30)
    def _cached_matrix(lim: int, fac: str | None):
        return runs_metrics_matrix(limit=lim, factor=fac)

    runs = _cached_list(limit, factor_f)
    if not runs:
        st.warning("暂无回测 run。请先：`python -m qdata.jobs.run_backtest ...`")
        return

    if show_matrix:
        st.subheader("最近 run 指标矩阵")
        matrix = _cached_matrix(min(limit, 20), factor_f)
        if matrix.empty:
            st.info("无矩阵")
        else:
            st.dataframe(matrix, use_container_width=True, hide_index=True, height=280)
        st.divider()

    labels = [_run_label(r) for r in runs]
    id_by_label = {_run_label(r): r.run_id for r in runs}
    src_by_id = {r.run_id: r.source for r in runs}

    c1, c2 = st.columns([2, 1])
    with c1:
        pick = st.selectbox("选择 run", labels, index=0, key="bt_pick")
    with c2:
        compare_on = st.checkbox("对比第二个 run", value=False, key="bt_cmp_on")

    run_id = id_by_label[pick]
    run_id_b = None
    if compare_on:
        pick_b = st.selectbox(
            "对比 run", labels, index=min(1, len(labels) - 1), key="bt_cmp"
        )
        run_id_b = id_by_label[pick_b]

    detail = load_run_detail(run_id)
    _render_run(detail, run_id, src_by_id.get(run_id, detail.get("source", "")))

    if run_id_b and run_id_b != run_id:
        st.divider()
        st.subheader("对比")
        detail_b = load_run_detail(run_id_b)
        _render_compare(detail, detail_b, run_id, run_id_b)


def main() -> None:
    st.set_page_config(
        page_title="qdata Backtest",
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
    render_backtest_page(embedded=False)


def _render_run(detail: dict, run_id: str, source: str) -> None:
    meta = detail.get("meta") or {}
    metrics = detail.get("metrics") or {}
    equity = detail.get("equity")
    fills = detail.get("fills")

    st.markdown(
        f"**run_id** `{run_id}` · source `{source}` · "
        f"dataset `{meta.get('dataset_version', '—')}` · "
        f"bench `{meta.get('benchmark_mode', '—')}`"
    )

    # 关键指标
    keys = [
        ("total_return", "总收益"),
        ("ann_return", "年化"),
        ("sharpe", "Sharpe"),
        ("max_drawdown", "最大回撤"),
        ("turnover", "换手"),
        ("excess_total", "超额"),
        ("info_ratio", "IR"),
        ("n_fills", "成交笔数"),
        ("n_rejects", "拒单"),
    ]
    cols = st.columns(len(keys))
    for col, (k, label) in zip(cols, keys):
        col.metric(label, _fmt_metric(metrics.get(k)))

    # NAV
    st.subheader("净值曲线")
    if equity is None or getattr(equity, "empty", True):
        st.info("无 equity 数据")
    else:
        eq = equity.copy()
        eq["trade_date"] = pd.to_datetime(eq["trade_date"])
        chart_df = eq.set_index("trade_date")[["nav"]].rename(columns={"nav": "NAV"})
        st.line_chart(chart_df, height=280)
        with st.expander("净值明细"):
            show = eq.copy()
            for c in ("nav", "ret", "cash", "turnover", "cash_ratio"):
                if c in show.columns:
                    show[c] = pd.to_numeric(show[c], errors="coerce")
            st.dataframe(show, use_container_width=True, hide_index=True)

    left, right = st.columns(2)
    with left:
        st.subheader("全部指标")
        if metrics:
            mdf = pd.DataFrame(
                [{"metric": k, "value": _fmt_metric(v)} for k, v in sorted(metrics.items())]
            )
            st.dataframe(mdf, use_container_width=True, hide_index=True, height=320)
        else:
            st.info("无 metrics")
    with right:
        st.subheader("拒单原因")
        reasons = meta.get("reject_reasons") or {}
        if not reasons:
            # 从 metrics reject_* 推断
            reasons = {
                k.replace("reject_", ""): int(v)
                for k, v in metrics.items()
                if str(k).startswith("reject_") and k != "n_rejects"
            }
        if reasons:
            rdf = pd.DataFrame(
                [{"reason": k, "count": v} for k, v in sorted(reasons.items())]
            )
            st.bar_chart(rdf.set_index("reason"))
            st.dataframe(rdf, use_container_width=True, hide_index=True)
        else:
            st.info("无拒单")

    st.subheader("成交明细")
    if fills is None or getattr(fills, "empty", True):
        st.info("无 fills（可能仅 CH 归档了 equity；Lake 有完整 fills）")
    else:
        f = fills.copy()
        if "rejected_reason" in f.columns:
            mask = f["rejected_reason"].isna() | (f["rejected_reason"].astype(str).str.strip() == "")
            accepted, rejected = f[mask], f[~mask]
        else:
            accepted, rejected = f, f.iloc[0:0]
        t1, t2 = st.tabs([f"成交 ({len(accepted)})", f"拒单 ({len(rejected)})"])
        with t1:
            st.dataframe(accepted, use_container_width=True, hide_index=True, height=280)
        with t2:
            st.dataframe(rejected, use_container_width=True, hide_index=True, height=280)

    with st.expander("meta JSON"):
        st.code(json.dumps(meta, ensure_ascii=False, indent=2, default=str), language="json")


def _render_compare(a: dict, b: dict, id_a: str, id_b: str) -> None:
    ma, mb = a.get("metrics") or {}, b.get("metrics") or {}
    keys = sorted(set(ma) | set(mb))
    rows = []
    for k in keys:
        rows.append({"metric": k, "A": _fmt_metric(ma.get(k)), "B": _fmt_metric(mb.get(k))})
    st.caption(f"A=`{id_a}` · B=`{id_b}`")
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True, height=360)

    ea, eb = a.get("equity"), b.get("equity")
    if (
        ea is not None
        and eb is not None
        and not getattr(ea, "empty", True)
        and not getattr(eb, "empty", True)
    ):
        ca = ea.copy()
        cb = eb.copy()
        ca["trade_date"] = pd.to_datetime(ca["trade_date"])
        cb["trade_date"] = pd.to_datetime(cb["trade_date"])
        # 归一化到 1
        ca["NAV_A"] = pd.to_numeric(ca["nav"], errors="coerce")
        cb["NAV_B"] = pd.to_numeric(cb["nav"], errors="coerce")
        if ca["NAV_A"].iloc[0]:
            ca["NAV_A"] = ca["NAV_A"] / ca["NAV_A"].iloc[0]
        if cb["NAV_B"].iloc[0]:
            cb["NAV_B"] = cb["NAV_B"] / cb["NAV_B"].iloc[0]
        m = pd.merge(
            ca[["trade_date", "NAV_A"]],
            cb[["trade_date", "NAV_B"]],
            on="trade_date",
            how="outer",
        ).sort_values("trade_date")
        st.line_chart(m.set_index("trade_date"), height=280)


if __name__ == "__main__":
    main()
