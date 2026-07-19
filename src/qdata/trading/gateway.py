"""交易网关：风控前置 → BrokerClient（策略不直连券商 SDK）。"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import pandas as pd

from qdata.brokers.base import BrokerClient, OrderRequest, OrderResult
from qdata.risk import RiskLimits, RiskVerdict, check_order

logger = logging.getLogger(__name__)


@dataclass
class GatewayResult:
    risk: RiskVerdict
    order: OrderResult | None = None

    @property
    def ok(self) -> bool:
        return bool(self.risk.ok and self.order is not None and self.order.ok)


class TradingGateway:
    """统一下单入口。"""

    def __init__(
        self,
        broker: BrokerClient,
        *,
        limits: RiskLimits | None = None,
    ) -> None:
        self.broker = broker
        self.limits = limits or RiskLimits()
        self._quotes: pd.DataFrame = pd.DataFrame()

    def connect(self) -> None:
        self.broker.connect()

    def disconnect(self) -> None:
        self.broker.disconnect()

    def update_quotes(self, quotes: pd.DataFrame) -> None:
        self._quotes = quotes if quotes is not None else pd.DataFrame()
        setter = getattr(self.broker, "set_quotes", None)
        if callable(setter):
            setter(self._quotes)

    def account(self) -> dict[str, Any]:
        return self.broker.account()

    def positions(self) -> pd.DataFrame:
        return self.broker.positions()

    def place(self, order: OrderRequest) -> GatewayResult:
        acc = self.broker.account()
        cash = float(acc.get("cash") or 0)
        positions = self.broker.positions()
        cost = getattr(self.broker, "cost", None)
        verdict = check_order(
            order,
            cash=cash,
            positions=positions,
            quotes=self._quotes,
            limits=self.limits,
            cost=cost,
        )
        if not verdict.ok:
            logger.warning("风控拒绝: %s", verdict.message)
            return GatewayResult(
                risk=verdict,
                order=OrderResult(ok=False, message=verdict.message),
            )

        req = order
        if verdict.adjusted_qty is not None and verdict.adjusted_qty != order.quantity:
            req = OrderRequest(
                exchange_code=order.exchange_code,
                side=order.side,
                quantity=int(verdict.adjusted_qty),
                price=order.price,
                order_type=order.order_type,
            )
            logger.info("风控整手调整 %s → %s", order.quantity, req.quantity)

        if req.price is None and not self._quotes.empty:
            m = self._quotes[self._quotes["exchange_code"] == req.exchange_code]
            if not m.empty:
                px = float(m.iloc[0].get("price") or 0)
                if px > 0:
                    req = OrderRequest(
                        exchange_code=req.exchange_code,
                        side=req.side,
                        quantity=req.quantity,
                        price=px,
                        order_type=req.order_type,
                    )

        result = self.broker.place_order(req)
        return GatewayResult(risk=verdict, order=result)
