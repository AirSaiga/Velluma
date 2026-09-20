#!/bin/bash
# =============================================================================
# Velluma 后台模式·macOS/Linux 入口（与 Windows 的 start-background.vbs 对称）
# =============================================================================
# monitor 文件夹完全自持：python 监督者 dev_dashboard.py 是本文件夹的私有副本，
# 与 scripts/dev、scripts/prod 的编排互不复用。监督者拥有整棵服务树：
#   - 端口协商（与全端契约一致：后端 8002~8100 / 前端 5175~5285，写 data/*.txt）
#   - 拉起 backend / vite / electron（独立进程组 + stdin 切断）
#   - backend/vite 意外退出自愈重启（上限 2 次）；electron 退出 = 收摊
#   - 网页监控台（8180 起扫空闲端口，浏览器自动打开）——后台模式下的唯一界面
# 用法：start-background.sh [dev|debug|prod]（默认 dev；debug = mtime 热重载）
# 停止：scripts/stop-velluma.sh（TERM 监督者，其信号处理器干净收摊）
# =============================================================================
MODE="${1:-dev}"
case "$MODE" in dev|debug|prod) ;; *) echo "无效模式: $MODE（可选 dev / debug / prod）"; exit 1 ;; esac

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# venv 解释器（Windows 形态兜底：本脚本也可能在 Git Bash 里被误跑，给出明确报错）
PY="$ROOT/.venv/bin/python3"
[ -x "$PY" ] || PY="$ROOT/venv/bin/python3"
[ -x "$PY" ] || PY="$(command -v python3 || true)"
[ -n "$PY" ] || { echo "python3 not found（venv: $ROOT/.venv/bin/python3）"; exit 1; }

# 单实例护栏：已有监督者在跑就拒绝——双服务树只会互相抢端口、抢同一组
# dev_*.log/状态文件（python 侧另有状态 JSON 新鲜度护栏，这里先挡一道）
if pgrep -f "monitor/dev_dashboard\.py.*--supervise" >/dev/null 2>&1; then
    echo "已有 Velluma 后台监督者在运行（先 scripts/stop-velluma.sh 再启动）"
    exit 1
fi

mkdir -p "$ROOT/logs" "$ROOT/data"
LOG="$ROOT/logs/background_$(date +%Y%m%d_%H%M%S).log"
nohup "$PY" "$SCRIPT_DIR/dev_dashboard.py" \
    --supervise --mode "$MODE" --root "$ROOT" \
    --dir "$ROOT/logs" --status "$ROOT/data/dev_status.json" --port 0 \
    > "$LOG" 2>&1 &
disown
echo "Velluma 后台启动中（$MODE）——网页监控台稍后自动打开"
echo "监督者日志: $LOG"
echo "停止: $ROOT/scripts/stop-velluma.sh"
