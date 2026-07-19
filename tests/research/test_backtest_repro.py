"""同配置双跑 metrics 一致。"""

import datetime as dt

import pandas as pd
import pytest

from qdata.research.backtest import BacktestConfig, BacktestEngine, FromWeightFrame
from qdata.research.backtest.types import Bar


class _FakeGate:
    def __init__(self) -> None:
        self.days = [dt.date(2026, 7, 1), dt.date(2026, 7, 2), dt.date(2026, 7, 3)]
        self.px = {
            dt.date(2026, 7, 1): 10.0,
            dt.date(2026, 7, 2): 10.0,
            dt.date(2026, 7, 3): 11.0,
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
                "600000.SH",
                open=p,
                close=p,
                up_limit=p * 1.1,
                down_limit=p * 0.9,
            )
        }

    def mark_prices(self, d, codes):
        return {"600000.SH": self.px[d]}

    def benchmark_returns(self, code=None):
        return pd.Series(dtype=float), "unavailable"


def _run_once() -> dict:
    cfg = BacktestConfig(
        start=dt.date(2026, 7, 1),
        end=dt.date(2026, 7, 3),
        initial_cash=1_000_000.0,
        persist=False,
        benchmark=None,
        slippage_bps=0.0,
        commission_rate=0.0,
        commission_min=0.0,
        stamp_tax=0.0,
        run_name="repro",
    )
    w = pd.DataFrame(
        {
            "trade_date": [dt.date(2026, 7, 1)],
            "exchange_code": ["600000.SH"],
            "weight": [1.0],
        }
    )
    # 每次新 gate，避免状态污染
    return BacktestEngine(cfg, gate=_FakeGate()).run(FromWeightFrame(w)).metrics


def test_double_run_metrics_equal():
    a = _run_once()
    b = _run_once()
    assert a.keys() == b.keys()
    for k in a:
        va, vb = a[k], b[k]
        if pd.isna(va) and pd.isna(vb):
            continue
        assert va == pytest.approx(vb, rel=1e-12, abs=1e-12), k
