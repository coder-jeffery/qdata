"""PIT（Point-in-Time）防前视：纯函数单测（不依赖 ClickHouse）。

规则与 DataAPI.get_fundamental / FinStatementLoader 约定一致：
  ann_date <= T；同票取 report_date 最大，再取 ann_date 最大（更正后可见）。
"""

from __future__ import annotations

import datetime as dt

import pandas as pd

from qdata.loaders.fin_statement import pick_pit_row


def _rows() -> pd.DataFrame:
    """构造场景：
    - 2024 年报 report_date=2024-12-31，首次 ann=2025-04-20，value=100
    - 更正 ann=2025-06-10，value=90
    - 2025 一季报 report_date=2025-03-31，ann=2025-04-28，value=30
    """
    return pd.DataFrame({
        "ann_date": [
            dt.date(2025, 4, 20),
            dt.date(2025, 6, 10),
            dt.date(2025, 4, 28),
        ],
        "report_date": [
            dt.date(2024, 12, 31),
            dt.date(2024, 12, 31),
            dt.date(2025, 3, 31),
        ],
        "value": [100.0, 90.0, 30.0],
        "update_flag": [0, 1, 0],
    })


def test_before_announcement_invisible():
    row = pick_pit_row(_rows(), dt.date(2025, 4, 19))
    assert row is None


def test_first_disclosure_visible():
    row = pick_pit_row(_rows(), dt.date(2025, 4, 21))
    assert row is not None
    assert float(row["value"]) == 100.0
    assert row["report_date"] == dt.date(2024, 12, 31)


def test_correction_takes_effect_after_its_ann_date():
    row = pick_pit_row(_rows(), dt.date(2025, 6, 11))
    assert row is not None
    # 一季报 report_date 更大 → 仍优先一季报 30；测更正需卡在一季报前
    row2 = pick_pit_row(
        _rows()[_rows()["report_date"] == dt.date(2024, 12, 31)],
        dt.date(2025, 6, 11),
    )
    assert row2 is not None
    assert float(row2["value"]) == 90.0


def test_latest_report_date_wins():
    row = pick_pit_row(_rows(), dt.date(2025, 5, 1))
    assert row is not None
    assert float(row["value"]) == 30.0
    assert row["report_date"] == dt.date(2025, 3, 31)
