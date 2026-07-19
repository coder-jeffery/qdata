"""日频回测核心类型。"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Literal

import pandas as pd

Side = Literal["buy", "sell"]


@dataclass(frozen=True)
class Bar:
    """单标的单日行情（撮合用）。"""

    exchange_code: str
    open: float
    close: float
    up_limit: float | None = None
    down_limit: float | None = None
    suspended: bool = False
    volume: float | None = None


@dataclass(frozen=True)
class Order:
    trade_date: dt.date
    exchange_code: str
    side: Side
    target_shares: int | None = None
    delta_shares: int | None = None
    tag: str = ""


@dataclass(frozen=True)
class Fill:
    trade_date: dt.date
    exchange_code: str
    side: Side
    shares: int
    price: float
    fee: float
    rejected_reason: str | None = None

    @property
    def accepted(self) -> bool:
        return self.rejected_reason is None and self.shares > 0


@dataclass
class LedgerSnapshot:
    trade_date: dt.date
    cash: float
    market_value: float
    nav: float
    positions: dict[str, int] = field(default_factory=dict)


@dataclass
class DailyResult:
    trade_date: dt.date
    nav: float
    ret: float
    turnover: float
    n_fills: int
    n_rejects: int
    cash_ratio: float


@dataclass
class BacktestResult:
    meta: dict
    equity_curve: pd.DataFrame
    fills: pd.DataFrame
    positions_panel: pd.DataFrame
    metrics: dict[str, float]
    daily: list[DailyResult] = field(default_factory=list)
