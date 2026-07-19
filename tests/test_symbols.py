"""代码格式转换单测。"""

from qdata.symbols import (
    from_baostock_code,
    is_baostock_a_share,
    to_baostock_code,
    to_exchange_code,
    to_pure_code,
    to_sina_symbol,
)


def test_to_exchange_code():
    assert to_exchange_code("600000") == "600000.SH"
    assert to_exchange_code("000001") == "000001.SZ"
    assert to_exchange_code("300750") == "300750.SZ"
    assert to_exchange_code("688981") == "688981.SH"
    assert to_exchange_code("830799") == "830799.BJ"


def test_to_pure_and_sina():
    assert to_pure_code("600000.SH") == "600000"
    assert to_sina_symbol("600000.SH") == "sh600000"
    assert to_sina_symbol("000001.SZ") == "sz000001"


def test_baostock_codes():
    assert to_baostock_code("600000.SH") == "sh.600000"
    assert to_baostock_code("000001.SZ") == "sz.000001"
    assert from_baostock_code("sh.600000") == "600000.SH"
    assert is_baostock_a_share("sz.000001")
    assert is_baostock_a_share("sh.688981")
    assert not is_baostock_a_share("sh.000001")  # 指数
