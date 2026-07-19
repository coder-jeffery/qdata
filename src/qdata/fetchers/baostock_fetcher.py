"""BaoStock 适配器。

与 AkshareFetcher 输出同一套标准列，可被 factory 单独选用或作为 auto 回退。
BaoStock 需 login/logout；量单位已是「股」，无需再 ×100。
"""

from __future__ import annotations

import datetime as dt
import logging
from contextlib import contextmanager

import baostock as bs
import pandas as pd

from qdata.config import settings
from qdata.fetchers.base import Fetcher, RateLimiter
from qdata.symbols import from_baostock_code, is_baostock_a_share, to_baostock_code

logger = logging.getLogger(__name__)

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

_K_FIELDS = (
    "date,code,open,high,low,close,preclose,volume,amount,"
    "adjustflag,turn,tradestatus,pctChg,isST"
)


@contextmanager
def _baostock_session(*, retries: int = 6, timeout_sec: float = 45.0):
    """login 带重试 + socket 超时，避免网络挂死无日志。"""
    import socket
    import time

    prev_timeout = socket.getdefaulttimeout()
    socket.setdefaulttimeout(timeout_sec)
    last_err = "unknown"
    try:
        for attempt in range(1, retries + 1):
            try:
                lg = bs.login()
            except OSError as e:
                last_err = f"socket {e}"
                logger.warning(
                    "BaoStock login 网络异常(%s/%s, timeout=%ss): %s",
                    attempt, retries, timeout_sec, last_err,
                )
                time.sleep(min(2 ** attempt, 30))
                continue
            if lg.error_code == "0":
                break
            last_err = f"{lg.error_code} {lg.error_msg}"
            logger.warning(
                "BaoStock login 失败(%s/%s, timeout=%ss): %s",
                attempt, retries, timeout_sec, last_err,
            )
            time.sleep(min(2 ** attempt, 30))
        else:
            hint = ""
            if "10002007" in last_err or "timed out" in last_err.lower() or "网络" in last_err:
                hint = (
                    "（BaoStock 服务端/网络超时。稍后重试；"
                    "prod_backfill 默认 --skip-published，已发布日会跳过。"
                    "也可换 QDATA_PROD_SOURCE=tushare）"
                )
            raise RuntimeError(f"BaoStock login 失败: {last_err}{hint}")
        try:
            yield
        finally:
            try:
                bs.logout()
            except Exception:
                pass
    finally:
        socket.setdefaulttimeout(prev_timeout)


def _rs_to_df(rs) -> pd.DataFrame:
    if rs.error_code != "0":
        raise RuntimeError(f"BaoStock 查询失败: {rs.error_code} {rs.error_msg}")
    rows: list[list[str]] = []
    while rs.next():
        rows.append(rs.get_row_data())
    if not rows:
        return pd.DataFrame(columns=list(rs.fields or []))
    return pd.DataFrame(rows, columns=rs.fields)


