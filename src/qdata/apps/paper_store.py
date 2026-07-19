"""A5 Paper 运营：读取 paper_sessions 快照。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from qdata.config import settings


def _sessions_root() -> Path:
    return settings().lake_root / "paper_sessions"


def list_sessions(limit: int = 50) -> list[dict[str, Any]]:
    """列出最近 Paper 调仓 session。"""
    root = _sessions_root()
    if not root.is_dir():
        return []
    dirs = sorted(
        [p for p in root.iterdir() if p.is_dir()],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )[:limit]
    out: list[dict[str, Any]] = []
    for d in dirs:
        mp = d / "meta.json"
        if not mp.is_file():
            continue
        try:
            meta = json.loads(mp.read_text(encoding="utf-8"))
        except Exception:
            meta = {"session_id": d.name}
        meta["path"] = str(d)
        out.append(meta)
    return out


def load_session(session_id: str) -> dict[str, Any]:
    """加载单个 session：meta / account / orders / positions / rejects。"""
    d = _sessions_root() / session_id
    if not d.is_dir():
        raise FileNotFoundError(f"session 不存在: {session_id}")

    meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
    account: dict[str, Any] = {}
    if (d / "account.json").is_file():
        account = json.loads((d / "account.json").read_text(encoding="utf-8"))

    orders = pd.read_parquet(d / "orders.parquet") if (d / "orders.parquet").is_file() else pd.DataFrame()
    positions = (
        pd.read_parquet(d / "positions.parquet") if (d / "positions.parquet").is_file() else pd.DataFrame()
    )
    rejects = pd.read_parquet(d / "rejects.parquet") if (d / "rejects.parquet").is_file() else pd.DataFrame()
    marks = pd.read_parquet(d / "marks.parquet") if (d / "marks.parquet").is_file() else pd.DataFrame()
    mark_latest: dict[str, Any] = {}
    if (d / "mark_latest.json").is_file():
        mark_latest = json.loads((d / "mark_latest.json").read_text(encoding="utf-8"))

    return {
        "session_id": session_id,
        "meta": meta,
        "account": account,
        "orders": orders,
        "positions": positions,
        "rejects": rejects,
        "marks": marks,
        "mark_latest": mark_latest,
        "path": str(d),
    }


def compare_sessions(session_ids: list[str]) -> pd.DataFrame:
    """A504：多 session 横向对比摘要（账户 / 成交 / 盯市 / 实验挂钩）。"""
    rows: list[dict[str, Any]] = []
    for sid in session_ids:
        try:
            data = load_session(sid)
        except FileNotFoundError:
            rows.append({"session_id": sid, "error": "not_found"})
            continue
        meta = data.get("meta") or {}
        account = data.get("account") or {}
        mark = data.get("mark_latest") or {}
        fe = meta.get("from_experiment") or {}
        cell = fe.get("selected_cell") or {}
        pos = data.get("positions")
        n_pos = 0 if pos is None or getattr(pos, "empty", True) else len(pos)
        rows.append(
            {
                "session_id": sid,
                "asof": meta.get("asof"),
                "created_at": meta.get("created_at"),
                "cash": account.get("cash"),
                "market_value": account.get("market_value"),
                "total_asset": account.get("total_asset"),
                "n_filled": meta.get("n_filled"),
                "n_rejected": meta.get("n_rejected"),
                "n_positions": n_pos,
                "mark_date": mark.get("mark_date") or meta.get("last_mark_date"),
                "mark_total_asset": mark.get("total_asset") or meta.get("last_mark_total_asset"),
                "pnl_vs_initial": mark.get("pnl_vs_initial") or meta.get("last_mark_pnl_vs_initial"),
                "experiment_id": fe.get("experiment_id") if fe.get("enabled") else None,
                "exp_factor": cell.get("factor"),
                "exp_method": cell.get("weight_method"),
                "signal_factor": (meta.get("signal_meta") or {}).get("factor"),
            }
        )
    return pd.DataFrame(rows)
