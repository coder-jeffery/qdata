"""多源工厂 / 注册表单测。"""

from qdata.fetchers.akshare_fetcher import AkshareFetcher
from qdata.fetchers.baostock_fetcher import BaostockFetcher
from qdata.fetchers.factory import get_fetcher, raw_source_candidates
from qdata.fetchers.failover import FailoverFetcher
from qdata.fetchers.registry import DEFAULT_AUTO_CHAIN, REGISTRY, list_sources


def test_registry_covers_requested_sources():
    for name in (
        "baostock", "tushare", "mootdx", "easyquotation", "efinance",
        "zvt", "miniqmt", "easytrader",
    ):
        assert name in REGISTRY


def test_list_sources_kinds():
    kinds = {s.kind for s in list_sources()}
    assert {"historical", "realtime", "broker"} <= kinds


def test_get_fetcher_modes(monkeypatch):
    from qdata.config import settings

    monkeypatch.setenv("QDATA_DATA_SOURCE", "akshare")
    settings.cache_clear()
    assert isinstance(get_fetcher(), AkshareFetcher)

    monkeypatch.setenv("QDATA_DATA_SOURCE", "baostock")
    settings.cache_clear()
    assert isinstance(get_fetcher(), BaostockFetcher)

    monkeypatch.setenv("QDATA_DATA_SOURCE", "auto")
    monkeypatch.setenv("QDATA_DATA_SOURCE_CHAIN", "akshare,baostock")
    settings.cache_clear()
    assert isinstance(get_fetcher(), FailoverFetcher)

    assert isinstance(get_fetcher("baostock"), BaostockFetcher)
    settings.cache_clear()


def test_get_fetcher_rejects_broker(monkeypatch):
    from qdata.config import settings

    settings.cache_clear()
    try:
        get_fetcher("easytrader")
        assert False, "should raise"
    except ValueError as e:
        assert "交易通道" in str(e)


def test_get_broker_names():
    from qdata.brokers.easytrader_broker import EasytraderBroker
    from qdata.brokers.miniqmt import MiniQmtBroker
    from qdata.fetchers.factory import get_broker

    assert isinstance(get_broker("easytrader"), EasytraderBroker)
    assert isinstance(get_broker("miniqmt"), MiniQmtBroker)


def test_raw_source_candidates(monkeypatch):
    from qdata.config import settings

    monkeypatch.setenv("QDATA_DATA_SOURCE", "auto")
    monkeypatch.setenv("QDATA_DATA_SOURCE_CHAIN", "akshare,baostock")
    settings.cache_clear()
    cands = raw_source_candidates()
    assert cands[0] == "akshare"
    assert "baostock" in cands
    assert raw_source_candidates("mootdx")[0] == "mootdx"
    settings.cache_clear()


def test_default_auto_chain():
    assert "baostock" in DEFAULT_AUTO_CHAIN
    assert "tushare" in DEFAULT_AUTO_CHAIN
    assert "efinance" in DEFAULT_AUTO_CHAIN
    assert "mootdx" in DEFAULT_AUTO_CHAIN
