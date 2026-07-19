"""多源故障转移：按顺序尝试，空结果或异常则下一个；回退后固定该源。"""

from __future__ import annotations

import datetime as dt
import logging

import pandas as pd

from qdata.fetchers.base import Fetcher, RateLimiter

logger = logging.getLogger(__name__)

# 当日无公告/无停牌时返回空表是合法结果，不可因此回退到下一源
_EMPTY_OK_DATASETS = frozenset({
    "suspend", "income", "balancesheet", "cashflow",
})


class FailoverFetcher(Fetcher):
    """包装多个 Fetcher；一旦某备源成功，后续数据集固定走该源。"""

    def __init__(self, *fetchers: Fetcher) -> None:
        if len(fetchers) < 2:
            raise ValueError("FailoverFetcher 至少需要 2 个源")
        super().__init__(RateLimiter(calls_per_minute=10_000))
        self._fetchers = list(fetchers)
        self._pinned: Fetcher | None = None
        self.source = fetchers[0].source

    def fetch(self, dataset: str, trade_date: dt.date) -> pd.DataFrame:
        if self._pinned is not None:
            df = self._pinned.fetch(dataset, trade_date)
            self.source = self._pinned.source
            logger.info("固定源 %s 拉取 %s，行数=%s", self.source, dataset, len(df))
            return df

        errors: list[str] = []
        for i, fetcher in enumerate(self._fetchers):
            try:
                df = fetcher.fetch(dataset, trade_date)
                if df is not None and not df.empty:
                    self.source = fetcher.source
                    if i > 0:
                        self._pinned = fetcher
                        logger.info(
                            "回退并固定 %s 拉取 %s，行数=%s",
                            self.source, dataset, len(df),
                        )
                    else:
                        logger.info("使用主源 %s 拉取 %s", self.source, dataset)
                    return df
                if dataset in _EMPTY_OK_DATASETS and df is not None:
                    self.source = fetcher.source
                    logger.info(
                        "源 %s 拉取 %s 合法空表（不回退）", self.source, dataset,
                    )
                    return df
                raise RuntimeError(f"{fetcher.source} 返回空结果")
            except Exception as e:
                errors.append(f"{fetcher.source}: {e}")
                nxt = self._fetchers[i + 1].source if i + 1 < len(self._fetchers) else None
                logger.warning(
                    "源 %s 拉取 %s 失败: %s%s",
                    fetcher.source,
                    dataset,
                    e,
                    f"；尝试 {nxt}" if nxt else "",
                )
        raise RuntimeError(
            f"全部数据源失败 dataset={dataset} date={trade_date}: " + " | ".join(errors)
        )

    def _fetch_raw(self, dataset: str, trade_date: dt.date) -> pd.DataFrame:
        raise NotImplementedError("FailoverFetcher 使用 fetch() 入口")

    def _normalize(self, dataset: str, df: pd.DataFrame) -> pd.DataFrame:
        return df
