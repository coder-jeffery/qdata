"""多渠道同步 daily_basic / suspend / fin_statement。

保留 Tushare；推荐 JoinQuant 做历史全量 + 按日增量（公告日）。

用法：
  # JoinQuant 全量（日历日扫财务；交易日扫 basic/suspend）
  python -m qdata.jobs.sync_market_extras \\
      --source joinquant --start 2024-01-01 --end 2026-07-15 --mode full

  # JoinQuant 增量（从库内最大日期次日 → end，默认昨天）
  python -m qdata.jobs.sync_market_extras --source joinquant --mode incremental

  # Tushare（需 QDATA_TUSHARE_ENABLED + token）
  python -m qdata.jobs.sync_market_extras \\
      --source tushare --start 2026-07-01 --end 2026-07-15 --mode full

  # 故障转移链（空表合法数据集不误切源）
  python -m qdata.jobs.sync_market_extras \\
      --source joinquant,tushare --mode incremental

  # 只拉其中一类
  python -m qdata.jobs.sync_market_extras --source joinquant --mode full \\
      --start 2026-06-01 --end 2026-07-15 --only basic,suspend
"""

from __future__ import annotations

import argparse
import datetime as dt
import logging
import os
import sys
import traceback
from zoneinfo import ZoneInfo

from qdata import calendar, db
from qdata.config import settings
from qdata.fetchers.cli import fetch_datasets
from qdata.loaders.daily_basic import DailyBasicLoader
from qdata.loaders.fin_statement import FinStatementLoader
from qdata.loaders.suspend import SuspendLoader
from qdata.publish import publish_day

logger = logging.getLogger(__name__)
_SH = ZoneInfo("Asia/Shanghai")


def _yesterday() -> dt.date:
    return dt.datetime.now(_SH).date() - dt.timedelta(days=1)


def _calendar_days(start: dt.date, end: dt.date) -> list[dt.date]:
    out: list[dt.date] = []
    d = start
    while d <= end:
        out.append(d)
        d += dt.timedelta(days=1)
    return out


def _max_date(sql: str) -> dt.date | None:
    try:
        df = db.query_df(sql)
        if df is None or df.empty or df.iloc[0, 0] is None:
            return None
        v = df.iloc[0, 0]
        if isinstance(v, dt.datetime):
            return v.date()
        if isinstance(v, dt.date):
            return v
        return dt.date.fromisoformat(str(v)[:10])
    except Exception as e:
        logger.warning("查询最大日期失败: %s", e)
        return None


def resolve_range(
    *,
    mode: str,
    start: dt.date | None,
    end: dt.date | None,
    only: set[str],
) -> tuple[dt.date, dt.date]:
    end = end or _yesterday()
    if mode == "full":
        if start is None:
            raise SystemExit("--mode full 必须指定 --start")
        if start > end:
            raise SystemExit("--start 不能大于 --end")
        return start, end

    # incremental：取各类已有最大日的最小值作水位，+1
    watermarks: list[dt.date] = []
    if "basic" in only:
        m = _max_date("SELECT max(trade_date) FROM daily_basic")
        if m:
            watermarks.append(m)
    if "suspend" in only:
        m = _max_date("SELECT max(suspend_date) FROM suspend")
        if m:
            watermarks.append(m)
    if "finance" in only:
        m = _max_date("SELECT max(ann_date) FROM fin_statement")
        if m:
            watermarks.append(m)

    if start is not None:
        auto_start = start
    elif watermarks:
        auto_start = min(watermarks) + dt.timedelta(days=1)
    else:
        auto_start = end - dt.timedelta(days=30)
        logger.info("库中无水位，增量默认回溯 30 日 → %s", auto_start)

    if auto_start > end:
        raise ValueError(f"增量无新区间: start={auto_start} end={end}（已是最新）")
    return auto_start, end


def run_incremental_extras(
    *,
    source: str | None = None,
    only: set[str] | None = None,
    end: dt.date | None = None,
    continue_on_error: bool = True,
    publish: bool = True,
    reuse_min_rows: int | None = None,
) -> dict[str, object]:
    """水位增量入口（供 daily_run / 调度调用）。

    - 默认源：``QDATA_EXTRAS_SOURCE`` 或 ``joinquant``
    - 无新区间时返回 ``{"skipped": True, ...}``，不抛错
    - 临时改写 ``QDATA_DATA_SOURCE``，结束后恢复，避免污染生产主源
    """
    only_parts = only or {"basic", "suspend", "finance"}
    src = source or os.environ.get("QDATA_EXTRAS_SOURCE", "joinquant")
    prev_source = os.environ.get("QDATA_DATA_SOURCE")
    try:
        start, end_r = resolve_range(
            mode="incremental", start=None, end=end, only=only_parts
        )
    except ValueError as e:
        logger.info("%s", e)
        return {
            "skipped": True,
            "reason": str(e),
            "source": src,
            "basic_ok": [],
            "suspend_ok": [],
            "finance_ok": [],
            "failed": [],
        }

    try:
        return sync_market_extras(
            start,
            end_r,
            source=src,
            with_basic="basic" in only_parts,
            with_suspend="suspend" in only_parts,
            with_finance="finance" in only_parts,
            continue_on_error=continue_on_error,
            publish=publish,
            reuse_min_rows=reuse_min_rows,
        )
    finally:
        if prev_source is None:
            os.environ.pop("QDATA_DATA_SOURCE", None)
        else:
            os.environ["QDATA_DATA_SOURCE"] = prev_source
        settings.cache_clear()


