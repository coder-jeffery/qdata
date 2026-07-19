"""指数成分 SCD2 区间重建单测。"""

import datetime as dt

import pandas as pd

from qdata.index import OPEN_END
from qdata.index.scd2 import members_on, snapshots_to_intervals


def test_scd2_closes_exits_and_opens_entries():
    d1, d2, d3 = dt.date(2024, 1, 1), dt.date(2024, 6, 1), dt.date(2024, 12, 1)
    snaps = pd.DataFrame({
        "index_code": ["000300.SH"] * 5,
        "exchange_code": [
            "600000.SH", "000001.SZ",
            "000001.SZ", "000002.SZ",
            "000002.SZ",
        ],
        "as_of_date": [d1, d1, d2, d2, d3],
    })
    iv = snapshots_to_intervals(snaps)
    assert members_on(iv, "000300.SH", d1) == ["000001.SZ", "600000.SH"]
    assert members_on(iv, "000300.SH", d2) == ["000001.SZ", "000002.SZ"]
    assert members_on(iv, "000300.SH", d3) == ["000002.SZ"]
    row = iv[(iv["exchange_code"] == "600000.SH")].iloc[0]
    assert row["in_date"] == d1 and row["out_date"] == d2
    row2 = iv[(iv["exchange_code"] == "000002.SZ")].iloc[0]
    assert row2["out_date"] == OPEN_END


def test_scd2_uses_include_date_hint():
    d1 = dt.date(2024, 6, 1)
    snaps = pd.DataFrame({
        "index_code": ["000905.SH"],
        "exchange_code": ["600519.SH"],
        "as_of_date": [d1],
        "in_date": [dt.date(2020, 1, 15)],
    })
    iv = snapshots_to_intervals(snaps)
    assert iv.iloc[0]["in_date"] == dt.date(2020, 1, 15)
    assert iv.iloc[0]["out_date"] == OPEN_END
    assert members_on(iv, "000905.SH", dt.date(2019, 12, 31)) == []
    assert members_on(iv, "000905.SH", dt.date(2020, 1, 15)) == ["600519.SH"]


def test_single_snapshot_all_open_end():
    d = dt.date(2026, 7, 15)
    snaps = pd.DataFrame({
        "index_code": ["000852.SH", "000852.SH"],
        "exchange_code": ["000001.SZ", "000002.SZ"],
        "as_of_date": [d, d],
    })
    iv = snapshots_to_intervals(snaps)
    assert set(iv["out_date"]) == {OPEN_END}
    assert len(members_on(iv, "000852.SH", d)) == 2
