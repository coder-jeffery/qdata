"""同步交易日历到 ClickHouse。

优先 BaoStock（免费）；若启用 Tushare 则可用 Tushare trade_cal。

用法：
  python -m qdata.jobs.sync_calendar --start 2024-01-01 --end 2026-12-31
  python -m qdata.jobs.sync_calendar --start 2024-01-01 --end 2026-12-31 --source tushare
"""

from __future__ import annotations

import argparse
import datetime as dt
import logging

import pandas as pd

from qdata.calendar import upsert_calendar

logger = logging.getLogger(__name__)


def sync_from_baostock(start: dt.date, end: dt.date) -> pd.DataFrame:
    import baostock as bs

    lg = bs.login()
    if lg.error_code != "0":
        raise RuntimeError(f"BaoStock login 失败: {lg.error_code} {lg.error_msg}")
    try:
        rs = bs.query_trade_dates(
            start_date=start.isoformat(),
            end_date=end.isoformat(),
        )
        if rs.error_code != "0":
            raise RuntimeError(f"query_trade_dates 失败: {rs.error_code} {rs.error_msg}")
        rows: list[list[str]] = []
        while rs.next():
            rows.append(rs.get_row_data())
        if not rows:
            return pd.DataFrame(columns=["cal_date", "is_open"])
        df = pd.DataFrame(rows, columns=rs.fields)
        # calendar_date, is_trading_day
        date_col = "calendar_date" if "calendar_date" in df.columns else df.columns[0]
        flag_col = "is_trading_day" if "is_trading_day" in df.columns else df.columns[1]
        out = pd.DataFrame({
            "cal_date": pd.to_datetime(df[date_col]).dt.date,
            "is_open": df[flag_col].astype(str).map(lambda x: 1 if x in ("1", "true", "True") else 0),
        })
        return out
    finally:
        bs.logout()


def sync_from_tushare(start: dt.date, end: dt.date) -> pd.DataFrame:
    import tushare as ts

    from qdata.config import settings
    from qdata.fetchers.tushare_fetcher import ensure_tushare_enabled

    ensure_tushare_enabled()
    token = (settings().tushare_token or "").strip()
    if not token:
        raise RuntimeError("未配置 QDATA_TUSHARE_TOKEN")
    pro = ts.pro_api(token)
    df = pro.trade_cal(
        exchange="SSE",
        start_date=start.strftime("%Y%m%d"),
        end_date=end.strftime("%Y%m%d"),
        fields="cal_date,is_open",
    )
    if df is None or df.empty:
        return pd.DataFrame(columns=["cal_date", "is_open"])
    return pd.DataFrame({
        "cal_date": pd.to_datetime(df["cal_date"], format="%Y%m%d").dt.date,
        "is_open": df["is_open"].astype(int),
    })


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser(description="同步 A 股交易日历到 ClickHouse")
    p.add_argument("--start", required=True, type=dt.date.fromisoformat)
    p.add_argument("--end", required=True, type=dt.date.fromisoformat)
    p.add_argument(
        "--source",
        default="baostock",
        choices=("baostock", "tushare"),
        help="日历数据源，默认 baostock",
    )
    args = p.parse_args(argv)
    if args.start > args.end:
        raise SystemExit("--start 不能大于 --end")

    logger.info("同步日历 %s ~ %s via %s", args.start, args.end, args.source)
    if args.source == "baostock":
        df = sync_from_baostock(args.start, args.end)
    else:
        df = sync_from_tushare(args.start, args.end)
    n = upsert_calendar(df)
    open_n = int(df["is_open"].sum()) if not df.empty else 0
    print(f"trade_calendar upsert {n} rows (open_days≈{open_n})")


if __name__ == "__main__":
    main()
