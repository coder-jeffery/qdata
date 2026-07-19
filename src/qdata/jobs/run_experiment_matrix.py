"""A1 CLI：策略实验矩阵批跑。

用法：
  python -m qdata.jobs.run_experiment_matrix \\
    --start 2026-07-01 --end 2026-07-15 \\
    --universe 000905.SH --factors mom_20,ep --weight-methods equal,industry_neutral \\
    --top-n 50 --version 2026-07-15
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import sys

from qdata.apps.experiment import ExperimentSpec, run_experiment_matrix

logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser(description="策略实验矩阵 → Lake experiments/")
    p.add_argument("--start", type=dt.date.fromisoformat, required=True)
    p.add_argument("--end", type=dt.date.fromisoformat, required=True)
    p.add_argument("--universe", default="000905.SH")
    p.add_argument("--factors", default="mom_20", help="逗号分隔")
    p.add_argument("--weight-methods", default="equal", help="equal,industry_neutral,...")
    p.add_argument("--top-n", type=int, default=50)
    p.add_argument("--version", default=None, help="dataset_version")
    p.add_argument(
        "--execution",
        default="next_open",
        choices=("next_open", "next_close"),
    )
    p.add_argument("--benchmark", default="000905.SH")
    p.add_argument("--no-benchmark", action="store_true")
    p.add_argument("--industry-level", default="sw_l1", choices=("sw_l1", "sw_l2"))
    p.add_argument("--factor-version", default="v1")
    p.add_argument("--initial-cash", type=float, default=100_000_000.0)
    p.add_argument("--no-persist", action="store_true")
    p.add_argument("--no-ch", action="store_true")
    args = p.parse_args(argv)

    if args.start > args.end:
        raise SystemExit("--start 不能大于 --end")

    factors = [x.strip() for x in args.factors.split(",") if x.strip()]
    weight_methods = [x.strip() for x in args.weight_methods.split(",") if x.strip()]

    spec = ExperimentSpec(
        start=args.start,
        end=args.end,
        universe=args.universe,
        factors=factors,
        weight_methods=weight_methods,
        top_n=args.top_n,
        version=args.version,
        execution=args.execution,
        benchmark=None if args.no_benchmark else args.benchmark,
        industry_level=args.industry_level,
        factor_version=args.factor_version,
        initial_cash=args.initial_cash,
        persist=not args.no_persist,
        persist_ch=not args.no_ch,
    )

    print(
        f"EXPERIMENT_MATRIX {args.start}~{args.end} "
        f"factors={factors} methods={weight_methods} universe={args.universe}"
    )
    try:
        result = run_experiment_matrix(spec)
    except Exception as e:
        logger.exception("%s", e)
        sys.exit(1)

    meta = result["meta"]
    print(f"experiment_id={result['experiment_id']}")
    print(f"n_ok={meta.get('n_ok')} n_fail={meta.get('n_fail')}")
    if result.get("path"):
        print(f"path={result['path']}")
    print(json.dumps(result["rows"], indent=2, ensure_ascii=False, default=str))
    sys.exit(0 if meta.get("n_fail", 0) == 0 else 2)


if __name__ == "__main__":
    main()
