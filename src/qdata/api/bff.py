"""qdata Web BFF：只读聚合 + 薄写操作入口（不直连 CH 给前端）。"""

from __future__ import annotations

import datetime as dt
import json
from contextlib import asynccontextmanager
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from qdata.apps.paper_store import compare_sessions, list_sessions, load_session
from qdata.config import settings


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    from qdata.api.job_queue import register_default_handlers

    register_default_handlers()
    yield


app = FastAPI(title="qdata Web BFF", version="0.2.0", lifespan=_lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173", "http://127.0.0.1:4173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _json_safe(obj: Any) -> Any:
    if obj is None:
        return None
    if is_dataclass(obj) and not isinstance(obj, type):
        return _json_safe(asdict(obj))
    if hasattr(obj, "isoformat"):
        try:
            return obj.isoformat()
        except Exception:
            return str(obj)
    if isinstance(obj, dict):
        return {str(k): _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(x) for x in obj]
    try:
        import pandas as pd

        if isinstance(obj, pd.DataFrame):
            return obj.where(pd.notna(obj), None).to_dict(orient="records")
        if isinstance(obj, pd.Series):
            return _json_safe(obj.to_dict())
    except Exception:
        pass
    if isinstance(obj, (str, int, float, bool)):
        return obj
    return str(obj)


class MarkBody(BaseModel):
    mark_date: str | None = None
    async_mode: bool = Field(default=True, alias="async")

    model_config = {"populate_by_name": True}


class JudgeBody(BaseModel):
    top_n: int | None = Field(default=20, ge=1, le=200)
    async_mode: bool = Field(default=True, alias="async")

    model_config = {"populate_by_name": True}


class PaperFromExperimentBody(BaseModel):
    experiment_id: str
    rank_by: str = "sharpe"
    asof: str | None = None
    cash: float | None = 1_000_000.0
    async_mode: bool = Field(default=True, alias="async")

    model_config = {"populate_by_name": True}


class EnqueueJobBody(BaseModel):
    type: str
    payload: dict[str, Any] = Field(default_factory=dict)


class RealtimeRefreshBody(BaseModel):
    source: str = "easyquotation"
    codes: list[str] | None = None
    async_mode: bool = Field(default=True, alias="async")

    model_config = {"populate_by_name": True}


def _latest_monitor() -> dict[str, Any]:
    root = Path(settings().lake_root) / "factor_monitor"
    if not root.is_dir():
        return {}
    dates: list[dt.date] = []
    for p in root.iterdir():
        if p.is_dir() and (p / "report.json").is_file():
            try:
                dates.append(dt.date.fromisoformat(p.name))
            except ValueError:
                continue
    if not dates:
        return {}
    d = max(dates)
    report = json.loads((root / d.isoformat() / "report.json").read_text(encoding="utf-8"))
    report["date"] = d.isoformat()
    return report


def _dataset_version() -> dict[str, Any]:
    try:
        from qdata import db

        rows = db.query_df(
            """
            SELECT version, published_at, note
            FROM dataset_version
            ORDER BY version DESC
            LIMIT 1
            """
        )
        if rows is None or rows.empty:
            return {"version": None, "source": "empty"}
        row = rows.iloc[0].to_dict()
        return {
            "version": str(row.get("version") or ""),
            "published_at": _json_safe(row.get("published_at")),
            "note": row.get("note") or "",
            "source": "clickhouse",
        }
    except Exception as exc:
        return {"version": None, "source": "unavailable", "error": str(exc)[:200]}


def _daily_bar_watermark() -> dict[str, Any]:
    try:
        from qdata import db

        rows = db.query_df(
            """
            SELECT min(trade_date) AS mn, max(trade_date) AS mx,
                   count() AS n, uniqExact(trade_date) AS days,
                   uniqExact(ts_code) AS n_codes
            FROM daily_bar
            """
        )
        if rows is None or rows.empty:
            return {}
        r = rows.iloc[0]
        return {
            "min_date": _json_safe(r.get("mn")),
            "max_date": _json_safe(r.get("mx")),
            "rows": int(r.get("n") or 0),
            "days": int(r.get("days") or 0),
            "n_codes": int(r.get("n_codes") or 0),
        }
    except Exception as exc:
        return {"error": str(exc)[:200]}


@app.get("/api/health")
def api_health() -> dict[str, str]:
    return {"status": "ok", "service": "qdata-bff"}


@app.get("/api/overview")
def api_overview() -> dict[str, Any]:
    """运营首页聚合：数据水位 · 因子监控 · Paper 摘要。"""
    sessions = list_sessions(limit=1)
    paper: dict[str, Any] = {}
    if sessions:
        sid = sessions[0].get("session_id") or ""
        try:
            data = load_session(sid)
            acct = data.get("account") or {}
            mark = data.get("mark_latest") or {}
            paper = {
                "session_id": sid,
                "asof": (data.get("meta") or {}).get("asof"),
                "total_asset": acct.get("total_asset"),
                "cash": acct.get("cash"),
                "market_value": acct.get("market_value"),
                "n_filled": (data.get("meta") or {}).get("n_filled"),
                "n_rejected": (data.get("meta") or {}).get("n_rejected"),
                "pnl_vs_initial": mark.get("pnl_vs_initial")
                or (data.get("meta") or {}).get("last_mark_pnl_vs_initial"),
                "mark_date": mark.get("mark_date")
                or (data.get("meta") or {}).get("last_mark_date"),
            }
        except FileNotFoundError:
            paper = {"session_id": sid, "error": "not_found"}

    monitor = _latest_monitor()
    return {
        "dataset": _dataset_version(),
        "daily_bar": _daily_bar_watermark(),
        "factor_monitor": {
            "date": monitor.get("date"),
            "n_alerts": monitor.get("n_alerts", 0),
            "universe_size": monitor.get("universe_size"),
            "min_coverage": monitor.get("min_coverage"),
            "via": monitor.get("via"),
        },
        "paper": paper,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }


@app.get("/api/paper/sessions")
def api_paper_sessions(limit: int = Query(30, ge=1, le=200)) -> dict[str, Any]:
    items = list_sessions(limit=limit)
    return {"items": _json_safe(items), "count": len(items)}


@app.get("/api/paper/sessions/{session_id}")
def api_paper_session(session_id: str) -> dict[str, Any]:
    try:
        data = load_session(session_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {
        "session_id": session_id,
        "meta": _json_safe(data.get("meta")),
        "account": _json_safe(data.get("account")),
        "orders": _json_safe(data.get("orders")),
        "positions": _json_safe(data.get("positions")),
        "rejects": _json_safe(data.get("rejects")),
        "mark_latest": _json_safe(data.get("mark_latest")),
        "marks": _json_safe(data.get("marks")),
    }


@app.get("/api/paper/compare")
def api_paper_compare(ids: str = Query(..., description="逗号分隔 session_id")) -> dict[str, Any]:
    sid_list = [x.strip() for x in ids.split(",") if x.strip()]
    if not sid_list:
        raise HTTPException(status_code=400, detail="ids 不能为空")
    df = compare_sessions(sid_list)
    return {"items": _json_safe(df), "count": len(df)}


@app.get("/api/monitor")
def api_monitor_latest() -> dict[str, Any]:
    report = _latest_monitor()
    if not report.get("date"):
        return {"report": {}, "coverage": [], "dates": _monitor_dates()}
    return api_monitor(str(report["date"]))


@app.get("/api/monitor/{date}")
def api_monitor(date: str) -> dict[str, Any]:
    try:
        d = dt.date.fromisoformat(date[:10])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="date 需为 YYYY-MM-DD") from exc
    path = Path(settings().lake_root) / "factor_monitor" / d.isoformat() / "report.json"
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"无监控报告: {d.isoformat()}")
    report = json.loads(path.read_text(encoding="utf-8"))
    report["date"] = d.isoformat()
    cov_path = path.parent / "coverage.parquet"
    coverage: list[dict[str, Any]] = []
    if cov_path.is_file():
        import pandas as pd

        coverage = _json_safe(pd.read_parquet(cov_path))
    return {"report": report, "coverage": coverage, "dates": _monitor_dates()}


