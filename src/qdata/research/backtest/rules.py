"""A 股日频成交规则（纯函数）。"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from qdata.research.backtest.types import Bar, Side
from qdata.trading.cost import CostModel

if TYPE_CHECKING:
    from qdata.research.backtest.config import BacktestConfig


def round_lot(shares: float, lot: int, side: Side, *, allow_partial: bool = False) -> int:
    """将目标股数调整为可下单整数股。

    默认整手下取整；``allow_partial=True`` 时仅取整到股（仍 ≥0）。
    """
    if lot <= 0:
        raise ValueError("lot 必须 > 0")
    if shares <= 0 or not math.isfinite(shares):
        return 0
    if allow_partial:
        return int(math.floor(shares))
    return int(math.floor(shares / lot) * lot)


def apply_slippage(price: float, side: Side, bps: float) -> float:
    """买加卖减（委托共享 CostModel）。"""
    return CostModel(
        commission_rate=0.0,
        commission_min=0.0,
        stamp_tax=0.0,
        slippage_bps=bps,
    ).apply_slippage(price, side)


def can_buy(bar: Bar, *, eps: float = 1e-4) -> tuple[bool, str | None]:
    if bar.suspended:
        return False, "suspended"
    if bar.open <= 0 or not math.isfinite(bar.open):
        return False, "no_price"
    if bar.up_limit is not None and math.isfinite(bar.up_limit) and bar.up_limit > 0:
        # 用 close 相对涨停价判断（设计：limit_proxy=close）
        if bar.close >= bar.up_limit * (1.0 - eps):
            return False, "limit_up"
    return True, None


def can_sell(bar: Bar, *, eps: float = 1e-4) -> tuple[bool, str | None]:
    if bar.suspended:
        return False, "suspended"
    if bar.open <= 0 or not math.isfinite(bar.open):
        return False, "no_price"
    if bar.down_limit is not None and math.isfinite(bar.down_limit) and bar.down_limit > 0:
        if bar.close <= bar.down_limit * (1.0 + eps):
            return False, "limit_down"
    return True, None


def calc_fee(notional: float, side: Side, cfg: BacktestConfig) -> float:
    """佣金（含最低）+ 卖出印花税；委托 ``CostModel``（与 Paper 同源）。"""
    return cfg.cost_model().fee(notional, side)


def exec_price(bar: Bar, side: Side, cfg: BacktestConfig) -> float:
    """执行基准价：next_open 用 open；next_close 用 close；再加滑点。"""
    raw = bar.open if cfg.execution == "next_open" else bar.close
    return cfg.cost_model().apply_slippage(raw, side)
