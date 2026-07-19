"""日历与回填相关单测（不依赖 ClickHouse 有数据）。"""

import datetime as dt

from qdata.calendar import clear_cache, is_trading_day, trading_days_between


def test_weekday_fallback_when_calendar_empty(monkeypatch):
    clear_cache()
    monkeypatch.setattr("qdata.calendar._open_days", lambda: ())
    days = trading_days_between(dt.date(2026, 7, 13), dt.date(2026, 7, 17))
    # 13 Mon ... 17 Fri
    assert days == [
        dt.date(2026, 7, 13),
        dt.date(2026, 7, 14),
        dt.date(2026, 7, 15),
        dt.date(2026, 7, 16),
        dt.date(2026, 7, 17),
    ]
    assert is_trading_day(dt.date(2026, 7, 15))
    assert not is_trading_day(dt.date(2026, 7, 18))  # Sat