def sync_market_extras(
    start: dt.date,
    end: dt.date,
    *,
    source: str | None = None,
    with_basic: bool = True,
    with_suspend: bool = True,
    with_finance: bool = True,
    continue_on_error: bool = True,
    publish: bool = True,
    reuse_min_rows: int | None = None,
) -> dict[str, object]:
    if source:
        os.environ["QDATA_DATA_SOURCE"] = source
        settings.cache_clear()

    summary: dict[str, object] = {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "source": source or settings().data_source,
        "basic_ok": [],
        "suspend_ok": [],
        "finance_ok": [],
        "failed": [],
    }

    trade_days = calendar.trading_days_between(start, end)
    cal_days = _calendar_days(start, end)

    if with_basic or with_suspend:
        if not trade_days:
            logger.warning("区间内无交易日 %s~%s（请先 sync_calendar）", start, end)
        for i, d in enumerate(trade_days, 1):
            logger.info("[trade %s/%s] extras %s", i, len(trade_days), d)
            try:
                datasets: list[str] = []
                if with_basic:
                    datasets.append("daily_basic")
                if with_suspend:
                    datasets.append("suspend")
                if datasets:
                    fetch_datasets(
                        tuple(datasets),
                        d,
                        source=source,
                        reuse_min_rows=reuse_min_rows,
                    )
                pub: list[str] = []
                if with_basic:
                    n = DailyBasicLoader().load(d)
                    print(f"daily_basic {d}: {n} rows")
                    summary["basic_ok"].append(d.isoformat())  # type: ignore[union-attr]
                    if n > 0:
                        pub.append("daily_basic")
                if with_suspend:
                    n = SuspendLoader().load(d)
                    print(f"suspend {d}: {n} rows")
                    summary["suspend_ok"].append(d.isoformat())  # type: ignore[union-attr]
                if publish and pub:
                    publish_day(d, tuple(pub), note="sync_market_extras")
            except Exception as e:
                logger.error("trade-day extras 失败 %s: %s", d, e)
                traceback.print_exc()
                summary["failed"].append({"date": d.isoformat(), "error": str(e)})  # type: ignore[union-attr]
                if not continue_on_error:
                    raise

    if with_finance:
        for i, d in enumerate(cal_days, 1):
            if i == 1 or i % 20 == 0 or i == len(cal_days):
                logger.info("[finance %s/%s] ann_date=%s", i, len(cal_days), d)
            try:
                # reuse_min_rows=0：分区已存在（含 0 行空公告日）则跳过重拉，便于中断续跑
                fetch_datasets(
                    ("income", "balancesheet", "cashflow"),
                    d,
                    source=source,
                    reuse_min_rows=0 if reuse_min_rows is None else reuse_min_rows,
                )
                n = FinStatementLoader().load(d)
                if n > 0:
                    print(f"fin_statement {d}: {n} rows")
                    summary["finance_ok"].append(d.isoformat())  # type: ignore[union-attr]
                    if publish:
                        publish_day(d, ("fin_statement",), note="sync_market_extras")
            except Exception as e:
                logger.error("finance 失败 %s: %s", d, e)
                traceback.print_exc()
                summary["failed"].append(  # type: ignore[union-attr]
                    {"date": d.isoformat(), "error": str(e), "kind": "finance"}
                )
                if not continue_on_error:
                    raise

    return summary


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser(
        description="多渠道同步 daily_basic / suspend / fin_statement（JQ 全量+增量）"
    )
    p.add_argument(
        "--source",
        default="joinquant",
        help="joinquant | tushare | joinquant,tushare | …（默认 joinquant）",
    )
    p.add_argument(
        "--mode",
        choices=("full", "incremental"),
        default="incremental",
        help="full=指定区间全量；incremental=自水位增量（默认）",
    )
    p.add_argument("--start", type=dt.date.fromisoformat, default=None)
    p.add_argument("--end", type=dt.date.fromisoformat, default=None)
    p.add_argument(
        "--only",
        default="basic,suspend,finance",
        help="逗号子集: basic,suspend,finance",
    )
    p.add_argument("--continue-on-error", action="store_true", default=True)
    p.add_argument("--fail-fast", action="store_true", help="遇错即停")
    p.add_argument("--no-publish", action="store_true")
    p.add_argument(
        "--reuse-min-rows",
        type=int,
        default=None,
        help="Raw 行数达标则跳过重拉（basic/suspend）",
    )
    args = p.parse_args(argv)

    only_parts = {x.strip() for x in args.only.split(",") if x.strip()}
    unknown = only_parts - {"basic", "suspend", "finance"}
    if unknown:
        raise SystemExit(f"--only 未知项: {unknown}")
    if not only_parts:
        raise SystemExit("--only 不能为空")

    try:
        start, end = resolve_range(
            mode=args.mode, start=args.start, end=args.end, only=only_parts
        )
    except ValueError as e:
        print(e)
        return

    print(
        f"SYNC_MARKET_EXTRAS mode={args.mode} source={args.source} "
        f"range={start}~{end} only={sorted(only_parts)}"
    )

    summary = sync_market_extras(
        start,
        end,
        source=args.source,
        with_basic="basic" in only_parts,
        with_suspend="suspend" in only_parts,
        with_finance="finance" in only_parts,
        continue_on_error=not args.fail_fast,
        publish=not args.no_publish,
        reuse_min_rows=args.reuse_min_rows,
    )
    print(
        "summary: "
        f"basic_days={len(summary['basic_ok'])} "  # type: ignore[arg-type]
        f"suspend_days={len(summary['suspend_ok'])} "  # type: ignore[arg-type]
        f"finance_days={len(summary['finance_ok'])} "  # type: ignore[arg-type]
        f"failed={len(summary['failed'])}"  # type: ignore[arg-type]
    )
    if summary["failed"]:
        for item in summary["failed"][:10]:  # type: ignore[index]
            print(f"  - {item}")
        sys.exit(1)


if __name__ == "__main__":
    main()
