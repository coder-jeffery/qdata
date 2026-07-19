"""同步种子指数成分区间表（SCD2）。

模式：
  snapshot  — 拉取当日/指定日 AKShare 快照并入库（单期；调出历史不全）
  rebuild   — 用湖中全部 Raw 快照重建区间（多次 sync 后才有调出闭合）
  tushare   — 拉取 Tushare 月度 index_weight 重建（推荐历史回放）

用法：
  python -m qdata.jobs.sync_index_member --date 2026-07-15
  python -m qdata.jobs.sync_index_member --mode rebuild
  python -m qdata.jobs.sync_index_member --mode tushare --start 2020-01-01 --end 2026-07-15

验收：
  DataAPI().get_universe('000300.SH', date) 非空；
  调仓前后时点成分集合应变化（有多期数据时）。
"""

from __future__ import annotations

import argparse
import datetime as dt
import logging
import sys
from zoneinfo import ZoneInfo

from qdata.index import SEED_INDEX_CODES
from qdata.index.fetch import (
    fetch_index_weight_history,
    fetch_seed_index_members,
    load_raw_index_snapshots,
)
from qdata.lake.raw import write_raw
from qdata.loaders.index_member import IndexMemberLoader, verify_pit

logger = logging.getLogger(__name__)
_SH = ZoneInfo("Asia/Shanghai")


def sync_index_member(
    as_of: dt.date | None = None,
    *,
    indices: tuple[str, ...] | None = None,
    source: str = "akshare",
    mode: str = "snapshot",
    start: dt.date | None = None,
    end: dt.date | None = None,
) -> int:
    """拉取/重建并入库，返回区间行数。"""
    d = as_of or dt.datetime.now(_SH).date()
    targets = indices or SEED_INDEX_CODES
    mode = (mode or "snapshot").strip().lower()
    print(f"SYNC_INDEX_MEMBER mode={mode} as_of={d} indices={list(targets)}")

    if mode == "snapshot":
        snap = fetch_seed_index_members(d, indices=targets)
        if snap.empty:
            raise RuntimeError("指数成分拉取为空（检查网络/代理或指数代码）")
        path = write_raw(source, "index_member", d, snap)
        print(f"raw index_member {d}: {len(snap)} rows -> {path}")
        for conf, n in snap.groupby("confidence").size().items():
            print(f"  confidence={conf}: {n}")
        print(
            "注意: 单期 snapshot 无法还原历史调出；"
            "多次 sync 后用 --mode rebuild，或 --mode tushare 做历史回放。"
        )
        n = IndexMemberLoader().load_scd2(snap)

    elif mode == "rebuild":
        snap = load_raw_index_snapshots(source=source)
        if snap.empty:
            raise RuntimeError(
                f"湖中无 {source}/index_member 快照。"
                f"请先: python -m qdata.jobs.sync_index_member --mode snapshot"
            )
        if indices:
            snap = snap[snap["index_code"].isin(indices)]
        n_dates = snap["as_of_date"].nunique() if "as_of_date" in snap.columns else 0
        print(f"rebuild from raw: rows={len(snap)} distinct_as_of={n_dates}")
        if n_dates < 2:
            print("警告: 仅 1 期快照，调出区间仍无法闭合（out_date 多为 2099-12-31）")
        n = IndexMemberLoader().load_scd2(snap)

    elif mode == "tushare":
        if start is None or end is None:
            raise RuntimeError("tushare 模式需要 --start 与 --end")
        if start > end:
            raise RuntimeError("--start 不能大于 --end")
        snap = fetch_index_weight_history(start, end, indices=targets)
        if snap.empty:
            raise RuntimeError(
                "Tushare index_weight 为空（检查 ENABLED/TOKEN/积分，"
                "沪深300 使用 399300.SZ）"
            )
        # 按月末分区落 Raw，便于 rebuild
        for as_of, part in snap.groupby("as_of_date"):
            write_raw("tushare", "index_member", as_of, part.reset_index(drop=True))
            print(f"raw tushare index_member {as_of}: {len(part)} rows")
        n = IndexMemberLoader().load_scd2(snap)

    else:
        raise RuntimeError(f"未知 mode={mode!r}，可选 snapshot|rebuild|tushare")

    print(f"index_member intervals: {n}")
    for idx in targets:
        cnt = verify_pit(idx, d)
        print(f"  PIT {idx} @{d}: {cnt}")
    return n


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser(description="同步种子指数成分区间表（SCD2）")
    p.add_argument("--date", type=dt.date.fromisoformat, default=None, help="snapshot 基准日")
    p.add_argument(
        "--mode",
        default="snapshot",
        choices=("snapshot", "rebuild", "tushare"),
        help="snapshot=当日快照; rebuild=湖内多期重建; tushare=月度权重历史",
    )
    p.add_argument("--start", type=dt.date.fromisoformat, default=None, help="tushare 起点")
    p.add_argument("--end", type=dt.date.fromisoformat, default=None, help="tushare 终点")
    p.add_argument(
        "--index",
        default=None,
        help="逗号分隔指数，默认 000300.SH,000905.SH,000852.SH",
    )
    p.add_argument("--source", default="akshare", help="Raw source 目录名（snapshot/rebuild）")
    args = p.parse_args(argv)
    indices = None
    if args.index:
        indices = tuple(x.strip() for x in args.index.split(",") if x.strip())
    try:
        sync_index_member(
            args.date,
            indices=indices,
            source=args.source,
            mode=args.mode,
            start=args.start,
            end=args.end,
        )
    except Exception as e:
        logger.exception("%s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
