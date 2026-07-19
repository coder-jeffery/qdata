"""AKShare 适配器（主数据源）。

下游 Raw / Loader 只消费标准列（exchange_code / trade_date / ...），
本模块负责把东财/新浪等接口字段映射到内部口径。

说明：
- 全市场日线无「按日一次拉全市场」接口，需按代码循环 stock_zh_a_hist；
  可用 QDATA_AKSHARE_MAX_SYMBOLS 限制数量做联调。
- 股票列表优先东财分市场 / 上交所名册，避免深交所 xlsx SSL 不稳定；
  成功后落盘缓存，避免每次冷启动重拉。
- 成交量：东财为「手」→ 乘 100 转「股」；成交额已是「元」。
"""

from __future__ import annotations

import datetime as dt
import logging
import os
import time
import warnings
from contextlib import contextmanager
from pathlib import Path

import akshare as ak
import pandas as pd

from qdata.config import settings
from qdata.fetchers.base import Fetcher, RateLimiter
from qdata.symbols import to_exchange_code

logger = logging.getLogger(__name__)

_DATASETS = frozenset({
    "daily_bar", "adj_factor", "daily_basic", "suspend", "stock_basic", "income",
    "balancesheet", "cashflow",
})

# 空结果也必须带列，避免 parquet 无 schema 导致 Loader KeyError
_EMPTY = {
    "daily_bar": [
        "exchange_code", "trade_date", "open", "high", "low", "close",
        "pre_close", "volume", "amount",
    ],
    "adj_factor": ["exchange_code", "trade_date", "adj_factor"],
    "daily_basic": ["exchange_code", "trade_date", "turnover_rate"],
    "suspend": ["exchange_code", "suspend_date"],
    "stock_basic": ["exchange_code", "symbol", "name", "list_date", "delist_date"],
    "income": [
        "exchange_code", "ann_date", "report_date", "update_flag",
        "revenue", "n_income_attr_p", "basic_eps", "operate_profit",
    ],
    "balancesheet": [
        "exchange_code", "ann_date", "report_date", "update_flag",
        "total_assets", "total_liab", "total_hldr_eqy_exc_min_int",
    ],
    "cashflow": [
        "exchange_code", "ann_date", "report_date", "update_flag",
        "n_cashflow_act", "n_cashflow_inv_act", "n_cash_flows_fnc_act",
    ],
}

_UNIVERSE_TTL_SEC = 24 * 3600
_PROXY_ENV = (
    "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
    "http_proxy", "https_proxy", "all_proxy",
)


