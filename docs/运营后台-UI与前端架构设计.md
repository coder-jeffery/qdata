# qdata 运营后台 — UI 与前端架构设计

> 更新日期：2026-07-19  
> 定位：面向研究/运维的**极简扁平科技感**后台（哑光白底、中文指标）  
> 原型：[`ui/ops-console/index.html`](../ui/ops-console/index.html)  
> 后端能力对齐：[量化平台开发手册.md](./量化平台开发手册.md)

---

## 1. 设计原则

| 原则 | 落地 |
|------|------|
| 极简留白 | 一屏一事；高级留白，无多余装饰 |
| 柔和氛围 | 低饱和莫兰迪底 + 径向柔和渐变；哑光噪点极弱 |
| 微分层 | 毛玻璃侧栏/卡片 + 轻阴影 + 弱高光内描边；无厚重浮雕 |
| 统一尺度 | 圆角 8 / 12px；分割线 2px；间距 4 / 8px 进制 |
| 图标 | 细线条、等距轻描 SVG；无填充厚图标 |
| 动效 | 卡片悬浮微抬升、页切换淡入；时长 ~220ms，可扩展 |
| 中文优先 | 指标、导航、空态、告警一律中文 |

**氛围关键词：** 轻奢商务 · 极简高端 · 克制 · 专业商用 · 低噪通透。

### 1.1 视觉令牌

```
--space:        4 / 8 / 12 / 16 / 24 / 32 / 48 / 64
--radius:       8px | 12px
--line:         2px
--bg:           #F3F1EE → #EDEAE5 柔和渐变 + 莫兰迪光晕
--surface:      rgba(255,252,248,0.72) + blur(16px)
--ink:          #2C2A28 / #5A5652 / #8A8580（三级文字）
--accent:       #6B7F7A（鼠尾草绿灰）
--accent-2:     #8B7355（暖陶土灰）
--up/down/warn: #5F7A68 / #A66A5E / #A68B5B
--shadow:       微分层（1 级静止 / 2 级悬浮）
--font:         DM Sans + Noto Sans SC；数字 JetBrains Mono
```

### 1.2 排版与组件

- **品牌**：侧栏毛玻璃顶栏「qdata」+ 细线 logo。
- **卡片**：12px 圆角；hover `translateY(-2px)` + 阴影加深。
- **按钮**：8px 圆角；主按钮鼠尾草渐变 + 弱高光。
- **表格**：2px 分割；行 hover 极淡着色。
- **栅格**：主内容 max ~1120px；指标区 4 列 → 2 列 → 1 列自适应。

---

## 2. 前端信息架构

按**工作流**分组，而非按技术表名：

```
总览
  └ 运营首页（日批状态 · 数据水位 · 监控告警 · Paper 摘要）

数据运维
  ├ 数据健康（发布连续性 · 行数 · 漂移）
  ├ 财务 PIT（公告水位 · 科目覆盖）
  └ 日批与告警（daily_run / factor_monitor WARN）

研究决策
  ├ 因子覆盖
  ├ 选股域 / 行业
  ├ 实验矩阵
  ├ 信号台（含研判联动）
  ├ 个股研判
  └ 回测报告

纸交易
  ├ Paper 运营（账户 · 成交 · 拒单）
  ├ 日终盯市
  └ 会话对比

系统
  └ 版本与契约（dataset_version · app_pipeline_version）
```

**导航层级：** L1 分组（数据运维 / 研究决策 / 纸交易）→ L2 页面。首屏默认「运营首页」。

---

## 3. 页面与模块功能设计

### 3.1 运营首页（总览）

| 区块 | 中文指标 | 数据来源 |
|------|----------|----------|
| 日批状态 | 最近日批结果、交易日、耗时提示 | `daily_run` 日志 / webhook |
| 数据水位 | 日线起止日、证券只数、已发布交易日数 | CH `daily_bar` / `dataset_version` |
| 因子监控 | 告警数、覆盖率阈值、来源（日批/手工） | `factor_monitor/<date>/report.json` |
| Paper 摘要 | 最新会话总资产、成交笔数、相对初始盈亏 | `paper_sessions` |
| 快捷入口 | 构建信号 · 调仓 · 盯市 · 实验矩阵 | 路由跳转 |

