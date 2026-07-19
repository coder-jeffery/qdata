"""每日指标 Loader：daily_basic Raw → ClickHouse daily_basic。"""

from __future__ import annotations

import datetime as dt
import logging

import pandas as pd

from qdata.loaders.base import Loader, map_security_id

logger = logging.getLogger(__name__)


class DailyBasicLoader(Loader):
    table = "daily_basic"
    depends_on = ("daily_basic",)

    def transform(self, trade_date: dt.date, raw: dict[str, pd.DataFrame]) -> pd.DataFrame:
        df = raw["daily_basic"]
        if df is None or df.empty:
            logger.warning("daily_basic Raw 为空 @ %s", trade_date)
            return pd.DataFrame()

        if "exchange_code" not in df.columns:
            raise ValueError("daily_basic 缺少 exchange_code")

        out = df.copy()
        out["trade_date"] = trade_date
        out = map_security_id(out)

        # 各源字段不一，缺列填 NA
        for col in (
            "total_share", "float_share", "total_mv", "circ_mv",
            "turnover_rate", "pe_ttm", "pb",
        ):
            if col not in out.columns:
                out[col] = None

        cols = [
            "trade_date", "security_id",
            "total_share", "float_share", "total_mv", "circ_mv",
            "turnover_rate", "pe_ttm", "pb",
        ]
        return out[cols]


if __name__ == "__main__":
    DailyBasicLoader.cli()
