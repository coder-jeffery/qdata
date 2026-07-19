"""A 股市场规则常量。

所有与交易所规则相关的魔法数字集中在此，规则变更（如注册制改革调整涨跌幅）只改这一处。
"""

from __future__ import annotations

from enum import Enum


class Board(str, Enum):
    """板块。涨跌幅与整手规则按板块区分。"""

    MAIN = "main"    # 沪深主板（含原中小板）
    GEM = "gem"      # 创业板 300xxx
    STAR = "star"    # 科创板 688xxx
    BSE = "bse"      # 北交所 8xxxxx / 4xxxxx


# 涨跌幅限制（非 ST）
PRICE_LIMIT: dict[Board, float] = {
    Board.MAIN: 0.10,
    Board.GEM: 0.20,
    Board.STAR: 0.20,
    Board.BSE: 0.30,
}

# ST/*ST 涨跌幅：仅主板收窄到 5%，创业板/科创板 ST 仍为 20%
ST_PRICE_LIMIT: dict[Board, float] = {
    Board.MAIN: 0.05,
    Board.GEM: 0.20,
    Board.STAR: 0.20,
    Board.BSE: 0.30,
}

# 整手规则：(最小买入股数, 递增单位)
LOT_RULE: dict[Board, tuple[int, int]] = {
    Board.MAIN: (100, 100),
    Board.GEM: (100, 100),
    Board.STAR: (200, 1),   # 科创板 200 股起、1 股递增
    Board.BSE: (100, 1),
}

# 新股上市初期无涨跌幅限制的交易日数（主板 1 日 44%/36% 特例单独处理）
NO_LIMIT_DAYS: dict[Board, int] = {
    Board.MAIN: 1,
    Board.GEM: 5,
    Board.STAR: 5,
    Board.BSE: 1,
}


def board_of(exchange_code: str) -> Board:
    """由交易所代码推断板块，如 '600000.SH' → MAIN，'300750.SZ' → GEM。"""
    symbol, _, market = exchange_code.partition(".")
    if market == "SH":
        return Board.STAR if symbol.startswith("688") else Board.MAIN
    if market == "SZ":
        return Board.GEM if symbol.startswith("300") else Board.MAIN
    if market == "BJ":
        return Board.BSE
    raise ValueError(f"无法识别的代码: {exchange_code}")


def limit_prices(pre_close: float, board: Board, is_st: bool) -> tuple[float, float]:
    """计算当日涨停价/跌停价（交易所口径：四舍五入到分）。

    注意必须用不复权的昨收 pre_close。
    """
    pct = (ST_PRICE_LIMIT if is_st else PRICE_LIMIT)[board]
    up = round(pre_close * (1 + pct) + 1e-9, 2)
    down = round(pre_close * (1 - pct) + 1e-9, 2)
    return up, down


def round_lot(shares: int, board: Board) -> int:
    """按整手规则向下取整可买股数。"""
    min_qty, step = LOT_RULE[board]
    if shares < min_qty:
        return 0
    return min_qty + (shares - min_qty) // step * step
