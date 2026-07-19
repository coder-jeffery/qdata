"""联调用股票池：优先读 lake 缓存，否则内置样本。"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from qdata.config import settings

logger = logging.getLogger(__name__)

_FALLBACK_ROWS = [
    ("000001", "平安银行"),
    ("000002", "万科A"),
    ("000858", "五粮液"),
    ("002415", "海康威视"),
    ("300750", "宁德时代"),
    ("600000", "浦发银行"),
    ("600519", "贵州茅台"),
    ("600900", "长江电力"),
    ("601318", "中国平安"),
    ("603259", "药明康德"),
    ("688981", "中芯国际"),
    ("688041", "海光信息"),
]


def fallback_universe_df() -> pd.DataFrame:
    return pd.DataFrame(_FALLBACK_ROWS, columns=["code", "name"])


def universe_cache_path() -> Path:
    return settings().lake_root / "meta" / "symbol_universe.parquet"


def load_cached_universe() -> pd.DataFrame | None:
    path = universe_cache_path()
    if not path.exists():
        return None
    try:
        df = pd.read_parquet(path)
        if "code" not in df.columns:
            return None
        return df
    except Exception as e:
        logger.warning("读取 universe 缓存失败: %s", e)
        return None


def limited_codes(codes: list[str], max_symbols: int) -> list[str]:
    codes = sorted({str(c).zfill(6) for c in codes})
    if max_symbols and max_symbols > 0:
        codes = codes[:max_symbols]
        logger.info("MAX_SYMBOLS=%s，仅使用 %s 只", max_symbols, len(codes))
    return codes
