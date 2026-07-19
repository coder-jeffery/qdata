"""next_close 成交价与 ADV 约束。"""

import datetime as dt

import pandas as pd
import pytest

from qdata.research.backtest import BacktestConfig, BacktestEngine, FromWeightFrame
from qdata.research.backtest.types import Bar


def test_next_close_uses_close_price():
    cfg = BacktestConfig(
        start=dt.date(2026, 7, 1),
        end=dt.date(2026, 7, 2),
        initial_cash=1_000_000.0,
        execution="next_close",
        persist=False,
        benchmark=None,
        slippage_bps=0.0,
        commission_rate=0.0,
        commission_min=0.0,
        stamp_tax=0.0,
    )

    class G:
        @property
        def dataset_version(self):
            return "t"

        def trading_days(self, start=None, end=None):
            return [dt.date(2026, 7, 1), dt.date(2026, 7, 2)]

        def ensure_loaded(self, codes):
            return None

        def bars_on(self, d, codes):
            return {
                "600000.SH": Bar(
                    "600000.SH",
                    open=10.0,
                    close=12.0,
                    up_limit=15.0,
                    down_limit=8.0,
                )
            }

        def mark_prices(self, d, codes):
            return {"600000.SH": 12.0}

        def benchmark_returns(self, code=None):
            return pd.Series(dtype=float), "unavailable"

    w = pd.DataFrame(
        {
            "trade_date": [dt.date(2026, 7, 1)],
            "exchange_code": ["600000.SH"],
            "weight": [1.0],
        }
    )
    result = BacktestEngine(cfg, gate=G()).run(FromWeightFrame(w))
    buys = result.fills[(result.fills["side"] == "buy") & (result.fills["shares"] > 0)]
    assert not buys.empty
    assert float(buys.iloc[0]["price"]) == pytest.approx(12.0)


def test_adv_participation_caps_shares():
    cfg = BacktestConfig(
        start=dt.date(2026, 7, 1),
        end=dt.date(2026, 7, 2),
        initial_cash=10_000_000.0,
        persist=False,
        benchmark=None,
        slippage_bps=0.0,
        commission_rate=0.0,
        commission_min=0.0,
        stamp_tax=0.0,
        max_adv_participation=0.1,  # 最多 10% * volume=1000 → 100 股
    )

    class G:
        @property
        def dataset_version(self):
            return "t"

        def trading_days(self, start=None, end=None):
            return [dt.date(2026, 7, 1), dt.date(2026, 7, 2)]

        def ensure_loaded(self, codes):
            return None

        def bars_on(self, d, codes):
            return {
                "600000.SH": Bar(
                    "600000.SH",
                    open=10.0,
                    close=10.0,
                    up_limit=11.0,
                    down_limit=9.0,
                    volume=1000.0,
                )
            }

        def mark_prices(self, d, codes):
            return {"600000.SH": 10.0}

        def benchmark_returns(self, code=None):
            return pd.Series(dtype=float), "unavailable"

    w = pd.DataFrame(
        {
            "trade_date": [dt.date(2026, 7, 1)],
            "exchange_code": ["600000.SH"],
            "weight": [1.0],
        }
    )
    result = BacktestEngine(cfg, gate=G()).run(FromWeightFrame(w))
    buys = result.fills[(result.fills["side"] == "buy") & (result.fills["shares"] > 0)]
    assert not buys.empty
    assert int(buys.iloc[0]["shares"]) == 100
