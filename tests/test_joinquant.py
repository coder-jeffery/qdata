"""JoinQuant / 代码转换单测。"""

import pytest

from qdata.symbols import (
    from_joinquant_code,
    is_joinquant_a_share,
    to_joinquant_code,
)


def test_joinquant_code_roundtrip():
    assert to_joinquant_code("600000.SH") == "600000.XSHG"
    assert to_joinquant_code("000001.SZ") == "000001.XSHE"
    assert to_joinquant_code("830799.BJ") == "830799.XBSE"
    assert from_joinquant_code("600000.XSHG") == "600000.SH"
    assert from_joinquant_code("000001.XSHE") == "000001.SZ"
    assert from_joinquant_code("830799.XBSE") == "830799.BJ"


def test_is_joinquant_a_share():
    assert is_joinquant_a_share("600000.XSHG")
    assert is_joinquant_a_share("000001.XSHE")
    assert not is_joinquant_a_share("000300.XSHG")  # 指数前缀 0003xx 在 SH 非 60/68


def test_joinquant_switch_filters_auto_chain(monkeypatch):
    from qdata.config import settings
    from qdata.fetchers.factory import _parse_chain

    monkeypatch.setenv("QDATA_JOINQUANT_ENABLED", "false")
    monkeypatch.setenv("QDATA_TUSHARE_ENABLED", "false")
    monkeypatch.setenv(
        "QDATA_DATA_SOURCE_CHAIN",
        "akshare,baostock,tushare,joinquant,efinance",
    )
    settings.cache_clear()
    chain = _parse_chain("auto")
    assert "joinquant" not in chain
    assert "tushare" not in chain
    assert "baostock" in chain
    settings.cache_clear()


def test_joinquant_explicit_disabled_kept_for_error(monkeypatch):
    from qdata.config import settings
    from qdata.fetchers.factory import _parse_chain

    monkeypatch.setenv("QDATA_JOINQUANT_ENABLED", "false")
    settings.cache_clear()
    assert _parse_chain("joinquant") == ["joinquant"]
    assert _parse_chain("jq") == ["joinquant"]
    settings.cache_clear()


def test_ensure_joinquant_enabled_raises(monkeypatch):
    from qdata.config import settings
    from qdata.fetchers.joinquant_fetcher import ensure_joinquant_enabled

    monkeypatch.setenv("QDATA_JOINQUANT_ENABLED", "false")
    settings.cache_clear()
    with pytest.raises(RuntimeError, match="JOINQUANT_ENABLED"):
        ensure_joinquant_enabled()


def test_joinquant_rejects_non_11_digit_mobile(monkeypatch):
    from qdata.config import Settings
    from qdata.fetchers.joinquant_fetcher import JoinquantFetcher

    fake = Settings(
        joinquant_enabled=True,
        joinquant_user="199017121802",  # 12 位
        joinquant_password="dummy",
    )
    monkeypatch.setattr(
        "qdata.fetchers.joinquant_fetcher.settings",
        lambda: fake,
    )
    with pytest.raises(RuntimeError, match="11 位手机号"):
        JoinquantFetcher()
