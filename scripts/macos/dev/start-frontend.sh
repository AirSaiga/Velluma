#!/bin/bash
# =============================================================================
# Velluma 开发调试环境·macOS 单独启动前端（Vite dev server，前台运行）
# =============================================================================
# scripts/macos/dev/ 四件套之一，与本目录 start-all.sh 互不依赖、逻辑各自独立。
# Ctrl+C 停止（收摊兜底 scripts/stop-velluma.sh）。
# 端口契约（与全端一致，check_launcher_contract.py 对拍）：
#   - 协商优先级：环境变量 VELLUMA_FRONTEND_PORT → data/frontend_port.txt 已记录且
#     空闲 → 扫描 5175~5285；
#   - 选中即写 data/frontend_port.txt 并设同名环境变量（vite.config.js strictPort 读它，
#     Electron 的 main.cjs 也读端口文件——双保险）。
# =============================================================================
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

DEFAULT_FRONTEND_PORT=5175
FRONTEND_PORT_MAX=5285       # 与 stop-velluma 孤儿清扫段对齐
FRONTEND_PORT_FILE="$PROJECT_ROOT/data/frontend_port.txt"
FRONTEND_DIR="$PROJECT_ROOT/frontend"

FORCE=0
[[ "${1:-}" = "--force" || "${1:-}" = "-Force" ]] && FORCE=1

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

find_free_port() {
    local start="$1" end="$2" port
    for ((port = start; port <= end; port++)); do
        if ! port_open "$port"; then echo "$port"; return 0; fi
    done
    echo "No free port in range $start..$end" >&2; exit 1
}

[[ -d "$FRONTEND_DIR/node_modules" ]] || { echo "node_modules not found. Please run: cd frontend && npm install" >&2; exit 1; }

# ---- 端口协商（环境变量 → 已记录且空闲 → 扫描）----
if [[ -n "$VELLUMA_FRONTEND_PORT" && "$VELLUMA_FRONTEND_PORT" =~ ^[0-9]+$ && "$VELLUMA_FRONTEND_PORT" -gt 0 ]]; then
    frontend_port="$VELLUMA_FRONTEND_PORT"
else
    recorded=$(read_port_file "$FRONTEND_PORT_FILE" "")
    if [[ -n "$recorded" ]] && ! port_open "$recorded"; then
        frontend_port="$recorded"
    else
        frontend_port=$(find_free_port "$DEFAULT_FRONTEND_PORT" "$FRONTEND_PORT_MAX")
    fi
fi
mkdir -p "$PROJECT_ROOT/data"
printf '%s' "$frontend_port" > "$FRONTEND_PORT_FILE"

echo ""
echo -e "\033[32m  Velluma · DEV 前端（Vite）  http://127.0.0.1:$frontend_port\033[0m"
echo ""

if port_open "$frontend_port"; then
    if [[ "$FORCE" = "1" ]]; then
        if command -v lsof >/dev/null 2>&1; then
            pid=$(lsof -ti tcp:"$frontend_port" -sTCP:LISTEN 2>/dev/null | head -1)
            [[ -n "$pid" ]] && kill -9 "$pid" 2>/dev/null || true && sleep 2
        fi
    else
        echo -e "\033[32m[OK] 前端已在运行 http://127.0.0.1:$frontend_port（--force 可强制重开）\033[0m"
        exit 0
    fi
fi

# 前台直跑：输出实时进本终端；stdin 挂在真终端上，vite 交互快捷键（r 重启等）可用
export VELLUMA_FRONTEND_PORT="$frontend_port"
cd "$FRONTEND_DIR"
exec npm run dev
