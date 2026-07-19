"""日线行情 Loader：A 股规则的核心落点。

转换内容：
1. 行情 + 复权因子按 (exchange_code, trade_date) 合并
2. 涨跌停价预计算（按板块系数 + 当日 ST 状态，用不复权昨收）
3. 停牌与 ST 状态快照到行，回测端免 join
"""

from __future__ import annotations

import datetime as dt
import logging

import pandas as pd

from qdata import db
from qdata.constants import board_of, limit_prices
from qdata.loaders.base import Loader, map_security_id

logger = logging.getLogger(__name__)


class DailyBarLoader(Loader):
    table = "daily_bar"
    depends_on = ("daily_bar", "adj_factor")
    # suspend 缺失时全市场 is_suspended=0；DD1 可后补停牌（DD205）
    optional_depends_on = ("suspend",)

    def transform(self, trade_date: dt.date, raw: dict[str, pd.DataFrame]) -> pd.DataFrame:
        bar = raw["daily_bar"]
        adj = raw["adj_factor"]
        suspend = raw.get("suspend", pd.DataFrame())

        if bar is None or bar.empty or "exchange_code" not in bar.columns:
            raise ValueError(
                f"daily_bar Raw 为空或缺列（{trade_date}）。"
                f"请重新: python -m qdata.loaders.daily_bar --date {trade_date} --fetch\n"
                f"若 fetch 成功 0 行：检查代理/网络，确认日期为交易日。"
            )

        if adj is None or adj.empty or "adj_factor" not in getattr(adj, "columns", []):
            logger.warning(
                "adj_factor Raw 为空或缺列，临时用 adj_factor=1.0（请稍后重拉 adj_factor）"
            )
            adj = pd.DataFrame({
                "exchange_code": bar["exchange_code"],
                "adj_factor": 1.0,
            })
        else:
            adj = adj[["exchange_code", "adj_factor"]].drop_duplicates("exchange_code")

        df = bar.merge(adj, on="exchange_code", how="left")
        missing_mask = df["adj_factor"].isna()
        if missing_mask.any():
            n = int(missing_mask.sum())
            logger.warning("有 %s 只股票缺复权因子，已填 1.0", n)
            df.loc[missing_mask, "adj_factor"] = 1.0

        suspended = (
            set(suspend["exchange_code"])
            if suspend is not None and not suspend.empty and "exchange_code" in suspend.columns
            else set()
        )
        df["is_suspended"] = df["exchange_code"].isin(suspended).astype("uint8")

        df["is_st"] = self._st_flags(trade_date, df["exchange_code"])

        boards = df["exchange_code"].map(board_of)
        limits = [
            limit_prices(pc, b, bool(st))
            for pc, b, st in zip(df["pre_close"], boards, df["is_st"])
        ]
        df["up_limit"] = [u for u, _ in limits]
        df["down_limit"] = [d for _, d in limits]

        df["trade_date"] = trade_date
        # 跨源补洞时允许少量退市/未入主数据代码丢弃，避免整日发布失败
        df = map_security_id(df, drop_missing=True)
        cols = [
            "trade_date", "security_id", "open", "high", "low", "close", "pre_close",
            "volume", "amount", "adj_factor", "up_limit", "down_limit", "is_suspended", "is_st",
        ]
        return df[cols]

    def _st_flags(self, trade_date: dt.date, codes: pd.Series) -> pd.Series:
        """当日 ST 状态：security_master 中该日有效行名称含 ST 即为真。"""
        master = db.query_df(
            """
            SELECT exchange_code, name FROM security_master
            WHERE valid_from <= %(d)s AND valid_to > %(d)s
            """,
            {"d": trade_date},
        )
        if master.empty or "name" not in master.columns:
            return pd.Series(0, index=codes.index, dtype="uint8")
        st_codes = set(master[master["name"].str.contains("ST", na=False)]["exchange_code"])
        return codes.isin(st_codes).astype("uint8")


if __name__ == "__main__":
    DailyBarLoader.cli()
