"""M1.5 P0：日批无人值守入口（无需 Airflow）。

流程：
  生产主源固化 →（可选）同步日历 → 当日全市场回填+质检+发布
  → smoke →（可选）extras 水位增量 →（可选）指数/行业/因子
  →（A405）软挂因子监控 → webhook

用法：
  python -m qdata.jobs.daily_run
  python -m qdata.jobs.daily_run --date 2026-07-15 --skip-quality
  python -m qdata.jobs.daily_run --post-m2 --with-basic --with-extras --sync-industry

  # cron 示例（工作日 17:30；--post-m2 默认软挂因子监控，失败不阻断发布）
  # 30 17 * * 1-5 cd /path/to/qdata && .venv/bin/python -m qdata.jobs.daily_run \\
  #   --post-m2 --with-basic --with-extras --sync-industry --industry-levels sw_l1,sw_l2 \\
  #   >>logs/daily_run.log 2>&1
"""

from __future__ import annotations

import argparse
import datetime as dt
import logging
import os
import sys
import traceback
from zoneinfo import ZoneInfo

from qdata import calendar
from qdata.calendar import upsert_calendar
from qdata.jobs.backfill import backfill
from qdata.jobs.smoke import run_smoke
from qdata.jobs.sync_calendar import sync_from_baostock, sync_from_tushare
from qdata.notify import notify
from qdata.prod import apply_prod_mode, prod_min_universe, resolve_prod_source

logger = logging.getLogger(__name__)

_SH_TZ = ZoneInfo("Asia/Shanghai")


def _today_shanghai() -> dt.date:
    return dt.datetime.now(_SH_TZ).date()


def _run_extras(
    *,
    extras_source: str | None,
    extras_only: set[str],
    end: dt.date,
    strict: bool,
) -> list[str]:
    """水位增量 extras；默认软失败。"""
    warnings: list[str] = []
    try:
        from qdata.jobs.sync_market_extras import run_incremental_extras

        summary = run_incremental_extras(
            source=extras_source,
            only=extras_only,
            end=end,
            continue_on_error=not strict,
        )
        if summary.get("skipped"):
            print(f"post-extras skipped: {summary.get('reason')}")
            return warnings
        failed = summary.get("failed") or []
        msg = (
            f"post-extras source={summary.get('source')} "
            f"basic={len(summary.get('basic_ok') or [])} "
            f"suspend={len(summary.get('suspend_ok') or [])} "
            f"finance={len(summary.get('finance_ok') or [])} "
            f"failed={len(failed)}"  # type: ignore[arg-type]
        )
        print(msg)
        if failed:
            warnings.append(msg)
            if strict:
                raise RuntimeError(msg)
    except Exception as e:
        msg = f"sync_market_extras: {e}"
        logger.warning(msg)
        warnings.append(msg)
        if strict:
            raise
    return warnings


def _run_post_m2(
    d: dt.date,
    *,
    sync_index: bool,
    sync_industry: bool,
    compute_factors: bool,
    industry_levels: tuple[str, ...] = ("sw_l1",),
    strict: bool = False,
) -> list[str]:
    """发布后研究层步骤。返回告警列表；strict 时抛错。"""
    warnings: list[str] = []

    if sync_index:
        try:
            from qdata.jobs.sync_index_member import sync_index_member

            n = sync_index_member(d, mode="snapshot")
            print(f"post-m2 sync_index_member: {n}")
        except Exception as e:
            msg = f"sync_index_member: {e}"
            logger.warning(msg)
            warnings.append(msg)
            if strict:
                raise

    if sync_industry:
        try:
            from qdata.jobs.sync_industry_member import sync_industry_member

            n = sync_industry_member(d, mode="snapshot", levels=industry_levels)
            print(f"post-m2 sync_industry_member: {n}")
        except Exception as e:
            msg = f"sync_industry_member: {e}"
            logger.warning(msg)
            warnings.append(msg)
            if strict:
                raise

    if compute_factors:
        try:
            from qdata.factors import compute_factors_for_day

            counts = compute_factors_for_day(d)
            print(f"post-m2 compute_factors: {counts}")
        except Exception as e:
            msg = f"compute_factors: {e}"
            logger.warning(msg)
            warnings.append(msg)
            if strict:
                raise

    return warnings


