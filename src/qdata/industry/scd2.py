"""行业分类属性 SCD2：多期快照 → (in_date, out_date) 区间。

规则：
  in_date <= T AND out_date > T  ⇒  T 日属于该 industry

对每个 (exchange_code, level)：当 industry 变更时闭合旧区间、开启新区间。
禁止仅用「最新分类」冒充历史：单期 snapshot 全部 out_date=OPEN_END。
"""

from __future__ import annotations

import datetime as dt

import pandas as pd

from qdata.industry import OPEN_END

_OUT_COLS = ["exchange_code", "level", "industry", "in_date", "out_date"]


def attribute_snapshots_to_intervals(snaps: pd.DataFrame) -> pd.DataFrame:
    """多期行业快照 → 区间表。

    输入列：exchange_code, level, industry, as_of_date
    （可选 in_date：首段纳入提示）
    """
    if snaps is None or snaps.empty:
        return pd.DataFrame(columns=_OUT_COLS)

    need = {"exchange_code", "level", "industry", "as_of_date"}
    missing = need - set(snaps.columns)
    if missing:
        raise ValueError(f"行业快照缺列: {missing}")

    df = snaps.copy()
    df["as_of_date"] = pd.to_datetime(df["as_of_date"], errors="coerce").dt.date
    df["exchange_code"] = df["exchange_code"].astype(str)
    df["level"] = df["level"].astype(str)
    df["industry"] = df["industry"].astype(str)
    df = df.dropna(subset=["as_of_date", "exchange_code", "level", "industry"])
    df = df.drop_duplicates(["exchange_code", "level", "as_of_date"], keep="last")

    include_hint: dict[tuple[str, str], dt.date] = {}
    if "in_date" in df.columns:
        tmp = df.dropna(subset=["in_date"]).copy()
        tmp["in_date"] = pd.to_datetime(tmp["in_date"], errors="coerce").dt.date
        for _, r in tmp.iterrows():
            key = (str(r["exchange_code"]), str(r["level"]))
            d = r["in_date"]
            if d is None or (isinstance(d, float) and pd.isna(d)):
                continue
            prev = include_hint.get(key)
            if prev is None or d < prev:
                include_hint[key] = d

    intervals: list[dict] = []
    for (code, level), g in df.groupby(["exchange_code", "level"]):
        g = g.sort_values("as_of_date")
        # as_of -> industry（同日已去重）
        by_date = {
            d: str(ind)
            for d, ind in zip(g["as_of_date"].tolist(), g["industry"].tolist())
        }
        dates = sorted(by_date)

        cur_ind: str | None = None
        cur_in: dt.date | None = None
        for d in dates:
            ind = by_date[d]
            if cur_ind is None:
                hinted = include_hint.get((str(code), str(level)))
                cur_in = hinted if hinted is not None and hinted <= d else d
                cur_ind = ind
                continue
            if ind == cur_ind:
                continue
            # 变更：闭合旧段
            intervals.append({
                "exchange_code": code,
                "level": level,
                "industry": cur_ind,
                "in_date": cur_in,
                "out_date": d,
            })
            cur_ind = ind
            cur_in = d

        if cur_ind is not None and cur_in is not None:
            intervals.append({
                "exchange_code": code,
                "level": level,
                "industry": cur_ind,
                "in_date": cur_in,
                "out_date": OPEN_END,
            })

    if not intervals:
        return pd.DataFrame(columns=_OUT_COLS)
    return _merge_adjacent(pd.DataFrame(intervals))


def industry_on(
    intervals: pd.DataFrame,
    exchange_code: str,
    level: str,
    on: dt.date,
) -> str | None:
    """时点查询单票行业（纯 DataFrame，便于单测）。"""
    if intervals is None or intervals.empty:
        return None
    m = intervals[
        (intervals["exchange_code"] == exchange_code)
        & (intervals["level"] == level)
        & (intervals["in_date"] <= on)
        & (intervals["out_date"] > on)
    ]
    if m.empty:
        return None
    return str(m.iloc[0]["industry"])


def _merge_adjacent(intervals: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict] = []
    for keys, g in intervals.groupby(["exchange_code", "level", "industry"]):
        g = g.sort_values("in_date")
        code, level, industry = keys
        cur_in = None
        cur_out = None
        for _, r in g.iterrows():
            if cur_in is None:
                cur_in, cur_out = r["in_date"], r["out_date"]
                continue
            if r["in_date"] <= cur_out:
                if r["out_date"] > cur_out:
                    cur_out = r["out_date"]
            else:
                rows.append({
                    "exchange_code": code,
                    "level": level,
                    "industry": industry,
                    "in_date": cur_in,
                    "out_date": cur_out,
                })
                cur_in, cur_out = r["in_date"], r["out_date"]
        if cur_in is not None:
            rows.append({
                "exchange_code": code,
                "level": level,
                "industry": industry,
                "in_date": cur_in,
                "out_date": cur_out,
            })
    return pd.DataFrame(rows) if rows else intervals.iloc[0:0].copy()
