"""A207 信号研判联动 + A504 session 对比。"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pandas as pd

from qdata.apps.paper_store import compare_sessions
from qdata.research.judgment import JudgmentCard, judge_signal_topn, judgments_to_frame


def test_judgments_to_frame():
    cards = [
        JudgmentCard(
            code="A.SH",
            asof="2026-07-15",
            benchmark="000905.SH",
            window=20,
            composite=60.0,
            stance="偏强",
            industry={"sw_l1": "银行"},
            tradability={"status": "ok"},
            tags=["mom"],
        )
    ]
    df = judgments_to_frame(cards)
    assert len(df) == 1
    assert df.iloc[0]["exchange_code"] == "A.SH"
    assert df.iloc[0]["stance"] == "偏强"


def test_judge_signal_topn_mocked(monkeypatch, tmp_path):
    sig = tmp_path / "sig"
    sig.mkdir()
    (sig / "meta.json").write_text(
        json.dumps({"asof": "2026-07-15", "factor": "mom_20"}), encoding="utf-8"
    )
    pd.DataFrame(
        {
            "exchange_code": ["A.SH", "B.SH", "C.SH"],
            "weight": [0.5, 0.3, 0.2],
        }
    ).to_parquet(sig / "weights.parquet", index=False)

    def fake_stocks(codes, asof=None, **kwargs):
        return [
            JudgmentCard(
                code=c,
                asof="2026-07-15",
                benchmark="000905.SH",
                window=20,
                composite=50.0,
                stance="中性",
            )
            for c in codes
        ]

    monkeypatch.setattr("qdata.research.judgment.judge_stocks", fake_stocks)
    result = judge_signal_topn(sig, top_n=2)
    assert result["n"] == 2
    assert result["codes"] == ["A.SH", "B.SH"]
    assert len(result["summary"]) == 2


def test_compare_sessions(tmp_path, monkeypatch):
    from qdata.apps import paper_store

    root = tmp_path / "paper_sessions"
    for i, sid in enumerate(["ps_a", "ps_b"]):
        d = root / sid
        d.mkdir(parents=True)
        meta = {
            "session_id": sid,
            "asof": "2026-07-15",
            "n_filled": i + 1,
            "n_rejected": 0,
            "from_experiment": {
                "enabled": True,
                "experiment_id": "exp_x",
                "selected_cell": {"factor": "ep", "weight_method": "equal"},
            }
            if i == 0
            else {},
        }
        (d / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
        (d / "account.json").write_text(
            json.dumps({"cash": 1000.0 * (i + 1), "market_value": 5000.0, "total_asset": 6000.0 + i}),
            encoding="utf-8",
        )
        pd.DataFrame({"exchange_code": ["A.SH"], "quantity": [100]}).to_parquet(
            d / "positions.parquet", index=False
        )

    monkeypatch.setattr(paper_store, "_sessions_root", lambda: root)
    cmp = compare_sessions(["ps_a", "ps_b"])
    assert len(cmp) == 2
    assert cmp.iloc[0]["experiment_id"] == "exp_x"
    assert cmp.iloc[1]["n_filled"] == 2
    assert cmp.iloc[0]["n_positions"] == 1
