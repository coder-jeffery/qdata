"""单票日频技术指标：MA / MACD / KDJ / 布林带。

输入为含 open/high/low/close/volume 的日线 DataFrame（通常来自 DataAPI.get_price）。
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def sma(series: pd.Series, window: int) -> pd.Series:
    return series.astype(float).rolling(window, min_periods=window).mean()


def ema(series: pd.Series, span: int) -> pd.Series:
    return series.astype(float).ewm(span=span, adjust=False, min_periods=span).mean()


def macd(
    close: pd.Series,
    *,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> pd.DataFrame:
    c = close.astype(float)
    dif = ema(c, fast) - ema(c, slow)
    dea = dif.ewm(span=signal, adjust=False, min_periods=signal).mean()
    hist = (dif - dea) * 2.0  # 国内常用柱 = 2*(DIF-DEA)
    return pd.DataFrame({"dif": dif, "dea": dea, "macd_hist": hist})


def kdj(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    *,
    n: int = 9,
    m1: int = 3,
    m2: int = 3,
) -> pd.DataFrame:
    h = high.astype(float)
    l = low.astype(float)
    c = close.astype(float)
    lowest = l.rolling(n, min_periods=n).min()
    highest = h.rolling(n, min_periods=n).max()
    span = (highest - lowest).replace(0, np.nan)
    rsv = ((c - lowest) / span * 100.0).fillna(50.0)
    k = rsv.ewm(alpha=1.0 / m1, adjust=False).mean()
    d = k.ewm(alpha=1.0 / m2, adjust=False).mean()
    j = 3.0 * k - 2.0 * d
    return pd.DataFrame({"k": k, "d": d, "j": j})


def bollinger(
    close: pd.Series,
    *,
    window: int = 20,
    num_std: float = 2.0,
) -> pd.DataFrame:
    mid = sma(close, window)
    std = close.astype(float).rolling(window, min_periods=window).std(ddof=0)
    upper = mid + num_std * std
    lower = mid - num_std * std
    return pd.DataFrame({"boll_mid": mid, "boll_upper": upper, "boll_lower": lower})


def compute_ta(bars: pd.DataFrame) -> pd.DataFrame:
    """在日线表上追加 MA5/10、MACD、KDJ、布林带列。"""
    if bars is None or bars.empty:
        return pd.DataFrame()
    df = bars.copy()
    df = df.sort_values("trade_date").reset_index(drop=True)
    for col in ("open", "high", "low", "close", "volume"):
        if col not in df.columns:
            raise ValueError(f"compute_ta 缺少列: {col}")
    close = df["close"]
    df["ma5"] = sma(close, 5)
    df["ma10"] = sma(close, 10)
    df = pd.concat([df, macd(close), kdj(df["high"], df["low"], close), bollinger(close)], axis=1)
    return df


def ta_payload(
    bars: pd.DataFrame,
    *,
    code: str,
    adjust: str,
) -> dict[str, Any]:
    """供 BFF / Web 使用的 JSON 友好结构。"""
    df = compute_ta(bars)
    if df.empty:
        return {
            "code": code,
            "adjust": adjust,
            "count": 0,
            "bars": [],
        }
    cols = [
        "trade_date",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "ma5",
        "ma10",
        "boll_mid",
        "boll_upper",
        "boll_lower",
        "dif",
        "dea",
        "macd_hist",
        "k",
        "d",
        "j",
    ]
    rows: list[dict[str, Any]] = []
    for _, r in df.iterrows():
        item: dict[str, Any] = {}
        for c in cols:
            if c not in r.index:
                continue
            v = r[c]
            if c == "trade_date":
                item[c] = str(v)[:10]
            elif pd.isna(v):
                item[c] = None
            else:
                item[c] = float(v) if c != "volume" else int(float(v))
        rows.append(item)
    last = rows[-1]
    return {
        "code": code,
        "adjust": adjust,
        "count": len(rows),
        "start": rows[0]["trade_date"],
        "end": last["trade_date"],
        "last_close": last.get("close"),
        "bars": rows,
    }