首屏只放上述 4 组指标 + 快捷入口，不堆全站统计。

### 3.2 数据健康

| 中文指标 | 含义 |
|----------|------|
| 最新发布日 | 最近 `dataset_version` |
| 连续发布天数 | 区间内无断档交易日数 |
| 全市场行数 | 当日 `daily_bar` 行数 |
| 证券主档只数 | `security_master` |
| 日线漂移 | 与预期行数偏差 |
| 验收状态 | ACCEPTANCE 通过/失败 |

### 3.3 因子覆盖

| 中文指标 | 含义 |
|----------|------|
| 因子名称 | mom_20 / ep 等 |
| 覆盖率 | 有值证券 / 宇宙 |
| 证券数 | 非空因子值数量 |
| 告警 | 低于阈值或空窗 |

### 3.4 实验矩阵

| 中文指标 | 含义 |
|----------|------|
| 实验编号 | experiment_id |
| 年化收益 | ann_return |
| 夏普比率 | sharpe |
| 最大回撤 | max_drawdown |
| 信息比率 | info_ratio |
| 换手率 | turnover |
| 状态 | 成功 / 失败 |

操作：选中最优行 →「挂钩调仓」（A308，显式确认）。

### 3.5 信号台

| 中文指标 | 含义 |
|----------|------|
| 信号日 | asof |
| 因子 / 加权方式 | factor / weight_method |
| 成分数 | n_names |
| 权重合计 | weight_sum |
| 不可交易数 | non_tradable_count |
| 行业暴露 | 相对指数偏离 |

操作：批量研判 TopN、跳转个股研判、导出权重。

### 3.6 个股研判

| 中文指标 | 含义 |
|----------|------|
| 综合分 | composite |
| 立场 | 偏强 / 中性 / 偏弱 |
| 相对强弱 | 相对基准超额 |
| 可交易性 | 正常 / 受限 / 阻断 |
| 五维分 | 动量·波动·估值·换手·质量 |

### 3.7 Paper 运营 / 盯市 / 对比

| 中文指标 | 含义 |
|----------|------|
| 现金 | cash |
| 持仓市值 | market_value |
| 总资产 | total_asset |
| 成交 / 拒单 | n_filled / n_rejected |
| 盯市日总资产 | mark total_asset |
| 相对初始盈亏 | pnl_vs_initial |
| 相对调仓盈亏 | pnl_vs_rebalance |
| 实验挂钩 | from_experiment 摘要 |

### 3.8 日批与告警

| 中文文案 | 对应事件 |
|----------|----------|
| 日批成功 | `qdata daily_run OK` |
| 日批失败 | `qdata daily_run FAIL`（阻断发布） |
| 因子监控警告 | `qdata factor_monitor WARN`（不阻断） |

---

## 4. 前端技术架构

### 4.1 推荐栈（替换 Streamlit 运营面）

```
ui/ops-console/          # 本阶段：静态原型（视觉与信息架构）
apps/web/                # 后续：React + Vite + TypeScript
  src/
    app/                 # 路由与壳层 Layout
    pages/               # 与 §2 一一对应
    features/            # 按域：data / research / paper / ops
    entities/            # 会话、信号、实验等类型
    shared/              # 设计令牌、Table、Metric、PageHeader
  api/                   # 调用后端 BFF，不直连 ClickHouse
```

| 层 | 职责 |
|----|------|
| 展示层 | React 页面；哑光白设计系统 |
| BFF | FastAPI / 现有 jobs 薄封装：只读 Lake+CH 聚合接口 |
| 领域层 | 复用 `qdata.apps.*` / `research.*`（Python） |
| 数据层 | ClickHouse + Lake（已有） |

**原则：** UI 不跑回测/回填重任务；触发类操作调 CLI 等价 HTTP（异步任务 + 状态轮询）。

### 4.2 路由草案

