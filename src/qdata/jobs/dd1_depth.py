"""M2.8 DD1 — 日线纵深：分段回填编排 + 水位状态。

目标区间（定稿）：2025-07-01 ~ 2026-07-15，按季：
  2025Q3 → 2025Q4 → 2026Q1 → 2026Q2 → 2026Q3a（至 07-15）

用法：
  # 查看缺口（不拉数）
  python -m qdata.jobs.dd1_depth --status

  # 跑下一段未完成季度（遇错继续，跳过已发布）
  python -m qdata.jobs.dd1_depth --run-next

  # BaoStock 抖动时用 JoinQuant 补洞
  python -m qdata.jobs.dd1_depth --run 2025Q4 --source joinquant

  # 指定段 / 全段缺口
  python -m qdata.jobs.dd1_depth --run 2025Q3
  python -m qdata.jobs.dd1_depth --run-all --source joinquant
"""

from __future__ import annotations

import argparse
import datetime as dt
import logging
import sys
from typing import Any

from qdata.calendar import trading_days_between
from qdata.jobs.prod_backfill import run_prod_backfill
from qdata.prod import prod_min_universe
from qdata.release import check_version_continuity

logger = logging.getLogger(__name__)

# DD101 定稿区间
DD1_START = dt.date(2025, 7, 1)
DD1_END = dt.date(2026, 7, 15)

SEGMENTS: list[tuple[str, dt.date, dt.date]] = [
    ("2025Q3", dt.date(2025, 7, 1), dt.date(2025, 9, 30)),
    ("2025Q4", dt.date(2025, 10, 1), dt.date(2025, 12, 31)),
    ("2026Q1", dt.date(2026, 1, 1), dt.date(2026, 3, 31)),
    ("2026Q2", dt.date(2026, 4, 1), dt.date(2026, 6, 30)),
    ("2026Q3a", dt.date(2026, 7, 1), dt.date(2026, 7, 15)),
]


def _segment_status(
    name: str,
    start: dt.date,
    end: dt.date,
    *,
    min_rows: int,
) -> dict[str, Any]:
    expected = trading_days_between(start, end)
    cont = check_version_continuity(start, end, "daily_bar", min_rows=min_rows)
    missing = list(cont.get("missing") or [])
    published = list(cont.get("published") or [])
    thin = list(cont.get("thin") or [])
    return {
        "segment": name,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "expected_days": len(expected),
        "published_days": len(published),
        "missing_days": len(missing),
        "thin_days": len(thin),
        "ok": bool(cont.get("ok")),
        "missing_head": missing[:8],
        "message": cont.get("message"),
    }


def status_report(*, min_rows: int | None = None) -> dict[str, Any]:
    min_n = min_rows if min_rows is not None else prod_min_universe()
    segs = [_segment_status(n, s, e, min_rows=min_n) for n, s, e in SEGMENTS]
    overall = check_version_continuity(DD1_START, DD1_END, "daily_bar", min_rows=min_n)
    next_seg = next((s["segment"] for s in segs if not s["ok"]), None)
    return {
        "target": {"start": DD1_START.isoformat(), "end": DD1_END.isoformat()},
        "min_rows": min_n,
        "segments": segs,
        "overall_ok": bool(overall.get("ok")),
        "overall_message": overall.get("message"),
        "overall_missing": len(overall.get("missing") or []),
        "next_segment": next_seg,
    }


def print_status(report: dict[str, Any]) -> None:
    print("=" * 60)
    print(f"DD1 DEPTH STATUS  {report['target']['start']} ~ {report['target']['end']}")
    print(f"min_rows={report['min_rows']}  overall_ok={report['overall_ok']}")
    print(report.get("overall_message") or "")
    print("=" * 60)
    for s in report["segments"]:
        flag = "OK" if s["ok"] else "GAP"
        print(
            f"[{flag}] {s['segment']}  {s['start']}~{s['end']}  "
            f"published={s['published_days']}/{s['expected_days']}  "
            f"missing={s['missing_days']} thin={s['thin_days']}"
        )
        if s["missing_head"]:
            print(f"       missing_head: {', '.join(s['missing_head'])}")
    print("-" * 60)
    print(f"next_segment: {report.get('next_segment') or '(全部完成)'}")
    print(f"overall_missing: {report.get('overall_missing')}")


