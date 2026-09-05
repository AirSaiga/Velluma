#!/bin/bash
# =============================================================================
# Velluma 后台启动（无终端）：nohup 脱离终端运行 start.sh，浏览器监控台是唯一界面。
# 用法：start-background.sh [dev|debug|prod]（默认 dev）
# 停止：同目录 stop-velluma.sh
# =============================================================================
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODE="${1:-dev}"
case "$MODE" in dev|debug|prod) ;; *) echo "无效模式: $MODE（可选 dev / debug / prod）"; exit 1 ;; esac
mkdir -p "$DIR/../../logs"
LOG="$DIR/../../logs/background_$(date +%Y%m%d_%H%M%S).log"
nohup bash "$DIR/start.sh" "$MODE" > "$LOG" 2>&1 &
disown
echo "Velluma 后台启动中（$MODE）——浏览器监控台稍后自动打开"
echo "启动器日志: $LOG"
echo "停止: $DIR/stop-velluma.sh"
