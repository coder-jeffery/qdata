"""组合账本：现金 + 股数。"""

from __future__ import annotations

import datetime as dt
import math
from copy import deepcopy

from qdata.research.backtest.types import Fill, LedgerSnapshot


class PortfolioLedger:
    def __init__(self, initial_cash: float) -> None:
        if initial_cash <= 0 or not math.isfinite(initial_cash):
            raise ValueError("initial_cash 必须为正有限数")
        self.cash = float(initial_cash)
        self.shares: dict[str, int] = {}

    def position(self, code: str) -> int:
        return int(self.shares.get(code, 0))

    def market_value(self, prices: dict[str, float]) -> float:
        mv = 0.0
        for code, n in self.shares.items():
            if n == 0:
                continue
            px = prices.get(code)
            if px is None or not math.isfinite(px) or px <= 0:
                continue
            mv += n * float(px)
        return float(mv)

    def nav(self, prices: dict[str, float]) -> float:
        return float(self.cash + self.market_value(prices))

    def apply_fill(self, fill: Fill) -> None:
        """仅接受成功成交；拒单忽略。"""
        if not fill.accepted:
            return
        code = fill.exchange_code
        notional = fill.shares * fill.price
        if fill.side == "buy":
            cost = notional + fill.fee
            if cost > self.cash + 1e-6:
                raise RuntimeError(
                    f"现金不足无法买入 {code}: need={cost:.2f} cash={self.cash:.2f}"
                )
            self.cash -= cost
            self.shares[code] = self.position(code) + fill.shares
        else:
            held = self.position(code)
            if fill.shares > held:
                raise RuntimeError(
                    f"卖出超过持仓 {code}: sell={fill.shares} held={held}"
                )
            proceeds = notional - fill.fee
            self.cash += proceeds
            left = held - fill.shares
            if left == 0:
                self.shares.pop(code, None)
            else:
                self.shares[code] = left

    def snapshot(self, trade_date: dt.date, prices: dict[str, float]) -> LedgerSnapshot:
        mv = self.market_value(prices)
        return LedgerSnapshot(
            trade_date=trade_date,
            cash=float(self.cash),
            market_value=float(mv),
            nav=float(self.cash + mv),
            positions=deepcopy(self.shares),
        )
