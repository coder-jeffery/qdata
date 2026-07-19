"""EasyQuotation 适配器：实时行情为主（新浪/腾讯等），可选依赖。

不适合做历史日线回填；daily_bar / adj_factor 会抛错提示改用 baostock/efinance/mootdx。
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


class EasyquotationFetcher(Fetcher):
    source = "easyquotation"

    def __init__(self) -> None:
        import easyquotation  # noqa: F401

        self._eq = easyquotation
        s = settings()
        super().__init__(RateLimiter(s.easyquotation_rate_limit))
        self._backend = s.easyquotation_backend
        self._max_symbols = s.akshare_max_symbols
        self._client = None

    def _api(self):
        if self._client is None:
            self._client = self._eq.use(self._backend)
        return self._client

    def _fetch_raw(self, dataset: str, trade_date: dt.date) -> pd.DataFrame:
        if dataset == "realtime_quote":
            return self._fetch_realtime()
        if dataset == "stock_basic":
            return self._fetch_stock_basic()
        if dataset in ("daily_bar", "adj_factor", "daily_basic", "suspend", "income"):
            raise RuntimeError(
                f"easyquotation 不支持历史数据集 {dataset}，"
                f"请改用 --source baostock|efinance|mootdx|akshare"
            )
        raise KeyError(f"easyquotation 不支持数据集 {dataset}")

    def _normalize(self, dataset: str, df: pd.DataFrame) -> pd.DataFrame:
        if df is None or df.empty:
            return pd.DataFrame(columns=EMPTY_SCHEMAS.get(dataset, []))
        return df.reset_index(drop=True)

    def _market_map(self) -> dict[str, dict]:
        api = self._api()
        self._limiter.acquire()
        # market() 返回全市场；失败则空
        if hasattr(api, "market_snapshot"):
            data = api.market_snapshot(prefix=True)
        elif hasattr(api, "market"):
            data = api.market()
        else:
            data = {}
        if not isinstance(data, dict):
            return {}
        return data

    def _fetch_stock_basic(self) -> pd.DataFrame:
        data = self._market_map()
        rows = []
        for code, info in data.items():
            pure = str(code).lower().replace("sh", "").replace("sz", "").replace("bj", "")
            pure = pure.zfill(6)
            if not pure.isdigit():
                continue
            name = str(info.get("name", info.get("名称", pure)))
            rows.append({
                "exchange_code": to_exchange_code(pure),
                "symbol": pure,
                "name": name,
                "list_date": None,
                "delist_date": None,
            })
        df = pd.DataFrame(rows)
        if df.empty:
            return df
        df = df.drop_duplicates("exchange_code")
        if self._max_symbols and self._max_symbols > 0:
            codes = limited_codes(df["symbol"].tolist(), self._max_symbols)
            df = df[df["symbol"].isin(codes)]
        return df.reset_index(drop=True)

    def _fetch_realtime(self) -> pd.DataFrame:
        data = self._market_map()
        if not data:
            # 退回样本 real()
            api = self._api()
            self._limiter.acquire()
            sample = ["600000", "000001", "600519", "300750"]
            if self._max_symbols and self._max_symbols > 0:
                sample = sample[: self._max_symbols]
            data = api.real(sample) or {}
        rows = []
        for code, info in data.items():
            pure = str(code).lower().replace("sh", "").replace("sz", "").replace("bj", "")
            pure = "".join(ch for ch in pure if ch.isdigit()).zfill(6)[-6:]
            if not pure.isdigit():
                continue
            rows.append({
                "exchange_code": to_exchange_code(pure),
                "name": str(info.get("name", info.get("名称", pure))),
                "price": _f(info, "now", "price", "现价"),
                "open": _f(info, "open", "开盘"),
                "high": _f(info, "high", "最高"),
                "low": _f(info, "low", "最低"),
                "pre_close": _f(info, "close", "pre_close", "昨收"),
                "volume": _f(info, "volume", "成交量"),
                "amount": _f(info, "amount", "成交额"),
                "bid": _f(info, "bid", "买一"),
                "ask": _f(info, "ask", "卖一"),
                "time": str(info.get("date", "")) + " " + str(info.get("time", "")),
            })
        df = pd.DataFrame(rows)
        if self._max_symbols and self._max_symbols > 0 and not df.empty:
            codes = limited_codes(
                [c.split(".")[0] for c in df["exchange_code"]], self._max_symbols
            )
            df = df[df["exchange_code"].map(lambda x: x.split(".")[0] in set(codes))]
        return df.reset_index(drop=True) if not df.empty else pd.DataFrame(
            columns=EMPTY_SCHEMAS["realtime_quote"]
        )


def _f(info: dict, *keys: str) -> float:
    for k in keys:
        if k in info and info[k] not in (None, ""):
            try:
                return float(info[k])
            except (TypeError, ValueError):
                continue
    return 0.0
