"""财务 PIT 质量看板读数。"""

from __future__ import annotations

import datetime as dt
from typing import Any

import pandas as pd

from qdata import db


def finance_summary() -> dict[str, Any]:
    df = db.query_df(
        """
        SELECT
            count() AS rows,
            uniqExact(security_id) AS securities,
            uniqExact(ann_date) AS ann_days,
            min(ann_date) AS min_ann,
            max(ann_date) AS max_ann,
            min(report_date) AS min_report,
            max(report_date) AS max_report,
            countIf(ann_date < report_date) AS bad_ann_lt_report,
            countIf(stmt_type = 'income') AS n_income,
            countIf(stmt_type = 'balance') AS n_balance,
            countIf(stmt_type = 'cashflow') AS n_cashflow
        FROM fin_statement
        """
    )
    if df is None or df.empty:
        return {"rows": 0}
    r = df.iloc[0]
    bar = db.query_df("SELECT max(trade_date) AS mx FROM daily_bar")
    bar_max = None
    if bar is not None and not bar.empty and pd.notna(bar.iloc[0]["mx"]):
        bar_max = pd.Timestamp(bar.iloc[0]["mx"]).date()
    def _d(v) -> str:
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return ""
        try:
            return pd.Timestamp(v).date().isoformat()
        except Exception:
            return str(v)[:10]

    max_ann = (
        pd.Timestamp(r["max_ann"]).date() if pd.notna(r.get("max_ann")) else None
    )
    lag = (bar_max - max_ann).days if bar_max and max_ann else None
    return {
        "rows": int(r["rows"] or 0),
        "securities": int(r["securities"] or 0),
        "ann_days": int(r["ann_days"] or 0),
        "min_ann": _d(r.get("min_ann")),
        "max_ann": max_ann.isoformat() if max_ann else "",
        "min_report": _d(r.get("min_report")),
        "max_report": _d(r.get("max_report")),
        "bad_ann_lt_report": int(r["bad_ann_lt_report"] or 0),
        "n_income": int(r["n_income"] or 0),
        "n_balance": int(r["n_balance"] or 0),
        "n_cashflow": int(r["n_cashflow"] or 0),
        "daily_bar_max": bar_max.isoformat() if bar_max else "",
        "lag_days": lag,
    }


def ann_monthly_counts(limit_months: int = 24) -> pd.DataFrame:
    df = db.query_df(
        """
        SELECT toStartOfMonth(ann_date) AS month, count() AS rows,
               uniqExact(security_id) AS securities
        FROM fin_statement
        GROUP BY month
        ORDER BY month DESC
        LIMIT %(n)s
        """,
        {"n": int(limit_months)},
    )
    if df is None or df.empty:
        return pd.DataFrame(columns=["month", "rows", "securities"])
    out = df.copy()
    out["month"] = pd.to_datetime(out["month"]).dt.date
    return out.sort_values("month").reset_index(drop=True)


def pit_field_coverage(
    asof: dt.date,
    fields: tuple[str, ...] = ("net_profit", "equity", "revenue"),
    sample_limit: int = 5000,
) -> pd.DataFrame:
    """抽样证券在 asof 的 PIT 科目覆盖（mapContains）。"""
    uni = db.query_df(
        """
        SELECT security_id
        FROM daily_bar
        WHERE trade_date = %(d)s
        LIMIT %(n)s
        """,
        {"d": asof, "n": int(sample_limit)},
    )
    if uni is None or uni.empty:
        return pd.DataFrame(columns=["field", "n_hit", "sample", "coverage"])
    sample_n = len(uni)
    rows = []
    for field in fields:
        hit = db.query_df(
            """
            SELECT uniqExact(f.security_id) AS n
            FROM fin_statement f
            INNER JOIN
            (
                SELECT security_id
                FROM daily_bar
                WHERE trade_date = %(d)s
                LIMIT %(n)s
            ) u USING (security_id)
            WHERE f.ann_date <= %(d)s
              AND mapContains(f.fields, %(f)s)
            """,
            {"d": asof, "n": int(sample_limit), "f": field},
        )
        n = int(hit.iloc[0]["n"] or 0) if hit is not None and not hit.empty else 0
        rows.append(
            {
                "field": field,
                "n_hit": n,
                "sample": sample_n,
                "coverage": n / sample_n if sample_n else 0.0,
            }
        )
    return pd.DataFrame(rows)


def lag_vs_daily_bar() -> dict[str, Any]:
    s = finance_summary()
    return {
        "fin_max_ann": s.get("max_ann", ""),
        "daily_bar_max": s.get("daily_bar_max", ""),
        "lag_days": s.get("lag_days"),
        "status": (
            "ok"
            if s.get("lag_days") is not None and s["lag_days"] <= 7
            else ("lag" if s.get("lag_days") is not None and s["lag_days"] <= 30 else "stale")
        ),
    }
