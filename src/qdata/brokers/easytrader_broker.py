"""EasyTrader 券商客户端适配器（同花顺/通用客户端自动化）。

需本机已登录对应交易客户端；仅作下单通道，不做历史行情 ETL。
配置：
  QDATA_EASYTRADER_BROKER=ht_client|yh_client|ths|universal_client ...
  QDATA_EASYTRADER_USER=
  QDATA_EASYTRADER_PASSWORD=
  QDATA_EASYTRADER_EXE=  # 可选，客户端路径
"""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from qdata.brokers.base import BrokerClient, OrderRequest, OrderResult
from qdata.config import settings
from qdata.symbols import to_pure_code

logger = logging.getLogger(__name__)


class EasytraderBroker(BrokerClient):
    name = "easytrader"

    def __init__(self) -> None:
        s = settings()
        self._broker = s.easytrader_broker
        self._user = s.easytrader_user
        self._password = s.easytrader_password
        self._exe = s.easytrader_exe
        self._client = None

    def connect(self) -> None:
        try:
            import easytrader
        except ImportError as e:
            raise ImportError(
                "EasyTrader 未安装。请: pip install 'qdata[easytrader]'，"
                "并确保本机交易客户端已登录。"
            ) from e

        user = easytrader.use(self._broker)
        if self._exe:
            user.connect(self._exe)
        if self._user and self._password:
            # 部分 broker 用 prepare；通用客户端用 connect
            if hasattr(user, "prepare"):
                user.prepare(user=self._user, password=self._password)
            else:
                user.account = self._user
                user.password = self._password
        self._client = user
        logger.info("EasyTrader 已连接 broker=%s", self._broker)

    def disconnect(self) -> None:
        self._client = None

    def account(self) -> dict[str, Any]:
        self._ensure()
        bal = self._client.balance
        if isinstance(bal, list) and bal:
            return dict(bal[0]) if isinstance(bal[0], dict) else {"raw": bal}
        if isinstance(bal, dict):
            return bal
        return {"raw": bal}

    def positions(self) -> pd.DataFrame:
        self._ensure()
        pos = self._client.position
        if isinstance(pos, pd.DataFrame):
            return pos
        if isinstance(pos, list):
            return pd.DataFrame(pos)
        return pd.DataFrame()

    def place_order(self, order: OrderRequest) -> OrderResult:
        self._ensure()
        code = to_pure_code(order.exchange_code)
        try:
            if order.side.lower() == "buy":
                raw = self._client.buy(code, price=order.price, amount=order.quantity)
            else:
                raw = self._client.sell(code, price=order.price, amount=order.quantity)
            return OrderResult(ok=True, order_id=str(raw), raw=raw)
        except Exception as e:
            return OrderResult(ok=False, message=str(e))

    def cancel_order(self, order_id: str) -> OrderResult:
        self._ensure()
        try:
            self._client.cancel_entrust(order_id)
            return OrderResult(ok=True, order_id=order_id)
        except Exception as e:
            return OrderResult(ok=False, order_id=order_id, message=str(e))

    def _ensure(self) -> None:
        if self._client is None:
            self.connect()
