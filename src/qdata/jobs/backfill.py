"""按日期区间回填行情 / 财务到 Raw + ClickHouse。

用法：
  # 先同步日历（推荐）
  python -m qdata.jobs.sync_calendar --start 2026-06-01 --end 2026-07-15

  # 回填主数据 + 日线（含 adj/suspend）
  python -m qdata.jobs.backfill --start 2026-06-01 --end 2026-07-15 --source baostock

  # 仅日线、跳过质量门禁（MAX_SYMBOLS 联调时常用）
  python -m qdata.jobs.backfill --start 2026-07-01 --end 2026-07-15 \\
      --source baostock --skip-master --skip-quality

  # 含财务 + 每日指标，并发布 dataset_version
  python -m qdata.jobs.backfill --start 2026-07-01 --end 2026-07-15 \\
      --source tushare --with-finance --with-basic --publish

  # 冒烟
  python -m qdata.jobs.smoke --date 2026-07-15
"""

from __future__ import annotations

import argparse
import datetime as dt
import logging
import os
import traceback

from qdata import calendar
from qdata.config import settings
from qdata.fetchers.cli import fetch_datasets
from qdata.loaders.daily_bar import DailyBarLoader
from qdata.loaders.daily_basic import DailyBasicLoader
from qdata.loaders.fin_statement import FinStatementLoader
from qdata.loaders.security_master import SecurityMasterLoader
from qdata.publish import is_published, publish_day
from qdata.quality.checks import has_blocking_failure, run_all

logger = logging.getLogger(__name__)


def _set_source(source: str | None) -> None:
    if not source:
        return
    os.environ["QDATA_DATA_SOURCE"] = source
    settings.cache_clear()


