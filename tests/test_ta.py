"""日频技术指标单测。"""

from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd

from qdata.research.ta import bollinger, compute_ta, kdj, macd, sma, ta_payload


def _bars(n: int = 60) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    dates = pd.bdate_range("2026-01-02", periods=n)
    close = 100 + np.cumsum(rng.normal(0, 1, size=n))
    high = close + rng.uniform(0.2, 1.5, size=n)
    low = close - rng.uniform(0.2, 1.5, size=n)
    open_ = close + rng.normal(0, 0.3, size=n)
    return pd.DataFrame(
        {
            "trade_date": [d.date() for d in dates],
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": rng.integers(1_000_000, 5_000_000, size=n),
        }
    )


def test_sma_window() -> None:
    s = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
    out = sma(s, 3)
    assert pd.isna(out.iloc[1])
    assert abs(out.iloc[2] - 2.0) < 1e-9
    assert abs(out.iloc[4] - 4.0) < 1e-9


def test_macd_kdj_boll_shapes() -> None:
    df = _bars(80)
    m = macd(df["close"])
    assert {"dif", "dea", "macd_hist"} <= set(m.columns)
    assert m["dif"].notna().sum() > 20
    kd = kdj(df["high"], df["low"], df["close"])
    assert {"k", "d", "j"} <= set(kd.columns)
    b = bollinger(df["close"])
    assert (b["boll_upper"].iloc[-1] >= b["boll_mid"].iloc[-1] >= b["boll_lower"].iloc[-1]) or pd.isna(
        b["boll_mid"].iloc[-1]
    )


def test_compute_ta_and_payload() -> None:
    df = _bars(50)
    out = compute_ta(df)
    assert "ma5" in out.columns and "ma10" in out.columns
    payload = ta_payload(df, code="600519.SH", adjust="post")
    assert payload["code"] == "600519.SH"
    assert payload["count"] == 50
    assert payload["bars"][0]["trade_date"]
    assert "macd_hist" in payload["bars"][-1]
    # 前几日均线可为 null
    assert payload["bars"][0]["ma5"] is None or isinstance(payload["bars"][0]["ma5"], float)


def test_empty_payload() -> None:
    p = ta_payload(pd.DataFrame(), code="000001.SZ", adjust="none")
    assert p["count"] == 0
    assert p["bars"] == []
