"""Efinance 适配器（东方财富封装，可选依赖）。"""

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


class EfinanceFetcher(Fetcher):
    source = "efinance"

    def __init__(self) -> None:
        import efinance as ef  # noqa: F401 — 缺依赖时尽早失败

        self._ef = ef
        s = settings()
        super().__init__(RateLimiter(s.efinance_rate_limit))
        self._max_symbols = s.akshare_max_symbols
        self._universe_cache: list[str] | None = None

    def _fetch_raw(self, dataset: str, trade_date: dt.date) -> pd.DataFrame:
        dispatch = {
            "stock_basic": lambda: self._fetch_stock_basic(),
            "daily_bar": lambda: self._fetch_daily_bar(trade_date),
            "adj_factor": lambda: self._fetch_adj_factor(trade_date),
            "daily_basic": lambda: self._fetch_daily_basic(trade_date),
            "suspend": lambda: pd.DataFrame(columns=EMPTY_SCHEMAS["suspend"]),
            "income": lambda: pd.DataFrame(columns=EMPTY_SCHEMAS["income"]),
        }
        if dataset not in dispatch:
            raise KeyError(f"efinance 不支持数据集 {dataset}")
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
            try:
                self._limiter.acquire()
                rq = self._ef.stock.get_realtime_quotes()
                col = "股票代码" if "股票代码" in rq.columns else rq.columns[0]
                codes = [str(c).zfill(6) for c in rq[col].tolist()]
            except Exception as e:
                logger.warning("efinance 实时列表失败，用兜底样本: %s", e)
                codes = fallback_universe_df()["code"].tolist()
        self._universe_cache = limited_codes(codes, self._max_symbols)
        return self._universe_cache

    def _fetch_stock_basic(self) -> pd.DataFrame:
        codes = self._codes()
        names: dict[str, str] = {}
        cached = load_cached_universe()
        if cached is not None and "name" in cached.columns:
            names = {
                str(r.code).zfill(6): str(r.name)
                for r in cached.itertuples(index=False)
            }
        rows = []
        for code in codes:
            rows.append({
                "exchange_code": to_exchange_code(code),
                "symbol": code,
                "name": names.get(code, code),
                "list_date": None,
                "delist_date": None,
            })
        return pd.DataFrame(rows)

    def _quote_one(self, code: str, trade_date: dt.date, fqt: int) -> pd.DataFrame:
        d = trade_date.strftime("%Y%m%d")
        self._limiter.acquire()
        return self._ef.stock.get_quote_history(
            code, beg=d, end=d, klt=101, fqt=fqt, suppress_error=True,
        )

    def _fetch_daily_bar(self, trade_date: dt.date) -> pd.DataFrame:
        frames: list[pd.DataFrame] = []
        for i, code in enumerate(self._codes(), 1):
            try:
                raw = self._quote_one(code, trade_date, fqt=0)
            except Exception as e:
                if i == 1:
                    logger.warning("efinance daily_bar 首个失败: %s", e)
                continue
            if raw is None or raw.empty:
                continue
            part = self._normalize_bar(raw, code, trade_date)
            if not part.empty:
                frames.append(part)
            if i % 50 == 0:
                logger.info("efinance daily_bar 进度 %s/%s", i, len(self._codes()))
        if not frames:
            raise RuntimeError(f"efinance daily_bar {trade_date} 成功 0/{len(self._codes())}")
        return pd.concat(frames, ignore_index=True)

    def _normalize_bar(self, raw: pd.DataFrame, code: str, trade_date: dt.date) -> pd.DataFrame:
        colmap = {
            "日期": "trade_date",
            "开盘": "open",
            "最高": "high",
            "最低": "low",
            "收盘": "close",
            "成交量": "volume",
            "成交额": "amount",
        }
        df = raw.rename(columns={k: v for k, v in colmap.items() if k in raw.columns})
        need = ["open", "high", "low", "close"]
        if any(c not in df.columns for c in need):
            return pd.DataFrame(columns=EMPTY_SCHEMAS["daily_bar"])
        df["exchange_code"] = to_exchange_code(code)
        df["trade_date"] = pd.to_datetime(df.get("trade_date", trade_date)).dt.date
        df = df[df["trade_date"] == trade_date]
        if "volume" in df.columns:
            # efinance 成交量单位多为「手」
            df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0) * 100
        else:
            df["volume"] = 0.0
        df["amount"] = pd.to_numeric(df.get("amount", 0), errors="coerce").fillna(0.0)
        # 无昨收时用收盘近似（后续可补）
        if "pre_close" not in df.columns:
            df["pre_close"] = pd.to_numeric(df["close"], errors="coerce")
        for c in ("open", "high", "low", "close", "pre_close"):
            df[c] = pd.to_numeric(df[c], errors="coerce")
        return df[EMPTY_SCHEMAS["daily_bar"]]

    def _fetch_adj_factor(self, trade_date: dt.date) -> pd.DataFrame:
        rows = []
        for i, code in enumerate(self._codes(), 1):
            try:
                raw0 = self._quote_one(code, trade_date, fqt=0)
                raw2 = self._quote_one(code, trade_date, fqt=2)  # 后复权
            except Exception:
                continue
            if raw0 is None or raw0.empty or raw2 is None or raw2.empty:
                continue
            c0 = float(pd.to_numeric(raw0["收盘"], errors="coerce").iloc[-1])
            c2 = float(pd.to_numeric(raw2["收盘"], errors="coerce").iloc[-1])
            if c0 and c0 > 0:
                rows.append({
                    "exchange_code": to_exchange_code(code),
                    "trade_date": trade_date,
                    "adj_factor": c2 / c0,
                })
            if i % 50 == 0:
                logger.info("efinance adj_factor 进度 %s/%s", i, len(self._codes()))
        if not rows:
            raise RuntimeError(f"efinance adj_factor {trade_date} 成功 0/{len(self._codes())}")
        return pd.DataFrame(rows)

    def _fetch_daily_basic(self, trade_date: dt.date) -> pd.DataFrame:
        # efinance 日 K 含换手率时一并取出
        rows = []
        for code in self._codes():
            try:
                raw = self._quote_one(code, trade_date, fqt=0)
            except Exception:
                continue
            if raw is None or raw.empty or "换手率" not in raw.columns:
                continue
            rows.append({
                "exchange_code": to_exchange_code(code),
                "trade_date": trade_date,
                "turnover_rate": float(pd.to_numeric(raw["换手率"], errors="coerce").iloc[-1]),
            })
        return pd.DataFrame(rows) if rows else pd.DataFrame(columns=EMPTY_SCHEMAS["daily_basic"])