| 路径 | 页面 |
|------|------|
| `/` | 运营首页 |
| `/data/health` | 数据健康 |
| `/data/finance` | 财务 PIT |
| `/ops/daily` | 日批与告警 |
| `/research/factors` | 因子覆盖 |
| `/research/universe` | 选股域/行业 |
| `/research/experiments` | 实验矩阵 |
| `/research/signals` | 信号台 |
| `/research/judgment` | 个股研判 |
| `/research/backtests` | 回测报告 |
| `/paper/sessions` | Paper 运营 |
| `/paper/mark` | 日终盯市 |
| `/paper/compare` | 会话对比 |
| `/system/versions` | 版本契约 |

### 4.3 BFF 接口草图（中文资源名可作 OpenAPI summary）

```
GET  /api/overview              # ✅ 运营首页聚合
GET  /api/data/health           # ✅ 数据健康
GET  /api/factors/coverage      # ✅ 因子覆盖
GET  /api/experiments           # ✅ 实验列表
GET  /api/experiments/{id}      # ✅ 实验明细
GET  /api/signals               # ✅ 信号列表
GET  /api/signals/{id}          # ✅ 权重/暴露
POST /api/signals/{id}/judge    # ✅ A207 批量研判
GET  /api/paper/sessions        # ✅
GET  /api/paper/sessions/{id}   # ✅
POST /api/paper/sessions/{id}/mark  # ✅ A306
GET  /api/paper/compare?ids=    # ✅ A504
GET  /api/monitor[/{date}]      # ✅
GET  /api/backtests             # ✅ 回测矩阵
POST /api/jobs/paper-from-experiment  # ✅ A308（默认 async → job_id）
POST /api/jobs                    # ✅ 通用入队
GET  /api/jobs[/{job_id}]         # ✅ 轮询
GET  /api/alerts                  # ✅ 告警聚合（监控/日批/失败 job/健康）
GET  /api/realtime/quotes         # ✅ Lake realtime 快照
POST /api/realtime/refresh        # ✅ 拉取快照（默认 async）
```

实现：`src/qdata/api/bff.py` · `job_queue.py` · `alerts.py` · 前端：`apps/web`

写操作默认返回 `job_id`（`async: true`），前端轮询至成功/失败；同步仍可用 `async: false`。

### 4.4 与现网关系

| 现状 | 演进 |
|------|------|
| Streamlit 多页 | 并行保留研究探索；运营后台迁至本 UI |
| jobs CLI | BFF 包装，权限与审计在 BFF |
| Lake/CH | 只读查询优先；发布仍走日批 |

---

## 5. 交互规范（精简）

1. **确认破坏性操作：** 实验挂钩调仓、强制重跑日批需二次确认。  
2. **软告警 vs 硬失败：** 监控警告用琥珀文案；日批失败用红，且不可与「成功」同色。  
3. **空态：** 「暂无 Paper 会话」+ 一条命令提示，不放插画。  
4. **加载：** 骨架线或单行「载入中」，不用全屏 spinner。  
5. **移动端：** 侧栏折叠为顶栏；表格横向滚动；首屏指标改单列。

---

## 6. 原型说明

打开本地原型：

```bash
open ui/ops-console/index.html
# 或
python -m http.server 8765 --directory ui/ops-console
```

原型包含：壳层导航、运营首页、数据健康、信号台、Paper 运营四个示意页（同一设计系统），指标均为中文标签 + 示意数据。

---

## 7. 实施建议顺序

1. ~~冻结设计令牌与壳层（本原型）~~ → 视觉令牌已迁至冷色投行风（见交易终端规范）  
2. ~~BFF：`/api/overview` + `/api/paper/sessions`~~ → `src/qdata/api/bff.py` + `python -m qdata.jobs.web_api`  
3. ~~壳层 React~~ → `apps/web`：总览 / 交易 / Paper / 研究占位  
4. 接通实验挂钩与盯市写操作  
5. 其余研究页按流量迁移  

### 7.1 本地启动（已落地）

```bash
.venv/bin/pip install -e '.[web]'
.venv/bin/python -m qdata.jobs.web_api --port 8787
cd apps/web && npm install && npm run dev   # http://127.0.0.1:5173
```

真金下单 UI **不在本后台范围**；开闸前禁止启用（见 [M3-开闸验收.md](./M3-开闸验收.md)）。
