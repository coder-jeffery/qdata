"""DD2 extras 状态计算（不依赖外网）。"""

from __future__ import annotations

import datetime as dt

from qdata.jobs import dd2_extras


def test_dd2_constants() -> None:
    assert dd2_extras.DD_START < dd2_extras.DD_END
    assert dd2_extras.FINANCE_START_DEFAULT < dd2_extras.DD_START


def test_status_report_shape(monkeypatch) -> None:
    monkeypatch.setattr(
        dd2_extras,
        "_published_bar_days",
        lambda **k: ["2025-07-01", "2025-07-02", "2026-04-01"],
    )
    monkeypatch.setattr(dd2_extras, "_basic_days", lambda: {"2026-04-01", "2026-04-02"})
    monkeypatch.setattr(
        dd2_extras,
        "_finance_watermark",
        lambda: {
            "min_ann": "2026-01-20",
            "max_ann": "2026-05-15",
            "rows": 100,
            "codes": 50,
        },
    )
    monkeypatch.setattr(
        dd2_extras,
        "_finance_raw_coverage",
        lambda **k: {
            "expected_days": 10,
            "present_days": 3,
            "missing_days": 7,
            "complete": False,
        },
    )
    r = dd2_extras.status_report()
    assert r["published_bar_days"] == 3
    assert r["bar_without_basic"] == 2
    assert r["overlap_ok"] is False
    assert r["missing_head"] == ["2025-07-01", "2025-07-02"]
    assert r["finance_needs_extend"] is True


def test_finance_complete_when_raw_full(monkeypatch) -> None:
    monkeypatch.setattr(dd2_extras, "_published_bar_days", lambda **k: ["2026-04-01"])
    monkeypatch.setattr(dd2_extras, "_basic_days", lambda: {"2026-04-01"})
    monkeypatch.setattr(
        dd2_extras,
        "_finance_watermark",
        lambda: {
            "min_ann": "2025-04-10",
            "max_ann": "2026-05-15",
            "rows": 70_000,
            "codes": 5_000,
        },
    )
    monkeypatch.setattr(
        dd2_extras,
        "_finance_raw_coverage",
        lambda **k: {
            "expected_days": 561,
            "present_days": 561,
            "missing_days": 0,
            "complete": True,
        },
    )
    r = dd2_extras.status_report()
    assert r["overlap_ok"] is True
    assert r["finance_needs_extend"] is False
