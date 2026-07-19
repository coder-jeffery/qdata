"""申万行业分类拉取（AKShare 乐咕 L1/L2 列表 + 申万成分）。

Raw 标准列：
  exchange_code, level, industry, as_of_date, confidence
  （可选 in_date）

industry 格式：``{code}|{name}``，如 ``801010.SI|农林牧渔``。

confidence:
  - akshare_sw_component: 乐咕行业列表 + index_component_sw 当日成分
"""

from __future__ import annotations

import datetime as dt
import logging
import time

import pandas as pd

from qdata.industry import LEVEL_L1, LEVEL_L2, SEED_LEVELS
from qdata.symbols import to_exchange_code

logger = logging.getLogger(__name__)

_EMPTY_COLS = ["exchange_code", "level", "industry", "as_of_date", "confidence"]


def format_industry(code: str, name: str) -> str:
    c = str(code).strip()
    if not c.endswith(".SI") and c.isdigit():
        c = f"{c}.SI"
    n = str(name).strip()
    return f"{c}|{n}" if n else c


def parse_industry(industry: str) -> tuple[str, str]:
    """``801010.SI|农林牧渔`` → (code, name)。"""
    s = str(industry).strip()
    if "|" in s:
        code, name = s.split("|", 1)
        return code.strip(), name.strip()
    return s, ""


def fetch_sw_industry_snapshot(
    as_of: dt.date,
    *,
    levels: tuple[str, ...] | None = None,
    sleep_s: float = 0.15,
) -> pd.DataFrame:
    """拉取申万 L1/L2 全市场分类快照。"""
    targets = levels or SEED_LEVELS
    frames: list[pd.DataFrame] = []
    if LEVEL_L1 in targets:
        frames.append(_fetch_level(LEVEL_L1, as_of, sleep_s=sleep_s))
    if LEVEL_L2 in targets:
        frames.append(_fetch_level(LEVEL_L2, as_of, sleep_s=sleep_s))
    frames = [f for f in frames if f is not None and not f.empty]
    if not frames:
        return pd.DataFrame(columns=_EMPTY_COLS)
    out = pd.concat(frames, ignore_index=True)
    out = out.drop_duplicates(["exchange_code", "level", "as_of_date"], keep="last")
    return out


def load_raw_industry_snapshots(source: str = "akshare") -> pd.DataFrame:
    """读取湖中全部 industry_member 分区。"""
    from qdata.config import settings

    root = settings().lake_root / "raw" / source / "industry_member"
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


def _fetch_level(level: str, as_of: dt.date, *, sleep_s: float) -> pd.DataFrame:
    import akshare as ak

    from qdata.fetchers.akshare_fetcher import _without_proxy

    with _without_proxy():
        if level == LEVEL_L1:
            info = ak.sw_index_first_info()
        elif level == LEVEL_L2:
            info = ak.sw_index_second_info()
        else:
            raise ValueError(f"不支持 level={level}")

    if info is None or info.empty:
        logger.warning("sw industry info empty level=%s", level)
        return pd.DataFrame(columns=_EMPTY_COLS)

    rows: list[dict] = []
    for _, r in info.iterrows():
        ind_code = str(r["行业代码"]).strip()
        ind_name = str(r["行业名称"]).strip()
        pure = ind_code.replace(".SI", "")
        try:
            with _without_proxy():
                cons = ak.index_component_sw(symbol=pure)
        except Exception as e:
            logger.warning("index_component_sw %s 失败: %s", pure, e)
            time.sleep(sleep_s)
            continue
        if sleep_s > 0:
            time.sleep(sleep_s)
        if cons is None or cons.empty:
            continue
        code_col = "证券代码" if "证券代码" in cons.columns else cons.columns[1]
        in_col = "计入日期" if "计入日期" in cons.columns else None
        industry = format_industry(ind_code, ind_name)
        for _, c in cons.iterrows():
            try:
                ec = to_exchange_code(str(c[code_col]))
            except Exception:
                continue
            in_date = None
            if in_col is not None and pd.notna(c.get(in_col)):
                try:
                    in_date = pd.to_datetime(c[in_col], errors="coerce").date()
                except Exception:
                    in_date = None
            rows.append({
                "exchange_code": ec,
                "level": level,
                "industry": industry,
                "as_of_date": as_of,
                "in_date": in_date,
                "confidence": "akshare_sw_component",
            })
        logger.info(
            "industry %s %s(%s): %s stocks",
            level, ind_name, ind_code, len(cons),
        )

    if not rows:
        return pd.DataFrame(columns=_EMPTY_COLS)
    return pd.DataFrame(rows)
