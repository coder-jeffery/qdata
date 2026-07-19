"""Dashboard：策略实验矩阵页。"""

from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from qdata.apps.experiment import list_experiments, load_experiment_summary


def render_experiment_page(*, embedded: bool = False) -> None:
    if not embedded:
        st.title("策略实验矩阵")

    exps = list_experiments(limit=30)
    if not exps:
        st.warning("暂无实验。请先：`python -m qdata.jobs.run_experiment_matrix ...`")
        return

    labels = [
        f"{e.get('experiment_id', '?')[:24]}… · ok={e.get('n_ok', '?')}/{e.get('n_cells', '?')}"
        for e in exps
    ]
    pick = st.selectbox("选择实验", labels, index=0, key="exp_pick")
    exp = exps[labels.index(pick)]
    eid = exp.get("experiment_id", "")

    st.caption(f"experiment_id `{eid}` · path `{exp.get('path', '')}`")
    with st.expander("meta JSON"):
        st.code(json.dumps(exp, ensure_ascii=False, indent=2, default=str), language="json")

    summary = load_experiment_summary(eid)
    if summary.empty:
        st.info("无 summary 表")
        return

    st.subheader("指标对比")
    show_cols = [
        c
        for c in summary.columns
        if c
        in (
            "factor",
            "weight_method",
            "status",
            "total_return",
            "ann_return",
            "sharpe",
            "max_drawdown",
            "turnover",
            "excess_total",
            "info_ratio",
            "n_fills",
            "error",
        )
    ]
    st.dataframe(summary[show_cols] if show_cols else summary, use_container_width=True, hide_index=True)

    ok = summary[summary.get("status", pd.Series()) == "ok"] if "status" in summary.columns else summary
    if not ok.empty and "sharpe" in ok.columns:
        st.subheader("Sharpe 透视")
        try:
            pivot = ok.pivot_table(index="factor", columns="weight_method", values="sharpe", aggfunc="first")
            st.dataframe(pivot, use_container_width=True)
        except Exception:
            pass

    md_path = exp.get("path", "") + "/summary.md" if exp.get("path") else ""
    if md_path:
        from pathlib import Path

        p = Path(md_path)
        if p.is_file():
            with st.expander("summary.md"):
                st.markdown(p.read_text(encoding="utf-8"))
