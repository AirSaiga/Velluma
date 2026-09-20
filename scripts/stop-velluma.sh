#!/bin/bash
# =============================================================================
# Velluma 一键收摊（macOS/Linux，dev / prod / monitor 通用）
# =============================================================================
# 停止顺序（给优雅路径优先权）：
#   1. TERM 编排启动器（scripts/macos/{dev,prod}/start-all.sh）——其 EXIT trap
#      会按进程树清理全部子服务（backend/vite/electron 都是启动器的子进程）；
#   2. TERM 后台监督者（scripts/monitor/dev_dashboard.py --supervise）——其 SIGTERM
#      处理器置停机标志，随后 stop_all 整组收摊并写「全停」状态 JSON；
#   3. 兜底清扫：端口段 8002~8100 / 5175~5285 上的残留监听者（单服务前台脚本不是
#      启动器的子进程，trap 够不到），归属判定 = 命令行含本项目路径
#      （他人项目/无关进程不碰，与 Windows 版孤儿清扫同哲学）。
# =============================================================================
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
found=0

# 1. 编排启动器
if pkill -TERM -f 'scripts/macos/(dev|prod)/start-all\.sh' 2>/dev/null; then
    echo "Velluma 停止中（已通知启动器，清理由其 trap 兜底完成）"
    found=1
fi

# 2. 后台监督者（monitor 私有副本）
if pkill -TERM -f 'monitor/dev_dashboard\.py.*--supervise' 2>/dev/null; then
    echo "Velluma 停止中（已通知后台监督者，其信号处理器收拢服务树）"
    found=1
fi

# 3. 端口清扫（归属闸：只杀命令行含本项目路径的监听者）
if command -v lsof >/dev/null 2>&1; then
    for port in $(seq 8002 8100) $(seq 5175 5285); do
        pid=$(lsof -ti tcp:"$port" -sTCP:LISTEN 2>/dev/null | head -1)
        [[ -z "$pid" ]] && continue
        if ps -p "$pid" -o command= 2>/dev/null | grep -qF "$ROOT"; then
            kill -9 "$pid" 2>/dev/null || true
            echo "  reaped orphan on port $port (pid $pid)"
            found=1
        fi
    done
fi

if [[ "$found" = "0" ]]; then
    echo "没有在运行的 Velluma 服务"
fi
