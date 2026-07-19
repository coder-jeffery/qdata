"""MiniQMT（迅投 QMT）交易/行情适配器。

依赖本机已安装并登录的 MiniQMT / QMT，Python 包通常为 xtquant（随 QMT 安装，非纯 PyPI）。
配置：
  QDATA_MINIQMT_PATH=/path/to/userdata_mini
  QDATA_MINIQMT_ACCOUNT=资金账号
"""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from qdata.brokers.base import BrokerClient, OrderRequest, OrderResult
from qdata.config import settings
from qdata.symbols import to_pure_code

logger = logging.getLogger(__name__)


def _to_qmt_code(exchange_code: str) -> str:
    """600000.SH → 600000.SH（QMT 常用）。"""
    code, market = exchange_code.split(".", 1)
    return f"{code.zfill(6)}.{market.upper()}"


class MiniQmtBroker(BrokerClient):
    name = "miniqmt"

    def __init__(self) -> None:
        s = settings()
        self._path = s.miniqmt_path
        self._account = s.miniqmt_account
        self._session = None
        self._trader = None

    def connect(self) -> None:
        try:
            from xtquant import xtdata
            from xtquant.xttrader import XtQuantTrader
            from xtquant.xttype import StockAccount
        except ImportError as e:
            raise ImportError(
                "未找到 xtquant。请安装并启动 MiniQMT/QMT，"
                "将其 site-packages 加入 PYTHONPATH，或 pip install 厂商提供的 xtquant wheel。"
                "参考: https://dict.thinktrader.net/"
            ) from e

        if not self._path:
            raise RuntimeError("请设置 QDATA_MINIQMT_PATH 为 MiniQMT userdata 目录")
        if not self._account:
            raise RuntimeError("请设置 QDATA_MINIQMT_ACCOUNT")

        # session_id 任意唯一整数
        import time

        session_id = int(time.time()) % 1_000_000
        trader = XtQuantTrader(self._path, session_id)
        trader.start()
        acc = StockAccount(self._account)
        connect_result = trader.connect()
        if connect_result != 0:
            raise RuntimeError(f"MiniQMT connect 失败, code={connect_result}")
        trader.subscribe(acc)
        self._trader = trader
        self._session = acc
        self._xtdata = xtdata
        logger.info("MiniQMT 已连接 account=%s", self._account)

    def disconnect(self) -> None:
        if self._trader is not None:
            try:
                self._trader.stop()
            except Exception:
                pass
        self._trader = None
        self._session = None

    def account(self) -> dict[str, Any]:
        self._ensure()
        asset = self._trader.query_stock_asset(self._session)
        if asset is None:
            return {}
        return {
            "cash": getattr(asset, "cash", None),
            "total_asset": getattr(asset, "total_asset", None),
            "market_value": getattr(asset, "market_value", None),
        }

    def positions(self) -> pd.DataFrame:
        self._ensure()
        pos = self._trader.query_stock_positions(self._session) or []
        rows = []
        for p in pos:
            rows.append({
                "exchange_code": getattr(p, "stock_code", ""),
                "volume": getattr(p, "volume", 0),
                "can_use": getattr(p, "can_use_volume", 0),
                "cost": getattr(p, "avg_price", 0),
            })
        return pd.DataFrame(rows)

    def place_order(self, order: OrderRequest) -> OrderResult:
        self._ensure()
        from xtquant import xtconstant

        code = _to_qmt_code(order.exchange_code)
        side = xtconstant.STOCK_BUY if order.side.lower() == "buy" else xtconstant.STOCK_SELL
        price_type = xtconstant.FIX_PRICE if order.price is not None else xtconstant.LATEST_PRICE
        price = float(order.price or 0)
        oid = self._trader.order_stock(
            self._session, code, side, order.quantity, price_type, price, "qdata", ""
        )
        ok = oid is not None and oid != -1
        return OrderResult(ok=ok, order_id=str(oid), message="" if ok else "下单失败", raw=oid)

    def cancel_order(self, order_id: str) -> OrderResult:
        self._ensure()
        try:
            self._trader.cancel_order_stock(self._session, int(order_id))
            return OrderResult(ok=True, order_id=order_id)
        except Exception as e:
            return OrderResult(ok=False, order_id=order_id, message=str(e))

    def realtime_quote(self, codes: list[str]) -> pd.DataFrame:
        self._ensure()
        qmt_codes = [_to_qmt_code(c) if "." in c else f"{to_pure_code(c)}.SH" for c in codes]
        # 简化：取最新 tick
        rows = []
        for c in qmt_codes:
            tick = self._xtdata.get_full_tick([c]) or {}
            info = tick.get(c, {})
            rows.append({
                "exchange_code": c,
                "price": info.get("lastPrice", 0),
                "volume": info.get("volume", 0),
                "amount": info.get("amount", 0),
            })
        return pd.DataFrame(rows)

    def _ensure(self) -> None:
        if self._trader is None or self._session is None:
            self.connect()
