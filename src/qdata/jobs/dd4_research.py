"""M2.8 DD4 — 研究验收重跑编排。

在「已发布日线 + 可用因子」最长连续窗口上：
  实验矩阵 → 信号 → Paper 调仓/盯市 → 个股研判抽检 → 验收记录。

用法：
  python -m qdata.jobs.dd4_research --status
  python -m qdata.jobs.dd4_research --accept          # 一键验收冒烟
  python -m qdata.jobs.dd4_research --matrix-only
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import sys
from pathlib import Path
from typing import Any

from qdata.apps.experiment import ExperimentSpec, list_experiments, run_experiment_matrix
from qdata.apps.paper_flow import mark_session_eod, run_paper_rebalance
from qdata.apps.paper_store import list_sessions
from qdata.apps.signal import build_signal, list_signals
from qdata.config import settings
from qdata.prod import prod_min_universe
from qdata.release import check_version_continuity
from qdata.research.judgment import judge_stock

logger = logging.getLogger(__name__)

# Q4/Q1 暂缓后：因子可用的最长连续段（与 DD3 结果对齐）
DEFAULT_START = dt.date(2026, 4, 1)
DEFAULT_END = dt.date(2026, 7, 15)
DEFAULT_FACTORS = ("mom_20", "vol_20")
DEFAULT_METHODS = ("equal", "industry_neutral")


def _published_days(start: dt.date, end: dt.date) -> list[str]:
    cont = check_version_continuity(
        start, end, "daily_bar", min_rows=prod_min_universe()
    )
    return list(cont.get("published") or [])


def status_report(
    *,
    start: dt.date = DEFAULT_START,
    end: dt.date = DEFAULT_END,
) -> dict[str, Any]:
    pub = _published_days(start, end)
    exps = list_experiments(limit=10)
    sigs = list_signals(limit=10)
    papers = list_sessions(limit=5)
    return {
        "window": {"start": start.isoformat(), "end": end.isoformat()},
        "published_days": len(pub),
        "continuity_ok": len(pub) > 0 and check_version_continuity(
            start, end, "daily_bar", min_rows=prod_min_universe()
        ).get("ok"),
        "n_experiments": len(exps),
        "latest_experiment": (exps[0].get("experiment_id") if exps else None),
        "n_signals": len(sigs),
        "latest_signal": (sigs[0].get("signal_id") if sigs else None),
        "n_paper_sessions": len(papers),
        "latest_paper": (papers[0].get("session_id") if papers else None),
        "note": "窗口为 Q4/Q1 暂缓后因子可用段；非完整 ≥6 个月样本",
    }


def print_status(r: dict[str, Any]) -> None:
    print("=" * 60)
    print(f"DD4 RESEARCH STATUS  {r['window']['start']} ~ {r['window']['end']}")
    print("=" * 60)
    print(
        f"published_days={r['published_days']} continuity_ok={r['continuity_ok']}\n"
        f"experiments={r['n_experiments']} latest={r['latest_experiment']}\n"
        f"signals={r['n_signals']} latest={r['latest_signal']}\n"
        f"paper={r['n_paper_sessions']} latest={r['latest_paper']}\n"
        f"note: {r['note']}"
    )


def run_matrix(
    *,
    start: dt.date = DEFAULT_START,
    end: dt.date = DEFAULT_END,
    factors: tuple[str, ...] = DEFAULT_FACTORS,
    weight_methods: tuple[str, ...] = DEFAULT_METHODS,
    universe: str = "000905.SH",
    top_n: int = 50,
) -> dict[str, Any]:
    print(
        f"\n>>> DD401 matrix  {start}~{end}  factors={factors} "
        f"methods={weight_methods} universe={universe}"
    )
    spec = ExperimentSpec(
        start=start,
        end=end,
        universe=universe,
        factors=list(factors),
        weight_methods=list(weight_methods),
        top_n=top_n,
        version=None,
        execution="next_open",
        benchmark=universe,
        industry_level="sw_l1",
        factor_version="v1",
        initial_cash=100_000_000.0,
        persist=True,
        persist_ch=True,
    )
    result = run_experiment_matrix(spec)
    meta = result.get("meta") or {}
    print(
        f"experiment_id={result.get('experiment_id')} "
        f"n_ok={meta.get('n_ok')} n_fail={meta.get('n_fail')}"
    )
    return result


def run_signal_paper(
    *,
    asof: dt.date = DEFAULT_END,
    factor: str = "mom_20",
    universe: str = "000905.SH",
    top_n: int = 50,
    cash: float = 1_000_000.0,
) -> dict[str, Any]:
    print(f"\n>>> DD403 signal  asof={asof} factor={factor}")
    sig = build_signal(
        asof,
        universe=universe,
        factor=factor,
        top_n=top_n,
        weight_method="equal",
        industry_level="sw_l1",
        version=None,
        factor_version="v1",
        persist=True,
    )
    print(f"signal_id={sig.get('signal_id')} n_names={sig.get('meta', {}).get('n_names')}")

    print(f"\n>>> DD404 paper_rebalance + mark  cash={cash}")
    paper = run_paper_rebalance(
        date=asof,
        factor=factor,
        universe=universe,
        top_n=top_n,
        weight_method="equal",
        industry_level="sw_l1",
        version=None,
        cash=cash,
        persist=True,
    )
    sid = paper.get("session_id")
    print(f"session_id={sid}")
    mark = mark_session_eod(str(sid), mark_date=asof, persist=True) if sid else {}
    print(
        f"mark total_asset={mark.get('total_asset')} "
        f"pnl_vs_initial={mark.get('pnl_vs_initial')}"
    )
    return {"signal": sig, "paper": paper, "mark": mark}


def run_judgment(
    *,
    asof: dt.date = DEFAULT_END,
    codes: list[str] | None = None,
) -> list[dict[str, Any]]:
    codes = codes or ["600519.SH", "000001.SZ", "600000.SH"]
    print(f"\n>>> DD405 judgment  asof={asof} codes={codes}")
    out: list[dict[str, Any]] = []
    for code in codes:
        try:
            card = judge_stock(code, asof)
            row = {
                "code": code,
                "stance": getattr(card, "stance", None) or (card.get("stance") if isinstance(card, dict) else None),
                "composite": getattr(card, "composite", None)
                if not isinstance(card, dict)
                else card.get("composite"),
                "ok": True,
            }
            print(f"  {code}: stance={row['stance']} composite={row['composite']}")
        except Exception as e:
            row = {"code": code, "ok": False, "error": str(e)[:200]}
            print(f"  {code}: FAIL {e}")
        out.append(row)
    return out


def _write_acceptance(payload: dict[str, Any]) -> Path:
    root = Path(settings().lake_root) / "dd4_acceptance"
    root.mkdir(parents=True, exist_ok=True)
    ts = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = root / f"accept_{ts}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    # 同步一份到 docs 附录友好路径
    docs = Path(__file__).resolve().parents[3] / "docs" / "DD4-研究验收记录.md"
    lines = [
        "# DD4 研究验收记录",
        "",
        f"> 生成于 {payload.get('finished_at')}（UTC）",
        "",
        "## 窗口",
        "",
        f"- start: `{payload['window']['start']}`",
        f"- end: `{payload['window']['end']}`",
        f"- 说明: {payload.get('note', '')}",
        "",
        "## 结果摘要",
        "",
        f"- experiment_id: `{payload.get('experiment_id')}`",
        f"- n_ok / n_fail: `{payload.get('n_ok')}` / `{payload.get('n_fail')}`",
        f"- signal_id: `{payload.get('signal_id')}`",
        f"- paper session: `{payload.get('session_id')}`",
        f"- mark pnl_vs_initial: `{payload.get('mark_pnl')}`",
        f"- judgment ok: `{payload.get('judgment_ok')}`",
        f"- 详细 JSON: `{path}`",
        "",
        "## 判定",
        "",
        f"- **{'PASS' if payload.get('pass') else 'FAIL'}**",
        "",
    ]
    docs.write_text("\n".join(lines), encoding="utf-8")
    return path


def accept(
    *,
    start: dt.date = DEFAULT_START,
    end: dt.date = DEFAULT_END,
    skip_matrix: bool = False,
) -> int:
    print_status(status_report(start=start, end=end))
    note = "Q4/Q1 暂缓；窗口为因子可用连续段（短于 6 个月）"
    exp_id = None
    n_ok = n_fail = 0
    rows: list[Any] = []
    if not skip_matrix:
        matrix = run_matrix(start=start, end=end)
        exp_id = matrix.get("experiment_id")
        meta = matrix.get("meta") or {}
        n_ok = int(meta.get("n_ok") or 0)
        n_fail = int(meta.get("n_fail") or 0)
        rows = matrix.get("rows") or []
        # 指标非全空
        sharpes = [r.get("sharpe") for r in rows if isinstance(r, dict)]
        if sharpes and all(s is None for s in sharpes):
            print("WARN: 全部 sharpe 为空")
    else:
        # 引用最近一次矩阵结果（本窗口刚跑过 --matrix-only 时）
        exps = list_experiments(limit=1)
        if exps:
            exp_id = exps[0].get("experiment_id")
            n_ok = int(exps[0].get("n_ok") or 0)
            n_fail = int(exps[0].get("n_fail") or 0)
            print(
                f"(skip-matrix) attach latest experiment_id={exp_id} "
                f"n_ok={n_ok} n_fail={n_fail}"
            )

    sp = run_signal_paper(asof=end)
    judgments = run_judgment(asof=end)
    j_ok = sum(1 for j in judgments if j.get("ok"))

    mark = sp.get("mark") or {}
    payload = {
        "window": {"start": start.isoformat(), "end": end.isoformat()},
        "note": note,
        "experiment_id": exp_id,
        "n_ok": n_ok,
        "n_fail": n_fail,
        "matrix_rows": rows,
        "signal_id": (sp.get("signal") or {}).get("signal_id"),
        "session_id": (sp.get("paper") or {}).get("session_id"),
        "mark_pnl": mark.get("pnl_vs_initial"),
        "mark_total_asset": mark.get("total_asset"),
        "judgment_ok": j_ok,
        "judgments": judgments,
        "finished_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "pass": (skip_matrix or (n_ok > 0 and n_fail == 0))
        and bool((sp.get("paper") or {}).get("session_id"))
        and j_ok >= 2,
    }
    path = _write_acceptance(payload)
    print(f"\nDD406 acceptance -> {path}")
    print(f"DD4 ACCEPTANCE {'PASS' if payload['pass'] else 'FAIL'}")
    return 0 if payload["pass"] else 1


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser(description="M2.8 DD4 研究验收重跑")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--status", action="store_true")
    g.add_argument("--accept", action="store_true", help="矩阵+信号+Paper+研判+落盘")
    g.add_argument("--matrix-only", action="store_true")
    g.add_argument("--signal-paper-only", action="store_true")
    p.add_argument("--start", type=dt.date.fromisoformat, default=DEFAULT_START)
    p.add_argument("--end", type=dt.date.fromisoformat, default=DEFAULT_END)
    p.add_argument("--skip-matrix", action="store_true", help="--accept 时跳过矩阵")
    args = p.parse_args(argv)

    if args.status:
        print_status(status_report(start=args.start, end=args.end))
        sys.exit(0)
    if args.matrix_only:
        r = run_matrix(start=args.start, end=args.end)
        sys.exit(0 if int((r.get("meta") or {}).get("n_fail") or 0) == 0 else 1)
    if args.signal_paper_only:
        run_signal_paper(asof=args.end)
        sys.exit(0)
    if args.accept:
        sys.exit(accept(start=args.start, end=args.end, skip_matrix=args.skip_matrix))


if __name__ == "__main__":
    main()
