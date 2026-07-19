"""A3 调仓 / Paper 工作流：信号权重 → 目标持仓 → 差额订单 → Gateway/Paper。"""

from __future__ import annotations

import datetime as dt
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

import pandas as pd

from qdata.apps.signal import build_signal, load_signal
from qdata.brokers.base import OrderRequest
from qdata.brokers.paper import PaperBroker
from qdata.config import settings
from qdata.risk import RiskLimits
from qdata.trading import TradingGateway
from qdata.trading.cost import DEFAULT_COST

logger = logging.getLogger(__name__)

LOT_SIZE = 100


def _sessions_root() -> Path:
    return settings().lake_root / "paper_sessions"


def load_signal_weights(
    signal_dir: str | Path | None = None,
    *,
    asof: dt.date | None = None,
    signal_id: str | None = None,
) -> pd.DataFrame:
    """从信号目录或 asof+signal_id 加载权重表。"""
    if signal_dir is not None:
        data = load_signal(signal_dir)
        return data["weights"]
    if asof is None or not signal_id:
        raise ValueError("需提供 signal_dir 或 (asof + signal_id)")
    path = settings().lake_root / "signals" / asof.isoformat() / signal_id
    return load_signal(path)["weights"]


def weights_to_target_shares(
    weights_df: pd.DataFrame,
    total_asset: float,
    prices: pd.Series | dict[str, float],
    *,
    lot_size: int = LOT_SIZE,
) -> pd.Series:
    """目标权重 × 总资产 → 目标股数（整手向下取整）。"""
    if weights_df is None or weights_df.empty:
        return pd.Series(dtype=int)

    px = prices if isinstance(prices, pd.Series) else pd.Series(prices, dtype=float)
    out: dict[str, int] = {}
    for _, row in weights_df.iterrows():
        code = str(row["exchange_code"])
        w = float(row["weight"])
        price = float(px.get(code, 0) or 0)
        if price <= 0 or w <= 0:
            out[code] = 0
            continue
        target_value = total_asset * w
        raw_shares = int(target_value / price)
        shares = (raw_shares // lot_size) * lot_size
        out[code] = max(shares, 0)
    return pd.Series(out, dtype=int)


def diff_orders(
    current_positions: pd.DataFrame | pd.Series | dict[str, int],
    target_shares: pd.Series | dict[str, int],
) -> list[OrderRequest]:
    """相对当前持仓生成 buy/sell 订单清单。"""
    cur: dict[str, int] = {}
    if isinstance(current_positions, pd.DataFrame):
        if not current_positions.empty and "exchange_code" in current_positions.columns:
            for _, r in current_positions.iterrows():
                cur[str(r["exchange_code"])] = int(r.get("quantity") or 0)
    elif isinstance(current_positions, pd.Series):
        cur = {str(k): int(v) for k, v in current_positions.items()}
    elif isinstance(current_positions, dict):
        cur = {str(k): int(v) for k, v in current_positions.items()}

    tgt = target_shares if isinstance(target_shares, pd.Series) else pd.Series(target_shares, dtype=int)
    all_codes = sorted(set(cur) | set(tgt.index.astype(str)))
    orders: list[OrderRequest] = []
    for code in all_codes:
        have = int(cur.get(code, 0))
        want = int(tgt.get(code, 0))
        delta = want - have
        if delta > 0:
            orders.append(OrderRequest(exchange_code=code, side="buy", quantity=delta))
        elif delta < 0:
            orders.append(OrderRequest(exchange_code=code, side="sell", quantity=-delta))
    return orders


def _quotes_for_codes(codes: list[str], trade_date: dt.date | None = None) -> pd.DataFrame:
    """从 CH daily_bar 构造 Gateway 行情。"""
    if not codes:
        return pd.DataFrame()
    try:
        from qdata import db

        if trade_date is not None:
            df = db.query_df(
                """
                SELECT m.exchange_code, b.close AS price, b.pre_close, b.open, b.high, b.low,
                       b.volume, b.amount, b.up_limit, b.down_limit, b.is_suspended, b.is_st
                FROM daily_bar b
                INNER JOIN security_master m USING (security_id)
                WHERE b.trade_date = %(d)s AND m.exchange_code IN %(codes)s
                """,
                {"d": trade_date, "codes": tuple(codes)},
            )
        else:
            df = db.query_df(
                """
                SELECT m.exchange_code, b.close AS price, b.pre_close, b.open, b.high, b.low,
                       b.volume, b.amount, b.up_limit, b.down_limit, b.is_suspended, b.is_st
                FROM daily_bar b
                INNER JOIN security_master m USING (security_id)
                WHERE m.exchange_code IN %(codes)s
                ORDER BY b.trade_date DESC
                LIMIT 1 BY m.exchange_code
                """,
                {"codes": tuple(codes)},
            )
        if df is None or df.empty:
            return pd.DataFrame()
        df["bid"] = df["price"]
        df["ask"] = df["price"]
        return df
    except Exception as e:
        logger.warning("quotes 查询失败: %s", e)
        return pd.DataFrame()


def run_paper_rebalance(
    *,
    signal_path: str | Path | None = None,
    date: dt.date | None = None,
    factor: str | None = None,
    universe: str = "000905.SH",
    top_n: int = 50,
    weight_method: Literal["equal", "factor_rank", "industry_neutral"] = "equal",
    industry_level: Literal["sw_l1", "sw_l2"] = "sw_l1",
    version: str | None = None,
    cash: float | None = None,
    session_id: str | None = None,
    persist: bool = True,
    extra_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """信号 → Paper 调仓 → session 落盘。"""
    if signal_path is not None:
        sig_data = load_signal(signal_path)
        weights = sig_data["weights"]
        meta_in = sig_data["meta"]
        asof = dt.date.fromisoformat(str(meta_in.get("asof", date or dt.date.today())))
    else:
        if date is None or factor is None:
            raise ValueError("无 signal_path 时需 date + factor")
        built = build_signal(
            date,
            universe=universe,
            factor=factor,
            top_n=top_n,
            weight_method=weight_method,
            industry_level=industry_level,
            version=version,
            persist=True,
        )
        weights = built["weights"]
        meta_in = built["meta"]
        asof = date
        signal_path = built.get("path")

    if weights.empty:
        raise ValueError("信号权重为空")

    codes = weights["exchange_code"].astype(str).tolist()
    quotes = _quotes_for_codes(codes, asof)
    if quotes.empty:
        raise ValueError("无法获取行情（daily_bar）")

    prices = quotes.set_index("exchange_code")["price"]
    initial_cash = cash if cash is not None else float(settings().paper_initial_cash)
    broker = PaperBroker(initial_cash=initial_cash, cost=DEFAULT_COST)
    gw = TradingGateway(broker, limits=RiskLimits())
    gw.connect()
    gw.update_quotes(quotes)

    account_before = gw.account()
    total_asset = float(account_before.get("total_asset") or initial_cash)
    target = weights_to_target_shares(weights, total_asset, prices)
    current = gw.positions()
    orders_req = diff_orders(current, target)

    order_records: list[dict[str, Any]] = []
    reject_records: list[dict[str, Any]] = []
    for req in orders_req:
        res = gw.place(req)
        rec = {
            "exchange_code": req.exchange_code,
            "side": req.side,
            "quantity": req.quantity,
            "risk_ok": res.risk.ok,
            "risk_message": res.risk.message,
            "order_ok": res.order.ok if res.order else False,
            "order_id": res.order.order_id if res.order else "",
            "message": res.order.message if res.order else "",
        }
        if res.ok and res.order and res.order.raw:
            rec.update(res.order.raw)
            order_records.append(rec)
        else:
            reject_records.append(rec)

    account_after = gw.account()
    positions = gw.positions()
    gw.disconnect()

    sid = session_id or f"ps_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{uuid4().hex[:8]}"
    meta: dict[str, Any] = {
        "session_id": sid,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "asof": asof.isoformat(),
        "signal_path": str(signal_path) if signal_path else None,
        "signal_meta": meta_in,
        "initial_cash": initial_cash,
        "account_before": account_before,
        "account_after": account_after,
        "n_orders": len(orders_req),
        "n_filled": len(order_records),
        "n_rejected": len(reject_records),
        "cost_model": DEFAULT_COST.to_dict(),
    }
    if extra_meta:
        meta.update(extra_meta)

    out_dir = _sessions_root() / sid
    path: str | None = None
    if persist:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        (out_dir / "account.json").write_text(
            json.dumps(account_after, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        if order_records:
            pd.DataFrame(order_records).to_parquet(out_dir / "orders.parquet", index=False)
        else:
            pd.DataFrame(columns=["exchange_code", "side", "quantity", "order_id"]).to_parquet(
                out_dir / "orders.parquet", index=False
            )
        if not positions.empty:
            positions.to_parquet(out_dir / "positions.parquet", index=False)
        else:
            pd.DataFrame(columns=["exchange_code", "quantity"]).to_parquet(
                out_dir / "positions.parquet", index=False
            )
        if reject_records:
            pd.DataFrame(reject_records).to_parquet(out_dir / "rejects.parquet", index=False)
        path = str(out_dir)

    return {
        "session_id": sid,
        "meta": meta,
        "orders": order_records,
        "rejects": reject_records,
        "positions": positions,
        "account": account_after,
        "path": path,
    }


def run_paper_from_experiment(
    experiment_id: str,
    *,
    asof: dt.date | None = None,
    rank_by: str = "sharpe",
    cash: float | None = None,
    version: str | None = None,
    session_id: str | None = None,
    persist: bool = True,
) -> dict[str, Any]:
    """A308：显式开关路径 — 实验最优 cell → build_signal → Paper 调仓。

    默认不启用；须调用本函数或 CLI ``--from-experiment``。
    """
    from qdata.apps.experiment import load_experiment, pick_best_cell

    exp = load_experiment(experiment_id)
    cell = pick_best_cell(exp["summary"], rank_by=rank_by)
    spec = (exp["meta"] or {}).get("spec") or {}

    if asof is None:
        end_s = spec.get("end")
        asof = dt.date.fromisoformat(str(end_s)) if end_s else dt.date.today()

    ds_version = version
    if ds_version is None:
        ds_version = (exp["meta"] or {}).get("dataset_version") or spec.get("version")

    wm = cell["weight_method"]
    if wm not in ("equal", "factor_rank", "industry_neutral"):
        raise ValueError(f"不支持的 weight_method: {wm}")

    link = {
        "from_experiment": {
            "enabled": True,
            "experiment_id": experiment_id,
            "experiment_path": exp.get("path"),
            "rank_by": rank_by,
            "selected_cell": cell,
            "asof": asof.isoformat(),
            "dataset_version": ds_version,
        }
    }

    result = run_paper_rebalance(
        date=asof,
        factor=cell["factor"],
        universe=cell["universe"],
        top_n=cell["top_n"],
        weight_method=wm,  # type: ignore[arg-type]
        industry_level=cell["industry_level"],  # type: ignore[arg-type]
        version=ds_version,
        cash=cash,
        session_id=session_id,
        persist=persist,
        extra_meta=link,
    )
    result["selected_cell"] = cell
    result["experiment_id"] = experiment_id
    return result


def mark_session_eod(
    session_id: str,
    mark_date: dt.date | None = None,
    *,
    persist: bool = True,
) -> dict[str, Any]:
    """A306 日终盯市：用 mark_date 收盘价重估持仓，不改变仓位与现金。

    落盘：
      paper_sessions/<id>/marks.parquet（追加）
      paper_sessions/<id>/mark_latest.json
      meta.json 更新 last_mark_*
    """
    from qdata.apps.paper_store import load_session

    data = load_session(session_id)
    meta = data["meta"]
    account = data["account"] or {}
    positions = data["positions"]
    out_dir = Path(data["path"])

    cash = float(account.get("cash") or meta.get("account_after", {}).get("cash") or 0)
    initial_cash = float(meta.get("initial_cash") or cash)
    asof_s = str(meta.get("asof") or "")
    asof = dt.date.fromisoformat(asof_s) if asof_s else None

    if mark_date is None:
        mark_date = _default_mark_date(asof)

    if positions is None or positions.empty:
        mark = {
            "session_id": session_id,
            "mark_date": mark_date.isoformat(),
            "cash": cash,
            "market_value": 0.0,
            "total_asset": cash,
            "pnl_vs_initial": cash - initial_cash,
            "pnl_vs_rebalance": cash - float(
                (meta.get("account_after") or {}).get("total_asset") or cash
            ),
            "n_positions": 0,
            "marked_at": datetime.now(timezone.utc).isoformat(),
            "note": "无持仓",
        }
    else:
        codes = positions["exchange_code"].astype(str).tolist()
        quotes = _quotes_for_codes(codes, mark_date)
        if quotes.empty:
            raise ValueError(f"盯市日 {mark_date} 无行情")
        px = quotes.set_index("exchange_code")["price"].astype(float)
        rows = []
        mv = 0.0
        missing: list[str] = []
        for _, r in positions.iterrows():
            code = str(r["exchange_code"])
            qty = int(r.get("quantity") or 0)
            cost = float(r.get("cost") or 0)
            price = float(px.get(code, 0) or 0)
            if qty > 0 and price <= 0:
                missing.append(code)
            mkt = price * qty
            mv += mkt
            rows.append(
                {
                    "exchange_code": code,
                    "quantity": qty,
                    "mark_price": price,
                    "market_value": mkt,
                    "cost": cost,
                    "unrealized_pnl": mkt - cost if qty else 0.0,
                }
            )
        total = cash + mv
        reb_total = float((meta.get("account_after") or {}).get("total_asset") or total)
        note = f"缺行情 {len(missing)} 只" if missing else ""
        mark = {
            "session_id": session_id,
            "mark_date": mark_date.isoformat(),
            "cash": cash,
            "market_value": mv,
            "total_asset": total,
            "pnl_vs_initial": total - initial_cash,
            "pnl_vs_rebalance": total - reb_total,
            "return_vs_initial": (total / initial_cash - 1.0) if initial_cash else None,
            "n_positions": len(rows),
            "n_missing_quotes": len(missing),
            "positions": rows,
            "marked_at": datetime.now(timezone.utc).isoformat(),
            "note": note,
        }

    # 相对上一盯市日 PnL
    prev_total = None
    marks_path = out_dir / "marks.parquet"
    if marks_path.is_file():
        hist = pd.read_parquet(marks_path)
        if not hist.empty and "total_asset" in hist.columns:
            hist = hist.sort_values("mark_date")
            # 排除同日覆盖前的上一笔
            earlier = hist[hist["mark_date"].astype(str) < mark_date.isoformat()]
            if not earlier.empty:
                prev_total = float(earlier.iloc[-1]["total_asset"])
    if prev_total is not None:
        mark["pnl_vs_prev_mark"] = mark["total_asset"] - prev_total
    else:
        mark["pnl_vs_prev_mark"] = None

    if persist:
        _persist_mark(out_dir, meta, mark)

    return mark


def _default_mark_date(asof: dt.date | None) -> dt.date:
    """默认盯市日：优先 asof 当日（有持仓即用调仓日收盘）；否则最新日线日。"""
    from qdata import db

    if asof is not None:
        return asof
    df = db.query_df("SELECT max(trade_date) AS mx FROM daily_bar")
    if df is None or df.empty or pd.isna(df.iloc[0]["mx"]):
        return dt.date.today()
    return pd.Timestamp(df.iloc[0]["mx"]).date()


def _persist_mark(out_dir: Path, meta: dict[str, Any], mark: dict[str, Any]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    # 摘要行（不含 positions 明细）
    summary = {k: v for k, v in mark.items() if k != "positions"}
    (out_dir / "mark_latest.json").write_text(
        json.dumps(mark, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    row = pd.DataFrame([summary])
    marks_path = out_dir / "marks.parquet"
    if marks_path.is_file():
        old = pd.read_parquet(marks_path)
        # 同日覆盖
        old = old[old["mark_date"].astype(str) != str(summary["mark_date"])]
        pd.concat([old, row], ignore_index=True).to_parquet(marks_path, index=False)
    else:
        row.to_parquet(marks_path, index=False)

    # 持仓明细
    pos_rows = mark.get("positions") or []
    if pos_rows:
        pd.DataFrame(pos_rows).to_parquet(
            out_dir / f"mark_positions_{summary['mark_date']}.parquet",
            index=False,
        )

    meta["last_mark_date"] = summary["mark_date"]
    meta["last_mark_total_asset"] = summary["total_asset"]
    meta["last_mark_pnl_vs_initial"] = summary.get("pnl_vs_initial")
    meta["last_marked_at"] = summary.get("marked_at")
    (out_dir / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


def list_marks(session_id: str) -> pd.DataFrame:
    """读取 session 盯市历史。"""
    d = _sessions_root() / session_id
    p = d / "marks.parquet"
    if not p.is_file():
        return pd.DataFrame()
    return pd.read_parquet(p).sort_values("mark_date")
