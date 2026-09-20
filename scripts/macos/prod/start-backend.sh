#!/bin/bash
# =============================================================================
# Velluma 正式生产环境·macOS 单独启动后端（无热重载，前台运行）
# =============================================================================
# scripts/macos/prod/ 四件套之一，与本目录 start-all.sh 互不依赖、逻辑各自独立。
# 走 main.py 的 __main__：内部 find_available_port 扫描（8002~8100，与全端契约一致，
# check_launcher_contract.py 对拍）并自写 data/port.txt——无需脚本侧协商。
# Ctrl+C 停止（收摊兜底 scripts/stop-velluma.sh）。
# =============================================================================
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

DEFAULT_BACKEND_PORT=8002
BACKEND_PORT_MAX=8100        # 与 backend/core/config.py、stop-velluma 孤儿清扫段对齐
PORT_FILE="$PROJECT_ROOT/data/port.txt"

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

find_python() {
    local path
    for path in ".venv/bin/python" "venv/bin/python"; do
        if [[ -x "$PROJECT_ROOT/$path" ]]; then
            echo "$PROJECT_ROOT/$path"; return 0
        fi
    done
    echo "Python venv not found (python3 -m venv .venv)" >&2; exit 1
}

recorded=$(read_port_file "$PORT_FILE" "")

echo ""
if [[ -n "$recorded" ]]; then
    echo -e "\033[36m  Velluma · PROD 后端（端口由后端自协商，上次记录 :$recorded）\033[0m"
else
    echo -e "\033[36m  Velluma · PROD 后端（端口由后端自协商，默认 ${DEFAULT_BACKEND_PORT} 起）\033[0m"
fi
echo ""

if [[ -n "$recorded" ]] && port_open "$recorded"; then
    echo -e "\033[32m[OK] 后端已在运行 http://127.0.0.1:$recorded\033[0m"
    exit 0
fi

python_path=$(find_python)
export PYTHONUNBUFFERED=1
export PYTHONIOENCODING=utf-8

# 前台直跑（exec 替换 shell）：main.py 自己扫描空闲端口并写 data/port.txt
cd "$PROJECT_ROOT"
exec "$python_path" -m backend.main
