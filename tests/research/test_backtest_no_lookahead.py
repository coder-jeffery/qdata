"""防前视：末日信号不得成交。"""

import datetime as dt

import pandas as pd

from qdata.research.backtest import BacktestConfig, BacktestEngine, FromWeightFrame
from qdata.research.backtest.types import Bar


class _FakeGate:
    def __init__(self) -> None:
        self.days = [dt.date(2026, 7, 14), dt.date(2026, 7, 15)]
        self._bar = Bar(
            "600000.SH",
            open=10.0,
            close=10.0,
            up_limit=11.0,
            down_limit=9.0,
        )

    @property
    def dataset_version(self) -> str:
        return "2026-07-15"

    def trading_days(self, start=None, end=None):
        return list(self.days)

    def ensure_loaded(self, codes):
        return None

    def bars_on(self, d, codes):
        return {"600000.SH": self._bar}

    def mark_prices(self, d, codes):
        return {"600000.SH": 10.0}

    def benchmark_returns(self, code=None):
        return pd.Series(dtype=float), "unavailable"


def test_last_day_signal_has_no_fill():
    cfg = BacktestConfig(
        start=dt.date(2026, 7, 14),
        end=dt.date(2026, 7, 15),
        initial_cash=1_000_000.0,
        persist=False,
        benchmark=None,
        slippage_bps=0.0,
        commission_rate=0.0,
        commission_min=0.0,
        stamp_tax=0.0,
    )
    # 仅末日有信号 → 无下一成交日 → 不成交
    w = pd.DataFrame(
        {
            "trade_date": [dt.date(2026, 7, 15)],
            "exchange_code": ["600000.SH"],
            "weight": [1.0],
        }
    )
    result = BacktestEngine(cfg, gate=_FakeGate()).run(FromWeightFrame(w))
    assert result.fills.empty or result.fills["rejected_reason"].notna().all()
    assert (result.fills["shares"] == 0).all() if not result.fills.empty else True
    assert result.meta.get("warnings")
    assert any("末日信号丢弃" in x for x in result.meta["warnings"])
    # 全程现金
    assert result.equity_curve["nav"].iloc[-1] == cfg.initial_cash
