"""ClickHouse 连接与幂等写入。

幂等策略：按分区先删后插。所有 Loader 复用 `replace_partition`，
保证任意 (dataset, trade_date) 重跑安全。
"""

from __future__ import annotations

import datetime as dt

import clickhouse_connect
import pandas as pd

from qdata.config import settings


def client():
    s = settings()
    try:
        return clickhouse_connect.get_client(
            host=s.ch_host,
            port=s.ch_port,
            database=s.ch_database,
            username=s.ch_user,
            password=s.ch_password,
        )
    except Exception as e:
        msg = str(e)
        if "Authentication failed" in msg or "AUTHENTICATION_FAILED" in msg:
            raise RuntimeError(
                f"ClickHouse 认证失败（{s.ch_user}@{s.ch_host}:{s.ch_port}/{s.ch_database}）。\n"
                f"请检查 .env 中 QDATA_CH_USER / QDATA_CH_PASSWORD，"
                f"本地 devops/clickhouse 的 default 密码见 "
                f"devops/clickhouse/config/users.xml。"
            ) from e
        raise


def insert_df(table: str, df: pd.DataFrame) -> int:
    """DataFrame 批量写入，返回行数。"""
    if df.empty:
        return 0
    client().insert_df(table, df)
    return len(df)


def replace_day(table: str, trade_date: dt.date, df: pd.DataFrame, date_col: str = "trade_date") -> int:
    """幂等写入某交易日的数据：先删该日已有行，再插入。

    ClickHouse 的 lightweight DELETE 对按天重跑的量级完全够用；
    若按月整体回补，可改为 DROP PARTITION 后整月插入。
    """
    ch = client()
    ch.command(
        f"ALTER TABLE {table} DELETE WHERE {date_col} = %(d)s",
        parameters={"d": trade_date},
    )
    return insert_df(table, df)


def query_df(sql: str, params: dict | None = None) -> pd.DataFrame:
    return client().query_df(sql, parameters=params or {})
