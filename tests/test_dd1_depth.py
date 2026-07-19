"""DD1 日线纵深：状态段定义 + suspend 软失败不阻断 publish。"""

from __future__ import annotations

import datetime as dt
from unittest.mock import MagicMock

from qdata.jobs import dd1_depth
from qdata.jobs.backfill import backfill


def test_dd1_segments_cover_target() -> None:
    assert dd1_depth.SEGMENTS[0][1] == dd1_depth.DD1_START
    assert dd1_depth.SEGMENTS[-1][2] == dd1_depth.DD1_END
    names = [n for n, _, _ in dd1_depth.SEGMENTS]
    assert names == ["2025Q3", "2025Q4", "2026Q1", "2026Q2", "2026Q3a"]
    # 段之间首尾相接、无重叠
    for i in range(len(dd1_depth.SEGMENTS) - 1):
        _, _, end_i = dd1_depth.SEGMENTS[i]
        _, start_j, _ = dd1_depth.SEGMENTS[i + 1]
        assert end_i < start_j


def test_backfill_skip_suspend_still_publishes(monkeypatch) -> None:
    """DD1 默认跳过 suspend 时仍应 publish daily_bar。"""
    day = dt.date(2025, 7, 14)
    calls: list[tuple[str, ...]] = []

    def fake_fetch(datasets, trade_date, source=None, reuse_min_rows=None):
        ds = tuple(datasets)
        calls.append(ds)
        return {d: 100 for d in ds}

    monkeypatch.setattr("qdata.jobs.backfill.fetch_datasets", fake_fetch)
    monkeypatch.setattr(
        "qdata.jobs.backfill.calendar.trading_days_between",
        lambda a, b: [day],
    )
    monkeypatch.setattr("qdata.jobs.backfill.is_published", lambda *a, **k: False)

    loader = MagicMock()
    loader.load.return_value = 5144
    monkeypatch.setattr("qdata.jobs.backfill.DailyBarLoader", lambda: loader)

    pub = MagicMock(return_value={"daily_bar": 5144})
    monkeypatch.setattr("qdata.jobs.backfill.publish_day", pub)

    summary = backfill(
        day,
        day,
        source="baostock",
        skip_master=True,
        skip_quality=True,
        with_suspend=False,
        publish=True,
        continue_on_error=False,
        reuse_min_rows=None,
        skip_published=False,
    )

    assert day.isoformat() in summary["ok"]  # type: ignore[operator]
    assert summary["failed"] == []
    assert ("daily_bar", "adj_factor") in calls
    assert ("suspend",) not in calls
    pub.assert_called_once()
    assert pub.call_args[0][1] == ("daily_bar",)