def _run_factor_monitor(
    d: dt.date,
    *,
    min_coverage: float = 0.9,
    strict: bool = False,
) -> list[str]:
    """A405：日批后软挂因子监控。告警/异常默认不阻断发布。"""
    warnings: list[str] = []
    try:
        from qdata.apps.factor_monitor import monitor_factor_day

        result = monitor_factor_day(
            d,
            min_coverage=min_coverage,
            persist=True,
            quintile=True,
            via="daily_run",
        )
        report = result.get("report") or {}
        n_alerts = int(report.get("n_alerts") or 0)
        path = result.get("path")
        print(
            f"post-m2 factor_monitor: n_alerts={n_alerts} "
            f"universe={report.get('universe_size', '—')} path={path}"
        )
        if n_alerts > 0:
            msgs = [a.get("message", str(a)) for a in (report.get("alerts") or [])]
            summary = f"factor_monitor {d}: {n_alerts} alerts; " + "; ".join(msgs[:6])
            if len(msgs) > 6:
                summary += f" …(+{len(msgs) - 6})"
            warnings.append(summary)
            # 软告警：单独 webhook，与 HARD FAIL 文案区分
            notify("qdata factor_monitor WARN", summary, ok=False)
    except Exception as e:
        msg = f"factor_monitor: {e}"
        logger.warning(msg)
        warnings.append(msg)
        notify("qdata factor_monitor WARN", msg, ok=False)

    if strict and warnings:
        raise RuntimeError(warnings[-1])
    return warnings


