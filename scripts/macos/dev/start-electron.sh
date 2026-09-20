#!/bin/bash
# =============================================================================
# Velluma 开发调试环境·macOS 单独启动 Electron（loadURL 连 Vite，自动开 DevTools）
# =============================================================================
# scripts/macos/dev/ 四件套之一，与本目录 start-all.sh 互不依赖、逻辑各自独立。
# 关掉 Electron 窗口即退出（只退 Electron，后端/前端是独立进程不受影响）。
# 前置检查：
#   - 前端（Vite）必须在跑——dev 模式 main.cjs 走 loadURL，没有 Vite 就是白屏；
#     端口取 data/frontend_port.txt（本目录 start-frontend.sh / start-all.sh 写入）。
#   - 后端不强求：未检测到时 main.cjs 会尝试自行拉起。
# electron:nobuild（= 直接 "electron ."）：vite build 产物在 dev 模式根本不会被加载；
# 显式清掉 NODE_ENV，外部残留会让 main.cjs 误判走 loadFile 分支。
# =============================================================================
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

PORT_FILE="$PROJECT_ROOT/data/port.txt"
FRONTEND_PORT_FILE="$PROJECT_ROOT/data/frontend_port.txt"
FRONTEND_DIR="$PROJECT_ROOT/frontend"

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

frontend_port=$(read_port_file "$FRONTEND_PORT_FILE" "")
if [[ -z "$frontend_port" ]] || ! port_open "$frontend_port"; then
    echo "前端（Vite）未在运行——先跑 scripts/macos/dev/start-frontend.sh 或 start-all.sh（dev 模式 Electron 必须连 Vite，否则白屏）" >&2
    exit 1
fi

backend_port=$(read_port_file "$PORT_FILE" "")
backend_note="已连接"
if [[ -z "$backend_port" ]] || ! port_open "$backend_port"; then
    backend_note="未检测到后端——Electron 将尝试自行拉起"
    echo -e "\033[33m[*] $backend_note\033[0m" >&2
fi

echo ""
echo -e "\033[33m  Velluma · DEV Electron  →  http://127.0.0.1:$frontend_port  （后端 $backend_note）\033[0m"
echo ""

export VELLUMA_FRONTEND_PORT="$frontend_port"
[[ -n "$backend_port" ]] && export VELLUMA_BACKEND_PORT="$backend_port" || unset VELLUMA_BACKEND_PORT
export VELLUMA_SERVICES_READY=1
unset NODE_ENV

cd "$FRONTEND_DIR"
exec npm run electron:nobuild
