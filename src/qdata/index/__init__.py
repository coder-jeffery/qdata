"""指数成分区间表：种子指数约定。"""

from __future__ import annotations

import datetime as dt

# 首批时点选股域（沪深300 / 中证500 / 中证1000）
SEED_INDEX_CODES: tuple[str, ...] = ("000300.SH", "000905.SH", "000852.SH")

# 未调出占位
OPEN_END: dt.date = dt.date(2099, 12, 31)

# 内部指数代码 → AKShare/中证纯代码
INDEX_PURE_CODE: dict[str, str] = {
    "000300.SH": "000300",
    "000905.SH": "000905",
    "000852.SH": "000852",
}

# 内部指数 → Tushare index_weight 代码（沪深300 需用 399300.SZ）
TUSHARE_INDEX_CODE: dict[str, str] = {
    "000300.SH": "399300.SZ",
    "000905.SH": "000905.SH",
    "000852.SH": "000852.SH",
}
