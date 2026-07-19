"""本地调试：拉取数据集并写入 Raw 区。

用法：
  python -m qdata.fetchers --list-sources
  python -m qdata.fetchers --date 2026-07-15 --dataset daily_bar --source baostock
  python -m qdata.fetchers --date 2026-07-15 --dataset realtime_quote --source easyquotation
  python -m qdata.fetchers --date 2026-07-15 --dataset daily_bar --source auto
"""

from __future__ import annotations

import argparse
import datetime as dt
import logging
import os

from qdata.config import settings
from qdata.fetchers.factory import format_sources_table, get_fetcher
from qdata.fetchers.registry import REGISTRY
from qdata.lake.raw import raw_row_count, write_raw

# 行数过少视为不完整，允许复用门槛跳过
# suspend 行数天然可能很少：只要分区存在即可复用
_REUSE_DATASETS = frozenset({
    "daily_bar", "adj_factor", "stock_basic", "daily_basic", "income",
    "balancesheet", "cashflow",
})
_REUSE_IF_EXISTS = frozenset({"suspend"})


def _can_reuse_raw(
    source: str,
    dataset: str,
    trade_date: dt.date,
    min_rows: int,
) -> bool:
    """判断 Raw 是否足够完整可跳过重拉。

    adj_factor 除绝对门槛外，还要求接近同日 daily_bar 行数，
    避免联调残留的少量复权因子被误复用。
    suspend 只要分区存在即可复用（停牌股可能很少）。
    """
    n = raw_row_count(source, dataset, trade_date)
    if dataset in _REUSE_IF_EXISTS:
        return n is not None
    if n is None or n < min_rows:
        return False
    if dataset == "adj_factor":
        bar_n = raw_row_count(source, "daily_bar", trade_date)
        if bar_n is not None and bar_n >= min_rows and n < int(bar_n * 0.9):
            return False
    return True


SOURCE_CHOICES = tuple(
    sorted(
        [n for n, s in REGISTRY.items() if s.kind in ("historical", "realtime")]
        + ["auto"]
    )
)


def fetch_datasets(
    datasets: tuple[str, ...] | list[str],
    trade_date: dt.date,
    source: str | None = None,
    *,
    reuse_min_rows: int | None = None,
) -> dict[str, int]:
    """拉取多个数据集落 Raw，返回 {dataset: rows}。

    reuse_min_rows: 若 Raw 已有 ≥ 该行数则跳过重拉（中断续跑用）。
    若 fetcher 实现 fetch_many，则未复用的数据集在同一会话内批量拉取（BaoStock 少 login）。
    """
    if source:
        os.environ["QDATA_DATA_SOURCE"] = source
        settings.cache_clear()
    fetcher = get_fetcher(source)
    result: dict[str, int] = {}
    to_fetch: list[str] = []

    for dataset in datasets:
        if (
            reuse_min_rows is not None
            and reuse_min_rows > 0
            and (
                dataset in _REUSE_DATASETS
                or dataset in _REUSE_IF_EXISTS
            )
            and _can_reuse_raw(
                fetcher.source, dataset, trade_date, reuse_min_rows
            )
        ):
            n_exist = raw_row_count(fetcher.source, dataset, trade_date) or 0
            print(
                f"reuse[{fetcher.source}] {dataset} {trade_date}: "
                f"{n_exist} rows (>= {reuse_min_rows})"
            )
            result[dataset] = n_exist
            continue
        to_fetch.append(dataset)

    if not to_fetch:
        return result

    if hasattr(fetcher, "fetch_many"):
        frames = fetcher.fetch_many(to_fetch, trade_date)
        for dataset in to_fetch:
            df = frames[dataset]
            path = write_raw(fetcher.source, dataset, trade_date, df)
            result[dataset] = len(df)
            print(
                f"fetch[{fetcher.source}] {dataset} {trade_date}: "
                f"{len(df)} rows -> {path}"
            )
        return result

    for dataset in to_fetch:
        df = fetcher.fetch(dataset, trade_date)
        path = write_raw(fetcher.source, dataset, trade_date, df)
        result[dataset] = len(df)
        print(f"fetch[{fetcher.source}] {dataset} {trade_date}: {len(df)} rows -> {path}")
    return result


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Fetch market datasets into Raw lake")
    parser.add_argument(
        "--list-sources",
        action="store_true",
        help="列出已注册数据源与能力",
    )
    parser.add_argument("--date", type=dt.date.fromisoformat, default=None)
    parser.add_argument(
        "--dataset",
        default=None,
        help="逗号分隔数据集，如 daily_bar,adj_factor,suspend / realtime_quote",
    )
    parser.add_argument(
        "--source",
        default=None,
        help=f"数据源或逗号链，默认 QDATA_DATA_SOURCE。可选: {', '.join(SOURCE_CHOICES)}",
    )
    args = parser.parse_args(argv)

    if args.list_sources:
        print(format_sources_table())
        return

    if args.date is None or not args.dataset:
        parser.error("拉取数据需同时提供 --date 与 --dataset（或使用 --list-sources）")

    datasets = tuple(d.strip() for d in args.dataset.split(",") if d.strip())
    if not datasets:
        raise SystemExit("--dataset 不能为空")
    fetch_datasets(datasets, args.date, source=args.source)


if __name__ == "__main__":
    main()
