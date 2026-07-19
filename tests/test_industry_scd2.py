"""行业属性 SCD2 单测。"""

import datetime as dt

import pandas as pd

from qdata.industry import OPEN_END
from qdata.industry.fetch import format_industry, parse_industry
from qdata.industry.scd2 import attribute_snapshots_to_intervals, industry_on
from qdata.research.portfolio import target_weights


def test_format_parse_industry():
    s = format_industry("801010.SI", "农林牧渔")
    assert s == "801010.SI|农林牧渔"
    assert parse_industry(s) == ("801010.SI", "农林牧渔")
    assert format_industry("801010", "钢铁").startswith("801010.SI|")


def test_attribute_scd2_closes_on_change():
    d1, d2, d3 = dt.date(2024, 1, 1), dt.date(2024, 6, 1), dt.date(2024, 12, 1)
    snaps = pd.DataFrame({
        "exchange_code": ["600000.SH"] * 3,
        "level": ["sw_l1"] * 3,
        "industry": [
            "801010.SI|农林牧渔",
            "801780.SI|银行",
            "801780.SI|银行",
        ],
        "as_of_date": [d1, d2, d3],
    })
    iv = attribute_snapshots_to_intervals(snaps)
    assert industry_on(iv, "600000.SH", "sw_l1", d1) == "801010.SI|农林牧渔"
    assert industry_on(iv, "600000.SH", "sw_l1", d2) == "801780.SI|银行"
    row = iv[iv["industry"].str.startswith("801010")].iloc[0]
    assert row["in_date"] == d1 and row["out_date"] == d2
    row2 = iv[iv["industry"].str.startswith("801780")].iloc[0]
    assert row2["out_date"] == OPEN_END


def test_single_industry_snapshot_open_end():
    d = dt.date(2026, 7, 15)
    snaps = pd.DataFrame({
        "exchange_code": ["000001.SZ", "600000.SH"],
        "level": ["sw_l1", "sw_l1"],
        "industry": ["801780.SI|银行", "801780.SI|银行"],
        "as_of_date": [d, d],
    })
    iv = attribute_snapshots_to_intervals(snaps)
    assert set(iv["out_date"]) == {OPEN_END}
    assert industry_on(iv, "000001.SZ", "sw_l1", d) == "801780.SI|银行"


def test_target_weights_equal_and_top_n():
    d = dt.date(2026, 7, 15)
    panel = pd.DataFrame({
        "trade_date": [d, d, d],
        "exchange_code": ["A", "B", "C"],
        "close": [10.0, 20.0, 30.0],
        "value": [0.1, 0.5, 0.3],
    })
    w = target_weights(panel, method="equal", top_n=2)
    assert len(w) == 2
    assert set(w["exchange_code"]) == {"B", "C"}
    assert abs(w["weight"].sum() - 1.0) < 1e-9

    wr = target_weights(panel, method="factor_rank")
    assert abs(wr["weight"].sum() - 1.0) < 1e-9
    # B 因子最大 → 权重最大
    assert wr.set_index("exchange_code").loc["B", "weight"] == wr["weight"].max()
