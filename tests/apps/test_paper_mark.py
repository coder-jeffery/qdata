"""A306 日终盯市单测。"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pandas as pd

from qdata.apps.paper_flow import list_marks, mark_session_eod


def _fake_session(tmp_path: Path, monkeypatch, *, cash: float = 40_000.0) -> str:
    from qdata.apps import paper_flow, paper_store

    root = tmp_path / "paper_sessions"
    root.mkdir(parents=True)
    sid = "ps_test_mark_001"
    d = root / sid
    d.mkdir()
    meta = {
        "session_id": sid,
        "asof": "2026-07-01",
        "initial_cash": 100_000.0,
        "account_after": {
            "cash": cash,
            "market_value": 60_000.0,
            "total_asset": cash + 60_000.0,
        },
        "n_filled": 1,
        "n_rejected": 0,
    }
    (d / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    (d / "account.json").write_text(
        json.dumps({"cash": cash, "market_value": 60_000.0, "total_asset": cash + 60_000.0}),
        encoding="utf-8",
    )
    pd.DataFrame(
        {
            "exchange_code": ["A.SH", "B.SH"],
            "quantity": [2000, 1000],
            "cost": [20_000.0, 40_000.0],
        }
    ).to_parquet(d / "positions.parquet", index=False)

    monkeypatch.setattr(paper_flow, "_sessions_root", lambda: root)
    monkeypatch.setattr(paper_store, "_sessions_root", lambda: root)
    return sid


def test_mark_session_eod_computes_pnl(tmp_path, monkeypatch):
    sid = _fake_session(tmp_path, monkeypatch, cash=40_000.0)

    def fake_quotes(codes, trade_date=None):
        return pd.DataFrame(
            {
                "exchange_code": ["A.SH", "B.SH"],
                "price": [12.0, 45.0],  # MV = 24000 + 45000 = 69000
            }
        )

    from qdata.apps import paper_flow

    monkeypatch.setattr(paper_flow, "_quotes_for_codes", fake_quotes)

    mark = mark_session_eod(sid, mark_date=dt.date(2026, 7, 2), persist=True)
    assert mark["cash"] == 40_000.0
    assert mark["market_value"] == 69_000.0
    assert mark["total_asset"] == 109_000.0
    assert mark["pnl_vs_initial"] == 9_000.0
    # rebalance total was 100000
    assert mark["pnl_vs_rebalance"] == 9_000.0
    assert mark["n_positions"] == 2

    out = tmp_path / "paper_sessions" / sid
    assert (out / "mark_latest.json").is_file()
    assert (out / "marks.parquet").is_file()
    hist = list_marks(sid)
    assert len(hist) == 1
    assert float(hist.iloc[0]["total_asset"]) == 109_000.0

    meta = json.loads((out / "meta.json").read_text(encoding="utf-8"))
    assert meta["last_mark_date"] == "2026-07-02"
    assert meta["last_mark_total_asset"] == 109_000.0


def test_mark_overwrite_same_day_and_prev_pnl(tmp_path, monkeypatch):
    sid = _fake_session(tmp_path, monkeypatch)
    from qdata.apps import paper_flow

    prices = {"A.SH": 10.0, "B.SH": 40.0}

    def fake_quotes(codes, trade_date=None):
        return pd.DataFrame(
            {"exchange_code": list(prices), "price": [prices[c] for c in prices]}
        )

    monkeypatch.setattr(paper_flow, "_quotes_for_codes", fake_quotes)

    m1 = mark_session_eod(sid, mark_date=dt.date(2026, 7, 1), persist=True)
    assert m1["pnl_vs_prev_mark"] is None
    # day1: 2000*10 + 1000*40 + 40000 = 100000

    prices["A.SH"] = 11.0
    m2 = mark_session_eod(sid, mark_date=dt.date(2026, 7, 2), persist=True)
    assert m2["pnl_vs_prev_mark"] == 2000.0  # +1 on A

    # same day overwrite
    prices["A.SH"] = 12.0
    m3 = mark_session_eod(sid, mark_date=dt.date(2026, 7, 2), persist=True)
    hist = list_marks(sid)
    assert len(hist) == 2
    assert float(hist[hist["mark_date"] == "2026-07-02"].iloc[0]["market_value"]) == (
        2000 * 12 + 1000 * 40
    )
    assert m3["pnl_vs_prev_mark"] == 4000.0  # vs day1 100000 → 104000


def test_mark_empty_positions(tmp_path, monkeypatch):
    from qdata.apps import paper_flow, paper_store

    root = tmp_path / "paper_sessions"
    sid = "ps_empty"
    d = root / sid
    d.mkdir(parents=True)
    meta = {
        "session_id": sid,
        "asof": "2026-07-01",
        "initial_cash": 100_000.0,
        "account_after": {"cash": 100_000.0, "total_asset": 100_000.0},
    }
    (d / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    (d / "account.json").write_text(
        json.dumps({"cash": 100_000.0, "total_asset": 100_000.0}), encoding="utf-8"
    )
    pd.DataFrame(columns=["exchange_code", "quantity"]).to_parquet(
        d / "positions.parquet", index=False
    )
    monkeypatch.setattr(paper_flow, "_sessions_root", lambda: root)
    monkeypatch.setattr(paper_store, "_sessions_root", lambda: root)

    mark = mark_session_eod(sid, mark_date=dt.date(2026, 7, 1), persist=True)
    assert mark["total_asset"] == 100_000.0
    assert mark["n_positions"] == 0
