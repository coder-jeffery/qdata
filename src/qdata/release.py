"""发布验收：dataset_version 连续性检查。"""

from __future__ import annotations

import datetime as dt
import logging

from qdata import calendar, db

logger = logging.getLogger(__name__)


def published_versions(
    start: dt.date,
    end: dt.date,
    dataset: str = "daily_bar",
) -> list[dt.date]:
    """区间内已发布的 version（按日解析）。"""
    df = db.query_df(
        """
        SELECT version, row_count
        FROM dataset_version
        WHERE dataset = %(ds)s
          AND version >= %(a)s AND version <= %(b)s
        ORDER BY version
        """,
        {"ds": dataset, "a": start.isoformat(), "b": end.isoformat()},
    )
    if df is None or df.empty:
        return []
    out: list[dt.date] = []
    for v in df["version"].astype(str).tolist():
        try:
            out.append(dt.date.fromisoformat(v))
        except ValueError:
            logger.warning("无法解析 version=%s，已忽略", v)
    return out


def check_version_continuity(
    start: dt.date,
    end: dt.date,
    dataset: str = "daily_bar",
    *,
    min_rows: int = 1,
) -> dict[str, object]:
    """校验 [start,end] 每个交易日均有 dataset_version，且 row_count>=min_rows。

    返回:
      ok, expected, published, missing, thin (有版本但行数不足)
    """
    expected = calendar.trading_days_between(start, end)
    if not expected:
        return {
            "ok": False,
            "expected": [],
            "published": [],
            "missing": [],
            "thin": [],
            "message": f"区间内无交易日: {start}~{end}（请先 sync_calendar）",
        }

    df = db.query_df(
        """
        SELECT version, max(row_count) AS row_count
        FROM dataset_version
        WHERE dataset = %(ds)s
          AND version >= %(a)s AND version <= %(b)s
        GROUP BY version
        ORDER BY version
        """,
        {"ds": dataset, "a": start.isoformat(), "b": end.isoformat()},
    )
    row_map: dict[dt.date, int] = {}
    if df is not None and not df.empty:
        for _, r in df.iterrows():
            try:
                d = dt.date.fromisoformat(str(r["version"]))
            except ValueError:
                continue
            row_map[d] = int(r["row_count"])

    missing = [d for d in expected if d not in row_map]
    thin = [d for d in expected if d in row_map and row_map[d] < min_rows]
    published = sorted(row_map)
    ok = not missing and not thin
    msg = (
        f"{dataset} versions: expected={len(expected)} published={len(published)} "
        f"missing={len(missing)} thin={len(thin)}"
    )
    return {
        "ok": ok,
        "expected": [d.isoformat() for d in expected],
        "published": [d.isoformat() for d in published],
        "missing": [d.isoformat() for d in missing],
        "thin": [d.isoformat() for d in thin],
        "message": msg,
    }
