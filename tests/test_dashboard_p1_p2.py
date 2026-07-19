"""Dashboard P1/P2 数据层单测。"""

from __future__ import annotations

import datetime as dt

from qdata.dashboard.data import runs_metrics_matrix
from qdata.dashboard.finance_data import ann_monthly_counts, finance_summary, pit_field_coverage
from qdata.dashboard.research_data import default_range, load_industry, load_price, seed_factors
from qdata.dashboard.universe_data import (
    available_asof_dates,
    index_size_history,
    index_universe_sizes,
    industry_coverage,
    industry_distribution,
)


def test_universe_pit_smoke():
    dates = available_asof_dates(5)
    if not dates:
        return
    d = dates[0]
    sizes = index_universe_sizes(d)
    assert "ALL" in set(sizes["index_code"])
    assert sizes["members"].sum() >= 0
    cov = industry_coverage(d, level="sw_l1")
    assert 0.0 <= cov["coverage"] <= 1.5
    dist = industry_distribution(d, level="sw_l1")
    assert "members" in dist.columns or dist.empty
    hist = index_size_history("000905.SH", limit_days=5)
    assert "members" in hist.columns or hist.empty


def test_finance_and_matrix_smoke():
    s = finance_summary()
    assert "rows" in s
    m = ann_monthly_counts(6)
    assert "rows" in m.columns or m.empty
    dates = available_asof_dates(1)
    if dates:
        cov = pit_field_coverage(dates[0], sample_limit=200)
        assert not cov.empty
        assert "coverage" in cov.columns
    matrix = runs_metrics_matrix(limit=3)
    assert hasattr(matrix, "empty")


def test_research_smoke():
    start, end = default_range()
    assert start <= end
    assert seed_factors()
    px = load_price("600000.SH", start, end, adjust="post")
    # 有数据时校验列
    if px is not None and not px.empty:
        assert "close" in px.columns or "trade_date" in px.columns
    ind = load_industry("600000.SH", end)
    assert "sw_l1" in ind
