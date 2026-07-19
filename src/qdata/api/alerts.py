"""告警聚合：因子监控 · 日批日志 · 失败 Web Job · 数据健康软告警。"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

from qdata.config import settings


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


def _daily_run_log_alerts(limit: int = 5) -> list[dict[str, Any]]:
    """从 logs/daily_run.log 尾部抓 FAIL（若存在）。"""
    candidates = [
        Path("logs/daily_run.log"),
        Path(settings().lake_root).parent.parent / "logs" / "daily_run.log",
        Path.cwd() / "logs" / "daily_run.log",
    ]
    path = next((p for p in candidates if p.is_file()), None)
    if path is None:
        return []
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return []
    lines = text.splitlines()[-400:]
    out: list[dict[str, Any]] = []
    for line in reversed(lines):
        if "daily_run FAIL" in line or "FAIL" in line and "daily_run" in line.lower():
            out.append(
                {
                    "id": f"daily_run:{abs(hash(line)) % 10_000_000}",
                    "level": "error",
                    "source": "daily_run",
                    "title": "日批失败",
                    "message": line.strip()[:240],
                    "ts": None,
                }
            )
        if len(out) >= limit:
            break
    return out


def _failed_jobs(limit: int = 10) -> list[dict[str, Any]]:
    root = Path(settings().lake_root) / "web_jobs"
    if not root.is_dir():
        return []
    files = sorted(root.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:40]
    out: list[dict[str, Any]] = []
    for f in files:
        try:
            job = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        if job.get("status") != "failed":
            continue
        out.append(
            {
                "id": f"job:{job.get('job_id')}",
                "level": "error",
                "source": "web_job",
                "title": f"任务失败 · {job.get('type')}",
                "message": str(job.get("error") or "")[:240],
                "ts": job.get("finished_at") or job.get("created_at"),
                "href": "/ops/jobs",
            }
        )
        if len(out) >= limit:
            break
    return out


def _health_soft_alerts() -> list[dict[str, Any]]:
    try:
        from qdata.dashboard.health_data import extras_lag_vs_daily_bar, health_summary

        s = health_summary()
        out: list[dict[str, Any]] = []
        stale = int(s.get("extras_stale") or 0)
        if stale > 0:
            out.append(
                {
                    "id": "health:extras_stale",
                    "level": "warn",
                    "source": "data_health",
                    "title": "Extras 滞后",
                    "message": f"{stale} 张表相对日线 stale",
                    "ts": None,
                    "href": "/data/health",
                }
            )
        lag = extras_lag_vs_daily_bar()
        if lag is not None and not lag.empty:
            for _, row in lag.iterrows():
                if str(row.get("status")) != "stale":
                    continue
                out.append(
                    {
                        "id": f"health:lag:{row.get('table')}",
                        "level": "warn",
                        "source": "data_health",
                        "title": f"表滞后 · {row.get('table')}",
                        "message": f"max={row.get('max_date')} lag_days={row.get('lag_days')}",
                        "ts": None,
                        "href": "/data/health",
                    }
                )
        return out[:8]
    except Exception:
        return []


def collect_alerts() -> dict[str, Any]:
    items: list[dict[str, Any]] = []

    mon = _latest_monitor()
    n = int(mon.get("n_alerts") or 0)
    if n > 0:
        alerts = mon.get("alerts") or []
        msg = "; ".join(str(a)[:80] for a in alerts[:3]) if alerts else f"{n} 条覆盖告警"
        items.append(
            {
                "id": f"monitor:{mon.get('date')}",
                "level": "warn",
                "source": "factor_monitor",
                "title": f"因子监控告警 · {mon.get('date')}",
                "message": msg,
                "ts": None,
                "href": "/ops/monitor",
                "meta": {"n_alerts": n, "via": mon.get("via")},
            }
        )

    items.extend(_daily_run_log_alerts())
    items.extend(_failed_jobs())
    items.extend(_health_soft_alerts())

    # de-dup by id
    seen: set[str] = set()
    uniq: list[dict[str, Any]] = []
    for a in items:
        aid = str(a.get("id"))
        if aid in seen:
            continue
        seen.add(aid)
        uniq.append(a)

    errors = sum(1 for a in uniq if a.get("level") == "error")
    warns = sum(1 for a in uniq if a.get("level") == "warn")
    return {
        "items": uniq,
        "count": len(uniq),
        "n_error": errors,
        "n_warn": warns,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
