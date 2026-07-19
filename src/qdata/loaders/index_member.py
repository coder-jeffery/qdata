"""指数成分区间表 Loader：快照 SCD2 → index_member(in_date, out_date)。"""

from __future__ import annotations

import datetime as dt
import logging

import pandas as pd

from qdata import db
from qdata.index.scd2 import snapshots_to_intervals

logger = logging.getLogger(__name__)


def map_intervals_security_id(intervals: pd.DataFrame) -> pd.DataFrame:
    """exchange_code → security_id；缺映射告警跳过。"""
    if intervals is None or intervals.empty:
        return pd.DataFrame(columns=["index_code", "security_id", "in_date", "out_date"])

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
            "index_member 跳过 %s 只无主数据映射（例: %s）",
            len(miss),
            list(miss[:5]),
        )
        merged = merged.dropna(subset=["security_id"])
    if merged.empty:
        raise RuntimeError("指数成分在 security_master 中无任何映射")
    merged["security_id"] = merged["security_id"].astype("uint32")
    return merged[["index_code", "security_id", "in_date", "out_date"]]


def snapshot_to_intervals(df: pd.DataFrame) -> pd.DataFrame:
    """兼容旧名：单期或多期快照 → 带 security_id 的区间。"""
    code_intervals = snapshots_to_intervals(df)
    return map_intervals_security_id(code_intervals)


def replace_index_members(intervals: pd.DataFrame, index_codes: list[str] | None = None) -> int:
    """按指数代码替换区间行（幂等）。"""
    if intervals is None or intervals.empty:
        return 0
    codes = index_codes or sorted(intervals["index_code"].astype(str).unique().tolist())
    ch = db.client()
    for code in codes:
        ch.command(
            "ALTER TABLE index_member DELETE WHERE index_code = %(c)s",
            parameters={"c": code},
        )
    part = intervals[intervals["index_code"].isin(codes)]
    return db.insert_df("index_member", part)


def verify_pit(index_code: str, on: dt.date) -> int:
    """返回时点成分数量。"""
    df = db.query_df(
        """
        SELECT count() AS n FROM index_member
        WHERE index_code = %(i)s AND in_date <= %(d)s AND out_date > %(d)s
        """,
        {"i": index_code, "d": on},
    )
    return int(df["n"][0]) if df is not None and not df.empty else 0


class IndexMemberLoader:
    """从 Raw 快照或 DataFrame 写入 index_member。"""

    table = "index_member"

    def load_dataframe(self, snap: pd.DataFrame) -> int:
        intervals = snapshot_to_intervals(snap)
        n = replace_index_members(intervals)
        logger.info("index_member upsert %s interval rows", n)
        return n

    def load_raw(self, trade_date: dt.date, source: str = "akshare") -> int:
        from qdata.lake.raw import read_raw

        snap = read_raw(source, "index_member", trade_date)
        return self.load_dataframe(snap)

    def load_scd2(self, snaps: pd.DataFrame) -> int:
        """显式多期 SCD2 重建。"""
        return self.load_dataframe(snaps)
