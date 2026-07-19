"""BacktestEngine：日频编排。"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any

import pandas as pd

from qdata.api.data_api import DataAPI
from qdata.research.backtest.broker import BrokerSim
from qdata.research.backtest.config import BacktestConfig
from qdata.research.backtest.data_gate import DataGate
from qdata.research.backtest.ledger import PortfolioLedger
from qdata.research.backtest.metrics import compute_metrics
from qdata.research.backtest.signals import FromWeightFrame, WeightSignalProvider
from qdata.research.backtest.store import RunStore, build_meta, new_run_id
from qdata.research.backtest.types import BacktestResult, DailyResult, Fill

logger = logging.getLogger(__name__)


class BacktestEngine:
    def __init__(
        self,
        cfg: BacktestConfig,
        *,
        api: DataAPI | None = None,
        gate: DataGate | None = None,
    ) -> None:
        self.cfg = cfg
        self.gate = gate or DataGate(cfg, api=api)
        self.broker = BrokerSim(cfg)

    def run(self, signals: WeightSignalProvider) -> BacktestResult:
        cfg = self.cfg
        days = self.gate.trading_days()
        if not days:
            raise RuntimeError(f"区间无交易日: {cfg.start}~{cfg.end}")

        # 预加载信号涉及代码 + 持仓可能代码 + 基准
        codes: set[str] = set()
        if hasattr(signals, "all_codes"):
            codes.update(signals.all_codes())  # type: ignore[attr-defined]
        if cfg.benchmark:
            codes.add(cfg.benchmark)
        # 扫一遍信号日收集代码（若无 all_codes）
        if not codes:
            for d in days:
                w = signals.weight_on(d)
                if w is not None and not w.empty:
                    codes.update(w["exchange_code"].astype(str).tolist())
        self.gate.ensure_loaded(codes)

        ledger = PortfolioLedger(cfg.initial_cash)
        pending: dict[dt.date, pd.DataFrame] = {}
        fills_all: list[Fill] = []
        equity_rows: list[dict[str, Any]] = []
        pos_rows: list[dict[str, Any]] = []
        warnings: list[str] = []

        next_day = {days[i]: days[i + 1] for i in range(len(days) - 1)}

        prev_nav: float | None = None
        for d in days:
            # 1) 执行待成交调仓
            day_fills: list[Fill] = []
            turnover = 0.0
            if d in pending:
                w = pending.pop(d)
                codes_d = set(w["exchange_code"].astype(str)) | set(ledger.shares)
                bars = self.gate.bars_on(d, codes_d)
                # 估价用复权 open（bars.open 已复权）
                day_fills = self.broker.rebalance_to_weights(d, w, ledger, bars)
                fills_all.extend(day_fills)
                # 换手：成交额 / nav（成交前权益近似用成交后 mark）
                marks = self.gate.mark_prices(d, set(ledger.shares) | codes_d)
                nav_approx = ledger.nav(marks) or cfg.initial_cash
                traded = sum(f.shares * f.price for f in day_fills if f.accepted)
                turnover = float(traded / nav_approx) if nav_approx > 0 else 0.0

            # 2) 收盘估值
            mark_codes = set(ledger.shares)
            if cfg.benchmark:
                mark_codes.add(cfg.benchmark)
            marks = self.gate.mark_prices(d, mark_codes)
            snap = ledger.snapshot(d, marks)
            ret = 0.0 if prev_nav is None or prev_nav <= 0 else snap.nav / prev_nav - 1.0
            prev_nav = snap.nav
            n_fills = sum(1 for f in day_fills if f.accepted)
            n_rejects = sum(1 for f in day_fills if f.rejected_reason)
            cash_ratio = snap.cash / snap.nav if snap.nav > 0 else 1.0
            equity_rows.append(
                {
                    "trade_date": d,
                    "nav": snap.nav,
                    "ret": ret,
                    "cash": snap.cash,
                    "market_value": snap.market_value,
                    "n_positions": len(snap.positions),
                    "turnover": turnover,
                    "cash_ratio": cash_ratio,
                    "n_fills": n_fills,
                    "n_rejects": n_rejects,
                }
            )
            for code, sh in snap.positions.items():
                pos_rows.append(
                    {"trade_date": d, "exchange_code": code, "shares": sh}
                )

            # 3) 收盘后信号 → 下一成交日
            w = signals.weight_on(d)
            if w is not None and not w.empty:
                exec_d = next_day.get(d)
                if exec_d is None:
                    msg = f"末日信号丢弃（无下一交易日）: {d}"
                    logger.warning(msg)
                    warnings.append(msg)
                else:
                    pending[exec_d] = w

        equity = pd.DataFrame(equity_rows)
        fills_df = _fills_to_df(fills_all)
        pos_df = pd.DataFrame(pos_rows) if pos_rows else pd.DataFrame(
            columns=["trade_date", "exchange_code", "shares"]
        )

        bench = None
        bench_mode = "unavailable"
        if cfg.benchmark:
            bench, bench_mode = self.gate.benchmark_returns(cfg.benchmark)
            if bench is None or bench.empty:
                warnings.append(f"benchmark 无数据: {cfg.benchmark}")
                bench_mode = "unavailable"

        metrics = compute_metrics(
            equity,
            benchmark_rets=bench if bench is not None and not bench.empty else None,
        )
        metrics["n_rejects"] = float(sum(1 for f in fills_all if f.rejected_reason))
        metrics["n_fills"] = float(sum(1 for f in fills_all if f.accepted))
        reject_reasons: dict[str, int] = {}
        for f in fills_all:
            if f.rejected_reason:
                reject_reasons[f.rejected_reason] = reject_reasons.get(f.rejected_reason, 0) + 1
        for reason, cnt in reject_reasons.items():
            metrics[f"reject_{reason}"] = float(cnt)

        sig_meta = signals.meta() if hasattr(signals, "meta") else {}
        run_id = new_run_id(cfg, sig_meta)
        meta = build_meta(
            cfg,
            dataset_version=self.gate.dataset_version,
            signal_meta=sig_meta,
            run_id=run_id,
            extra={
                "warnings": warnings,
                "benchmark": cfg.benchmark,
                "benchmark_mode": bench_mode,
                "benchmark_ok": bench_mode != "unavailable",
                "reject_reasons": reject_reasons,
            },
        )

        result = BacktestResult(
            meta=meta,
            equity_curve=equity,
            fills=fills_df,
            positions_panel=pos_df,
            metrics=metrics,
            daily=[
                DailyResult(
                    trade_date=r["trade_date"],
                    nav=r["nav"],
                    ret=r["ret"],
                    turnover=r["turnover"],
                    n_fills=int(r["n_fills"]),
                    n_rejects=int(r["n_rejects"]),
                    cash_ratio=r["cash_ratio"],
                )
                for r in equity_rows
            ],
        )

        if cfg.persist:
            RunStore().save(
                result,
                to_ch=cfg.persist_ch,
                tearsheet=cfg.write_tearsheet,
            )
        return result


def _fills_to_df(fills: list[Fill]) -> pd.DataFrame:
    if not fills:
        return pd.DataFrame(
            columns=[
                "trade_date",
                "exchange_code",
                "side",
                "shares",
                "price",
                "fee",
                "rejected_reason",
            ]
        )
    return pd.DataFrame(
        [
            {
                "trade_date": f.trade_date,
                "exchange_code": f.exchange_code,
                "side": f.side,
                "shares": f.shares,
                "price": f.price,
                "fee": f.fee,
                "rejected_reason": f.rejected_reason,
            }
            for f in fills
        ]
    )


def run_backtest(
    cfg: BacktestConfig,
    signals: WeightSignalProvider | pd.DataFrame,
    *,
    api: DataAPI | None = None,
) -> BacktestResult:
    """便捷入口：DataFrame 权重自动包成 FromWeightFrame。"""
    if isinstance(signals, pd.DataFrame):
        signals = FromWeightFrame(signals)
    return BacktestEngine(cfg, api=api).run(signals)