def _monitor_dates(limit: int = 30) -> list[str]:
    root = Path(settings().lake_root) / "factor_monitor"
    if not root.is_dir():
        return []
    out: list[str] = []
    for p in sorted(root.iterdir(), reverse=True):
        if p.is_dir() and (p / "report.json").is_file():
            out.append(p.name)
        if len(out) >= limit:
            break
    return out


@app.get("/api/data/health")
def api_data_health() -> dict[str, Any]:
    try:
        from qdata.dashboard.health_data import (
            extras_lag_vs_daily_bar,
            health_summary,
            recent_publications,
        )

        summary = health_summary()
        return {
            "summary": _json_safe(summary),
            "lag": _json_safe(extras_lag_vs_daily_bar()),
            "publications": _json_safe(recent_publications(limit=15)),
        }
    except Exception as exc:
        return {"summary": {}, "lag": [], "publications": [], "error": str(exc)[:300]}


@app.get("/api/factors/coverage")
def api_factors_coverage(date: str | None = None) -> dict[str, Any]:
    try:
        from qdata.dashboard.factor_data import available_factor_dates, factor_matrix_latest

        trade_date = dt.date.fromisoformat(date[:10]) if date else None
        matrix = factor_matrix_latest(trade_date)
        dates = [d.isoformat() for d in available_factor_dates(limit=30)]
        return {
            "trade_date": (trade_date.isoformat() if trade_date else (dates[0] if dates else None)),
            "items": _json_safe(matrix),
            "dates": dates,
        }
    except Exception as exc:
        return {"trade_date": date, "items": [], "dates": [], "error": str(exc)[:300]}


