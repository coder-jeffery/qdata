"""A4 CLI：因子日覆盖监控。

用法：
  python -m qdata.jobs.monitor_factors --date 2026-07-15
  python -m qdata.jobs.monitor_factors --start 2026-07-01 --end 2026-07-15
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import sys

from qdata.apps.factor_monitor import monitor_factor_day, monitor_factor_range

logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser(description="因子覆盖监控 → Lake factor_monitor/")
    p.add_argument("--date", type=dt.date.fromisoformat, default=None)
    p.add_argument("--start", type=dt.date.fromisoformat, default=None)
    p.add_argument("--end", type=dt.date.fromisoformat, default=None)
    p.add_argument("--factors", default=None, help="逗号分隔；默认六种子因子")
    p.add_argument("--min-coverage", type=float, default=0.9)
    p.add_argument("--no-persist", action="store_true")
    p.add_argument("--no-quintile", action="store_true")
    args = p.parse_args(argv)

    factors = [x.strip() for x in args.factors.split(",") if x.strip()] if args.factors else None

    if args.date is not None:
        print(f"MONITOR_FACTORS date={args.date}")
        try:
            result = monitor_factor_day(
                args.date,
                factors=factors,
                min_coverage=args.min_coverage,
                persist=not args.no_persist,
                quintile=not args.no_quintile,
            )
        except Exception as e:
            logger.exception("%s", e)
            sys.exit(1)
        print(json.dumps(result["report"], indent=2, ensure_ascii=False, default=str))
        if result.get("path"):
            print(f"path={result['path']}")
        sys.exit(0 if result["report"].get("n_alerts", 0) == 0 else 2)

    if args.start is None or args.end is None:
        raise SystemExit("需 --date 或 (--start + --end)")

    print(f"MONITOR_FACTORS {args.start}~{args.end}")
    try:
        results = monitor_factor_range(
            args.start,
            args.end,
            factors=factors,
            min_coverage=args.min_coverage,
        )
    except Exception as e:
        logger.exception("%s", e)
        sys.exit(1)

    total_alerts = sum(r["report"].get("n_alerts", 0) for r in results)
    print(f"days={len(results)} total_alerts={total_alerts}")
    sys.exit(0 if total_alerts == 0 else 2)


if __name__ == "__main__":
    main()
