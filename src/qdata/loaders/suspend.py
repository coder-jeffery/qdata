"""停牌 Loader：Raw suspend → ClickHouse suspend。

亦由 DailyBarLoader 合并进 daily_bar.is_suspended；本表保留明细便于复核。
"""

from __future__ import annotations

import datetime as dt
import logging

import pandas as pd

from qdata.loaders.base import Loader, map_security_id

logger = logging.getLogger(__name__)


class SuspendLoader(Loader):
    table = "suspend"
    depends_on = ("suspend",)

    def date_col(self) -> str:
        return "suspend_date"

    def load(self, trade_date: dt.date) -> int:
        from qdata import db
        from qdata.lake.raw import read_raw_any

        try:
            df, src = read_raw_any("suspend", trade_date)
            logger.info("Raw sources: %s", {"suspend": src})
        except FileNotFoundError:
            logger.info("suspend Raw 缺失 @ %s，写入空日", trade_date)
            df = pd.DataFrame()
        out = self.transform(trade_date, {"suspend": df})
        return db.replace_day(self.table, trade_date, out, date_col=self.date_col())

    def transform(self, trade_date: dt.date, raw: dict[str, pd.DataFrame]) -> pd.DataFrame:
        df = raw.get("suspend")
        if df is None or df.empty:
            return pd.DataFrame()
        if "exchange_code" not in df.columns:
            raise ValueError("suspend 缺少 exchange_code")
        out = df.copy()
        out["suspend_date"] = trade_date
        out = map_security_id(out)
        out["resume_date"] = None
        return out[["security_id", "suspend_date", "resume_date"]].drop_duplicates(
            subset=["security_id", "suspend_date"]
        )


if __name__ == "__main__":
    SuspendLoader.cli()
