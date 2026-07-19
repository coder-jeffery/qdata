"""全局配置。环境变量前缀 QDATA_，支持 .env 文件。"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# src/qdata/config.py → 项目根目录
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_LAKE = _PROJECT_ROOT / "data" / "data-lake"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="QDATA_",
        env_file=(_PROJECT_ROOT / ".env", ".env"),
        extra="ignore",
    )

    # 数据源：单一名 / auto / 逗号链（联调可用 auto；生产请用 prod_source）
    data_source: str = "auto"
    data_source_chain: str = "akshare,baostock,tushare,efinance,mootdx"

    # M1.5 生产主源：baostock | tushare（禁止 auto）；生产作业强制全市场
    prod_source: str = "baostock"
    prod_min_universe: int = 500  # smoke 全市场股票数下限

    akshare_rate_limit: int = 120
    baostock_rate_limit: int = 300
    tushare_rate_limit: int = 200
    efinance_rate_limit: int = 120
    mootdx_rate_limit: int = 600
    easyquotation_rate_limit: int = 120
    zvt_rate_limit: int = 300
    akshare_max_symbols: int = 0  # >0 时仅拉前 N 只（各源共用），0=全市场

    # Tushare Pro（https://tushare.pro ）
    # 总开关：false 时不参与 auto/故障转移链，且禁止 --source tushare
    tushare_enabled: bool = False
    tushare_token: str = ""

    # JoinQuant 聚宽（https://www.joinquant.com ）
    # 总开关：false 时不参与 auto 链；显式 --source joinquant 时需开启并配置账号
    joinquant_enabled: bool = False
    joinquant_user: str = ""
    joinquant_password: str = ""
    joinquant_rate_limit: int = 60

    # MootDX / 通达信
    mootdx_server: str = ""  # host:port，空则让 mootdx 自选
    tdx_dir: Path | None = None  # 本地通达信目录（离线 .day）

    # EasyQuotation
    easyquotation_backend: str = "sina"  # sina | tencent | qq | ...

    # 交易通道
    broker: str = "paper"  # paper | miniqmt | easytrader
    paper_initial_cash: float = 1_000_000.0
    miniqmt_path: str = ""
    miniqmt_account: str = ""
    easytrader_broker: str = "universal_client"
    easytrader_user: str = ""
    easytrader_password: str = ""
    easytrader_exe: str = ""

    # Raw 区数据湖根目录
    lake_root: Path = _DEFAULT_LAKE

    # ClickHouse
    ch_host: str = "localhost"
    ch_port: int = 8123
    ch_database: str = "qdata"
    ch_user: str = "default"
    ch_password: str = ""

    # 告警 webhook（钉钉/企微）
    alert_webhook: str = ""


@lru_cache
def settings() -> Settings:
    return Settings()
