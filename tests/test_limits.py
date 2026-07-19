"""涨跌停价与整手规则单元测试。

这些用例是 M1 验收「回测引擎单元测试覆盖全部 A 股规则」的数据层部分，
交易所口径以上交所/深交所交易规则为准。
"""

import pytest

from qdata.constants import Board, board_of, limit_prices, round_lot


class TestBoardOf:
    @pytest.mark.parametrize("code,board", [
        ("600000.SH", Board.MAIN),   # 沪主板
        ("000001.SZ", Board.MAIN),   # 深主板
        ("002415.SZ", Board.MAIN),   # 原中小板 → 主板
        ("300750.SZ", Board.GEM),    # 创业板
        ("688111.SH", Board.STAR),   # 科创板
        ("830799.BJ", Board.BSE),    # 北交所
    ])
    def test_board(self, code, board):
        assert board_of(code) is board


class TestLimitPrices:
    def test_main_board_10pct(self):
        up, down = limit_prices(10.00, Board.MAIN, is_st=False)
        assert (up, down) == (11.00, 9.00)

    def test_rounding_to_cent(self):
        # 10.03 * 1.1 = 11.033 → 11.03（四舍五入到分）
        up, _ = limit_prices(10.03, Board.MAIN, is_st=False)
        assert up == 11.03

    def test_st_main_board_5pct(self):
        up, down = limit_prices(10.00, Board.MAIN, is_st=True)
        assert (up, down) == (10.50, 9.50)

    def test_gem_20pct_even_if_st(self):
        # 创业板 ST 仍为 20%
        up, _ = limit_prices(10.00, Board.GEM, is_st=True)
        assert up == 12.00

    def test_star_20pct(self):
        up, down = limit_prices(50.00, Board.STAR, is_st=False)
        assert (up, down) == (60.00, 40.00)

    def test_bse_30pct(self):
        up, _ = limit_prices(10.00, Board.BSE, is_st=False)
        assert up == 13.00


class TestRoundLot:
    def test_main_board_100_step(self):
        assert round_lot(250, Board.MAIN) == 200

    def test_below_min_is_zero(self):
        assert round_lot(99, Board.MAIN) == 0

    def test_star_200_min_then_1_step(self):
        # 科创板 200 股起、1 股递增
        assert round_lot(199, Board.STAR) == 0
        assert round_lot(357, Board.STAR) == 357
