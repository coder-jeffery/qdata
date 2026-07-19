"""指数成分 Loader 映射单测。"""

import datetime as dt

import pandas as pd

from qdata.index import OPEN_END
from qdata.loaders import index_member as im


def test_snapshot_to_intervals_maps_and_open_end(monkeypatch):
    snap = pd.DataFrame({
        "index_code": ["000300.SH", "000300.SH"],
        "exchange_code": ["600000.SH", "000001.SZ"],
        "in_date": [dt.date(2020, 1, 1), dt.date(2021, 6, 15)],
        "as_of_date": [dt.date(2026, 7, 15)] * 2,
        "confidence": ["sina_include_date"] * 2,
    })

    monkeypatch.setattr(
        im.db,
        "query_df",
        lambda sql, params=None: pd.DataFrame({
            "exchange_code": ["600000.SH", "000001.SZ"],
            "security_id": [1, 2],
        }),
    )
    out = im.snapshot_to_intervals(snap)
    assert len(out) == 2
    assert set(out["out_date"]) == {OPEN_END}
    assert set(out["security_id"].astype(int)) == {1, 2}


def test_seed_index_codes():
    from qdata.index import SEED_INDEX_CODES, TUSHARE_INDEX_CODE

    assert "000300.SH" in SEED_INDEX_CODES
    assert TUSHARE_INDEX_CODE["000300.SH"] == "399300.SZ"
