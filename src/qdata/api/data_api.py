"""DataAPI：研究与回测的唯一数据入口。

设计目标：让「写对」成为默认行为——
- get_price 强制显式声明复权方式
- get_universe 支持 ALL（当日有行情的股票）或指数成分
- get_industry 时点申万 L1/L2（需 industry_member）
- get_fundamental 只返回 T 日可见（ann_date <= T）的数据，从接口层杜绝前视
- 锁定 ``version``（发布日）后，行情/选股域读取不超过该 as-of 日
"""

from __future__ import annotations

import datetime as dt
from typing import Literal

import pandas as pd

from qdata import db

Adjust = Literal["none", "pre", "post"]

# get_universe 支持的过滤器
_FILTERS = {"st", "suspended", "listed_days<120", "limit_up_open"}


class DataAPI:
    def __init__(self, version: str | None = None, *, allow_unpublished: bool = False):
        """version: 锁定 dataset_version 中已发布的版本号（如 '2026-07-15'）。

        None 表示最新已发布版本。allow_unpublished=True 时，无发布版本可用
        'unpublished' 占位，便于回填后立刻冒烟（正式回测应关闭）。

        当 version 为 ISO 日期时，``get_price`` / ``get_universe`` / ``load_factor``
        会截断到该日（含），避免读到「发布点之后」的数据。
        """
        self.allow_unpublished = allow_unpublished
        self.version = version or self._latest_version()

    def asof_date(self) -> dt.date | None:
        """版本对应的 as-of 日；unpublished 或无法解析时返回 None。"""
        v = str(self.version or "").strip()
        if not v or v == "unpublished":
            return None
        try:
            return dt.date.fromisoformat(v[:10])
        except ValueError:
            return None

    def _clamp_range(self, start: dt.date, end: dt.date) -> tuple[dt.date, dt.date] | None:
        asof = self.asof_date()
        if asof is None:
            return start, end
        end = min(end, asof)
        if start > end:
            return None
        return start, end

    # ------------------------------------------------------------------
    # 行情
    # ------------------------------------------------------------------
    def get_price(
        self,
        codes: list[str],
        start: dt.date,
        end: dt.date,
        adjust: Adjust = "post",
        fields: tuple[str, ...] = ("open", "high", "low", "close", "volume"),
    ) -> pd.DataFrame:
        """日线行情，复权在读取时计算。

        后复权：price * adj_factor（净值连续，回测常用）
        前复权：price * adj_factor / 最新 adj_factor（贴近当前市价）

        若 DataAPI 锁定了发布 version（ISO 日），则 ``end`` 不超过该日。
        """
        if not codes:
            return pd.DataFrame()
        clamped = self._clamp_range(start, end)
        if clamped is None:
            return pd.DataFrame()
        start, end = clamped
        df = db.query_df(
            """
            SELECT b.trade_date, m.exchange_code, b.open, b.high, b.low, b.close,
                   b.volume, b.amount, b.adj_factor, b.up_limit, b.down_limit,
                   b.is_suspended, b.is_st
            FROM daily_bar b
            INNER JOIN security_master m USING (security_id)
            WHERE m.exchange_code IN %(codes)s
              AND b.trade_date BETWEEN %(s)s AND %(e)s
            ORDER BY m.exchange_code, b.trade_date
            """,
            {"codes": tuple(codes), "s": start, "e": end},
        )
        if df.empty:
            return df
        if adjust != "none":
            price_cols = [c for c in ("open", "high", "low", "close") if c in df.columns]
            if adjust == "post":
                factor = df["adj_factor"]
            else:  # pre：以每只股票区间内最新因子为基准
                latest = df.groupby("exchange_code")["adj_factor"].transform("last")
                factor = df["adj_factor"] / latest.replace(0, pd.NA)
            df[price_cols] = df[price_cols].mul(factor, axis=0)
        keep = [
            "trade_date", "exchange_code", *fields,
            "up_limit", "down_limit", "is_suspended", "is_st",
        ]
        out = df[[c for c in keep if c in df.columns]]
        out.attrs["dataset_version"] = self.version
        return out

    # ------------------------------------------------------------------
    # 选股域
    # ------------------------------------------------------------------
    def get_universe(
        self,
        index_code: str,
        date: dt.date,
        filters: list[str] | None = None,
    ) -> list[str]:
        """date 时点的选股域。

        index_code:
          - 'ALL' / '*'：当日 daily_bar 有行情的全部股票
          - 指数代码（如 '000905.SH'）：读 index_member 区间表

        若锁定了发布 version，则 ``date`` 不得晚于该 as-of 日（否则返回空列表）。
        """
        filters = filters or []
        unknown = set(filters) - _FILTERS
        if unknown:
            raise ValueError(f"未知过滤器: {unknown}，支持 {_FILTERS}")

        asof = self.asof_date()
        if asof is not None and date > asof:
            return []

        if index_code in ("ALL", "*", "all"):
            df = db.query_df(
                """
                SELECT m.exchange_code, b.is_st, b.is_suspended, m.list_date
                FROM daily_bar b
                INNER JOIN security_master m USING (security_id)
                WHERE b.trade_date = %(d)s
                """,
                {"d": date},
            )
        else:
            df = db.query_df(
                """
                SELECT m.exchange_code, b.is_st, b.is_suspended, m.list_date
                FROM index_member im
                INNER JOIN security_master m ON m.security_id = im.security_id
                LEFT JOIN daily_bar b ON b.security_id = im.security_id AND b.trade_date = %(d)s
                WHERE im.index_code = %(idx)s
                  AND im.in_date <= %(d)s AND im.out_date > %(d)s
                """,
                {"idx": index_code, "d": date},
            )
        if df.empty:
            return []

        if "st" in filters:
            df = df[df["is_st"].fillna(0).astype(int) != 1]
        if "suspended" in filters:
            df = df[df["is_suspended"].fillna(0).astype(int) != 1]
        if "listed_days<120" in filters:
            cutoff = date - dt.timedelta(days=120)
            df = df[pd.to_datetime(df["list_date"]).dt.date <= cutoff]
        if "limit_up_open" in filters:
            # 剔除当日收盘一字涨停（次日开盘不可买的近似；严格应用需次日 open）
            lim = db.query_df(
                """
                SELECT m.exchange_code
                FROM daily_bar b
                INNER JOIN security_master m USING (security_id)
                WHERE b.trade_date = %(d)s
                  AND b.is_suspended = 0
                  AND abs(b.close - b.up_limit) < 1e-6
                """,
                {"d": date},
            )
            blocked = set(lim["exchange_code"].tolist()) if not lim.empty else set()
            df = df[~df["exchange_code"].isin(blocked)]
        return sorted(df["exchange_code"].astype(str).unique().tolist())

    def get_industry(
        self,
        codes: list[str],
        date: dt.date,
        level: Literal["sw_l1", "sw_l2"] = "sw_l1",
    ) -> pd.Series:
        """时点行业分类（申万 L1/L2）。

        返回 Series：index=exchange_code，value=industry（``801010.SI|农林牧渔``）。
        需先 sync_industry_member。
        """
        if not codes:
            return pd.Series(dtype="object")
        if level not in ("sw_l1", "sw_l2"):
            raise ValueError(f"level 需为 sw_l1|sw_l2，收到 {level!r}")
        df = db.query_df(
            """
            SELECT m.exchange_code, im.industry
            FROM industry_member im
            INNER JOIN security_master m ON m.security_id = im.security_id
            WHERE m.exchange_code IN %(codes)s
              AND im.level = %(lv)s
              AND im.in_date <= %(d)s AND im.out_date > %(d)s
            """,
            {"codes": tuple(codes), "lv": level, "d": date},
        )
        if df.empty:
            return pd.Series(dtype="object")
        return df.drop_duplicates("exchange_code").set_index("exchange_code")["industry"]

    # ------------------------------------------------------------------
    # PIT 财务
    # ------------------------------------------------------------------
    def get_fundamental(self, field: str, codes: list[str], date: dt.date) -> pd.Series:
        """T 日可见的最新财务科目值（Point-in-Time）。

        对每只股票：取 ann_date <= date 的记录中，report_date 最大者；
        同一 report_date 有更正公告时取 ann_date 最大者。

        若锁定了发布 version，则查询日不超过 as-of。
        """
        if not codes:
            return pd.Series(dtype="float64")
        asof = self.asof_date()
        if asof is not None:
            date = min(date, asof)
        df = db.query_df(
            """
            SELECT m.exchange_code, f.fields[%(f)s] AS value
            FROM fin_statement f
            INNER JOIN security_master m USING (security_id)
            WHERE m.exchange_code IN %(codes)s
              AND f.ann_date <= %(d)s
              AND mapContains(f.fields, %(f)s)
            ORDER BY f.report_date DESC, f.ann_date DESC
            LIMIT 1 BY f.security_id
            """,
            {"f": field, "codes": tuple(codes), "d": date},
        )
        if df.empty:
            return pd.Series(dtype="float64")
        return df.set_index("exchange_code")["value"]

    def list_versions(self, dataset: str = "daily_bar") -> pd.DataFrame:
        return db.query_df(
            """
            SELECT dataset, version, row_count, published, note
            FROM dataset_version
            WHERE dataset = %(d)s
            ORDER BY version DESC
            """,
            {"d": dataset},
        )

    # ------------------------------------------------------------------
    # 因子读写
    # ------------------------------------------------------------------
    def save_factor(self, name: str, df: pd.DataFrame, version: str = "v1") -> int:
        """df 需含 trade_date / security_id / value 三列。"""
        out = df.assign(factor_name=name, version=version)
        return db.insert_df("factor_value", out[["trade_date", "security_id", "factor_name", "version", "value"]])

    def load_factor(
        self,
        name: str,
        start: dt.date,
        end: dt.date,
        version: str = "v1",
        *,
        with_code: bool = True,
    ) -> pd.DataFrame:
        """读取因子。with_code=True 时附带 exchange_code。

        若锁定了发布 version，则区间不超过 as-of 日。
        """
        clamped = self._clamp_range(start, end)
        if clamped is None:
            return pd.DataFrame()
        start, end = clamped
        if with_code:
            return db.query_df(
                """
                SELECT f.trade_date, f.security_id, m.exchange_code, f.value
                FROM factor_value f
                LEFT JOIN security_master m ON m.security_id = f.security_id
                WHERE f.factor_name = %(n)s AND f.version = %(v)s
                  AND f.trade_date BETWEEN %(s)s AND %(e)s
                ORDER BY f.trade_date, f.security_id
                """,
                {"n": name, "v": version, "s": start, "e": end},
            )
        return db.query_df(
            """
            SELECT trade_date, security_id, value FROM factor_value
            WHERE factor_name = %(n)s AND version = %(v)s
              AND trade_date BETWEEN %(s)s AND %(e)s
            ORDER BY trade_date, security_id
            """,
            {"n": name, "v": version, "s": start, "e": end},
        )

    # ------------------------------------------------------------------
    def _latest_version(self) -> str:
        try:
            df = db.query_df(
                "SELECT max(version) AS v FROM dataset_version WHERE dataset = 'daily_bar'"
            )
        except Exception as e:
            if self.allow_unpublished:
                return "unpublished"
            raise RuntimeError(f"无法读取 dataset_version: {e}") from e
        if df.empty or pd.isna(df["v"][0]) or not str(df["v"][0]).strip():
            if self.allow_unpublished:
                return "unpublished"
            raise RuntimeError(
                "没有已发布的数据版本。请先回填并发布，例如:\n"
                "  python -m qdata.jobs.backfill --start <d> --end <d> --source baostock\n"
                "或冒烟时使用 DataAPI(allow_unpublished=True)"
            )
        return str(df["v"][0])
