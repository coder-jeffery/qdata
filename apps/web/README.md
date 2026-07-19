# qdata Web（React + Vite）· P1 产品化

冷色投行风 Desk，对接 FastAPI BFF。

## 启动

```bash
# 终端 1
.venv/bin/python -m qdata.jobs.web_api --port 8787

# 终端 2
cd apps/web && npm run dev
```

http://127.0.0.1:5173

## 页面地图

| 路由 | 说明 |
|------|------|
| `/` | 运营总览 |
| `/trade` | Paper 只读交易台 |
| `/paper` | 盯市（确认框）· 对比 · Toast |
| `/data/health` | 数据健康 |
| `/data/finance` | 财务 PIT |
| `/ops/monitor` | 因子监控 |
| `/research` | 回测矩阵入口 |
| `/research/experiments` | 实验 → Paper（确认） |
| `/research/signals` | 信号 · Top20 研判（确认） |
| `/research/factors` | 因子覆盖 |
| `/research/universe` | 选股域 / 行业 |
| `/research/judgment/:code` | 个股研判 |
| `/research/backtests/:runId` | 回测详情 |
