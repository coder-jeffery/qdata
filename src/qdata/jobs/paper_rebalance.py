"""A3 CLI：Paper 调仓工作流。

用法：
  python -m qdata.jobs.paper_rebalance --signal data/data-lake/signals/2026-07-15/.../
  python -m qdata.jobs.paper_rebalance --date 2026-07-15 --factor mom_20 --universe 000905.SH --top-n 50 --cash 1000000

  # A308：实验最优 cell → 信号 → Paper（显式开关）
  python -m qdata.jobs.paper_rebalance --from-experiment exp_xxx --date 2026-07-15 --cash 1000000
  python -m qdata.jobs.paper_rebalance --from-experiment exp_xxx --rank-by sharpe
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import sys

from qdata.apps.paper_flow import run_paper_from_experiment, run_paper_rebalance

logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser(description="信号 → Paper 调仓 → Lake paper_sessions/")
    p.add_argument("--signal", default=None, help="信号目录路径")
    p.add_argument("--date", type=dt.date.fromisoformat, default=None)
    p.add_argument("--factor", default=None)
    p.add_argument("--universe", default="000905.SH")
    p.add_argument("--top-n", type=int, default=50)
    p.add_argument(
        "--weight-method",
        default="equal",
        choices=("equal", "factor_rank", "industry_neutral"),
    )
    p.add_argument("--industry-level", default="sw_l1", choices=("sw_l1", "sw_l2"))
    p.add_argument("--version", default=None)
    p.add_argument("--cash", type=float, default=None)
    p.add_argument("--session-id", default=None)
    p.add_argument("--no-persist", action="store_true")
    # A308
    p.add_argument(
        "--from-experiment",
        default=None,
        metavar="EXP_ID",
        help="A308：用实验最优 cell 出信号并调仓（显式开关，默认关闭）",
    )
    p.add_argument(
        "--rank-by",
        default="sharpe",
        help="选优指标（默认 sharpe；需存在于 summary 列）",
    )
    args = p.parse_args(argv)

    if args.from_experiment:
        print(
            f"PAPER_FROM_EXPERIMENT exp={args.from_experiment} "
            f"rank_by={args.rank_by} asof={args.date or 'spec.end'} cash={args.cash}"
        )
        try:
            result = run_paper_from_experiment(
                args.from_experiment,
                asof=args.date,
                rank_by=args.rank_by,
                cash=args.cash,
                version=args.version,
                session_id=args.session_id,
                persist=not args.no_persist,
            )
        except Exception as e:
            logger.exception("%s", e)
            sys.exit(1)

        cell = result.get("selected_cell") or {}
        print(
            f"selected factor={cell.get('factor')} method={cell.get('weight_method')} "
            f"{args.rank_by}={cell.get('rank_value')}"
        )
        print(f"session_id={result['session_id']}")
        print(f"n_filled={result['meta'].get('n_filled')} n_rejected={result['meta'].get('n_rejected')}")
        if result.get("path"):
            print(f"path={result['path']}")
        print(json.dumps(result["account"], indent=2, ensure_ascii=False, default=str))
        fe = (result["meta"] or {}).get("from_experiment")
        if fe:
            print(json.dumps(fe, indent=2, ensure_ascii=False, default=str))
        sys.exit(0)

    if not args.signal and (args.date is None or args.factor is None):
        raise SystemExit("需 --signal PATH、(--date + --factor)、或 --from-experiment EXP_ID")

    print(f"PAPER_REBALANCE signal={args.signal or 'inline'} cash={args.cash}")
    try:
        result = run_paper_rebalance(
            signal_path=args.signal,
            date=args.date,
            factor=args.factor,
            universe=args.universe,
            top_n=args.top_n,
            weight_method=args.weight_method,
            industry_level=args.industry_level,
            version=args.version,
            cash=args.cash,
            session_id=args.session_id,
            persist=not args.no_persist,
        )
    except Exception as e:
        logger.exception("%s", e)
        sys.exit(1)

    print(f"session_id={result['session_id']}")
    print(f"n_filled={result['meta'].get('n_filled')} n_rejected={result['meta'].get('n_rejected')}")
    if result.get("path"):
        print(f"path={result['path']}")
    print(json.dumps(result["account"], indent=2, ensure_ascii=False, default=str))
    sys.exit(0)


if __name__ == "__main__":
    main()
