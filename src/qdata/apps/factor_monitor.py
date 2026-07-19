"""A4 因子监控：日覆盖 + 简易分层前瞻收益 + 告警。"""

from __future__ import annotations

import datetime as dt
import json
import logging
from pathlib import Path
from typing import Any

import pandas as pd

from qdata import calendar
from qdata.config import settings
from qdata.factors import list_seed_factors

logger = logging.getLogger(__name__)


def _monitor_root() -> Path:
    return settings().lake_root / "factor_monitor"


def _universe_size(trade_date: dt.date) -> int:
    try:
        from qdata import db

        df = db.query_df(
            """
            SELECT count() AS n
            FROM daily_bar
            WHERE trade_date = %(d)s AND is_suspended = 0
            """,
            {"d": trade_date},
        )
        if df is not None and not df.empty:
            return int(df.iloc[0]["n"])
    except Exception as e:
        logger.warning("universe size 查询失败: %s", e)
    return 0


def _factor_coverage(trade_date: dt.date, factors: list[str]) -> pd.DataFrame:
    try:
        from qdata import db

        df = db.query_df(
            """
            SELECT factor_name,
                   count() AS n_rows,
                   uniqExact(security_id) AS n_securities
            FROM factor_value
            WHERE trade_date = %(d)s AND factor_name IN %(factors)s
            GROUP BY factor_name
            """,
            {"d": trade_date, "factors": tuple(factors)},
        )
    except Exception as e:
        logger.warning("factor coverage 查询失败: %s", e)
        return pd.DataFrame(columns=["factor_name", "n_rows", "n_securities", "coverage"])

    uni_n = _universe_size(trade_date)
    if df is None or df.empty:
        out = pd.DataFrame({"factor_name": factors, "n_rows": 0, "n_securities": 0})
    else:
        out = df.copy()
        missing = set(factors) - set(out["factor_name"].astype(str))
        if missing:
            out = pd.concat(
                [
                    out,
                    pd.DataFrame(
                        {"factor_name": list(missing), "n_rows": 0, "n_securities": 0}
                    ),
                ],
                ignore_index=True,
            )
    out["universe_size"] = uni_n
    out["coverage"] = out["n_securities"] / uni_n if uni_n > 0 else 0.0
    return out.sort_values("factor_name").reset_index(drop=True)


def _quintile_fwd_return(
    trade_date: dt.date,
    factor: str,
    *,
    factor_version: str = "v1",
) -> dict[str, Any] | None:
    """因子 T 日 vs T+1 close-to-close 分层收益（防前视：因子仅 T，收益 T→T+1）。"""
    try:
        from qdata import db

        future = calendar.trading_days_between(
            trade_date + dt.timedelta(days=1),
            trade_date + dt.timedelta(days=31),
        )
        if not future:
            return None
        nxt = future[0]

        fac = db.query_df(
            """
            SELECT m.exchange_code, f.value AS factor_value
            FROM factor_value f
            INNER JOIN security_master m USING (security_id)
            WHERE f.trade_date = %(d)s AND f.factor_name = %(fn)s AND f.version = %(v)s
            """,
            {"d": trade_date, "fn": factor, "v": factor_version},
        )
        px0 = db.query_df(
            """
            SELECT m.exchange_code, b.close AS c0
            FROM daily_bar b
            INNER JOIN security_master m USING (security_id)
            WHERE b.trade_date = %(d)s
            """,
            {"d": trade_date},
        )
        px1 = db.query_df(
            """
            SELECT m.exchange_code, b.close AS c1
            FROM daily_bar b
            INNER JOIN security_master m USING (security_id)
            WHERE b.trade_date = %(d)s
            """,
            {"d": nxt},
        )
    except Exception as e:
        logger.warning("quintile fwd return 失败 factor=%s: %s", factor, e)
        return None

    if fac is None or fac.empty or px0 is None or px0.empty or px1 is None or px1.empty:
        return None

    m = fac.merge(px0, on="exchange_code").merge(px1, on="exchange_code")
    m = m.dropna(subset=["factor_value", "c0", "c1"])
    m = m[(m["c0"] > 0) & (m["c1"] > 0)]
    if len(m) < 50:
        return None

    m["fwd_ret"] = m["c1"] / m["c0"] - 1.0
    try:
        m["quintile"] = pd.qcut(m["factor_value"].rank(method="first"), 5, labels=["Q1", "Q2", "Q3", "Q4", "Q5"])
    except ValueError:
        return None

    grp = m.groupby("quintile", observed=True)["fwd_ret"].mean()
    return {
        "factor": factor,
        "trade_date": trade_date.isoformat(),
        "fwd_date": nxt.isoformat(),
        "n_names": len(m),
        "quintile_returns": {str(k): float(v) for k, v in grp.items()},
        "spread_q5_q1": float(grp.get("Q5", 0) - grp.get("Q1", 0)),
    }


def monitor_factor_day(
    date: dt.date,
    factors: list[str] | None = None,
    min_coverage: float = 0.9,
    *,
    persist: bool = True,
    quintile: bool = True,
    via: str = "cli",
) -> dict[str, Any]:
    """日覆盖监控 + 可选分层前瞻收益 + 告警。"""
    facs = factors or list_seed_factors()
    coverage = _factor_coverage(date, facs)

    alerts: list[dict[str, Any]] = []
    for _, row in coverage.iterrows():
        cov = float(row.get("coverage") or 0)
        fn = str(row["factor_name"])
        if cov < min_coverage:
            alerts.append(
                {
                    "level": "warn",
                    "factor": fn,
                    "coverage": cov,
                    "message": f"{fn} 覆盖率 {cov:.1%} 低于阈值 {min_coverage:.0%}",
                }
            )
        if int(row.get("n_securities") or 0) == 0:
            alerts.append(
                {
                    "level": "error",
                    "factor": fn,
                    "coverage": 0.0,
                    "message": f"{fn} 在 {date} 无因子值",
                }
            )

    quintiles: dict[str, Any] = {}
    if quintile:
        for fn in facs:
            q = _quintile_fwd_return(date, fn)
            if q:
                quintiles[fn] = q

    report: dict[str, Any] = {
        "trade_date": date.isoformat(),
        "min_coverage": min_coverage,
        "universe_size": int(coverage["universe_size"].iloc[0]) if not coverage.empty else 0,
        "n_alerts": len(alerts),
        "alerts": alerts,
        "quintiles": quintiles,
        "via": via,
    }

    out_dir = _monitor_root() / date.isoformat()
    if persist:
        out_dir.mkdir(parents=True, exist_ok=True)
        coverage.to_parquet(out_dir / "coverage.parquet", index=False)
        (out_dir / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )

    return {
        "date": date,
        "coverage": coverage,
        "report": report,
        "path": str(out_dir) if persist else None,
    }


def monitor_factor_range(
    start: dt.date,
    end: dt.date,
    factors: list[str] | None = None,
    min_coverage: float = 0.9,
) -> list[dict[str, Any]]:
    """区间逐日监控。"""
    results: list[dict[str, Any]] = []
    for d in calendar.trading_days_between(start, end):
        results.append(monitor_factor_day(d, factors=factors, min_coverage=min_coverage))
    return results


def load_monitor_report(date: dt.date) -> dict[str, Any]:
    """读取已落盘监控报告。"""
    p = _monitor_root() / date.isoformat() / "report.json"
    if not p.is_file():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def load_monitor_coverage(date: dt.date) -> pd.DataFrame:
    p = _monitor_root() / date.isoformat() / "coverage.parquet"
    if not p.is_file():
        return pd.DataFrame()
    return pd.read_parquet(p)
