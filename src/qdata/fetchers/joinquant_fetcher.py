"""JoinQuant（聚宽）jqdatasdk 适配器。

开关：QDATA_JOINQUANT_ENABLED=true|false（默认 false）
凭证：QDATA_JOINQUANT_USER / QDATA_JOINQUANT_PASSWORD
文档：https://www.joinquant.com/help/api/doc?name=JQDatadoc

日线按标的批量拉取；全市场较慢，可用 QDATA_AKSHARE_MAX_SYMBOLS 联调截断。
"""

from __future__ import annotations

import datetime as dt
import logging

import pandas as pd

from qdata.config import settings
from qdata.fetchers.base import Fetcher, RateLimiter
from qdata.fetchers.schema import EMPTY_SCHEMAS
from qdata.symbols import (
    from_joinquant_code,
    is_joinquant_a_share,
    to_pure_code,
)

logger = logging.getLogger(__name__)


def ensure_joinquant_enabled() -> None:
    if not settings().joinquant_enabled:
        raise RuntimeError(
            "JoinQuant 渠道已关闭。请在 .env 设置 QDATA_JOINQUANT_ENABLED=true，"
            "并配置 QDATA_JOINQUANT_USER / QDATA_JOINQUANT_PASSWORD"
        )


class JoinquantFetcher(Fetcher):
    source = "joinquant"

    def __init__(self) -> None:
        ensure_joinquant_enabled()
        s = settings()
        user = (s.joinquant_user or "").strip()
        password = (s.joinquant_password or "").strip()
        if not user or not password:
            raise RuntimeError(
                "未配置 JoinQuant 账号。请在 .env 设置 "
                "QDATA_JOINQUANT_USER / QDATA_JOINQUANT_PASSWORD"
            )
        # jqdatasdk 账号一般为申请 JQData 时填写的 11 位手机号
        if user.isdigit() and len(user) != 11:
            raise RuntimeError(
                f"QDATA_JOINQUANT_USER={user!r} 长度={len(user)}，"
                "应为申请 JQData 时填写的 11 位手机号（见 "
                "https://www.joinquant.com/default/index/sdk ）"
            )
        import jqdatasdk as jq

        super().__init__(RateLimiter(s.joinquant_rate_limit))
        self._max_symbols = s.akshare_max_symbols
        self._jq = jq
        self._auth(user, password)
        self._universe: list[str] | None = None  # jq codes
        logger.info("JoinQuant 渠道已启用（user=%s）", user)

    def _auth(self, user: str, password: str) -> None:
        self._limiter.acquire()
        try:
            self._jq.auth(user, password)
        except Exception as e:
            raise RuntimeError(
                f"JoinQuant 鉴权失败: {e}\n"
                "请核对 QDATA_JOINQUANT_USER（申请时的手机号）与官网登录密码，"
                "并确认已开通 JQData 调用权限："
                "https://www.joinquant.com/default/index/sdk"
            ) from e
        if not self._jq.is_auth():
            raise RuntimeError("JoinQuant auth 失败（请检查账号密码/权限）")

    def fetch_many(
        self,
        datasets: tuple[str, ...] | list[str],
        trade_date: dt.date,
    ) -> dict[str, pd.DataFrame]:
        """同一鉴权会话内拉多个数据集（避免三日表各登录一次）。"""
        out: dict[str, pd.DataFrame] = {}
        for ds in datasets:
            out[ds] = self.fetch(ds, trade_date)
        return out

    def _fetch_raw(self, dataset: str, trade_date: dt.date) -> pd.DataFrame:
        dispatch = {
            "stock_basic": lambda: self._fetch_stock_basic(trade_date),
            "daily_bar": lambda: self._fetch_daily_bar(trade_date),
            "adj_factor": lambda: self._fetch_adj_factor(trade_date),
            "daily_basic": lambda: self._fetch_daily_basic(trade_date),
            "suspend": lambda: self._fetch_suspend(trade_date),
            "income": lambda: self._fetch_income(trade_date),
            "balancesheet": lambda: self._fetch_balancesheet(trade_date),
            "cashflow": lambda: self._fetch_cashflow(trade_date),
        }
        if dataset not in dispatch:
            raise KeyError(f"joinquant 不支持数据集 {dataset}")
        return dispatch[dataset]()

    def _normalize(self, dataset: str, df: pd.DataFrame) -> pd.DataFrame:
        if df is None or df.empty:
            return pd.DataFrame(columns=EMPTY_SCHEMAS.get(dataset, []))
        return df.reset_index(drop=True)

    def _universe_jq(self, trade_date: dt.date) -> list[str]:
        if self._universe is not None:
            return self._universe
        self._limiter.acquire()
        sec = self._jq.get_all_securities(types=["stock"], date=trade_date.isoformat())
        if sec is None or sec.empty:
            self._universe = []
            return self._universe
        codes = [c for c in sec.index.astype(str).tolist() if is_joinquant_a_share(c)]
        codes = sorted(set(codes))
        if self._max_symbols and self._max_symbols > 0:
            codes = codes[: self._max_symbols]
            logger.info("JoinQuant MAX_SYMBOLS=%s，仅 %s 只", self._max_symbols, len(codes))
        self._universe = codes
        return codes

    def _fetch_stock_basic(self, trade_date: dt.date) -> pd.DataFrame:
        self._limiter.acquire()
        sec = self._jq.get_all_securities(types=["stock"], date=trade_date.isoformat())
        if sec is None or sec.empty:
            return pd.DataFrame(columns=EMPTY_SCHEMAS["stock_basic"])
        sec = sec.rename_axis("code").reset_index()
        sec["code"] = sec["code"].astype(str)
        sec = sec[sec["code"].map(is_joinquant_a_share)].copy()
        uni = self._universe_jq(trade_date)
        if uni:
            # 与 universe 对齐（含 MAX_SYMBOLS）
            by = sec.set_index("code", drop=False)
            rows = []
            for c in uni:
                if c not in by.index:
                    rows.append({
                        "code": c,
                        "display_name": to_pure_code(from_joinquant_code(c)),
                        "start_date": None,
                        "end_date": None,
                    })
                else:
                    r = by.loc[c]
                    if isinstance(r, pd.DataFrame):
                        r = r.iloc[0]
                    rows.append(r.to_dict())
            sec = pd.DataFrame(rows)
        name_col = "display_name" if "display_name" in sec.columns else "name"
        out = pd.DataFrame({
            "exchange_code": sec["code"].map(from_joinquant_code),
            "symbol": sec["code"].map(lambda c: to_pure_code(from_joinquant_code(c))),
            "name": sec[name_col].astype(str) if name_col in sec.columns else sec["code"].astype(str),
            "list_date": pd.to_datetime(sec.get("start_date"), errors="coerce").dt.date,
            "delist_date": pd.to_datetime(sec.get("end_date"), errors="coerce").dt.date,
        })
        out["delist_date"] = out["delist_date"].where(
            out["delist_date"].map(
                lambda x: isinstance(x, dt.date) and x < dt.date(2100, 1, 1)
            ),
            None,
        )
        return out

    def _get_price_panel(
        self,
        codes: list[str],
        trade_date: dt.date,
        *,
        fq: str | None,
        fields: list[str],
    ) -> pd.DataFrame:
        """批量 get_price；分块避免单次过大。"""
        if not codes:
            return pd.DataFrame()
        chunk = 200
        frames: list[pd.DataFrame] = []
        d = trade_date.isoformat()
        for i in range(0, len(codes), chunk):
            part = codes[i : i + chunk]
            self._limiter.acquire()
            try:
                df = self._jq.get_price(
                    part,
                    start_date=d,
                    end_date=d,
                    frequency="daily",
                    fields=fields,
                    skip_paused=False,
                    fq=fq,
                    panel=False,
                )
            except TypeError:
                # 旧版 SDK 无 panel 参数
                df = self._jq.get_price(
                    part,
                    start_date=d,
                    end_date=d,
                    frequency="daily",
                    fields=fields,
                    skip_paused=False,
                    fq=fq,
                )
            if df is None or (isinstance(df, pd.DataFrame) and df.empty):
                continue
            if not isinstance(df, pd.DataFrame):
                # panel / dict 少见路径：跳过
                continue
            frames.append(df)
            if i == 0 or (i // chunk) % 5 == 0:
                logger.info(
                    "joinquant get_price fq=%s 进度 %s/%s",
                    fq, min(i + chunk, len(codes)), len(codes),
                )
        if not frames:
            return pd.DataFrame()
        out = pd.concat(frames, ignore_index=False)
        return out.reset_index() if "code" not in getattr(out, "columns", []) else out

    def _fetch_daily_bar(self, trade_date: dt.date) -> pd.DataFrame:
        codes = self._universe_jq(trade_date)
        fields = ["open", "high", "low", "close", "volume", "money", "pre_close"]
        raw = self._get_price_panel(codes, trade_date, fq=None, fields=fields)
        if raw is None or raw.empty:
            raise RuntimeError(f"joinquant daily_bar {trade_date} 无数据")
        # 列名兼容：code / time / date
        code_col = "code" if "code" in raw.columns else ("security" if "security" in raw.columns else None)
        if code_col is None:
            raise RuntimeError(f"joinquant daily_bar 缺 code 列: {raw.columns.tolist()}")
        out = pd.DataFrame({
            "exchange_code": raw[code_col].map(from_joinquant_code),
            "trade_date": trade_date,
            "open": pd.to_numeric(raw["open"], errors="coerce"),
            "high": pd.to_numeric(raw["high"], errors="coerce"),
            "low": pd.to_numeric(raw["low"], errors="coerce"),
            "close": pd.to_numeric(raw["close"], errors="coerce"),
            "pre_close": pd.to_numeric(raw.get("pre_close"), errors="coerce"),
            # JoinQuant volume 已是股
            "volume": pd.to_numeric(raw["volume"], errors="coerce").fillna(0).astype("int64"),
            "amount": pd.to_numeric(raw.get("money"), errors="coerce").fillna(0.0),
        })
        if out["pre_close"].isna().all():
            out["pre_close"] = out["close"]
        return out.dropna(subset=["close"])

    def _fetch_adj_factor(self, trade_date: dt.date) -> pd.DataFrame:
        codes = self._universe_jq(trade_date)
        raw = self._get_price_panel(codes, trade_date, fq=None, fields=["close"])
        hfq = self._get_price_panel(codes, trade_date, fq="post", fields=["close"])
        if raw is None or raw.empty or hfq is None or hfq.empty:
            raise RuntimeError(f"joinquant adj_factor {trade_date} 无数据")
        code_col = "code" if "code" in raw.columns else "security"
        a = raw[[code_col, "close"]].rename(columns={"close": "c0"})
        b = hfq[[code_col, "close"]].rename(columns={"close": "c1"})
        m = a.merge(b, on=code_col, how="inner")
        m["c0"] = pd.to_numeric(m["c0"], errors="coerce")
        m["c1"] = pd.to_numeric(m["c1"], errors="coerce")
        m = m[(m["c0"] > 0) & m["c1"].notna()]
        return pd.DataFrame({
            "exchange_code": m[code_col].map(from_joinquant_code),
            "trade_date": trade_date,
            "adj_factor": (m["c1"] / m["c0"]).astype(float),
        })

    def _fetch_daily_basic(self, trade_date: dt.date) -> pd.DataFrame:
        """全市场估值/换手：优先 valuation；失败回退 get_price.turnover_ratio。

        单位对齐 Tushare Loader：股本万股、市值万元。
        """
        d = trade_date.isoformat()
        try:
            from jqdatasdk import query, valuation

            self._limiter.acquire()
            raw = self._jq.get_fundamentals(query(valuation), date=d)
        except Exception as e:
            logger.warning("joinquant valuation 失败，回退 get_price: %s", e)
            raw = None

        if raw is not None and not raw.empty and "code" in raw.columns:
            if self._max_symbols and self._max_symbols > 0:
                uni = set(self._universe_jq(trade_date))
                raw = raw[raw["code"].astype(str).isin(uni)]
            # JQ: market_cap 亿元 → 万元 ×10000；capitalization 已是万股
            out = pd.DataFrame({
                "exchange_code": raw["code"].astype(str).map(from_joinquant_code),
                "trade_date": trade_date,
                "turnover_rate": pd.to_numeric(raw.get("turnover_ratio"), errors="coerce"),
                "total_share": pd.to_numeric(raw.get("capitalization"), errors="coerce"),
                "float_share": pd.to_numeric(raw.get("circulating_cap"), errors="coerce"),
                "total_mv": pd.to_numeric(raw.get("market_cap"), errors="coerce") * 10000.0,
                "circ_mv": pd.to_numeric(
                    raw.get("circulating_market_cap"), errors="coerce"
                ) * 10000.0,
                "pe_ttm": pd.to_numeric(raw.get("pe_ratio"), errors="coerce"),
                "pb": pd.to_numeric(raw.get("pb_ratio"), errors="coerce"),
            })
            return out.dropna(subset=["exchange_code"]).reset_index(drop=True)

        # 回退：仅换手
        codes = self._universe_jq(trade_date)
        try:
            panel = self._get_price_panel(
                codes, trade_date, fq=None, fields=["close", "turnover_ratio"]
            )
        except Exception as e:
            logger.warning("joinquant daily_basic 回退失败: %s", e)
            return pd.DataFrame(columns=EMPTY_SCHEMAS["daily_basic"])
        if panel is None or panel.empty or "turnover_ratio" not in panel.columns:
            return pd.DataFrame(columns=EMPTY_SCHEMAS["daily_basic"])
        code_col = "code" if "code" in panel.columns else "security"
        return pd.DataFrame({
            "exchange_code": panel[code_col].map(from_joinquant_code),
            "trade_date": trade_date,
            "turnover_rate": pd.to_numeric(panel["turnover_ratio"], errors="coerce"),
            "total_share": None,
            "float_share": None,
            "total_mv": None,
            "circ_mv": None,
            "pe_ttm": None,
            "pb": None,
        }).dropna(subset=["turnover_rate"])

    def _fetch_suspend(self, trade_date: dt.date) -> pd.DataFrame:
        """当日停牌：get_price.paused=1（无停牌时合法空表）。"""
        codes = self._universe_jq(trade_date)
        try:
            raw = self._get_price_panel(codes, trade_date, fq=None, fields=["paused"])
        except Exception as e:
            logger.warning("joinquant suspend 失败: %s", e)
            return pd.DataFrame(columns=EMPTY_SCHEMAS["suspend"])
        if raw is None or raw.empty or "paused" not in raw.columns:
            return pd.DataFrame(columns=EMPTY_SCHEMAS["suspend"])
        code_col = "code" if "code" in raw.columns else "security"
        paused = raw[pd.to_numeric(raw["paused"], errors="coerce").fillna(0) > 0]
        if paused.empty:
            return pd.DataFrame(columns=EMPTY_SCHEMAS["suspend"])
        return pd.DataFrame({
            "exchange_code": paused[code_col].map(from_joinquant_code),
            "suspend_date": trade_date,
        }).drop_duplicates("exchange_code")

    def _stmt_by_pubdate(
        self,
        trade_date: dt.date,
        *,
        table_name: str,
        field_map: dict[str, str],
        empty_cols: list[str],
    ) -> pd.DataFrame:
        """按公告日 pubDate 拉取三大表（增量/全量均按日调用）。

        table_name: income | balance | cash_flow（jqdatasdk 模块名）
        field_map: JQ 列 → 标准 Raw 列（不含 code/pubDate/statDate）
        """
        try:
            import jqdatasdk as jqmod

            table = getattr(jqmod, table_name)
            query = jqmod.query
        except Exception as e:
            logger.warning("joinquant %s 导入失败: %s", table_name, e)
            return pd.DataFrame(columns=empty_cols)

        d = trade_date.isoformat()
        jq_fields = [table.code, table.pubDate, table.statDate]
        for jq_col in field_map:
            jq_fields.append(getattr(table, jq_col))
        try:
            self._limiter.acquire()
            q = query(*jq_fields).filter(table.pubDate == d)
            raw = self._jq.get_fundamentals(q, date=d)
        except Exception as e:
            logger.warning("joinquant %s@%s 失败: %s", table_name, d, e)
            return pd.DataFrame(columns=empty_cols)

        return normalize_jq_statement(raw, trade_date, field_map, empty_cols)

    def _fetch_income(self, trade_date: dt.date) -> pd.DataFrame:
        return self._stmt_by_pubdate(
            trade_date,
            table_name="income",
            field_map={
                "operating_revenue": "revenue",
                "np_parent_company_owners": "n_income_attr_p",
                "basic_eps": "basic_eps",
                "operating_profit": "operate_profit",
            },
            empty_cols=EMPTY_SCHEMAS["income"],
        )

    def _fetch_balancesheet(self, trade_date: dt.date) -> pd.DataFrame:
        return self._stmt_by_pubdate(
            trade_date,
            table_name="balance",
            field_map={
                "total_assets": "total_assets",
                "total_liability": "total_liab",
                "equities_parent_company_owners": "total_hldr_eqy_exc_min_int",
            },
            empty_cols=EMPTY_SCHEMAS["balancesheet"],
        )

    def _fetch_cashflow(self, trade_date: dt.date) -> pd.DataFrame:
        return self._stmt_by_pubdate(
            trade_date,
            table_name="cash_flow",
            field_map={
                "net_operate_cash_flow": "n_cashflow_act",
                "net_invest_cash_flow": "n_cashflow_inv_act",
                "net_finance_cash_flow": "n_cash_flows_fnc_act",
            },
            empty_cols=EMPTY_SCHEMAS["cashflow"],
        )


def normalize_jq_statement(
    raw: pd.DataFrame | None,
    trade_date: dt.date,
    field_map: dict[str, str],
    empty_cols: list[str],
) -> pd.DataFrame:
    """将 JQ get_fundamentals 结果规范为 qdata Raw 财务列（可单测）。"""
    if raw is None or raw.empty:
        return pd.DataFrame(columns=empty_cols)

    colmap = {c.lower(): c for c in raw.columns}
    code_c = colmap.get("code")
    pub_c = colmap.get("pubdate") or colmap.get("pub_date")
    stat_c = colmap.get("statdate") or colmap.get("stat_date")
    if not code_c or not pub_c or not stat_c:
        logger.warning("joinquant statement 缺关键列: %s", list(raw.columns))
        return pd.DataFrame(columns=empty_cols)

    ann = pd.to_datetime(raw[pub_c], errors="coerce").dt.date
    report = pd.to_datetime(raw[stat_c], errors="coerce").dt.date
    mask = (ann == trade_date) & ann.notna() & report.notna() & (ann >= report)
    raw = raw.loc[mask].copy()
    if raw.empty:
        return pd.DataFrame(columns=empty_cols)
    ann = ann.loc[mask].reset_index(drop=True)
    report = report.loc[mask].reset_index(drop=True)
    raw = raw.reset_index(drop=True)

    out: dict[str, object] = {
        "exchange_code": raw[code_c].astype(str).map(from_joinquant_code),
        "ann_date": ann,
        "report_date": report,
        "update_flag": "0",
    }
    for jq_col, std in field_map.items():
        src = colmap.get(jq_col.lower(), jq_col if jq_col in raw.columns else None)
        if src is None:
            out[std] = None
        else:
            out[std] = pd.to_numeric(raw[src], errors="coerce")
    return pd.DataFrame(out).reset_index(drop=True)
