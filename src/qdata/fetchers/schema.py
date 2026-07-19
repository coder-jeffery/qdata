"""各数据源输出的标准空表 schema（保证 Loader 列存在）。"""

from __future__ import annotations

EMPTY_SCHEMAS: dict[str, list[str]] = {
    "daily_bar": [
        "exchange_code", "trade_date", "open", "high", "low", "close",
        "pre_close", "volume", "amount",
    ],
    "adj_factor": ["exchange_code", "trade_date", "adj_factor"],
    "daily_basic": [
        "exchange_code", "trade_date", "turnover_rate",
        "total_share", "float_share", "total_mv", "circ_mv", "pe_ttm", "pb",
    ],
    "suspend": ["exchange_code", "suspend_date"],
    "stock_basic": ["exchange_code", "symbol", "name", "list_date", "delist_date"],
    "income": [
        "exchange_code", "ann_date", "report_date", "update_flag",
        "revenue", "n_income_attr_p", "basic_eps", "operate_profit",
    ],
    "balancesheet": [
        "exchange_code", "ann_date", "report_date", "update_flag",
        "total_assets", "total_liab", "total_hldr_eqy_exc_min_int",
    ],
    "cashflow": [
        "exchange_code", "ann_date", "report_date", "update_flag",
        "n_cashflow_act", "n_cashflow_inv_act", "n_cash_flows_fnc_act",
    ],
    "realtime_quote": [
        "exchange_code", "name", "price", "open", "high", "low", "pre_close",
        "volume", "amount", "bid", "ask", "time",
    ],
    "index_member": [
        "index_code", "exchange_code", "in_date", "as_of_date", "confidence",
    ],
    "industry_member": [
        "exchange_code", "level", "industry", "as_of_date", "confidence",
    ],
}

# 历史 ETL 核心数据集（Loader 依赖）
HISTORICAL_DATASETS = frozenset({
    "stock_basic", "daily_bar", "adj_factor", "daily_basic", "suspend", "income",
    "balancesheet", "cashflow",
    "index_member", "industry_member",
})
