"""财务报表 Loader：Point-in-Time 建模。

关键约定：
- 按公告日（ann_date）增量拉取与写入，而不是按报告期。
- 更正公告（update_flag=1）追加新行，绝不覆盖首次披露的行——
  回测在 T 日只能看到 T 日之前公告的版本。
- 科目一律放入 fields Map，schema 演进无需改表。
- income / balancesheet / cashflow 同日一次入库（避免 replace_day 互删）。
"""

from __future__ import annotations

import datetime as dt
import logging

import pandas as pd

from qdata.loaders.base import Loader, map_security_id

logger = logging.getLogger(__name__)

# 入库的科目白名单：源列名 → 标准科目名
_INCOME_FIELDS = {
    "revenue": "revenue",
    "n_income_attr_p": "net_profit",
    "basic_eps": "eps_basic",
    "operate_profit": "op_profit",
}

_BALANCE_FIELDS = {
    "total_assets": "total_assets",
    "total_liab": "total_liab",
    "total_hldr_eqy_exc_min_int": "equity",
}

_CASHFLOW_FIELDS = {
    "n_cashflow_act": "cfo",
    "n_cashflow_inv_act": "cfi",
    "n_cash_flows_fnc_act": "cff",
}

_STMT_SPECS: dict[str, tuple[str, dict[str, str]]] = {
    # raw dataset → (stmt_type, field map)
    "income": ("income", _INCOME_FIELDS),
    "balancesheet": ("balance", _BALANCE_FIELDS),
    "cashflow": ("cashflow", _CASHFLOW_FIELDS),
}


def pick_pit_row(rows: pd.DataFrame, as_of: dt.date) -> pd.Series | None:
    """纯函数：在已过滤 ``ann_date <= as_of`` 的行中选 PIT 可见行。

    规则与 DataAPI.get_fundamental 一致：
      ORDER BY report_date DESC, ann_date DESC → 取第一条。
    输入需含 ann_date / report_date；可选 value 列供调用方读取。
    """
    if rows is None or rows.empty:
        return None
    df = rows.copy()
    df["ann_date"] = pd.to_datetime(df["ann_date"], errors="coerce").dt.date
    df["report_date"] = pd.to_datetime(df["report_date"], errors="coerce").dt.date
    df = df.dropna(subset=["ann_date", "report_date"])
    df = df[df["ann_date"] <= as_of]
    if df.empty:
        return None
    df = df.sort_values(
        ["report_date", "ann_date"],
        ascending=[False, False],
    )
    return df.iloc[0]


class FinStatementLoader(Loader):
    table = "fin_statement"
    # income 必拉；balancesheet/cashflow 缺失时按空表处理（见 load）
    depends_on = ("income", "balancesheet", "cashflow")

    def date_col(self) -> str:
        return "ann_date"

    def load(self, trade_date: dt.date) -> int:
        from qdata import db
        from qdata.lake.raw import read_raw_any

        raw: dict[str, pd.DataFrame] = {}
        used: dict[str, str] = {}
        for ds in self.depends_on:
            try:
                df, src = read_raw_any(ds, trade_date)
                raw[ds] = df
                used[ds] = src
            except FileNotFoundError:
                raw[ds] = pd.DataFrame()
                logger.info("fin raw 缺失 %s@%s，按空表", ds, trade_date)
        if used:
            logger.info("Raw sources: %s", used)
        out = self.transform(trade_date, raw)
        # 无公告日保持库内已有行，避免空拉取误删（尤其补扫近月时）
        if out is None or out.empty:
            return 0
        return db.replace_day(self.table, trade_date, out, date_col=self.date_col())

    def transform(self, trade_date: dt.date, raw: dict[str, pd.DataFrame]) -> pd.DataFrame:
        frames: list[pd.DataFrame] = []
        for ds, (stmt_type, fmap) in _STMT_SPECS.items():
            part = self._transform_one(raw.get(ds), stmt_type, fmap)
            if part is not None and not part.empty:
                frames.append(part)
        if not frames:
            return pd.DataFrame()
        return pd.concat(frames, ignore_index=True)

    def _transform_one(
        self,
        df: pd.DataFrame | None,
        stmt_type: str,
        fmap: dict[str, str],
    ) -> pd.DataFrame:
        if df is None or df.empty:
            return pd.DataFrame()
        need = {"exchange_code", "ann_date", "report_date"}
        if missing := need - set(df.columns):
            raise ValueError(f"{stmt_type} Raw 缺列: {missing}")

        bad = df[df["ann_date"] < df["report_date"]]
        if not bad.empty:
            raise ValueError(f"PIT 违规（ann_date < report_date）: {len(bad)} 行 ({stmt_type})")

        mapped = map_security_id(df)
        flag = mapped.get("update_flag", 0)
        if isinstance(flag, pd.Series):
            update_flag = pd.to_numeric(flag, errors="coerce").fillna(0).astype("uint8")
        else:
            update_flag = 0

        fields = []
        for _, row in mapped.iterrows():
            m: dict[str, float] = {}
            for src, std in fmap.items():
                if src in mapped.columns and pd.notna(row.get(src)):
                    try:
                        m[std] = float(row[src])
                    except (TypeError, ValueError):
                        continue
            fields.append(m)

        return pd.DataFrame({
            "security_id": mapped["security_id"],
            "ann_date": mapped["ann_date"],
            "report_date": mapped["report_date"],
            "stmt_type": stmt_type,
            "update_flag": update_flag,
            "fields": fields,
        })


if __name__ == "__main__":
    FinStatementLoader.cli()
