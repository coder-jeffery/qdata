"""FillRules 单测。"""

import datetime as dt

import pytest

from qdata.research.backtest import (
    BacktestConfig,
    Bar,
    apply_slippage,
    calc_fee,
    can_buy,
    can_sell,
    round_lot,
)


def test_round_lot_floor():
    assert round_lot(250, 100, "buy") == 200
    assert round_lot(99, 100, "buy") == 0
    assert round_lot(100.9, 100, "sell") == 100


def test_round_lot_partial():
    assert round_lot(250.7, 100, "buy", allow_partial=True) == 250


def test_slippage_buy_sell():
    assert apply_slippage(10.0, "buy", 10.0) == pytest.approx(10.01)
    assert apply_slippage(10.0, "sell", 10.0) == pytest.approx(9.99)


def test_calc_fee_commission_min_and_stamp():
    cfg = BacktestConfig(
        start=dt.date(2026, 1, 1),
        end=dt.date(2026, 1, 2),
        commission_rate=0.0003,
        commission_min=5.0,
        stamp_tax=0.0005,
    )
    # 小额成交触发最低佣金
    assert calc_fee(1000.0, "buy", cfg) == pytest.approx(5.0)
    # 卖出含印花税
    fee_sell = calc_fee(100_000.0, "sell", cfg)
    assert fee_sell == pytest.approx(100_000 * 0.0003 + 100_000 * 0.0005)


def test_can_buy_limit_up_and_suspend():
    up = Bar("600000.SH", open=10.0, close=11.0, up_limit=11.0, down_limit=9.0)
    ok, reason = can_buy(up)
    assert not ok and reason == "limit_up"

    sus = Bar("600000.SH", open=10.0, close=10.0, suspended=True)
    ok, reason = can_buy(sus)
    assert not ok and reason == "suspended"

    normal = Bar("600000.SH", open=10.0, close=10.5, up_limit=11.0, down_limit=9.0)
    assert can_buy(normal)[0]


def test_can_sell_limit_down():
    down = Bar("600000.SH", open=10.0, close=9.0, up_limit=11.0, down_limit=9.0)
    ok, reason = can_sell(down)
    assert not ok and reason == "limit_down"


def test_config_validates():
    with pytest.raises(ValueError):
        BacktestConfig(start=dt.date(2026, 2, 1), end=dt.date(2026, 1, 1))
    with pytest.raises(ValueError):
        BacktestConfig(
            start=dt.date(2026, 1, 1),
            end=dt.date(2026, 1, 2),
            commission_rate=-0.1,
        )
