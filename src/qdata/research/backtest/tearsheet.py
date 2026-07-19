"""简易 HTML tearsheet（无第三方依赖）。"""

from __future__ import annotations

import html
from pathlib import Path

import pandas as pd

from qdata.research.backtest.types import BacktestResult


def write_tearsheet_html(result: BacktestResult, path: Path) -> Path:
    path = Path(path)
    meta = result.meta or {}
    metrics = result.metrics or {}
    eq = result.equity_curve if result.equity_curve is not None else pd.DataFrame()

    rows = "".join(
        f"<tr><td>{html.escape(str(k))}</td><td>{html.escape(str(v))}</td></tr>"
        for k, v in sorted(metrics.items())
    )
    meta_rows = "".join(
        f"<tr><td>{html.escape(str(k))}</td><td>{html.escape(str(v))}</td></tr>"
        for k, v in meta.items()
        if k not in ("config", "warnings", "reject_reasons")
    )

    nav_poly = ""
    if not eq.empty and "nav" in eq.columns:
        nav = pd.to_numeric(eq["nav"], errors="coerce").dropna()
        if len(nav) >= 2:
            vmin, vmax = float(nav.min()), float(nav.max())
            span = (vmax - vmin) or 1.0
            w, h = 640, 180
            pts = []
            for i, v in enumerate(nav.tolist()):
                x = i / (len(nav) - 1) * (w - 20) + 10
                y = h - 10 - (float(v) - vmin) / span * (h - 20)
                pts.append(f"{x:.1f},{y:.1f}")
            nav_poly = (
                f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}">'
                f'<polyline fill="none" stroke="#222" stroke-width="2" points="{" ".join(pts)}"/>'
                f"</svg>"
            )

    doc = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8"/>
<title>backtest {html.escape(str(meta.get("run_id", "")))}</title>
<style>
body {{ font-family: ui-sans-serif, system-ui, sans-serif; margin: 24px; color: #111; }}
h1 {{ font-size: 20px; }} table {{ border-collapse: collapse; margin: 12px 0; }}
td, th {{ border: 1px solid #ddd; padding: 6px 10px; font-size: 13px; }}
th {{ text-align: left; background: #f5f5f5; }}
</style></head><body>
<h1>Backtest Tearsheet</h1>
<p>run_id={html.escape(str(meta.get("run_id", "")))} · engine={html.escape(str(meta.get("engine_version", "")))}</p>
<h2>NAV</h2>
{nav_poly or "<p>no equity</p>"}
<h2>Metrics</h2>
<table><tr><th>metric</th><th>value</th></tr>{rows}</table>
<h2>Meta</h2>
<table><tr><th>key</th><th>value</th></tr>{meta_rows}</table>
</body></html>
"""
    path.write_text(doc, encoding="utf-8")
    return path
