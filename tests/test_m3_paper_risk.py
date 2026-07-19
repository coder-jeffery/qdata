"""M3：风控 + PaperBroker + TradingGateway 单测（无外部依赖）。"""

from __future__ import annotations

import pandas as pd
import pytest

from qdata.brokers.base import OrderRequest
from qdata.brokers.paper import PaperBroker
from qdata.risk import RiskLimits, check_order
from qdata.trading import TradingGateway
from qdata.trading.cost import DEFAULT_COST, CostModel


def _quote(code: str = "600000.SH", price: float = 10.0, **kw) -> pd.DataFrame:
    row = {
        "exchange_code": code,
        "price": price,
        "pre_close": kw.get("pre_close", price),
        "up_limit": kw.get("up_limit", round(price * 1.1, 2)),
        "down_limit": kw.get("down_limit", round(price * 0.9, 2)),
        "volume": kw.get("volume", 1_000_000),
        "is_suspended": kw.get("is_suspended", 0),
        "is_st": kw.get("is_st", 0),
    }
    return pd.DataFrame([row])


def test_risk_rejects_odd_lot_below_min():
    v = check_order(
        OrderRequest("600000.SH", "buy", 50, price=10.0),
        cash=1e6,
        quotes=_quote(),
    )
    assert not v.ok
    assert "最小下单量" in v.message


def test_risk_adjusts_odd_lot():
    v = check_order(
        OrderRequest("600000.SH", "buy", 150, price=10.0),
        cash=1e6,
        quotes=_quote(),
    )
    assert v.ok
    assert v.adjusted_qty == 100


def test_risk_rejects_limit_up_buy():
    q = _quote(price=11.0, pre_close=10.0, up_limit=11.0)
    v = check_order(
        OrderRequest("600000.SH", "buy", 100, price=11.0),
        cash=1e6,
        quotes=q,
    )
    assert not v.ok
    assert "涨停" in v.message


def test_risk_rejects_insufficient_cash():
    v = check_order(
        OrderRequest("600000.SH", "buy", 100, price=10.0),
        cash=100.0,
        quotes=_quote(),
    )
    assert not v.ok
    assert "现金不足" in v.message


def test_paper_gateway_buy_sell_roundtrip():
    """默认 CostModel 与回测一致：含滑点 + 佣金/印花税。"""
    cost = DEFAULT_COST
    broker = PaperBroker(initial_cash=100_000.0, cost=cost)
    gw = TradingGateway(broker, limits=RiskLimits())
    gw.connect()
    gw.update_quotes(_quote(price=10.0))

    buy = gw.place(OrderRequest("600000.SH", "buy", 100, price=10.0))
    assert buy.ok
    fill_b, notion_b, fee_b = cost.buy_cash_need(10.0, 100)
    cash_after_buy = 100_000.0 - notion_b - fee_b
    assert gw.account()["cash"] == pytest.approx(cash_after_buy)
    assert int(gw.positions().iloc[0]["quantity"]) == 100
    assert buy.order.raw["price"] == pytest.approx(fill_b)
    assert buy.order.raw["fee"] == pytest.approx(fee_b)

    sell = gw.place(OrderRequest("600000.SH", "sell", 100, price=10.5))
    assert sell.ok
    fill_s, notion_s, fee_s = cost.sell_cash_proceeds(10.5, 100)
    assert gw.account()["cash"] == pytest.approx(cash_after_buy + notion_s - fee_s)
    assert gw.positions().empty
    gw.disconnect()


def test_paper_gateway_zero_cost_roundtrip():
    broker = PaperBroker(initial_cash=100_000.0, cost=CostModel.zero())
    gw = TradingGateway(broker, limits=RiskLimits())
    gw.connect()
    gw.update_quotes(_quote(price=10.0))
    assert gw.place(OrderRequest("600000.SH", "buy", 100, price=10.0)).ok
    assert abs(gw.account()["cash"] - 99_000.0) < 1e-6
    assert gw.place(OrderRequest("600000.SH", "sell", 100, price=10.5)).ok
    assert abs(gw.account()["cash"] - 100_050.0) < 1e-6
    gw.disconnect()


def test_gateway_blocks_before_broker():
    broker = PaperBroker(initial_cash=100_000.0)
    gw = TradingGateway(broker)
    gw.connect()
    gw.update_quotes(_quote(price=10.0))
    bad = gw.place(OrderRequest("600000.SH", "buy", 50, price=10.0))
    assert not bad.ok
    assert abs(gw.account()["cash"] - 100_000.0) < 1e-6
    gw.disconnect()
