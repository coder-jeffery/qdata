"""生产主源与发布连续性单测。"""

import datetime as dt

import pytest

from qdata.config import settings
from qdata.prod import PROD_SOURCES, apply_prod_mode, resolve_prod_source


def test_resolve_prod_source_ok(monkeypatch):
    monkeypatch.setenv("QDATA_PROD_SOURCE", "baostock")
    settings.cache_clear()
    assert resolve_prod_source() == "baostock"
    settings.cache_clear()


def test_resolve_prod_source_rejects_auto(monkeypatch):
    monkeypatch.setenv("QDATA_PROD_SOURCE", "auto")
    settings.cache_clear()
    with pytest.raises(RuntimeError, match="禁止 auto"):
        resolve_prod_source()
    settings.cache_clear()


def test_resolve_prod_source_rejects_chain(monkeypatch):
    settings.cache_clear()
    with pytest.raises(RuntimeError, match="禁止 auto"):
        resolve_prod_source("akshare,baostock")
    settings.cache_clear()


def test_resolve_tushare_requires_switch(monkeypatch):
    monkeypatch.setenv("QDATA_PROD_SOURCE", "tushare")
    monkeypatch.setenv("QDATA_TUSHARE_ENABLED", "false")
    monkeypatch.setenv("QDATA_TUSHARE_TOKEN", "x")
    settings.cache_clear()
    with pytest.raises(RuntimeError, match="TUSHARE_ENABLED"):
        resolve_prod_source()
    settings.cache_clear()


def test_resolve_joinquant_gap_fill(monkeypatch):
    monkeypatch.setenv("QDATA_PROD_SOURCE", "joinquant")
    monkeypatch.setenv("QDATA_JOINQUANT_ENABLED", "true")
    monkeypatch.setenv("QDATA_JOINQUANT_USER", "u")
    settings.cache_clear()
    assert resolve_prod_source() == "joinquant"
    assert "joinquant" in PROD_SOURCES
    settings.cache_clear()


def test_apply_prod_mode_forces_full_market(monkeypatch):
    monkeypatch.setenv("QDATA_PROD_SOURCE", "baostock")
    monkeypatch.setenv("QDATA_AKSHARE_MAX_SYMBOLS", "30")
    monkeypatch.setenv("QDATA_DATA_SOURCE", "auto")
    settings.cache_clear()
    name = apply_prod_mode()
    assert name == "baostock"
    s = settings()
    assert s.data_source == "baostock"
    assert s.akshare_max_symbols == 0
    assert "baostock" in PROD_SOURCES
    settings.cache_clear()


def test_check_version_continuity_logic(monkeypatch):
    from qdata import release

    expected = [dt.date(2026, 7, 13), dt.date(2026, 7, 14), dt.date(2026, 7, 15)]
    monkeypatch.setattr(
        "qdata.release.calendar.trading_days_between",
        lambda a, b: expected,
    )

    import pandas as pd

    monkeypatch.setattr(
        "qdata.release.db.query_df",
        lambda sql, params=None: pd.DataFrame({
            "version": ["2026-07-13", "2026-07-15"],
            "row_count": [100, 100],
        }),
    )
    r = release.check_version_continuity(dt.date(2026, 7, 13), dt.date(2026, 7, 15))
    assert r["ok"] is False
    assert r["missing"] == ["2026-07-14"]
