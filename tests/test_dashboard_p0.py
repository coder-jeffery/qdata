"""P0 Dashboard 数据层单测（不依赖 Streamlit UI）。"""

from __future__ import annotations

from qdata.dashboard.factor_data import (
    available_factor_dates,
    available_factor_names,
    factor_coverage_day,
    factor_coverage_series,
    factor_matrix_latest,
    list_factor_watermarks,
)
from qdata.dashboard.health_data import (
    daily_bar_series,
    extras_lag_vs_daily_bar,
    health_summary,
    list_table_watermarks,
    recent_publications,
)


def test_health_watermarks_smoke():
    marks = list_table_watermarks()
    assert marks
    names = {m.name for m in marks}
    assert "daily_bar" in names
    assert "security_master" in names
    summary = health_summary()
    assert "daily_bar_max" in summary
    assert "latest_published" in summary


def test_daily_bar_series_and_lag():
    s = daily_bar_series(10)
    assert "row_count" in s.columns or s.empty
    lag = extras_lag_vs_daily_bar()
    assert "table" in lag.columns or lag.empty
    pubs = recent_publications(limit=5)
    assert "version" in pubs.columns or pubs.empty


def test_factor_coverage_smoke():
    marks = list_factor_watermarks()
    names = available_factor_names()
    assert isinstance(names, list)
    if not names:
        return
    dates = available_factor_dates(names[0], limit=5)
    if not dates:
        return
    cov = factor_coverage_day(names[0], dates[0])
    assert cov["factor"] == names[0]
    assert cov["n_valid"] >= 0
    assert 0.0 <= cov["coverage"] <= 1.5  # 允许略超（因子有、日线过滤差异）
    series = factor_coverage_series(names[0], limit_days=5)
    assert "coverage" in series.columns or series.empty
    matrix = factor_matrix_latest(dates[0])
    assert not matrix.empty
    assert "coverage" in matrix.columns
