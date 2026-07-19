"""证券主数据 Loader：stock_basic 快照 → security_master。

首次跑日线前必须先入库主数据，否则 exchange_code → security_id 映射会失败。
本地调试将当日快照整表替换为当前有效行（valid_to=2099-12-31）。
"""

from __future__ import annotations

import datetime as dt

import pandas as pd

from qdata import db
from qdata.constants import board_of
from qdata.lake.raw import read_raw_any
from qdata.loaders.base import Loader


class SecurityMasterLoader(Loader):
    table = "security_master"
    depends_on = ("stock_basic",)

    def load(self, trade_date: dt.date) -> int:
        """主数据按快照整表幂等重写（非按日分区删除）。"""
        raw: dict[str, pd.DataFrame] = {}
        for ds in self.depends_on:
            try:
                raw[ds], src = read_raw_any(ds, trade_date)
                print(f"security_master raw source={src}")
            except FileNotFoundError as e:
                raise FileNotFoundError(
                    f"{e}\n"
                    f"请先拉取: python -m qdata.fetchers --date {trade_date} --dataset stock_basic\n"
                    f"或: python -m qdata.loaders.security_master --date {trade_date} --fetch"
                ) from e
        df = self.transform(trade_date, raw)
        ch = db.client()
        ch.command(f"TRUNCATE TABLE {self.table}")
        return db.insert_df(self.table, df)

    def transform(self, trade_date: dt.date, raw: dict[str, pd.DataFrame]) -> pd.DataFrame:
        df = raw["stock_basic"].copy()
        if df.empty:
            return pd.DataFrame()

        # 复用已有 security_id，新代码递增分配，保证跨日稳定
        existing = db.query_df("SELECT DISTINCT exchange_code, security_id FROM security_master")
        id_map = (
            dict(zip(existing["exchange_code"], existing["security_id"].astype(int)))
            if not existing.empty
            else {}
        )
        next_id = (max(id_map.values()) + 1) if id_map else 1

        security_ids: list[int] = []
        for code in df["exchange_code"]:
            if code not in id_map:
                id_map[code] = next_id
                next_id += 1
            security_ids.append(id_map[code])

        if "list_date" in df.columns:
            list_date = pd.to_datetime(df["list_date"], errors="coerce")
        else:
            list_date = pd.Series([pd.NaT] * len(df))
        if "delist_date" in df.columns:
            delist = pd.to_datetime(df["delist_date"], errors="coerce")
        else:
            delist = pd.Series([pd.NaT] * len(df))
        name_col = "name" if "name" in df.columns else "symbol"
        default_list = dt.date(1990, 1, 1)

        out = pd.DataFrame({
            "security_id": pd.Series(security_ids, dtype="uint32"),
            "exchange_code": df["exchange_code"].astype(str),
            "name": df[name_col].astype(str),
            "list_date": list_date.dt.date.fillna(default_list),
            "delist_date": delist.dt.date,
            "board": [board_of(c).value for c in df["exchange_code"]],
            "valid_from": list_date.dt.date.fillna(default_list),
            "valid_to": dt.date(2099, 12, 31),
        })
        out["delist_date"] = out["delist_date"].where(pd.notna(out["delist_date"]), None)
        return out


if __name__ == "__main__":
    SecurityMasterLoader.cli()
