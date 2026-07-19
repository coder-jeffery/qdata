"""daily_basic / suspend / finance 多渠道与 failover 空表语义。"""

from __future__ import annotations

import datetime as dt
from unittest.mock import MagicMock

import pandas as pd
import pytest

from qdata.fetchers.failover import FailoverFetcher, _EMPTY_OK_DATASETS
from qdata.fetchers.schema import EMPTY_SCHEMAS


def test_empty_ok_datasets_include_finance_and_suspend():
    assert "suspend" in _EMPTY_OK_DATASETS
    assert "income" in _EMPTY_OK_DATASETS
    assert "balancesheet" in _EMPTY_OK_DATASETS
    assert "cashflow" in _EMPTY_OK_DATASETS


def test_failover_accepts_empty_suspend_without_pinning_next():
    primary = MagicMock()
    primary.source = "joinquant"
    primary.fetch.return_value = pd.DataFrame(columns=EMPTY_SCHEMAS["suspend"])

    secondary = MagicMock()
    secondary.source = "tushare"
    secondary.fetch.return_value = pd.DataFrame({
        "exchange_code": ["600000.SH"],
        "suspend_date": [dt.date(2026, 7, 15)],
    })

    fo = FailoverFetcher(primary, secondary)
    out = fo.fetch("suspend", dt.date(2026, 7, 15))
    assert out.empty
    assert fo.source == "joinquant"
    assert fo._pinned is None
    secondary.fetch.assert_not_called()


def test_failover_still_falls_back_on_empty_daily_basic():
    primary = MagicMock()
    primary.source = "joinquant"
    primary.fetch.return_value = pd.DataFrame()

    secondary = MagicMock()
    secondary.source = "tushare"
    secondary.fetch.return_value = pd.DataFrame({
        "exchange_code": ["600000.SH"],
        "trade_date": [dt.date(2026, 7, 15)],
        "turnover_rate": [1.2],
    })

    fo = FailoverFetcher(primary, secondary)
    out = fo.fetch("daily_basic", dt.date(2026, 7, 15))
    assert len(out) == 1
    assert fo.source == "tushare"
    assert fo._pinned is secondary


def test_normalize_jq_statement_filters_pubdate():
    from qdata.fetchers.joinquant_fetcher import normalize_jq_statement

    raw = pd.DataFrame({
        "code": ["600000.XSHG", "000001.XSHE"],
        "pubDate": ["2026-07-15", "2026-07-14"],
        "statDate": ["2026-06-30", "2026-06-30"],
        "operating_revenue": [1e9, 2e9],
        "np_parent_company_owners": [1e8, 2e8],
    })
    out = normalize_jq_statement(
        raw,
        dt.date(2026, 7, 15),
        {
            "operating_revenue": "revenue",
            "np_parent_company_owners": "n_income_attr_p",
        },
        EMPTY_SCHEMAS["income"],
    )
    assert len(out) == 1
    assert out.iloc[0]["exchange_code"] == "600000.SH"
    assert float(out.iloc[0]["revenue"]) == 1e9


def test_resolve_range_full_requires_start():
    from qdata.jobs.sync_market_extras import resolve_range

    with pytest.raises(SystemExit):
        resolve_range(
            mode="full",
            start=None,
            end=dt.date(2026, 7, 15),
            only={"basic"},
        )


def test_resolve_range_full_ok():
    from qdata.jobs.sync_market_extras import resolve_range

    s, e = resolve_range(
        mode="full",
        start=dt.date(2026, 7, 1),
        end=dt.date(2026, 7, 15),
        only={"finance"},
    )
    assert s == dt.date(2026, 7, 1)
    assert e == dt.date(2026, 7, 15)
