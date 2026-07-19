"""基准超额与拒单统计。"""

import datetime as dt

import pandas as pd
import pytest

from qdata.research.backtest import BacktestConfig, BacktestEngine, FromWeightFrame
from qdata.research.backtest.types import Bar


class _GateWithBench:
    def __init__(self) -> None:
        self.days = [dt.date(2026, 7, 1), dt.date(2026, 7, 2), dt.date(2026, 7, 3)]
        self.px = {
            dt.date(2026, 7, 1): 10.0,
            dt.date(2026, 7, 2): 10.0,
            dt.date(2026, 7, 3): 12.0,  # +20% after buy on day2
        }

    @property
    def dataset_version(self) -> str:
        return "2026-07-15"

    def trading_days(self, start=None, end=None):
        return list(self.days)

    def ensure_loaded(self, codes):
        return None

    def bars_on(self, d, codes):
        p = self.px[d]
        return {
            "600000.SH": Bar(
                "600000.SH", open=p, close=p, up_limit=p * 1.2, down_limit=p * 0.8
            )
        }

    def mark_prices(self, d, codes):
        return {"600000.SH": self.px[d]}

    def benchmark_returns(self, code=None):
        # 基准每日 +1%
        s = pd.Series(
            {dt.date(2026, 7, 2): 0.01, dt.date(2026, 7, 3): 0.01}
        )
        return s, "security_price"


def test_benchmark_excess_and_reject_meta():
    cfg = BacktestConfig(
        start=dt.date(2026, 7, 1),
        end=dt.date(2026, 7, 3),
        initial_cash=1_000_000.0,
        persist=False,
        benchmark="000905.SH",
        slippage_bps=0.0,
        commission_rate=0.0,
        commission_min=0.0,
        stamp_tax=0.0,
    )
    w = pd.DataFrame(
        {
            "trade_date": [dt.date(2026, 7, 1)],
            "exchange_code": ["600000.SH"],
            "weight": [1.0],
        }
    )
    result = BacktestEngine(cfg, gate=_GateWithBench()).run(FromWeightFrame(w))
    assert result.meta["benchmark_ok"] is True
    assert result.meta["benchmark_mode"] == "security_price"
    assert "excess_total" in result.metrics
    assert pd.notna(result.metrics["excess_total"])
    assert "info_ratio" in result.metrics


def test_reject_reason_counts_limit_up():
    cfg = BacktestConfig(
        start=dt.date(2026, 7, 1),
        end=dt.date(2026, 7, 2),
        initial_cash=1_000_000.0,
        persist=False,
        benchmark=None,
        slippage_bps=0.0,
        commission_rate=0.0,
        commission_min=0.0,
        stamp_tax=0.0,
    )

    class _GateLimit:
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
                    close=11.0,
                    up_limit=11.0,
                    down_limit=9.0,
                )
            }

        def mark_prices(self, d, codes):
            return {"600000.SH": 11.0}

        def benchmark_returns(self, code=None):
            return pd.Series(dtype=float), "unavailable"

    w = pd.DataFrame(
        {
            "trade_date": [dt.date(2026, 7, 1)],
            "exchange_code": ["600000.SH"],
            "weight": [1.0],
        }
    )
    result = BacktestEngine(cfg, gate=_GateLimit()).run(FromWeightFrame(w))
    assert result.meta["reject_reasons"].get("limit_up", 0) >= 1
    assert result.metrics.get("reject_limit_up", 0) >= 1
