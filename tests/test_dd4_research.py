"""DD4 研究验收编排：窗口常量与 status 形状。"""

from __future__ import annotations

from qdata.jobs import dd4_research


def test_default_window() -> None:
    assert dd4_research.DEFAULT_START < dd4_research.DEFAULT_END
    assert "mom_20" in dd4_research.DEFAULT_FACTORS


def test_status_keys(monkeypatch) -> None:
    monkeypatch.setattr(dd4_research, "_published_days", lambda s, e: ["2026-04-01", "2026-04-02"])
    monkeypatch.setattr(
        dd4_research,
        "check_version_continuity",
        lambda *a, **k: {"ok": True, "published": ["2026-04-01", "2026-04-02"]},
    )
    monkeypatch.setattr(dd4_research, "list_experiments", lambda limit=10: [{"experiment_id": "e1"}])
    monkeypatch.setattr(dd4_research, "list_signals", lambda limit=10: [{"signal_id": "s1"}])
    monkeypatch.setattr(dd4_research, "list_sessions", lambda limit=5: [{"session_id": "p1"}])
    r = dd4_research.status_report()
    assert r["published_days"] == 2
    assert r["latest_experiment"] == "e1"
    assert r["latest_paper"] == "p1"
