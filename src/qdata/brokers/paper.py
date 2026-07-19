"""纸交易 Broker：内存撮合，不连接真实券商。

用于 M3 演练：行情 → 风控 → 下单 → 查仓。真金前必须先跑通本通道。
成本规则与回测共享 ``qdata.trading.cost.CostModel``（运行时状态隔离）。
"""

from __future__ import annotations

import itertools
import logging
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from qdata.brokers.base import BrokerClient, OrderRequest, OrderResult
from qdata.config import settings
from qdata.trading.cost import DEFAULT_COST, CostModel

logger = logging.getLogger(__name__)


@dataclass
class _Position:
    exchange_code: str
    quantity: int
    cost: float  # 持仓成本（总金额，不含费用）


@dataclass
class PaperState:
    cash: float
    positions: dict[str, _Position] = field(default_factory=dict)
    orders: list[dict[str, Any]] = field(default_factory=list)


class PaperBroker(BrokerClient):
    name = "paper"

    def __init__(
        self,
        *,
        initial_cash: float | None = None,
        cost: CostModel | None = None,
    ) -> None:
        s = settings()
        cash = initial_cash if initial_cash is not None else float(
            getattr(s, "paper_initial_cash", 1_000_000.0) or 1_000_000.0
        )
        self.cost = cost if cost is not None else DEFAULT_COST
        self._state = PaperState(cash=cash)
        self._id_gen = itertools.count(1)
        self._connected = False
        self._last_quotes: pd.DataFrame = pd.DataFrame()

    def connect(self) -> None:
        self._connected = True
        logger.info("PaperBroker connected cash=%.2f", self._state.cash)

    def disconnect(self) -> None:
        self._connected = False

    def account(self) -> dict[str, Any]:
        self._ensure()
        mv = self._positions_market_value()
        return {
            "broker": self.name,
            "cash": self._state.cash,
            "market_value": mv,
            "total_asset": self._state.cash + mv,
            "orders": len(self._state.orders),
        }

    def positions(self) -> pd.DataFrame:
        self._ensure()
        rows = []
        for code, p in sorted(self._state.positions.items()):
            px = self._mark_price(code)
            mv = px * p.quantity
            rows.append({
                "exchange_code": code,
                "quantity": p.quantity,
                "cost": p.cost,
                "avg_cost": (p.cost / p.quantity) if p.quantity else 0.0,
                "price": px,
                "market_value": mv,
            })
        return pd.DataFrame(rows)

    def place_order(self, order: OrderRequest) -> OrderResult:
        self._ensure()
        code = order.exchange_code.strip().upper()
        side = order.side.strip().lower()
        qty = int(order.quantity)
        price = order.price
        if price is None:
            price = self._mark_price(code)
        if price is None or price <= 0:
            return OrderResult(ok=False, message="无有效成交价")
        if side not in ("buy", "sell"):
            return OrderResult(ok=False, message=f"非法 side={order.side}")

        if side == "buy":
            fill_px, notional, fee = self.cost.buy_cash_need(float(price), qty)
            need = notional + fee
            if need > self._state.cash + 1e-6:
                return OrderResult(ok=False, message="现金不足")
            self._state.cash -= need
            pos = self._state.positions.get(code)
            if pos is None:
                self._state.positions[code] = _Position(code, qty, notional)
            else:
                pos.quantity += qty
                pos.cost += notional
        else:
            pos = self._state.positions.get(code)
            if pos is None or pos.quantity < qty:
                return OrderResult(ok=False, message="持仓不足")
            fill_px, notional, fee = self.cost.sell_cash_proceeds(float(price), qty)
            frac = qty / pos.quantity
            pos.cost *= 1 - frac
            pos.quantity -= qty
            self._state.cash += notional - fee
            if pos.quantity <= 0:
                del self._state.positions[code]

        oid = f"P{next(self._id_gen):06d}"
        rec = {
            "order_id": oid,
            "exchange_code": code,
            "side": side,
            "quantity": qty,
            "price": float(fill_px),
            "raw_price": float(price),
            "fee": float(fee),
            "notional": float(notional),
            "status": "filled",
        }
        self._state.orders.append(rec)
        logger.info("paper fill %s", rec)
        return OrderResult(ok=True, order_id=oid, message="filled", raw=rec)

    def set_quotes(self, quotes: pd.DataFrame) -> None:
        """注入最新行情用于市价估计。"""
        self._last_quotes = quotes.copy() if quotes is not None else pd.DataFrame()

    def _mark_price(self, code: str) -> float | None:
        q = self._last_quotes
        if q is None or q.empty or "exchange_code" not in q.columns:
            return None
        m = q[q["exchange_code"].astype(str) == code]
        if m.empty:
            return None
        row = m.iloc[0]
        for k in ("price", "ask", "bid", "close"):
            if k in row.index and pd.notna(row[k]) and float(row[k]) > 0:
                return float(row[k])
        return None

    def _positions_market_value(self) -> float:
        total = 0.0
        for code, p in self._state.positions.items():
            px = self._mark_price(code) or (p.cost / p.quantity if p.quantity else 0.0)
            total += px * p.quantity
        return total

    def _ensure(self) -> None:
        if not self._connected:
            raise RuntimeError("PaperBroker 未 connect()")
