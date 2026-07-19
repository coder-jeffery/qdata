"""申万行业分类区间表约定。"""

from __future__ import annotations

from qdata.index import OPEN_END

# ClickHouse Enum8 取值
LEVEL_L1 = "sw_l1"
LEVEL_L2 = "sw_l2"
SEED_LEVELS: tuple[str, ...] = (LEVEL_L1, LEVEL_L2)

__all__ = [
    "OPEN_END",
    "LEVEL_L1",
    "LEVEL_L2",
    "SEED_LEVELS",
]
