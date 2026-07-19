"""A306 CLI：Paper session 日终盯市。

用法：
  python -m qdata.jobs.paper_mark --session <session_id>
  python -m qdata.jobs.paper_mark --session <session_id> --date 2026-07-15
  python -m qdata.jobs.paper_mark --latest
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import sys

from qdata.apps.paper_flow import mark_session_eod
from qdata.apps.paper_store import list_sessions

logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser(description="Paper session 日终盯市 → marks.parquet")
    p.add_argument("--session", default=None, help="session_id")
    p.add_argument("--latest", action="store_true", help="盯市最近一个 session")
    p.add_argument("--date", type=dt.date.fromisoformat, default=None, help="盯市日（默认 asof）")
    p.add_argument("--no-persist", action="store_true")
    args = p.parse_args(argv)

    sid = args.session
    if args.latest or not sid:
        sessions = list_sessions(limit=1)
        if not sessions:
            raise SystemExit("无 paper_sessions，请先 paper_rebalance")
        sid = sessions[0].get("session_id")
        if not sid:
            raise SystemExit("无法解析 session_id")
        if args.latest:
            print(f"使用最新 session={sid}")

    if not sid:
        raise SystemExit("需 --session 或 --latest")

    print(f"PAPER_MARK session={sid} date={args.date or 'default'}")
    try:
        mark = mark_session_eod(sid, mark_date=args.date, persist=not args.no_persist)
    except Exception as e:
        logger.exception("%s", e)
        sys.exit(1)

    summary = {k: v for k, v in mark.items() if k != "positions"}
    print(json.dumps(summary, indent=2, ensure_ascii=False, default=str))
    sys.exit(0)


if __name__ == "__main__":
    main()