@app.get("/api/experiments")
def api_experiments(limit: int = Query(30, ge=1, le=200)) -> dict[str, Any]:
    from qdata.apps.experiment import list_experiments

    items = list_experiments(limit=limit)
    return {"items": _json_safe(items), "count": len(items)}


@app.get("/api/experiments/{experiment_id}")
def api_experiment(experiment_id: str) -> dict[str, Any]:
    from qdata.apps.experiment import load_experiment

    try:
        data = load_experiment(experiment_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {
        "experiment_id": experiment_id,
        "meta": _json_safe(data.get("meta")),
        "summary": _json_safe(data.get("summary")),
        "path": data.get("path"),
    }


@app.get("/api/signals")
def api_signals(limit: int = Query(30, ge=1, le=200), asof: str | None = None) -> dict[str, Any]:
    from qdata.apps.signal import list_signals

    asof_d = dt.date.fromisoformat(asof[:10]) if asof else None
    items = list_signals(asof=asof_d, limit=limit)
    return {"items": _json_safe(items), "count": len(items)}


def _resolve_signal_path(signal_key: str) -> Path:
    """signal_key 可为绝对路径，或 list 中的 signal_id。"""
    p = Path(signal_key)
    if p.is_dir() and (p / "meta.json").is_file():
        return p
    from qdata.apps.signal import list_signals

    for item in list_signals(limit=200):
        sid = str(item.get("signal_id") or "")
        path = str(item.get("path") or "")
        if signal_key in (sid, path) or path.endswith("/" + signal_key) or path.endswith(signal_key):
            return Path(path)
    raise FileNotFoundError(f"信号不存在: {signal_key}")


@app.get("/api/signals/{signal_key:path}")
def api_signal(signal_key: str) -> dict[str, Any]:
    from qdata.apps.signal import load_signal

    try:
        path = _resolve_signal_path(signal_key)
        data = load_signal(path)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {
        "meta": _json_safe(data.get("meta")),
        "weights": _json_safe(data.get("weights")),
        "exposure": _json_safe(data.get("exposure")),
        "tradability": _json_safe(data.get("tradability")),
        "path": data.get("path"),
    }


@app.get("/api/backtests")
def api_backtests(limit: int = Query(20, ge=1, le=100), factor: str | None = None) -> dict[str, Any]:
    try:
        from qdata.dashboard.data import list_runs, runs_metrics_matrix

        runs = list_runs(limit=limit, factor=factor)
        matrix = runs_metrics_matrix(limit=limit, factor=factor)
        return {"items": _json_safe(runs), "matrix": _json_safe(matrix), "count": len(runs)}
    except Exception as exc:
        return {"items": [], "matrix": [], "count": 0, "error": str(exc)[:300]}


@app.post("/api/paper/sessions/{session_id}/mark")
def api_paper_mark(session_id: str, body: MarkBody | None = None) -> dict[str, Any]:
    from qdata.apps.paper_flow import mark_session_eod
    from qdata.api.job_queue import enqueue, register_default_handlers

    register_default_handlers()
    mark_date_s = body.mark_date if body else None
    async_mode = True if body is None else bool(body.async_mode)
    if mark_date_s:
        try:
            dt.date.fromisoformat(mark_date_s[:10])
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="mark_date 需为 YYYY-MM-DD") from exc

    if async_mode:
        job = enqueue(
            "paper_mark",
            {"session_id": session_id, "mark_date": mark_date_s},
        )
        return {"ok": True, "async": True, "job_id": job["job_id"], "status": job["status"]}

    mark_date = dt.date.fromisoformat(mark_date_s[:10]) if mark_date_s else None
    try:
        result = mark_session_eod(session_id, mark_date=mark_date, persist=True)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "async": False, "mark": _json_safe(result)}


