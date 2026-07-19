"""A2 CLI：研究信号快照。

用法：
  python -m qdata.jobs.build_signal --date 2026-07-15 --factor mom_20 --universe 000905.SH \\
    --top-n 50 --weight-method equal --version 2026-07-15
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import sys

from qdata.apps.signal import build_signal

logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser(description="研究信号台 → Lake signals/")
    p.add_argument("--date", type=dt.date.fromisoformat, required=True)
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
    p.add_argument("--version", default=None)
    p.add_argument("--no-persist", action="store_true")
    args = p.parse_args(argv)

    print(
        f"BUILD_SIGNAL date={args.date} factor={args.factor} "
        f"method={args.weight_method} universe={args.universe}"
    )
    try:
        result = build_signal(
            args.date,
            universe=args.universe,
            factor=args.factor,
            top_n=args.top_n,
            weight_method=args.weight_method,
            industry_level=args.industry_level,
            version=args.version,
            factor_version=args.factor_version,
            persist=not args.no_persist,
        )
    except Exception as e:
        logger.exception("%s", e)
        sys.exit(1)

    print(f"signal_id={result['signal_id']}")
    print(f"n_names={result['meta'].get('n_names')}")
    if result.get("path"):
        print(f"path={result['path']}")
    print(json.dumps(result["meta"], indent=2, ensure_ascii=False, default=str))
    sys.exit(0)


if __name__ == "__main__":
    main()
