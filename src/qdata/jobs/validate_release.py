"""M1.5 发布验收：dataset_version 连续 + smoke 全绿。

用法：
  python -m qdata.jobs.validate_release --start 2026-07-01 --end 2026-07-15
  python -m qdata.jobs.validate_release --start 2026-07-01 --end 2026-07-15 --prod
"""

from __future__ import annotations

import argparse
import datetime as dt
import logging
import sys

from qdata.jobs.smoke import run_smoke_range
from qdata.prod import prod_min_universe
from qdata.release import check_version_continuity

logger = logging.getLogger(__name__)


def validate_release(
    start: dt.date,
    end: dt.date,
    *,
    prod: bool = True,
    code: str = "600000.SH",
    min_universe: int | None = None,
    min_rows: int = 1,
) -> int:
    """返回 0 表示验收通过。"""
    print("=" * 60)
    print(f"VALIDATE RELEASE {start} ~ {end}  prod={prod}")
    print("=" * 60)

    cont = check_version_continuity(start, end, "daily_bar", min_rows=min_rows)
    print(cont["message"])
    if cont["missing"]:
        miss = cont["missing"]
        print(f"missing versions ({len(miss)}): {', '.join(miss[:15])}"
              + (" ..." if len(miss) > 15 else ""))
    if cont["thin"]:
        thin = cont["thin"]
        print(f"thin versions ({len(thin)}): {', '.join(thin[:15])}"
              + (" ..." if len(thin) > 15 else ""))

    if not cont["ok"]:
        print("\nACCEPTANCE FAIL: dataset_version 不连续")
        if not cont["published"]:
            print(
                "提示: 区间内尚未发布任何 daily_bar 版本。"
                "请先跑生产回填再验收，例如:\n"
                f"  .venv/bin/python -m qdata.jobs.prod_backfill "
                f"--start {start} --end {end}"
            )
        return 1
    print("dataset_version continuity: PASS")

    min_uni = min_universe
    if prod and min_uni is None:
        min_uni = prod_min_universe()

    rc = run_smoke_range(
        start,
        end,
        code=code,
        require_published=True,
        min_universe=min_uni if prod else (min_uni or 1),
    )
    if rc != 0:
        print("\nACCEPTANCE FAIL: smoke 未全绿")
        return 1

    print("\n" + "=" * 60)
    print("ACCEPTANCE PASS: dataset_version 连续 + smoke 全绿")
    print("=" * 60)
    return 0


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser(description="M1.5 发布验收（version 连续 + smoke）")
    p.add_argument("--start", required=True, type=dt.date.fromisoformat)
    p.add_argument("--end", required=True, type=dt.date.fromisoformat)
    p.add_argument("--code", default="600000.SH")
    p.add_argument(
        "--prod",
        action="store_true",
        default=True,
        help="生产标准（默认开启）：universe≥PROD_MIN_UNIVERSE",
    )
    p.add_argument("--no-prod", action="store_true", help="放宽 universe 下限")
    p.add_argument("--min-universe", type=int, default=None)
    p.add_argument("--min-rows", type=int, default=1, help="每日 published row_count 下限")
    args = p.parse_args(argv)
    if args.start > args.end:
        raise SystemExit("--start 不能大于 --end")
    prod = not args.no_prod
    sys.exit(
        validate_release(
            args.start,
            args.end,
            prod=prod,
            code=args.code,
            min_universe=args.min_universe,
            min_rows=args.min_rows,
        )
    )


if __name__ == "__main__":
    main()