@app.post("/api/signals/{signal_key:path}/judge")
def api_signal_judge(signal_key: str, body: JudgeBody | None = None) -> dict[str, Any]:
    from qdata.api.job_queue import enqueue, register_default_handlers
    from qdata.research.judgment import judge_signal_topn

    register_default_handlers()
    top_n = body.top_n if body and body.top_n else 20
    async_mode = True if body is None else bool(body.async_mode)
    if async_mode:
        job = enqueue("signal_judge", {"signal_key": signal_key, "top_n": top_n})
        return {"ok": True, "async": True, "job_id": job["job_id"], "status": job["status"]}

    try:
        path = _resolve_signal_path(signal_key)
        result = judge_signal_topn(path, top_n=top_n)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)[:300]) from exc
    cards = result.get("cards") or []
    card_rows = [_judgment_card(c) for c in cards]
    return {
        "ok": True,
        "async": False,
        "n": result.get("n"),
        "codes": result.get("codes"),
        "summary": _json_safe(result.get("summary")),
        "cards": card_rows,
        "meta": _json_safe(result.get("meta")),
        "signal_dir": result.get("signal_dir"),
    }


def _judgment_card(c: Any) -> Any:
    if hasattr(c, "to_dict"):
        return _json_safe(c.to_dict())
    if is_dataclass(c) and not isinstance(c, type):
        return _json_safe(asdict(c))
    if isinstance(c, dict):
        return _json_safe(c)
    return _json_safe(getattr(c, "__dict__", {"repr": str(c)}))


@app.post("/api/jobs/paper-from-experiment")
def api_paper_from_experiment(body: PaperFromExperimentBody) -> dict[str, Any]:
    from qdata.apps.paper_flow import run_paper_from_experiment
    from qdata.api.job_queue import enqueue, register_default_handlers

    register_default_handlers()
    if body.async_mode:
        job = enqueue(
            "paper_from_experiment",
            {
                "experiment_id": body.experiment_id,
                "rank_by": body.rank_by,
                "asof": body.asof,
                "cash": body.cash,
            },
        )
        return {"ok": True, "async": True, "job_id": job["job_id"], "status": job["status"]}

    asof = dt.date.fromisoformat(body.asof[:10]) if body.asof else None
    try:
        result = run_paper_from_experiment(
            body.experiment_id,
            asof=asof,
            rank_by=body.rank_by,
            cash=body.cash,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)[:400]) from exc
    return {"ok": True, "async": False, "result": _json_safe(result)}


