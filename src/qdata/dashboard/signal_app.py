"""Dashboard：研究信号台页 + A207 研判联动。"""

from __future__ import annotations

import json

import streamlit as st

from qdata.apps.signal import list_signals, load_signal
from qdata.research.judgment import judge_signal_topn


def render_signal_page(*, embedded: bool = False) -> None:
    if not embedded:
        st.title("研究信号台")

    signals = list_signals(limit=50)
    if not signals:
        st.warning("暂无信号。请先：`python -m qdata.jobs.build_signal --date ...`")
        return

    labels = [
        f"{s.get('asof', '?')} · {s.get('factor', '?')} · {s.get('weight_method', '?')} · "
        f"{s.get('signal_id', '?')[:16]}"
        for s in signals
    ]
    pick = st.selectbox("选择信号", labels, index=0, key="sig_pick")
    sig_meta = signals[labels.index(pick)]
    path = sig_meta.get("path", "")

    st.caption(
        f"signal_id `{sig_meta.get('signal_id')}` · "
        f"dataset `{sig_meta.get('dataset_version', '—')}` · "
        f"n={sig_meta.get('n_names', '—')}"
    )

    if not path:
        st.error("信号路径缺失")
        return

    data = load_signal(path)
    weights = data["weights"]
    exposure = data["exposure"]
    trad = data["tradability"]

    c1, c2, c3 = st.columns(3)
    c1.metric("成分数", sig_meta.get("n_names", len(weights)))
    c2.metric("权重和", f"{sig_meta.get('weight_sum', weights['weight'].sum()):.4f}")
    c3.metric("不可交易", sig_meta.get("non_tradable_count", 0))

    st.subheader("目标权重")
    st.dataframe(weights, use_container_width=True, hide_index=True, height=360)
    csv = weights.to_csv(index=False).encode("utf-8")
    st.download_button("导出 CSV", csv, file_name=f"weights_{sig_meta.get('signal_id')}.csv")

    # —— A207 ——
    st.subheader("研判联动（A207）")
    top_n = st.number_input("批量研判 TopN", min_value=1, max_value=100, value=min(10, max(len(weights), 1)), key="sig_j_topn")
    col_j1, col_j2 = st.columns([1, 2])
    with col_j1:
        run_batch = st.button("批量研判 TopN", type="primary", key="sig_j_batch")
    with col_j2:
        st.caption("或点击权重表下方「打开研判」跳转个股研判页")

    if run_batch:
        with st.spinner("批量研判中…"):
            try:
                result = judge_signal_topn(
                    path,
                    top_n=int(top_n),
                    include_p1=True,
                    include_brief=False,
                )
                st.session_state["sig_judgment_summary"] = result["summary"]
                st.session_state["sig_judgment_codes"] = result.get("codes") or []
            except Exception as e:
                st.error(f"批量研判失败: {e}")

    summary = st.session_state.get("sig_judgment_summary")
    if summary is not None and not getattr(summary, "empty", True):
        st.dataframe(summary, use_container_width=True, hide_index=True)
        codes = st.session_state.get("sig_judgment_codes") or summary["exchange_code"].tolist()
        jump = st.selectbox("打开个股研判", codes, key="sig_j_jump_code")
        if st.button("跳转研判页", key="sig_j_go"):
            st.session_state["j_code"] = str(jump)
            if sig_meta.get("asof"):
                st.session_state["j_asof"] = str(sig_meta["asof"])
            st.session_state["pending_nav"] = "个股研判"
            st.rerun()

    if not weights.empty:
        pick_code = st.selectbox(
            "单票跳转",
            weights["exchange_code"].astype(str).tolist(),
            key="sig_single_jump",
        )
        if st.button("打开研判", key="sig_single_go"):
            st.session_state["j_code"] = str(pick_code)
            if sig_meta.get("asof"):
                st.session_state["j_asof"] = str(sig_meta["asof"])
            st.session_state["pending_nav"] = "个股研判"
            st.rerun()

    if exposure is not None and not exposure.empty:
        st.subheader("行业暴露 vs 指数")
        st.bar_chart(exposure.set_index("industry")[["signal_weight", "index_weight"]])
        st.dataframe(exposure, use_container_width=True, hide_index=True)

    if trad is not None and not trad.empty:
        st.subheader("可交易性预览")
        bad = trad[trad.get("tradable", 1) == 0] if "tradable" in trad.columns else trad.iloc[0:0]
        st.caption(f"不可交易 {len(bad)} 只")
        st.dataframe(trad, use_container_width=True, hide_index=True, height=240)

    with st.expander("meta JSON"):
        st.code(json.dumps(data["meta"], ensure_ascii=False, indent=2, default=str), language="json")
