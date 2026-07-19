"""Raw 复用跳过重拉。"""

import datetime as dt

import pandas as pd

from qdata.fetchers import cli as fetch_cli
from qdata.lake.raw import write_raw


class _FakeFetcher:
    source = "baostock"

    def __init__(self) -> None:
        self.calls: list[str] = []

    def fetch(self, dataset: str, trade_date: dt.date) -> pd.DataFrame:
        self.calls.append(dataset)
        return pd.DataFrame({
            "exchange_code": ["600000.SH"],
            "trade_date": [trade_date],
            "adj_factor": [1.0],
        })


def test_fetch_datasets_reuses_complete_raw(monkeypatch, tmp_path):
    monkeypatch.setenv("QDATA_LAKE_ROOT", str(tmp_path))
    from qdata.config import settings

    settings.cache_clear()

    d = dt.date(2026, 7, 1)
    write_raw(
        "baostock",
        "daily_bar",
        d,
        pd.DataFrame({
            "exchange_code": [f"{i:06d}.SH" for i in range(600)],
            "trade_date": [d] * 600,
            "close": [10.0] * 600,
        }),
    )

    fake = _FakeFetcher()
    monkeypatch.setattr(fetch_cli, "get_fetcher", lambda source=None: fake)

    result = fetch_cli.fetch_datasets(
        ("daily_bar", "adj_factor"),
        d,
        source="baostock",
        reuse_min_rows=500,
    )
    assert result["daily_bar"] == 600
    assert "daily_bar" not in fake.calls
    assert "adj_factor" in fake.calls
    settings.cache_clear()


def test_adj_not_reused_when_thin_vs_daily_bar(monkeypatch, tmp_path):
    monkeypatch.setenv("QDATA_LAKE_ROOT", str(tmp_path))
    from qdata.config import settings

    settings.cache_clear()
    d = dt.date(2026, 7, 1)
    write_raw(
        "baostock",
        "daily_bar",
        d,
        pd.DataFrame({
            "exchange_code": [f"{i:06d}.SH" for i in range(600)],
            "trade_date": [d] * 600,
            "close": [10.0] * 600,
        }),
    )
    write_raw(
        "baostock",
        "adj_factor",
        d,
        pd.DataFrame({
            "exchange_code": [f"{i:06d}.SH" for i in range(30)],
            "trade_date": [d] * 30,
            "adj_factor": [1.0] * 30,
        }),
    )
    fake = _FakeFetcher()
    monkeypatch.setattr(fetch_cli, "get_fetcher", lambda source=None: fake)
    fetch_cli.fetch_datasets(
        ("daily_bar", "adj_factor"),
        d,
        source="baostock",
        reuse_min_rows=30,
    )
    assert "daily_bar" not in fake.calls
    assert "adj_factor" in fake.calls
    settings.cache_clear()
