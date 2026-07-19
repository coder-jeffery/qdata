"""BrokerSim / Ledger 单测。"""

import datetime as dt

import pandas as pd
import pytest

from qdata.research.backtest import (
    BacktestConfig,
    Bar,
    BrokerSim,
    PortfolioLedger,
)


def _cfg(**kwargs) -> BacktestConfig:
    base = dict(
        start=dt.date(2026, 7, 1),
        end=dt.date(2026, 7, 15),
        initial_cash=1_000_000.0,
        slippage_bps=0.0,  # 便于断言价格
        commission_rate=0.0,
        commission_min=0.0,
        stamp_tax=0.0,
    )
    base.update(kwargs)
    return BacktestConfig(**base)  # type: ignore[arg-type]


def test_ledger_cash_only_nav():
    led = PortfolioLedger(1_000_000.0)
    assert led.nav({}) == pytest.approx(1_000_000.0)
    snap = led.snapshot(dt.date(2026, 7, 1), {})
    assert snap.nav == pytest.approx(1_000_000.0)
    assert snap.positions == {}


def test_rebalance_100pct_single_name():
    cfg = _cfg()
    led = PortfolioLedger(cfg.initial_cash)
    broker = BrokerSim(cfg)
    d = dt.date(2026, 7, 2)
    bars = {
        "600000.SH": Bar(
            "600000.SH",
            open=10.0,
            close=10.2,
            up_limit=11.0,
            down_limit=9.0,
        )
    }
    w = pd.DataFrame({"exchange_code": ["600000.SH"], "weight": [1.0]})
    fills = broker.rebalance_to_weights(d, w, led, bars)
    accepted = [f for f in fills if f.accepted]
    assert len(accepted) == 1
    f = accepted[0]
    assert f.side == "buy"
    assert f.shares == 100_000  # 1e6 / 10
    assert f.price == pytest.approx(10.0)
    assert led.position("600000.SH") == 100_000
    assert led.cash == pytest.approx(0.0)
    assert led.nav({"600000.SH": 10.0}) == pytest.approx(1_000_000.0)


def test_limit_up_rejects_buy_keeps_cash():
    cfg = _cfg()
    led = PortfolioLedger(cfg.initial_cash)
    broker = BrokerSim(cfg)
    d = dt.date(2026, 7, 2)
    bars = {
        "600000.SH": Bar(
            "600000.SH",
            open=10.0,
            close=11.0,
            up_limit=11.0,
            down_limit=9.0,
        )
    }
    w = pd.DataFrame({"exchange_code": ["600000.SH"], "weight": [1.0]})
    fills = broker.rebalance_to_weights(d, w, led, bars)
    assert any(f.rejected_reason == "limit_up" for f in fills)
    assert led.position("600000.SH") == 0
    assert led.cash == pytest.approx(cfg.initial_cash)


def test_suspended_rejects():
    cfg = _cfg()
    led = PortfolioLedger(cfg.initial_cash)
    # 先建仓
    bars_ok = {
        "600000.SH": Bar("600000.SH", open=10.0, close=10.0, up_limit=11.0, down_limit=9.0)
    }
    BrokerSim(cfg).rebalance_to_weights(
        dt.date(2026, 7, 2),
        pd.DataFrame({"exchange_code": ["600000.SH"], "weight": [1.0]}),
        led,
        bars_ok,
    )
    assert led.position("600000.SH") > 0

    # 停牌无法卖出换仓到另一只
    bars_sus = {
        "600000.SH": Bar(
            "600000.SH", open=10.0, close=10.0, up_limit=11.0, down_limit=9.0, suspended=True
        ),
        "000001.SZ": Bar("000001.SZ", open=20.0, close=20.0, up_limit=22.0, down_limit=18.0),
    }
    fills = BrokerSim(cfg).rebalance_to_weights(
        dt.date(2026, 7, 3),
        pd.DataFrame({"exchange_code": ["000001.SZ"], "weight": [1.0]}),
        led,
        bars_sus,
    )
    assert any(f.rejected_reason == "suspended" and f.side == "sell" for f in fills)
    # 原持仓未卖掉
    assert led.position("600000.SH") > 0


def test_sell_then_buy_and_fees():
    cfg = _cfg(commission_rate=0.0003, commission_min=5.0, stamp_tax=0.0005)
    led = PortfolioLedger(cfg.initial_cash)
    broker = BrokerSim(cfg)
    bars = {
        "AAA.SH": Bar("AAA.SH", open=10.0, close=10.0, up_limit=11.0, down_limit=9.0),
        "BBB.SH": Bar("BBB.SH", open=20.0, close=20.0, up_limit=22.0, down_limit=18.0),
    }
    BrokerSim(_cfg()).rebalance_to_weights(
        dt.date(2026, 7, 2),
        pd.DataFrame({"exchange_code": ["AAA.SH"], "weight": [1.0]}),
        led,
        {"AAA.SH": bars["AAA.SH"]},
    )
    # 换仓到 BBB
    fills = broker.rebalance_to_weights(
        dt.date(2026, 7, 3),
        pd.DataFrame({"exchange_code": ["BBB.SH"], "weight": [1.0]}),
        led,
        bars,
    )
    sells = [f for f in fills if f.accepted and f.side == "sell"]
    buys = [f for f in fills if f.accepted and f.side == "buy"]
    assert sells and buys
    assert sells[0].fee > 0  # 印花税+佣金
    assert led.position("AAA.SH") == 0
    assert led.position("BBB.SH") > 0


def test_renormalize_weights():
    cfg = _cfg()
    led = PortfolioLedger(cfg.initial_cash)
    bars = {
        "A.SH": Bar("A.SH", open=10.0, close=10.0, up_limit=11.0, down_limit=9.0),
        "B.SH": Bar("B.SH", open=10.0, close=10.0, up_limit=11.0, down_limit=9.0),
    }
    w = pd.DataFrame({"exchange_code": ["A.SH", "B.SH"], "weight": [1.0, 1.0]})
    fills = BrokerSim(cfg).rebalance_to_weights(dt.date(2026, 7, 2), w, led, bars)
    assert any(f.accepted for f in fills)
    # 约各半仓
    assert led.position("A.SH") == pytest.approx(led.position("B.SH"), abs=100)
