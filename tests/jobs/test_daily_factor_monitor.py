"""A405：daily_run 软挂因子监控。"""

from __future__ import annotations

import datetime as dt

import pytest

from qdata.jobs import daily_run


def test_run_factor_monitor_soft_alerts(monkeypatch):
    calls: list[tuple] = []

    def fake_monitor(d, **kwargs):
        assert kwargs.get("via") == "daily_run"
        return {
            "report": {
                "n_alerts": 2,
                "universe_size": 100,
                "alerts": [
                    {"message": "mom_20 覆盖率低"},
                    {"message": "ep 无因子值"},
                ],
            },
            "path": "/tmp/fake",
        }

    def fake_notify(title, content, *, ok=True):
        calls.append((title, content, ok))
        return True

    monkeypatch.setattr(
        "qdata.apps.factor_monitor.monitor_factor_day",
        fake_monitor,
    )
    # import path used inside function
    monkeypatch.setattr(daily_run, "notify", fake_notify)

    # patch the import target used in _run_factor_monitor
    import qdata.apps.factor_monitor as fm

    monkeypatch.setattr(fm, "monitor_factor_day", fake_monitor)

    warn = daily_run._run_factor_monitor(dt.date(2026, 7, 15), strict=False)
    assert len(warn) == 1
    assert "2 alerts" in warn[0]
    assert any(t == "qdata factor_monitor WARN" and not ok for t, _, ok in calls)


def test_run_factor_monitor_exception_soft(monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError("db down")

    import qdata.apps.factor_monitor as fm

    monkeypatch.setattr(fm, "monitor_factor_day", boom)
    monkeypatch.setattr(daily_run, "notify", lambda *a, **k: True)

    warn = daily_run._run_factor_monitor(dt.date(2026, 7, 15), strict=False)
    assert len(warn) == 1
    assert "db down" in warn[0]


def test_run_factor_monitor_strict_raises(monkeypatch):
    def fake_monitor(d, **kwargs):
        return {
            "report": {
                "n_alerts": 1,
                "universe_size": 10,
                "alerts": [{"message": "low"}],
            },
            "path": None,
        }

    import qdata.apps.factor_monitor as fm

    monkeypatch.setattr(fm, "monitor_factor_day", fake_monitor)
    monkeypatch.setattr(daily_run, "notify", lambda *a, **k: True)

    with pytest.raises(RuntimeError, match="alerts"):
        daily_run._run_factor_monitor(dt.date(2026, 7, 15), strict=True)


def test_run_daily_calls_monitor_after_post_m2(monkeypatch):
    """post_m2 成功路径会调用监控，监控告警不改变 exit=0。"""
    d = dt.date(2026, 7, 15)
    monitor_called = {"n": 0}

    monkeypatch.setattr(daily_run, "apply_prod_mode", lambda: None)
    monkeypatch.setattr(daily_run, "resolve_prod_source", lambda: "baostock")
    monkeypatch.setattr(daily_run.calendar, "is_trading_day", lambda _d: True)
    monkeypatch.setattr(
        daily_run,
        "backfill",
        lambda *a, **k: {
            "failed": [],
            "published": [d.isoformat()],
            "quality_failed": [],
            "master_rows": 100,
        },
    )
    monkeypatch.setattr(daily_run, "run_smoke", lambda *a, **k: 0)
    monkeypatch.setattr(daily_run, "_run_post_m2", lambda *a, **k: [])

    def fake_mon(date, **kwargs):
        monitor_called["n"] += 1
        return ["factor_monitor alert"]

    monkeypatch.setattr(daily_run, "_run_factor_monitor", fake_mon)
    monkeypatch.setattr(daily_run, "notify", lambda *a, **k: True)

    rc = daily_run.run_daily(
        d,
        skip_calendar=True,
        post_m2=True,
        monitor_factors=True,
    )
    assert rc == 0
    assert monitor_called["n"] == 1


def test_run_daily_skips_monitor_when_disabled(monkeypatch):
    d = dt.date(2026, 7, 15)
    monitor_called = {"n": 0}

    monkeypatch.setattr(daily_run, "apply_prod_mode", lambda: None)
    monkeypatch.setattr(daily_run, "resolve_prod_source", lambda: "baostock")
    monkeypatch.setattr(daily_run.calendar, "is_trading_day", lambda _d: True)
    monkeypatch.setattr(
        daily_run,
        "backfill",
        lambda *a, **k: {
            "failed": [],
            "published": [d.isoformat()],
            "quality_failed": [],
            "master_rows": 100,
        },
    )
    monkeypatch.setattr(daily_run, "run_smoke", lambda *a, **k: 0)
    monkeypatch.setattr(daily_run, "_run_post_m2", lambda *a, **k: [])

    def fake_mon(*_a, **_k):
        monitor_called["n"] += 1
        return []

    monkeypatch.setattr(daily_run, "_run_factor_monitor", fake_mon)
    monkeypatch.setattr(daily_run, "notify", lambda *a, **k: True)

    rc = daily_run.run_daily(
        d,
        skip_calendar=True,
        post_m2=True,
        monitor_factors=False,
    )
    assert rc == 0
    assert monitor_called["n"] == 0
