"""研究 / 运维 Dashboard（可选依赖 streamlit）。"""

from __future__ import annotations

from qdata.dashboard.data import list_runs, load_run_detail, runs_metrics_matrix
from qdata.dashboard.factor_data import (
    factor_coverage_day,
    factor_matrix_latest,
    list_factor_watermarks,
)
from qdata.dashboard.finance_data import finance_summary
from qdata.dashboard.health_data import health_summary, list_table_watermarks
from qdata.dashboard.universe_data import index_universe_sizes, industry_distribution

__all__ = [
    "list_runs",
    "load_run_detail",
    "runs_metrics_matrix",
    "list_table_watermarks",
    "health_summary",
    "list_factor_watermarks",
    "factor_coverage_day",
    "factor_matrix_latest",
    "index_universe_sizes",
    "industry_distribution",
    "finance_summary",
]
