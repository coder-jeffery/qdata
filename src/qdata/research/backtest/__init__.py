"""日频回测引擎。"""

from __future__ import annotations

from qdata.research.backtest.broker import BrokerSim
from qdata.research.backtest.config import ENGINE_VERSION, BacktestConfig
from qdata.research.backtest.data_gate import DataGate
from qdata.research.backtest.engine import BacktestEngine, run_backtest
from qdata.research.backtest.ledger import PortfolioLedger
from qdata.research.backtest.metrics import compute_metrics
from qdata.research.backtest.rules import (
    apply_slippage,
    calc_fee,
    can_buy,
    can_sell,
    exec_price,
    round_lot,
)
from qdata.research.backtest.signals import FromRebalanceSpec, FromWeightFrame
from qdata.research.backtest.store import RunStore, build_meta, ensure_backtest_tables
from qdata.research.backtest.tearsheet import write_tearsheet_html
from qdata.research.backtest.types import (
    BacktestResult,
    Bar,
    DailyResult,
    Fill,
    LedgerSnapshot,
    Order,
)

__all__ = [
    "ENGINE_VERSION",
    "BacktestConfig",
    "BacktestEngine",
    "BacktestResult",
    "Bar",
    "BrokerSim",
    "DailyResult",
    "DataGate",
    "Fill",
    "FromRebalanceSpec",
    "FromWeightFrame",
    "LedgerSnapshot",
    "Order",
    "PortfolioLedger",
    "RunStore",
    "apply_slippage",
    "build_meta",
    "ensure_backtest_tables",
    "write_tearsheet_html",
    "calc_fee",
    "can_buy",
    "can_sell",
    "compute_metrics",
    "exec_price",
    "round_lot",
    "run_backtest",
]
