"""DataAPI 纯逻辑单测（不连库）。"""

from qdata.api.data_api import _FILTERS


def test_filters_known():
    assert "st" in _FILTERS
    assert "suspended" in _FILTERS
    assert "limit_up_open" in _FILTERS
