"""单票研究台读数（DataAPI + CH）。"""

from __future__ import annotations

import datetime as dt
from typing import Any

import pandas as pd

from qdata import db
from qdata.api.data_api import DataAPI
from qdata.factors import list_seed_factors


def load_price(
    code: str,
    start: dt.date,
    end: dt.date,
    *,
    adjust: str = "post",
) -> pd.DataFrame:
    api = DataAPI(allow_unpublished=True)
    return api.get_price([code], start, end, adjust=adjust)  # type: ignore[arg-type]


def load_factor_series(
    code: str,
    factor: str,
    start: dt.date,
    end: dt.date,
) -> pd.DataFrame:
    api = DataAPI(allow_unpublished=True)
    df = api.load_factor(factor, start, end, with_code=True)
    if df is None or df.empty:
        return pd.DataFrame(columns=["trade_date", "value"])
    out = df[df["exchange_code"].astype(str) == code.upper()].copy()
    if out.empty:
        return pd.DataFrame(columns=["trade_date", "value"])
    return out[["trade_date", "value"]].sort_values("trade_date")


def load_industry(code: str, asof: dt.date) -> dict[str, str]:
    api = DataAPI(allow_unpublished=True)
    out: dict[str, str] = {}
    for lv in ("sw_l1", "sw_l2"):
        s = api.get_industry([code], asof, level=lv)  # type: ignore[arg-type]
        out[lv] = str(s.get(code.upper(), "")) if not s.empty else ""
    return out


def load_fundamentals(
    code: str,
    asof: dt.date,
    fields: tuple[str, ...] = ("net_profit", "equity", "revenue"),
) -> dict[str, Any]:
    api = DataAPI(allow_unpublished=True)
    out: dict[str, Any] = {}
    for f in fields:
        try:
            s = api.get_fundamental(f, [code], asof)
            out[f] = float(s[code.upper()]) if not s.empty and code.upper() in s.index else None
        except Exception:
            out[f] = None
    return out


def latest_basic(code: str, asof: dt.date | None = None) -> dict[str, Any]:
    """最近 daily_basic 一行。"""
    params: dict[str, Any] = {"c": code.upper()}
    where = "m.exchange_code = %(c)s"
    if asof is not None:
        where += " AND b.trade_date <= %(d)s"
        params["d"] = asof
    df = db.query_df(
        f"""
        SELECT b.trade_date, b.pe_ttm, b.pb, b.total_mv, b.circ_mv, b.turnover_rate
        FROM daily_basic b
        INNER JOIN security_master m USING (security_id)
        WHERE {where}
        ORDER BY b.trade_date DESC
        LIMIT 1
        """,
        params,
    )
    if df is None or df.empty:
        return {}
    return df.iloc[0].to_dict()


def default_range() -> tuple[dt.date, dt.date]:
    df = db.query_df("SELECT min(trade_date) AS mn, max(trade_date) AS mx FROM daily_bar")
    if df is None or df.empty or pd.isna(df.iloc[0]["mx"]):
        today = dt.date.today()
        return today - dt.timedelta(days=60), today
    mx = pd.Timestamp(df.iloc[0]["mx"]).date()
    mn = pd.Timestamp(df.iloc[0]["mn"]).date()
    start = max(mn, mx - dt.timedelta(days=90))
    return start, mx


def seed_factors() -> list[str]:
    return list_seed_factors()
