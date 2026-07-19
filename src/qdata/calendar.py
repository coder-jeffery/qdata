"""交易日历：优先读 ClickHouse trade_calendar；空表时可回退或同步。"""

from __future__ import annotations

import datetime as dt
import logging
from functools import lru_cache

import pandas as pd

from qdata import db

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _open_days() -> tuple[dt.date, ...]:
    try:
        df = db.query_df(
            "SELECT cal_date FROM trade_calendar WHERE is_open = 1 ORDER BY cal_date"
        )
    except Exception as e:
        logger.warning("读取 trade_calendar 失败: %s", e)
        return ()
    if df is None or df.empty:
        return ()
    return tuple(pd.to_datetime(df["cal_date"]).dt.date.tolist())


def clear_cache() -> None:
    fn = _open_days
    if hasattr(fn, "cache_clear"):
        fn.cache_clear()


def is_trading_day(d: dt.date) -> bool:
    days = _open_days()
    if days:
        return d in set(days)
    # 无日历时：工作日近似（回填联调兜底，正式环境应先 sync_calendar）
    return d.weekday() < 5


def prev_trading_day(d: dt.date) -> dt.date:
    """严格小于 d 的最近交易日。"""
    days = list(_open_days())
    if not days:
        cur = d - dt.timedelta(days=1)
        while cur.weekday() >= 5:
            cur -= dt.timedelta(days=1)
        return cur
    idx = _bisect_left(days, d)
    if idx == 0:
        raise ValueError(f"{d} 早于日历起点")
    return days[idx - 1]


def trading_days_between(start: dt.date, end: dt.date) -> list[dt.date]:
    if start > end:
        return []
    days = _open_days()
    if days:
        return [d for d in days if start <= d <= end]
    logger.warning(
        "trade_calendar 为空，按周一至周五近似交易日；"
        "请运行: python -m qdata.jobs.sync_calendar --start %s --end %s",
        start, end,
    )
    out: list[dt.date] = []
    cur = start
    while cur <= end:
        if cur.weekday() < 5:
            out.append(cur)
        cur += dt.timedelta(days=1)
    return out


def upsert_calendar(rows: pd.DataFrame) -> int:
    """写入/覆盖 trade_calendar。rows 需含 cal_date, is_open[, prev_open, next_open]。"""
    if rows is None or rows.empty:
        return 0
    df = rows.copy()
    df["cal_date"] = pd.to_datetime(df["cal_date"]).dt.date
    df = df.sort_values("cal_date").reset_index(drop=True)
    opens = df.loc[df["is_open"].astype(int) == 1, "cal_date"].tolist()
    prev_map: dict[dt.date, dt.date] = {}
    next_map: dict[dt.date, dt.date] = {}
    for i, d in enumerate(opens):
        if i > 0:
            prev_map[d] = opens[i - 1]
        if i + 1 < len(opens):
            next_map[d] = opens[i + 1]
    # 非交易日也填最近 prev/next
    all_dates = df["cal_date"].tolist()
    for i, d in enumerate(all_dates):
        if d not in prev_map:
            # 向前找
            for j in range(i - 1, -1, -1):
                if all_dates[j] in set(opens) or df.loc[j, "is_open"] == 1:
                    if int(df.loc[j, "is_open"]) == 1:
                        prev_map[d] = all_dates[j]
                        break
        if d not in next_map:
            for j in range(i + 1, len(all_dates)):
                if int(df.loc[j, "is_open"]) == 1:
                    next_map[d] = all_dates[j]
                    break
    # 缺省用自身
    df["prev_open"] = df["cal_date"].map(lambda x: prev_map.get(x, x))
    df["next_open"] = df["cal_date"].map(lambda x: next_map.get(x, x))
    df["is_open"] = df["is_open"].astype("uint8")
    # 幂等：删区间再插
    d0, d1 = df["cal_date"].min(), df["cal_date"].max()
    ch = db.client()
    ch.command(
        "ALTER TABLE trade_calendar DELETE WHERE cal_date >= %(a)s AND cal_date <= %(b)s",
        parameters={"a": d0, "b": d1},
    )
    n = db.insert_df("trade_calendar", df[["cal_date", "is_open", "prev_open", "next_open"]])
    clear_cache()
    return n


def _bisect_left(days: list[dt.date], d: dt.date) -> int:
    import bisect

    return bisect.bisect_left(days, d)
