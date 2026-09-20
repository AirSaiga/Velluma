#!/bin/bash
# =============================================================================
# Velluma 开发调试环境·macOS 单独启动后端（uvicorn --reload 热重载，前台运行）
# =============================================================================
# scripts/macos/dev/ 四件套之一，与本目录 start-all.sh 互不依赖、逻辑各自独立。
# Ctrl+C 停止（收摊兜底 scripts/stop-velluma.sh）。
# 端口契约（与全端一致，check_launcher_contract.py 对拍）：
#   - 协商优先级：环境变量 VELLUMA_PORT → data/port.txt 已记录且空闲 → 扫描 8002~8100；
#   - 选中即写 data/port.txt——uvicorn 直启不走 main.py 的 __main__（save_port 不执行），
#     固定端口是热重载期间端口不漂移的前提。
# =============================================================================
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

DEFAULT_BACKEND_PORT=8002
BACKEND_PORT_MAX=8100        # 与 backend/core/config.py、stop-velluma 孤儿清扫段对齐
PORT_FILE="$PROJECT_ROOT/data/port.txt"

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

find_python() {
    local path
    for path in ".venv/bin/python" "venv/bin/python"; do
        if [[ -x "$PROJECT_ROOT/$path" ]]; then
            echo "$PROJECT_ROOT/$path"; return 0
        fi
    done
    echo "Python venv not found (python3 -m venv .venv)" >&2; exit 1
}

# ---- 端口协商（环境变量 → 已记录且空闲 → 扫描）----
if [[ -n "$VELLUMA_PORT" && "$VELLUMA_PORT" =~ ^[0-9]+$ && "$VELLUMA_PORT" -gt 0 ]]; then
    backend_port="$VELLUMA_PORT"
else
    recorded=$(read_port_file "$PORT_FILE" "")
    if [[ -n "$recorded" ]] && ! port_open "$recorded"; then
        backend_port="$recorded"
    else
        backend_port=$(find_free_port "$DEFAULT_BACKEND_PORT" "$BACKEND_PORT_MAX")
    fi
fi
mkdir -p "$PROJECT_ROOT/data"
printf '%s' "$backend_port" > "$PORT_FILE"

echo ""
echo -e "\033[36m  Velluma · DEV 后端（热重载）  http://127.0.0.1:$backend_port\033[0m"
echo ""

if port_open "$backend_port"; then
    if [[ "$FORCE" = "1" ]]; then
        if command -v lsof >/dev/null 2>&1; then
            pid=$(lsof -ti tcp:"$backend_port" -sTCP:LISTEN 2>/dev/null | head -1)
            [[ -n "$pid" ]] && kill -9 "$pid" 2>/dev/null || true && sleep 2
        fi
    else
        echo -e "\033[32m[OK] 后端已在运行 http://127.0.0.1:$backend_port（--force 可强制重开）\033[0m"
        exit 0
    fi
fi

python_path=$(find_python)
export VELLUMA_PORT="$backend_port"
export PYTHONUNBUFFERED=1
export PYTHONIOENCODING=utf-8

# 前台直跑（exec 替换 shell）：输出实时进本终端，Ctrl+C 由 uvicorn reloader 收敛
#   --reload 必须传 import path；--reload-dir backend 只监听后端代码变更
cd "$PROJECT_ROOT"
exec "$python_path" -m uvicorn backend.main:app \
    --host 127.0.0.1 --port "$backend_port" \
    --reload --reload-dir "$PROJECT_ROOT/backend" --app-dir "$PROJECT_ROOT"
