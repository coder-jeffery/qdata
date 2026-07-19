"""回测配置。"""

from __future__ import annotations

import datetime as dt
from dataclasses import asdict, dataclass
from typing import Any, Literal

from qdata.api.data_api import Adjust
from qdata.trading.cost import CostModel

Execution = Literal["next_open", "next_close"]

ENGINE_VERSION = "bt-daily-0.1"


@dataclass(frozen=True)
class BacktestConfig:
    start: dt.date
    end: dt.date
    initial_cash: float = 100_000_000.0
    execution: Execution = "next_open"
    adjust: Adjust = "post"
    lot_size: int = 100
    commission_rate: float = 0.0003
    commission_min: float = 5.0
    stamp_tax: float = 0.0005
    slippage_bps: float = 5.0
    weight_sum_tol: float = 1e-6
    renormalize_weights: bool = True
    allow_partial_lot: bool = False
    benchmark: str | None = "000905.SH"
    dataset_version: str | None = None
    engine_version: str = ENGINE_VERSION
    run_name: str = ""
    persist: bool = True
    persist_ch: bool = True  # Lake 之外是否写入 backtest_run / backtest_equity
    write_tearsheet: bool = True
    # 涨跌停判定：close 相对限价的相对容差
    limit_eps: float = 1e-4
    # 单票成交量占比上限（相对当日 volume）；0=不限制
    max_adv_participation: float = 0.0

    def __post_init__(self) -> None:
        if self.start > self.end:
            raise ValueError(f"start({self.start}) > end({self.end})")
        if self.initial_cash <= 0:
            raise ValueError("initial_cash 必须 > 0")
        if self.lot_size <= 0:
            raise ValueError("lot_size 必须 > 0")
        # 复用 CostModel 校验（非法费率在构造时抛错）
        self.cost_model()
        if self.execution not in ("next_open", "next_close"):
            raise ValueError(f"非法 execution={self.execution!r}")
        if self.adjust not in ("none", "pre", "post"):
            raise ValueError(f"非法 adjust={self.adjust!r}")
        if self.max_adv_participation < 0:
            raise ValueError("max_adv_participation 不能为负")

    def cost_model(self) -> CostModel:
        """与 Paper 对齐的成本模型（同参数，独立实例）。"""
        return CostModel(
            commission_rate=self.commission_rate,
            commission_min=self.commission_min,
            stamp_tax=self.stamp_tax,
            slippage_bps=self.slippage_bps,
        )

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["start"] = self.start.isoformat()
        d["end"] = self.end.isoformat()
        return d
