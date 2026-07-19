"""Loader 抽象基类：Raw 区 → ClickHouse 服务区。

约定：
- 每个 Loader 处理一个目标表，transform 输入为 Raw DataFrame 字典（可依赖多个数据集）。
- load() 按 (table, trade_date) 幂等：先删该日再插入。
- Raw 可来自 akshare / baostock（auto 模式下按候选顺序查找）。
"""

from __future__ import annotations

import abc
import argparse
import datetime as dt
import logging

import pandas as pd

from qdata import db
from qdata.lake.raw import read_raw_any


class Loader(abc.ABC):
    table: str                      # 目标 ClickHouse 表
    depends_on: tuple[str, ...]     # 依赖的 raw 数据集名（缺失则失败）
    optional_depends_on: tuple[str, ...] = ()  # 缺失则空表继续（如 suspend）

    def load(self, trade_date: dt.date) -> int:
        raw: dict[str, pd.DataFrame] = {}
        used_sources: dict[str, str] = {}
        for ds in self.depends_on:
            try:
                df, src = read_raw_any(ds, trade_date)
                raw[ds] = df
                used_sources[ds] = src
            except FileNotFoundError as e:
                mod = type(self).__module__.rsplit(".", 1)[-1]
                raise FileNotFoundError(
                    f"{e}\n"
                    f"请先拉取: python -m qdata.fetchers --date {trade_date} "
                    f"--dataset {','.join(self.depends_on)}\n"
                    f"或: python -m qdata.loaders.{mod} --date {trade_date} --fetch"
                ) from e
        for ds in self.optional_depends_on:
            try:
                df, src = read_raw_any(ds, trade_date)
                raw[ds] = df
                used_sources[ds] = src
            except FileNotFoundError:
                logging.getLogger(__name__).warning(
                    "可选 Raw 缺失，按空表继续: %s@%s", ds, trade_date,
                )
                raw[ds] = pd.DataFrame()
        if used_sources:
            logging.getLogger(__name__).info("Raw sources: %s", used_sources)
        df = self.transform(trade_date, raw)
        return db.replace_day(self.table, trade_date, df, date_col=self.date_col())

    def date_col(self) -> str:
        return "trade_date"

    @abc.abstractmethod
    def transform(self, trade_date: dt.date, raw: dict[str, pd.DataFrame]) -> pd.DataFrame:
        """清洗转换：标准化、join、衍生字段计算。输出列与目标表一致。"""

    @classmethod
    def cli(cls) -> None:
        logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
        parser = argparse.ArgumentParser(description=f"Load {cls.table}")
        parser.add_argument("--date", required=True, type=dt.date.fromisoformat)
        parser.add_argument(
            "--fetch",
            action="store_true",
            help="入库前先拉取 depends_on 到 Raw 区",
        )
        parser.add_argument(
            "--source",
            default=None,
            help="覆盖 QDATA_DATA_SOURCE（如 baostock / efinance / mootdx / auto / 逗号链）",
        )
        args = parser.parse_args()
        if args.source:
            from qdata.config import settings

            settings.cache_clear()
            # 运行期覆盖：写入环境变量供 Settings 读取
            import os

            os.environ["QDATA_DATA_SOURCE"] = args.source
            settings.cache_clear()
        if args.fetch:
            from qdata.fetchers.cli import fetch_datasets

            fetch_datasets(cls().depends_on, args.date, source=args.source)
        rows = cls().load(args.date)
        print(f"{cls.table} {args.date}: {rows} rows")


def map_security_id(
    df: pd.DataFrame,
    on: str = "exchange_code",
    *,
    drop_missing: bool = False,
) -> pd.DataFrame:
    """exchange_code → security_id。

    默认映射不到抛错。``drop_missing=True`` 时丢弃无映射行并打 warning
    （跨源补洞时日线可能含已退市/主数据未覆盖代码）。
    """
    master = db.query_df(
        "SELECT DISTINCT exchange_code, security_id FROM security_master"
    )
    out = df.merge(master, on=on, how="left")
    missing = out[out["security_id"].isna()][on].unique()
    if len(missing) > 0:
        msg = (
            f"security_master 缺少映射: {list(missing[:10])} ...共 {len(missing)} 个。\n"
            f"请用与日线相同的数据源重载主数据，例如:\n"
            f"  python -m qdata.loaders.security_master --date <trade_date> --fetch --source joinquant\n"
            f"（MAX_SYMBOLS 联调时须保证 stock_basic 与 daily_bar 同一 universe）"
        )
        if not drop_missing:
            raise ValueError(msg)
        import logging

        logging.getLogger(__name__).warning(
            "丢弃无 security_id 映射 %s 行 / %s 代码: %s",
            int(out["security_id"].isna().sum()),
            len(missing),
            list(missing[:10]),
        )
        out = out.dropna(subset=["security_id"]).copy()
        if out.empty:
            raise ValueError("全部行均无 security_id 映射，无法入库\n" + msg)
    out["security_id"] = out["security_id"].astype("uint32")
    return out
