"""数据健康看板读数：水位、发布、日线漂移、extras 滞后。"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any

import pandas as pd

from qdata import db


@dataclass
class TableWatermark:
    name: str
    min_date: str = ""
    max_date: str = ""
    rows: int = 0
    days: int = 0
    ok: bool = True
    note: str = ""


def _to_date_str(v: Any) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    if isinstance(v, dt.date) and not isinstance(v, dt.datetime):
        return v.isoformat()
    try:
        return pd.Timestamp(v).date().isoformat()
    except Exception:
        return str(v)[:10]


def list_table_watermarks() -> list[TableWatermark]:
    """核心表水位一览。"""
    specs: list[tuple[str, str, str | None]] = [
        ("security_master", "SELECT count() AS n FROM security_master", None),
        (
            "daily_bar",
            """
            SELECT min(trade_date) AS mn, max(trade_date) AS mx,
                   count() AS n, uniqExact(trade_date) AS days
            FROM daily_bar
            """,
            "trade",
        ),
        (
            "daily_basic",
            """
            SELECT min(trade_date) AS mn, max(trade_date) AS mx,
                   count() AS n, uniqExact(trade_date) AS days
            FROM daily_basic
            """,
            "trade",
        ),
        (
            "suspend",
            """
            SELECT min(suspend_date) AS mn, max(suspend_date) AS mx,
                   count() AS n, uniqExact(suspend_date) AS days
            FROM suspend
            """,
            "trade",
        ),
        (
            "fin_statement",
            """
            SELECT min(ann_date) AS mn, max(ann_date) AS mx,
                   count() AS n, uniqExact(ann_date) AS days
            FROM fin_statement
            """,
            "ann",
        ),
        (
            "index_member",
            "SELECT count() AS n FROM index_member",
            None,
        ),
        (
            "industry_member",
            """
            SELECT count() AS n,
                   uniqExact(level) AS levels
            FROM industry_member
            """,
            None,
        ),
        (
            "factor_value",
            """
            SELECT min(trade_date) AS mn, max(trade_date) AS mx,
                   count() AS n, uniqExact(trade_date) AS days
            FROM factor_value
            """,
            "trade",
        ),
    ]
    out: list[TableWatermark] = []
    for name, sql, kind in specs:
        try:
            df = db.query_df(sql)
            if df is None or df.empty:
                out.append(TableWatermark(name=name, ok=False, note="empty"))
                continue
            r = df.iloc[0]
            rows = int(r.get("n") or 0)
            if kind is None:
                note = ""
                if name == "industry_member" and "levels" in r.index:
                    note = f"levels={int(r['levels'] or 0)}"
                out.append(
                    TableWatermark(
                        name=name,
                        rows=rows,
                        ok=rows > 0,
                        note=note or ("ok" if rows > 0 else "empty"),
                    )
                )
            else:
                out.append(
                    TableWatermark(
                        name=name,
                        min_date=_to_date_str(r.get("mn")),
                        max_date=_to_date_str(r.get("mx")),
                        rows=rows,
                        days=int(r.get("days") or 0),
                        ok=rows > 0,
                        note="ok" if rows > 0 else "empty",
                    )
                )
        except Exception as e:
            out.append(TableWatermark(name=name, ok=False, note=f"error: {e}"))
    return out


def daily_bar_series(limit_days: int = 30) -> pd.DataFrame:
    """最近 N 个交易日日线行数 + 相对昨日漂移。"""
    df = db.query_df(
        """
        SELECT trade_date, count() AS row_count
        FROM daily_bar
        GROUP BY trade_date
        ORDER BY trade_date DESC
        LIMIT %(n)s
        """,
        {"n": int(limit_days)},
    )
    if df is None or df.empty:
        return pd.DataFrame(
            columns=["trade_date", "row_count", "prev_count", "drift_pct"]
        )
    df = df.sort_values("trade_date").reset_index(drop=True)
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
    df["row_count"] = pd.to_numeric(df["row_count"], errors="coerce").fillna(0).astype(int)
    df["prev_count"] = df["row_count"].shift(1)
    df["drift_pct"] = (df["row_count"] - df["prev_count"]) / df["prev_count"].replace(0, pd.NA)
    return df


def recent_publications(dataset: str = "daily_bar", limit: int = 20) -> pd.DataFrame:
    df = db.query_df(
        """
        SELECT dataset, version, row_count, published, note
        FROM dataset_version
        WHERE dataset = %(ds)s
        ORDER BY version DESC
        LIMIT %(n)s
        """,
        {"ds": dataset, "n": int(limit)},
    )
    if df is None or df.empty:
        return pd.DataFrame(
            columns=["dataset", "version", "row_count", "published", "note"]
        )
    return df


def extras_lag_vs_daily_bar() -> pd.DataFrame:
    """extras / 因子水位相对 daily_bar.max 的滞后天数（日历日近似）。"""
    marks = {m.name: m for m in list_table_watermarks()}
    bar = marks.get("daily_bar")
    if bar is None or not bar.max_date:
        return pd.DataFrame(columns=["table", "max_date", "lag_days", "status"])

    bar_max = dt.date.fromisoformat(bar.max_date)
    rows = []
    for name in ("daily_basic", "suspend", "fin_statement", "factor_value"):
        m = marks.get(name)
        if m is None or not m.max_date:
            rows.append(
                {
                    "table": name,
                    "max_date": "",
                    "lag_days": None,
                    "status": "missing",
                }
            )
            continue
        mx = dt.date.fromisoformat(m.max_date)
        lag = (bar_max - mx).days
        if lag <= 0:
            status = "ok"
        elif lag <= 3:
            status = "lag"
        else:
            status = "stale"
        rows.append(
            {
                "table": name,
                "max_date": m.max_date,
                "lag_days": lag,
                "status": status,
            }
        )
    return pd.DataFrame(rows)


def health_summary() -> dict[str, Any]:
    """顶部 KPI。"""
    marks = list_table_watermarks()
    by = {m.name: m for m in marks}
    bar = by.get("daily_bar")
    pubs = recent_publications(limit=1)
    latest_pub = str(pubs.iloc[0]["version"]) if not pubs.empty else ""
    series = daily_bar_series(5)
    last_drift = None
    if not series.empty and pd.notna(series.iloc[-1].get("drift_pct")):
        last_drift = float(series.iloc[-1]["drift_pct"])
    lag = extras_lag_vs_daily_bar()
    stale_n = int((lag["status"] == "stale").sum()) if not lag.empty else 0
    return {
        "security_master": by.get("security_master").rows if by.get("security_master") else 0,
        "daily_bar_max": bar.max_date if bar else "",
        "daily_bar_days": bar.days if bar else 0,
        "daily_bar_rows": bar.rows if bar else 0,
        "latest_published": latest_pub,
        "last_drift_pct": last_drift,
        "extras_stale": stale_n,
        "watermarks": marks,
    }
