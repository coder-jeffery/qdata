"""A308：实验 → 信号 → Paper 挂钩单测。"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pandas as pd
import pytest

from qdata.apps.experiment import load_experiment, pick_best_cell
from qdata.apps.paper_flow import run_paper_from_experiment


def _fake_experiment(tmp_path: Path, monkeypatch) -> str:
    from qdata.apps import experiment as exp_mod

    root = tmp_path / "experiments"
    eid = "exp_test_a308"
    d = root / eid
    d.mkdir(parents=True)
    meta = {
        "experiment_id": eid,
        "dataset_version": "2026-07-15",
        "spec": {
            "start": "2026-07-01",
            "end": "2026-07-15",
            "universe": "000905.SH",
            "version": "2026-07-15",
        },
    }
    (d / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    pd.DataFrame(
        [
            {
                "factor": "mom_20",
                "weight_method": "equal",
                "universe": "000905.SH",
                "top_n": 50,
                "factor_version": "v1",
                "industry_level": "sw_l1",
                "execution": "next_open",
                "benchmark": "000905.SH",
                "status": "ok",
                "run_id": "r1",
                "sharpe": 0.5,
                "ann_return": 0.1,
            },
            {
                "factor": "ep",
                "weight_method": "industry_neutral",
                "universe": "000905.SH",
                "top_n": 30,
                "factor_version": "v1",
                "industry_level": "sw_l1",
                "execution": "next_open",
                "benchmark": "000905.SH",
                "status": "ok",
                "run_id": "r2",
                "sharpe": 1.2,
                "ann_return": 0.2,
            },
            {
                "factor": "vol_20",
                "weight_method": "equal",
                "universe": "000905.SH",
                "top_n": 50,
                "factor_version": "v1",
                "industry_level": "sw_l1",
                "execution": "next_open",
                "benchmark": "000905.SH",
                "status": "fail",
                "run_id": None,
                "sharpe": 9.0,
                "ann_return": 9.0,
            },
        ]
    ).to_parquet(d / "summary.parquet", index=False)

    monkeypatch.setattr(exp_mod, "_experiments_root", lambda: root)
    return eid


def test_pick_best_cell_by_sharpe(tmp_path, monkeypatch):
    eid = _fake_experiment(tmp_path, monkeypatch)
    summary = load_experiment(eid)["summary"]
    cell = pick_best_cell(summary, rank_by="sharpe")
    assert cell["factor"] == "ep"
    assert cell["weight_method"] == "industry_neutral"
    assert cell["top_n"] == 30
    assert cell["rank_value"] == pytest.approx(1.2)


def test_pick_best_cell_skips_fail(tmp_path, monkeypatch):
    eid = _fake_experiment(tmp_path, monkeypatch)
    cell = pick_best_cell(load_experiment(eid)["summary"], rank_by="sharpe")
    assert cell["factor"] != "vol_20"  # fail 即使 sharpe 更高也跳过


def test_run_paper_from_experiment_wires_meta(tmp_path, monkeypatch):
    eid = _fake_experiment(tmp_path, monkeypatch)
    captured: dict = {}

    def fake_rebalance(**kwargs):
        captured.update(kwargs)
        return {
            "session_id": "ps_test",
            "meta": {**(kwargs.get("extra_meta") or {}), "n_filled": 1, "n_rejected": 0},
            "account": {"cash": 1.0},
            "path": None,
            "orders": [],
            "rejects": [],
            "positions": pd.DataFrame(),
        }

    from qdata.apps import paper_flow

    monkeypatch.setattr(paper_flow, "run_paper_rebalance", fake_rebalance)

    result = run_paper_from_experiment(
        eid,
        asof=dt.date(2026, 7, 15),
        rank_by="sharpe",
        cash=1_000_000,
        persist=False,
    )
    assert result["experiment_id"] == eid
    assert result["selected_cell"]["factor"] == "ep"
    assert captured["factor"] == "ep"
    assert captured["weight_method"] == "industry_neutral"
    assert captured["top_n"] == 30
    assert captured["date"] == dt.date(2026, 7, 15)
    assert captured["cash"] == 1_000_000
    fe = captured["extra_meta"]["from_experiment"]
    assert fe["enabled"] is True
    assert fe["experiment_id"] == eid
    assert fe["selected_cell"]["factor"] == "ep"


def test_run_paper_from_experiment_default_asof_from_spec(tmp_path, monkeypatch):
    eid = _fake_experiment(tmp_path, monkeypatch)
    captured: dict = {}

    def fake_rebalance(**kwargs):
        captured["date"] = kwargs.get("date")
        return {
            "session_id": "ps_x",
            "meta": kwargs.get("extra_meta") or {},
            "account": {},
            "path": None,
            "orders": [],
            "rejects": [],
            "positions": pd.DataFrame(),
        }

    from qdata.apps import paper_flow

    monkeypatch.setattr(paper_flow, "run_paper_rebalance", fake_rebalance)
    run_paper_from_experiment(eid, persist=False)
    assert captured["date"] == dt.date(2026, 7, 15)
