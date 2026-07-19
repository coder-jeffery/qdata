"""实时行情总线：与日线 ETL 分通道落盘。

目录：
  <lake_root>/realtime/<source>/realtime_quote/dt=<日>/ts=<HHMMSS>/data.parquet

不写 ClickHouse 日线表；策略/纸交易通过 bus 读最新快照。
"""

from __future__ import annotations

import datetime as dt
import logging
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from qdata.config import settings

logger = logging.getLogger(__name__)
_SH = ZoneInfo("Asia/Shanghai")

_QUOTE_COLS = [
    "exchange_code", "name", "price", "open", "high", "low", "pre_close",
    "volume", "amount", "bid", "ask", "time", "snapshot_ts",
]


def realtime_root() -> Path:
    return settings().lake_root / "realtime"


def _snap_dir(source: str, day: dt.date, ts: dt.datetime) -> Path:
    return (
        realtime_root()
        / source
        / "realtime_quote"
        / f"dt={day.isoformat()}"
        / f"ts={ts.strftime('%H%M%S')}"
    )


def write_snapshot(
    source: str,
    df: pd.DataFrame,
    *,
    asof: dt.datetime | None = None,
) -> Path:
    """写入一次实时快照，返回 parquet 路径。"""
    asof = asof or dt.datetime.now(_SH)
    day = asof.date()
    out = df.copy() if df is not None else pd.DataFrame(columns=_QUOTE_COLS)
    if "snapshot_ts" not in out.columns:
        out["snapshot_ts"] = asof.isoformat(timespec="seconds")
    # 对齐列
    for c in _QUOTE_COLS:
        if c not in out.columns:
            out[c] = None
    out = out[_QUOTE_COLS]

    pdir = _snap_dir(source, day, asof)
    pdir.mkdir(parents=True, exist_ok=True)
    path = pdir / "data.parquet"
    out.to_parquet(path, index=False)
    logger.info("realtime snapshot %s %s rows=%s -> %s", source, day, len(out), path)
    return path


def list_snapshots(source: str, day: dt.date | None = None) -> list[Path]:
    day = day or dt.datetime.now(_SH).date()
    root = realtime_root() / source / "realtime_quote" / f"dt={day.isoformat()}"
    if not root.exists():
        return []
    return sorted(root.glob("ts=*/data.parquet"))


def read_latest_snapshot(
    source: str,
    day: dt.date | None = None,
) -> pd.DataFrame:
    paths = list_snapshots(source, day)
    if not paths:
        return pd.DataFrame(columns=_QUOTE_COLS)
    return pd.read_parquet(paths[-1])


def fetch_and_store(
    *,
    source: str = "easyquotation",
    codes: list[str] | None = None,
) -> tuple[pd.DataFrame, Path]:
    """从行情源拉 realtime_quote 并写入 realtime 通道。"""
    from qdata.fetchers.factory import get_fetcher

    fetcher = get_fetcher(source)
    today = dt.datetime.now(_SH).date()
    df = fetcher.fetch("realtime_quote", today)
    if codes:
        want = {c.strip().upper() for c in codes if c.strip()}
        if not df.empty and "exchange_code" in df.columns:
            df = df[df["exchange_code"].astype(str).str.upper().isin(want)].copy()
    path = write_snapshot(source, df)
    return df, path
