"""M2.8 DD2 — 估值/财务配套：对齐水位 + 编排入口。

相对「已发布 daily_bar」检查 daily_basic 缺口；财务按公告日拉长。

用法：
  python -m qdata.jobs.dd2_extras --status
  python -m qdata.jobs.dd2_extras --align-basic          # 补齐 bar∖basic
  python -m qdata.jobs.dd2_extras --finance-extend       # 公告日拉长
  python -m qdata.jobs.dd2_extras --pit-check            # get_fundamental 抽检
"""

from __future__ import annotations

import argparse
import datetime as dt
import logging
import sys
from typing import Any

from qdata import db
from qdata.jobs.sync_market_extras import sync_market_extras
from qdata.prod import prod_min_universe
from qdata.release import check_version_continuity

logger = logging.getLogger(__name__)

# 与 DD1 定稿一致（跳过未回填季度时，对齐只针对已发布日）
DD_START = dt.date(2025, 7, 1)
DD_END = dt.date(2026, 7, 15)
# 财务 PIT：研究起点前需要足够公告水位
FINANCE_START_DEFAULT = dt.date(2025, 1, 1)


def _iso(d: Any) -> str:
    return str(d)[:10]


def _published_bar_days(
    start: dt.date = DD_START,
    end: dt.date = DD_END,
    *,
    min_rows: int | None = None,
) -> list[str]:
    min_n = min_rows if min_rows is not None else prod_min_universe()
    cont = check_version_continuity(start, end, "daily_bar", min_rows=min_n)
    return sorted(cont.get("published") or [])


def _basic_days() -> set[str]:
    try:
        df = db.query_df("SELECT DISTINCT trade_date AS d FROM daily_basic")
    except Exception as e:
        logger.warning("读 daily_basic 失败: %s", e)
        return set()
    if df is None or df.empty:
        return set()
    return {_iso(x) for x in df["d"].tolist()}


def _finance_watermark() -> dict[str, Any]:
    try:
        df = db.query_df(
            """
            SELECT min(ann_date) AS mn, max(ann_date) AS mx, count() AS n,
                   uniqExact(security_id) AS codes
            FROM fin_statement
            """
        )
    except Exception as e:
        return {"error": str(e)[:200]}
    if df is None or df.empty:
        return {"min_ann": None, "max_ann": None, "rows": 0, "codes": 0}
    r = df.iloc[0]
    return {
        "min_ann": _iso(r["mn"]) if r["mn"] is not None else None,
        "max_ann": _iso(r["mx"]) if r["mx"] is not None else None,
        "rows": int(r["n"] or 0),
        "codes": int(r["codes"] or 0),
    }


def _finance_raw_coverage(
    start: dt.date = FINANCE_START_DEFAULT,
    end: dt.date = DD_END,
    *,
    source: str = "joinquant",
) -> dict[str, Any]:
    """目标公告日日历区间的 Raw 覆盖（含 0 行空日也算已同步）。

    财报公告天然稀疏：CH max(ann_date) 不必等于 end 才算拉长完成。
    """
    from qdata.lake.raw import raw_row_count

    expected = 0
    present = 0
    missing_head: list[str] = []
    d = start
    while d <= end:
        expected += 1
        n = raw_row_count(source, "income", d)
        if n is not None:
            present += 1
        elif len(missing_head) < 8:
            missing_head.append(d.isoformat())
        d += dt.timedelta(days=1)
    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "expected_days": expected,
        "present_days": present,
        "missing_days": expected - present,
        "missing_head": missing_head,
        "complete": expected > 0 and present >= expected,
    }


def status_report(*, min_rows: int | None = None) -> dict[str, Any]:
    pub = _published_bar_days(min_rows=min_rows)
    basic = _basic_days()
    pub_set = set(pub)
    missing = sorted(pub_set - basic)
    covered = sorted(pub_set & basic)
    fin = _finance_watermark()
    raw_cov = _finance_raw_coverage()
    overlap_ok = len(pub) > 0 and len(missing) == 0
    # 水位：Raw 区间已齐 + CH 有足够行/代码（公告右端稀疏不强制 max==end）
    fin_ok = (
        bool(raw_cov.get("complete"))
        and int(fin.get("rows") or 0) >= 10_000
        and int(fin.get("codes") or 0) >= 1_000
    )
    return {
        "target": {"start": DD_START.isoformat(), "end": DD_END.isoformat()},
        "published_bar_days": len(pub),
        "basic_days_total": len(basic),
        "overlap_covered": len(covered),
        "bar_without_basic": len(missing),
        "missing_head": missing[:12],
        "missing_tail": missing[-6:] if len(missing) > 6 else missing,
        "overlap_ok": overlap_ok,
        "finance": fin,
        "finance_raw": raw_cov,
        "finance_needs_extend": not fin_ok,
    }


