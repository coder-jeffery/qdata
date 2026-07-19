"""数据源 Fetcher / Broker 工厂。

QDATA_DATA_SOURCE:
  - 单一源名：akshare|baostock|efinance|mootdx|easyquotation|zvt
  - auto：按 QDATA_DATA_SOURCE_CHAIN（默认 akshare,baostock,efinance,mootdx）故障转移
  - 逗号链：akshare,baostock,mootdx  （显式 failover 链）

交易通道（非 ETL）：
  python -c "from qdata.fetchers.factory import get_broker; ..."
  miniqmt | easytrader
"""

from __future__ import annotations

import logging

from qdata.brokers.base import BrokerClient
from qdata.config import settings
from qdata.fetchers.base import Fetcher
from qdata.fetchers.failover import FailoverFetcher
from qdata.fetchers.registry import (
    DEFAULT_AUTO_CHAIN,
    REGISTRY,
    create_source,
    list_sources,
)

logger = logging.getLogger(__name__)


def _parse_chain(name: str) -> list[str]:
    name = name.strip().lower()
    if name == "auto":
        chain = settings().data_source_chain.strip()
        if chain:
            parts = [x.strip() for x in chain.split(",") if x.strip()]
        else:
            parts = list(DEFAULT_AUTO_CHAIN)
    elif "," in name:
        parts = [x.strip() for x in name.split(",") if x.strip()]
    else:
        parts = [name]
    return _apply_source_switches(parts, allow_explicit_disabled=len(parts) == 1)


def _apply_source_switches(parts: list[str], *, allow_explicit_disabled: bool) -> list[str]:
    """按渠道开关过滤；单源显式指定且关闭时保留，交给 Fetcher 抛明确错误。"""
    s = settings()
    out: list[str] = []
    for p in parts:
        if p == "tushare" and not s.tushare_enabled:
            if allow_explicit_disabled and len(parts) == 1:
                out.append(p)
            else:
                logger.info("Tushare 开关关闭（QDATA_TUSHARE_ENABLED=false），已从链路中排除")
            continue
        if p in ("joinquant", "jq") and not s.joinquant_enabled:
            if allow_explicit_disabled and len(parts) == 1:
                out.append("joinquant" if p == "jq" else p)
            else:
                logger.info(
                    "JoinQuant 开关关闭（QDATA_JOINQUANT_ENABLED=false），已从链路中排除"
                )
            continue
        if p == "jq":
            out.append("joinquant")
            continue
        out.append(p)
    return out


def get_fetcher(source: str | None = None) -> Fetcher:
    """按配置或显式 source 返回行情 Fetcher。"""
    name = (source or settings().data_source).strip().lower()
    # 单源显式指定时，关闭开关也应报错而非静默跳过
    explicit_single = "," not in name and name != "auto"
    # jq 别名
    if name == "jq":
        name = "joinquant"
    parts = _parse_chain(name)
    if explicit_single and name == "tushare" and not parts:
        # 防御：开关过滤不应吞掉唯一源
        parts = ["tushare"]
    if explicit_single and name == "joinquant" and not parts:
        parts = ["joinquant"]

    fetchers: list[Fetcher] = []
    errors: list[str] = []
    for part in parts:
        spec = REGISTRY.get(part)
        if spec is None:
            raise ValueError(
                f"未知 data_source={part!r}。历史/实时源: "
                f"{[s.name for s in list_sources() if s.kind in ('historical', 'realtime')]}"
            )
        if spec.kind == "broker":
            raise ValueError(
                f"{part} 是交易通道，请用 get_broker({part!r})，不能作为 ETL Fetcher"
            )
        try:
            obj = create_source(part)
        except (ImportError, RuntimeError) as e:
            # 链式/auto 时跳过未装依赖或未配 token 的源；单源则直接抛错
            if len(parts) == 1:
                raise
            logger.warning("跳过数据源 %s: %s", part, e)
            errors.append(f"{part}: {e}")
            continue
        if not isinstance(obj, Fetcher):
            raise TypeError(f"{part} factory 未返回 Fetcher")
        fetchers.append(obj)

    if not fetchers:
        raise RuntimeError(
            "没有可用的数据源 Fetcher。"
            + ((" 失败: " + " | ".join(errors)) if errors else "")
        )
    if len(fetchers) == 1:
        return fetchers[0]
    return FailoverFetcher(*fetchers)


def get_broker(name: str | None = None) -> BrokerClient:
    """返回交易通道客户端（与行情 Fetcher 分离）。"""
    key = (name or settings().broker).strip().lower()
    if key == "paper":
        from qdata.brokers.paper import PaperBroker
        return PaperBroker()
    if key == "miniqmt":
        from qdata.brokers.miniqmt import MiniQmtBroker
        return MiniQmtBroker()
    if key == "easytrader":
        from qdata.brokers.easytrader_broker import EasytraderBroker
        return EasytraderBroker()
    raise ValueError(f"未知 broker={key!r}。可选: paper | miniqmt | easytrader")


def raw_source_candidates(preferred: str | None = None) -> list[str]:
    """Loader 读 Raw 时的候选 source 顺序。"""
    name = (preferred or settings().data_source).strip().lower()
    parts = _parse_chain(name)
    # 仅保留可能写入 Raw 的 historical/realtime 名
    out: list[str] = []
    for p in parts:
        spec = REGISTRY.get(p)
        if spec and spec.kind in ("historical", "realtime"):
            out.append(p)
        elif p == "auto":
            out.extend(DEFAULT_AUTO_CHAIN)
    # 去重保序，并附上全部 historical 作为兜底查找
    seen: set[str] = set()
    ordered: list[str] = []
    for x in out + [s.name for s in list_sources(kind="historical")]:
        if x not in seen:
            seen.add(x)
            ordered.append(x)
    return ordered


def format_sources_table() -> str:
    s = settings()
    lines = [
        f"{'name':<14} {'kind':<11} {'extra':<14} {'local':<5} {'on':<4} datasets",
        "-" * 78,
    ]
    for spec in list_sources():
        ds = ",".join(sorted(spec.datasets)) if spec.datasets else "-"
        if spec.name == "tushare":
            on = "yes" if s.tushare_enabled else "no"
        elif spec.name == "joinquant":
            on = "yes" if s.joinquant_enabled else "no"
        elif spec.kind == "broker":
            on = "-"
        else:
            on = "yes"
        lines.append(
            f"{spec.name:<14} {spec.kind:<11} {(spec.extra or '-'):<14} "
            f"{'yes' if spec.requires_local else 'no':<5} {on:<4} {ds}"
        )
    lines.append("")
    lines.append(
        f"Tushare 开关: QDATA_TUSHARE_ENABLED={str(s.tushare_enabled).lower()} "
        f"(token={'已配置' if (s.tushare_token or '').strip() else '未配置'})"
    )
    lines.append(
        f"JoinQuant 开关: QDATA_JOINQUANT_ENABLED={str(s.joinquant_enabled).lower()} "
        f"(user={'已配置' if (s.joinquant_user or '').strip() else '未配置'})"
    )
    return "\n".join(lines)
