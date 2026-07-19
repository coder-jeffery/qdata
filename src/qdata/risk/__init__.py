"""风控前置：下单前校验（涨跌停 / 停牌 / 整手 / 资金与持仓限额）。

策略与券商之间必须经过本模块；Paper / 仿真 / 实盘共用同一套规则。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from qdata.brokers.base import OrderRequest
from qdata.constants import LOT_RULE, board_of, limit_prices, round_lot
from qdata.trading.cost import CostModel


@dataclass
class RiskVerdict:
    ok: bool
    reasons: list[str] = field(default_factory=list)
    adjusted_qty: int | None = None  # 若因整手下调

    @property
    def message(self) -> str:
        return "; ".join(self.reasons) if self.reasons else "OK"


@dataclass
class RiskLimits:
    """账户级限额（纸交易 / 仿真可配）。"""

    max_order_value: float = 0.0       # 0=不限制单笔金额
    max_position_value: float = 0.0    # 0=不限制单票市值
    max_gross_exposure: float = 0.0    # 0=不限制总持仓市值
    reject_limit_up_buy: bool = True
    reject_limit_down_sell: bool = True
    reject_suspended: bool = True


def _quote_row(quotes: pd.DataFrame | None, code: str) -> pd.Series | None:
    if quotes is None or quotes.empty or "exchange_code" not in quotes.columns:
        return None
    m = quotes[quotes["exchange_code"].astype(str) == code]
    if m.empty:
        return None
    return m.iloc[0]


def check_order(
    order: OrderRequest,
    *,
    cash: float,
    positions: pd.DataFrame | None = None,
    quote: pd.Series | dict | None = None,
    quotes: pd.DataFrame | None = None,
    limits: RiskLimits | None = None,
    cost: CostModel | None = None,
) -> RiskVerdict:
    """返回风控裁决；不修改券商状态。

    ``cost`` 若提供，买入现金校验含滑点后名义 + 费用（与 Paper/回测对齐）。
    """
    limits = limits or RiskLimits()
    reasons: list[str] = []
    code = order.exchange_code.strip().upper()
    side = order.side.strip().lower()
    qty = int(order.quantity)

    if side not in ("buy", "sell"):
        return RiskVerdict(False, [f"非法 side={order.side!r}"])
    if qty <= 0:
        return RiskVerdict(False, ["quantity 必须 > 0"])

    try:
        board = board_of(code)
    except ValueError as e:
        return RiskVerdict(False, [str(e)])

    min_qty, step = LOT_RULE[board]
    if qty < min_qty:
        return RiskVerdict(False, [f"低于最小下单量 {min_qty}（{board.value}）"])
    adj = round_lot(qty, board)
    if adj != qty:
        # 科创板 step=1 时 adj==qty；主板必须整百
        if step > 1 and qty % step != 0:
            reasons.append(f"非整手：已建议下调至 {adj}（step={step}）")
            if adj <= 0:
                return RiskVerdict(False, reasons)
            qty = adj
        elif adj < qty and step == 1 and qty < min_qty:
            return RiskVerdict(False, [f"低于最小下单量 {min_qty}"])

    q = quote
    if q is None:
        row = _quote_row(quotes, code)
        q = row.to_dict() if row is not None else None
    if isinstance(q, pd.Series):
        q = q.to_dict()

    price = order.price
    if price is None and q is not None:
        price = float(q.get("price") or q.get("ask") or q.get("bid") or 0) or None
    if price is None or price <= 0:
        return RiskVerdict(False, ["缺少有效价格（限价或行情）"])

    if q is not None and limits.reject_suspended:
        sus = q.get("is_suspended")
        px = float(q.get("price") or 0)
        vol = float(q.get("volume") or 0)
        if sus in (1, True, "1") or (px <= 0 and vol <= 0):
            reasons.append("疑似停牌/无有效行情，拒绝下单")
            return RiskVerdict(False, reasons)

    if q is not None:
        pre = float(q.get("pre_close") or 0)
        is_st = bool(int(q.get("is_st") or 0)) if q.get("is_st") is not None else False
        up = q.get("up_limit")
        down = q.get("down_limit")
        if pre > 0 and (up is None or down is None):
            up_c, down_c = limit_prices(pre, board, is_st)
            up = up if up is not None else up_c
            down = down if down is not None else down_c
        if up is not None and limits.reject_limit_up_buy and side == "buy":
            if abs(float(price) - float(up)) < 1e-6 or float(price) >= float(up) - 1e-9:
                # 以涨停价买入通常无法成交
                if float(q.get("price") or 0) >= float(up) - 1e-6:
                    reasons.append(f"涨停不可买（up_limit={up}）")
                    return RiskVerdict(False, reasons)
        if down is not None and limits.reject_limit_down_sell and side == "sell":
            if float(q.get("price") or 0) <= float(down) + 1e-6:
                reasons.append(f"跌停不可卖（down_limit={down}）")
                return RiskVerdict(False, reasons)

    notional = float(price) * qty
    if limits.max_order_value > 0 and notional > limits.max_order_value + 1e-6:
        reasons.append(
            f"单笔金额 {notional:.2f} 超过限额 {limits.max_order_value:.2f}"
        )
        return RiskVerdict(False, reasons)

    if side == "buy":
        if cost is not None:
            _, slip_notional, fee = cost.buy_cash_need(float(price), qty)
            need = slip_notional + fee
        else:
            need = notional
        if need > cash + 1e-6:
            reasons.append(f"现金不足：need={need:.2f} cash={cash:.2f}")
            return RiskVerdict(False, reasons)
    else:
        pos_qty = 0
        if positions is not None and not positions.empty:
            col = "exchange_code" if "exchange_code" in positions.columns else None
            qty_col = "quantity" if "quantity" in positions.columns else "qty"
            if col and qty_col in positions.columns:
                m = positions[positions[col].astype(str) == code]
                if not m.empty:
                    pos_qty = int(m.iloc[0][qty_col])
        if qty > pos_qty:
            reasons.append(f"持仓不足：have={pos_qty} sell={qty}")
            return RiskVerdict(False, reasons)

    if limits.max_position_value > 0 and side == "buy":
        # 近似：成交后该票市值
        cur_val = 0.0
        if positions is not None and not positions.empty and "market_value" in positions.columns:
            m = positions[positions["exchange_code"].astype(str) == code]
            if not m.empty:
                cur_val = float(m.iloc[0]["market_value"])
        if cur_val + notional > limits.max_position_value + 1e-6:
            reasons.append("超过单票持仓市值限额")
            return RiskVerdict(False, reasons)

    if reasons and adj != order.quantity and adj > 0:
        return RiskVerdict(True, reasons, adjusted_qty=adj)
    if adj != order.quantity and adj > 0 and step > 1:
        return RiskVerdict(True, [f"整手调整 {order.quantity}→{adj}"], adjusted_qty=adj)
    return RiskVerdict(True, [], adjusted_qty=None)
