#!/bin/bash
# =============================================================================
# Velluma 正式生产环境·macOS 单独启动 Electron（NODE_ENV=production 载入 dist）
# =============================================================================
# scripts/macos/prod/ 四件套之一，与本目录 start-all.sh 互不依赖、逻辑各自独立。
# 关掉 Electron 窗口即退出（只退 Electron，后端是独立进程不受影响）。
# 前置检查：
#   - dist/index.html 必须在（先跑本目录 start-frontend.sh 构建 或 start-all.sh）；
#   - 后端不强求：未检测到时 main.cjs 会尝试自行拉起。
# electron:nobuild（= 直接 "electron ."）：dist 已构建时 electron:dev/preview 系脚本
# 再 build 一次纯属浪费；NODE_ENV=production → loadFile 分支、不开 DevTools。
# =============================================================================
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

PORT_FILE="$PROJECT_ROOT/data/port.txt"
FRONTEND_DIR="$PROJECT_ROOT/frontend"
DIST_INDEX="$FRONTEND_DIR/dist/index.html"

port_open() {
    local port="$1"
    if command -v nc >/dev/null 2>&1; then
        nc -z 127.0.0.1 "$port" >/dev/null 2>&1
    else
        (exec 3<>"/dev/tcp/127.0.0.1/$port") >/dev/null 2>&1
    fi
}

read_port_file() {
    local file="$1" fallback="$2" port
    if [[ -f "$file" ]]; then
        port=$(tr -d ' \t\r\n' < "$file" 2>/dev/null || true)
        if [[ "$port" =~ ^[0-9]+$ ]] && [[ "$port" -gt 0 ]]; then
            echo "$port"; return 0
        fi
    fi
    echo "$fallback"
}

[[ -d "$FRONTEND_DIR/node_modules" ]] || { echo "node_modules not found. Please run: cd frontend && npm install" >&2; exit 1; }
[[ -f "$DIST_INDEX" ]] || { echo "frontend/dist/index.html 不存在——先跑 scripts/macos/prod/start-frontend.sh 构建（或 start-all.sh）" >&2; exit 1; }

backend_port=$(read_port_file "$PORT_FILE" "")
backend_note="已连接"
if [[ -z "$backend_port" ]] || ! port_open "$backend_port"; then
    backend_note="未检测到后端——Electron 将尝试自行拉起"
    echo -e "\033[33m[*] $backend_note\033[0m" >&2
fi

echo ""
echo -e "\033[33m  Velluma · PROD Electron  →  dist/index.html  （后端 $backend_note）\033[0m"
echo ""

[[ -n "$backend_port" ]] && export VELLUMA_BACKEND_PORT="$backend_port" || unset VELLUMA_BACKEND_PORT
export VELLUMA_SERVICES_READY=1
export NODE_ENV="production"

cd "$FRONTEND_DIR"
exec npm run electron:nobuild
