"""Dashboard：因子监控页。"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import streamlit as st

from qdata.apps.factor_monitor import load_monitor_coverage, load_monitor_report
from qdata.config import settings


def _list_monitor_dates(limit: int = 30) -> list[dt.date]:
    root = Path(settings().lake_root) / "factor_monitor"
    if not root.is_dir():
        return []
    out: list[dt.date] = []
    for p in sorted(root.iterdir(), reverse=True):
        if p.is_dir() and (p / "report.json").is_file():
            try:
                out.append(dt.date.fromisoformat(p.name))
            except ValueError:
                continue
        if len(out) >= limit:
            break
    return out


def render_monitor_page(*, embedded: bool = False) -> None:
    if not embedded:
        st.title("因子监控")

    dates = _list_monitor_dates()
    if not dates:
        st.warning("暂无监控报告。请先：`python -m qdata.jobs.monitor_factors --date ...`")
        return

    pick = st.selectbox("选择日期", [d.isoformat() for d in dates], index=0, key="mon_date")
    d = dt.date.fromisoformat(pick)

    report = load_monitor_report(d)
    coverage = load_monitor_coverage(d)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("universe", report.get("universe_size", "—"))
    c2.metric("告警数", report.get("n_alerts", 0))
    c3.metric("阈值", f"{report.get('min_coverage', 0.9):.0%}")
    via = report.get("via") or "—"
    c4.metric("来源", "日批" if via == "daily_run" else str(via))
    if via == "daily_run":
        st.caption("本报告由 `daily_run --post-m2` 软挂生成（A405）")

    st.subheader("覆盖率")
    if coverage.empty:
        st.info("无 coverage 数据")
    else:
        st.bar_chart(coverage.set_index("factor_name")["coverage"])
        st.dataframe(coverage, use_container_width=True, hide_index=True)

    alerts = report.get("alerts") or []
    if alerts:
        st.subheader("告警")
        for a in alerts:
            st.warning(a.get("message", str(a)))

    quintiles = report.get("quintiles") or {}
    if quintiles:
        st.subheader("分层前瞻收益（T→T+1）")
        for fn, q in quintiles.items():
            with st.expander(f"{fn} · spread={q.get('spread_q5_q1', 0):.4f}"):
                st.json(q)

    with st.expander("report.json"):
        st.code(json.dumps(report, ensure_ascii=False, indent=2, default=str), language="json")
