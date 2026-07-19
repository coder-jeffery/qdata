"""A2/A3 信号 + Paper 调仓测试。"""

from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

from qdata.apps.paper_flow import diff_orders, weights_to_target_shares
from qdata.apps.signal import build_signal
from qdata.brokers.base import OrderRequest


def test_weights_to_target_shares_lot():
    w = pd.DataFrame(
        {
            "trade_date": [dt.date(2026, 7, 1)] * 2,
            "exchange_code": ["A.SH", "B.SH"],
            "weight": [0.6, 0.4],
        }
    )
    prices = {"A.SH": 10.0, "B.SH": 20.0}
    shares = weights_to_target_shares(w, 100_000.0, prices, lot_size=100)
    assert shares["A.SH"] == 6000  # 60000/10 = 6000
    assert shares["B.SH"] == 2000  # 40000/20 = 2000


def test_diff_orders_buy_sell():
    current = pd.DataFrame(
        {"exchange_code": ["A.SH", "B.SH"], "quantity": [100, 500]}
    )
    target = pd.Series({"A.SH": 300, "B.SH": 0, "C.SH": 200})
    orders = diff_orders(current, target)
    assert len(orders) == 3
    by = {(o.exchange_code, o.side): o.quantity for o in orders}
    assert by[("A.SH", "buy")] == 200
    assert by[("B.SH", "sell")] == 500
    assert by[("C.SH", "buy")] == 200
    for o in orders:
        assert isinstance(o, OrderRequest)


def test_diff_orders_from_dict():
    orders = diff_orders({"X.SH": 100}, {"X.SH": 100})
    assert orders == []


@pytest.mark.integration
def test_build_signal_structure():
    try:
        from qdata import db

        df = db.query_df(
            "SELECT max(trade_date) AS d FROM factor_value WHERE factor_name='mom_20'"
        )
        if df is None or df.empty:
            pytest.skip("无 factor 数据")
        d = df.iloc[0]["d"]
        if hasattr(d, "date"):
            d = d.date()
    except Exception:
        pytest.skip("ClickHouse 不可用")

    result = build_signal(d, factor="mom_20", top_n=5, persist=False)
    assert result["signal_id"]
    assert "weights" in result
    w = result["weights"]
    if not w.empty:
        assert abs(w["weight"].sum() - 1.0) < 1e-6
        assert set(w.columns) >= {"trade_date", "exchange_code", "weight"}
    assert "meta" in result
    assert result["meta"]["dataset_version"]
