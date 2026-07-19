"""DataAPI version as-of + 行业中性权重单测。"""

from __future__ import annotations

import datetime as dt
import pandas as pd

from qdata.api.data_api import DataAPI
from qdata.research.portfolio import target_weights


def test_asof_date_and_clamp():
    api = DataAPI.__new__(DataAPI)
    api.version = "2026-07-01"
    api.allow_unpublished = False
    assert api.asof_date() == dt.date(2026, 7, 1)
    assert api._clamp_range(dt.date(2026, 6, 1), dt.date(2026, 7, 15)) == (
        dt.date(2026, 6, 1),
        dt.date(2026, 7, 1),
    )
    assert api._clamp_range(dt.date(2026, 7, 2), dt.date(2026, 7, 15)) is None


def test_get_universe_rejects_after_asof(monkeypatch):
    api = DataAPI.__new__(DataAPI)
    api.version = "2026-07-01"
    api.allow_unpublished = False
    # 不应查库
    assert api.get_universe("ALL", dt.date(2026, 7, 2)) == []


def test_industry_neutral_weights_sum_and_balance():
    d = dt.date(2026, 7, 1)
    panel = pd.DataFrame({
        "trade_date": [d] * 4,
        "exchange_code": ["A", "B", "C", "D"],
        "close": [1, 1, 1, 1],
        "value": [1.0, 2.0, 3.0, 4.0],
        "industry": ["X", "X", "Y", "Y"],
    })
    w = target_weights(panel, method="industry_neutral")
    assert abs(w["weight"].sum() - 1.0) < 1e-9
    # 两行业总权重大致相等
    wx = w[w["exchange_code"].isin(["A", "B"])]["weight"].sum()
    wy = w[w["exchange_code"].isin(["C", "D"])]["weight"].sum()
    assert abs(wx - 0.5) < 1e-9
    assert abs(wy - 0.5) < 1e-9
    # 行业内因子大者权重大
    by = w.set_index("exchange_code")["weight"]
    assert by["B"] > by["A"]
    assert by["D"] > by["C"]
