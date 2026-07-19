"""权重信号端口。"""

from __future__ import annotations

import datetime as dt
from typing import Protocol

import pandas as pd

from qdata.research.portfolio import RebalanceSpec, build_weight_series


class WeightSignalProvider(Protocol):
    def weight_on(self, d: dt.date) -> pd.DataFrame:
        """空 = 当日无调仓；非空列: exchange_code, weight。"""
        ...

    def meta(self) -> dict:
        ...


class FromWeightFrame:
    """吃已有权重面板（如 build_weight_series 输出）。"""

    def __init__(self, weights: pd.DataFrame, *, meta: dict | None = None) -> None:
        if weights is None or weights.empty:
            self._by_date: dict[dt.date, pd.DataFrame] = {}
            self._meta = meta or {}
            return
        df = weights.copy()
        need = {"trade_date", "exchange_code", "weight"}
        if not need.issubset(df.columns):
            raise ValueError(f"weights 需含 {need}")
        df["trade_date"] = pd.to_datetime(df["trade_date"], errors="coerce").dt.date
        df["exchange_code"] = df["exchange_code"].astype(str)
        df["weight"] = pd.to_numeric(df["weight"], errors="coerce")
        df = df.dropna(subset=["trade_date", "exchange_code", "weight"])
        self._by_date = {
            d: g[["exchange_code", "weight"]].reset_index(drop=True)
            for d, g in df.groupby("trade_date", sort=True)
        }
        self._meta = dict(meta or {})
        # 透传 attrs
        attrs = getattr(weights, "attrs", None) or {}
        for k in ("dataset_version", "factor", "universe", "weight_method"):
            if k in attrs and k not in self._meta:
                self._meta[k] = attrs[k]

    def weight_on(self, d: dt.date) -> pd.DataFrame:
        return self._by_date.get(d, pd.DataFrame(columns=["exchange_code", "weight"])).copy()

    def meta(self) -> dict:
        return dict(self._meta)

    def all_codes(self) -> list[str]:
        codes: set[str] = set()
        for g in self._by_date.values():
            codes.update(g["exchange_code"].astype(str).tolist())
        return sorted(codes)


class FromRebalanceSpec:
    """内部预计算 build_weight_series（BT-3 主路径；BT-2 CLI 也可直接用）。"""

    def __init__(
        self,
        start: dt.date,
        end: dt.date,
        *,
        spec: RebalanceSpec | None = None,
        api=None,
    ) -> None:
        from qdata.api.data_api import DataAPI

        self.spec = spec or RebalanceSpec()
        api = api or DataAPI()
        weights = build_weight_series(start, end, api=api, spec=self.spec)
        self._inner = FromWeightFrame(
            weights,
            meta={
                "factor": self.spec.factor,
                "factor_version": self.spec.factor_version,
                "universe": self.spec.universe,
                "weight_method": self.spec.weight_method,
                "dataset_version": weights.attrs.get("dataset_version"),
            },
        )

    def weight_on(self, d: dt.date) -> pd.DataFrame:
        return self._inner.weight_on(d)

    def meta(self) -> dict:
        return self._inner.meta()

    def all_codes(self) -> list[str]:
        return self._inner.all_codes()
