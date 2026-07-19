"""采集层抽象基类。

每个数据源实现一个 Fetcher 子类；每个数据集注册为一个 fetch 方法。
基类统一处理：限频、重试（指数退避）、列名标准化。
输出的 DataFrame 一律使用内部标准列名（exchange_code / trade_date / ...），
下游 Raw 区与 Loader 不感知数据源差异。
"""

from __future__ import annotations

import abc
import datetime as dt
import threading
import time

import pandas as pd
from tenacity import retry, stop_after_attempt, wait_exponential


class RateLimiter:
    """简单滑动窗口限频器（每分钟 N 次），抑制东财/新浪限流。"""

    def __init__(self, calls_per_minute: int):
        self._interval = 60.0 / max(calls_per_minute, 1)
        self._lock = threading.Lock()
        self._last = 0.0

    def acquire(self) -> None:
        with self._lock:
            wait = self._last + self._interval - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()


class Fetcher(abc.ABC):
    """数据源适配器基类。

    子类实现 `_fetch_raw`，基类包装限频与重试。
    dataset 名与 Raw 区目录、Loader 一一对应。
    """

    source: str  # 如 'akshare'

    def __init__(self, rate_limiter: RateLimiter):
        self._limiter = rate_limiter

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, max=60), reraise=True)
    def fetch(self, dataset: str, trade_date: dt.date) -> pd.DataFrame:
        """拉取某数据集某天的数据，返回标准列名 DataFrame。"""
        self._limiter.acquire()
        df = self._fetch_raw(dataset, trade_date)
        return self._normalize(dataset, df)

    @abc.abstractmethod
    def _fetch_raw(self, dataset: str, trade_date: dt.date) -> pd.DataFrame: ...

    @abc.abstractmethod
    def _normalize(self, dataset: str, df: pd.DataFrame) -> pd.DataFrame:
        """源字段 → 标准列名映射，日期字符串 → date 类型。"""
