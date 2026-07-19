"""ZVT 适配器（可选依赖，偏重量化研究框架）。

ZVT 需自行完成数据下载（zvt.api / recorder）；本适配器从本地 ZVT 库读日线。
未安装或库为空时给出明确提示。
"""

from __future__ import annotations

import datetime as dt
import logging

import pandas as pd

from qdata.config import settings
from qdata.fetchers.base import Fetcher, RateLimiter
from qdata.fetchers.schema import EMPTY_SCHEMAS
from qdata.fetchers.universe import limited_codes
from qdata.symbols import to_exchange_code

logger = logging.getLogger(__name__)


class ZvtFetcher(Fetcher):
    source = "zvt"

    def __init__(self) -> None:
        try:
            import zvt  # noqa: F401
            from zvt.api.kdata import get_kdata
            from zvt.domain import Stock
        except ImportError as e:
            raise ImportError(
                "ZVT 未安装。请: pip install 'qdata[zvt]' 并按 ZVT 文档初始化数据目录"
            ) from e

        self._get_kdata = get_kdata
        self._Stock = Stock
        s = settings()
        super().__init__(RateLimiter(s.zvt_rate_limit))
        self._max_symbols = s.akshare_max_symbols

    def _fetch_raw(self, dataset: str, trade_date: dt.date) -> pd.DataFrame:
        dispatch = {
            "stock_basic": self._fetch_stock_basic,
            "daily_bar": lambda: self._fetch_daily_bar(trade_date),
            "adj_factor": lambda: self._fetch_adj_factor(trade_date),
            "suspend": lambda: pd.DataFrame(columns=EMPTY_SCHEMAS["suspend"]),
            "daily_basic": lambda: pd.DataFrame(columns=EMPTY_SCHEMAS["daily_basic"]),
            "income": lambda: pd.DataFrame(columns=EMPTY_SCHEMAS["income"]),
        }
        if dataset not in dispatch:
            raise KeyError(f"zvt 不支持数据集 {dataset}")
        return dispatch[dataset]()

    def _normalize(self, dataset: str, df: pd.DataFrame) -> pd.DataFrame:
        if df is None or df.empty:
            return pd.DataFrame(columns=EMPTY_SCHEMAS.get(dataset, []))
        return df.reset_index(drop=True)

    def _entity_ids(self) -> list[str]:
        # ZVT entity_id 形如 stock_sh_600000
        try:
            df = self._Stock.query_data(limit=None)
        except Exception as e:
            raise RuntimeError(
                f"ZVT Stock 表为空或不可读: {e}。请先用 ZVT recorder 下载股票列表"
            ) from e
        if df is None or df.empty:
            raise RuntimeError("ZVT Stock 无数据，请先运行 ZVT 数据下载")
        ids = df["entity_id"].astype(str).tolist() if "entity_id" in df.columns else []
        if self._max_symbols and self._max_symbols > 0:
            ids = ids[: self._max_symbols]
            logger.info("ZVT MAX_SYMBOLS=%s，仅 %s 只", self._max_symbols, len(ids))
        return ids

    def _to_exchange(self, entity_id: str) -> str:
        # stock_sh_600000 → 600000.SH
        parts = entity_id.split("_")
        if len(parts) >= 3:
            return to_exchange_code(parts[-1])
        return to_exchange_code(entity_id[-6:])

    def _fetch_stock_basic(self) -> pd.DataFrame:
        df = self._Stock.query_data(limit=None)
        if df is None or df.empty:
            return pd.DataFrame(columns=EMPTY_SCHEMAS["stock_basic"])
        if self._max_symbols and self._max_symbols > 0:
            df = df.head(self._max_symbols)
        code_col = "code" if "code" in df.columns else None
        name_col = "name" if "name" in df.columns else None
        rows = []
        for _, r in df.iterrows():
            eid = str(r.get("entity_id", ""))
            code = str(r[code_col]).zfill(6) if code_col else eid[-6:]
            rows.append({
                "exchange_code": to_exchange_code(code),
                "symbol": code,
                "name": str(r[name_col]) if name_col else code,
                "list_date": None,
                "delist_date": None,
            })
        return pd.DataFrame(rows)

    def _fetch_daily_bar(self, trade_date: dt.date) -> pd.DataFrame:
        start = trade_date.isoformat()
        end = trade_date.isoformat()
        frames = []
        for eid in self._entity_ids():
            self._limiter.acquire()
            try:
                k = self._get_kdata(
                    entity_id=eid,
                    start_timestamp=start,
                    end_timestamp=end,
                    provider="em",
                    level="1d",
                )
            except Exception:
                continue
            if k is None or k.empty:
                continue
            k = k.copy()
            k["exchange_code"] = self._to_exchange(eid)
            k["trade_date"] = trade_date
            rename = {
                "open": "open", "high": "high", "low": "low", "close": "close",
                "volume": "volume", "turnover": "amount",
            }
            for src, dst in rename.items():
                if src in k.columns and dst not in k.columns:
                    k[dst] = k[src]
            if "pre_close" not in k.columns:
                k["pre_close"] = k["close"]
            frames.append(k)
        if not frames:
            raise RuntimeError(
                f"zvt daily_bar {trade_date} 无数据。请确认已用 ZVT recorder 下载日线"
            )
        out = pd.concat(frames, ignore_index=True)
        return out[EMPTY_SCHEMAS["daily_bar"]]

    def _fetch_adj_factor(self, trade_date: dt.date) -> pd.DataFrame:
        # ZVT kdata 若含 factor 则用，否则 1.0
        rows = []
        for eid in self._entity_ids():
            self._limiter.acquire()
            try:
                k = self._get_kdata(
                    entity_id=eid,
                    start_timestamp=trade_date.isoformat(),
                    end_timestamp=trade_date.isoformat(),
                    provider="em",
                    level="1d",
                )
            except Exception:
                continue
            if k is None or k.empty:
                continue
            factor = 1.0
            if "factor" in k.columns:
                factor = float(pd.to_numeric(k["factor"], errors="coerce").iloc[-1] or 1.0)
            rows.append({
                "exchange_code": self._to_exchange(eid),
                "trade_date": trade_date,
                "adj_factor": factor,
            })
        if not rows:
            raise RuntimeError(f"zvt adj_factor {trade_date} 无数据")
        return pd.DataFrame(rows)
