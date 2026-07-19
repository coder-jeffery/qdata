"""M3 纸交易演示：行情 → 风控 → PaperBroker。

用法：
  # 可选先拉快照
  python -m qdata.jobs.realtime_snapshot --source easyquotation --codes 600000.SH

  python -m qdata.jobs.paper_demo --code 600000.SH --side buy --qty 100
  python -m qdata.jobs.paper_demo --code 600000.SH --side buy --qty 150   # 整手下调
  python -m qdata.jobs.paper_demo --code 600000.SH --side buy --qty 50    # 风控拒绝
"""

from __future__ import annotations

import argparse
import logging
import sys

import pandas as pd

from qdata.brokers.base import OrderRequest
from qdata.brokers.paper import PaperBroker
from qdata.realtime import read_latest_snapshot
from qdata.risk import RiskLimits
from qdata.trading import TradingGateway

logger = logging.getLogger(__name__)


def _quotes_from_ch(code: str) -> pd.DataFrame:
    """无实时快照时，用最近日线收盘价构造演示行情。"""
    try:
        from qdata import db

        df = db.query_df(
            """
            SELECT m.exchange_code, b.close AS price, b.pre_close, b.open, b.high, b.low,
                   b.volume, b.amount, b.up_limit, b.down_limit, b.is_suspended, b.is_st
            FROM daily_bar b
            INNER JOIN security_master m USING (security_id)
            WHERE m.exchange_code = %(c)s
            ORDER BY b.trade_date DESC
            LIMIT 1
            """,
            {"c": code},
        )
        if df is None or df.empty:
            return pd.DataFrame()
        df["name"] = code
        df["bid"] = df["price"]
        df["ask"] = df["price"]
        df["time"] = ""
        return df
    except Exception as e:
        logger.warning("从 CH 构造行情失败: %s", e)
        return pd.DataFrame()


def run_demo(
    code: str,
    side: str,
    qty: int,
    *,
    price: float | None = None,
    source: str = "easyquotation",
    cash: float = 1_000_000.0,
    max_order_value: float = 0.0,
) -> int:
    code = code.strip().upper()
    quotes = read_latest_snapshot(source)
    if quotes.empty or code not in set(quotes.get("exchange_code", pd.Series(dtype=str)).astype(str)):
        print("realtime 快照无该标的，尝试用 ClickHouse 日线收盘价演示")
        quotes = _quotes_from_ch(code)
    if quotes.empty:
        print("无可用行情：请先 realtime_snapshot 或保证 daily_bar 有该代码")
        return 1

    broker = PaperBroker(initial_cash=cash)
    limits = RiskLimits(max_order_value=max_order_value)
    gw = TradingGateway(broker, limits=limits)
    gw.connect()
    gw.update_quotes(quotes)

    order = OrderRequest(exchange_code=code, side=side, quantity=qty, price=price)
    print(f"ORDER {side} {code} qty={qty} price={price}")
    print(f"account_before={gw.account()}")
    res = gw.place(order)
    print(f"risk.ok={res.risk.ok} risk={res.risk.message}")
    if res.order:
        print(f"order.ok={res.order.ok} id={res.order.order_id} msg={res.order.message}")
    print(f"account_after={gw.account()}")
    pos = gw.positions()
    if not pos.empty:
        print(pos.to_string(index=False))
    gw.disconnect()
    return 0 if res.ok else 2


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser(description="M3 Paper 交易演示")
    p.add_argument("--code", default="600000.SH")
    p.add_argument("--side", default="buy", choices=("buy", "sell"))
    p.add_argument("--qty", type=int, default=100)
    p.add_argument("--price", type=float, default=None, help="限价；默认用行情价")
    p.add_argument("--source", default="easyquotation", help="realtime 快照源名")
    p.add_argument("--cash", type=float, default=1_000_000.0)
    p.add_argument("--max-order-value", type=float, default=0.0)
    args = p.parse_args(argv)
    sys.exit(
        run_demo(
            args.code,
            args.side,
            args.qty,
            price=args.price,
            source=args.source,
            cash=args.cash,
            max_order_value=args.max_order_value,
        )
    )


if __name__ == "__main__":
    main()