@app.post("/api/jobs")
def api_enqueue_job(body: EnqueueJobBody) -> dict[str, Any]:
    from qdata.api.job_queue import enqueue, register_default_handlers

    register_default_handlers()
    try:
        job = enqueue(body.type, body.payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "job_id": job["job_id"], "status": job["status"], "type": job["type"]}


@app.get("/api/jobs")
def api_list_jobs(limit: int = Query(30, ge=1, le=100)) -> dict[str, Any]:
    from qdata.api.job_queue import list_jobs

    items = list_jobs(limit=limit)
    return {"items": _json_safe(items), "count": len(items)}


@app.get("/api/jobs/{job_id}")
def api_get_job(job_id: str) -> dict[str, Any]:
    from qdata.api.job_queue import get_job

    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"任务不存在: {job_id}")
    return _json_safe(job)


@app.get("/api/alerts")
def api_alerts() -> dict[str, Any]:
    from qdata.api.alerts import collect_alerts

    return _json_safe(collect_alerts())


@app.get("/api/realtime/quotes")
def api_realtime_quotes(
    codes: str | None = Query(None, description="逗号分隔代码"),
    source: str = Query("easyquotation"),
) -> dict[str, Any]:
    """读 Lake 最新 realtime 快照；可选按代码过滤。"""
    from qdata.realtime import read_latest_snapshot

    try:
        df = read_latest_snapshot(source)
    except Exception as exc:
        return {
            "source": source,
            "quotes": [],
            "n": 0,
            "error": str(exc)[:300],
        }
    if df is None or df.empty:
        return {"source": source, "quotes": [], "n": 0, "stale": True}
    if codes:
        want = {c.strip().upper() for c in codes.split(",") if c.strip()}
        if "exchange_code" in df.columns:
            df = df[df["exchange_code"].astype(str).str.upper().isin(want)].copy()
    rows = df.fillna("").to_dict(orient="records")
    snap_ts = None
    if rows and rows[0].get("snapshot_ts"):
        snap_ts = rows[0].get("snapshot_ts")
    return {
        "source": source,
        "quotes": _json_safe(rows[:500]),
        "n": len(rows),
        "snapshot_ts": snap_ts,
        "stale": False,
    }


@app.post("/api/realtime/refresh")
def api_realtime_refresh(body: RealtimeRefreshBody | None = None) -> dict[str, Any]:
    from qdata.api.job_queue import enqueue, register_default_handlers
    from qdata.realtime import fetch_and_store, read_latest_snapshot

    register_default_handlers()
    body = body or RealtimeRefreshBody()
    if body.async_mode:
        job = enqueue(
            "realtime_snapshot",
            {"source": body.source, "codes": body.codes},
        )
        return {"ok": True, "async": True, "job_id": job["job_id"], "status": job["status"]}
    try:
        df, path = fetch_and_store(source=body.source, codes=body.codes)
    except Exception as exc:
        df = read_latest_snapshot(body.source)
        if df is None or df.empty:
            raise HTTPException(status_code=400, detail=str(exc)[:300]) from exc
        path = None
    rows = df.head(500).fillna("").to_dict(orient="records") if df is not None else []
    return {
        "ok": True,
        "async": False,
        "source": body.source,
        "path": str(path) if path else None,
        "n": len(rows),
        "quotes": _json_safe(rows),
    }


@app.get("/api/data/finance")
def api_data_finance() -> dict[str, Any]:
    try:
        from qdata.dashboard.finance_data import (
            ann_monthly_counts,
            finance_summary,
            lag_vs_daily_bar,
            pit_field_coverage,
        )

        summary = finance_summary()
        asof_s = summary.get("daily_bar_max") or summary.get("max_ann") or ""
        asof = dt.date.fromisoformat(asof_s[:10]) if asof_s else None
        pit = pit_field_coverage(asof) if asof else None
        return {
            "summary": _json_safe(summary),
            "monthly": _json_safe(ann_monthly_counts(18)),
            "pit": _json_safe(pit) if pit is not None else [],
            "lag": _json_safe(lag_vs_daily_bar()),
        }
    except Exception as exc:
        return {
            "summary": {},
            "monthly": [],
            "pit": [],
            "lag": {},
            "error": str(exc)[:300],
        }