def run_daily(
    trade_date: dt.date | None = None,
    *,
    skip_quality: bool = False,
    skip_calendar: bool = False,
    skip_if_not_trading: bool = True,
    with_basic: bool = False,
    with_finance: bool = False,
    with_extras: bool = False,
    extras_source: str | None = None,
    extras_only: set[str] | None = None,
    post_m2: bool = False,
    sync_index: bool | None = None,
    sync_industry: bool = False,
    compute_factors: bool | None = None,
    monitor_factors: bool | None = None,
    monitor_min_coverage: float = 0.9,
    industry_levels: tuple[str, ...] = ("sw_l1",),
    strict_m2: bool = False,
) -> int:
    """返回 0 成功/跳过，非 0 失败。"""
    apply_prod_mode()
    d = trade_date or _today_shanghai()
    print(f"DAILY_RUN date={d}")

    do_index = post_m2 if sync_index is None else sync_index
    do_factors = post_m2 if compute_factors is None else compute_factors
    # A405：--post-m2 默认软挂监控；可用 --no-monitor-factors 关闭
    do_monitor = post_m2 if monitor_factors is None else monitor_factors
    only_extras = extras_only or {"basic", "suspend", "finance"}

    if skip_if_not_trading and not calendar.is_trading_day(d):
        msg = f"{d} 非交易日，跳过"
        print(msg)
        notify("qdata daily_run skip", msg, ok=True)
        return 0

    prod_source = resolve_prod_source()
    try:
        if not skip_calendar:
            start = d - dt.timedelta(days=40)
            end = d + dt.timedelta(days=5)
            if prod_source == "tushare":
                cal = sync_from_tushare(start, end)
            else:
                cal = sync_from_baostock(start, end)
            n = upsert_calendar(cal)
            calendar.clear_cache()
            print(f"trade_calendar upsert {n} rows")

        summary = backfill(
            d,
            d,
            source=prod_source,
            skip_master=False,
            skip_quality=skip_quality,
            with_basic=with_basic,
            with_finance=with_finance,
            publish=True,
            continue_on_error=False,
            reuse_min_rows=prod_min_universe(),
        )
        if summary["failed"]:
            raise RuntimeError(f"回填失败: {summary['failed']}")
        if not summary["published"]:
            raise RuntimeError(
                f"未发布 dataset_version（quality_failed={summary['quality_failed']}）"
            )

        rc = run_smoke(
            d,
            require_published=True,
            min_universe=prod_min_universe(),
            check_m2=True,
        )
        if rc != 0:
            raise RuntimeError("smoke 未通过")

        warn: list[str] = []
        if with_extras:
            # extras 水位拉到当日（与日批对齐）；源默认 JQ，不污染 prod 主源
            warn.extend(
                _run_extras(
                    extras_source=extras_source
                    or os.environ.get("QDATA_EXTRAS_SOURCE", "joinquant"),
                    extras_only=only_extras,
                    end=d,
                    strict=strict_m2,
                )
            )

        warn.extend(
            _run_post_m2(
                d,
                sync_index=do_index,
                sync_industry=sync_industry,
                compute_factors=do_factors,
                industry_levels=industry_levels,
                strict=strict_m2,
            )
        )

        if do_monitor:
            warn.extend(
                _run_factor_monitor(
                    d,
                    min_coverage=monitor_min_coverage,
                    strict=strict_m2,
                )
            )

        msg = (
            f"OK {d} source={prod_source} "
            f"published={summary['published']} master={summary['master_rows']}"
        )
        if warn:
            msg += f" warn={len(warn)}"
        print(msg)
        # 发布成功：即使有软监控告警仍发 OK（软告警已单独 notify）
        notify("qdata daily_run OK", msg, ok=True)
        return 0
    except Exception as e:
        err = f"FAIL {d}: {e}"
        logger.exception(err)
        traceback.print_exc()
        notify("qdata daily_run FAIL", err, ok=False)
        return 1


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser(description="M1.5 日批无人值守（cron/本地）")
    p.add_argument("--date", type=dt.date.fromisoformat, default=None)
    p.add_argument("--skip-quality", action="store_true")
    p.add_argument("--skip-calendar", action="store_true")
    p.add_argument(
        "--force",
        action="store_true",
        help="非交易日也强制跑（默认跳过）",
    )
    p.add_argument(
        "--with-basic",
        action="store_true",
        help="生产主源同时拉 daily_basic（turn_20 需要）",
    )
    p.add_argument(
        "--with-finance",
        action="store_true",
        help="生产主源同日拉 income/balancesheet/cashflow（需源支持）",
    )
    p.add_argument(
        "--with-extras",
        action="store_true",
        help="发布后跑 sync_market_extras 水位增量（默认 JoinQuant：basic/suspend/finance）",
    )
    p.add_argument(
        "--extras-source",
        default=None,
        help="extras 源，默认 $QDATA_EXTRAS_SOURCE 或 joinquant",
    )
    p.add_argument(
        "--extras-only",
        default="basic,suspend,finance",
        help="extras 子集，逗号分隔 basic,suspend,finance",
    )
    p.add_argument(
        "--post-m2",
        action="store_true",
        help="发布后跑指数 snapshot + 种子因子 + 软挂因子监控（行业需另加 --sync-industry）",
    )
    p.add_argument("--sync-index", action="store_true", help="强制同步指数成分")
    p.add_argument(
        "--no-sync-index",
        action="store_true",
        help="即使 --post-m2 也不同步指数",
    )
    p.add_argument(
        "--sync-industry",
        action="store_true",
        help="同步申万行业（默认仅 sw_l1，较慢）",
    )
    p.add_argument("--compute-factors", action="store_true", help="强制计算种子因子")
    p.add_argument(
        "--no-compute-factors",
        action="store_true",
        help="即使 --post-m2 也不算因子",
    )
    p.add_argument(
        "--monitor-factors",
        action="store_true",
        help="强制跑因子监控（A405）",
    )
    p.add_argument(
        "--no-monitor-factors",
        action="store_true",
        help="即使 --post-m2 也不跑因子监控",
    )
    p.add_argument(
        "--monitor-min-coverage",
        type=float,
        default=0.9,
        help="因子覆盖率告警阈值（默认 0.9）",
    )
    p.add_argument(
        "--industry-levels",
        default="sw_l1",
        help="行业 level 逗号分隔，默认 sw_l1",
    )
    p.add_argument(
        "--strict-m2",
        action="store_true",
        help="M2/extras/监控后置步骤失败则日批失败（默认仅告警）",
    )
    args = p.parse_args(argv)

    sync_index: bool | None = None
    if args.sync_index:
        sync_index = True
    elif args.no_sync_index:
        sync_index = False

    compute_factors: bool | None = None
    if args.compute_factors:
        compute_factors = True
    elif args.no_compute_factors:
        compute_factors = False

    monitor_factors: bool | None = None
    if args.monitor_factors:
        monitor_factors = True
    elif args.no_monitor_factors:
        monitor_factors = False

    levels = tuple(x.strip() for x in args.industry_levels.split(",") if x.strip())
    extras_only = {x.strip() for x in args.extras_only.split(",") if x.strip()}
    unknown = extras_only - {"basic", "suspend", "finance"}
    if unknown:
        raise SystemExit(f"--extras-only 未知项: {unknown}")

    sys.exit(
        run_daily(
            args.date,
            skip_quality=args.skip_quality,
            skip_calendar=args.skip_calendar,
            skip_if_not_trading=not args.force,
            with_basic=args.with_basic,
            with_finance=args.with_finance,
            with_extras=args.with_extras,
            extras_source=args.extras_source,
            extras_only=extras_only or {"basic", "suspend", "finance"},
            post_m2=args.post_m2,
            sync_index=sync_index,
            sync_industry=args.sync_industry,
            compute_factors=compute_factors,
            monitor_factors=monitor_factors,
            monitor_min_coverage=args.monitor_min_coverage,
            industry_levels=levels or ("sw_l1",),
            strict_m2=args.strict_m2,
        )
    )


if __name__ == "__main__":
    main()
