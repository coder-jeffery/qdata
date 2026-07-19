"""MiniQMT / xtquant 行情适配器（需本机 QMT）。

历史日线与实时行情走 xtdata；交易下单请用 qdata.brokers.miniqmt.MiniQmtBroker。
"""

from __future__ import annotations

import datetime as dt
import logging

import pandas as pd

from qdata.config import settings
from qdata.fetchers.base import Fetcher, RateLimiter
from qdata.fetchers.schema import EMPTY_SCHEMAS
from qdata.fetchers.universe import fallback_universe_df, limited_codes, load_cached_universe
from qdata.symbols import to_exchange_code, to_pure_code

logger = logging.getLogger(__name__)


def _qmt_code(exchange_code_or_pure: str) -> str:
    if "." in exchange_code_or_pure:
        code, mkt = exchange_code_or_pure.split(".", 1)
        return f"{code.zfill(6)}.{mkt.upper()}"
    return to_exchange_code(exchange_code_or_pure)


class MiniQmtFetcher(Fetcher):
    source = "miniqmt"

    def __init__(self) -> None:
        try:
            from xtquant import xtdata
        except ImportError as e:
            raise ImportError(
                "未找到 xtquant。请安装并启动 MiniQMT/QMT，将其 Python 库加入路径。"
            ) from e
        self._xtdata = xtdata
        s = settings()
        super().__init__(RateLimiter(300))
        self._max_symbols = s.akshare_max_symbols
        self._universe_cache: list[str] | None = None

    def _fetch_raw(self, dataset: str, trade_date: dt.date) -> pd.DataFrame:
        dispatch = {
            "stock_basic": self._fetch_stock_basic,
            "daily_bar": lambda: self._fetch_daily_bar(trade_date),
            "adj_factor": lambda: self._fetch_adj_factor(trade_date),
            "realtime_quote": self._fetch_realtime,
            "suspend": lambda: pd.DataFrame(columns=EMPTY_SCHEMAS["suspend"]),
            "daily_basic": lambda: pd.DataFrame(columns=EMPTY_SCHEMAS["daily_basic"]),
            "income": lambda: pd.DataFrame(columns=EMPTY_SCHEMAS["income"]),
        }
        if dataset not in dispatch:
            raise KeyError(f"miniqmt 不支持数据集 {dataset}")
        return dispatch[dataset]()

    def _normalize(self, dataset: str, df: pd.DataFrame) -> pd.DataFrame:
        if df is None or df.empty:
            return pd.DataFrame(columns=EMPTY_SCHEMAS.get(dataset, []))
        return df.reset_index(drop=True)

    def _codes(self) -> list[str]:
        if self._universe_cache is not None:
            return self._universe_cache
        cached = load_cached_universe()
        if cached is not None and not cached.empty:
            codes = [str(c).zfill(6) for c in cached["code"].tolist()]
        else:
            codes = fallback_universe_df()["code"].tolist()
        self._universe_cache = limited_codes(codes, self._max_symbols)
        return self._universe_cache

    def _fetch_stock_basic(self) -> pd.DataFrame:
        codes = self._codes()
        return pd.DataFrame({
            "exchange_code": [to_exchange_code(c) for c in codes],
            "symbol": codes,
            "name": codes,
            "list_date": None,
            "delist_date": None,
        })

    def _fetch_daily_bar(self, trade_date: dt.date) -> pd.DataFrame:
        d = trade_date.strftime("%Y%m%d")
        rows = []
        for code in self._codes():
            qmt = _qmt_code(code)
            self._limiter.acquire()
            try:
                data = self._xtdata.get_market_data_ex(
                    field_list=[],
                    stock_list=[qmt],
                    period="1d",
                    start_time=d,
                    end_time=d,
                    count=-1,
                    dividend_type="none",
                    fill_data=False,
                )
            except Exception as e:
                logger.debug("miniqmt bar %s: %s", qmt, e)
                continue
            if not data or qmt not in data:
                continue
            df = data[qmt]
            if df is None or df.empty:
                continue
            r = df.iloc[-1]
            rows.append({
                "exchange_code": to_exchange_code(code),
                "trade_date": trade_date,
                "open": float(r.get("open", 0)),
                "high": float(r.get("high", 0)),
                "low": float(r.get("low", 0)),
                "close": float(r.get("close", 0)),
                "pre_close": float(r.get("preClose", r.get("close", 0))),
                "volume": float(r.get("volume", 0)),
                "amount": float(r.get("amount", 0)),
            })
        if not rows:
            raise RuntimeError(
                f"miniqmt daily_bar {trade_date} 无数据（确认 QMT 已下载合约行情）"
            )
        return pd.DataFrame(rows)

    def _fetch_adj_factor(self, trade_date: dt.date) -> pd.DataFrame:
        # 用后复权收盘 / 不复权收盘
        d = trade_date.strftime("%Y%m%d")
        rows = []
        for code in self._codes():
            qmt = _qmt_code(code)
            try:
                raw = self._xtdata.get_market_data_ex(
                    field_list=["close"], stock_list=[qmt], period="1d",
                    start_time=d, end_time=d, count=-1, dividend_type="none",
                )
                hfq = self._xtdata.get_market_data_ex(
                    field_list=["close"], stock_list=[qmt], period="1d",
                    start_time=d, end_time=d, count=-1, dividend_type="back_ratio",
                )
            except Exception:
                continue
            if not raw or qmt not in raw or not hfq or qmt not in hfq:
                continue
            c0 = float(raw[qmt]["close"].iloc[-1])
            ch = float(hfq[qmt]["close"].iloc[-1])
            if c0 > 0:
                rows.append({
                    "exchange_code": to_exchange_code(code),
                    "trade_date": trade_date,
                    "adj_factor": ch / c0,
                })
        if not rows:
            raise RuntimeError(f"miniqmt adj_factor {trade_date} 无数据")
        return pd.DataFrame(rows)

    def _fetch_realtime(self) -> pd.DataFrame:
        codes = [_qmt_code(c) for c in self._codes()[:200]]
        tick = self._xtdata.get_full_tick(codes) or {}
        rows = []
        for c, info in tick.items():
            pure = to_pure_code(c) if "." in c else str(c).zfill(6)
            rows.append({
                "exchange_code": to_exchange_code(pure),
                "name": pure,
                "price": float(info.get("lastPrice", 0) or 0),
                "open": float(info.get("open", 0) or 0),
                "high": float(info.get("high", 0) or 0),
                "low": float(info.get("low", 0) or 0),
                "pre_close": float(info.get("lastClose", 0) or 0),
                "volume": float(info.get("volume", 0) or 0),
                "amount": float(info.get("amount", 0) or 0),
                "bid": 0.0,
                "ask": 0.0,
                "time": dt.datetime.now().isoformat(timespec="seconds"),
            })
        return pd.DataFrame(rows) if rows else pd.DataFrame(
            columns=EMPTY_SCHEMAS["realtime_quote"]
        )
