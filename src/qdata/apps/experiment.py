"""A1 策略实验工厂：factor×weight_method 矩阵回测 + 汇总归档。"""

from __future__ import annotations

import datetime as dt
import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from hashlib import sha1
from pathlib import Path
from typing import Any, Literal

import pandas as pd

from qdata.api.data_api import DataAPI
from qdata.config import settings
from qdata.research.backtest import BacktestConfig, BacktestEngine
from qdata.research.backtest.signals import FromRebalanceSpec
from qdata.research.portfolio import RebalanceSpec

logger = logging.getLogger(__name__)

APP_PIPELINE_VERSION = "app-0.1"

Execution = Literal["next_open", "next_close"]
IndustryLevel = Literal["sw_l1", "sw_l2"]

_CH_DDL = """
CREATE TABLE IF NOT EXISTS experiment_run
(
    experiment_id    String,
    created_at       DateTime,
    app_version      LowCardinality(String),
    dataset_version  String,
    universe         String,
    execution        LowCardinality(String),
    benchmark        String DEFAULT '',
    start_date       Date,
    end_date         Date,
    n_cells          UInt32,
    n_ok             UInt32,
    n_fail           UInt32,
    summary_json     String DEFAULT '',
    meta_json        String DEFAULT ''
)
ENGINE = MergeTree
ORDER BY (created_at, experiment_id);
"""


@dataclass
class ExperimentSpec:
    start: dt.date
    end: dt.date
    universe: str = "000905.SH"
    factors: list[str] = field(default_factory=lambda: ["mom_20"])
    weight_methods: list[str] = field(default_factory=lambda: ["equal"])
    top_n: int = 50
    version: str | None = None
    execution: Execution = "next_open"
    benchmark: str | None = "000905.SH"
    industry_level: IndustryLevel = "sw_l1"
    factor_version: str = "v1"
    initial_cash: float = 100_000_000.0
    persist: bool = True
    persist_ch: bool = True

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["start"] = self.start.isoformat()
        d["end"] = self.end.isoformat()
        return d


def expand_cells(spec: ExperimentSpec) -> list[dict[str, Any]]:
    """factor × weight_method 笛卡尔积，每格一条 cell dict。"""
    cells: list[dict[str, Any]] = []
    for factor in spec.factors:
        for wm in spec.weight_methods:
            cells.append(
                {
                    "factor": str(factor),
                    "weight_method": str(wm),
                    "universe": spec.universe,
                    "top_n": spec.top_n,
                    "factor_version": spec.factor_version,
                    "industry_level": spec.industry_level,
                    "execution": spec.execution,
                    "benchmark": spec.benchmark,
                }
            )
    return cells


