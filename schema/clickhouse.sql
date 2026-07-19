-- =====================================================================
-- qdata ClickHouse 建表 DDL
-- 设计原则：行情存不复权价+复权因子；财务按公告日 PIT；退市股保留
-- =====================================================================

CREATE DATABASE IF NOT EXISTS qdata;

-- ---------------------------------------------------------------------
-- 证券主数据（SCD2 区间表：更名/状态变更以区间行表示）
-- security_id 为内部永久 ID，避免 A 股代码复用冲突
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS qdata.security_master
(
    security_id   UInt32,
    exchange_code String,                 -- '600000.SH' / '000001.SZ'
    name          String,
    list_date     Date,
    delist_date   Nullable(Date),         -- NULL = 在市；退市股必须保留
    board         Enum8('main' = 1, 'gem' = 2, 'star' = 3, 'bse' = 4),
    valid_from    Date,
    valid_to      Date                    -- 开区间上界，当前有效行用 '2099-12-31'
)
ENGINE = ReplacingMergeTree
ORDER BY (security_id, valid_from);

-- ---------------------------------------------------------------------
-- 交易日历
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS qdata.trade_calendar
(
    cal_date   Date,
    is_open    UInt8,
    prev_open  Date,                      -- 上一交易日（预计算）
    next_open  Date
)
ENGINE = ReplacingMergeTree
ORDER BY cal_date;

-- ---------------------------------------------------------------------
-- 日线行情：不复权价 + 累积复权因子 + 涨跌停价预计算 + 状态快照
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS qdata.daily_bar
(
    trade_date   Date,
    security_id  UInt32,
    open         Float64,
    high         Float64,
    low          Float64,
    close        Float64,
    pre_close    Float64,                 -- 昨收（除权基准，交易所口径）
    volume       UInt64,                  -- 股
    amount       Float64,                 -- 元
    adj_factor   Float64,                 -- 累积复权因子
    up_limit     Float64,                 -- 当日涨停价（按板块/ST 预计算）
    down_limit   Float64,
    is_suspended UInt8,
    is_st        UInt8                    -- 当日 ST 状态快照，避免回测时 join
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(trade_date)
ORDER BY (security_id, trade_date);

-- ---------------------------------------------------------------------
-- 每日指标（股本/换手/估值，来自 AKShare daily_basic）
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS qdata.daily_basic
(
    trade_date    Date,
    security_id   UInt32,
    total_share   Float64,                -- 总股本（万股）
    float_share   Float64,
    total_mv      Float64,                -- 总市值（万元）
    circ_mv       Float64,
    turnover_rate Float64,
    pe_ttm        Nullable(Float64),
    pb            Nullable(Float64)
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(trade_date)
ORDER BY (security_id, trade_date);

-- ---------------------------------------------------------------------
-- 财务报表 PIT：按公告日建模，更正公告追加（update_flag=1）不覆盖
-- 查询语义：T 日可见 = ann_date <= T 的最新 (report_date, ann_date)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS qdata.fin_statement
(
    security_id UInt32,
    ann_date    Date,                     -- 公告日：回测中可见的最早日期
    report_date Date,                     -- 报告期末，如 2025-12-31
    stmt_type   Enum8('income' = 1, 'balance' = 2, 'cashflow' = 3),
    update_flag UInt8,                    -- 0=首次披露 1=更正
    fields      Map(String, Float64)      -- 科目 → 值，如 {'revenue': 1.2e9}
)
ENGINE = MergeTree
PARTITION BY toYear(ann_date)
ORDER BY (security_id, ann_date, report_date);

-- ---------------------------------------------------------------------
-- 停复牌区间
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS qdata.suspend
(
    security_id  UInt32,
    suspend_date Date,
    resume_date  Nullable(Date)           -- NULL = 尚未复牌
)
ENGINE = ReplacingMergeTree
ORDER BY (security_id, suspend_date);

-- ---------------------------------------------------------------------
-- 指数成分区间表（时点正确的选股域）
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS qdata.index_member
(
    index_code  String,                   -- '000905.SH'
    security_id UInt32,
    in_date     Date,
    out_date    Date                      -- 未调出用 '2099-12-31'
)
ENGINE = ReplacingMergeTree
ORDER BY (index_code, security_id, in_date);

-- ---------------------------------------------------------------------
-- 行业分类区间表（申万，保留历史变更）
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS qdata.industry_member
(
    security_id UInt32,
    level       Enum8('sw_l1' = 1, 'sw_l2' = 2),
    industry    String,
    in_date     Date,
    out_date    Date
)
ENGINE = ReplacingMergeTree
ORDER BY (security_id, level, in_date);

-- ---------------------------------------------------------------------
-- 因子库
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS qdata.factor_value
(
    trade_date  Date,
    security_id UInt32,
    factor_name LowCardinality(String),
    version     LowCardinality(String),
    value       Float64
)
ENGINE = MergeTree
PARTITION BY (factor_name, toYYYYMM(trade_date))
ORDER BY (factor_name, version, trade_date, security_id);

-- ---------------------------------------------------------------------
-- 数据集版本登记（全部质量硬规则通过后才发布）
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS qdata.dataset_version
(
    dataset    String,
    version    String,                    -- 如 '2026-07-15'
    row_count  UInt64,
    published  DateTime DEFAULT now(),
    note       String DEFAULT ''
)
ENGINE = MergeTree
ORDER BY (dataset, version);

-- ---------------------------------------------------------------------
-- 回测 run 元数据与净值曲线（Lake Parquet 为主；CH 便于多 run 对比）
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS qdata.backtest_run
(
    run_id           String,
    created_at       DateTime,
    engine_version   LowCardinality(String),
    dataset_version  String,
    factor           String DEFAULT '',
    factor_version   LowCardinality(String) DEFAULT 'v1',
    universe         String DEFAULT '',
    execution        LowCardinality(String),
    benchmark        String DEFAULT '',
    benchmark_mode   LowCardinality(String) DEFAULT '',
    run_name         String DEFAULT '',
    metrics_json     String DEFAULT '',
    meta_json        String DEFAULT ''
)
ENGINE = MergeTree
ORDER BY (created_at, run_id);

CREATE TABLE IF NOT EXISTS qdata.backtest_equity
(
    run_id       String,
    trade_date   Date,
    nav          Float64,
    ret          Float64,
    cash         Float64,
    market_value Float64,
    turnover     Float64,
    cash_ratio   Float64,
    n_positions  UInt32
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(trade_date)
ORDER BY (run_id, trade_date);
