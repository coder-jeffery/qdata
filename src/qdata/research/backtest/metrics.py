"""回测绩效指标。"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

_TRADING_DAYS_YEAR = 242.0


def compute_metrics(
    equity_curve: pd.DataFrame,
    *,
    benchmark_rets: pd.Series | None = None,
    turnover_series: pd.Series | None = None,
    cash_ratios: pd.Series | None = None,
) -> dict[str, float]:
    """equity_curve 需含 trade_date, nav；可选 ret。"""
    out: dict[str, float] = {}
    if equity_curve is None or equity_curve.empty:
        return out

    df = equity_curve.sort_values("trade_date").copy()
    nav = pd.to_numeric(df["nav"], errors="coerce").astype(float)
    if "ret" in df.columns:
        rets = pd.to_numeric(df["ret"], errors="coerce").astype(float)
    else:
        rets = nav.pct_change()
    rets = rets.replace([np.inf, -np.inf], np.nan).dropna()

    nav0 = float(nav.iloc[0])
    nav1 = float(nav.iloc[-1])
    if nav0 > 0 and math.isfinite(nav0) and math.isfinite(nav1):
        total = nav1 / nav0 - 1.0
    else:
        total = float("nan")
    out["total_return"] = float(total)

    n = max(len(rets), 1)
    if math.isfinite(total) and n > 1:
        out["ann_return"] = float((1.0 + total) ** (_TRADING_DAYS_YEAR / n) - 1.0)
    else:
        out["ann_return"] = float("nan")

    if len(rets) >= 2:
        vol = float(rets.std(ddof=1) * math.sqrt(_TRADING_DAYS_YEAR))
    else:
        vol = float("nan")
    out["ann_vol"] = vol

    if math.isfinite(out["ann_return"]) and math.isfinite(vol) and vol > 0:
        out["sharpe"] = float(out["ann_return"] / vol)
    else:
        out["sharpe"] = float("nan")

    # max drawdown
    peak = nav.cummax()
    dd = nav / peak - 1.0
    mdd = float(dd.min()) if len(dd) else float("nan")
    out["max_drawdown"] = mdd
    if math.isfinite(out["ann_return"]) and math.isfinite(mdd) and mdd < 0:
        out["calmar"] = float(out["ann_return"] / abs(mdd))
    else:
        out["calmar"] = float("nan")

    if turnover_series is not None and len(turnover_series):
        out["turnover"] = float(pd.to_numeric(turnover_series, errors="coerce").mean())
    elif "turnover" in df.columns:
        out["turnover"] = float(pd.to_numeric(df["turnover"], errors="coerce").mean())
    else:
        out["turnover"] = float("nan")

    if cash_ratios is not None and len(cash_ratios):
        out["avg_cash"] = float(pd.to_numeric(cash_ratios, errors="coerce").mean())
    elif "cash_ratio" in df.columns:
        out["avg_cash"] = float(pd.to_numeric(df["cash_ratio"], errors="coerce").mean())
    else:
        out["avg_cash"] = float("nan")

    if len(rets):
        out["hit_ratio"] = float((rets > 0).mean())
    else:
        out["hit_ratio"] = float("nan")

    if benchmark_rets is not None and len(benchmark_rets):
        dates = [_to_date(x) for x in df["trade_date"].tolist()]
        strat = pd.Series(nav.pct_change().to_numpy(), index=dates).dropna()
        b = benchmark_rets.copy()
        b.index = [_to_date(x) for x in b.index]
        common = strat.index.intersection(b.index)
        if len(common) >= 2:
            er = strat.loc[common] - b.loc[common]
            out["excess_total"] = float((1.0 + er).prod() - 1.0)
            ev = float(er.std(ddof=1) * math.sqrt(_TRADING_DAYS_YEAR))
            out["excess_ann_vol"] = ev
            ea = float(er.mean() * _TRADING_DAYS_YEAR)
            out["excess_ann_return"] = ea
            out["info_ratio"] = float(ea / ev) if ev > 0 else float("nan")
    return out


def _to_date(v):
    import datetime as dt

    if isinstance(v, dt.datetime):
        return v.date()
    if isinstance(v, dt.date):
        return v
    return pd.Timestamp(v).date()