def run_segment(
    name: str,
    *,
    source: str | None = None,
    skip_calendar: bool = True,
    continue_on_error: bool = True,
    run_quality: bool = False,
    validate: bool = False,
    with_suspend: bool = False,
) -> int:
    seg = next((x for x in SEGMENTS if x[0] == name), None)
    if seg is None:
        known = ", ".join(n for n, _, _ in SEGMENTS)
        raise SystemExit(f"未知段 {name!r}；可选: {known}")
    _, start, end = seg
    print(
        f"\n>>> DD1 run segment {name}  {start} ~ {end}  "
        f"source={source or '(prod default)'} with_suspend={with_suspend}"
    )
    rc = run_prod_backfill(
        start,
        end,
        source=source,
        skip_calendar=skip_calendar,
        skip_backfill=False,
        validate_only=False,
        skip_quality=not run_quality,
        with_suspend=with_suspend,
        continue_on_error=continue_on_error,
        skip_published=True,
        skip_validate=not validate,
    )
    st = _segment_status(name, start, end, min_rows=prod_min_universe())
    print(
        f"segment {name} after-run: published={st['published_days']}/"
        f"{st['expected_days']} missing={st['missing_days']} rc={rc}"
    )
    return rc


def run_next(**kwargs: Any) -> int:
    report = status_report()
    print_status(report)
    nxt = report.get("next_segment")
    if not nxt:
        print("DD1: 全部季度已满足 version 连续（min_rows 门槛内）")
        return 0
    return run_segment(str(nxt), **kwargs)


def run_all(**kwargs: Any) -> int:
    worst = 0
    min_n = prod_min_universe()
    for name, start, end in SEGMENTS:
        st = _segment_status(name, start, end, min_rows=min_n)
        if st["ok"]:
            print(f"skip OK segment {name}")
            continue
        rc = run_segment(name, **kwargs)
        if rc != 0:
            worst = rc
    print_status(status_report())
    return worst


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser(description="M2.8 DD1 日线纵深：状态 + 分段回填")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--status", action="store_true", help="只打印缺口水位")
    g.add_argument("--run-next", action="store_true", help="跑下一段未完成季度")
    g.add_argument("--run-all", action="store_true", help="依次跑所有缺口段")
    g.add_argument("--run", metavar="SEG", help="跑指定段，如 2025Q3")
    p.add_argument(
        "--with-calendar",
        action="store_true",
        help="回填前同步日历（默认跳过，DD102 已覆盖）",
    )
    p.add_argument(
        "--stop-on-error",
        action="store_true",
        help="单日失败即停（默认 continue-on-error，适合 BaoStock 抖动）",
    )
    p.add_argument("--run-quality", action="store_true", help="回填时跑质量 HARD")
    p.add_argument(
        "--with-suspend",
        action="store_true",
        help="同时拉停牌（默认关闭，避免 BaoStock 超时拖死日线发布）",
    )
    p.add_argument(
        "--source",
        default=None,
        help="覆盖生产主源：baostock|tushare|joinquant（BaoStock 抖动时用 joinquant 补洞）",
    )
    p.add_argument(
        "--min-rows",
        type=int,
        default=None,
        help="status 用的 published row_count 下限（默认 PROD_MIN_UNIVERSE）",
    )
    args = p.parse_args(argv)

    if args.status:
        print_status(status_report(min_rows=args.min_rows))
        report = status_report(min_rows=args.min_rows)
        sys.exit(0 if report["overall_ok"] else 1)

    kwargs = dict(
        source=args.source,
        skip_calendar=not args.with_calendar,
        continue_on_error=not args.stop_on_error,
        run_quality=args.run_quality,
        with_suspend=args.with_suspend,
    )
    if args.run_next:
        sys.exit(run_next(**kwargs))
    if args.run_all:
        sys.exit(run_all(**kwargs))
    if args.run:
        sys.exit(run_segment(args.run, **kwargs))


if __name__ == "__main__":
    main()
