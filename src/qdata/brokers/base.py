"""交易通道抽象：下单 / 查仓 / 实时行情（非 Raw ETL）。"""

from __future__ import annotations

import abc
from dataclasses import dataclass
from typing import Any

import pandas as pd


@dataclass
class OrderRequest:
    exchange_code: str          # 600000.SH
    side: str                   # buy | sell
    quantity: int
    price: float | None = None  # None=市价（视通道支持）
    order_type: str = "limit"


@dataclass
class OrderResult:
    ok: bool
    order_id: str = ""
    message: str = ""
    raw: Any = None


class BrokerClient(abc.ABC):
    """券商/交易终端适配器。"""

    name: str

    @abc.abstractmethod
    def connect(self) -> None: ...

    @abc.abstractmethod
    def disconnect(self) -> None: ...

    @abc.abstractmethod
    def account(self) -> dict[str, Any]: ...

    @abc.abstractmethod
    def positions(self) -> pd.DataFrame: ...

    @abc.abstractmethod
    def place_order(self, order: OrderRequest) -> OrderResult: ...

    def cancel_order(self, order_id: str) -> OrderResult:
        return OrderResult(ok=False, message="该通道未实现撤单")

    def realtime_quote(self, codes: list[str]) -> pd.DataFrame:
        raise NotImplementedError(f"{self.name} 未实现 realtime_quote")