def _experiment_id(spec: ExperimentSpec) -> str:
    payload = {**spec.to_dict(), "app_version": APP_PIPELINE_VERSION}
    h = sha1(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()[:10]
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"exp_{ts}_{h}"


def _experiments_root() -> Path:
    return settings().lake_root / "experiments"


def _write_summary_md(spec: ExperimentSpec, summary: pd.DataFrame, out_dir: Path) -> None:
    lines = [
        "# 策略实验矩阵摘要",
        "",
        f"- **experiment_id**: `{out_dir.name}`",
        f"- **app_version**: `{APP_PIPELINE_VERSION}`",
        f"- **区间**: {spec.start} ~ {spec.end}",
        f"- **universe**: {spec.universe}",
        f"- **execution**: {spec.execution}",
        f"- **factors**: {', '.join(spec.factors)}",
        f"- **weight_methods**: {', '.join(spec.weight_methods)}",
        "",
        "## 指标对比",
        "",
    ]
    if summary.empty:
        lines.append("_无成功 run_")
    else:
        cols = [
            c
            for c in (
                "factor",
                "weight_method",
                "total_return",
                "ann_return",
                "sharpe",
                "max_drawdown",
                "turnover",
                "excess_total",
                "info_ratio",
                "n_fills",
                "status",
            )
            if c in summary.columns
        ]
        lines.append("| " + " | ".join(cols) + " |")
        lines.append("| " + " | ".join(["---"] * len(cols)) + " |")
        for _, row in summary.iterrows():
            vals = []
            for c in cols:
                v = row.get(c)
                if isinstance(v, float):
                    vals.append(f"{v:.4f}" if pd.notna(v) else "—")
                else:
                    vals.append(str(v) if v is not None else "—")
            lines.append("| " + " | ".join(vals) + " |")
    (out_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _persist_ch(experiment_id: str, spec: ExperimentSpec, summary: pd.DataFrame, meta: dict) -> None:
    from qdata import db

    ch = db.client()
    for stmt in _CH_DDL.strip().split(";"):
        s = stmt.strip()
        if s:
            ch.command(s)

    created = meta.get("created_at") or datetime.now(timezone.utc).isoformat()
    try:
        created_dt = pd.Timestamp(created).to_pydatetime().replace(tzinfo=None)
    except Exception:
        created_dt = datetime.utcnow()

    n_ok = int((summary.get("status") == "ok").sum()) if not summary.empty and "status" in summary.columns else 0
    n_fail = len(summary) - n_ok if not summary.empty else 0

    ch.command(
        "ALTER TABLE experiment_run DELETE WHERE experiment_id = %(e)s",
        parameters={"e": experiment_id},
    )
    row = pd.DataFrame(
        [
            {
                "experiment_id": experiment_id,
                "created_at": created_dt,
                "app_version": APP_PIPELINE_VERSION,
                "dataset_version": str(meta.get("dataset_version") or ""),
                "universe": spec.universe,
                "execution": spec.execution,
                "benchmark": spec.benchmark or "",
                "start_date": spec.start,
                "end_date": spec.end,
                "n_cells": len(summary),
                "n_ok": n_ok,
                "n_fail": n_fail,
                "summary_json": summary.to_json(orient="records", force_ascii=False),
                "meta_json": json.dumps(meta, ensure_ascii=False, default=str),
            }
        ]
    )
    db.insert_df("experiment_run", row)


def run_experiment_matrix(spec: ExperimentSpec) -> dict[str, Any]:
    """批跑矩阵回测，汇总 metrics 并落 Lake（+ 可选 CH）。"""
    if spec.start > spec.end:
        raise ValueError(f"start({spec.start}) > end({spec.end})")

    api = DataAPI(version=spec.version) if spec.version else DataAPI()
    experiment_id = _experiment_id(spec)
    cells = expand_cells(spec)
    rows: list[dict[str, Any]] = []

    for cell in cells:
        factor = cell["factor"]
        wm = cell["weight_method"]
        run_name = f"{factor}_{wm}"
        row: dict[str, Any] = {
            **cell,
            "experiment_id": experiment_id,
            "status": "ok",
            "run_id": None,
            "error": "",
        }
        try:
            reb_spec = RebalanceSpec(
                universe=spec.universe,
                factor=factor,
                factor_version=spec.factor_version,
                top_n=spec.top_n,
                weight_method=wm,  # type: ignore[arg-type]
                industry_level=spec.industry_level,
            )
            cfg = BacktestConfig(
                start=spec.start,
                end=spec.end,
                initial_cash=spec.initial_cash,
                execution=spec.execution,
                benchmark=spec.benchmark,
                dataset_version=spec.version or api.version,
                run_name=run_name,
                persist=False,
                persist_ch=False,
                write_tearsheet=False,
            )
            signals = FromRebalanceSpec(spec.start, spec.end, spec=reb_spec, api=api)
            result = BacktestEngine(cfg, api=api).run(signals)
            row["run_id"] = result.meta.get("run_id")
            for k, v in (result.metrics or {}).items():
                row[k] = v
        except Exception as e:
            logger.exception("cell failed factor=%s wm=%s: %s", factor, wm, e)
            row["status"] = "fail"
            row["error"] = str(e)

        rows.append(row)

    summary = pd.DataFrame(rows)
    meta: dict[str, Any] = {
        "experiment_id": experiment_id,
        "app_pipeline_version": APP_PIPELINE_VERSION,
        "dataset_version": api.version,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "spec": spec.to_dict(),
        "n_cells": len(cells),
        "n_ok": int((summary["status"] == "ok").sum()) if not summary.empty else 0,
        "n_fail": int((summary["status"] == "fail").sum()) if not summary.empty else 0,
    }

    out_dir = _experiments_root() / experiment_id
    path: Path | None = None
    if spec.persist:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        (out_dir / "cells.json").write_text(
            json.dumps(cells, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        try:
            summary.to_parquet(out_dir / "summary.parquet", index=False)
        except Exception:
            summary.to_csv(out_dir / "summary.csv", index=False)
        _write_summary_md(spec, summary, out_dir)
        path = out_dir

        if spec.persist_ch:
            try:
                _persist_ch(experiment_id, spec, summary, meta)
            except Exception as e:
                logger.warning("ClickHouse experiment_run 归档失败: %s", e)

    return {
        "experiment_id": experiment_id,
        "rows": rows,
        "summary": summary,
        "path": str(path) if path else None,
        "meta": meta,
    }


def list_experiments(limit: int = 50) -> list[dict[str, Any]]:
    """列出 Lake 中最近实验（Dashboard 用）。"""
    root = _experiments_root()
    if not root.is_dir():
        return []
    dirs = sorted(
        [p for p in root.iterdir() if p.is_dir()],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )[:limit]
    out: list[dict[str, Any]] = []
    for d in dirs:
        meta_path = d / "meta.json"
        if not meta_path.is_file():
            continue
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            meta = {"experiment_id": d.name}
        meta["path"] = str(d)
        out.append(meta)
    return out


def load_experiment_summary(experiment_id: str) -> pd.DataFrame:
    """读取实验 summary 表。"""
    d = _experiments_root() / experiment_id
    pq = d / "summary.parquet"
    csv = d / "summary.csv"
    if pq.is_file():
        return pd.read_parquet(pq)
    if csv.is_file():
        return pd.read_csv(csv)
    return pd.DataFrame()


def load_experiment(experiment_id: str) -> dict[str, Any]:
    """加载实验 meta + summary。"""
    d = _experiments_root() / experiment_id
    if not d.is_dir():
        raise FileNotFoundError(f"experiment 不存在: {experiment_id}")
    meta_path = d / "meta.json"
    if not meta_path.is_file():
        raise FileNotFoundError(f"缺少 meta.json: {experiment_id}")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    summary = load_experiment_summary(experiment_id)
    return {
        "experiment_id": experiment_id,
        "meta": meta,
        "summary": summary,
        "path": str(d),
    }


def pick_best_cell(
    summary: pd.DataFrame,
    *,
    rank_by: str = "sharpe",
    ascending: bool = False,
) -> dict[str, Any]:
    """从实验汇总中选最优 ok cell（默认按 sharpe 降序）。"""
    if summary is None or summary.empty:
        raise ValueError("实验 summary 为空，无法选优")
    df = summary.copy()
    if "status" in df.columns:
        df = df[df["status"].astype(str) == "ok"]
    if df.empty:
        raise ValueError("无 status=ok 的实验 cell")
    if rank_by not in df.columns:
        raise ValueError(f"排序指标不存在: {rank_by}；可用列={list(df.columns)}")
    ranked = df.sort_values(rank_by, ascending=ascending, na_position="last")
    best = ranked.iloc[0]
    cell = {
        "factor": str(best["factor"]),
        "weight_method": str(best["weight_method"]),
        "universe": str(best.get("universe") or "000905.SH"),
        "top_n": int(best["top_n"]) if pd.notna(best.get("top_n")) else 50,
        "factor_version": str(best.get("factor_version") or "v1"),
        "industry_level": str(best.get("industry_level") or "sw_l1"),
        "execution": str(best.get("execution") or "next_open"),
        "benchmark": None if pd.isna(best.get("benchmark")) else str(best.get("benchmark")),
        "run_id": None if pd.isna(best.get("run_id")) else str(best.get("run_id")),
        "rank_by": rank_by,
        "rank_value": float(best[rank_by]) if pd.notna(best[rank_by]) else None,
        "status": str(best.get("status") or "ok"),
    }
    return cell
