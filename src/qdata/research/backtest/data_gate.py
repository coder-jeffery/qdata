"""DataGate：DataAPI / CH 批量读数缓存。"""

from __future__ import annotations

import datetime as dt
import logging
import math

import pandas as pd

from qdata import calendar, db
from qdata.api.data_api import DataAPI
from qdata.research.backtest.config import BacktestConfig
from qdata.research.backtest.types import Bar

logger = logging.getLogger(__name__)


def _as_date(v) -> dt.date:
    if isinstance(v, dt.datetime):
        return v.date()
    if isinstance(v, dt.date):
        return v
    return pd.Timestamp(v).date()


class DataGate:
    """一次回测内缓存行情与停牌。

    价格模型 ``post_adjust_nav_raw_limits``：
      - 成交/市值用复权 open·close（由 config.adjust 决定，默认 post）
      - 涨跌停判断用未复权 close vs raw limit
      - 停牌：daily_bar.is_suspended ∪ suspend 表
    """

    def __init__(self, cfg: BacktestConfig, api: DataAPI | None = None) -> None:
        self.cfg = cfg
        if api is not None:
            self.api = api
        else:
            self.api = DataAPI(version=cfg.dataset_version) if cfg.dataset_version else DataAPI()

        self._raw: pd.DataFrame | None = None  # 未复权全字段
        self._suspend: set[tuple[str, dt.date]] = set()
        self._loaded_codes: set[str] = set()

    @property
    def dataset_version(self) -> str:
        return str(self.api.version)

    def trading_days(self, start: dt.date | None = None, end: dt.date | None = None) -> list[dt.date]:
        s = start or self.cfg.start
        e = end or self.cfg.end
        asof = self.api.asof_date()
        if asof is not None:
            e = min(e, asof)
        return calendar.trading_days_between(s, e)

    def ensure_loaded(self, codes: list[str] | set[str]) -> None:
        """按需增量加载代码池行情。"""
        need = {str(c) for c in codes} - self._loaded_codes
        if not need:
            return
        self._load_prices(sorted(need))
        self._load_suspend(sorted(need))
        self._loaded_codes |= need

    def _load_prices(self, codes: list[str]) -> None:
        if not codes:
            return
        start, end = self.cfg.start, self.cfg.end
        asof = self.api.asof_date()
        if asof is not None:
            end = min(end, asof)
        df = db.query_df(
            """
            SELECT b.trade_date, m.exchange_code,
                   b.open, b.close, b.volume, b.adj_factor,
                   b.up_limit, b.down_limit, b.is_suspended
            FROM daily_bar b
            INNER JOIN security_master m USING (security_id)
            WHERE m.exchange_code IN %(codes)s
              AND b.trade_date BETWEEN %(s)s AND %(e)s
            ORDER BY m.exchange_code, b.trade_date
            """,
            {"codes": tuple(codes), "s": start, "e": end},
        )
        if df is None or df.empty:
            logger.warning("DataGate 无行情 codes=%s %s~%s", len(codes), start, end)
            return
        df = df.copy()
        df["trade_date"] = df["trade_date"].map(_as_date)
        df["exchange_code"] = df["exchange_code"].astype(str)
        if self._raw is None or self._raw.empty:
            self._raw = df
        else:
            self._raw = pd.concat([self._raw, df], ignore_index=True)
            self._raw = self._raw.drop_duplicates(
                ["trade_date", "exchange_code"], keep="last"
            )

    def _load_suspend(self, codes: list[str]) -> None:
        if not codes:
            return
        start, end = self.cfg.start, self.cfg.end
        try:
            df = db.query_df(
                """
                SELECT m.exchange_code, s.suspend_date
                FROM suspend s
                INNER JOIN security_master m USING (security_id)
                WHERE m.exchange_code IN %(codes)s
                  AND s.suspend_date BETWEEN %(s)s AND %(e)s
                """,
                {"codes": tuple(codes), "s": start, "e": end},
            )
        except Exception as e:
            logger.warning("读取 suspend 表失败，仅用 daily_bar.is_suspended: %s", e)
            return
        if df is None or df.empty:
            return
        for _, r in df.iterrows():
            self._suspend.add((str(r["exchange_code"]), _as_date(r["suspend_date"])))

    def is_suspended(self, code: str, d: dt.date) -> bool:
        if (code, d) in self._suspend:
            return True
        if self._raw is None or self._raw.empty:
            return False
        m = self._raw[
            (self._raw["exchange_code"] == code) & (self._raw["trade_date"] == d)
        ]
        if m.empty:
            return False
        return bool(m.iloc[0].get("is_suspended", False))

    def _adj_factor(self, row: pd.Series) -> float:
        adj = float(row.get("adj_factor") or 1.0)
        if not math.isfinite(adj) or adj <= 0:
            return 1.0
        if self.cfg.adjust == "none":
            return 1.0
        if self.cfg.adjust == "post":
            return adj
        # pre：相对该标的区间末因子
        code = str(row["exchange_code"])
        sub = self._raw[self._raw["exchange_code"] == code] if self._raw is not None else None
        if sub is None or sub.empty:
            return 1.0
        latest = float(sub["adj_factor"].iloc[-1] or 1.0)
        if latest <= 0:
            return 1.0
        return adj / latest

    def bars_on(self, d: dt.date, codes: list[str] | set[str]) -> dict[str, Bar]:
        codes = [str(c) for c in codes]
        self.ensure_loaded(codes)
        out: dict[str, Bar] = {}
        if self._raw is None or self._raw.empty:
            return out
        day = self._raw[self._raw["trade_date"] == d]
        if day.empty:
            return out
        for code in codes:
            rows = day[day["exchange_code"] == code]
            if rows.empty:
                continue
            r = rows.iloc[0]
            fac = self._adj_factor(r)
            raw_open = float(r["open"])
            raw_close = float(r["close"])
            up = r.get("up_limit")
            down = r.get("down_limit")
            up_f = float(up) if up is not None and pd.notna(up) else None
            down_f = float(down) if down is not None and pd.notna(down) else None
            sus = bool(r.get("is_suspended", False)) or self.is_suspended(code, d)
            vol = r.get("volume")
            out[code] = Bar(
                exchange_code=code,
                open=raw_open * fac,
                close=raw_close,  # 限价判断用未复权收盘
                up_limit=up_f,
                down_limit=down_f,
                suspended=sus,
                volume=float(vol) if vol is not None and pd.notna(vol) else None,
            )
        return out

    def mark_prices(self, d: dt.date, codes: list[str] | set[str]) -> dict[str, float]:
        """收盘市值计价（复权 close）。"""
        codes = [str(c) for c in codes]
        self.ensure_loaded(codes)
        out: dict[str, float] = {}
        if self._raw is None or self._raw.empty:
            return out
        day = self._raw[self._raw["trade_date"] == d]
        for code in codes:
            rows = day[day["exchange_code"] == code]
            if rows.empty:
                continue
            r = rows.iloc[0]
            fac = self._adj_factor(r)
            px = float(r["close"]) * fac
            if px > 0 and math.isfinite(px):
                out[code] = px
        return out

    def benchmark_returns(
        self, code: str | None = None
    ) -> tuple[pd.Series, str]:
        """基准日收益。

        返回 ``(rets, mode)``：
          - ``security_price``：基准代码自身在 daily_bar 有行情
          - ``index_members_equal``：指数成分当日等权收益（无指数独立行情时）
          - ``unavailable``：无法计算
        """
        b = code or self.cfg.benchmark
        if not b:
            return pd.Series(dtype=float), "unavailable"

        # 1) 尝试作为证券行情
        self.ensure_loaded([b])
        if self._raw is not None and not self._raw.empty:
            sub = self._raw[self._raw["exchange_code"] == b].sort_values("trade_date")
            if len(sub) >= 2:
                closes = []
                dates = []
                for _, r in sub.iterrows():
                    fac = self._adj_factor(r)
                    closes.append(float(r["close"]) * fac)
                    dates.append(_as_date(r["trade_date"]))
                s = pd.Series(closes, index=dates, dtype=float).pct_change().dropna()
                if not s.empty:
                    return s, "security_price"

        # 2) 指数成分等权（库内通常无指数 OHLC）
        syn = self._index_member_equal_returns(b)
        if not syn.empty:
            return syn, "index_members_equal"
        return pd.Series(dtype=float), "unavailable"

    def _index_member_equal_returns(self, index_code: str) -> pd.Series:
        days = self.trading_days()
        if len(days) < 2:
            return pd.Series(dtype=float)
        try:
            mem = db.query_df(
                """
                SELECT m.exchange_code, im.in_date, im.out_date
                FROM index_member im
                INNER JOIN security_master m ON m.security_id = im.security_id
                WHERE im.index_code = %(idx)s
                  AND im.in_date <= %(e)s AND im.out_date > %(s)s
                """,
                {"idx": index_code, "s": days[0], "e": days[-1]},
            )
        except Exception as e:
            logger.warning("读取 index_member 失败: %s", e)
            return pd.Series(dtype=float)
        if mem is None or mem.empty:
            return pd.Series(dtype=float)

        codes = sorted(mem["exchange_code"].astype(str).unique().tolist())
        self.ensure_loaded(codes)
        if self._raw is None or self._raw.empty:
            return pd.Series(dtype=float)

        mem = mem.copy()
        mem["exchange_code"] = mem["exchange_code"].astype(str)
        mem["in_date"] = mem["in_date"].map(_as_date)
        mem["out_date"] = mem["out_date"].map(_as_date)

        # 复权收盘面板
        raw = self._raw[self._raw["exchange_code"].isin(codes)].copy()
        adj = pd.to_numeric(raw["adj_factor"], errors="coerce").fillna(1.0).replace(0, 1.0)
        close = pd.to_numeric(raw["close"], errors="coerce")
        if self.cfg.adjust == "none":
            raw["adj_close"] = close
        else:
            # post / pre：成分基准用 post 更稳；pre 简化为 post（超额对比同口径）
            raw["adj_close"] = close * adj
        panel = raw.pivot_table(
            index="trade_date", columns="exchange_code", values="adj_close", aggfunc="last"
        ).sort_index()
        if panel.empty or len(panel.index) < 2:
            return pd.Series(dtype=float)

        rets_panel = panel.pct_change()
        out: dict[dt.date, float] = {}
        for i in range(1, len(days)):
            d = days[i]
            prev = days[i - 1]
            if d not in rets_panel.index or prev not in panel.index:
                continue
            active = mem[(mem["in_date"] <= d) & (mem["out_date"] > d)]["exchange_code"]
            cols = [c for c in active if c in rets_panel.columns]
            if not cols:
                continue
            row = rets_panel.loc[d, cols]
            row = pd.to_numeric(row, errors="coerce").dropna()
            if row.empty:
                continue
            out[d] = float(row.mean())
        if not out:
            return pd.Series(dtype=float)
        return pd.Series(out).sort_index()
