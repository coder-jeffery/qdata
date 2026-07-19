"""实时行情快照 → realtime 分通道（与日线 ETL 分离）。

用法：
  python -m qdata.jobs.realtime_snapshot --source easyquotation
  python -m qdata.jobs.realtime_snapshot --source easyquotation --codes 600000.SH,000001.SZ
"""

from __future__ import annotations

import argparse
import logging
import sys

from qdata.realtime import fetch_and_store, read_latest_snapshot

logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser(description="拉取实时行情并写入 realtime 通道")
    p.add_argument(
        "--source",
        default="easyquotation",
        help="行情源：easyquotation（默认）/ mootdx / miniqmt 等支持 realtime_quote 的源",
    )
    p.add_argument(
        "--codes",
        default=None,
        help="逗号分隔 exchange_code；空=源返回的全量/样本",
    )
    args = p.parse_args(argv)
    codes = None
    if args.codes:
        codes = [x.strip() for x in args.codes.split(",") if x.strip()]
    try:
        df, path = fetch_and_store(source=args.source, codes=codes)
    except Exception as e:
        logger.exception("%s", e)
        sys.exit(1)
    print(f"realtime rows={len(df)} path={path}")
    if not df.empty:
        print(df.head(5).to_string(index=False))
    latest = read_latest_snapshot(args.source)
    print(f"latest_snapshot rows={len(latest)}")


if __name__ == "__main__":
    main()