class BaostockFetcher(Fetcher):
    source = "baostock"

    def __init__(self) -> None:
        s = settings()
        super().__init__(RateLimiter(s.baostock_rate_limit))
        self._max_symbols = s.akshare_max_symbols  # 复用同一联调开关
        self._universe_cache: list[str] | None = None  # baostock codes sh.600000
        # daily_bar 同趟计算的复权因子，供随后 adj_factor fetch 直接使用
        self._adj_cache: dict[dt.date, pd.DataFrame] = {}

    def fetch(self, dataset: str, trade_date: dt.date) -> pd.DataFrame:
        """覆盖基类：整段拉取包在一次 login 会话内。

        adj_factor 若已有 daily_bar 同趟缓存则不再 login。
        """
        if dataset == "adj_factor" and trade_date in self._adj_cache:
            return self._normalize(dataset, self._fetch_adj_factor(trade_date))
        with _baostock_session():
            self._limiter.acquire()
            df = self._fetch_raw(dataset, trade_date)
            return self._normalize(dataset, df)

    def fetch_many(
        self,
        datasets: tuple[str, ...] | list[str],
        trade_date: dt.date,
    ) -> dict[str, pd.DataFrame]:
        """同一 login 会话内拉取多个数据集（减少 10002007 重登）。"""
        need_login = [
            ds for ds in datasets
            if not (ds == "adj_factor" and trade_date in self._adj_cache)
        ]
        out: dict[str, pd.DataFrame] = {}
        if not need_login:
            for ds in datasets:
                out[ds] = self.fetch(ds, trade_date)
            return out

        with _baostock_session():
            for ds in datasets:
                if ds == "adj_factor" and trade_date in self._adj_cache:
                    out[ds] = self._normalize(ds, self._fetch_adj_factor(trade_date))
                    continue
                self._limiter.acquire()
                out[ds] = self._normalize(ds, self._fetch_raw(ds, trade_date))
        return out

    def _fetch_raw(self, dataset: str, trade_date: dt.date) -> pd.DataFrame:
        dispatch = {
            "stock_basic": lambda: self._fetch_stock_basic(trade_date),
            "daily_bar": lambda: self._fetch_daily_bar(trade_date),
            "adj_factor": lambda: self._fetch_adj_factor(trade_date),
            "daily_basic": lambda: self._fetch_daily_basic(trade_date),
            "suspend": lambda: self._fetch_suspend(trade_date),
            "income": lambda: self._fetch_income(trade_date),
            "balancesheet": lambda: pd.DataFrame(columns=_EMPTY["balancesheet"]),
            "cashflow": lambda: pd.DataFrame(columns=_EMPTY["cashflow"]),
        }
        if dataset not in dispatch:
            raise KeyError(f"未知数据集: {dataset}，可选: {sorted(dispatch)}")
        return dispatch[dataset]()

    def _normalize(self, dataset: str, df: pd.DataFrame) -> pd.DataFrame:
        if df is None or df.empty:
            return pd.DataFrame(columns=_EMPTY.get(dataset, []))
        return df.reset_index(drop=True)

    def _universe_bs_codes(self, trade_date: dt.date) -> list[str]:
        if self._universe_cache is not None:
            return self._universe_cache
        self._limiter.acquire()
        rs = bs.query_all_stock(day=trade_date.isoformat())
        df = _rs_to_df(rs)
        if df.empty:
            # 回退证券基本信息
            self._limiter.acquire()
            basic = _rs_to_df(bs.query_stock_basic())
            codes = [
                c for c in basic.loc[basic["type"] == "1", "code"].tolist()
                if is_baostock_a_share(c)
            ]
        else:
            codes = [c for c in df["code"].tolist() if is_baostock_a_share(c)]
        codes = sorted(set(codes))
        if self._max_symbols and self._max_symbols > 0:
            codes = codes[: self._max_symbols]
            logger.info("BaoStock MAX_SYMBOLS=%s，仅拉取 %s 只", self._max_symbols, len(codes))
        self._universe_cache = codes
        return codes

    def _fetch_stock_basic(self, trade_date: dt.date) -> pd.DataFrame:
        """与 daily_bar 共用同一 universe（MAX_SYMBOLS 时按当日可交易代码截断）。"""
        self._limiter.acquire()
        df = _rs_to_df(bs.query_stock_basic())
        if df.empty:
            return pd.DataFrame(columns=_EMPTY["stock_basic"])
        df = df[df["type"] == "1"].copy()
        df = df[df["code"].map(is_baostock_a_share)]
        if self._max_symbols and self._max_symbols > 0:
            # 必须与 _universe_bs_codes 一致：query_all_stock 当日集合，
            # 不能对 query_stock_basic 直接 head（含已退市会导致与日线错位）
            uni = self._universe_bs_codes(trade_date)
            by_code = df.set_index("code", drop=False)
            missing = [c for c in uni if c not in by_code.index]
            if missing:
                logger.warning(
                    "stock_basic 缺少 %s 只 universe 代码，将用 code 占位名补齐",
                    len(missing),
                )
            rows: list[dict] = []
            for c in uni:
                if c in by_code.index:
                    r = by_code.loc[c]
                    if isinstance(r, pd.DataFrame):
                        r = r.iloc[0]
                    rows.append({
                        "code": c,
                        "code_name": str(r["code_name"]),
                        "ipoDate": r.get("ipoDate", ""),
                        "outDate": r.get("outDate", ""),
                    })
                else:
                    rows.append({
                        "code": c,
                        "code_name": c.split(".", 1)[-1],
                        "ipoDate": "",
                        "outDate": "",
                    })
            df = pd.DataFrame(rows)
        out = pd.DataFrame({
            "exchange_code": [from_baostock_code(c) for c in df["code"]],
            "symbol": df["code"].map(lambda c: c.split(".", 1)[1].zfill(6)),
            "name": df["code_name"].astype(str),
            "list_date": pd.to_datetime(df["ipoDate"], errors="coerce").dt.date,
            "delist_date": pd.to_datetime(df.get("outDate"), errors="coerce").dt.date,
        })
        out["delist_date"] = out["delist_date"].where(pd.notna(out["delist_date"]), None)
        return out

    def _query_k(
        self,
        bs_code: str,
        trade_date: dt.date,
        adjustflag: str,
        *,
        end_date: dt.date | None = None,
    ) -> pd.DataFrame:
        self._limiter.acquire()
        start = trade_date.isoformat()
        end = (end_date or trade_date).isoformat()
        rs = bs.query_history_k_data_plus(
            bs_code,
            _K_FIELDS,
            start_date=start,
            end_date=end,
            frequency="d",
            adjustflag=adjustflag,
        )
        return _rs_to_df(rs)

    def prefetch_daily_range_to_raw(
        self,
        start: dt.date,
        end: dt.date,
        *,
        open_days: list[dt.date] | None = None,
    ) -> dict[str, int]:
        """一次扫全市场：区间 K 线写入各日 Raw（daily_bar + adj_factor）。

        相对按日逐标的拉取，标的数 × 查询次数从 O(days) 降到 O(1)。
        返回 {\"YYYY-MM-DD\": daily_bar_rows}。
        """
        from qdata.lake.raw import write_raw

        days = open_days or [
            start + dt.timedelta(days=i) for i in range((end - start).days + 1)
        ]
        days = [d for d in days if start <= d <= end]
        if not days:
            return {}

        day_set = set(days)
        bar_parts: dict[dt.date, list[pd.DataFrame]] = {d: [] for d in days}
        adj_parts: dict[dt.date, list[dict]] = {d: [] for d in days}
        ok_symbols = 0
        first_err: str | None = None
        codes: list[str] = []

        logger.info(
            "baostock 区间预取 %s~%s，交易日 %s 天",
            start, end, len(days),
        )
        with _baostock_session(timeout_sec=60.0):
            self._universe_cache = None
            codes = self._universe_bs_codes(days[-1])
            logger.info("baostock 区间预取标的数 %s", len(codes))
            for i, code in enumerate(codes, 1):
                try:
                    raw = self._query_k(code, start, "3", end_date=end)
                    hfq = self._query_k(code, start, "1", end_date=end)
                except Exception as e:
                    if first_err is None:
                        first_err = f"{code}: {e}"
                        logger.warning("baostock 区间预取首个失败: %s", first_err)
                    continue
                if raw.empty:
                    continue

                raw = raw.copy()
                raw["trade_date"] = pd.to_datetime(raw["date"], errors="coerce").dt.date
                raw = raw[raw["trade_date"].isin(day_set)]
                if raw.empty:
                    continue

                hfq_by_date: dict[dt.date, float] = {}
                if not hfq.empty:
                    hfq = hfq.copy()
                    hfq["trade_date"] = pd.to_datetime(hfq["date"], errors="coerce").dt.date
                    for _, hr in hfq.iterrows():
                        td = hr["trade_date"]
                        if td in day_set:
                            hfq_by_date[td] = float(
                                pd.to_numeric(hr["close"], errors="coerce") or 0.0
                            )

                part_all = self._normalize_k_bars(raw)
                if part_all.empty:
                    continue
                ok_symbols += 1
                for td, g in part_all.groupby("trade_date", sort=False):
                    if td not in bar_parts:
                        continue
                    bar_parts[td].append(g.reset_index(drop=True))
                    close = float(g.iloc[0]["close"] or 0.0)
                    hfq_close = hfq_by_date.get(td, 0.0)
                    factor = (hfq_close / close) if close and hfq_close else 1.0
                    adj_parts[td].append({
                        "exchange_code": from_baostock_code(code),
                        "trade_date": td,
                        "adj_factor": float(factor),
                    })

                if i == 1 or i % 20 == 0 or i == len(codes):
                    logger.info(
                        "baostock 区间预取进度 %s/%s，有行情标的 %s",
                        i, len(codes), ok_symbols,
                    )

        if ok_symbols == 0:
            raise RuntimeError(
                f"baostock 区间预取 {start}~{end} 成功 0/{len(codes)}。"
                f"{(' 首个错误: ' + first_err) if first_err else ''}"
            )

        out: dict[str, int] = {}
        for d in days:
            frames = bar_parts[d]
            if not frames:
                logger.warning("baostock 区间预取 %s 无行情行，跳过写 Raw", d)
                continue
            bar_df = pd.concat(frames, ignore_index=True)
            write_raw(self.source, "daily_bar", d, bar_df)
            adj_df = pd.DataFrame(adj_parts[d], columns=_EMPTY["adj_factor"])
            if not adj_df.empty:
                write_raw(self.source, "adj_factor", d, adj_df)
            out[d.isoformat()] = len(bar_df)
            print(
                f"prefetch[{self.source}] daily_bar+adj {d}: "
                f"{len(bar_df)} bars / {len(adj_df)} adj"
            )
        return out

    def _fetch_daily_bar(self, trade_date: dt.date) -> pd.DataFrame:
        """拉取日线；同趟拉后复权价并缓存 adj_factor，避免二次全市场扫描。"""
        codes = self._universe_bs_codes(trade_date)
        frames: list[pd.DataFrame] = []
        adj_rows: list[dict] = []
        first_err: str | None = None
        for i, code in enumerate(codes, 1):
            try:
                raw = self._query_k(code, trade_date, adjustflag="3")
                hfq = self._query_k(code, trade_date, adjustflag="1")
            except Exception as e:
                if first_err is None:
                    first_err = f"{code}: {e}"
                    logger.warning("baostock daily_bar 首个失败: %s", first_err)
                continue
            if raw.empty:
                continue
            part = self._normalize_k_bar(raw, trade_date)
            if not part.empty:
                frames.append(part)
                close = float(pd.to_numeric(raw.iloc[0]["close"], errors="coerce") or 0.0)
                hfq_close = (
                    float(pd.to_numeric(hfq.iloc[0]["close"], errors="coerce") or 0.0)
                    if not hfq.empty
                    else 0.0
                )
                factor = (hfq_close / close) if close and hfq_close else 1.0
                adj_rows.append({
                    "exchange_code": from_baostock_code(code),
                    "trade_date": trade_date,
                    "adj_factor": float(factor),
                })
            if i == 1 or i % 20 == 0 or i == len(codes):
                logger.info(
                    "baostock daily_bar 进度 %s/%s，成功 %s（已缓存 adj）",
                    i, len(codes), len(frames),
                )
        if not frames:
            raise RuntimeError(
                f"baostock daily_bar {trade_date} 成功 0/{len(codes)}。"
                f"{(' 首个错误: ' + first_err) if first_err else ''}"
            )
        if adj_rows:
            self._adj_cache[trade_date] = pd.DataFrame(adj_rows, columns=_EMPTY["adj_factor"])
        return pd.concat(frames, ignore_index=True)

    def _normalize_k_bar(self, raw: pd.DataFrame, trade_date: dt.date) -> pd.DataFrame:
        df = raw.copy()
        df["trade_date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
        df = df[df["trade_date"] == trade_date]
        return self._normalize_k_bars(df)

    def _normalize_k_bars(self, raw: pd.DataFrame) -> pd.DataFrame:
        """标准化已含 trade_date 列的 K 线（可多日）。"""
        if raw is None or raw.empty:
            return pd.DataFrame(columns=_EMPTY["daily_bar"])
        df = raw.copy()
        if "trade_date" not in df.columns:
            df["trade_date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
        df["exchange_code"] = df["code"].map(from_baostock_code)
        for c in ("open", "high", "low", "close", "preclose", "volume", "amount"):
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors="coerce")
        df = df.rename(columns={"preclose": "pre_close"})
        # BaoStock volume 已是股
        df["volume"] = df["volume"].fillna(0).astype("int64")
        return df[[
            "exchange_code", "trade_date", "open", "high", "low", "close",
            "pre_close", "volume", "amount",
        ]].dropna(subset=["close"])

    def _fetch_adj_factor(self, trade_date: dt.date) -> pd.DataFrame:
        cached = self._adj_cache.pop(trade_date, None)
        if cached is not None and not cached.empty:
            logger.info(
                "baostock adj_factor %s: 使用 daily_bar 同趟缓存 %s 行",
                trade_date, len(cached),
            )
            return cached

        # 续跑：日线已在 lake 时只补后复权价（每标的 1 次查询，而非 2 次）
        closes = self._closes_from_lake(trade_date)
        codes = self._universe_bs_codes(trade_date)
        rows: list[dict] = []
        first_err: str | None = None
        for i, code in enumerate(codes, 1):
            try:
                hfq = self._query_k(code, trade_date, "1")
                close = closes.get(code)
                if close is None:
                    raw = self._query_k(code, trade_date, "3")
                    if raw.empty:
                        continue
                    close = float(pd.to_numeric(raw.iloc[0]["close"], errors="coerce") or 0.0)
            except Exception as e:
                if first_err is None:
                    first_err = f"{code}: {e}"
                continue
            if hfq.empty or not close:
                continue
            hfq_close = float(pd.to_numeric(hfq.iloc[0]["close"], errors="coerce") or 0.0)
            factor = (hfq_close / close) if close else 1.0
            rows.append({
                "exchange_code": from_baostock_code(code),
                "trade_date": trade_date,
                "adj_factor": float(factor),
            })
            if i == 1 or i % 20 == 0 or i == len(codes):
                logger.info(
                    "baostock adj_factor 进度 %s/%s，成功 %s（lake_close=%s）",
                    i, len(codes), len(rows), bool(closes),
                )
        if not rows:
            raise RuntimeError(
                f"baostock adj_factor {trade_date} 成功 0/{len(codes)}。"
                f"{(' 首个错误: ' + first_err) if first_err else ''}"
            )
        return pd.DataFrame(rows, columns=_EMPTY["adj_factor"])

    def _closes_from_lake(self, trade_date: dt.date) -> dict[str, float]:
        """从已落盘 daily_bar 读取收盘价，键为 baostock code。"""
        try:
            from qdata.lake.raw import read_raw

            bar = read_raw(self.source, "daily_bar", trade_date)
        except FileNotFoundError:
            return {}
        if bar is None or bar.empty or "exchange_code" not in bar.columns:
            return {}
        out: dict[str, float] = {}
        for _, r in bar.iterrows():
            try:
                out[to_baostock_code(str(r["exchange_code"]))] = float(r["close"])
            except Exception:
                continue
        return out

    def _fetch_daily_basic(self, trade_date: dt.date) -> pd.DataFrame:
        codes = self._universe_bs_codes(trade_date)
        rows: list[dict] = []
        for code in codes:
            try:
                raw = self._query_k(code, trade_date, "3")
            except Exception:
                continue
            if raw.empty:
                continue
            rows.append({
                "exchange_code": from_baostock_code(code),
                "trade_date": trade_date,
                "turnover_rate": float(pd.to_numeric(raw.iloc[0].get("turn"), errors="coerce") or 0.0),
            })
        return pd.DataFrame(rows, columns=_EMPTY["daily_basic"]) if rows else pd.DataFrame(columns=_EMPTY["daily_basic"])

    def _fetch_suspend(self, trade_date: dt.date) -> pd.DataFrame:
        self._limiter.acquire()
        rs = bs.query_all_stock(day=trade_date.isoformat())
        df = _rs_to_df(rs)
        if df.empty:
            return pd.DataFrame(columns=_EMPTY["suspend"])
        df = df[df["code"].map(is_baostock_a_share)]
        # tradeStatus: 1 正常，0 停牌
        stopped = df[df["tradeStatus"].astype(str) == "0"]
        if stopped.empty:
            return pd.DataFrame(columns=_EMPTY["suspend"])
        return pd.DataFrame({
            "exchange_code": [from_baostock_code(c) for c in stopped["code"]],
            "suspend_date": trade_date,
        })

    def _fetch_income(self, trade_date: dt.date) -> pd.DataFrame:
        logger.warning(
            "BaoStock 无稳定的按公告日利润表接口，income 返回空表；"
            "请用 data_source=akshare 或 auto 回退拉取 income"
        )
        return pd.DataFrame(columns=_EMPTY["income"])
