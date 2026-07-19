"""同步申万行业分类区间表（属性 SCD2）。

模式：
  snapshot — 拉取当日 AKShare 申万 L1/L2 成分并入库（单期；历史变更不全）
  rebuild  — 用湖中全部 Raw 快照重建区间

用法：
  python -m qdata.jobs.sync_industry_member --date 2026-07-15
  python -m qdata.jobs.sync_industry_member --date 2026-07-15 --levels sw_l1
  python -m qdata.jobs.sync_industry_member --mode rebuild

验收：
  DataAPI().get_industry(['600000.SH'], date, level='sw_l1') 非空；
  多期 rebuild 后分类变更应闭合旧区间。
"""

from __future__ import annotations

import argparse
import datetime as dt
import logging
import sys
from zoneinfo import ZoneInfo

from qdata.industry import SEED_LEVELS
from qdata.industry.fetch import fetch_sw_industry_snapshot, load_raw_industry_snapshots
from qdata.lake.raw import write_raw
from qdata.loaders.industry_member import IndustryMemberLoader, verify_pit

logger = logging.getLogger(__name__)
_SH = ZoneInfo("Asia/Shanghai")


def sync_industry_member(
    as_of: dt.date | None = None,
    *,
    levels: tuple[str, ...] | None = None,
    source: str = "akshare",
    mode: str = "snapshot",
    sleep_s: float = 0.15,
) -> int:
    d = as_of or dt.datetime.now(_SH).date()
    targets = levels or SEED_LEVELS
    mode = (mode or "snapshot").strip().lower()
    print(f"SYNC_INDUSTRY_MEMBER mode={mode} as_of={d} levels={list(targets)}")

    if mode == "snapshot":
        snap = fetch_sw_industry_snapshot(d, levels=targets, sleep_s=sleep_s)
        if snap.empty:
            raise RuntimeError("行业分类拉取为空（检查网络/代理或 AKShare）")
        path = write_raw(source, "industry_member", d, snap)
        print(f"raw industry_member {d}: {len(snap)} rows -> {path}")
        for conf, n in snap.groupby("confidence").size().items():
            print(f"  confidence={conf}: {n}")
        print(
            "注意: 单期 snapshot 无法还原历史调行业；"
            "多次 sync 后用 --mode rebuild。"
        )
        n = IndustryMemberLoader().load_scd2(snap)

    elif mode == "rebuild":
        snap = load_raw_industry_snapshots(source=source)
        if snap.empty:
            raise RuntimeError(
                f"湖中无 {source}/industry_member 快照。"
                f"请先: python -m qdata.jobs.sync_industry_member --mode snapshot"
            )
        if levels:
            snap = snap[snap["level"].isin(levels)]
        n_dates = snap["as_of_date"].nunique() if "as_of_date" in snap.columns else 0
        print(f"rebuild from raw: rows={len(snap)} distinct_as_of={n_dates}")
        if n_dates < 2:
            print("警告: 仅 1 期快照，调行业区间仍无法闭合（out_date 多为 2099-12-31）")
        n = IndustryMemberLoader().load_scd2(snap)

    else:
        raise RuntimeError(f"未知 mode={mode!r}，可选 snapshot|rebuild")

    print(f"industry_member intervals: {n}")
    for lv in targets:
        cnt = verify_pit(lv, d)
        print(f"  PIT {lv} @{d}: {cnt}")
    return n


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser(description="同步申万行业分类区间表（SCD2）")
    p.add_argument("--date", type=dt.date.fromisoformat, default=None)
    p.add_argument(
        "--mode",
        default="snapshot",
        choices=("snapshot", "rebuild"),
        help="snapshot=当日快照; rebuild=湖内多期重建",
    )
    p.add_argument(
        "--levels",
        default=None,
        help="逗号分隔，默认 sw_l1,sw_l2",
    )
    p.add_argument("--source", default="akshare")
    p.add_argument(
        "--sleep",
        type=float,
        default=0.15,
        help="拉取各行业成分间隔秒（限速）",
    )
    args = p.parse_args(argv)
    levels = None
    if args.levels:
        levels = tuple(x.strip() for x in args.levels.split(",") if x.strip())
    try:
        sync_industry_member(
            args.date,
            levels=levels,
            source=args.source,
            mode=args.mode,
            sleep_s=args.sleep,
        )
    except Exception as e:
        logger.exception("%s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
