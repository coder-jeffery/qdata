"""Airflow 每日 ETL DAG。

与 cron 对齐：直接调用 ``qdata.jobs.daily_run.run_daily``，避免双路径漂移。

本地无 Airflow 时：
  python -m qdata.jobs.daily_run --post-m2 --with-basic --with-extras \\
      --sync-industry --industry-levels sw_l1,sw_l2
  bash scripts/install_daily_cron.sh
"""

from __future__ import annotations

import datetime as dt

import pendulum
from airflow.decorators import dag, task


@dag(
    dag_id="daily_etl",
    schedule="30 17 * * 1-5",  # 交易日 17:30（数据源盘后更新完毕）
    start_date=pendulum.datetime(2026, 1, 1, tz="Asia/Shanghai"),
    catchup=False,
    default_args={"retries": 3, "retry_delay": dt.timedelta(minutes=5)},
    tags=["qdata"],
)
def daily_etl():

    @task
    def run_daily_batch() -> str:
        """等价 cron：生产日线 + extras + 指数/行业/因子 + A405 软挂监控。"""
        from qdata.jobs.daily_run import run_daily

        rc = run_daily(
            post_m2=True,  # 含因子监控软挂；告警不阻断发布
            with_basic=True,
            with_extras=True,
            sync_industry=True,
            industry_levels=("sw_l1", "sw_l2"),
        )
        if rc != 0:
            raise RuntimeError(f"daily_run failed rc={rc}")
        return "ok"

    run_daily_batch()


daily_etl()
