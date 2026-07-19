# qdata — A 股量化平台数据管道与历史库

- 采集操作手册：[docs/数据采集操作说明.md](docs/数据采集操作说明.md)
- **开发计划手册（✅/❌）**：[docs/开发计划手册.md](docs/开发计划手册.md)
- **量化平台开发手册（模块功能）**：[docs/量化平台开发手册.md](docs/量化平台开发手册.md)
- **运营后台 UI**：[docs/运营后台-UI与前端架构设计.md](docs/运营后台-UI与前端架构设计.md) · [`ui/ops-console/index.html`](ui/ops-console/index.html)
- **量化交易终端 UI（机构级高保真）**：[docs/量化交易终端-UI设计规范.md](docs/量化交易终端-UI设计规范.md) · [`ui/trading-terminal/index.html`](ui/trading-terminal/index.html)
- **Web 前端（React）**：[`apps/web`](apps/web) · BFF：`python -m qdata.jobs.web_api` → `cd apps/web && npm run dev`
- **开发功能进度**：[docs/开发功能进度.md](docs/开发功能进度.md)
- **执行计划（命令+备注）**：[docs/下一阶段执行计划-命令手册.md](docs/下一阶段执行计划-命令手册.md)
- 应用链路专项：[docs/应用链路-开发计划.md](docs/应用链路-开发计划.md)
- M1.5 生产回填验收：[docs/M1.5-生产回填验收.md](docs/M1.5-生产回填验收.md)
- 下一阶段规划：[docs/下一阶段功能规划.md](docs/下一阶段功能规划.md)

指数成分：`python -m qdata.jobs.sync_index_member`  
行业分类：`python -m qdata.jobs.sync_industry_member --levels sw_l1`  
种子因子：`python -m qdata.jobs.compute_factors --date <日>`  
回测读数：`from qdata.research.portfolio import build_weight_series`  
纸交易：`python -m qdata.jobs.paper_demo --code 600000.SH --qty 100`  
实时快照：`python -m qdata.jobs.realtime_snapshot --source easyquotation`

M1 阶段「工作流一」的代码骨架，对应五段式数据流：

```
① 采集层 Fetcher（多源可插拔 / auto 故障转移）→ ② Raw 区 Parquet → ③ Loader → ④ ClickHouse → ⑤ DataAPI
```

## 目录结构

```
qdata/
├── pyproject.toml
├── scripts/
│   ├── dev_install.sh          # 可编辑安装 + 修复 import 路径
│   ├── ensure_import_path.py   # macOS/Py3.14 .pth 隐藏问题修复
│   └── qdata.sh                # PYTHONPATH=src 包装启动
├── schema/
│   └── clickhouse.sql          # 全部建表 DDL
├── dags/
│   └── daily_etl.py            # Airflow 每日 ETL DAG（含主数据）
├── src/qdata/
│   ├── jobs/                   # 日历 / 回填 / 生产验收 / 日批 / smoke
│   ├── prod.py                 # 生产主源固化
│   ├── release.py              # dataset_version 连续性
│   ├── notify.py               # webhook 告警
│   ├── quality/checks.py       # 质检 HARD/SOFT

│   ├── constants.py            # A 股规则常量（板块、涨跌幅、整手规则）
│   ├── config.py               # 配置（pydantic-settings，从环境变量读取）
│   ├── symbols.py              # 代码格式转换
│   ├── calendar.py             # 交易日历
│   ├── db.py                   # ClickHouse 连接与幂等写入
│   ├── fetchers/               # ① 采集层
│   │   ├── registry.py         #    数据源注册表（能力/依赖）
│   │   ├── factory.py          #    get_fetcher / get_broker
│   │   ├── failover.py         #    多源故障转移
│   │   ├── akshare_fetcher.py
│   │   ├── baostock_fetcher.py
│   │   ├── tushare_fetcher.py
│   │   ├── joinquant_fetcher.py
│   │   ├── efinance_fetcher.py
│   │   ├── mootdx_fetcher.py   #    PyTDX / MootDX
│   │   ├── easyquotation_fetcher.py
│   │   ├── zvt_fetcher.py
│   │   ├── miniqmt_fetcher.py  #    需本机 QMT
│   │   └── cli.py
│   ├── brokers/                # 交易通道（非 ETL）
│   │   ├── miniqmt.py
│   │   └── easytrader_broker.py
│   ├── lake/                   # ② Raw 区
│   │   └── raw.py              #    Parquet 落盘 + manifest 登记
│   ├── index/                  # 指数成分 SCD2
│   ├── industry/               # 申万行业属性 SCD2
│   ├── factors/                # 种子因子
│   ├── research/               # 回测读数（portfolio）
│   ├── loaders/                # ③ 清洗转换
│   │   ├── base.py
│   │   ├── security_master.py
│   │   ├── daily_bar.py
│   │   ├── index_member.py
│   │   ├── industry_member.py
│   │   └── fin_statement.py
│   ├── quality/
│   │   └── checks.py
│   └── api/
│       └── data_api.py         # get_price / get_universe / get_industry / load_factor
└── tests/
```

