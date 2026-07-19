"""extras 水位区间解析（不依赖外网）。"""

import datetime as dt

import pytest

from qdata.jobs.sync_market_extras import resolve_range


def test_incremental_no_new_range_raises(monkeypatch):
    today = dt.date(2026, 7, 15)

    def _fake_max(_sql: str) -> dt.date:
        return today

    monkeypatch.setattr("qdata.jobs.sync_market_extras._max_date", _fake_max)
    monkeypatch.setattr(
        "qdata.jobs.sync_market_extras._yesterday",
        lambda: today,
    )
    with pytest.raises(ValueError, match="增量无新区间"):
        resolve_range(
            mode="incremental",
            start=None,
            end=None,
            only={"finance"},
        )


def test_full_requires_start():
    with pytest.raises(SystemExit):
        resolve_range(
            mode="full",
            start=None,
            end=dt.date(2026, 7, 15),
            only={"basic"},
        )
