"""数据质量校验框架 + A 股规则集。

规则分两级：
- HARD：失败阻断 dataset_version 发布（下游研究端看不到这天的数据）
- SOFT：失败只告警，记录后放行

新增规则 = 写一个函数 + @rule 装饰器注册，DAG 端统一调 run_all()。
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from enum import Enum
from typing import Callable

import pandas as pd

from qdata import db
from qdata.constants import Board, NO_LIMIT_DAYS, board_of, limit_prices


class Severity(str, Enum):
    HARD = "hard"
    SOFT = "soft"


@dataclass
class CheckResult:
    name: str
    severity: Severity
    passed: bool
    message: str = ""


_REGISTRY: list[tuple[str, Severity, Callable[[dt.date], CheckResult]]] = []


def rule(name: str, severity: Severity):
    def deco(fn: Callable[[dt.date], CheckResult]):
        _REGISTRY.append((name, severity, fn))
        return fn
    return deco


def run_all(trade_date: dt.date) -> list[CheckResult]:
    results = [fn(trade_date) for _, _, fn in _REGISTRY]
    return results


def has_blocking_failure(results: list[CheckResult]) -> bool:
    return any(r.severity == Severity.HARD and not r.passed for r in results)


def _as_date(v) -> dt.date | None:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    if isinstance(v, dt.date) and not isinstance(v, dt.datetime):
        return v
    try:
        return pd.Timestamp(v).date()
    except Exception:
        return None


def _board_from_row(exchange_code: str, board_val: object) -> Board:
    if board_val is not None and str(board_val) in {b.value for b in Board}:
        return Board(str(board_val))
    return board_of(str(exchange_code))


def _in_no_limit_window(trade_date: dt.date, list_date: dt.date | None, board: Board) -> bool:
    """上市初期无涨跌幅限制窗口（及复权大幅波动可接受窗口）。"""
    if list_date is None:
        return False
    days = NO_LIMIT_DAYS.get(board, 1)
    return list_date <= trade_date < list_date + dt.timedelta(days=days)


# ---------------------------------------------------------------------
# A 股规则集
# ---------------------------------------------------------------------

@rule("行数完整性", Severity.HARD)
def check_row_count(d: dt.date) -> CheckResult:
    """日线行数门禁：全市场下限 + 相对昨量/主数据合理性。

    联调开启 MAX_SYMBOLS 时降为软规则。
    """
    from qdata.config import settings

    got = int(
        db.query_df(
            "SELECT count() AS n FROM daily_bar WHERE trade_date = %(d)s", {"d": d}
        )["n"][0]
    )
    master_n = int(
        db.query_df(
            """
            SELECT uniqExact(security_id) AS n FROM security_master
            WHERE list_date <= %(d)s AND (delist_date IS NULL OR delist_date > %(d)s)
            """,
            {"d": d},
        )["n"][0]
    )
    prev_n = 0
    try:
        prev = db.query_df(
            "SELECT prev_open AS p FROM trade_calendar WHERE cal_date = %(d)s LIMIT 1",
            {"d": d},
        )
        if prev is not None and not prev.empty:
            p = prev["p"][0]
            prev_n = int(
                db.query_df(
                    "SELECT count() AS n FROM daily_bar WHERE trade_date = %(p)s",
                    {"p": p},
                )["n"][0]
            )
    except Exception:
        prev_n = 0

    min_uni = max(1, int(settings().prod_min_universe))
    msg = f"got={got} master≈{master_n} prev={prev_n} min_uni={min_uni}"

    if settings().akshare_max_symbols and settings().akshare_max_symbols > 0:
        soft_ok = got > 0
        return CheckResult(
            "行数完整性",
            Severity.SOFT if soft_ok else Severity.HARD,
            soft_ok,
            msg + f" (MAX_SYMBOLS={settings().akshare_max_symbols})",
        )

    if got < min_uni:
        return CheckResult("行数完整性", Severity.HARD, False, msg + " 低于全市场下限")

    if prev_n >= min_uni:
        drift = abs(got - prev_n) / prev_n
        ok = drift <= 0.05
        return CheckResult(
            "行数完整性",
            Severity.HARD,
            ok,
            msg + f" vs昨漂移={drift:.2%}",
        )

    # 无昨量时：相对主数据允许约 10% 缺口（停牌/源覆盖）
    ok = master_n > 0 and got >= master_n * 0.90
    return CheckResult("行数完整性", Severity.HARD, ok, msg)


@rule("复权连续性", Severity.HARD)
def check_adj_continuity(d: dt.date) -> CheckResult:
    """复权价单日涨跌超 ±21%（排除新股无涨跌幅窗口）→ 疑似复权因子错误。"""
    df = db.query_df(
        """
        SELECT
            b.security_id,
            m.exchange_code,
            m.board,
            m.list_date,
            (b.close * b.adj_factor) / nullIf(p.close * p.adj_factor, 0) - 1 AS adj_ret
        FROM daily_bar b
        INNER JOIN daily_bar p
            ON p.security_id = b.security_id
           AND p.trade_date = (
               SELECT prev_open FROM trade_calendar WHERE cal_date = %(d)s LIMIT 1
           )
        INNER JOIN security_master m ON m.security_id = b.security_id
        WHERE b.trade_date = %(d)s
          AND abs(
              (b.close * b.adj_factor) / nullIf(p.close * p.adj_factor, 0) - 1
          ) > 0.21
        """,
        {"d": d},
    )
    if df is None or df.empty:
        return CheckResult("复权连续性", Severity.HARD, True, "异常 0 只")

    bad = 0
    for _, row in df.iterrows():
        board = _board_from_row(str(row["exchange_code"]), row.get("board"))
        list_date = _as_date(row.get("list_date"))
        if _in_no_limit_window(d, list_date, board):
            continue
        # 上市首日无昨收可比，已由 join 过滤；仍排除 list_date == d
        if list_date == d:
            continue
        bad += 1

    return CheckResult("复权连续性", Severity.HARD, bad == 0, f"异常 {bad} 只（已排除新股窗口）")


@rule("涨跌停价正确性", Severity.HARD)
def check_limit_prices(d: dt.date) -> CheckResult:
    """抽样重算涨跌停价，与入库 up_limit/down_limit 比对（容差 0.01）。"""
    df = db.query_df(
        """
        SELECT
            b.security_id,
            b.pre_close,
            b.up_limit,
            b.down_limit,
            b.is_st,
            m.exchange_code,
            m.board,
            m.list_date
        FROM daily_bar b
        INNER JOIN security_master m ON m.security_id = b.security_id
        WHERE b.trade_date = %(d)s
          AND b.pre_close > 0
        ORDER BY cityHash64(b.security_id, %(seed)s)
        LIMIT 200
        """,
        {"d": d, "seed": d.isoformat()},
    )
    if df is None or df.empty:
        return CheckResult("涨跌停价正确性", Severity.HARD, False, "抽样 0 只")

    checked = 0
    mismatch = 0
    for _, row in df.iterrows():
        board = _board_from_row(str(row["exchange_code"]), row.get("board"))
        list_date = _as_date(row.get("list_date"))
        if _in_no_limit_window(d, list_date, board):
            continue
        pre = float(row["pre_close"])
        if pre <= 0:
            continue
        exp_up, exp_down = limit_prices(pre, board, bool(int(row["is_st"])))
        got_up = float(row["up_limit"])
        got_down = float(row["down_limit"])
        checked += 1
        if abs(got_up - exp_up) > 0.011 or abs(got_down - exp_down) > 0.011:
            mismatch += 1

    if checked == 0:
        return CheckResult(
            "涨跌停价正确性",
            Severity.HARD,
            True,
            f"抽样 {len(df)} 只均在无涨跌幅窗口，跳过比对",
        )
    ok = mismatch == 0
    return CheckResult(
        "涨跌停价正确性",
        Severity.HARD,
        ok,
        f"抽样比对 {checked} 只，不符 {mismatch} 只",
    )


@rule("PIT 合理性", Severity.HARD)
def check_pit_sanity(d: dt.date) -> CheckResult:
    n = db.query_df(
        "SELECT count() AS n FROM fin_statement WHERE ann_date = %(d)s AND ann_date < report_date",
        {"d": d},
    )["n"][0]
    return CheckResult("PIT 合理性", Severity.HARD, n == 0, f"违规 {n} 行")


@rule("跨源抽样比对", Severity.SOFT)
def check_cross_source(d: dt.date) -> CheckResult:
    """随机抽样与第二数据源比对 close/volume。第二源接入后启用。"""
    return CheckResult("跨源抽样比对", Severity.SOFT, True, "第二源未接入，跳过")


@rule("因子覆盖率", Severity.SOFT)
def check_factor_coverage(d: dt.date) -> CheckResult:
    """种子因子相对当日日线覆盖率（无因子日跳过，不阻断发布）。"""
    bar_n = int(
        db.query_df(
            "SELECT count() AS n FROM daily_bar WHERE trade_date = %(d)s",
            {"d": d},
        )["n"][0]
    )
    if bar_n <= 0:
        return CheckResult("因子覆盖率", Severity.SOFT, True, "无日线，跳过")

    try:
        fac = db.query_df(
            """
            SELECT factor_name, count() AS n,
                   countIf(isNotNull(value) AND isFinite(value)) AS nn
            FROM factor_value
            WHERE trade_date = %(d)s AND version = 'v1'
              AND factor_name IN ('mom_20', 'mom_60', 'vol_20', 'turn_20', 'ep', 'bp')
            GROUP BY factor_name
            """,
            {"d": d},
        )
    except Exception as e:
        return CheckResult("因子覆盖率", Severity.SOFT, True, f"因子表不可用: {e}")

    if fac is None or fac.empty:
        return CheckResult(
            "因子覆盖率",
            Severity.SOFT,
            True,
            "当日无 factor_value（可 compute_factors）",
        )

    msgs: list[str] = []
    ok = True
    for _, row in fac.iterrows():
        name = str(row["factor_name"])
        nn = int(row["nn"])
        cov = nn / bar_n if bar_n else 0.0
        msgs.append(f"{name}={cov:.1%}({nn}/{bar_n})")
        # lookback 不足时覆盖率会偏低；仅当已有写入但覆盖极低时告警
        if nn > 0 and cov < 0.50:
            ok = False
    return CheckResult("因子覆盖率", Severity.SOFT, ok, "; ".join(msgs))
