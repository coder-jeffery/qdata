"""日频回测 CLI。

用法：
  python -m qdata.jobs.run_backtest \\
    --start 2026-04-01 --end 2026-07-15 \\
    --universe 000905.SH --factor mom_20 --top-n 50 \\
    --version 2026-07-15 --execution next_open
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import sys

from qdata.api.data_api import DataAPI
from qdata.research.backtest import BacktestConfig, BacktestEngine
from qdata.research.backtest.signals import FromRebalanceSpec
from qdata.research.portfolio import RebalanceSpec

logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser(description="日频回测 → Lake backtest/runs")
    p.add_argument("--start", type=dt.date.fromisoformat, required=True)
    p.add_argument("--end", type=dt.date.fromisoformat, required=True)
    p.add_argument("--universe", default="000905.SH")
    p.add_argument("--factor", default="mom_20")
    p.add_argument("--factor-version", default="v1")
    p.add_argument("--top-n", type=int, default=50)
    p.add_argument(
        "--weight-method",
        default="equal",
        choices=("equal", "factor_rank", "industry_neutral"),
    )
    p.add_argument("--industry-level", default="sw_l1", choices=("sw_l1", "sw_l2"))
    p.add_argument("--version", default=None, help="dataset_version / DataAPI as-of")
    p.add_argument(
        "--execution",
        default="next_open",
        choices=("next_open", "next_close"),
    )
    p.add_argument("--initial-cash", type=float, default=100_000_000.0)
    p.add_argument("--benchmark", default="000905.SH")
    p.add_argument("--no-benchmark", action="store_true")
    p.add_argument("--no-persist", action="store_true")
    p.add_argument("--no-ch", action="store_true", help="不写 ClickHouse backtest_* 表")
    p.add_argument("--no-tearsheet", action="store_true")
    p.add_argument("--run-name", default="")
    p.add_argument(
        "--max-adv-participation",
        type=float,
        default=0.0,
        help="单票成交量占比上限（0=不限制），如 0.1=不超过当日 volume 的 10%%",
    )
    args = p.parse_args(argv)

    if args.start > args.end:
        raise SystemExit("--start 不能大于 --end")

    api = DataAPI(version=args.version) if args.version else DataAPI()
    spec = RebalanceSpec(
        universe=args.universe,
        factor=args.factor,
        factor_version=args.factor_version,
        top_n=args.top_n,
        weight_method=args.weight_method,  # type: ignore[arg-type]
        industry_level=args.industry_level,  # type: ignore[arg-type]
    )
    cfg = BacktestConfig(
        start=args.start,
        end=args.end,
        initial_cash=args.initial_cash,
        execution=args.execution,  # type: ignore[arg-type]
        benchmark=None if args.no_benchmark else args.benchmark,
        dataset_version=args.version,
        run_name=args.run_name,
        persist=not args.no_persist,
        persist_ch=not args.no_ch,
        write_tearsheet=not args.no_tearsheet,
        max_adv_participation=args.max_adv_participation,
    )

    print(
        f"RUN_BACKTEST {args.start}~{args.end} universe={args.universe} "
        f"factor={args.factor} top_n={args.top_n} execution={args.execution} "
        f"version={api.version}"
    )
    try:
        signals = FromRebalanceSpec(args.start, args.end, spec=spec, api=api)
        result = BacktestEngine(cfg, api=api).run(signals)
    except Exception as e:
        logger.exception("%s", e)
        sys.exit(1)

    print("metrics:")
    print(json.dumps(result.metrics, indent=2, ensure_ascii=False, default=str))
    run_id = result.meta.get("run_id")
    print(f"run_id={run_id}")
    if cfg.persist:
        from qdata.config import settings

        print(f"path={settings().lake_root / 'backtest' / 'runs' / str(run_id)}")


if __name__ == "__main__":
    main()
