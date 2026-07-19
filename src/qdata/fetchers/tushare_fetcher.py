"""Tushare Pro 适配器。

开关：QDATA_TUSHARE_ENABLED=true|false（默认 false）
凭证：QDATA_TUSHARE_TOKEN（https://tushare.pro 积分接口）
日线/复权/指标多为按 trade_date 全市场单次拉取，适合正式跑批。
"""

from __future__ import annotations

import datetime as dt
import logging

import pandas as pd

from qdata.config import settings
from qdata.fetchers.base import Fetcher, RateLimiter
from qdata.fetchers.schema import EMPTY_SCHEMAS

logger = logging.getLogger(__name__)


def ensure_tushare_enabled() -> None:
    """未开启开关时抛错（显式 --source tushare 时用）。"""
    if not settings().tushare_enabled:
        raise RuntimeError(
            "Tushare 渠道已关闭。请在 .env 设置 QDATA_TUSHARE_ENABLED=true，"
            "并配置 QDATA_TUSHARE_TOKEN"
        )


def _ymd(d: dt.date) -> str:
    return d.strftime("%Y%m%d")


def _parse_ymd(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, format="%Y%m%d", errors="coerce").dt.date


class TushareFetcher(Fetcher):
    source = "tushare"

    def __init__(self) -> None:
        import tushare as ts

        ensure_tushare_enabled()
        s = settings()
        token = (s.tushare_token or "").strip()
        if not token:
            raise RuntimeError(
                "未配置 Tushare token。请在 .env 设置 QDATA_TUSHARE_TOKEN="
                "（https://tushare.pro 个人中心获取）"
            )
        super().__init__(RateLimiter(s.tushare_rate_limit))
        self._max_symbols = s.akshare_max_symbols
        self._pro = ts.pro_api(token)
        self._universe: list[str] | None = None  # exchange_code / ts_code
        logger.info("Tushare 渠道已启用")

    def _fetch_raw(self, dataset: str, trade_date: dt.date) -> pd.DataFrame:
        dispatch = {
            "stock_basic": self._fetch_stock_basic,
            "daily_bar": lambda: self._fetch_daily_bar(trade_date),
            "adj_factor": lambda: self._fetch_adj_factor(trade_date),
            "daily_basic": lambda: self._fetch_daily_basic(trade_date),
            "suspend": lambda: self._fetch_suspend(trade_date),
            "income": lambda: self._fetch_income(trade_date),
            "balancesheet": lambda: self._fetch_balancesheet(trade_date),
            "cashflow": lambda: self._fetch_cashflow(trade_date),
        }
        if dataset not in dispatch:
            raise KeyError(f"tushare 不支持数据集 {dataset}")
        return dispatch[dataset]()

    def _normalize(self, dataset: str, df: pd.DataFrame) -> pd.DataFrame:
        if df is None or df.empty:
            return pd.DataFrame(columns=EMPTY_SCHEMAS.get(dataset, []))
        return df.reset_index(drop=True)

    def _call(self, api_name: str, **kwargs) -> pd.DataFrame:
        self._limiter.acquire()
        fn = getattr(self._pro, api_name)
        df = fn(**kwargs)
        if df is None:
            return pd.DataFrame()
        return df

    def _codes(self) -> list[str]:
        if self._universe is not None:
            return self._universe
        basic = self._fetch_stock_basic()
        if basic.empty:
            self._universe = []
        else:
            self._universe = basic["exchange_code"].astype(str).tolist()
        return self._universe

    def _filter_codes(self, df: pd.DataFrame, code_col: str = "ts_code") -> pd.DataFrame:
        if df is None or df.empty:
            return df
        if self._max_symbols and self._max_symbols > 0:
            allow = set(self._codes())
            if allow:
                df = df[df[code_col].isin(allow)]
        return df

    def _fetch_stock_basic(self) -> pd.DataFrame:
        # L=上市 D=退市 P=暂停；联调取上市为主，同时拉退市便于历史
        frames = []
        for status in ("L", "D", "P"):
            try:
                part = self._call(
                    "stock_basic",
                    exchange="",
                    list_status=status,
                    fields="ts_code,symbol,name,list_date,delist_date",
                )
            except Exception as e:
                logger.warning("tushare stock_basic list_status=%s 失败: %s", status, e)
                continue
            if part is not None and not part.empty:
                frames.append(part)
        if not frames:
            raise RuntimeError("tushare stock_basic 无数据（检查 token / 积分权限）")
        df = pd.concat(frames, ignore_index=True).drop_duplicates("ts_code")
        df = df.sort_values("ts_code")
        if self._max_symbols and self._max_symbols > 0:
            df = df.head(self._max_symbols).copy()
            logger.info("Tushare MAX_SYMBOLS=%s，仅 %s 只", self._max_symbols, len(df))
        self._universe = df["ts_code"].astype(str).tolist()
        out = pd.DataFrame({
            "exchange_code": df["ts_code"].astype(str),
            "symbol": df["symbol"].astype(str).str.zfill(6),
            "name": df["name"].astype(str),
            "list_date": _parse_ymd(df["list_date"]) if "list_date" in df.columns else None,
            "delist_date": _parse_ymd(df["delist_date"]) if "delist_date" in df.columns else None,
        })
        out["delist_date"] = out["delist_date"].where(pd.notna(out["delist_date"]), None)
        return out

    def _fetch_daily_bar(self, trade_date: dt.date) -> pd.DataFrame:
        df = self._call("daily", trade_date=_ymd(trade_date))
        if df is None or df.empty:
            raise RuntimeError(
                f"tushare daily {trade_date} 无数据（非交易日或权限不足）"
            )
        df = self._filter_codes(df)
        if df.empty:
            raise RuntimeError(f"tushare daily {trade_date} 过滤后为空")
        out = pd.DataFrame({
            "exchange_code": df["ts_code"].astype(str),
            "trade_date": trade_date,
            "open": pd.to_numeric(df["open"], errors="coerce"),
            "high": pd.to_numeric(df["high"], errors="coerce"),
            "low": pd.to_numeric(df["low"], errors="coerce"),
            "close": pd.to_numeric(df["close"], errors="coerce"),
            "pre_close": pd.to_numeric(df["pre_close"], errors="coerce"),
            # Tushare 成交量为手 → 股
            "volume": (pd.to_numeric(df["vol"], errors="coerce").fillna(0) * 100).astype("int64"),
            "amount": pd.to_numeric(df["amount"], errors="coerce").fillna(0.0) * 1000.0,
            # Tushare amount 单位：千元 → 元
        })
        return out.dropna(subset=["close"])

    def _fetch_adj_factor(self, trade_date: dt.date) -> pd.DataFrame:
        df = self._call("adj_factor", trade_date=_ymd(trade_date))
        if df is None or df.empty:
            raise RuntimeError(f"tushare adj_factor {trade_date} 无数据")
        df = self._filter_codes(df)
        if df.empty:
            raise RuntimeError(f"tushare adj_factor {trade_date} 过滤后为空")
        return pd.DataFrame({
            "exchange_code": df["ts_code"].astype(str),
            "trade_date": trade_date,
            "adj_factor": pd.to_numeric(df["adj_factor"], errors="coerce"),
        }).dropna(subset=["adj_factor"])

    def _fetch_daily_basic(self, trade_date: dt.date) -> pd.DataFrame:
        df = self._call(
            "daily_basic",
            trade_date=_ymd(trade_date),
            fields=(
                "ts_code,trade_date,turnover_rate,total_share,float_share,"
                "total_mv,circ_mv,pe_ttm,pb"
            ),
        )
        if df is None or df.empty:
            return pd.DataFrame(columns=EMPTY_SCHEMAS["daily_basic"])
        df = self._filter_codes(df)
        if df.empty:
            return pd.DataFrame(columns=EMPTY_SCHEMAS["daily_basic"])
        out = pd.DataFrame({
            "exchange_code": df["ts_code"].astype(str),
            "trade_date": trade_date,
            "turnover_rate": pd.to_numeric(df.get("turnover_rate"), errors="coerce"),
            "total_share": pd.to_numeric(df.get("total_share"), errors="coerce"),
            "float_share": pd.to_numeric(df.get("float_share"), errors="coerce"),
            "total_mv": pd.to_numeric(df.get("total_mv"), errors="coerce"),
            "circ_mv": pd.to_numeric(df.get("circ_mv"), errors="coerce"),
            "pe_ttm": pd.to_numeric(df.get("pe_ttm"), errors="coerce"),
            "pb": pd.to_numeric(df.get("pb"), errors="coerce"),
        })
        return out

    def _fetch_suspend(self, trade_date: dt.date) -> pd.DataFrame:
        # suspend_d：停牌明细；无数据时返回空表（合法）
        try:
            df = self._call(
                "suspend_d",
                suspend_type="S",
                trade_date=_ymd(trade_date),
            )
        except Exception as e:
            logger.warning("tushare suspend_d 失败，回退空表: %s", e)
            return pd.DataFrame(columns=EMPTY_SCHEMAS["suspend"])
        if df is None or df.empty:
            return pd.DataFrame(columns=EMPTY_SCHEMAS["suspend"])
        code_col = "ts_code" if "ts_code" in df.columns else None
        if code_col is None:
            return pd.DataFrame(columns=EMPTY_SCHEMAS["suspend"])
        df = self._filter_codes(df, code_col)
        return pd.DataFrame({
            "exchange_code": df[code_col].astype(str),
            "suspend_date": trade_date,
        }).drop_duplicates("exchange_code")

    def _fetch_income(self, trade_date: dt.date) -> pd.DataFrame:
        # 按公告日拉取当日披露的利润表（PIT）
        try:
            df = self._call(
                "income",
                ann_date=_ymd(trade_date),
                fields=(
                    "ts_code,ann_date,end_date,update_flag,"
                    "revenue,n_income_attr_p,basic_eps,operate_profit"
                ),
            )
        except Exception as e:
            logger.warning("tushare income 失败: %s", e)
            return pd.DataFrame(columns=EMPTY_SCHEMAS["income"])
        if df is None or df.empty:
            return pd.DataFrame(columns=EMPTY_SCHEMAS["income"])
        df = self._filter_codes(df)
        if df.empty:
            return pd.DataFrame(columns=EMPTY_SCHEMAS["income"])
        return pd.DataFrame({
            "exchange_code": df["ts_code"].astype(str),
            "ann_date": _parse_ymd(df["ann_date"]),
            "report_date": _parse_ymd(df["end_date"]),
            "update_flag": df.get("update_flag", "0").astype(str),
            "revenue": pd.to_numeric(df.get("revenue"), errors="coerce"),
            "n_income_attr_p": pd.to_numeric(df.get("n_income_attr_p"), errors="coerce"),
            "basic_eps": pd.to_numeric(df.get("basic_eps"), errors="coerce"),
            "operate_profit": pd.to_numeric(df.get("operate_profit"), errors="coerce"),
        })

    def _fetch_balancesheet(self, trade_date: dt.date) -> pd.DataFrame:
        try:
            df = self._call(
                "balancesheet",
                ann_date=_ymd(trade_date),
                fields=(
                    "ts_code,ann_date,end_date,update_flag,"
                    "total_assets,total_liab,total_hldr_eqy_exc_min_int"
                ),
            )
        except Exception as e:
            logger.warning("tushare balancesheet 失败: %s", e)
            return pd.DataFrame(columns=EMPTY_SCHEMAS["balancesheet"])
        if df is None or df.empty:
            return pd.DataFrame(columns=EMPTY_SCHEMAS["balancesheet"])
        df = self._filter_codes(df)
        if df.empty:
            return pd.DataFrame(columns=EMPTY_SCHEMAS["balancesheet"])
        return pd.DataFrame({
            "exchange_code": df["ts_code"].astype(str),
            "ann_date": _parse_ymd(df["ann_date"]),
            "report_date": _parse_ymd(df["end_date"]),
            "update_flag": df.get("update_flag", "0").astype(str),
            "total_assets": pd.to_numeric(df.get("total_assets"), errors="coerce"),
            "total_liab": pd.to_numeric(df.get("total_liab"), errors="coerce"),
            "total_hldr_eqy_exc_min_int": pd.to_numeric(
                df.get("total_hldr_eqy_exc_min_int"), errors="coerce"
            ),
        })

    def _fetch_cashflow(self, trade_date: dt.date) -> pd.DataFrame:
        try:
            df = self._call(
                "cashflow",
                ann_date=_ymd(trade_date),
                fields=(
                    "ts_code,ann_date,end_date,update_flag,"
                    "n_cashflow_act,n_cashflow_inv_act,n_cash_flows_fnc_act"
                ),
            )
        except Exception as e:
            logger.warning("tushare cashflow 失败: %s", e)
            return pd.DataFrame(columns=EMPTY_SCHEMAS["cashflow"])
        if df is None or df.empty:
            return pd.DataFrame(columns=EMPTY_SCHEMAS["cashflow"])
        df = self._filter_codes(df)
        if df.empty:
            return pd.DataFrame(columns=EMPTY_SCHEMAS["cashflow"])
        return pd.DataFrame({
            "exchange_code": df["ts_code"].astype(str),
            "ann_date": _parse_ymd(df["ann_date"]),
            "report_date": _parse_ymd(df["end_date"]),
            "update_flag": df.get("update_flag", "0").astype(str),
            "n_cashflow_act": pd.to_numeric(df.get("n_cashflow_act"), errors="coerce"),
            "n_cashflow_inv_act": pd.to_numeric(df.get("n_cashflow_inv_act"), errors="coerce"),
            "n_cash_flows_fnc_act": pd.to_numeric(
                df.get("n_cash_flows_fnc_act"), errors="coerce"
            ),
        })