def backfill(
    start: dt.date,
    end: dt.date,
    *,
    source: str | None = None,
    skip_master: bool = False,
    skip_quality: bool = False,
    with_finance: bool = False,
    with_basic: bool = False,
    with_suspend: bool = True,
    publish: bool = True,
    continue_on_error: bool = True,
    reuse_min_rows: int | None = None,
    skip_published: bool = False,
    skip_published_min_rows: int | None = None,
) -> dict[str, object]:
    """回填 [start, end] 交易日。返回摘要统计。

    reuse_min_rows: Raw 已有足够行数则跳过重拉（中断续跑）。
    skip_published: 已发布且 row_count 达标的交易日整日跳过（prod 续跑推荐）。
    with_suspend: 是否拉取/加载停牌（BaoStock 易超时；DD1 纵深默认可关）。
    """
    _set_source(source)
    days = calendar.trading_days_between(start, end)
    if not days:
        raise RuntimeError(f"区间内无交易日: {start} ~ {end}（请先 sync_calendar）")

    pub_min = (
        skip_published_min_rows
        if skip_published_min_rows is not None
        else (reuse_min_rows if reuse_min_rows is not None else 1)
    )

    summary: dict[str, object] = {
        "days": len(days),
        "ok": [],
        "failed": [],
        "skipped": [],
        "master_rows": 0,
        "quality_failed": [],
        "published": [],
    }

    # 主数据：用区间末日快照一次即可（在市列表）
    if not skip_master:
        master_date = days[-1]
        logger.info("加载 security_master @ %s", master_date)
        try:
            fetch_datasets(
                ("stock_basic",),
                master_date,
                source=source,
                reuse_min_rows=reuse_min_rows,
            )
            summary["master_rows"] = SecurityMasterLoader().load(master_date)
            print(f"security_master {master_date}: {summary['master_rows']} rows")
        except Exception as e:
            # 主数据失败不阻断「仅补缺日」：若库中已有 master 可继续
            from qdata import db

            n = int(db.query_df("SELECT count() AS n FROM security_master")["n"][0])
            if n <= 0:
                raise
            logger.warning(
                "security_master 拉取失败，沿用库中 %s 行: %s", n, e,
            )
            summary["master_rows"] = n
            print(f"security_master reuse existing: {n} rows ({e})")

    # 日线主路径硬依赖；suspend/basic 软依赖（网络抖动不得阻断 publish）
    core_datasets: list[str] = ["daily_bar", "adj_factor"]
    soft_datasets: list[str] = []
    if with_suspend:
        soft_datasets.append("suspend")
    if with_basic:
        soft_datasets.append("daily_basic")

    # BaoStock：多日未发布时一次区间预取写 Raw，避免按日 × 全市场重复扫标的
    prod_src = (source or settings().data_source or "").strip().lower()
    if prod_src == "baostock":
        need_prefetch: list[dt.date] = []
        for d in days:
            if skip_published and is_published(d, "daily_bar", min_rows=pub_min):
                continue
            if (
                reuse_min_rows is not None
                and reuse_min_rows > 0
            ):
                from qdata.lake.raw import raw_row_count

                n_exist = raw_row_count("baostock", "daily_bar", d)
                if n_exist is not None and n_exist >= reuse_min_rows:
                    continue
            need_prefetch.append(d)
        # 分块预取：整季 60 天一次 login 易因网络抖动失败；默认按 10 日切块
        if len(need_prefetch) >= 2:
            from qdata.fetchers.baostock_fetcher import BaostockFetcher

            chunk_n = int(os.environ.get("QDATA_BAOSTOCK_PREFETCH_CHUNK_DAYS", "10") or "10")
            chunk_n = max(2, chunk_n)
            fetcher = BaostockFetcher()
            for i in range(0, len(need_prefetch), chunk_n):
                chunk = need_prefetch[i : i + chunk_n]
                logger.info(
                    "BaoStock 区间预取 chunk %s/%s 天: %s ~ %s",
                    len(chunk),
                    len(need_prefetch),
                    chunk[0],
                    chunk[-1],
                )
                print(
                    f"baostock prefetch chunk: {chunk[0]}~{chunk[-1]} "
                    f"({len(chunk)}/{len(need_prefetch)} days)"
                )
                try:
                    fetcher.prefetch_daily_range_to_raw(
                        chunk[0],
                        chunk[-1],
                        open_days=chunk,
                    )
                except Exception as e:
                    logger.warning(
                        "BaoStock 预取 chunk 失败 %s~%s: %s（将回退按日 fetch）",
                        chunk[0],
                        chunk[-1],
                        e,
                    )
                    print(f"warn: baostock prefetch chunk failed, fallback per-day: {e}")

    for i, d in enumerate(days, 1):
        logger.info("[%s/%s] 回填 %s", i, len(days), d)
        if skip_published and is_published(d, "daily_bar", min_rows=pub_min):
            msg = f"skip published daily_bar@{d} (row_count>={pub_min})"
            print(msg)
            summary["skipped"].append(d.isoformat())  # type: ignore[union-attr]
            summary["ok"].append(d.isoformat())  # type: ignore[union-attr]
            continue
        try:
            fetch_datasets(
                tuple(core_datasets),
                d,
                source=source,
                reuse_min_rows=reuse_min_rows,
            )
            for soft_ds in soft_datasets:
                try:
                    fetch_datasets(
                        (soft_ds,),
                        d,
                        source=source,
                        reuse_min_rows=reuse_min_rows,
                    )
                except Exception as e:
                    logger.warning("软数据集 fetch 跳过 %s@%s: %s", soft_ds, d, e)
                    print(f"warn: soft fetch skip {soft_ds}@{d}: {e}")

            n = DailyBarLoader().load(d)
            print(f"daily_bar {d}: {n} rows")

            publish_datasets: list[str] = ["daily_bar"]

            if with_suspend:
                try:
                    from qdata.loaders.suspend import SuspendLoader

                    ns = SuspendLoader().load(d)
                    if ns > 0:
                        print(f"suspend {d}: {ns} rows")
                except Exception as e:
                    logger.warning("suspend 表写入跳过 %s: %s", d, e)

            if with_basic:
                try:
                    nb = DailyBasicLoader().load(d)
                    print(f"daily_basic {d}: {nb} rows")
                    if nb > 0:
                        publish_datasets.append("daily_basic")
                except Exception as e:
                    logger.warning("daily_basic 跳过 %s: %s", d, e)

            if with_finance:
                for ds in ("income", "balancesheet", "cashflow"):
                    try:
                        fetch_datasets((ds,), d, source=source)
                    except Exception as e:
                        logger.warning("finance fetch %s@%s 跳过: %s", ds, d, e)
                nf = FinStatementLoader().load(d)
                print(f"fin_statement {d}: {nf} rows")
                if nf > 0:
                    publish_datasets.append("fin_statement")

            quality_blocked = False
            if not skip_quality:
                results = run_all(d)
                report = "; ".join(
                    f"{r.name}={'PASS' if r.passed else 'FAIL'}" for r in results
                )
                print(f"quality {d}: {report}")
                if has_blocking_failure(results):
                    quality_blocked = True
                    summary["quality_failed"].append(d.isoformat())  # type: ignore[union-attr]
                    if not continue_on_error:
                        raise RuntimeError(f"质量硬规则失败: {d}\n{report}")
                    logger.warning("质量硬规则失败，跳过发布: %s", d)

            if publish and not quality_blocked:
                pub = publish_day(d, tuple(publish_datasets), note="backfill")
                print(f"published {d}: {pub}")
                summary["published"].append(d.isoformat())  # type: ignore[union-attr]

            summary["ok"].append(d.isoformat())  # type: ignore[union-attr]
        except Exception as e:
            logger.error("回填失败 %s: %s", d, e)
            traceback.print_exc()
            summary["failed"].append({"date": d.isoformat(), "error": str(e)})  # type: ignore[union-attr]
            if not continue_on_error:
                raise

    return summary


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser(description="按日期区间回填 qdata 行情/财务")
    p.add_argument("--start", required=True, type=dt.date.fromisoformat)
    p.add_argument("--end", required=True, type=dt.date.fromisoformat)
    p.add_argument(
        "--source",
        default=None,
        help="覆盖 QDATA_DATA_SOURCE，如 baostock / tushare / auto",
    )
    p.add_argument("--skip-master", action="store_true", help="跳过 security_master")
    p.add_argument("--skip-quality", action="store_true", help="跳过质量校验")
    p.add_argument(
        "--with-finance",
        action="store_true",
        help="同时回填 income/balancesheet/cashflow 财务",
    )
    p.add_argument("--with-basic", action="store_true", help="同时回填 daily_basic")
    p.add_argument(
        "--skip-suspend",
        action="store_true",
        help="不拉取停牌（加快 DD1 日线发布；停牌可后补）",
    )
    p.add_argument(
        "--no-publish",
        action="store_true",
        help="不写入 dataset_version（默认质量通过后发布）",
    )
    p.add_argument(
        "--stop-on-error",
        action="store_true",
        help="遇错即停（默认单日失败后继续下一日）",
    )
    p.add_argument(
        "--reuse-min-rows",
        type=int,
        default=None,
        help="Raw 行数≥该值则跳过重拉（续跑）；默认不复用",
    )
    p.add_argument(
        "--skip-published",
        action="store_true",
        help="已发布 daily_bar 且行数达标的交易日整日跳过",
    )
    args = p.parse_args(argv)
    if args.start > args.end:
        raise SystemExit("--start 不能大于 --end")

    summary = backfill(
        args.start,
        args.end,
        source=args.source,
        skip_master=args.skip_master,
        skip_quality=args.skip_quality,
        with_finance=args.with_finance,
        with_basic=args.with_basic,
        with_suspend=not args.skip_suspend,
        publish=not args.no_publish,
        continue_on_error=not args.stop_on_error,
        reuse_min_rows=args.reuse_min_rows,
        skip_published=args.skip_published,
    )
    print(
        f"\n回填完成: days={summary['days']} ok={len(summary['ok'])} "  # type: ignore[arg-type]
        f"skipped={len(summary.get('skipped') or [])} "  # type: ignore[arg-type]
        f"failed={len(summary['failed'])} "  # type: ignore[arg-type]
        f"quality_failed={len(summary['quality_failed'])} "  # type: ignore[arg-type]
        f"published={len(summary['published'])}"  # type: ignore[arg-type]
    )
    if summary["failed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
