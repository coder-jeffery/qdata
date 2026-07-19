"""PyTDX / MootDX 适配器（通达信协议，可选依赖）。

优先使用 mootdx.Quotes；可通过 QDATA_MOOTDX_SERVER=host:port 指定主站。
本地通达信目录 QDATA_TDX_DIR 存在时，日线可读离线 .day 文件。
"""

from __future__ import annotations

import datetime as dt
import logging

import pandas as pd

from qdata.config import settings
from qdata.fetchers.base import Fetcher, RateLimiter
from qdata.fetchers.schema import EMPTY_SCHEMAS
from qdata.fetchers.universe import fallback_universe_df, limited_codes, load_cached_universe
from qdata.symbols import to_exchange_code

logger = logging.getLogger(__name__)


def _parse_server(spec: str) -> tuple[str, int] | None:
    spec = (spec or "").strip()
    if not spec:
        return None
    if ":" not in spec:
        return spec, 7709
    host, port = spec.rsplit(":", 1)
    return host.strip(), int(port)


class MootdxFetcher(Fetcher):
    source = "mootdx"

    def __init__(self) -> None:
        from mootdx.quotes import Quotes  # noqa: F401

        s = settings()
        super().__init__(RateLimiter(s.mootdx_rate_limit))
        self._max_symbols = s.akshare_max_symbols
        self._server = _parse_server(s.mootdx_server)
        self._tdx_dir = s.tdx_dir
        self._client = None
        self._universe_cache: list[str] | None = None

    def _quotes(self):
        if self._client is not None:
            return self._client
        from mootdx.quotes import Quotes

        kwargs: dict = {"market": "std", "multithread": False, "heartbeat": False}
        if self._server:
            kwargs["server"] = self._server
        self._client = Quotes.factory(**kwargs)
        return self._client

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
            raise KeyError(f"mootdx 不支持数据集 {dataset}")
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
            self._universe_cache = limited_codes(codes, self._max_symbols)
            return self._universe_cache
        try:
            client = self._quotes()
            frames = []
            for market in (0, 1):  # sz, sh
                self._limiter.acquire()
                part = client.stocks(market=market)
                if part is not None and len(part) > 0:
                    frames.append(part if isinstance(part, pd.DataFrame) else pd.DataFrame(part))
            if frames:
                all_df = pd.concat(frames, ignore_index=True)
                code_col = "code" if "code" in all_df.columns else all_df.columns[0]
                codes = [str(c).zfill(6) for c in all_df[code_col].tolist()]
            else:
                codes = fallback_universe_df()["code"].tolist()
        except Exception as e:
            logger.warning("mootdx 股票列表失败，用兜底样本: %s", e)
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

    def _bars_for(self, code: str, trade_date: dt.date, adjust: str | None = None) -> pd.DataFrame:
        # 离线优先
        if self._tdx_dir:
            try:
                from mootdx.reader import Reader
                reader = Reader.factory(market="std", tdxdir=str(self._tdx_dir))
                df = reader.daily(symbol=code)
                if df is not None and not df.empty:
                    return df
            except Exception as e:
                logger.debug("mootdx reader %s 失败: %s", code, e)

        client = self._quotes()
        self._limiter.acquire()
        kwargs = {"symbol": code, "frequency": 9, "offset": 800}
        if adjust:
            kwargs["adjust"] = adjust
        return client.bars(**kwargs)

    def _row_on_date(self, df: pd.DataFrame, trade_date: dt.date) -> pd.Series | None:
        if df is None or df.empty:
            return None
        date_col = None
        for c in ("date", "datetime", "时间", "日期"):
            if c in df.columns:
                date_col = c
                break
        if date_col is None and isinstance(df.index, pd.DatetimeIndex):
            df = df.reset_index()
            date_col = df.columns[0]
        if date_col is None:
            return None
        dates = pd.to_datetime(df[date_col], errors="coerce").dt.date
        hit = df.loc[dates == trade_date]
        if hit.empty:
            return None
        return hit.iloc[-1]

    def _fetch_daily_bar(self, trade_date: dt.date) -> pd.DataFrame:
        rows = []
        for i, code in enumerate(self._codes(), 1):
            try:
                raw = self._bars_for(code, trade_date)
                row = self._row_on_date(raw, trade_date)
            except Exception as e:
                if i == 1:
                    logger.warning("mootdx daily_bar 首个失败: %s", e)
                continue
            if row is None:
                continue
            open_ = float(row.get("open", row.get("开盘", 0)) or 0)
            high = float(row.get("high", row.get("最高", 0)) or 0)
            low = float(row.get("low", row.get("最低", 0)) or 0)
            close = float(row.get("close", row.get("收盘", 0)) or 0)
            vol = float(row.get("vol", row.get("volume", row.get("成交量", 0))) or 0)
            # TDX 量常为手
            if vol < 1e7:
                vol *= 100
            amount = float(row.get("amount", row.get("成交额", 0)) or 0)
            pre = float(row.get("pre_close", row.get("昨收", close)) or close)
            rows.append({
                "exchange_code": to_exchange_code(code),
                "trade_date": trade_date,
                "open": open_, "high": high, "low": low, "close": close,
                "pre_close": pre, "volume": vol, "amount": amount,
            })
            if i % 50 == 0:
                logger.info("mootdx daily_bar 进度 %s/%s 成功 %s", i, len(self._codes()), len(rows))
        if not rows:
            raise RuntimeError(f"mootdx daily_bar {trade_date} 成功 0/{len(self._codes())}")
        return pd.DataFrame(rows)

    def _fetch_adj_factor(self, trade_date: dt.date) -> pd.DataFrame:
        rows = []
        for code in self._codes():
            try:
                raw0 = self._bars_for(code, trade_date)
                raw_h = self._bars_for(code, trade_date, adjust="hfq")
                r0 = self._row_on_date(raw0, trade_date)
                rh = self._row_on_date(raw_h, trade_date)
            except Exception:
                continue
            if r0 is None or rh is None:
                continue
            c0 = float(r0.get("close", 0) or 0)
            ch = float(rh.get("close", 0) or 0)
            if c0 > 0:
                rows.append({
                    "exchange_code": to_exchange_code(code),
                    "trade_date": trade_date,
                    "adj_factor": ch / c0,
                })
        if not rows:
            raise RuntimeError(f"mootdx adj_factor {trade_date} 成功 0/{len(self._codes())}")
        return pd.DataFrame(rows)

    def _fetch_realtime(self) -> pd.DataFrame:
        client = self._quotes()
        codes = self._codes()[:80]  # 单次批量上限保守
        self._limiter.acquire()
        raw = client.quotes(symbol=codes)
        if raw is None or (hasattr(raw, "empty") and raw.empty):
            return pd.DataFrame(columns=EMPTY_SCHEMAS["realtime_quote"])
        df = raw if isinstance(raw, pd.DataFrame) else pd.DataFrame(raw)
        code_col = "code" if "code" in df.columns else df.columns[0]
        out = pd.DataFrame({
            "exchange_code": [to_exchange_code(str(c)) for c in df[code_col]],
            "name": df.get("name", df[code_col]).astype(str),
            "price": pd.to_numeric(df.get("price", df.get("now", 0)), errors="coerce"),
            "open": pd.to_numeric(df.get("open", 0), errors="coerce"),
            "high": pd.to_numeric(df.get("high", 0), errors="coerce"),
            "low": pd.to_numeric(df.get("low", 0), errors="coerce"),
            "pre_close": pd.to_numeric(df.get("last_close", df.get("pre_close", 0)), errors="coerce"),
            "volume": pd.to_numeric(df.get("vol", df.get("volume", 0)), errors="coerce"),
            "amount": pd.to_numeric(df.get("amount", 0), errors="coerce"),
            "bid": pd.to_numeric(df.get("bid", 0), errors="coerce"),
            "ask": pd.to_numeric(df.get("ask", 0), errors="coerce"),
            "time": dt.datetime.now().isoformat(timespec="seconds"),
        })
        return out