@app.get("/api/research/universe")
def api_research_universe(date: str | None = None, index: str = "000905.SH") -> dict[str, Any]:
    try:
        from qdata.dashboard.universe_data import (
            index_universe_sizes,
            industry_coverage,
            industry_distribution,
            latest_bar_date,
        )

        d = dt.date.fromisoformat(date[:10]) if date else latest_bar_date()
        if d is None:
            return {"trade_date": None, "sizes": [], "industry": [], "coverage": {}, "error": "无日线日期"}
        return {
            "trade_date": d.isoformat(),
            "sizes": _json_safe(index_universe_sizes(d)),
            "industry": _json_safe(industry_distribution(d, index_code=index)),
            "coverage": _json_safe(industry_coverage(d)),
            "index": index,
        }
    except Exception as exc:
        return {
            "trade_date": date,
            "sizes": [],
            "industry": [],
            "coverage": {},
            "error": str(exc)[:300],
        }


@app.get("/api/backtests/{run_id}")
def api_backtest_detail(run_id: str) -> dict[str, Any]:
    from qdata.dashboard.data import load_run_detail

    try:
        detail = load_run_detail(run_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc)[:300]) from exc
    if not detail.get("meta") and not detail.get("metrics"):
        raise HTTPException(status_code=404, detail=f"回测不存在: {run_id}")
    equity = detail.get("equity")
    fills = detail.get("fills")
    return {
        "run_id": run_id,
        "meta": _json_safe(detail.get("meta")),
        "metrics": _json_safe(detail.get("metrics")),
        "equity": _json_safe(equity.tail(120) if hasattr(equity, "tail") else equity),
        "fills": _json_safe(fills.head(50) if hasattr(fills, "head") else fills),
    }


@app.get("/api/research/judgment/{code}")
def api_judgment(code: str, asof: str | None = None) -> dict[str, Any]:
    from qdata.research.judgment import judge_stock

    asof_d = dt.date.fromisoformat(asof[:10]) if asof else None
    try:
        card = judge_stock(code, asof_d)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)[:300]) from exc
    return {"ok": True, "card": _judgment_card(card)}


@app.get("/api/research/ta/{code}")
def api_research_ta(
    code: str,
    start: str | None = None,
    end: str | None = None,
    adjust: str = Query("post", pattern="^(post|pre|none)$"),
) -> dict[str, Any]:
    """单票日频 K 线 + MA/MACD/KDJ/布林带（供独立 Chart 面板）。"""
    from qdata.api.data_api import DataAPI
    from qdata.research.ta import ta_payload

    code_u = code.strip().upper()
    if not code_u:
        raise HTTPException(status_code=400, detail="code 不能为空")
    end_d = dt.date.fromisoformat(end[:10]) if end else dt.date.today()
    start_d = (
        dt.date.fromisoformat(start[:10])
        if start
        else end_d - dt.timedelta(days=220)
    )
    if start_d > end_d:
        raise HTTPException(status_code=400, detail="start 不能晚于 end")
    try:
        api = DataAPI(allow_unpublished=True)
        bars = api.get_price(
            [code_u],
            start_d,
            end_d,
            adjust=adjust,  # type: ignore[arg-type]
            fields=("open", "high", "low", "close", "volume"),
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)[:300]) from exc
    if bars is None or bars.empty:
        raise HTTPException(
            status_code=404,
            detail=f"无行情: {code_u} {start_d}~{end_d}",
        )
    payload = ta_payload(bars, code=code_u, adjust=adjust)
    return {"ok": True, **payload}
