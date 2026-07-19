"""集成烟测：需 ClickHouse 与已发布日线/因子。"""

import datetime as dt

import pytest

from qdata.research.backtest import BacktestConfig, BacktestEngine, FromRebalanceSpec
from qdata.research.portfolio import RebalanceSpec


@pytest.mark.integration
def test_run_backtest_mom20_smoke():
    try:
        from qdata import db

        n = int(
            db.query_df(
                """
                SELECT count() AS n FROM factor_value
                WHERE factor_name='mom_20' AND version='v1'
                  AND trade_date BETWEEN '2026-07-01' AND '2026-07-15'
                """
            )["n"][0]
        )
    except Exception as e:
        pytest.skip(f"ClickHouse 不可用: {e}")
    if n <= 0:
        pytest.skip("无 mom_20 因子数据")

    cfg = BacktestConfig(
        start=dt.date(2026, 7, 1),
        end=dt.date(2026, 7, 15),
        dataset_version="2026-07-15",
        initial_cash=10_000_000.0,
        persist=False,
        benchmark=None,
    )
    spec = RebalanceSpec(
        universe="000905.SH",
        factor="mom_20",
        top_n=20,
        weight_method="equal",
    )
    from qdata.api.data_api import DataAPI

    api = DataAPI(version="2026-07-15")
    signals = FromRebalanceSpec(cfg.start, cfg.end, spec=spec, api=api)
    result = BacktestEngine(cfg, api=api).run(signals)
    assert "total_return" in result.metrics
    assert result.equity_curve is not None and not result.equity_curve.empty
    assert result.meta.get("engine_version")
    assert result.meta.get("dataset_version")
    assert result.meta.get("price_model") == "post_adjust_nav_raw_limits"
