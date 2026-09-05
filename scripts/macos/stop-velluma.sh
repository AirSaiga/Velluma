#!/bin/bash
# =============================================================================
# Velluma 一键收摊：TERM 启动器，其 EXIT trap 会按进程树清理全部子服务
# （backend/vite/electron/网页监控台都是启动器的子进程）
# =============================================================================
pkill -TERM -f "scripts/macos/start.sh" 2>/dev/null
if [[ $? -eq 0 ]]; then
    echo "Velluma 停止中（已通知启动器，清理由其 trap 兜底完成）"
else
    echo "没有在运行的 Velluma 启动器"
fi
