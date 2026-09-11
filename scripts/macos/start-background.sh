#!/bin/bash
# =============================================================================
# Velluma 后台启动（无终端）：nohup 脱离终端运行 start.sh，浏览器监控台是唯一界面。
# 用法：start-background.sh [dev|debug|prod]（默认 dev）
# 停止：同目录 stop-velluma.sh
# =============================================================================
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODE="${1:-dev}"
case "$MODE" in dev|debug|prod) ;; *) echo "无效模式: $MODE（可选 dev / debug / prod）"; exit 1 ;; esac
# 单实例护栏（与 Windows 监督者对称）：已有启动器在跑就拒绝——双服务树只会互相抢端口、
# 抢同一组 dev_*.log/状态文件（本脚本自身的命令行是 start-background.sh，不会被此模式命中）
if pgrep -f "scripts/macos/start\.sh" >/dev/null 2>&1; then
    echo "已有 Velluma 启动器在运行（先 stop-velluma.sh 再启动）"
    exit 1
fi
mkdir -p "$DIR/../../logs"
LOG="$DIR/../../logs/background_$(date +%Y%m%d_%H%M%S).log"
nohup bash "$DIR/start.sh" "$MODE" > "$LOG" 2>&1 &
disown
echo "Velluma 后台启动中（$MODE）——浏览器监控台稍后自动打开"
echo "启动器日志: $LOG"
echo "停止: $DIR/stop-velluma.sh"
