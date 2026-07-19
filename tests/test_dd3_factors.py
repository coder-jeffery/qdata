"""DD3 因子编排状态（不依赖外网重算）。"""

from __future__ import annotations

import datetime as dt

from qdata.jobs import dd3_factors


def test_seed_list() -> None:
    assert "mom_20" in dd3_factors.SEED
    assert "ep" in dd3_factors.SEED
    assert len(dd3_factors.SEED) == 6


def test_status_shape(monkeypatch) -> None:
    monkeypatch.setattr(
        dd3_factors,
        "_published_days",
        lambda **k: [dt.date(2026, 7, 1), dt.date(2026, 7, 2)],
    )
    monkeypatch.setattr(
        dd3_factors,
        "_factor_day_counts",
        lambda version="v1": {
            "mom_20": {
                "min": "2026-07-01",
                "max": "2026-07-02",
                "days": 2,
                "rows": 100,
            }
        },
    )

    def fake_set(fac: str, version: str = "v1") -> set[str]:
        if fac == "mom_20":
            return {"2026-07-01", "2026-07-02"}
        return {"2026-07-01"}

    monkeypatch.setattr(dd3_factors, "_factor_days_set", fake_set)
    r = dd3_factors.status_report()
    assert r["published_bar_days"] == 2
    assert r["factors"]["mom_20"]["missing_on_published"] == 0
    assert r["factors"]["vol_20"]["missing_on_published"] == 1
    assert r["aligned_ok"] is False
