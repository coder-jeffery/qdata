"""A1 实验工厂冒烟 / 单元测试。"""

from __future__ import annotations

import datetime as dt

import pytest

from qdata.apps.experiment import APP_PIPELINE_VERSION, ExperimentSpec, expand_cells, run_experiment_matrix


def test_expand_cells_cartesian():
    spec = ExperimentSpec(
        start=dt.date(2026, 7, 1),
        end=dt.date(2026, 7, 5),
        factors=["mom_20", "ep"],
        weight_methods=["equal", "industry_neutral"],
        top_n=10,
    )
    cells = expand_cells(spec)
    assert len(cells) == 4
    pairs = {(c["factor"], c["weight_method"]) for c in cells}
    assert pairs == {
        ("mom_20", "equal"),
        ("mom_20", "industry_neutral"),
        ("ep", "equal"),
        ("ep", "industry_neutral"),
    }
    for c in cells:
        assert c["top_n"] == 10
        assert c["universe"] == spec.universe


def test_app_pipeline_version():
    assert APP_PIPELINE_VERSION == "app-0.1"


@pytest.mark.integration
def test_run_experiment_matrix_one_cell_no_persist():
    """有 CH 数据时跑 1 格；否则 skip。"""
    try:
        from qdata import db

        df = db.query_df(
            "SELECT max(trade_date) AS d FROM factor_value WHERE factor_name='mom_20'"
        )
        if df is None or df.empty or df.iloc[0]["d"] is None:
            pytest.skip("无 factor_value 数据")
        end = df.iloc[0]["d"]
        if hasattr(end, "date"):
            end = end.date()
        start = end - dt.timedelta(days=5)
    except Exception:
        pytest.skip("ClickHouse 不可用")

    spec = ExperimentSpec(
        start=start,
        end=end,
        factors=["mom_20"],
        weight_methods=["equal"],
        top_n=5,
        persist=False,
        persist_ch=False,
    )
    result = run_experiment_matrix(spec)
    assert result["experiment_id"]
    assert len(result["rows"]) == 1
    assert "status" in result["rows"][0]
