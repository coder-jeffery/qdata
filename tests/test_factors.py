"""种子因子计算单测（不依赖 ClickHouse 全市场）。"""

import datetime as dt

import pandas as pd

from qdata.factors import _bp, _ep, _mom, _turn, _vol, list_seed_factors


def test_list_seed_factors():
    names = list_seed_factors()
    assert "mom_20" in names
    assert "vol_20" in names
    assert "turn_20" in names
    assert "ep" in names
    assert "bp" in names


def test_mom_20_formula():
    d0 = dt.date(2026, 1, 1)
    dates = [d0 + dt.timedelta(days=i) for i in range(25)]
    # 后复权价从 100 线性涨到约 124；mom_20 ≈ 124/104 - 1
    closes = [100.0 + i for i in range(25)]
    panel = pd.DataFrame({
        "trade_date": dates,
        "security_id": [1] * 25,
        "close": closes,
        "adj_factor": [1.0] * 25,
    })
    out = _mom(panel, dates[-1], 20)
    assert len(out) == 1
    expected = closes[-1] / closes[-21] - 1.0
    assert abs(out.iloc[0]["value"] - expected) < 1e-9


def test_vol_20_finite():
    d0 = dt.date(2026, 1, 1)
    dates = [d0 + dt.timedelta(days=i) for i in range(30)]
    # 交替涨跌
    closes = [100.0 * (1.01 if i % 2 == 0 else 0.99) ** (i // 2) for i in range(30)]
    panel = pd.DataFrame({
        "trade_date": dates,
        "security_id": [7] * 30,
        "close": closes,
        "adj_factor": [1.0] * 30,
    })
    out = _vol(panel, dates[-1], 20)
    assert len(out) == 1
    assert out.iloc[0]["value"] > 0


def test_turn_20_allows_sparse_nan():
    d0 = dt.date(2026, 6, 1)
    dates = [d0 + dt.timedelta(days=i) for i in range(25)]
    rates = [1.0] * 25
    rates[5] = float("nan")  # 窗口内单点缺失不应整行丢弃
    df = pd.DataFrame({
        "trade_date": dates,
        "security_id": [3] * 25,
        "turnover_rate": rates,
    })
    out = _turn(df, dates[-1], 20)
    assert len(out) == 1
    assert abs(out.iloc[0]["value"] - 1.0) < 1e-9


def test_ep_bp_units_wan_to_yuan():
    """total_mv 万元 ×10000 = 元；ep/bp = 财务/市值。"""
    d = dt.date(2026, 7, 15)
    mv = pd.DataFrame({
        "trade_date": [d, d],
        "security_id": [1, 2],
        "total_mv": [10_000.0, 20_000.0],  # 万元 → 1e8 / 2e8 元
    })
    profit = pd.DataFrame({"security_id": [1, 2], "value": [1e7, 5e7]})
    equity = pd.DataFrame({"security_id": [1, 2], "value": [5e7, 1e8]})
    ep = _ep(mv, profit, d).set_index("security_id")["value"]
    bp = _bp(mv, equity, d).set_index("security_id")["value"]
    assert abs(ep.loc[1] - 0.1) < 1e-12
    assert abs(ep.loc[2] - 0.25) < 1e-12
    assert abs(bp.loc[1] - 0.5) < 1e-12
    assert abs(bp.loc[2] - 0.5) < 1e-12
