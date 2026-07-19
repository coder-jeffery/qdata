"""指数成分拉取（AKShare 为主；Tushare 可选）。

Raw 标准列：
  index_code, exchange_code, in_date, as_of_date, confidence

confidence:
  - sina_include_date: 新浪成分 + 纳入日期（当前成分区间近似）
  - csindex_snapshot: 中证官网当日快照（in_date=as_of）
  - tushare_weight: 月度权重重建的历史区间（更可信）
"""

from __future__ import annotations

import datetime as dt
import logging

import pandas as pd

from qdata.index import INDEX_PURE_CODE, SEED_INDEX_CODES, TUSHARE_INDEX_CODE
from qdata.symbols import to_exchange_code

logger = logging.getLogger(__name__)

_EMPTY_COLS = ["index_code", "exchange_code", "in_date", "as_of_date", "confidence"]


def fetch_seed_index_members(
    as_of: dt.date,
    *,
    indices: tuple[str, ...] | None = None,
) -> pd.DataFrame:
    """拉取种子指数成分快照（AKShare），合并为一张表。"""
    targets = indices or SEED_INDEX_CODES
    frames: list[pd.DataFrame] = []
    for idx in targets:
        pure = INDEX_PURE_CODE.get(idx, idx.split(".", 1)[0])
        part = _fetch_one(idx, pure, as_of)
        if not part.empty:
            frames.append(part)
            logger.info("index_member %s: %s rows (%s)", idx, len(part), part["confidence"].iloc[0])
        else:
            logger.warning("index_member %s: 空结果", idx)
    if not frames:
        return pd.DataFrame(columns=_EMPTY_COLS)
    return pd.concat(frames, ignore_index=True)


def fetch_index_weight_history(
    start: dt.date,
    end: dt.date,
    *,
    indices: tuple[str, ...] | None = None,
) -> pd.DataFrame:
    """Tushare 月度 index_weight → 多期快照（需 ENABLED+TOKEN+积分）。

    返回标准快照列，confidence=tushare_weight。
    """
    from qdata.fetchers.tushare_fetcher import ensure_tushare_enabled
    from qdata.config import settings

    ensure_tushare_enabled()
    import tushare as ts

    s = settings()
    pro = ts.pro_api((s.tushare_token or "").strip())
    targets = indices or SEED_INDEX_CODES
    frames: list[pd.DataFrame] = []
    for idx in targets:
        ts_code = TUSHARE_INDEX_CODE.get(idx, idx)
        try:
            raw = pro.index_weight(
                index_code=ts_code,
                start_date=start.strftime("%Y%m%d"),
                end_date=end.strftime("%Y%m%d"),
            )
        except Exception as e:
            logger.warning("tushare index_weight %s(%s) 失败: %s", idx, ts_code, e)
            continue
        if raw is None or raw.empty:
            logger.warning("tushare index_weight %s(%s) 空", idx, ts_code)
            continue
        part = pd.DataFrame({
            "index_code": idx,
            "exchange_code": raw["con_code"].astype(str),
            "in_date": pd.NaT,  # 由 SCD2 用 as_of 推断
            "as_of_date": pd.to_datetime(raw["trade_date"], format="%Y%m%d", errors="coerce").dt.date,
            "confidence": "tushare_weight",
        }).dropna(subset=["as_of_date", "exchange_code"])
        frames.append(part)
        logger.info(
            "tushare weight %s: %s rows, dates=%s~%s",
            idx, len(part), part["as_of_date"].min(), part["as_of_date"].max(),
        )
    if not frames:
        return pd.DataFrame(columns=_EMPTY_COLS)
    return pd.concat(frames, ignore_index=True)


