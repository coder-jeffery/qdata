"""BrokerSim：目标权重 → 成交明细（先卖后买）。"""

from __future__ import annotations

import datetime as dt
import math

import pandas as pd

from qdata.research.backtest.config import BacktestConfig
from qdata.research.backtest.ledger import PortfolioLedger
from qdata.research.backtest.rules import (
    calc_fee,
    can_buy,
    can_sell,
    exec_price,
    round_lot,
)
from qdata.research.backtest.types import Bar, Fill


def _reject(
    d: dt.date,
    code: str,
    side: str,
    reason: str,
) -> Fill:
    return Fill(
        trade_date=d,
        exchange_code=code,
        side=side,  # type: ignore[arg-type]
        shares=0,
        price=0.0,
        fee=0.0,
        rejected_reason=reason,
    )


class BrokerSim:
    def __init__(self, cfg: BacktestConfig) -> None:
        self.cfg = cfg

    def rebalance_to_weights(
        self,
        d_exec: dt.date,
        target_weights: pd.DataFrame,
        ledger: PortfolioLedger,
        bars: dict[str, Bar],
    ) -> list[Fill]:
        """按目标权重调仓；拒单写入 fills，不抛业务异常。"""
        cfg = self.cfg
        fills: list[Fill] = []

        wdf = self._normalize_weights(target_weights)
        if wdf.empty:
            return fills

        # 估价：用执行基准价（未加滑点）估权益
        mark: dict[str, float] = {}
        for code, bar in bars.items():
            px = bar.open if cfg.execution == "next_open" else bar.close
            if px > 0 and math.isfinite(px):
                mark[code] = float(px)
        for code in list(ledger.shares):
            if code not in mark and code in bars:
                bar = bars[code]
                px = bar.open if cfg.execution == "next_open" else bar.close
                if px > 0 and math.isfinite(px):
                    mark[code] = float(px)

        equity = ledger.nav(mark)
        if equity <= 0 or not math.isfinite(equity):
            return fills

        # 目标股数
        targets: dict[str, int] = {}
        for _, row in wdf.iterrows():
            code = str(row["exchange_code"])
            weight = float(row["weight"])
            bar = bars.get(code)
            if bar is None:
                fills.append(_reject(d_exec, code, "buy", "no_bar"))
                targets[code] = ledger.position(code)
                continue
            px = mark.get(code)
            if px is None or px <= 0:
                fills.append(_reject(d_exec, code, "buy", "no_price"))
                targets[code] = ledger.position(code)
                continue
            raw_shares = weight * equity / px
            targets[code] = round_lot(
                raw_shares,
                cfg.lot_size,
                "buy",
                allow_partial=cfg.allow_partial_lot,
            )

        # 未在目标中的持仓 → 清零
        for code in list(ledger.shares):
            if code not in targets:
                targets[code] = 0

        # 先卖
        sells: list[tuple[str, int, float]] = []
        for code, tgt in targets.items():
            cur = ledger.position(code)
            delta = int(tgt) - cur
            if delta >= 0:
                continue
            qty = -delta
            bar = bars.get(code)
            if bar is None:
                fills.append(_reject(d_exec, code, "sell", "no_bar"))
                continue
            ok, reason = can_sell(bar, eps=cfg.limit_eps)
            if not ok:
                fills.append(_reject(d_exec, code, "sell", reason or "reject"))
                continue
            price = exec_price(bar, "sell", cfg)
            sells.append((code, qty, price))

        for code, qty, price in sells:
            fee = calc_fee(qty * price, "sell", cfg)
            fill = Fill(
                trade_date=d_exec,
                exchange_code=code,
                side="sell",
                shares=qty,
                price=price,
                fee=fee,
            )
            ledger.apply_fill(fill)
            fills.append(fill)

        # 再买：按目标权重从高到低，现金耗尽为止
        buys: list[tuple[str, int, float, float]] = []  # code, qty, price, weight
        w_map = {str(r["exchange_code"]): float(r["weight"]) for _, r in wdf.iterrows()}
        for code, tgt in targets.items():
            cur = ledger.position(code)
            delta = int(tgt) - cur
            if delta <= 0:
                continue
            bar = bars.get(code)
            if bar is None:
                fills.append(_reject(d_exec, code, "buy", "no_bar"))
                continue
            ok, reason = can_buy(bar, eps=cfg.limit_eps)
            if not ok:
                fills.append(_reject(d_exec, code, "buy", reason or "reject"))
                continue
            price = exec_price(bar, "buy", cfg)
            # ADV / 当日成交量占比约束
            if cfg.max_adv_participation > 0 and bar.volume is not None and bar.volume > 0:
                max_sh = int(bar.volume * cfg.max_adv_participation)
                max_sh = round_lot(
                    max_sh, cfg.lot_size, "buy", allow_partial=cfg.allow_partial_lot
                )
                if max_sh <= 0:
                    fills.append(_reject(d_exec, code, "buy", "adv_limit"))
                    continue
                if delta > max_sh:
                    delta = max_sh
            buys.append((code, delta, price, w_map.get(code, 0.0)))

        buys.sort(key=lambda x: x[3], reverse=True)

        for code, qty, price, _w in buys:
            # 在现金约束下尽量买整手
            while qty > 0:
                fee = calc_fee(qty * price, "buy", cfg)
                need = qty * price + fee
                if need <= ledger.cash + 1e-9:
                    break
                # 下调一手
                step = cfg.lot_size if not cfg.allow_partial_lot else 1
                qty -= step
            if qty <= 0:
                fills.append(_reject(d_exec, code, "buy", "insufficient_cash"))
                continue
            fee = calc_fee(qty * price, "buy", cfg)
            fill = Fill(
                trade_date=d_exec,
                exchange_code=code,
                side="buy",
                shares=qty,
                price=price,
                fee=fee,
            )
            ledger.apply_fill(fill)
            fills.append(fill)

        return fills

    def _normalize_weights(self, target_weights: pd.DataFrame) -> pd.DataFrame:
        cfg = self.cfg
        if target_weights is None or target_weights.empty:
            return pd.DataFrame(columns=["exchange_code", "weight"])
        df = target_weights.copy()
        if "exchange_code" not in df.columns or "weight" not in df.columns:
            raise ValueError("target_weights 需含 exchange_code, weight")
        df["exchange_code"] = df["exchange_code"].astype(str)
        df["weight"] = pd.to_numeric(df["weight"], errors="coerce")
        df = df.dropna(subset=["weight"])
        df = df[df["weight"] > 0]
        if df.empty:
            return pd.DataFrame(columns=["exchange_code", "weight"])
        s = float(df["weight"].sum())
        if s <= 0:
            return pd.DataFrame(columns=["exchange_code", "weight"])
        if abs(s - 1.0) > cfg.weight_sum_tol:
            if cfg.renormalize_weights:
                df["weight"] = df["weight"] / s
            else:
                raise ValueError(f"权重和={s} 超出容差且 renormalize_weights=False")
        return df[["exchange_code", "weight"]].reset_index(drop=True)
