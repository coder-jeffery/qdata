"""M2.8 DD3 — 因子重算与对齐。

对「已发布 daily_bar」交易日重算六种子因子，并做覆盖门禁 / 冒烟。

用法：
  python -m qdata.jobs.dd3_factors --status
  python -m qdata.jobs.dd3_factors --compute          # 仅已发布日
  python -m qdata.jobs.dd3_factors --coverage-gate    # 末日覆盖门禁
  python -m qdata.jobs.dd3_factors --smoke-ic         # 短窗口 IC 冒烟
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import sys
from pathlib import Path
from typing import Any

from qdata import db
from qdata.config import settings
from qdata.factors import (
    DEFAULT_FACTOR_VERSION,
    compute_factors_for_day,
    list_seed_factors,
)
from qdata.prod import prod_min_universe
from qdata.release import check_version_continuity

logger = logging.getLogger(__name__)

DD_START = dt.date(2025, 7, 1)
DD_END = dt.date(2026, 7, 15)
SEED = list_seed_factors()


def _published_days(
    start: dt.date = DD_START,
    end: dt.date = DD_END,
    *,
    min_rows: int | None = None,
) -> list[dt.date]:
    min_n = min_rows if min_rows is not None else prod_min_universe()
    cont = check_version_continuity(start, end, "daily_bar", min_rows=min_n)
    out: list[dt.date] = []
    for s in cont.get("published") or []:
        try:
            out.append(dt.date.fromisoformat(str(s)[:10]))
        except ValueError:
            continue
    return sorted(out)


def _factor_day_counts(version: str = DEFAULT_FACTOR_VERSION) -> dict[str, dict[str, Any]]:
    try:
        df = db.query_df(
            """
            SELECT factor_name, min(trade_date) AS mn, max(trade_date) AS mx,
                   uniqExact(trade_date) AS days, count() AS n
            FROM factor_value
            WHERE version = %(v)s
            GROUP BY factor_name
            ORDER BY factor_name
            """,
            {"v": version},
        )
    except Exception as e:
        return {"_error": {"message": str(e)[:240]}}
    out: dict[str, dict[str, Any]] = {}
    if df is None or df.empty:
        return out
    for _, r in df.iterrows():
        out[str(r["factor_name"])] = {
            "min": str(r["mn"])[:10] if r["mn"] is not None else None,
            "max": str(r["mx"])[:10] if r["mx"] is not None else None,
            "days": int(r["days"] or 0),
            "rows": int(r["n"] or 0),
        }
    return out


def _factor_days_set(factor: str, version: str = DEFAULT_FACTOR_VERSION) -> set[str]:
    try:
        df = db.query_df(
            """
            SELECT DISTINCT trade_date AS d
            FROM factor_value
            WHERE factor_name = %(f)s AND version = %(v)s
            """,
            {"f": factor, "v": version},
        )
    except Exception:
        return set()
    if df is None or df.empty:
        return set()
    return {str(x)[:10] for x in df["d"].tolist()}


def status_report(
    *,
    version: str = DEFAULT_FACTOR_VERSION,
    min_rows: int | None = None,
) -> dict[str, Any]:
    pub = _published_days(min_rows=min_rows)
    pub_s = {d.isoformat() for d in pub}
    counts = _factor_day_counts(version)
    per: dict[str, Any] = {}
    worst_missing = 0
    for fac in SEED:
        have = _factor_days_set(fac, version) & pub_s
        missing = sorted(pub_s - have)
        worst_missing = max(worst_missing, len(missing))
        meta = counts.get(fac) or {}
        per[fac] = {
            "published_overlap": len(have),
            "missing_on_published": len(missing),
            "missing_head": missing[:8],
            "stored_days": meta.get("days", 0),
            "stored_range": f"{meta.get('min')}~{meta.get('max')}",
            "rows": meta.get("rows", 0),
        }
    ok = bool(pub) and all(per[f]["missing_on_published"] == 0 for f in SEED)
    return {
        "target": {"start": DD_START.isoformat(), "end": DD_END.isoformat()},
        "version": version,
        "seeds": SEED,
        "published_bar_days": len(pub),
        "factors": per,
        "aligned_ok": ok,
        "worst_missing": worst_missing,
        "next_compute_days": len(pub),
    }


def print_status(report: dict[str, Any]) -> None:
    print("=" * 60)
    print(f"DD3 FACTORS STATUS  {report['target']['start']} ~ {report['target']['end']}")
    print(f"version={report['version']}  published_bar={report['published_bar_days']}  aligned_ok={report['aligned_ok']}")
    print("=" * 60)
    for fac, m in (report.get("factors") or {}).items():
        flag = "OK" if m["missing_on_published"] == 0 else "GAP"
        print(
            f"[{flag}] {fac:8} overlap={m['published_overlap']}/{report['published_bar_days']}  "
            f"missing={m['missing_on_published']}  stored={m['stored_range']} ({m['stored_days']}d)"
        )
        if m["missing_head"]:
            print(f"         missing_head: {', '.join(m['missing_head'])}")


def compute_published(
    *,
    version: str = DEFAULT_FACTOR_VERSION,
    factors: list[str] | None = None,
    skip_existing: bool = True,
) -> int:
    """对已发布 daily_bar 日重算因子（跳过日历空洞）。"""
    facs = factors or SEED
    pub = _published_days()
    if not pub:
        print("无已发布 daily_bar，请先完成 DD1 段回填")
        return 1
    report = status_report(version=version)
    print_status(report)
    todo: list[dt.date] = []
    if skip_existing:
        pub_s = {d.isoformat() for d in pub}
        missing_union: set[str] = set()
        for fac in facs:
            have = _factor_days_set(fac, version) & pub_s
            missing_union |= pub_s - have
        todo = sorted(dt.date.fromisoformat(x) for x in missing_union)
    else:
        todo = list(pub)

    print(f"\n>>> DD301 compute  days={len(todo)}/{len(pub)}  factors={facs}  version={version}")
    if not todo:
        print("无需重算：已发布日均已有因子")
        return 0

    ok = 0
    fail = 0
    for i, d in enumerate(todo, 1):
        try:
            counts = compute_factors_for_day(d, factors=facs, version=version)
            print(f"[{i}/{len(todo)}] {d}: {counts}")
            ok += 1
        except Exception as e:
            logger.exception("compute fail %s", d)
            print(f"[{i}/{len(todo)}] {d}: FAIL {e}")
            fail += 1
    # 落盘简易 meta（DD303）
    meta_root = Path(settings().lake_root) / "factor_runs"
    meta_root.mkdir(parents=True, exist_ok=True)
    meta = {
        "job": "dd3_factors",
        "version": version,
        "factors": facs,
        "computed_days": ok,
        "failed_days": fail,
        "published_bar_days": len(pub),
        "range": {"start": DD_START.isoformat(), "end": DD_END.isoformat()},
        "finished_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    path = meta_root / f"dd3_{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"meta -> {path}")
    print_status(status_report(version=version))
    return 0 if fail == 0 else 1


def coverage_gate(
    *,
    date: dt.date | None = None,
    min_coverage: float = 0.9,
) -> int:
    """DD302：对指定日（默认最新已发布）跑因子覆盖门禁。"""
    from qdata.apps.factor_monitor import monitor_factor_day

    pub = _published_days()
    if not pub:
        print("无已发布日")
        return 1
    d = date or pub[-1]
    print(f"\n>>> DD302 coverage-gate  date={d}  min_coverage={min_coverage}")
    result = monitor_factor_day(d, factors=SEED, min_coverage=min_coverage)
    alerts = result.get("alerts") or []
    cov = result.get("coverage")
    if cov is not None and hasattr(cov, "to_string"):
        print(cov.to_string(index=False))
    print(f"n_alerts={result.get('n_alerts', len(alerts))} universe={result.get('universe_size')}")
    for a in alerts[:12]:
        print(f"  ALERT: {a}")
    return 0 if not alerts else 1


def smoke_ic(
    *,
    start: dt.date | None = None,
    end: dt.date | None = None,
) -> int:
    """DD305：在已发布区间末若干日做覆盖冒烟（能出数即可；跳过日历空洞）。"""
    from qdata.apps.factor_monitor import monitor_factor_day

    pub = _published_days()
    if len(pub) < 5:
        print("已发布日不足，跳过 IC 冒烟")
        return 1
    end = end or pub[-1]
    window = [d for d in pub if d <= end][-30:]
    if start is not None:
        window = [d for d in window if d >= start]
    print(f"\n>>> DD305 smoke-ic  {window[0]} ~ {window[-1]}  days={len(window)}")
    ok = 0
    fail = 0
    for d in window:
        try:
            r = monitor_factor_day(d, factors=SEED[:2], min_coverage=0.5)
            n_alerts = int(r.get("n_alerts") or 0)
            print(f"  {d}: universe={r.get('universe_size')} alerts={n_alerts}")
            ok += 1
        except Exception as e:
            print(f"  {d}: FAIL {e}")
            fail += 1
    print(f"smoke-ic finished ok={ok} fail={fail}")
    return 0 if fail == 0 else 1


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser(description="M2.8 DD3 因子重算与对齐")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--status", action="store_true")
    g.add_argument("--compute", action="store_true", help="DD301：对已发布日重算种子因子")
    g.add_argument("--coverage-gate", action="store_true", help="DD302：覆盖门禁")
    g.add_argument("--smoke-ic", action="store_true", help="DD305：短窗口冒烟")
    p.add_argument("--version", default=DEFAULT_FACTOR_VERSION)
    p.add_argument("--factors", default=None, help="逗号分隔，默认全部种子")
    p.add_argument("--date", type=dt.date.fromisoformat, default=None)
    p.add_argument("--no-skip-existing", action="store_true")
    p.add_argument("--min-coverage", type=float, default=0.9)
    args = p.parse_args(argv)

    factors = None
    if args.factors:
        factors = [x.strip() for x in args.factors.split(",") if x.strip()]

    if args.status:
        r = status_report(version=args.version)
        print_status(r)
        sys.exit(0 if r["aligned_ok"] else 1)
    if args.compute:
        sys.exit(
            compute_published(
                version=args.version,
                factors=factors,
                skip_existing=not args.no_skip_existing,
            )
        )
    if args.coverage_gate:
        sys.exit(coverage_gate(date=args.date, min_coverage=args.min_coverage))
    if args.smoke_ic:
        sys.exit(smoke_ic())


if __name__ == "__main__":
    main()
