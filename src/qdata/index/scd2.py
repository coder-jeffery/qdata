"""指数成分 SCD2：多期快照 / 月度权重 → (in_date, out_date) 区间。

规则：
  in_date <= T AND out_date > T  ⇒  T 日在指数内

禁止仅用「最新成分」冒充历史：单日快照模式只能覆盖当前成员；
多期快照或 Tushare 月度权重才能正确闭合调出区间。
"""

from __future__ import annotations

import datetime as dt

import pandas as pd

from qdata.index import OPEN_END


def snapshots_to_intervals(snaps: pd.DataFrame) -> pd.DataFrame:
    """多期成分快照 → 区间表。

    输入列：index_code, exchange_code, as_of_date
    （可选 in_date：若提供，首段 in_date 取 min(纳入日, 首次快照日)）

    算法：按指数、按 as_of 排序；相邻快照间成员消失则 out_date=下一快照日；
    仍在最后一期的成员 out_date=OPEN_END。
    """
    if snaps is None or snaps.empty:
        return pd.DataFrame(columns=["index_code", "exchange_code", "in_date", "out_date"])

    need = {"index_code", "exchange_code", "as_of_date"}
    missing = need - set(snaps.columns)
    if missing:
        raise ValueError(f"快照缺列: {missing}")

    df = snaps.copy()
    df["as_of_date"] = pd.to_datetime(df["as_of_date"], errors="coerce").dt.date
    df["exchange_code"] = df["exchange_code"].astype(str)
    df["index_code"] = df["index_code"].astype(str)
    df = df.dropna(subset=["as_of_date", "exchange_code", "index_code"])
    df = df.drop_duplicates(["index_code", "exchange_code", "as_of_date"])

    include_hint: dict[tuple[str, str], dt.date] = {}
    if "in_date" in df.columns:
        tmp = df.dropna(subset=["in_date"]).copy()
        tmp["in_date"] = pd.to_datetime(tmp["in_date"], errors="coerce").dt.date
        for _, r in tmp.iterrows():
            key = (str(r["index_code"]), str(r["exchange_code"]))
            d = r["in_date"]
            if d is None or (isinstance(d, float) and pd.isna(d)):
                continue
            prev = include_hint.get(key)
            if prev is None or d < prev:
                include_hint[key] = d

    intervals: list[dict] = []
    for index_code, g_idx in df.groupby("index_code"):
        snap_dates = sorted(g_idx["as_of_date"].unique())
        # date -> set(codes)
        members_by_date: dict[dt.date, set[str]] = {
            d: set(g_idx.loc[g_idx["as_of_date"] == d, "exchange_code"].astype(str))
            for d in snap_dates
        }

        # active: code -> in_date
        active: dict[str, dt.date] = {}
        for i, d in enumerate(snap_dates):
            cur = members_by_date[d]
            prev_codes = set(active)

            # 调出
            for code in sorted(prev_codes - cur):
                intervals.append({
                    "index_code": index_code,
                    "exchange_code": code,
                    "in_date": active.pop(code),
                    "out_date": d,
                })

            # 调入
            for code in sorted(cur - prev_codes):
                hinted = include_hint.get((str(index_code), code))
                in_d = hinted if hinted is not None and hinted <= d else d
                active[code] = in_d

        # 收尾：仍在市
        for code, in_d in sorted(active.items()):
            intervals.append({
                "index_code": index_code,
                "exchange_code": code,
                "in_date": in_d,
                "out_date": OPEN_END,
            })

    if not intervals:
        return pd.DataFrame(columns=["index_code", "exchange_code", "in_date", "out_date"])
    out = pd.DataFrame(intervals)
    # 合并同指数同代码相邻/重叠段（防御）
    return _merge_adjacent(out)


def weight_panel_to_snapshots(weights: pd.DataFrame, *, index_code: str) -> pd.DataFrame:
    """Tushare index_weight 面板 → 快照表。

    输入列：con_code / exchange_code, trade_date（月度调仓日）
    """
    if weights is None or weights.empty:
        return pd.DataFrame(columns=["index_code", "exchange_code", "as_of_date", "confidence"])

    w = weights.copy()
    if "exchange_code" not in w.columns:
        if "con_code" in w.columns:
            w["exchange_code"] = w["con_code"].astype(str)
        else:
            raise ValueError("weight 面板需要 exchange_code 或 con_code")
    w["as_of_date"] = pd.to_datetime(w["trade_date"], errors="coerce").dt.date
    w = w.dropna(subset=["as_of_date", "exchange_code"])
    w["index_code"] = index_code
    w["confidence"] = "tushare_weight"
    return w[["index_code", "exchange_code", "as_of_date", "confidence"]].drop_duplicates()


def _merge_adjacent(intervals: pd.DataFrame) -> pd.DataFrame:
    """合并同 (index, code) 且 out==下一 in 的相邻段。"""
    rows: list[dict] = []
    key_cols = ["index_code", "exchange_code"]
    for keys, g in intervals.groupby(key_cols):
        g = g.sort_values("in_date")
        cur_in = None
        cur_out = None
        index_code, exchange_code = keys if isinstance(keys, tuple) else (keys, None)
        for _, r in g.iterrows():
            if cur_in is None:
                cur_in, cur_out = r["in_date"], r["out_date"]
                continue
            if r["in_date"] <= cur_out:
                # 重叠或相接：延长
                if r["out_date"] > cur_out:
                    cur_out = r["out_date"]
            else:
                rows.append({
                    "index_code": index_code,
                    "exchange_code": exchange_code,
                    "in_date": cur_in,
                    "out_date": cur_out,
                })
                cur_in, cur_out = r["in_date"], r["out_date"]
        if cur_in is not None:
            rows.append({
                "index_code": index_code,
                "exchange_code": exchange_code,
                "in_date": cur_in,
                "out_date": cur_out,
            })
    return pd.DataFrame(rows) if rows else intervals.iloc[0:0].copy()


def members_on(intervals: pd.DataFrame, index_code: str, on: dt.date) -> list[str]:
    """时点查询（纯 DataFrame，便于单测）。"""
    if intervals is None or intervals.empty:
        return []
    m = intervals[
        (intervals["index_code"] == index_code)
        & (intervals["in_date"] <= on)
        & (intervals["out_date"] > on)
    ]
    return sorted(m["exchange_code"].astype(str).unique().tolist())
