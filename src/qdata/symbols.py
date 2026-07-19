"""A 股代码格式转换（内部统一用 exchange_code，如 600000.SH）。"""

from __future__ import annotations


def to_exchange_code(code: str) -> str:
    """6 位代码 → 600000.SH / 000001.SZ / 830799.BJ。"""
    c = str(code).strip().zfill(6)
    if c.startswith(("4", "8")):
        return f"{c}.BJ"
    if c.startswith(("5", "6", "9")):
        return f"{c}.SH"
    return f"{c}.SZ"


def to_pure_code(exchange_code: str) -> str:
    """600000.SH → 600000。"""
    return exchange_code.split(".", 1)[0].zfill(6)


def to_sina_symbol(exchange_code: str) -> str:
    """600000.SH → sh600000（AKShare stock_zh_a_daily 用）。"""
    code, market = exchange_code.split(".", 1)
    return f"{market.lower()}{code.zfill(6)}"


def to_baostock_code(exchange_code: str) -> str:
    """600000.SH → sh.600000。"""
    code, market = exchange_code.split(".", 1)
    return f"{market.lower()}.{code.zfill(6)}"


def from_baostock_code(bs_code: str) -> str:
    """sh.600000 → 600000.SH。"""
    market, code = bs_code.split(".", 1)
    return f"{code.zfill(6)}.{market.upper()}"


def to_joinquant_code(exchange_code: str) -> str:
    """600000.SH → 600000.XSHG；000001.SZ → 000001.XSHE；830799.BJ → 830799.XBSE。"""
    code, market = exchange_code.split(".", 1)
    code = code.zfill(6)
    m = market.upper()
    if m == "SH":
        return f"{code}.XSHG"
    if m == "SZ":
        return f"{code}.XSHE"
    if m == "BJ":
        return f"{code}.XBSE"
    raise ValueError(f"无法转为 JoinQuant 代码: {exchange_code}")


def from_joinquant_code(jq_code: str) -> str:
    """600000.XSHG → 600000.SH。"""
    code, market = str(jq_code).strip().split(".", 1)
    code = code.zfill(6)
    m = market.upper()
    if m in ("XSHG", "SH"):
        return f"{code}.SH"
    if m in ("XSHE", "SZ"):
        return f"{code}.SZ"
    if m in ("XBSE", "XBEI", "BJ"):
        return f"{code}.BJ"
    raise ValueError(f"无法解析 JoinQuant 代码: {jq_code}")


def is_joinquant_a_share(jq_code: str) -> bool:
    """过滤指数等，仅保留沪深京 A 股。"""
    try:
        ec = from_joinquant_code(jq_code)
    except ValueError:
        return False
    num, market = ec.split(".", 1)
    if market == "SH":
        return num.startswith(("60", "68"))
    if market == "SZ":
        return num.startswith(("00", "30"))
    if market == "BJ":
        return num.startswith(("4", "8"))
    return False


def is_baostock_a_share(bs_code: str) -> bool:
    """过滤指数，仅保留沪深京 A 股。"""
    try:
        market, num = bs_code.split(".", 1)
    except ValueError:
        return False
    num = num.zfill(6)
    if market == "sh":
        return num.startswith(("60", "68"))
    if market == "sz":
        return num.startswith(("00", "30"))
    if market == "bj":
        return num.startswith(("4", "8"))
    return False
