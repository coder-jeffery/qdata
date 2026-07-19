"""列出已归档回测 run（ClickHouse / Lake）。

用法：
  python -m qdata.jobs.list_backtests
  python -m qdata.jobs.list_backtests --limit 20 --factor mom_20
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from qdata.config import settings


def _from_ch(limit: int, factor: str | None) -> None:
    from qdata import db
    from qdata.research.backtest.store import ensure_backtest_tables

    ensure_backtest_tables()
    where = "WHERE 1"
    params: dict = {"n": limit}
    if factor:
        where += " AND factor = %(f)s"
        params["f"] = factor
    df = db.query_df(
        f"""
        SELECT run_id, created_at, factor, universe, execution,
               benchmark_mode, run_name, dataset_version
        FROM backtest_run
        {where}
        ORDER BY created_at DESC
        LIMIT %(n)s
        """,
        params,
    )
    if df is None or df.empty:
        print("CH: (empty)")
        return
    print(df.to_string(index=False))


def _from_lake(limit: int) -> None:
    root = settings().lake_root / "backtest" / "runs"
    if not root.exists():
        print("Lake: (no runs dir)")
        return
    runs = sorted(root.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
    n = 0
    for d in runs:
        meta_p = d / "meta.json"
        if not meta_p.exists():
            continue
        meta = json.loads(meta_p.read_text(encoding="utf-8"))
        print(
            f"{meta.get('run_id')}  factor={meta.get('factor')}  "
            f"universe={meta.get('universe')}  "
            f"bench={meta.get('benchmark_mode')}  name={meta.get('run_name')}"
        )
        n += 1
        if n >= limit:
            break
    if n == 0:
        print("Lake: (empty)")


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="列出回测 run")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--factor", default=None)
    p.add_argument("--lake-only", action="store_true")
    args = p.parse_args(argv)
    if args.lake_only:
        _from_lake(args.limit)
        return
    try:
        _from_ch(args.limit, args.factor)
    except Exception as e:
        print(f"CH 不可用，回退 Lake: {e}", file=sys.stderr)
        _from_lake(args.limit)


if __name__ == "__main__":
    main()
