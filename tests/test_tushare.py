"""Tushare 适配器单测（不访问网络）。"""

import pytest

from qdata.config import settings
from qdata.fetchers.factory import get_fetcher
from qdata.fetchers.tushare_fetcher import TushareFetcher


def test_tushare_disabled_by_default(monkeypatch):
    monkeypatch.setenv("QDATA_TUSHARE_ENABLED", "false")
    monkeypatch.setenv("QDATA_TUSHARE_TOKEN", "dummy")
    settings.cache_clear()
    with pytest.raises(RuntimeError, match="Tushare 渠道已关闭"):
        TushareFetcher()
    settings.cache_clear()


def test_tushare_requires_token_when_enabled(monkeypatch):
    monkeypatch.setenv("QDATA_TUSHARE_ENABLED", "true")
    monkeypatch.setenv("QDATA_TUSHARE_TOKEN", "")
    settings.cache_clear()
    with pytest.raises(RuntimeError, match="QDATA_TUSHARE_TOKEN"):
        TushareFetcher()
    settings.cache_clear()


def test_tushare_skipped_in_auto_when_disabled(monkeypatch):
    monkeypatch.setenv("QDATA_TUSHARE_ENABLED", "false")
    monkeypatch.setenv("QDATA_TUSHARE_TOKEN", "dummy")
    monkeypatch.setenv("QDATA_DATA_SOURCE", "auto")
    monkeypatch.setenv("QDATA_DATA_SOURCE_CHAIN", "tushare,baostock")
    settings.cache_clear()
    fetcher = get_fetcher()
    assert fetcher.source == "baostock"
    settings.cache_clear()


def test_tushare_explicit_source_respects_switch(monkeypatch):
    monkeypatch.setenv("QDATA_TUSHARE_ENABLED", "false")
    monkeypatch.setenv("QDATA_TUSHARE_TOKEN", "dummy")
    settings.cache_clear()
    with pytest.raises(RuntimeError, match="Tushare 渠道已关闭"):
        get_fetcher("tushare")
    settings.cache_clear()


def test_get_fetcher_tushare_when_enabled(monkeypatch):
    monkeypatch.setenv("QDATA_TUSHARE_ENABLED", "true")
    monkeypatch.setenv("QDATA_TUSHARE_TOKEN", "dummy-token-for-init")
    settings.cache_clear()
    f = get_fetcher("tushare")
    assert isinstance(f, TushareFetcher)
    assert f.source == "tushare"
    settings.cache_clear()
