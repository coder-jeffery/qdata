"""数据源注册表：能力声明、可选依赖、工厂构造。

分类：
- historical: 日线/主数据等 ETL Fetcher（写入 Raw）
- realtime:   盘中快照（EasyQuotation / MootDX quotes 等）
- broker:     交易通道（MiniQMT / EasyTrader），非行情 ETL
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from qdata.fetchers.base import Fetcher
from qdata.fetchers.schema import HISTORICAL_DATASETS


@dataclass(frozen=True)
class SourceSpec:
    name: str
    kind: str  # historical | realtime | broker
    label: str
    datasets: frozenset[str] = field(default_factory=frozenset)
    extra: str | None = None          # pip install 'qdata[extra]'
    requires_local: bool = False      # 需本机客户端（QMT/同花顺等）
    factory: Callable[[], object] | None = None


def _lazy(factory: Callable[[], object]) -> Callable[[], object]:
    return factory


def _build_registry() -> dict[str, SourceSpec]:
    """延迟导入各适配器，避免未安装 optional 依赖时 import 失败。"""

    def akshare() -> Fetcher:
        from qdata.fetchers.akshare_fetcher import AkshareFetcher
        return AkshareFetcher()

    def baostock() -> Fetcher:
        from qdata.fetchers.baostock_fetcher import BaostockFetcher
        return BaostockFetcher()

    def tushare() -> Fetcher:
        from qdata.fetchers.tushare_fetcher import TushareFetcher
        return TushareFetcher()

    def efinance() -> Fetcher:
        from qdata.fetchers.efinance_fetcher import EfinanceFetcher
        return EfinanceFetcher()

    def mootdx() -> Fetcher:
        from qdata.fetchers.mootdx_fetcher import MootdxFetcher
        return MootdxFetcher()

    def easyquotation() -> Fetcher:
        from qdata.fetchers.easyquotation_fetcher import EasyquotationFetcher
        return EasyquotationFetcher()

    def zvt() -> Fetcher:
        from qdata.fetchers.zvt_fetcher import ZvtFetcher
        return ZvtFetcher()

    def miniqmt() -> Fetcher:
        from qdata.fetchers.miniqmt_fetcher import MiniQmtFetcher
        return MiniQmtFetcher()

    def easytrader():
        from qdata.brokers.easytrader_broker import EasytraderBroker
        return EasytraderBroker()

    def joinquant() -> Fetcher:
        from qdata.fetchers.joinquant_fetcher import JoinquantFetcher
        return JoinquantFetcher()

    hist = HISTORICAL_DATASETS
    specs = [
        SourceSpec("akshare", "historical", "AKShare", hist, factory=akshare),
        SourceSpec("baostock", "historical", "BaoStock", hist, factory=baostock),
        SourceSpec(
            "tushare", "historical", "Tushare Pro",
            hist, extra="tushare", factory=tushare,
        ),
        SourceSpec(
            "joinquant", "historical", "JoinQuant(聚宽)",
            hist, extra="joinquant", factory=joinquant,
        ),
        SourceSpec(
            "efinance", "historical", "Efinance",
            frozenset({"stock_basic", "daily_bar", "adj_factor", "daily_basic", "suspend"}),
            extra="efinance", factory=efinance,
        ),
        SourceSpec(
            "mootdx", "historical", "PyTDX/MootDX",
            frozenset({"stock_basic", "daily_bar", "adj_factor", "realtime_quote"}),
            extra="mootdx", factory=mootdx,
        ),
        SourceSpec(
            "easyquotation", "realtime", "EasyQuotation",
            frozenset({"stock_basic", "realtime_quote"}),
            extra="easyquotation", factory=easyquotation,
        ),
        SourceSpec(
            "zvt", "historical", "ZVT",
            frozenset({"stock_basic", "daily_bar", "adj_factor"}),
            extra="zvt", factory=zvt,
        ),
        SourceSpec(
            "miniqmt", "historical", "MiniQMT(xtdata)",
            frozenset({"stock_basic", "daily_bar", "adj_factor", "realtime_quote"}),
            extra="miniqmt", requires_local=True, factory=miniqmt,
        ),
        SourceSpec(
            "easytrader", "broker", "EasyTrader",
            frozenset(),
            extra="easytrader", requires_local=True, factory=easytrader,
        ),
    ]
    return {s.name: s for s in specs}


REGISTRY: dict[str, SourceSpec] = _build_registry()

# auto 默认故障转移链（未配置 token 时 tushare / joinquant 会被开关过滤）
DEFAULT_AUTO_CHAIN = ("akshare", "baostock", "tushare", "joinquant", "efinance", "mootdx")


def list_sources(kind: str | None = None) -> list[SourceSpec]:
    rows = list(REGISTRY.values())
    if kind:
        rows = [s for s in rows if s.kind == kind]
    return rows


def create_source(name: str) -> object:
    spec = REGISTRY.get(name)
    if spec is None:
        raise ValueError(
            f"未知数据源 {name!r}。可选: {sorted(REGISTRY)}。"
            f"查看: python -m qdata.fetchers --list-sources"
        )
    if spec.factory is None:
        raise RuntimeError(f"{name} 未注册 factory")
    try:
        return spec.factory()
    except ImportError as e:
        hint = (
            f".venv/bin/python -m pip install -e '.[{spec.extra}]'"
            if spec.extra
            else "安装对应依赖"
        )
        raise ImportError(
            f"数据源 {name} 依赖未安装（{e}）。请执行: {hint}"
            + ("；并确保本机客户端已启动" if spec.requires_local else "")
        ) from e