## 快速开始

```bash
bash scripts/dev_install.sh
cp .env.example .env

# 可选行情源（Tushare / Efinance / MootDX / EasyQuotation）
# .venv/bin/python -m pip install -e '.[sources]'
# .env: QDATA_TUSHARE_ENABLED=true 且 QDATA_TUSHARE_TOKEN=... 后可用 --source tushare

# QDATA_DATA_SOURCE=auto
# QDATA_DATA_SOURCE_CHAIN=akshare,baostock,tushare,efinance,mootdx
# QDATA_AKSHARE_MAX_SYMBOLS=30

clickhouse-client --multiquery < schema/clickhouse.sql

.venv/bin/python -m qdata.fetchers --list-sources

# M1.5 生产：主源固化 + 全市场回填 + version连续/smoke全绿验收
# .env: QDATA_PROD_SOURCE=baostock  QDATA_AKSHARE_MAX_SYMBOLS=0
.venv/bin/python -m qdata.jobs.prod_backfill --start 2026-07-01 --end 2026-07-15

# 联调回填（可用 MAX_SYMBOLS）
.venv/bin/python -m qdata.jobs.sync_calendar --start 2026-01-01 --end 2026-12-31
.venv/bin/python -m qdata.jobs.backfill --start 2026-07-01 --end 2026-07-15 --source baostock
.venv/bin/python -m qdata.jobs.smoke --date 2026-07-15

# 或单日
.venv/bin/python -m qdata.loaders.security_master --date 2026-07-15 --fetch
.venv/bin/python -m qdata.loaders.daily_bar --date 2026-07-15 --fetch
```

Raw：`data/data-lake/raw/<source>/<dataset>/dt=<date>/`。

### 多源采集

| 源 | 类型 | 安装 | 说明 |
|----|------|------|------|
| `akshare` | 历史 | 默认 | 东财等，网络敏感 |
| `baostock` | 历史 | 默认 | 稳定日线，免费兜底 |
| `tushare` | 历史 | `.[tushare]` + token | 正式跑批推荐，按积分 |
| `joinquant` | 历史 | `.[joinquant]` + 账号 | 聚宽 jqdatasdk（别名 `jq`） |
| `efinance` | 历史 | `.[efinance]` | 东财封装 |
| `mootdx` | 历史/实时 | `.[mootdx]` | 通达信协议（PyTDX） |
| `easyquotation` | 实时 | `.[easyquotation]` | 新浪/腾讯快照，无历史日线 |
| `zvt` | 历史 | `.[zvt]` | 读本地 ZVT 库 |
| `miniqmt` | 历史/实时 | 本机 QMT+`xtquant` | 行情；下单用 `get_broker` |
| `easytrader` | 交易 | `.[easytrader]`+客户端 | 仅交易，不做 ETL |

详见 [docs/数据采集操作说明.md](docs/数据采集操作说明.md)。

```bash
# 指定源 / 故障转移链
.venv/bin/python -m qdata.fetchers --date 2026-07-15 --dataset daily_bar --source tushare
.venv/bin/python -m qdata.fetchers --date 2026-07-15 --dataset daily_bar --source baostock
.venv/bin/python -m qdata.fetchers --date 2026-07-15 --dataset realtime_quote --source easyquotation
.venv/bin/python -m qdata.loaders.daily_bar --date 2026-07-15 --fetch --source mootdx

# 交易通道（需本机终端）
# from qdata.fetchers.factory import get_broker
# br = get_broker("miniqmt"); br.connect()
```

`QDATA_DATA_SOURCE=auto` 时按 `QDATA_DATA_SOURCE_CHAIN` 依次回退（默认 `akshare,baostock,efinance,mootdx`）。

### 排查：`No module named 'qdata'`

```bash
.venv/bin/python scripts/ensure_import_path.py
./scripts/qdata.sh -m qdata.loaders.security_master --date 2026-07-15 --fetch
```

## 设计要点

- **Raw 区不可变**：`raw/<source>/<dataset>/dt=<date>/`。
- **行情存不复权价 + 复权因子**：复权在 DataAPI 读取时计算。
- **财务 PIT**：按公告日 `ann_date` 建模。
- **分区幂等**：Loader 按日先删后插。
- **行情与交易分离**：`get_fetcher` vs `get_broker`。
