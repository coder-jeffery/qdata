"""启动 Dashboard（兼容入口；等同 ``qdata.jobs.dashboard``）。

用法：
  python -m qdata.jobs.backtest_dashboard
  python -m qdata.jobs.dashboard
"""

from __future__ import annotations

from qdata.jobs.dashboard import main

if __name__ == "__main__":
    main()
