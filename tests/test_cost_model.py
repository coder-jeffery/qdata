"""B408：CostModel 回测 / Paper 对齐单测。"""

from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

from qdata.brokers.base import OrderRequest
from qdata.brokers.paper import PaperBroker
from qdata.research.backtest import BacktestConfig, calc_fee
from qdata.trading.cost import DEFAULT_COST, CostModel


def test_default_matches_backtest_config():
    cfg = BacktestConfig(start=dt.date(2026, 1, 1), end=dt.date(2026, 1, 2))
    assert cfg.cost_model() == DEFAULT_COST


def test_fee_and_slippage_shared():
    cost = CostModel(
        commission_rate=0.0003,
        commission_min=5.0,
        stamp_tax=0.0005,
        slippage_bps=10.0,
    )
    assert cost.apply_slippage(10.0, "buy") == pytest.approx(10.01)
    assert cost.apply_slippage(10.0, "sell") == pytest.approx(9.99)
    assert cost.fee(1000.0, "buy") == pytest.approx(5.0)
    assert cost.fee(100_000.0, "sell") == pytest.approx(
        100_000 * 0.0003 + 100_000 * 0.0005
    )


def test_backtest_calc_fee_delegates():
    cfg = BacktestConfig(
        start=dt.date(2026, 1, 1),
        end=dt.date(2026, 1, 2),
        commission_rate=0.0003,
        commission_min=5.0,
        stamp_tax=0.0005,
    )
    assert calc_fee(1000.0, "buy", cfg) == pytest.approx(cfg.cost_model().fee(1000.0, "buy"))
    assert calc_fee(100_000.0, "sell", cfg) == pytest.approx(
        cfg.cost_model().fee(100_000.0, "sell")
    )


def test_paper_and_backtest_same_fill_economics():
    """同一名义单：Paper 现金变动与 CostModel / 回测 fee 一致。"""
    cost = CostModel()
    raw_px, qty = 10.0, 100
    fill_px, notional, fee = cost.buy_cash_need(raw_px, qty)

    broker = PaperBroker(initial_cash=100_000.0, cost=cost)
    broker.connect()
    broker.set_quotes(pd.DataFrame([{"exchange_code": "600000.SH", "price": raw_px}]))
    res = broker.place_order(OrderRequest("600000.SH", "buy", qty, price=raw_px))
    assert res.ok
    assert res.raw["price"] == pytest.approx(fill_px)
    assert res.raw["fee"] == pytest.approx(fee)
    assert broker.account()["cash"] == pytest.approx(100_000.0 - notional - fee)

    # 与回测 calc_fee 对齐
    cfg = BacktestConfig(
        start=dt.date(2026, 1, 1),
        end=dt.date(2026, 1, 2),
        commission_rate=cost.commission_rate,
        commission_min=cost.commission_min,
        stamp_tax=cost.stamp_tax,
        slippage_bps=cost.slippage_bps,
    )
    assert calc_fee(notional, "buy", cfg) == pytest.approx(fee)
    broker.disconnect()


def test_paper_zero_cost_preserves_simple_cash():
    broker = PaperBroker(initial_cash=100_000.0, cost=CostModel.zero())
    broker.connect()
    broker.set_quotes(pd.DataFrame([{"exchange_code": "600000.SH", "price": 10.0}]))
    assert broker.place_order(OrderRequest("600000.SH", "buy", 100, price=10.0)).ok
    assert broker.account()["cash"] == pytest.approx(99_000.0)
    broker.disconnect()
