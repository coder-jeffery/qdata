#!/usr/bin/env bash
# 安装 qdata 日批 cron（Asia/Shanghai 工作日 17:30）
# 对齐：生产日线+basic → extras 水位增量(JQ) → 指数/行业 L1+L2 → 种子因子
#       → A405 软挂因子监控（告警不阻断发布；可用 --no-monitor-factors 关闭）
# 用法: bash scripts/install_daily_cron.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="$ROOT/.venv/bin/python"
LOG_DIR="$ROOT/logs"
mkdir -p "$LOG_DIR"
CMD="\"$PY\" -m qdata.jobs.daily_run --post-m2 --with-basic --with-extras --sync-industry --industry-levels sw_l1,sw_l2"
LINE="30 17 * * 1-5 cd \"$ROOT\" && $CMD >>\"$LOG_DIR/daily_run.log\" 2>&1"
(crontab -l 2>/dev/null | grep -v 'qdata.jobs.daily_run' || true; echo "$LINE") | crontab -
echo "已安装 cron:"
echo "  $LINE"
echo "查看: crontab -l | grep qdata"
echo "说明: extras 默认源 joinquant（可用 QDATA_EXTRAS_SOURCE 覆盖）；M2/监控失败默认仅告警"
