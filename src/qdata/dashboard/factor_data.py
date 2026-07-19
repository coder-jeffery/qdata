"""因子覆盖看板读数。"""

from __future__ import annotations

import datetime as dt
from typing import Any

import numpy as np
import pandas as pd

from qdata import db
from qdata.factors import list_seed_factors


def list_factor_watermarks() -> pd.DataFrame:
    df = db.query_df(
        """
        SELECT factor_name,
               min(trade_date) AS min_date,
               max(trade_date) AS max_date,
               count() AS rows,
               uniqExact(trade_date) AS days,
               uniqExact(security_id) AS securities
        FROM factor_value
        GROUP BY factor_name
        ORDER BY factor_name
        """
    )
    if df is None or df.empty:
        return pd.DataFrame(
            columns=[
                "factor_name",
                "min_date",
                "max_date",
                "rows",
                "days",
                "securities",
            ]
        )
    return df


def available_factor_names() -> list[str]:
    df = list_factor_watermarks()
    if df.empty:
        return list_seed_factors()
    return [str(x) for x in df["factor_name"].tolist()]


def available_factor_dates(factor: str | None = None, limit: int = 60) -> list[dt.date]:
    if factor:
        df = db.query_df(
            """
            SELECT DISTINCT trade_date
            FROM factor_value
            WHERE factor_name = %(f)s
            ORDER BY trade_date DESC
            LIMIT %(n)s
            """,
            {"f": factor, "n": int(limit)},
        )
    else:
        df = db.query_df(
            """
            SELECT DISTINCT trade_date
            FROM factor_value
            ORDER BY trade_date DESC
            LIMIT %(n)s
            """,
            {"n": int(limit)},
        )
    if df is None or df.empty:
        return []
    out: list[dt.date] = []
    for v in df["trade_date"].tolist():
        out.append(pd.Timestamp(v).date())
    return out


def universe_size(trade_date: dt.date) -> int:
    """当日日线覆盖（近似全市场 universe）。"""
    df = db.query_df(
        """
        SELECT count() AS n
        FROM daily_bar
        WHERE trade_date = %(d)s
        """,
        {"d": trade_date},
    )
    if df is None or df.empty:
        return 0
    return int(df.iloc[0]["n"] or 0)


def factor_coverage_day(factor: str, trade_date: dt.date) -> dict[str, Any]:
    """单日单因子覆盖 + 分位数。"""
    uni = universe_size(trade_date)
    df = db.query_df(
        """
        SELECT value
        FROM factor_value
        WHERE factor_name = %(f)s AND trade_date = %(d)s
          AND isFinite(value) AND NOT isNaN(value)
        """,
        {"f": factor, "d": trade_date},
    )
    if df is None or df.empty:
        return {
            "factor": factor,
            "trade_date": trade_date.isoformat(),
            "universe": uni,
            "n_valid": 0,
            "coverage": 0.0,
            "quantiles": {},
            "values": pd.Series(dtype=float),
        }
    s = pd.to_numeric(df["value"], errors="coerce").dropna()
    n = int(len(s))
    qs = [0.01, 0.05, 0.25, 0.5, 0.75, 0.95, 0.99]
    qmap = {f"p{int(q * 100)}": float(s.quantile(q)) for q in qs} if n else {}
    return {
        "factor": factor,
        "trade_date": trade_date.isoformat(),
        "universe": uni,
        "n_valid": n,
        "coverage": (n / uni) if uni > 0 else 0.0,
        "mean": float(s.mean()) if n else None,
        "std": float(s.std()) if n > 1 else None,
        "quantiles": qmap,
        "values": s,
    }


def factor_coverage_series(
    factor: str,
    *,
    limit_days: int = 30,
) -> pd.DataFrame:
    """因子按日覆盖率时间序列（相对当日 daily_bar 行数）。"""
    df = db.query_df(
        """
        SELECT
            f.trade_date AS trade_date,
            count() AS n_factor,
            countIf(isFinite(f.value) AND NOT isNaN(f.value)) AS n_valid
        FROM factor_value f
        WHERE f.factor_name = %(f)s
        GROUP BY f.trade_date
        ORDER BY f.trade_date DESC
        LIMIT %(n)s
        """,
        {"f": factor, "n": int(limit_days)},
    )
    if df is None or df.empty:
        return pd.DataFrame(
            columns=["trade_date", "n_valid", "universe", "coverage"]
        )
    bar = db.query_df(
        """
        SELECT trade_date, count() AS universe
        FROM daily_bar
        WHERE trade_date >= %(a)s AND trade_date <= %(b)s
        GROUP BY trade_date
        """,
        {
            "a": pd.Timestamp(df["trade_date"].min()).date().isoformat(),
            "b": pd.Timestamp(df["trade_date"].max()).date().isoformat(),
        },
    )
    if bar is None:
        bar = pd.DataFrame(columns=["trade_date", "universe"])
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
    if not bar.empty:
        bar["trade_date"] = pd.to_datetime(bar["trade_date"]).dt.date
    out = df.merge(bar, on="trade_date", how="left")
    out["universe"] = pd.to_numeric(out.get("universe"), errors="coerce").fillna(0).astype(int)
    out["n_valid"] = pd.to_numeric(out["n_valid"], errors="coerce").fillna(0).astype(int)
    out["coverage"] = np.where(
        out["universe"] > 0, out["n_valid"] / out["universe"], 0.0
    )
    return out.sort_values("trade_date").reset_index(drop=True)


def factor_matrix_latest(trade_date: dt.date | None = None) -> pd.DataFrame:
    """某日全部因子覆盖一览。"""
    if trade_date is None:
        dates = available_factor_dates(limit=1)
        if not dates:
            return pd.DataFrame()
        trade_date = dates[0]
    names = available_factor_names()
    rows = []
    uni = universe_size(trade_date)
    for fac in names:
        cov = factor_coverage_day(fac, trade_date)
        rows.append(
            {
                "trade_date": trade_date.isoformat(),
                "factor": fac,
                "n_valid": cov["n_valid"],
                "universe": uni,
                "coverage": cov["coverage"],
                "p50": cov["quantiles"].get("p50"),
                "mean": cov.get("mean"),
            }
        )
    return pd.DataFrame(rows)
