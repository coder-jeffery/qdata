"""回测 Dashboard 读数：优先 ClickHouse，回退 Lake Parquet。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from qdata.config import settings


@dataclass
class RunSummary:
    run_id: str
    created_at: str = ""
    factor: str = ""
    universe: str = ""
    execution: str = ""
    benchmark_mode: str = ""
    run_name: str = ""
    dataset_version: str = ""
    source: str = ""  # ch | lake


def lake_runs_root() -> Path:
    return Path(settings().lake_root) / "backtest" / "runs"


def list_runs(limit: int = 50, factor: str | None = None) -> list[RunSummary]:
    try:
        rows = _list_from_ch(limit=limit, factor=factor)
        if rows:
            return rows
    except Exception:
        pass
    return _list_from_lake(limit=limit, factor=factor)


def load_run_detail(run_id: str) -> dict[str, Any]:
    """返回 meta / metrics / equity / fills DataFrame。"""
    try:
        detail = _detail_from_ch(run_id)
        if detail.get("equity") is not None and not detail["equity"].empty:
            return detail
    except Exception:
        pass
    return _detail_from_lake(run_id)


_MATRIX_KEYS = (
    "total_return",
    "ann_return",
    "sharpe",
    "max_drawdown",
    "turnover",
    "excess_total",
    "info_ratio",
    "n_fills",
    "n_rejects",
)


def runs_metrics_matrix(limit: int = 20, factor: str | None = None) -> pd.DataFrame:
    """最近 N 条 run 的关键指标矩阵（便于横向对比）。"""
    runs = list_runs(limit=limit, factor=factor)
    rows: list[dict[str, Any]] = []
    for r in runs:
        detail = load_run_detail(r.run_id)
        m = detail.get("metrics") or {}
        meta = detail.get("meta") or {}
        row: dict[str, Any] = {
            "run_id": r.run_id,
            "factor": r.factor or meta.get("factor", ""),
            "universe": r.universe or meta.get("universe", ""),
            "execution": r.execution or meta.get("execution", ""),
            "benchmark_mode": r.benchmark_mode or meta.get("benchmark_mode", ""),
            "dataset_version": r.dataset_version or meta.get("dataset_version", ""),
        }
        for k in _MATRIX_KEYS:
            row[k] = m.get(k)
        rows.append(row)
    return pd.DataFrame(rows)


def _list_from_ch(limit: int, factor: str | None) -> list[RunSummary]:
    from qdata import db
    from qdata.research.backtest.store import ensure_backtest_tables

    ensure_backtest_tables()
    where = "WHERE 1"
    params: dict[str, Any] = {"n": int(limit)}
    if factor:
        where += " AND factor = %(f)s"
        params["f"] = factor
    df = db.query_df(
        f"""
        SELECT run_id, created_at, factor, universe, execution,
               benchmark_mode, run_name, dataset_version
        FROM backtest_run
        {where}
        ORDER BY created_at DESC
        LIMIT %(n)s
        """,
        params,
    )
    if df is None or df.empty:
        return []
    out: list[RunSummary] = []
    for _, r in df.iterrows():
        out.append(
            RunSummary(
                run_id=str(r["run_id"]),
                created_at=str(r.get("created_at") or ""),
                factor=str(r.get("factor") or ""),
                universe=str(r.get("universe") or ""),
                execution=str(r.get("execution") or ""),
                benchmark_mode=str(r.get("benchmark_mode") or ""),
                run_name=str(r.get("run_name") or ""),
                dataset_version=str(r.get("dataset_version") or ""),
                source="ch",
            )
        )
    return out


def _list_from_lake(limit: int, factor: str | None) -> list[RunSummary]:
    root = lake_runs_root()
    if not root.exists():
        return []
    runs = sorted(root.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
    out: list[RunSummary] = []
    for d in runs:
        meta_p = d / "meta.json"
        if not meta_p.exists():
            continue
        meta = json.loads(meta_p.read_text(encoding="utf-8"))
        fac = str(meta.get("factor") or "")
        if factor and fac != factor:
            continue
        out.append(
            RunSummary(
                run_id=str(meta.get("run_id") or d.name),
                created_at=str(meta.get("created_at") or ""),
                factor=fac,
                universe=str(meta.get("universe") or ""),
                execution=str(meta.get("execution") or ""),
                benchmark_mode=str(meta.get("benchmark_mode") or ""),
                run_name=str(meta.get("run_name") or ""),
                dataset_version=str(meta.get("dataset_version") or ""),
                source="lake",
            )
        )
        if len(out) >= limit:
            break
    return out


def _detail_from_ch(run_id: str) -> dict[str, Any]:
    from qdata import db
    from qdata.research.backtest.store import ensure_backtest_tables

    ensure_backtest_tables()
    meta_df = db.query_df(
        "SELECT * FROM backtest_run WHERE run_id = %(r)s LIMIT 1",
        {"r": run_id},
    )
    equity = db.query_df(
        """
        SELECT trade_date, nav, ret, cash, market_value, turnover, cash_ratio, n_positions
        FROM backtest_equity
        WHERE run_id = %(r)s
        ORDER BY trade_date
        """,
        {"r": run_id},
    )
    meta: dict[str, Any] = {}
    metrics: dict[str, Any] = {}
    if meta_df is not None and not meta_df.empty:
        row = meta_df.iloc[0]
        try:
            meta = json.loads(row.get("meta_json") or "{}")
        except Exception:
            meta = {"run_id": run_id}
        try:
            metrics = json.loads(row.get("metrics_json") or "{}")
        except Exception:
            metrics = {}
    fills = _load_lake_fills(run_id)
    return {
        "meta": meta,
        "metrics": metrics,
        "equity": equity if equity is not None else pd.DataFrame(),
        "fills": fills,
        "source": "ch",
    }


def _detail_from_lake(run_id: str) -> dict[str, Any]:
    d = lake_runs_root() / run_id
    if not d.exists():
        # 兼容 run_id 目录名不一致时按前缀搜
        matches = list(lake_runs_root().glob(f"{run_id}*")) if lake_runs_root().exists() else []
        d = matches[0] if matches else d
    meta: dict[str, Any] = {}
    metrics: dict[str, Any] = {}
    meta_p = d / "meta.json"
    metrics_p = d / "metrics.json"
    if meta_p.exists():
        meta = json.loads(meta_p.read_text(encoding="utf-8"))
    if metrics_p.exists():
        metrics = json.loads(metrics_p.read_text(encoding="utf-8"))
    equity = pd.read_parquet(d / "equity.parquet") if (d / "equity.parquet").exists() else pd.DataFrame()
    fills = pd.read_parquet(d / "fills.parquet") if (d / "fills.parquet").exists() else pd.DataFrame()
    return {
        "meta": meta,
        "metrics": metrics,
        "equity": equity,
        "fills": fills,
        "source": "lake",
        "tearsheet_path": str(d / "tearsheet.html") if (d / "tearsheet.html").exists() else "",
    }


def _load_lake_fills(run_id: str) -> pd.DataFrame:
    d = lake_runs_root() / run_id
    if (d / "fills.parquet").exists():
        return pd.read_parquet(d / "fills.parquet")
    return pd.DataFrame()