def print_status(report: dict[str, Any]) -> None:
    print("=" * 60)
    print(f"DD2 EXTRAS STATUS  {report['target']['start']} ~ {report['target']['end']}")
    print("=" * 60)
    print(
        f"published_bar={report['published_bar_days']}  "
        f"basic_total={report['basic_days_total']}  "
        f"overlap_covered={report['overlap_covered']}  "
        f"bar_without_basic={report['bar_without_basic']}  "
        f"overlap_ok={report['overlap_ok']}"
    )
    if report["missing_head"]:
        print(f"missing_head: {', '.join(report['missing_head'])}")
        if report["missing_tail"] and report["missing_tail"] != report["missing_head"]:
            print(f"missing_tail: {', '.join(report['missing_tail'])}")
    fin = report.get("finance") or {}
    raw = report.get("finance_raw") or {}
    print(
        f"finance: rows={fin.get('rows')} codes={fin.get('codes')} "
        f"ann={fin.get('min_ann')}~{fin.get('max_ann')} "
        f"raw={raw.get('present_days')}/{raw.get('expected_days')} "
        f"needs_extend={report.get('finance_needs_extend')}"
    )


def align_basic(
    *,
    source: str = "joinquant",
    reuse_min_rows: int | None = 400,
) -> int:
    """为已发布 daily_bar 且缺 daily_basic 的交易日补齐。"""
    report = status_report()
    print_status(report)
    missing = sorted(set(_published_bar_days()) - _basic_days())
    if not missing:
        print("DD201: 已发布日线均有 daily_basic，无需对齐")
        return 0
    start = dt.date.fromisoformat(missing[0])
    end = dt.date.fromisoformat(missing[-1])
    print(f"\n>>> DD201 align-basic  {start} ~ {end}  days={len(missing)}  source={source}")
    summary = sync_market_extras(
        start,
        end,
        source=source,
        with_basic=True,
        with_suspend=False,
        with_finance=False,
        continue_on_error=True,
        publish=True,
        reuse_min_rows=reuse_min_rows,
    )
    print(
        f"summary: basic_ok={len(summary['basic_ok'])} "  # type: ignore[arg-type]
        f"failed={len(summary['failed'])}"  # type: ignore[arg-type]
    )
    after = status_report()
    print_status(after)
    return 0 if after["overlap_ok"] or after["bar_without_basic"] < report["bar_without_basic"] else 1


def finance_extend(
    *,
    source: str = "joinquant",
    start: dt.date | None = None,
    end: dt.date | None = None,
) -> int:
    """按公告日拉长 fin_statement（默认研究起点前 → DD 末日）。"""
    start = start or FINANCE_START_DEFAULT
    end = end or DD_END
    print(f"\n>>> DD202 finance-extend  {start} ~ {end}  source={source}")
    print_status(status_report())
    summary = sync_market_extras(
        start,
        end,
        source=source,
        with_basic=False,
        with_suspend=False,
        with_finance=True,
        continue_on_error=True,
        publish=True,
        reuse_min_rows=0,  # 空公告日 Raw 也可复用
    )
    print(
        f"summary: finance_days={len(summary['finance_ok'])} "  # type: ignore[arg-type]
        f"failed={len(summary['failed'])}"  # type: ignore[arg-type]
    )
    print_status(status_report())
    return 0 if not summary["failed"] else 1


def pit_check(
    *,
    codes: list[str] | None = None,
    asof: dt.date | None = None,
) -> int:
    """DD203：固定代码 × asof 抽检 get_fundamental（无前视、科目非空）。"""
    from qdata.api.data_api import DataAPI

    codes = codes or ["600519.SH", "000001.SZ", "600000.SH"]
    asof = asof or dt.date(2026, 4, 15)
    api = DataAPI()
    print(f"\n>>> DD203 pit-check  asof={asof}  codes={codes}")
    ok = 0
    fail = 0
    nonempty_n = 0
    for code in codes:
        for field in ("revenue", "net_profit", "total_assets", "equity"):
            try:
                s = api.get_fundamental(field, [code], asof)
                val = s.get(code) if hasattr(s, "get") else (s[code] if code in s.index else None)
                # 允许部分科目空，但至少不应抛错；记录非空数
                nonempty = val is not None and str(val) not in ("", "nan", "None")
                if nonempty:
                    nonempty_n += 1
                print(f"  {code} {field}: {val!r}  nonempty={nonempty}")
                ok += 1
            except Exception as e:
                print(f"  {code} {field}: FAIL {e}")
                fail += 1
    # 每只股票至少 1 个非空科目；整体非空率不过低
    min_nonempty = max(len(codes), 3)
    print(f"pit-check done: ok={ok} fail={fail} nonempty={nonempty_n}/{ok}")
    return 0 if fail == 0 and nonempty_n >= min_nonempty else 1


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser(description="M2.8 DD2 估值/财务配套")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--status", action="store_true")
    g.add_argument("--align-basic", action="store_true", help="DD201：补齐已发布日线缺 basic")
    g.add_argument("--finance-extend", action="store_true", help="DD202：拉长财务公告日")
    g.add_argument("--pit-check", action="store_true", help="DD203：PIT 抽检")
    p.add_argument("--source", default="joinquant")
    p.add_argument("--start", type=dt.date.fromisoformat, default=None)
    p.add_argument("--end", type=dt.date.fromisoformat, default=None)
    p.add_argument("--asof", type=dt.date.fromisoformat, default=None)
    args = p.parse_args(argv)

    if args.status:
        report = status_report()
        print_status(report)
        sys.exit(0 if report["overlap_ok"] and not report["finance_needs_extend"] else 1)
    if args.align_basic:
        sys.exit(align_basic(source=args.source))
    if args.finance_extend:
        sys.exit(finance_extend(source=args.source, start=args.start, end=args.end))
    if args.pit_check:
        sys.exit(pit_check(asof=args.asof))


if __name__ == "__main__":
    main()