def load_raw_index_snapshots(source: str = "akshare") -> pd.DataFrame:
    """读取湖中已有全部 index_member 分区，合并为多期快照。"""
    from qdata.config import settings

    root = settings().lake_root / "raw" / source / "index_member"
    if not root.exists():
        return pd.DataFrame(columns=_EMPTY_COLS)
    frames: list[pd.DataFrame] = []
    for pdir in sorted(root.glob("dt=*")):
        path = pdir / "data.parquet"
        if not path.exists():
            continue
        try:
            df = pd.read_parquet(path)
        except Exception as e:
            logger.warning("读 Raw 失败 %s: %s", path, e)
            continue
        if df is None or df.empty:
            continue
        if "as_of_date" not in df.columns:
            # 从分区名推断
            try:
                as_of = dt.date.fromisoformat(pdir.name.replace("dt=", ""))
            except ValueError:
                continue
            df = df.copy()
            df["as_of_date"] = as_of
        frames.append(df)
    if not frames:
        return pd.DataFrame(columns=_EMPTY_COLS)
    return pd.concat(frames, ignore_index=True)


def _fetch_one(index_code: str, pure: str, as_of: dt.date) -> pd.DataFrame:
    # 1) 新浪：含纳入日期，利于近似区间
    try:
        df = _from_sina(index_code, pure, as_of)
        if not df.empty:
            return df
    except Exception as e:
        logger.warning("sina index_stock_cons %s 失败: %s", pure, e)

    # 2) 中证官网当日目录
    try:
        df = _from_csindex(index_code, pure, as_of)
        if not df.empty:
            return df
    except Exception as e:
        logger.warning("csindex cons %s 失败: %s", pure, e)

    return pd.DataFrame(columns=_EMPTY_COLS)


def _from_sina(index_code: str, pure: str, as_of: dt.date) -> pd.DataFrame:
    import akshare as ak

    from qdata.fetchers.akshare_fetcher import _without_proxy

    with _without_proxy():
        raw = ak.index_stock_cons(symbol=pure)
    if raw is None or raw.empty:
        return pd.DataFrame(columns=_EMPTY_COLS)

    code_col = "品种代码" if "品种代码" in raw.columns else raw.columns[0]
    in_col = "纳入日期" if "纳入日期" in raw.columns else None
    codes = raw[code_col].astype(str).map(lambda x: to_exchange_code(x))
    if in_col:
        in_dates = pd.to_datetime(raw[in_col], errors="coerce").dt.date
        in_dates = in_dates.fillna(as_of)
        confidence = "sina_include_date"
    else:
        in_dates = pd.Series([as_of] * len(raw))
        confidence = "sina_snapshot"

    return pd.DataFrame({
        "index_code": index_code,
        "exchange_code": codes,
        "in_date": in_dates,
        "as_of_date": as_of,
        "confidence": confidence,
    })


def _from_csindex(index_code: str, pure: str, as_of: dt.date) -> pd.DataFrame:
    import akshare as ak

    from qdata.fetchers.akshare_fetcher import _without_proxy

    with _without_proxy():
        raw = ak.index_stock_cons_csindex(symbol=pure)
    if raw is None or raw.empty:
        return pd.DataFrame(columns=_EMPTY_COLS)

    code_col = "成分券代码" if "成分券代码" in raw.columns else None
    if code_col is None:
        raise RuntimeError(f"csindex 列异常: {raw.columns.tolist()}")
    ex_col = "交易所" if "交易所" in raw.columns else None
    codes: list[str] = []
    for i, sym in enumerate(raw[code_col].astype(str)):
        if ex_col:
            ex = str(raw.iloc[i][ex_col])
            if "上海" in ex or "Shanghai" in ex:
                codes.append(f"{sym.zfill(6)}.SH")
            elif "北京" in ex or "Beijing" in ex:
                codes.append(f"{sym.zfill(6)}.BJ")
            else:
                codes.append(f"{sym.zfill(6)}.SZ")
        else:
            codes.append(to_exchange_code(sym))

    snap = as_of
    if "日期" in raw.columns:
        try:
            snap = pd.to_datetime(raw["日期"].iloc[0]).date()
        except Exception:
            pass

    return pd.DataFrame({
        "index_code": index_code,
        "exchange_code": codes,
        "in_date": snap,
        "as_of_date": as_of,
        "confidence": "csindex_snapshot",
    })
