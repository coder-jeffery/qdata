"""M1.5 P0：生产主源固化 + 全市场回填 + 发布验收。

流程：
  1) apply_prod_mode（单一主源 + MAX_SYMBOLS=0）
  2) sync_calendar
  3) backfill 全市场（publish）
  4) validate_release：dataset_version 连续 + smoke 全绿

用法：
  # .env
  # QDATA_PROD_SOURCE=baostock
  # QDATA_AKSHARE_MAX_SYMBOLS=0
  # QDATA_PROD_MIN_UNIVERSE=500

  python -m qdata.jobs.prod_backfill --start 2026-04-01 --end 2026-07-15

  # 仅验收（数据已回填）
  python -m qdata.jobs.prod_backfill --start 2026-04-01 --end 2026-07-15 --validate-only

  # Tushare 生产主源
  python -m qdata.jobs.prod_backfill --start 2026-04-01 --end 2026-07-15 --source tushare
"""

from __future__ import annotations

import argparse
import datetime as dt
import logging
import sys

from qdata.jobs.backfill import backfill
from qdata.jobs.sync_calendar import sync_from_baostock, sync_from_tushare
from qdata.jobs.validate_release import validate_release
from qdata.calendar import upsert_calendar
from qdata.prod import apply_prod_mode, prod_min_universe, resolve_prod_source

logger = logging.getLogger(__name__)


def run_prod_backfill(
    start: dt.date,
    end: dt.date,
    *,
    source: str | None = None,
    skip_calendar: bool = False,
    skip_backfill: bool = False,
    validate_only: bool = False,
    skip_quality: bool = True,
    with_basic: bool = False,
    with_finance: bool = False,
    with_suspend: bool = True,
    min_universe: int | None = None,
    continue_on_error: bool = False,
    skip_published: bool = True,
    skip_validate: bool = False,
) -> int:
    """返回 0 表示回填+验收通过（``skip_validate`` 时仅看回填失败日）。"""
    if validate_only:
        skip_calendar = True
        skip_backfill = True

    prod_source = apply_prod_mode(source)
    print(f"PROD_SOURCE={prod_source}  FULL_MARKET=1  range={start}~{end}")
    print(f"skip_published={skip_published}  continue_on_error={continue_on_error}")

    if not skip_calendar:
        logger.info("同步交易日历 via %s", prod_source)
        if prod_source == "tushare":
            cal = sync_from_tushare(start, end)
        else:
            cal = sync_from_baostock(start, end)
        n = upsert_calendar(cal)
        open_n = int(cal["is_open"].sum()) if not cal.empty else 0
        print(f"trade_calendar upsert {n} rows (open≈{open_n})")

    backfill_rc = 0
    if not skip_backfill:
        logger.info("全市场回填开始 source=%s", prod_source)
        # 默认复用已完整的 Raw（中断后续跑，避免重拉 5000+ 只日线）
        reuse_n = prod_min_universe()
        summary = backfill(
            start,
            end,
            source=prod_source,
            skip_master=False,
            skip_quality=skip_quality,
            with_finance=with_finance,
            with_basic=with_basic,
            with_suspend=with_suspend,
            publish=True,
            continue_on_error=continue_on_error,
            reuse_min_rows=reuse_n,
            skip_published=skip_published,
            skip_published_min_rows=reuse_n,
        )
        skipped = summary.get("skipped") or []
        print(
            f"backfill summary: days={summary['days']} ok={len(summary['ok'])} "  # type: ignore[arg-type]
            f"skipped={len(skipped)} "  # type: ignore[arg-type]
            f"failed={len(summary['failed'])} published={len(summary['published'])}"  # type: ignore[arg-type]
        )
        if summary["failed"]:
            print("PROD_BACKFILL FAIL: 存在回填失败日")
            for item in summary["failed"][:10]:  # type: ignore[index]
                print(f"  - {item}")
            print(
                "提示: 网络超时可稍后原命令重跑（默认跳过已发布日）；"
                "或 --continue-on-error 先尽量多填几天。"
            )
            backfill_rc = 1
            if not continue_on_error:
                return 1

    if skip_validate or (not skip_backfill and backfill_rc != 0 and continue_on_error):
        # 分段续跑：有失败日时跳过整段验收，避免掩盖「已推进」事实
        if skip_validate:
            print("skip validate (caller requested)")
        elif backfill_rc != 0:
            print("skip validate: 本段仍有失败日，请修复后 --validate-only 或 dd1_depth --status")
        return backfill_rc

    # 验收：version 连续 + smoke 全绿
    rc = validate_release(
        start,
        end,
        prod=True,
        min_universe=min_universe,
        min_rows=1,
    )
    return rc if backfill_rc == 0 else backfill_rc


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser(
        description="M1.5 P0 生产主源全市场回填 + dataset_version/smoke 验收"
    )
    p.add_argument("--start", required=True, type=dt.date.fromisoformat)
    p.add_argument("--end", required=True, type=dt.date.fromisoformat)
    p.add_argument(
        "--source",
        default=None,
        help="覆盖 QDATA_PROD_SOURCE（baostock|tushare）",
    )
    p.add_argument("--skip-calendar", action="store_true")
    p.add_argument("--skip-backfill", action="store_true", help="只跑日历+验收")
    p.add_argument(
        "--validate-only",
        action="store_true",
        help="仅验收（不拉数）；等价于已回填后的门禁",
    )
    p.add_argument(
        "--run-quality",
        action="store_true",
        help="回填时跑质量 HARD（默认跳过，避免未补全规则误伤发布）",
    )
    p.add_argument("--with-basic", action="store_true")
    p.add_argument("--with-finance", action="store_true")
    p.add_argument(
        "--skip-suspend",
        action="store_true",
        help="不拉取停牌（DD1 日线纵深推荐，避免 BaoStock 超时卡死）",
    )
    p.add_argument(
        "--continue-on-error",
        action="store_true",
        help="单日失败继续（默认遇错即停，保证版本连续）",
    )
    p.add_argument(
        "--no-skip-published",
        action="store_true",
        help="不跳过已发布日（默认跳过，便于断点续跑）",
    )
    p.add_argument(
        "--min-universe",
        type=int,
        default=None,
        help="覆盖 QDATA_PROD_MIN_UNIVERSE",
    )
    args = p.parse_args(argv)
    if args.start > args.end:
        raise SystemExit("--start 不能大于 --end")

    # 预先解析，给出清晰错误
    resolve_prod_source(args.source)

    rc = run_prod_backfill(
        args.start,
        args.end,
        source=args.source,
        skip_calendar=args.skip_calendar,
        skip_backfill=args.skip_backfill,
        validate_only=args.validate_only,
        skip_quality=not args.run_quality,
        with_basic=args.with_basic,
        with_finance=args.with_finance,
        with_suspend=not args.skip_suspend,
        min_universe=args.min_universe,
        continue_on_error=args.continue_on_error,
        skip_published=not args.no_skip_published,
    )
    sys.exit(rc)


if __name__ == "__main__":
    main()