@contextmanager
def _without_proxy():
    """临时去掉代理，并让 requests 忽略环境代理。

    东财 push2 / 深交所经系统 HTTP(S)_PROXY 时经常 ProxyError / SSL EOF。
    """
    import requests

    saved = {k: os.environ.pop(k) for k in _PROXY_ENV if k in os.environ}
    saved_no = {k: os.environ.get(k) for k in ("NO_PROXY", "no_proxy")}
    os.environ["NO_PROXY"] = "*"
    os.environ["no_proxy"] = "*"

    original_init = requests.Session.__init__

    def _init_no_trust(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        original_init(self, *args, **kwargs)
        self.trust_env = False

    requests.Session.__init__ = _init_no_trust  # type: ignore[method-assign]
    try:
        yield
    finally:
        requests.Session.__init__ = original_init  # type: ignore[method-assign]
        for k in ("NO_PROXY", "no_proxy"):
            if saved_no.get(k) is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = saved_no[k]  # type: ignore[index]
        os.environ.update(saved)


class AkshareFetcher(Fetcher):
    source = "akshare"

    def __init__(self) -> None:
        s = settings()
        super().__init__(RateLimiter(s.akshare_rate_limit))
        self._max_symbols = s.akshare_max_symbols
        self._universe_cache: list[str] | None = None
        self._universe_df: pd.DataFrame | None = None

    def _fetch_raw(self, dataset: str, trade_date: dt.date) -> pd.DataFrame:
        if dataset not in _DATASETS:
            raise KeyError(f"未知数据集: {dataset}，可选: {sorted(_DATASETS)}")
        dispatch = {
            "stock_basic": self._fetch_stock_basic,
            "daily_bar": lambda: self._fetch_daily_bar(trade_date),
            "adj_factor": lambda: self._fetch_adj_factor(trade_date),
            "daily_basic": lambda: self._fetch_daily_basic(trade_date),
            "suspend": lambda: self._fetch_suspend(trade_date),
            "income": lambda: self._fetch_income(trade_date),
            "balancesheet": lambda: pd.DataFrame(columns=_EMPTY["balancesheet"]),
            "cashflow": lambda: pd.DataFrame(columns=_EMPTY["cashflow"]),
        }
        return dispatch[dataset]()

    def _normalize(self, dataset: str, df: pd.DataFrame) -> pd.DataFrame:
        if df is None or df.empty:
            return pd.DataFrame()
        return df.reset_index(drop=True)

    # ------------------------------------------------------------------
    # universe
    # ------------------------------------------------------------------
    def _universe_cache_path(self) -> Path:
        return settings().lake_root / "meta" / "symbol_universe.parquet"

    def _symbol_universe(self) -> list[str]:
        if self._universe_cache is not None:
            return self._universe_cache
        df = self._load_universe_df()
        codes = sorted({str(c).zfill(6) for c in df["code"].tolist()})
        if self._max_symbols and self._max_symbols > 0:
            codes = codes[: self._max_symbols]
            logger.info("QDATA_AKSHARE_MAX_SYMBOLS=%s，仅拉取 %s 只", self._max_symbols, len(codes))
        self._universe_cache = codes
        return codes

    def _load_universe_df(self) -> pd.DataFrame:
        """返回至少含 code/name 两列的股票列表。"""
        if self._universe_df is not None:
            return self._universe_df

        cache = self._universe_cache_path()
        cached = self._read_universe_cache(cache)
        if cached is not None:
            self._universe_df = cached
            return cached

        errors: list[str] = []
        with _without_proxy():
            # 上交所名册优先：快且不依赖深交所 xlsx / 东财 push2
            for name, loader in (
                ("exchange_name_lists", self._universe_from_exchanges),
                ("eastmoney_split_spot", self._universe_from_em_split),
                ("eastmoney_spot", self._universe_from_em_spot),
                # 最后才用会打深交所 xlsx 的聚合接口（常 SSL EOF）
                ("stock_info_a_code_name", self._universe_from_code_name),
            ):
                try:
                    df = loader()
                    if df is not None and not df.empty:
                        df = df.drop_duplicates("code").reset_index(drop=True)
                        self._write_universe_cache(cache, df)
                        logger.info("股票列表来源=%s，共 %s 只 → 缓存 %s", name, len(df), cache)
                        self._universe_df = df
                        return df
                except Exception as e:
                    errors.append(f"{name}: {type(e).__name__}: {e}")
                    logger.warning("股票列表来源 %s 失败: %s", name, e)

        # 联调兜底：网络全挂时仍能跑通有限股票
        if self._max_symbols and self._max_symbols > 0:
            df = _fallback_universe_df()
            logger.warning(
                "全部远端股票列表失败，使用内置兜底列表 %s 只（仅联调）。错误摘要: %s",
                len(df),
                " | ".join(errors[:3]),
            )
            self._write_universe_cache(cache, df)
            self._universe_df = df
            return df

        raise RuntimeError(
            "无法获取 A 股代码列表。已尝试交易所名册、东财、code_name。\n"
            "常见原因：HTTP(S)_PROXY 干扰、深交所 SSL 不稳定、东财限流。\n"
            "可尝试：unset HTTP_PROXY HTTPS_PROXY ALL_PROXY；"
            "或设置 QDATA_AKSHARE_MAX_SYMBOLS=30 使用联调兜底列表；"
            "或检查缓存 data/data-lake/meta/symbol_universe.parquet。\n"
            + "\n".join(errors)
        )

    def _read_universe_cache(self, path: Path) -> pd.DataFrame | None:
        if not path.exists():
            return None
        age = time.time() - path.stat().st_mtime
        if age > _UNIVERSE_TTL_SEC:
            logger.info("股票列表缓存过期（%.0fh），将重新拉取", age / 3600)
            return None
        df = pd.read_parquet(path)
        if "code" not in df.columns:
            return None
        if "name" not in df.columns:
            df["name"] = ""
        logger.info("使用股票列表缓存 %s（%s 只，%.1fh 前）", path, len(df), age / 3600)
        return df

    def _write_universe_cache(self, path: Path, df: pd.DataFrame) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        df[["code", "name"]].to_parquet(path, index=False)

    def _universe_from_em_split(self) -> pd.DataFrame:
        frames: list[pd.DataFrame] = []
        for fn_name in (
            "stock_sh_a_spot_em",
            "stock_sz_a_spot_em",
            "stock_bj_a_spot_em",
            "stock_cy_a_spot_em",
            "stock_kc_a_spot_em",
        ):
            fn = getattr(ak, fn_name, None)
            if fn is None:
                continue
            try:
                self._limiter.acquire()
                part = fn()
                if part is not None and not part.empty:
                    frames.append(part)
            except Exception as e:
                logger.debug("%s 失败: %s", fn_name, e)
        if not frames:
            raise RuntimeError("东财分市场 spot 全部失败")
        raw = pd.concat(frames, ignore_index=True)
        return pd.DataFrame({
            "code": raw["代码"].astype(str).str.zfill(6),
            "name": raw["名称"].astype(str),
        })

    def _universe_from_em_spot(self) -> pd.DataFrame:
        raw = ak.stock_zh_a_spot_em()
        return pd.DataFrame({
            "code": raw["代码"].astype(str).str.zfill(6),
            "name": raw["名称"].astype(str),
        })

    def _universe_from_exchanges(self) -> pd.DataFrame:
        """上交所/深交所/北交所名册；各所独立捕获，深交所失败不影响沪市。"""
        frames: list[pd.DataFrame] = []

        def _take(part: pd.DataFrame, code_keys: tuple[str, ...], name_keys: tuple[str, ...]) -> None:
            if part is None or part.empty:
                return
            code_col = next((c for c in code_keys if c in part.columns), part.columns[0])
            name_col = next((c for c in name_keys if c in part.columns), part.columns[1])
            frames.append(pd.DataFrame({
                "code": part[code_col].astype(str).str.zfill(6),
                "name": part[name_col].astype(str),
            }))

        for symbol in ("主板A股", "科创板"):
            try:
                self._limiter.acquire()
                _take(
                    ak.stock_info_sh_name_code(symbol=symbol),
                    ("证券代码",),
                    ("证券简称",),
                )
            except Exception as e:
                logger.warning("上交所名册[%s]失败: %s", symbol, e)

        try:
            self._limiter.acquire()
            _take(ak.stock_info_bj_name_code(), ("证券代码",), ("证券简称",))
        except Exception as e:
            logger.debug("北交所名册失败: %s", e)

        # 深交所 xlsx 经常 SSL EOF，失败可忽略
        try:
            self._limiter.acquire()
            _take(
                ak.stock_info_sz_name_code(symbol="A股列表"),
                ("A股代码", "证券代码"),
                ("A股简称", "证券简称"),
            )
        except Exception as e:
            logger.warning("深交所名册失败（可忽略）: %s", e)

        if not frames:
            raise RuntimeError("交易所名册全部失败")
        return pd.concat(frames, ignore_index=True)

    def _universe_from_code_name(self) -> pd.DataFrame:
        raw = ak.stock_info_a_code_name()
        code_col = "code" if "code" in raw.columns else raw.columns[0]
        name_col = "name" if "name" in raw.columns else raw.columns[1]
        return pd.DataFrame({
            "code": raw[code_col].astype(str).str.zfill(6),
            "name": raw[name_col].astype(str),
        })

    # ------------------------------------------------------------------
    # datasets
    # ------------------------------------------------------------------
    def _fetch_stock_basic(self) -> pd.DataFrame:
        df = self._load_universe_df().copy()
        if self._max_symbols and self._max_symbols > 0:
            # 与 daily_bar 同一截断：按 code 排序后取前 N，而非 DataFrame 原始 head
            uni = set(self._symbol_universe())
            df = df[df["code"].astype(str).str.zfill(6).isin(uni)].copy()
            df["_code"] = df["code"].astype(str).str.zfill(6)
            df = df.sort_values("_code").drop(columns="_code")
        out = pd.DataFrame({
            "exchange_code": [to_exchange_code(c) for c in df["code"]],
            "symbol": df["code"].astype(str).str.zfill(6),
            "name": df["name"].astype(str),
            "list_date": None,
            "delist_date": None,
        })
        return out

    def _fetch_daily_bar(self, trade_date: dt.date) -> pd.DataFrame:
        d = trade_date.strftime("%Y%m%d")
        codes = self._symbol_universe()
        frames: list[pd.DataFrame] = []
        total = len(codes)
        first_err: str | None = None
        with _without_proxy():
            for i, code in enumerate(codes, 1):
                self._limiter.acquire()
                try:
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore")
                        raw = ak.stock_zh_a_hist(
                            symbol=code,
                            period="daily",
                            start_date=d,
                            end_date=d,
                            adjust="",
                        )
                except Exception as e:
                    if first_err is None:
                        first_err = f"{code}: {type(e).__name__}: {e}"
                        logger.warning("daily_bar 首个失败样例 %s", first_err)
                    raw = None
                if raw is not None and not raw.empty:
                    part = self._normalize_hist_bar(raw, code, trade_date)
                    if not part.empty:
                        frames.append(part)
                if i == 1 or i % 10 == 0 or i == total:
                    logger.info("daily_bar 进度 %s/%s，已成功 %s 行", i, total, len(frames))
        if not frames:
            hint = f" 首个错误: {first_err}" if first_err else "（接口均返回空，可能非交易日或东财尚未更新）"
            raise RuntimeError(
                f"daily_bar {trade_date} 拉取成功 0/{total}。{hint}\n"
                f"请 unset 代理后重试，或换最近交易日；勿入库空分区。"
            )
        return pd.concat(frames, ignore_index=True)

    def _normalize_hist_bar(
        self, raw: pd.DataFrame, code: str, trade_date: dt.date
    ) -> pd.DataFrame:
        colmap = {
            "日期": "trade_date",
            "股票代码": "symbol",
            "开盘": "open",
            "收盘": "close",
            "最高": "high",
            "最低": "low",
            "成交量": "volume",
            "成交额": "amount",
            "涨跌幅": "pct_chg",
            "涨跌额": "change",
            "换手率": "turnover_rate",
        }
        df = raw.rename(columns={k: v for k, v in colmap.items() if k in raw.columns}).copy()
        if "trade_date" in df.columns:
            df["trade_date"] = pd.to_datetime(df["trade_date"], errors="coerce").dt.date
            df = df[df["trade_date"] == trade_date]
        if df.empty:
            return pd.DataFrame()

        df["exchange_code"] = to_exchange_code(code)
        df["volume"] = (pd.to_numeric(df["volume"], errors="coerce").fillna(0) * 100).astype("int64")
        df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0.0)
        for c in ("open", "high", "low", "close"):
            df[c] = pd.to_numeric(df[c], errors="coerce")

        if "change" in df.columns:
            df["pre_close"] = df["close"] - pd.to_numeric(df["change"], errors="coerce").fillna(0.0)
        elif "pct_chg" in df.columns:
            pct = pd.to_numeric(df["pct_chg"], errors="coerce").fillna(0.0) / 100.0
            df["pre_close"] = df["close"] / (1.0 + pct).replace(0, pd.NA)
        else:
            df["pre_close"] = df["close"]

        return df[[
            "exchange_code", "trade_date", "open", "high", "low", "close",
            "pre_close", "volume", "amount",
        ]].dropna(subset=["close"])

    def _fetch_adj_factor(self, trade_date: dt.date) -> pd.DataFrame:
        d = trade_date.strftime("%Y%m%d")
        codes = self._symbol_universe()
        rows: list[dict] = []
        total = len(codes)
        first_err: str | None = None
        with _without_proxy():
            for i, code in enumerate(codes, 1):
                try:
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore")
                        self._limiter.acquire()
                        raw = ak.stock_zh_a_hist(
                            symbol=code, period="daily", start_date=d, end_date=d, adjust="",
                        )
                        self._limiter.acquire()
                        hfq = ak.stock_zh_a_hist(
                            symbol=code, period="daily", start_date=d, end_date=d, adjust="hfq",
                        )
                except Exception as e:
                    if first_err is None:
                        first_err = f"{code}: {type(e).__name__}: {e}"
                        logger.warning("adj_factor 首个失败样例 %s", first_err)
                    continue
                if raw is None or raw.empty or hfq is None or hfq.empty:
                    continue
                close = float(pd.to_numeric(raw.iloc[0]["收盘"], errors="coerce") or 0.0)
                hfq_close = float(pd.to_numeric(hfq.iloc[0]["收盘"], errors="coerce") or 0.0)
                factor = (hfq_close / close) if close else 1.0
                rows.append({
                    "exchange_code": to_exchange_code(code),
                    "trade_date": trade_date,
                    "adj_factor": float(factor),
                })
                if i == 1 or i % 10 == 0 or i == total:
                    logger.info("adj_factor 进度 %s/%s，已成功 %s 行", i, total, len(rows))
        if not rows:
            hint = f" 首个错误: {first_err}" if first_err else "（接口均返回空）"
            raise RuntimeError(
                f"adj_factor {trade_date} 拉取成功 0/{total}。{hint}\n"
                f"请 unset 代理后重试；勿入库空分区。"
            )
        return pd.DataFrame(rows, columns=_EMPTY["adj_factor"])

    def _fetch_daily_basic(self, trade_date: dt.date) -> pd.DataFrame:
        d = trade_date.strftime("%Y%m%d")
        rows: list[dict] = []
        with _without_proxy():
            for code in self._symbol_universe():
                self._limiter.acquire()
                try:
                    raw = ak.stock_zh_a_hist(
                        symbol=code, period="daily", start_date=d, end_date=d, adjust="",
                    )
                except Exception:
                    continue
                if raw is None or raw.empty:
                    continue
                r = raw.iloc[0]
                rows.append({
                    "exchange_code": to_exchange_code(code),
                    "trade_date": trade_date,
                    "turnover_rate": float(pd.to_numeric(r.get("换手率"), errors="coerce") or 0.0),
                })
        return pd.DataFrame(rows)

    def _fetch_suspend(self, trade_date: dt.date) -> pd.DataFrame:
        self._limiter.acquire()
        try:
            with _without_proxy():
                raw = ak.stock_tfp_em(date=trade_date.strftime("%Y%m%d"))
        except Exception as e:
            logger.warning("stock_tfp_em 失败: %s", e)
            return pd.DataFrame(columns=["exchange_code", "suspend_date"])

        if raw is None or raw.empty:
            return pd.DataFrame(columns=["exchange_code", "suspend_date"])

        code_col = "代码" if "代码" in raw.columns else raw.columns[1]
        out = pd.DataFrame({
            "exchange_code": [to_exchange_code(c) for c in raw[code_col]],
            "suspend_date": trade_date,
        })
        return out.drop_duplicates("exchange_code")

    def _fetch_income(self, trade_date: dt.date) -> pd.DataFrame:
        frames: list[pd.DataFrame] = []
        with _without_proxy():
            for period in _recent_report_periods(trade_date):
                self._limiter.acquire()
                try:
                    raw = ak.stock_lrb_em(date=period.strftime("%Y%m%d"))
                except Exception as e:
                    logger.debug("stock_lrb_em %s: %s", period, e)
                    continue
                if raw is None or raw.empty:
                    continue
                frames.append(raw)

        if not frames:
            return pd.DataFrame()

        df = pd.concat(frames, ignore_index=True)
        rename = {}
        for a, b in [
            ("股票代码", "symbol"),
            ("证券代码", "symbol"),
            ("公告日期", "ann_date"),
            ("最新公告日期", "ann_date"),
            ("截止日期", "report_date"),
            ("报告期", "report_date"),
            ("营业总收入", "revenue"),
            ("营业收入", "revenue"),
            ("净利润", "n_income_attr_p"),
            ("归母净利润", "n_income_attr_p"),
            ("基本每股收益", "basic_eps"),
            ("营业利润", "operate_profit"),
        ]:
            if a in df.columns and b not in df.columns:
                rename[a] = b
        df = df.rename(columns=rename)
        if "symbol" not in df.columns:
            return pd.DataFrame()

        df["exchange_code"] = df["symbol"].map(lambda c: to_exchange_code(str(c)))
        for col in ("ann_date", "report_date"):
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], errors="coerce").dt.date
        if "ann_date" in df.columns:
            df = df[df["ann_date"] == trade_date]
        if "update_flag" not in df.columns:
            df["update_flag"] = 0
        keep = [
            c for c in (
                "exchange_code", "ann_date", "report_date", "update_flag",
                "revenue", "n_income_attr_p", "basic_eps", "operate_profit",
            ) if c in df.columns
        ]
        return df[keep].drop_duplicates()


def _recent_report_periods(asof: dt.date, n: int = 4) -> list[dt.date]:
    quarters = [(3, 31), (6, 30), (9, 30), (12, 31)]
    periods: list[dt.date] = []
    y = asof.year
    while len(periods) < n:
        for m, day in reversed(quarters):
            p = dt.date(y, m, day)
            if p <= asof:
                periods.append(p)
                if len(periods) >= n:
                    break
        y -= 1
    return periods


def _fallback_universe_df() -> pd.DataFrame:
    """网络全失败时的联调兜底样本（含沪深主板/创业/科创）。"""
    rows = [
        ("000001", "平安银行"),
        ("000002", "万科A"),
        ("000858", "五粮液"),
        ("002415", "海康威视"),
        ("300750", "宁德时代"),
        ("600000", "浦发银行"),
        ("600519", "贵州茅台"),
        ("600900", "长江电力"),
        ("601318", "中国平安"),
        ("603259", "药明康德"),
        ("688981", "中芯国际"),
        ("688041", "海光信息"),
    ]
    return pd.DataFrame(rows, columns=["code", "name"])
