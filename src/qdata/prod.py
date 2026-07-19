"""生产主源固化：单一数据源 + 全市场（禁止 MAX_SYMBOLS / auto）。

环境变量：
  QDATA_PROD_SOURCE=baostock|tushare|joinquant  # 生产唯一主源（必填于生产作业）
  QDATA_PROD_MIN_UNIVERSE=500                   # smoke 全市场下限（联调可调低）

说明：
  - 日常默认 baostock；BaoStock 网络抖动时可用 joinquant 做 DD1 缺口补洞。
  - akshare/efinance 等易漂移源仍禁止作为生产主源。
"""

from __future__ import annotations

import logging
import os

from qdata.config import settings

logger = logging.getLogger(__name__)

# 允许作为生产主源的历史源（单一、稳定、可全市场按日拉取）
PROD_SOURCES = frozenset({"baostock", "tushare", "joinquant"})


def resolve_prod_source(override: str | None = None) -> str:
    """解析并校验生产主源名。"""
    s = settings()
    raw = (override or s.prod_source or s.data_source or "").strip().lower()
    if not raw:
        raise RuntimeError(
            "未配置生产主源。请在 .env 设置 QDATA_PROD_SOURCE=baostock|tushare|joinquant"
        )
    if "," in raw or raw == "auto":
        raise RuntimeError(
            f"生产主源禁止 auto/多源链（当前={raw!r}）。"
            f"请设置单一源 QDATA_PROD_SOURCE=baostock|tushare|joinquant"
        )
    if raw not in PROD_SOURCES:
        raise RuntimeError(
            f"生产主源 {raw!r} 不在允许列表 {sorted(PROD_SOURCES)}。"
            f"正式发布勿使用 akshare/efinance 等易漂移源。"
        )
    if raw == "tushare":
        if not s.tushare_enabled:
            raise RuntimeError(
                "生产主源为 tushare 时需 QDATA_TUSHARE_ENABLED=true"
            )
        if not (s.tushare_token or "").strip():
            raise RuntimeError(
                "生产主源为 tushare 时需配置 QDATA_TUSHARE_TOKEN"
            )
    if raw == "joinquant":
        if not getattr(s, "joinquant_enabled", False):
            raise RuntimeError(
                "生产主源为 joinquant 时需 QDATA_JOINQUANT_ENABLED=true"
            )
        if not (getattr(s, "joinquant_user", "") or "").strip():
            raise RuntimeError(
                "生产主源为 joinquant 时需配置 QDATA_JOINQUANT_USER"
            )
    return raw


def apply_prod_mode(source: str | None = None) -> str:
    """切换到生产模式：单一主源 + 全市场（MAX_SYMBOLS=0）。

    写入进程环境变量并清空 settings 缓存，供后续 Fetcher/Loader 读取。
    返回实际主源名。
    """
    name = resolve_prod_source(source)
    os.environ["QDATA_DATA_SOURCE"] = name
    os.environ["QDATA_AKSHARE_MAX_SYMBOLS"] = "0"
    os.environ["QDATA_PROD_SOURCE"] = name
    settings.cache_clear()
    s = settings()
    if s.akshare_max_symbols != 0:
        # pydantic 可能从 .env 再读到旧值；强制覆盖
        os.environ["QDATA_AKSHARE_MAX_SYMBOLS"] = "0"
        settings.cache_clear()
        s = settings()
    if s.akshare_max_symbols != 0:
        raise RuntimeError(
            f"无法关闭 MAX_SYMBOLS（当前={s.akshare_max_symbols}）。"
            f"请从 .env 删除或设 QDATA_AKSHARE_MAX_SYMBOLS=0"
        )
    if s.data_source.strip().lower() != name:
        raise RuntimeError(
            f"生产模式 data_source 未生效: want={name} got={s.data_source}"
        )
    logger.info(
        "生产模式已启用: prod_source=%s max_symbols=0（全市场）",
        name,
    )
    return name


def prod_min_universe() -> int:
    return max(1, int(settings().prod_min_universe))
