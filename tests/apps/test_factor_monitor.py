"""A4 因子监控测试。"""

from __future__ import annotations

import datetime as dt

import pytest

from qdata.apps.factor_monitor import monitor_factor_day


def test_monitor_empty_safe_no_ch(monkeypatch):
    """无 CH 时返回空 coverage 但不抛错。"""

    def _fail(*args, **kwargs):
        raise RuntimeError("no ch")

    monkeypatch.setattr("qdata.apps.factor_monitor._factor_coverage", lambda d, f: __import__("pandas").DataFrame())
    monkeypatch.setattr(
        "qdata.apps.factor_monitor._universe_size",
        lambda d: 0,
    )
    result = monitor_factor_day(dt.date(2026, 7, 15), factors=["mom_20"], persist=False, quintile=False)
    assert result["date"] == dt.date(2026, 7, 15)
    assert "coverage" in result
    assert "report" in result


@pytest.mark.integration
def test_monitor_one_day_if_data():
    try:
        from qdata import db

        df = db.query_df("SELECT max(trade_date) AS d FROM daily_bar")
        if df is None or df.empty:
            pytest.skip("无 daily_bar")
        d = df.iloc[0]["d"]
        if hasattr(d, "date"):
            d = d.date()
    except Exception:
        pytest.skip("ClickHouse 不可用")

    result = monitor_factor_day(d, factors=["mom_20"], persist=False, quintile=False)
    cov = result["coverage"]
    assert not cov.empty or result["report"]["universe_size"] == 0
    assert "alerts" in result["report"]
