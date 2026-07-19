"""种子因子定义与计算。

因子写入 factor_value(factor_name, version, trade_date, security_id, value)。
重算请换新 version，避免覆盖已有回测依赖。

价值因子约定：
  - ``daily_basic.total_mv`` 单位为万元；财务科目为元 → 市值(元)=total_mv×10000
  - ``ep`` = PIT ``net_profit`` / 市值(元)（最新已公告报告期利润，非强制 TTM）
  - ``bp`` = PIT ``equity`` / 市值(元)
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass
from typing import Callable

import numpy as np
import pandas as pd

from qdata import calendar, db

logger = logging.getLogger(__name__)

DEFAULT_FACTOR_VERSION = "v1"

# daily_basic.total_mv（万元）→ 元
_MV_WAN_TO_YUAN = 10_000.0


@dataclass(frozen=True)
class FactorSpec:
    name: str
    lookback: int
    needs_turnover: bool = False
    needs_value: bool = False  # ep/bp：PIT 财务 + 市值


SEED_FACTORS: tuple[FactorSpec, ...] = (
    FactorSpec("mom_20", 20),
    FactorSpec("mom_60", 60),
    FactorSpec("vol_20", 20),
    FactorSpec("turn_20", 20, needs_turnover=True),
    FactorSpec("ep", 0, needs_value=True),
    FactorSpec("bp", 0, needs_value=True),
)


def list_seed_factors() -> list[str]:
    return [f.name for f in SEED_FACTORS]


def _post_close(df: pd.DataFrame) -> pd.Series:
    return df["close"] * df["adj_factor"].replace(0, np.nan)


def _as_dates(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s, errors="coerce").dt.date


def _load_bars(end: dt.date, lookback_calendar_days: int) -> pd.DataFrame:
    """加载 [end-lookback, end] 的日线（按日历宽取，再按交易日截断）。"""
    start = end - dt.timedelta(days=lookback_calendar_days)
    df = db.query_df(
        """
        SELECT trade_date, security_id, close, adj_factor, volume, amount
        FROM daily_bar
        WHERE trade_date BETWEEN %(s)s AND %(e)s
        ORDER BY security_id, trade_date
        """,
        {"s": start, "e": end},
    )
    if df is None or df.empty:
        return pd.DataFrame()
    df = df.copy()
    df["trade_date"] = _as_dates(df["trade_date"])
    return df


def _load_turnover(end: dt.date, lookback_calendar_days: int) -> pd.DataFrame:
    start = end - dt.timedelta(days=lookback_calendar_days)
    try:
        df = db.query_df(
            """
            SELECT trade_date, security_id, turnover_rate
            FROM daily_basic
            WHERE trade_date BETWEEN %(s)s AND %(e)s
            ORDER BY security_id, trade_date
            """,
            {"s": start, "e": end},
        )
    except Exception as e:
        logger.warning("读取 daily_basic 失败（turn_* 将跳过）: %s", e)
        return pd.DataFrame()
    if df is None or df.empty:
        return pd.DataFrame()
    df = df.copy()
    df["trade_date"] = _as_dates(df["trade_date"])
    return df


def _load_total_mv(trade_date: dt.date) -> pd.DataFrame:
    """当日市值（万元）。"""
    try:
        df = db.query_df(
            """
            SELECT trade_date, security_id, total_mv
            FROM daily_basic
            WHERE trade_date = %(d)s
              AND isNotNull(total_mv) AND total_mv > 0 AND isFinite(total_mv)
            """,
            {"d": trade_date},
        )
    except Exception as e:
        logger.warning("读取 daily_basic.total_mv 失败: %s", e)
        return pd.DataFrame()
    if df is None or df.empty:
        return pd.DataFrame()
    df = df.copy()
    df["trade_date"] = _as_dates(df["trade_date"])
    return df


def _load_pit_field(field: str, as_of: dt.date) -> pd.DataFrame:
    """T 日可见的最新财务科目（与 DataAPI.get_fundamental 同规则）。"""
    try:
        df = db.query_df(
            """
            SELECT security_id, fields[%(f)s] AS value
            FROM fin_statement
            WHERE ann_date <= %(d)s
              AND mapContains(fields, %(f)s)
            ORDER BY report_date DESC, ann_date DESC
            LIMIT 1 BY security_id
            """,
            {"f": field, "d": as_of},
        )
    except Exception as e:
        logger.warning("读取 fin_statement.%s 失败: %s", field, e)
        return pd.DataFrame()
    if df is None or df.empty:
        return pd.DataFrame()
    return df


def _mom(panel: pd.DataFrame, trade_date: dt.date, n: int) -> pd.DataFrame:
    """后复权动量：close_adj[t] / close_adj[t-n] - 1。"""
    rows: list[dict] = []
    for sid, g in panel.groupby("security_id"):
        g = g.sort_values("trade_date")
        if trade_date not in set(g["trade_date"]):
            continue
        # 取截止 trade_date 的序列
        g = g[g["trade_date"] <= trade_date]
        if len(g) < n + 1:
            continue
        px = _post_close(g).to_numpy(dtype=float)
        if not np.isfinite(px[-1]) or not np.isfinite(px[-(n + 1)]) or px[-(n + 1)] == 0:
            continue
        rows.append({
            "trade_date": trade_date,
            "security_id": int(sid),
            "value": float(px[-1] / px[-(n + 1)] - 1.0),
        })
    return pd.DataFrame(rows)


def _vol(panel: pd.DataFrame, trade_date: dt.date, n: int) -> pd.DataFrame:
    """近 n 日后复权收益标准差。"""
    rows: list[dict] = []
    for sid, g in panel.groupby("security_id"):
        g = g.sort_values("trade_date")
        g = g[g["trade_date"] <= trade_date]
        if len(g) < n + 1:
            continue
        if g["trade_date"].iloc[-1] != trade_date:
            continue
        px = _post_close(g).to_numpy(dtype=float)
        rets = px[1:] / px[:-1] - 1.0
        window = rets[-n:]
        if len(window) < n or not np.isfinite(window).all():
            continue
        rows.append({
            "trade_date": trade_date,
            "security_id": int(sid),
            "value": float(np.std(window, ddof=1)),
        })
    return pd.DataFrame(rows)


def _turn(
    turn_df: pd.DataFrame,
    trade_date: dt.date,
    n: int,
    *,
    min_periods: int | None = None,
) -> pd.DataFrame:
    """近 n 个交易日换手率均值。

    窗口内允许少量缺失（默认至少 3/4 有效观测）；当日换手必须有值。
    否则一处 NaN 会误杀全市场（多源 basic 拼日常见）。
    """
    if turn_df is None or turn_df.empty:
        return pd.DataFrame()
    need = min_periods if min_periods is not None else max(1, (n * 3) // 4)
    rows: list[dict] = []
    for sid, g in turn_df.groupby("security_id"):
        g = g.sort_values("trade_date")
        g = g[g["trade_date"] <= trade_date]
        if len(g) < need:
            continue
        if g["trade_date"].iloc[-1] != trade_date:
            continue
        w = pd.to_numeric(g["turnover_rate"].iloc[-n:], errors="coerce")
        if int(w.notna().sum()) < need:
            continue
        if pd.isna(w.iloc[-1]):
            continue
        rows.append({
            "trade_date": trade_date,
            "security_id": int(sid),
            "value": float(w.mean(skipna=True)),
        })
    return pd.DataFrame(rows)


def _value_ratio(
    mv_df: pd.DataFrame,
    pit_df: pd.DataFrame,
    trade_date: dt.date,
) -> pd.DataFrame:
    """fundamental(元) / market_cap(元)；跳过非有限或市值无效。"""
    if mv_df is None or mv_df.empty or pit_df is None or pit_df.empty:
        return pd.DataFrame()
    mv = mv_df[["security_id", "total_mv"]].copy()
    pit = pit_df.rename(columns={"value": "fund"})[["security_id", "fund"]]
    m = mv.merge(pit, on="security_id", how="inner")
    if m.empty:
        return pd.DataFrame()
    cap = pd.to_numeric(m["total_mv"], errors="coerce") * _MV_WAN_TO_YUAN
    fund = pd.to_numeric(m["fund"], errors="coerce")
    ratio = fund / cap
    ok = cap.gt(0) & fund.notna() & np.isfinite(ratio.to_numpy(dtype=float))
    if not bool(ok.any()):
        return pd.DataFrame()
    return pd.DataFrame({
        "trade_date": trade_date,
        "security_id": m.loc[ok, "security_id"].astype(int).to_numpy(),
        "value": ratio.loc[ok].astype(float).to_numpy(),
    })


def _ep(mv_df: pd.DataFrame, pit_profit: pd.DataFrame, trade_date: dt.date) -> pd.DataFrame:
    return _value_ratio(mv_df, pit_profit, trade_date)


def _bp(mv_df: pd.DataFrame, pit_equity: pd.DataFrame, trade_date: dt.date) -> pd.DataFrame:
    return _value_ratio(mv_df, pit_equity, trade_date)


_COMPUTE: dict[str, Callable[..., pd.DataFrame]] = {
    "mom_20": lambda bars, turns, d: _mom(bars, d, 20),
    "mom_60": lambda bars, turns, d: _mom(bars, d, 60),
    "vol_20": lambda bars, turns, d: _vol(bars, d, 20),
    "turn_20": lambda bars, turns, d: _turn(turns, d, 20),
}


def replace_factor_day(
    name: str,
    trade_date: dt.date,
    df: pd.DataFrame,
    *,
    version: str = DEFAULT_FACTOR_VERSION,
) -> int:
    """幂等写入某日某因子某版本。"""
    ch = db.client()
    ch.command(
        """
        ALTER TABLE factor_value DELETE
        WHERE factor_name = %(n)s AND version = %(v)s AND trade_date = %(d)s
        """,
        parameters={"n": name, "v": version, "d": trade_date},
    )
    if df is None or df.empty:
        return 0
    out = df.copy()
    out["factor_name"] = name
    out["version"] = version
    out["trade_date"] = trade_date
    return db.insert_df(
        "factor_value",
        out[["trade_date", "security_id", "factor_name", "version", "value"]],
    )


def compute_factors_for_day(
    trade_date: dt.date,
    *,
    factors: list[str] | None = None,
    version: str = DEFAULT_FACTOR_VERSION,
) -> dict[str, int]:
    """计算并写入种子因子，返回 {factor_name: rows}。"""
    specs = {f.name: f for f in SEED_FACTORS}
    names = factors or list_seed_factors()
    unknown = [n for n in names if n not in specs]
    if unknown:
        raise ValueError(f"未知因子: {unknown}，可选 {list_seed_factors()}")

    price_names = [n for n in names if not specs[n].needs_value]
    value_names = [n for n in names if specs[n].needs_value]

    bars = pd.DataFrame()
    turns = pd.DataFrame()
    if price_names:
        max_lb = max(specs[n].lookback for n in price_names)
        # 交易日约 20/月，日历天数取 lookback*3 + 缓冲
        cal_days = max_lb * 3 + 10
        bars = _load_bars(trade_date, cal_days)
        need_turn = any(specs[n].needs_turnover for n in price_names)
        turns = _load_turnover(trade_date, cal_days) if need_turn else pd.DataFrame()
        if bars is None or bars.empty:
            logger.warning("daily_bar 为空 @ %s，价格类因子无法计算", trade_date)
        else:
            day_n = int((bars["trade_date"] == trade_date).sum())
            if day_n == 0:
                logger.warning("当日无 daily_bar: %s", trade_date)

    mv_df = pd.DataFrame()
    pit_profit = pd.DataFrame()
    pit_equity = pd.DataFrame()
    if value_names:
        mv_df = _load_total_mv(trade_date)
        if "ep" in value_names:
            pit_profit = _load_pit_field("net_profit", trade_date)
        if "bp" in value_names:
            pit_equity = _load_pit_field("equity", trade_date)
        if mv_df is None or mv_df.empty:
            logger.warning("当日无 total_mv: %s", trade_date)

    counts: dict[str, int] = {}
    for name in names:
        if specs[name].needs_value:
            if mv_df is None or mv_df.empty:
                logger.warning("%s 跳过：无 daily_basic.total_mv", name)
                part = pd.DataFrame()
            elif name == "ep":
                if pit_profit is None or pit_profit.empty:
                    logger.warning("ep 跳过：无 PIT net_profit")
                    part = pd.DataFrame()
                else:
                    part = _ep(mv_df, pit_profit, trade_date)
            elif name == "bp":
                if pit_equity is None or pit_equity.empty:
                    logger.warning("bp 跳过：无 PIT equity")
                    part = pd.DataFrame()
                else:
                    part = _bp(mv_df, pit_equity, trade_date)
            else:
                raise ValueError(f"未实现的价值因子: {name}")
        else:
            if bars is None or bars.empty:
                part = pd.DataFrame()
            elif specs[name].needs_turnover and (turns is None or turns.empty):
                logger.warning("%s 跳过：无 daily_basic.turnover_rate", name)
                part = pd.DataFrame()
            else:
                part = _COMPUTE[name](bars, turns, trade_date)
        n = replace_factor_day(name, trade_date, part, version=version)
        counts[name] = n
        logger.info("factor %s@%s version=%s rows=%s", name, trade_date, version, n)
    return counts


def compute_factors_range(
    start: dt.date,
    end: dt.date,
    *,
    factors: list[str] | None = None,
    version: str = DEFAULT_FACTOR_VERSION,
) -> dict[str, dict[str, int]]:
    """按交易日区间计算。"""
    days = calendar.trading_days_between(start, end)
    if not days:
        raise RuntimeError(f"区间无交易日: {start}~{end}（请先 sync_calendar）")
    out: dict[str, dict[str, int]] = {}
    for d in days:
        out[d.isoformat()] = compute_factors_for_day(d, factors=factors, version=version)
    return out
