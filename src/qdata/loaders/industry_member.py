"""行业分类区间表 Loader：属性 SCD2 → industry_member。"""

from __future__ import annotations

import datetime as dt
import logging

import pandas as pd

from qdata import db
from qdata.industry.scd2 import attribute_snapshots_to_intervals

logger = logging.getLogger(__name__)


def map_industry_security_id(intervals: pd.DataFrame) -> pd.DataFrame:
    """exchange_code → security_id；缺映射告警跳过。"""
    if intervals is None or intervals.empty:
        return pd.DataFrame(columns=["security_id", "level", "industry", "in_date", "out_date"])

    master = db.query_df(
        "SELECT DISTINCT exchange_code, security_id FROM security_master"
    )
    if master is None or master.empty:
        raise RuntimeError(
            "security_master 为空：请先 "
            "python -m qdata.loaders.security_master --date <日> --fetch"
        )
    merged = intervals.merge(master, on="exchange_code", how="left")
    miss = merged[merged["security_id"].isna()]["exchange_code"].unique()
    if len(miss) > 0:
        logger.warning(
            "industry_member 跳过 %s 只无主数据映射（例: %s）",
            len(miss),
            list(miss[:5]),
        )
        merged = merged.dropna(subset=["security_id"])
    if merged.empty:
        raise RuntimeError("行业分类在 security_master 中无任何映射")
    merged["security_id"] = merged["security_id"].astype("uint32")
    return merged[["security_id", "level", "industry", "in_date", "out_date"]]


def snapshot_to_intervals(df: pd.DataFrame) -> pd.DataFrame:
    code_intervals = attribute_snapshots_to_intervals(df)
    return map_industry_security_id(code_intervals)


def replace_industry_members(
    intervals: pd.DataFrame,
    levels: list[str] | None = None,
) -> int:
    """按 level 替换区间行（幂等）。"""
    if intervals is None or intervals.empty:
        return 0
    lvls = levels or sorted(intervals["level"].astype(str).unique().tolist())
    ch = db.client()
    for level in lvls:
        ch.command(
            "ALTER TABLE industry_member DELETE WHERE level = %(lv)s",
            parameters={"lv": level},
        )
    part = intervals[intervals["level"].isin(lvls)]
    return db.insert_df("industry_member", part)


def verify_pit(level: str, on: dt.date) -> int:
    df = db.query_df(
        """
        SELECT count() AS n FROM industry_member
        WHERE level = %(lv)s AND in_date <= %(d)s AND out_date > %(d)s
        """,
        {"lv": level, "d": on},
    )
    return int(df["n"][0]) if df is not None and not df.empty else 0


class IndustryMemberLoader:
    table = "industry_member"

    def load_dataframe(self, snap: pd.DataFrame) -> int:
        intervals = snapshot_to_intervals(snap)
        n = replace_industry_members(intervals)
        logger.info("industry_member upsert %s interval rows", n)
        return n

    def load_raw(self, trade_date: dt.date, source: str = "akshare") -> int:
        from qdata.lake.raw import read_raw

        snap = read_raw(source, "industry_member", trade_date)
        return self.load_dataframe(snap)

    def load_scd2(self, snaps: pd.DataFrame) -> int:
        return self.load_dataframe(snaps)
