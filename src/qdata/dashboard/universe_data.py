"""选股域 / 行业 PIT 看板读数。"""

from __future__ import annotations

import datetime as dt
from typing import Any

import pandas as pd

from qdata import db

DEFAULT_INDEXES = ("000300.SH", "000905.SH", "000852.SH")


def _as_date(v) -> dt.date:
    return pd.Timestamp(v).date()


def latest_bar_date() -> dt.date | None:
    df = db.query_df("SELECT max(trade_date) AS mx FROM daily_bar")
    if df is None or df.empty or pd.isna(df.iloc[0]["mx"]):
        return None
    return _as_date(df.iloc[0]["mx"])


def index_universe_sizes(
    trade_date: dt.date,
    indexes: tuple[str, ...] = DEFAULT_INDEXES,
) -> pd.DataFrame:
    """as-of 日各指数成分规模（PIT）。"""
    rows = []
    for idx in indexes:
        df = db.query_df(
            """
            SELECT count() AS n
            FROM index_member
            WHERE index_code = %(idx)s
              AND in_date <= %(d)s AND out_date > %(d)s
            """,
            {"idx": idx, "d": trade_date},
        )
        n = int(df.iloc[0]["n"] or 0) if df is not None and not df.empty else 0
        rows.append({"trade_date": trade_date.isoformat(), "index_code": idx, "members": n})
    # ALL = 当日有日线
    all_df = db.query_df(
        "SELECT count() AS n FROM daily_bar WHERE trade_date = %(d)s",
        {"d": trade_date},
    )
    all_n = int(all_df.iloc[0]["n"] or 0) if all_df is not None and not all_df.empty else 0
    rows.insert(0, {"trade_date": trade_date.isoformat(), "index_code": "ALL", "members": all_n})
    return pd.DataFrame(rows)


def index_size_history(
    index_code: str,
    *,
    limit_days: int = 60,
) -> pd.DataFrame:
    """指数成分规模按日变化（用 daily_bar 交易日 × PIT 计数）。"""
    df = db.query_df(
        """
        SELECT d.trade_date AS trade_date, count() AS members
        FROM
        (
            SELECT DISTINCT trade_date
            FROM daily_bar
            ORDER BY trade_date DESC
            LIMIT %(n)s
        ) d
        CROSS JOIN index_member im
        WHERE im.index_code = %(idx)s
          AND im.in_date <= d.trade_date
          AND im.out_date > d.trade_date
        GROUP BY d.trade_date
        ORDER BY d.trade_date
        """,
        {"idx": index_code, "n": int(limit_days)},
    )
    if df is None or df.empty:
        return pd.DataFrame(columns=["trade_date", "members"])
    out = df.copy()
    out["trade_date"] = pd.to_datetime(out["trade_date"]).dt.date
    out["members"] = pd.to_numeric(out["members"], errors="coerce").fillna(0).astype(int)
    return out


def industry_distribution(
    trade_date: dt.date,
    *,
    level: str = "sw_l1",
    index_code: str | None = None,
) -> pd.DataFrame:
    """行业家数分布；可限定指数成分内。"""
    if level not in ("sw_l1", "sw_l2"):
        raise ValueError("level 需为 sw_l1|sw_l2")
    if index_code and index_code not in ("ALL", "*", "all", ""):
        df = db.query_df(
            """
            SELECT im.industry AS industry, count() AS members
            FROM industry_member im
            INNER JOIN index_member x ON x.security_id = im.security_id
            WHERE im.level = %(lv)s
              AND im.in_date <= %(d)s AND im.out_date > %(d)s
              AND x.index_code = %(idx)s
              AND x.in_date <= %(d)s AND x.out_date > %(d)s
            GROUP BY im.industry
            ORDER BY members DESC
            """,
            {"lv": level, "d": trade_date, "idx": index_code},
        )
    else:
        df = db.query_df(
            """
            SELECT industry, count() AS members
            FROM industry_member
            WHERE level = %(lv)s
              AND in_date <= %(d)s AND out_date > %(d)s
            GROUP BY industry
            ORDER BY members DESC
            """,
            {"lv": level, "d": trade_date},
        )
    if df is None or df.empty:
        return pd.DataFrame(columns=["industry", "industry_name", "members", "weight"])
    out = df.copy()
    out["industry_name"] = out["industry"].astype(str).map(
        lambda s: s.split("|", 1)[1] if "|" in s else s
    )
    total = int(out["members"].sum()) or 1
    out["weight"] = out["members"] / total
    return out


def industry_coverage(
    trade_date: dt.date,
    *,
    level: str = "sw_l1",
) -> dict[str, Any]:
    """行业映射覆盖率（相对当日日线）。"""
    uni = db.query_df(
        "SELECT count() AS n FROM daily_bar WHERE trade_date = %(d)s",
        {"d": trade_date},
    )
    uni_n = int(uni.iloc[0]["n"] or 0) if uni is not None and not uni.empty else 0
    mapped = db.query_df(
        """
        SELECT uniqExact(im.security_id) AS n
        FROM industry_member im
        INNER JOIN daily_bar b ON b.security_id = im.security_id AND b.trade_date = %(d)s
        WHERE im.level = %(lv)s
          AND im.in_date <= %(d)s AND im.out_date > %(d)s
        """,
        {"d": trade_date, "lv": level},
    )
    mapped_n = int(mapped.iloc[0]["n"] or 0) if mapped is not None and not mapped.empty else 0
    return {
        "trade_date": trade_date.isoformat(),
        "level": level,
        "universe": uni_n,
        "mapped": mapped_n,
        "coverage": (mapped_n / uni_n) if uni_n else 0.0,
        "n_industries": int(
            db.query_df(
                """
                SELECT uniqExact(industry) AS n
                FROM industry_member
                WHERE level = %(lv)s AND in_date <= %(d)s AND out_date > %(d)s
                """,
                {"lv": level, "d": trade_date},
            ).iloc[0]["n"]
            or 0
        )
        if uni_n
        else 0,
    }


def available_asof_dates(limit: int = 60) -> list[dt.date]:
    df = db.query_df(
        """
        SELECT DISTINCT trade_date
        FROM daily_bar
        ORDER BY trade_date DESC
        LIMIT %(n)s
        """,
        {"n": int(limit)},
    )
    if df is None or df.empty:
        return []
    return [_as_date(x) for x in df["trade_date"].tolist()]
