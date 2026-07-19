"""Web BFF 轻量异步任务队列：落盘 Lake + 线程执行。"""

from __future__ import annotations

import datetime as dt
import json
import logging
import threading
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

from qdata.config import settings

logger = logging.getLogger(__name__)

_LOCK = threading.Lock()
_EXEC = ThreadPoolExecutor(max_workers=2, thread_name_prefix="qdata-job")
_HANDLERS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {}


def _jobs_root() -> Path:
    root = Path(settings().lake_root) / "web_jobs"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _path(job_id: str) -> Path:
    return _jobs_root() / f"{job_id}.json"


def _write(job: dict[str, Any]) -> None:
    p = _path(str(job["job_id"]))
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(job, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    tmp.replace(p)


def get_job(job_id: str) -> dict[str, Any] | None:
    p = _path(job_id)
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def list_jobs(limit: int = 30) -> list[dict[str, Any]]:
    files = sorted(_jobs_root().glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    out: list[dict[str, Any]] = []
    for f in files[:limit]:
        try:
            out.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception:
            continue
    return out


def register(job_type: str, fn: Callable[[dict[str, Any]], dict[str, Any]]) -> None:
    _HANDLERS[job_type] = fn


def _run(job_id: str) -> None:
    job = get_job(job_id)
    if not job:
        return
    job_type = str(job.get("type") or "")
    handler = _HANDLERS.get(job_type)
    with _LOCK:
        job["status"] = "running"
        job["started_at"] = _now()
        _write(job)
    try:
        if handler is None:
            raise ValueError(f"未知任务类型: {job_type}")
        result = handler(job.get("payload") or {})
        with _LOCK:
            cur = get_job(job_id) or job
            cur["status"] = "succeeded"
            cur["finished_at"] = _now()
            cur["result"] = result
            cur["error"] = None
            _write(cur)
    except Exception as exc:
        logger.exception("job %s failed", job_id)
        with _LOCK:
            cur = get_job(job_id) or job
            cur["status"] = "failed"
            cur["finished_at"] = _now()
            cur["error"] = str(exc)[:800]
            cur["traceback"] = traceback.format_exc()[-2000:]
            _write(cur)


def enqueue(job_type: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    if job_type not in _HANDLERS:
        raise ValueError(f"未注册任务类型: {job_type}; 可用={sorted(_HANDLERS)}")
    job_id = f"job_{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{uuid.uuid4().hex[:8]}"
    job = {
        "job_id": job_id,
        "type": job_type,
        "status": "queued",
        "payload": payload or {},
        "created_at": _now(),
        "started_at": None,
        "finished_at": None,
        "result": None,
        "error": None,
    }
    _write(job)
    _EXEC.submit(_run, job_id)
    return job


def register_default_handlers() -> None:
    """幂等注册默认 handlers。"""
    if _HANDLERS:
        return

    def _paper_mark(payload: dict[str, Any]) -> dict[str, Any]:
        from qdata.apps.paper_flow import mark_session_eod

        sid = str(payload.get("session_id") or "")
        if not sid:
            raise ValueError("session_id 必填")
        mark_date = None
        if payload.get("mark_date"):
            mark_date = dt.date.fromisoformat(str(payload["mark_date"])[:10])
        return mark_session_eod(sid, mark_date=mark_date, persist=True)

    def _paper_from_experiment(payload: dict[str, Any]) -> dict[str, Any]:
        from qdata.apps.paper_flow import run_paper_from_experiment

        eid = str(payload.get("experiment_id") or "")
        if not eid:
            raise ValueError("experiment_id 必填")
        asof = None
        if payload.get("asof"):
            asof = dt.date.fromisoformat(str(payload["asof"])[:10])
        return run_paper_from_experiment(
            eid,
            asof=asof,
            rank_by=str(payload.get("rank_by") or "sharpe"),
            cash=payload.get("cash"),
        )

    def _signal_judge(payload: dict[str, Any]) -> dict[str, Any]:
        from dataclasses import asdict, is_dataclass
        from pathlib import Path

        from qdata.apps.signal import list_signals, load_signal
        from qdata.research.judgment import judge_signal_topn

        key = str(payload.get("signal_key") or "")
        if not key:
            raise ValueError("signal_key 必填")
        p = Path(key)
        if not (p.is_dir() and (p / "meta.json").is_file()):
            path = None
            for item in list_signals(limit=200):
                sid = str(item.get("signal_id") or "")
                sp = str(item.get("path") or "")
                if key in (sid, sp) or sp.endswith(key):
                    path = Path(sp)
                    break
            if path is None:
                raise FileNotFoundError(f"信号不存在: {key}")
            p = path
        top_n = int(payload.get("top_n") or 20)
        # ensure loadable
        _ = load_signal(p)
        result = judge_signal_topn(p, top_n=top_n)

        def _card(c: Any) -> Any:
            if hasattr(c, "to_dict"):
                return c.to_dict()
            if is_dataclass(c) and not isinstance(c, type):
                return asdict(c)
            if isinstance(c, dict):
                return c
            return getattr(c, "__dict__", {"repr": str(c)})

        return {
            "n": result.get("n"),
            "codes": result.get("codes"),
            "cards": [_card(c) for c in (result.get("cards") or [])],
            "signal_dir": result.get("signal_dir"),
        }

    def _realtime_snapshot(payload: dict[str, Any]) -> dict[str, Any]:
        from qdata.realtime import fetch_and_store, read_latest_snapshot

        source = str(payload.get("source") or "easyquotation")
        codes = payload.get("codes")
        code_list = [str(c) for c in codes] if isinstance(codes, list) else None
        try:
            df, path = fetch_and_store(source=source, codes=code_list)
        except Exception:
            df = read_latest_snapshot(source)
            path = None
            if df.empty:
                raise
        rows = df.head(500).fillna("").to_dict(orient="records") if df is not None else []
        return {"source": source, "path": str(path) if path else None, "n": len(rows), "quotes": rows}

    register("paper_mark", _paper_mark)
    register("paper_from_experiment", _paper_from_experiment)
    register("signal_judge", _signal_judge)
    register("realtime_snapshot", _realtime_snapshot)
