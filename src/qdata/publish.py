"""数据集版本发布：质量通过后登记 dataset_version。"""

from __future__ import annotations

import datetime as dt
import logging

import pandas as pd

from qdata import db

logger = logging.getLogger(__name__)

_DATE_COL = {
    "daily_bar": "trade_date",
    "daily_basic": "trade_date",
    "fin_statement": "ann_date",
}


def is_published(
    trade_date: dt.date,
    dataset: str = "daily_bar",
    *,
    min_rows: int = 1,
) -> bool:
    """是否已有足够行数的发布版本（用于续跑跳过）。"""
    try:
        df = db.query_df(
            """
            SELECT row_count FROM dataset_version
            WHERE dataset = %(ds)s AND version = %(v)s
            LIMIT 1
            """,
            {"ds": dataset, "v": trade_date.isoformat()},
        )
    except Exception as e:
        logger.warning("读取 dataset_version 失败: %s", e)
        return False
    if df is None or df.empty:
        return False
    return int(df["row_count"].iloc[0] or 0) >= int(min_rows)


def publish_day(
    trade_date: dt.date,
    datasets: tuple[str, ...] = ("daily_bar",),
    *,
    note: str = "",
) -> dict[str, int]:
    """按日发布版本，返回 {dataset: row_count}。"""
    version = trade_date.isoformat()
    out: dict[str, int] = {}
    for dataset in datasets:
        date_col = _DATE_COL.get(dataset)
        if not date_col:
            logger.warning("未知 dataset=%s，跳过发布", dataset)
            continue
        n = int(
            db.query_df(
                f"SELECT count() AS n FROM {dataset} WHERE {date_col} = %(d)s",
                {"d": trade_date},
            )["n"][0]
        )
        # 幂等：删同版本再插
        db.client().command(
            "ALTER TABLE dataset_version DELETE WHERE dataset = %(ds)s AND version = %(v)s",
            parameters={"ds": dataset, "v": version},
        )
        db.insert_df(
            "dataset_version",
            pd.DataFrame([{
                "dataset": dataset,
                "version": version,
                "row_count": n,
                "note": note,
            }]),
        )
        out[dataset] = n
        logger.info("published %s version=%s rows=%s", dataset, version, n)
    return out
