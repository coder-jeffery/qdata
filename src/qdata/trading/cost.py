"""交易成本模型：回测与 Paper 共享同一套费率/滑点规则。

运行时隔离：双方各自持有 CostModel 实例（或值相等的配置），
不共享 broker / ledger 状态。
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any, Literal

SideLike = Literal["buy", "sell"]


@dataclass(frozen=True)
class CostModel:
    """A 股日频默认成本：佣金（含最低）+ 卖出印花税 + 买卖滑点。"""

    commission_rate: float = 0.0003
    commission_min: float = 5.0
    stamp_tax: float = 0.0005
    slippage_bps: float = 5.0

    def __post_init__(self) -> None:
        if self.commission_rate < 0 or self.stamp_tax < 0 or self.slippage_bps < 0:
            raise ValueError("费率/滑点不能为负")
        if self.commission_min < 0:
            raise ValueError("commission_min 不能为负")

    @classmethod
    def zero(cls) -> CostModel:
        """零成本（单测 / 演示可关闭摩擦）。"""
        return cls(
            commission_rate=0.0,
            commission_min=0.0,
            stamp_tax=0.0,
            slippage_bps=0.0,
        )

    def apply_slippage(self, price: float, side: SideLike | str) -> float:
        """买加卖减。"""
        side_n = str(side).strip().lower()
        if side_n not in ("buy", "sell"):
            raise ValueError(f"非法 side={side!r}")
        if price <= 0 or not math.isfinite(price):
            raise ValueError(f"非法 price={price}")
        mult = 1.0 + (self.slippage_bps / 10_000.0) * (1.0 if side_n == "buy" else -1.0)
        out = price * mult
        if out <= 0:
            raise ValueError("滑点后价格非正")
        return float(out)

    def fee(self, notional: float, side: SideLike | str) -> float:
        """佣金（含最低）+ 卖出印花税；notional 为成交金额绝对值。"""
        side_n = str(side).strip().lower()
        if side_n not in ("buy", "sell"):
            raise ValueError(f"非法 side={side!r}")
        if notional <= 0 or not math.isfinite(notional):
            return 0.0
        commission = max(abs(notional) * self.commission_rate, self.commission_min)
        stamp = abs(notional) * self.stamp_tax if side_n == "sell" else 0.0
        return float(commission + stamp)

    def buy_cash_need(self, price: float, quantity: int) -> tuple[float, float, float]:
        """买入所需现金 = 滑点后名义 + 费用。返回 (fill_price, notional, fee)。"""
        fill = self.apply_slippage(float(price), "buy")
        notional = fill * int(quantity)
        fee = self.fee(notional, "buy")
        return fill, notional, fee

    def sell_cash_proceeds(self, price: float, quantity: int) -> tuple[float, float, float]:
        """卖出到手现金 = 滑点后名义 - 费用。返回 (fill_price, notional, fee)。"""
        fill = self.apply_slippage(float(price), "sell")
        notional = fill * int(quantity)
        fee = self.fee(notional, "sell")
        return fill, notional, fee

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# 与 BacktestConfig / Paper 默认一致
DEFAULT_COST = CostModel()
