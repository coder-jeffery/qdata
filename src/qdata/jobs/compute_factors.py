"""计算种子因子并写入 factor_value。

用法：
  python -m qdata.jobs.compute_factors --date 2026-07-15
  python -m qdata.jobs.compute_factors --start 2026-07-01 --end 2026-07-15
  python -m qdata.jobs.compute_factors --date 2026-07-15 --factors mom_20,vol_20 --version v1
"""

from __future__ import annotations

import argparse
import datetime as dt
import logging
import sys

from qdata.factors import (
    DEFAULT_FACTOR_VERSION,
    compute_factors_for_day,
    compute_factors_range,
    list_seed_factors,
)

logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser(description="计算种子因子 → factor_value")
    p.add_argument("--date", type=dt.date.fromisoformat, default=None)
    p.add_argument("--start", type=dt.date.fromisoformat, default=None)
    p.add_argument("--end", type=dt.date.fromisoformat, default=None)
    p.add_argument(
        "--factors",
        default=None,
        help=f"逗号分隔，默认全部: {','.join(list_seed_factors())}",
    )
    p.add_argument("--version", default=DEFAULT_FACTOR_VERSION)
    p.add_argument("--list", action="store_true", help="列出种子因子并退出")
    args = p.parse_args(argv)

    if args.list:
        for n in list_seed_factors():
            print(n)
        return

    factors = None
    if args.factors:
        factors = [x.strip() for x in args.factors.split(",") if x.strip()]

    try:
        if args.date:
            counts = compute_factors_for_day(
                args.date, factors=factors, version=args.version
            )
            print(f"compute_factors {args.date} version={args.version}: {counts}")
        elif args.start and args.end:
            if args.start > args.end:
                raise SystemExit("--start 不能大于 --end")
            summary = compute_factors_range(
                args.start, args.end, factors=factors, version=args.version
            )
            for d, c in summary.items():
                print(f"  {d}: {c}")
            print(f"compute_factors range done days={len(summary)} version={args.version}")
        else:
            p.error("请指定 --date 或 --start/--end（或 --list）")
    except Exception as e:
        logger.exception("%s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
