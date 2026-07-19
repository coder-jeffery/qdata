"""RunStore：回测结果落 Lake（+ 可选 ClickHouse / HTML）。"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from hashlib import sha1
from pathlib import Path
from typing import Any
from uuid import uuid4

import pandas as pd

from qdata.config import settings
from qdata.research.backtest.config import BacktestConfig
from qdata.research.backtest.types import BacktestResult

logger = logging.getLogger(__name__)

PRICE_MODEL = "post_adjust_nav_raw_limits"

_CH_DDL = """
CREATE TABLE IF NOT EXISTS backtest_run
(
    run_id           String,
    created_at       DateTime,
    engine_version   LowCardinality(String),
    dataset_version  String,
    factor           String DEFAULT '',
    factor_version   LowCardinality(String) DEFAULT 'v1',
    universe         String DEFAULT '',
    execution        LowCardinality(String),
    benchmark        String DEFAULT '',
    benchmark_mode   LowCardinality(String) DEFAULT '',
    run_name         String DEFAULT '',
    metrics_json     String DEFAULT '',
    meta_json        String DEFAULT ''
)
ENGINE = MergeTree
ORDER BY (created_at, run_id);

CREATE TABLE IF NOT EXISTS backtest_equity
(
    run_id       String,
    trade_date   Date,
    nav          Float64,
    ret          Float64,
    cash         Float64,
    market_value Float64,
    turnover     Float64,
    cash_ratio   Float64,
    n_positions  UInt32
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(trade_date)
ORDER BY (run_id, trade_date);
"""


def _run_id(cfg: BacktestConfig, extra: dict[str, Any] | None = None) -> str:
    payload = {**cfg.to_dict(), **(extra or {})}
    h = sha1(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()[:10]
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{ts}_{h}"


def build_meta(
    cfg: BacktestConfig,
    *,
    dataset_version: str,
    signal_meta: dict[str, Any] | None = None,
    run_id: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    sig = signal_meta or {}
    meta: dict[str, Any] = {
        "run_id": run_id,
        "engine_version": cfg.engine_version,
        "dataset_version": dataset_version,
        "factor": sig.get("factor"),
        "factor_version": sig.get("factor_version", "v1"),
        "universe": sig.get("universe"),
        "weight_method": sig.get("weight_method"),
        "execution": cfg.execution,
        "price_model": PRICE_MODEL,
        "run_name": cfg.run_name,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "config": cfg.to_dict(),
    }
    if extra:
        meta.update(extra)
    return meta


def ensure_backtest_tables() -> None:
    from qdata import db

    ch = db.client()
    for stmt in _CH_DDL.strip().split(";"):
        s = stmt.strip()
        if s:
            ch.command(s)


class RunStore:
    def __init__(self, root: Path | None = None) -> None:
        base = root or (settings().lake_root / "backtest" / "runs")
        self.root = Path(base)

    def save(self, result: BacktestResult, *, to_ch: bool = True, tearsheet: bool = True) -> Path:
        run_id = str(result.meta.get("run_id") or uuid4().hex)
        out_dir = self.root / run_id
        out_dir.mkdir(parents=True, exist_ok=True)

        (out_dir / "meta.json").write_text(
            json.dumps(result.meta, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        (out_dir / "metrics.json").write_text(
            json.dumps(result.metrics, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        if result.equity_curve is not None and not result.equity_curve.empty:
            result.equity_curve.to_parquet(out_dir / "equity.parquet", index=False)
        else:
            pd.DataFrame().to_parquet(out_dir / "equity.parquet", index=False)
        if result.fills is not None and not result.fills.empty:
            result.fills.to_parquet(out_dir / "fills.parquet", index=False)
        else:
            pd.DataFrame().to_parquet(out_dir / "fills.parquet", index=False)
        if result.positions_panel is not None and not result.positions_panel.empty:
            result.positions_panel.to_parquet(out_dir / "positions.parquet", index=False)

        if tearsheet:
            try:
                from qdata.research.backtest.tearsheet import write_tearsheet_html

                write_tearsheet_html(result, out_dir / "tearsheet.html")
            except Exception as e:
                logger.warning("tearsheet 写入失败: %s", e)

        if to_ch:
            try:
                self._save_ch(result)
            except Exception as e:
                logger.warning("ClickHouse 回测归档失败（Lake 已保存）: %s", e)

        logger.info("backtest run saved → %s", out_dir)
        return out_dir

    def _save_ch(self, result: BacktestResult) -> None:
        from qdata import db

        ensure_backtest_tables()
        run_id = str(result.meta.get("run_id"))
        created = result.meta.get("created_at") or datetime.now(timezone.utc).isoformat()
        try:
            created_dt = pd.Timestamp(created).to_pydatetime().replace(tzinfo=None)
        except Exception:
            created_dt = datetime.utcnow()

        # 先删同 run_id 再插（幂等）
        ch = db.client()
        ch.command(
            "ALTER TABLE backtest_run DELETE WHERE run_id = %(r)s",
            parameters={"r": run_id},
        )
        ch.command(
            "ALTER TABLE backtest_equity DELETE WHERE run_id = %(r)s",
            parameters={"r": run_id},
        )

        run_df = pd.DataFrame(
            [
                {
                    "run_id": run_id,
                    "created_at": created_dt,
                    "engine_version": str(result.meta.get("engine_version") or ""),
                    "dataset_version": str(result.meta.get("dataset_version") or ""),
                    "factor": str(result.meta.get("factor") or ""),
                    "factor_version": str(result.meta.get("factor_version") or "v1"),
                    "universe": str(result.meta.get("universe") or ""),
                    "execution": str(result.meta.get("execution") or ""),
                    "benchmark": str(result.meta.get("benchmark") or ""),
                    "benchmark_mode": str(result.meta.get("benchmark_mode") or ""),
                    "run_name": str(result.meta.get("run_name") or ""),
                    "metrics_json": json.dumps(result.metrics, ensure_ascii=False, default=str),
                    "meta_json": json.dumps(result.meta, ensure_ascii=False, default=str),
                }
            ]
        )
        db.insert_df("backtest_run", run_df)

        eq = result.equity_curve
        if eq is not None and not eq.empty:
            out = pd.DataFrame(
                {
                    "run_id": run_id,
                    "trade_date": pd.to_datetime(eq["trade_date"]).dt.date,
                    "nav": pd.to_numeric(eq.get("nav"), errors="coerce"),
                    "ret": pd.to_numeric(eq.get("ret"), errors="coerce").fillna(0.0),
                    "cash": pd.to_numeric(eq.get("cash"), errors="coerce").fillna(0.0),
                    "market_value": pd.to_numeric(eq.get("market_value"), errors="coerce").fillna(0.0),
                    "turnover": pd.to_numeric(eq.get("turnover"), errors="coerce").fillna(0.0),
                    "cash_ratio": pd.to_numeric(eq.get("cash_ratio"), errors="coerce").fillna(0.0),
                    "n_positions": pd.to_numeric(eq.get("n_positions"), errors="coerce")
                    .fillna(0)
                    .astype(int),
                }
            )
            db.insert_df("backtest_equity", out)


def new_run_id(cfg: BacktestConfig, signal_meta: dict | None = None) -> str:
    return _run_id(cfg, extra={"signal": signal_meta or {}})
