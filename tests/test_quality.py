"""质检 HARD 规则单测（不依赖 ClickHouse）。"""

import datetime as dt

from qdata.constants import Board
from qdata.quality import checks


def test_in_no_limit_window_gem():
    list_date = dt.date(2026, 7, 1)
    assert checks._in_no_limit_window(dt.date(2026, 7, 1), list_date, Board.GEM)
    assert checks._in_no_limit_window(dt.date(2026, 7, 5), list_date, Board.GEM)
    assert not checks._in_no_limit_window(dt.date(2026, 7, 6), list_date, Board.GEM)


def test_limit_prices_recalc_matches_constants():
    from qdata.constants import limit_prices

    up, down = limit_prices(10.0, Board.MAIN, False)
    assert up == 11.0
    assert down == 9.0
    up_st, down_st = limit_prices(10.0, Board.MAIN, True)
    assert up_st == 10.5
    assert down_st == 9.5


def test_board_from_row_fallback():
    assert checks._board_from_row("300750.SZ", None) == Board.GEM
    assert checks._board_from_row("600000.SH", "main") == Board.MAIN
