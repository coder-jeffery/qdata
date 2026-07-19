"""简易回测读数层：按日拼装选股域 / 价格 / 因子 → 目标权重。

不做撮合、滑点、下单（M3）。报告应记录 DataAPI.version。
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Literal

import pandas as pd

from qdata import calendar
from qdata.api.data_api import Adjust, DataAPI

WeightMethod = Literal["equal", "factor_rank", "industry_neutral"]


@dataclass(frozen=True)
class RebalanceSpec:
    universe: str = "000905.SH"
    filters: tuple[str, ...] = ("st", "suspended", "listed_days<120")
    factor: str = "mom_20"
    factor_version: str = "v1"
    adjust: Adjust = "post"
    top_n: int | None = None
    weight_method: WeightMethod = "equal"
    industry_level: Literal["sw_l1", "sw_l2"] = "sw_l1"


def iter_trading_days(start: dt.date, end: dt.date) -> list[dt.date]:
    return calendar.trading_days_between(start, end)


def day_panel(
    api: DataAPI,
    d: dt.date,
    *,
    universe: str = "000905.SH",
    filters: list[str] | None = None,
    factor: str = "mom_20",
    factor_version: str = "v1",
    adjust: Adjust = "post",
    with_industry: bool = False,
    industry_level: Literal["sw_l1", "sw_l2"] = "sw_l1",
) -> pd.DataFrame:
    """单日研究面板：exchange_code ∩ close ∩ factor value（可选 industry）。"""
    cols = ["trade_date", "exchange_code", "close", "value"]
    if with_industry:
        cols.append("industry")
    uni = api.get_universe(universe, d, filters=filters)
    if not uni:
        return pd.DataFrame(columns=cols)

    px = api.get_price(uni, d, d, adjust=adjust, fields=("close",))
    if px is None or px.empty:
        return pd.DataFrame(columns=cols)
    px = px[["exchange_code", "close"]].copy()

    fac = api.load_factor(factor, d, d, version=factor_version, with_code=True)
    if fac is None or fac.empty or "exchange_code" not in fac.columns:
        return pd.DataFrame(columns=cols)
    fac = fac[["exchange_code", "value"]].dropna(subset=["value"])

    panel = px.merge(fac, on="exchange_code", how="inner")
    if panel.empty:
        return pd.DataFrame(columns=cols)
    panel.insert(0, "trade_date", d)

    if with_industry:
        ind = api.get_industry(panel["exchange_code"].tolist(), d, level=industry_level)
        if isinstance(ind, pd.Series):
            panel["industry"] = panel["exchange_code"].map(ind).fillna("UNKNOWN")
        else:
            panel["industry"] = panel["exchange_code"].map(
                lambda c: (ind or {}).get(c, "UNKNOWN")
            ).fillna("UNKNOWN")
        panel = panel[cols]
    else:
        panel = panel[["trade_date", "exchange_code", "close", "value"]]
    return panel.sort_values("exchange_code").reset_index(drop=True)


def target_weights(
    panel: pd.DataFrame,
    *,
    method: WeightMethod = "equal",
    top_n: int | None = None,
) -> pd.DataFrame:
    """研究输出：trade_date, exchange_code, weight（同日权重和为 1）。"""
    out_cols = ["trade_date", "exchange_code", "weight"]
    if panel is None or panel.empty:
        return pd.DataFrame(columns=out_cols)

    df = panel.dropna(subset=["value"]).copy()
    if df.empty:
        return pd.DataFrame(columns=out_cols)

    if top_n is not None and top_n > 0:
        df = df.sort_values("value", ascending=False).head(int(top_n))

    if method == "equal":
        df["weight"] = 1.0 / len(df)
    elif method == "factor_rank":
        ranks = df["value"].rank(method="average", ascending=True)
        s = float(ranks.sum())
        df["weight"] = (ranks / s) if s > 0 else 1.0 / len(df)
    elif method == "industry_neutral":
        if "industry" not in df.columns:
            raise ValueError("industry_neutral 需要 panel 含 industry 列")
        df["industry"] = df["industry"].fillna("UNKNOWN").astype(str)
        parts: list[pd.DataFrame] = []
        industries = sorted(df["industry"].unique().tolist())
        if not industries:
            return pd.DataFrame(columns=out_cols)
        w_ind = 1.0 / len(industries)
        for ind in industries:
            g = df[df["industry"] == ind].copy()
            # 行业内按因子秩加权，再缩放到行业总权重相等
            ranks = g["value"].rank(method="average", ascending=True)
            s = float(ranks.sum())
            g["weight"] = (ranks / s * w_ind) if s > 0 else (w_ind / len(g))
            parts.append(g)
        df = pd.concat(parts, ignore_index=True)
    else:
        raise ValueError(f"未知 weight_method={method!r}")

    return df[["trade_date", "exchange_code", "weight"]].reset_index(drop=True)


def build_weight_series(
    start: dt.date,
    end: dt.date,
    *,
    api: DataAPI | None = None,
    spec: RebalanceSpec | None = None,
) -> pd.DataFrame:
    """区间内逐日目标权重；``attrs['dataset_version']`` 记录读数版本。"""
    api = api or DataAPI()
    spec = spec or RebalanceSpec()
    need_ind = spec.weight_method == "industry_neutral"
    frames: list[pd.DataFrame] = []
    for d in iter_trading_days(start, end):
        panel = day_panel(
            api,
            d,
            universe=spec.universe,
            filters=list(spec.filters),
            factor=spec.factor,
            factor_version=spec.factor_version,
            adjust=spec.adjust,
            with_industry=need_ind,
            industry_level=spec.industry_level,
        )
        w = target_weights(panel, method=spec.weight_method, top_n=spec.top_n)
        if not w.empty:
            frames.append(w)
    if not frames:
        out = pd.DataFrame(columns=["trade_date", "exchange_code", "weight"])
    else:
        out = pd.concat(frames, ignore_index=True)
    out.attrs["dataset_version"] = api.version
    out.attrs["factor"] = spec.factor
    out.attrs["universe"] = spec.universe
    out.attrs["weight_method"] = spec.weight_method
    return out
