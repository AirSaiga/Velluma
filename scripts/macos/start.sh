#!/bin/bash
# =============================================================================
# Velluma 启动脚本·macOS 编排（与 windows/start.ps1 对称）
# =============================================================================
# 本脚本位于 scripts/macos/ 下，项目根 = 脚本目录的祖父目录。
# 用法：start.sh [dev|debug|prod] [flags]，模式也可用 -m/--mode 指定。
#   - prod : 生产体验模式。npm run build 预构建 dist，Electron 载入本地 dist 文件
#            （NODE_ENV=production），不启动 Vite dev server，不开 DevTools。
#            后端仍用本地 .venv 启动。
#   - dev  : 开发模式（默认）。后端 + Vite dev server + Electron（自动开 DevTools）。
#   - debug: 调试模式。后端 uvicorn --reload 热重载（保存 backend/ 下任意 .py 即自动
#            重启），前端 Vite + Electron。
# flags:
#   --force / -Force           端口被占用时强制清理后重启
#   --skip-backend / -SkipBackend    跳过后端（假设已运行）
#   --skip-frontend / -SkipFrontend  跳过前端（dev：跳 Vite；prod：跳 build）
#   --electron-only / -ElectronOnly  只启动 Electron（假设前后端已就绪）
#   --dry-run / -DryRun        仅打印将执行的命令，不启动任何进程
#   --no-log / -NoLog          关闭会话日志落盘
#
# 监控台（2026-09-04 与 Windows 版对称改造）：本就是单终端运行，此版把三端输出
# 逐行加彩色前缀（backend 青 / vite 绿 / electron 黄）合流，不再裸交错；同时 tee
# 到 logs/console_<mode>_<时间戳>.log。按键聚焦视图（1/2/3/0/s/q）为 Windows 版
# 专有功能，bash 版以 Ctrl+C（trap 兜底清理）停止全部。
#
# 与 Windows 版行为契约一致：
#   - 端口写 data/port.txt 与 data/frontend_port.txt（vite.config.js / electron/main.cjs 读）
#   - 为 Electron 设 VELLUMA_BACKEND_PORT / VELLUMA_FRONTEND_PORT / VELLUMA_SERVICES_READY
#   - debug 模式脚本侧固定后端端口（VELLUMA_PORT），保证热重载期间端口不漂移
#   - DryRun 不写端口文件（一次试跑就会把运行实例与下次启动的端口协商带偏）
#   - 退出时按进程树清理，再兜底清理端口监听者，避免孤儿进程占用端口
# =============================================================================

MODE="dev"
FORCE=0
SKIP_BACKEND=0
SKIP_FRONTEND=0
ELECTRON_ONLY=0
DRY_RUN=0
NO_LOG=0
NO_DASHBOARD=0
BACKEND_PID=""
VITE_PID=""
ELECTRON_PID=""
DASH_URL=""

usage() {
    sed -n '2,36p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        dev|debug|prod) MODE="$1"; shift ;;
        -m|--mode|-Mode) MODE="${2:-}"; shift 2 ;;
        --force|-Force) FORCE=1; shift ;;
        --skip-backend|-SkipBackend) SKIP_BACKEND=1; shift ;;
        --skip-frontend|-SkipFrontend) SKIP_FRONTEND=1; shift ;;
        --electron-only|-ElectronOnly) ELECTRON_ONLY=1; shift ;;
        --dry-run|-DryRun) DRY_RUN=1; shift ;;
        --no-log|-NoLog) NO_LOG=1; shift ;;
        --no-dashboard|-NoDashboard) NO_DASHBOARD=1; shift ;;
        -h|--help) usage; exit 0 ;;
        *) echo "未知参数: $1"; usage; exit 1 ;;
    esac
done

case "$MODE" in
    dev|debug|prod) ;;
    *) echo "无效模式: $MODE（可选 dev / debug / prod）"; exit 1 ;;
esac

# =============================================================================
# Config
# =============================================================================
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

DEFAULT_BACKEND_PORT=8002
DEFAULT_FRONTEND_PORT=5175   # 起始扫描端口
FRONTEND_PORT_RANGE=100      # 5175~5274
BACKEND_TIMEOUT=60
FRONTEND_TIMEOUT=30
HEALTH_CHECK_INTERVAL=0.5
PYTHON_MODULE="backend.main"
PORT_FILE="$PROJECT_ROOT/data/port.txt"
FRONTEND_PORT_FILE="$PROJECT_ROOT/data/frontend_port.txt"
FRONTEND_DIR="$PROJECT_ROOT/frontend"

FRONTEND_PORT=""             # 实际端口（运行时由 resolve_frontend_port 填充）
CHILD_PIDS=()
CLEANUP_DONE=0
CONSOLE_LOG=""               # 会话日志路径（main 里初始化；空 = 不落盘）

# =============================================================================
# 日志（一律走 stderr：端口协商等函数经 $() 捕获返回值，stdout 不能混入日志）
# =============================================================================
CYAN='\033[36m'; GREEN='\033[32m'; RED='\033[31m'; GRAY='\033[90m'; YELLOW='\033[33m'; NC='\033[0m'
log_step()    { echo -e "\n${CYAN}[>] $1${NC}" >&2; }
log_ok()      { echo -e "${GREEN}[OK] $1${NC}" >&2; }
log_err()     { echo -e "${RED}[ERR] $1${NC}" >&2; }
log_info()    { echo -e "${GRAY}[*] $1${NC}" >&2; }
log_wait()    { echo -ne "${YELLOW}[...] $1${GRAY}" >&2; }
die()         { echo "" >&2; log_err "$1"; exit 1; }

# =============================================================================
# 监控台：三端输出逐行彩色前缀合流 + tee 会话日志
# =============================================================================
# 用法：cmd > >(prefix_stream backend 36) 2>&1（36=青 32=绿 33=黄）
# 屏幕行带 ANSI 色；同时写 logs/dev_<label>.log（"HH:mm:ss 原始行"，网页监控台的
# 数据源，与 Windows 读线泵同格式——改格式须同步 dev_dashboard.py 的 LINE_RE）
prefix_stream() {
    local label="$1" color="$2" ts line
    local devfile="$PROJECT_ROOT/logs/dev_${label}.log"
    while IFS= read -r line; do
        ts="$(date +%H:%M:%S)"
        printf '\033[0;%sm%s %-8s\033[0m│ %s\n' "$color" "$ts" "$label" "$line"
        printf '%s %s\n' "$ts" "$line" >> "$devfile"
        if [[ -n "$CONSOLE_LOG" ]]; then
            printf '%s [%s] %s\n' "$ts" "$label" "$line" >> "$CONSOLE_LOG"
        fi
    done
}

# =============================================================================
# 端口与进程工具
# =============================================================================
port_open() {
    # TCP 探测：优先 nc（macOS 内置），回退 bash /dev/tcp
    local port="$1"
    if command -v nc >/dev/null 2>&1; then
        nc -z 127.0.0.1 "$port" >/dev/null 2>&1
    else
        (exec 3<>"/dev/tcp/127.0.0.1/$port") >/dev/null 2>&1
    fi
}

read_port_file() {
    # 读端口文件；不存在/非法时返回回退值
    local file="$1" fallback="$2" port
    if [[ -f "$file" ]]; then
        port=$(tr -d ' \t\r\n' < "$file" 2>/dev/null || true)
        if [[ "$port" =~ ^[0-9]+$ ]] && [[ "$port" -gt 0 ]]; then
            echo "$port"; return 0
        fi
    fi
    echo "$fallback"
}

write_port_file() {
    # 写端口文件（供 vite.config.js 代理与 electron/main.cjs 读取）
    local file="$1" port="$2"
    mkdir -p "$(dirname "$file")"
    printf '%s' "$port" > "$file" || log_err "Failed to write port file: $file"
}

find_free_frontend_port() {
    # 扫描 5175~5274 找第一个空闲端口（避免与其它项目的 Vite 冲突）
    local offset candidate
    for ((offset = 0; offset < FRONTEND_PORT_RANGE; offset++)); do
        candidate=$((DEFAULT_FRONTEND_PORT + offset))
        if ! port_open "$candidate"; then echo "$candidate"; return 0; fi
    done
    die "No free frontend port in range $DEFAULT_FRONTEND_PORT..$((DEFAULT_FRONTEND_PORT + FRONTEND_PORT_RANGE - 1))"
}

find_free_backend_port() {
    # 与 backend/core/config.py 的 DEFAULT_PORT..MAX_PORT（8002~8100）对齐
    local port
    for ((port = DEFAULT_BACKEND_PORT; port <= 8100; port++)); do
        if ! port_open "$port"; then echo "$port"; return 0; fi
    done
    die "No free backend port in range $DEFAULT_BACKEND_PORT..8100"
}

resolve_backend_port() {
    # debug 热重载模式下协商后端端口，优先级：
    # 1. 环境变量 VELLUMA_PORT（用户强制指定）
    # 2. 已记录端口（data/port.txt）且该端口空闲 → 复用
    # 3. 扫描空闲端口（8002 起）
    # 固定端口是热重载的前提：reload 重启 worker 时端口不能漂移，否则前端断连
    local env_port="$VELLUMA_PORT" recorded free_port
    if [[ -n "$env_port" && "$env_port" =~ ^[0-9]+$ && "$env_port" -gt 0 ]]; then
        write_port_file "$PORT_FILE" "$env_port"
        log_info "Backend port from env: $env_port"
        echo "$env_port"; return 0
    fi
    recorded=$(read_port_file "$PORT_FILE" "")
    if [[ -n "$recorded" ]] && ! port_open "$recorded"; then
        write_port_file "$PORT_FILE" "$recorded"
        echo "$recorded"; return 0
    fi
    free_port=$(find_free_backend_port)
    write_port_file "$PORT_FILE" "$free_port"
    if [[ "$free_port" -ne "$DEFAULT_BACKEND_PORT" ]]; then
        log_info "Default backend port $DEFAULT_BACKEND_PORT busy, using $free_port"
    fi
    echo "$free_port"
}

resolve_frontend_port() {
    # 协商前端端口：环境变量 → 已记录且空闲 → 扫描（5175 起）
    local env_port="$VELLUMA_FRONTEND_PORT" recorded free_port
    if [[ -n "$env_port" && "$env_port" =~ ^[0-9]+$ && "$env_port" -gt 0 ]]; then
        write_port_file "$FRONTEND_PORT_FILE" "$env_port"
        log_info "Frontend port from env: $env_port"
        echo "$env_port"; return 0
    fi
    recorded=$(read_port_file "$FRONTEND_PORT_FILE" "")
    if [[ -n "$recorded" ]] && ! port_open "$recorded"; then
        write_port_file "$FRONTEND_PORT_FILE" "$recorded"
        echo "$recorded"; return 0
    fi
    free_port=$(find_free_frontend_port)
    write_port_file "$FRONTEND_PORT_FILE" "$free_port"
    if [[ "$free_port" -ne "$DEFAULT_FRONTEND_PORT" ]]; then
        log_info "Default port $DEFAULT_FRONTEND_PORT busy, using $free_port"
    fi
    echo "$free_port"
}

kill_port_listener() {
    # 杀掉端口监听者（兜底清理；依赖 lsof，macOS 内置）
    local port="$1" name="$2" pid
    command -v lsof >/dev/null 2>&1 || return 1
    pid=$(lsof -ti tcp:"$port" -sTCP:LISTEN 2>/dev/null | head -1)
    if [[ -n "$pid" ]]; then
        log_info "Stopping $name on port $port (PID: $pid)..."
        kill -9 "$pid" 2>/dev/null || true
        sleep 2
        log_ok "$name stopped"
        return 0
    fi
    return 1
}

kill_tree() {
    # 递归终止进程树：先杀子进程再杀父进程
    # 用途：uvicorn --reload 的 reloader 父进程会 spawn worker 子进程，
    #       仅杀父进程会留下 worker 孤儿继续占用端口
    local pid="$1" child
    [[ -z "$pid" ]] && return 0
    for child in $(pgrep -P "$pid" 2>/dev/null || true); do
        kill_tree "$child"
    done
    kill -TERM "$pid" 2>/dev/null || true
}

wait_for_service() {
    # 轮询端口直到就绪或超时
    local port="$1" name="$2" timeout="${3:-30}"
    local start now dots=0
    start=$(date +%s)
    while :; do
        if port_open "$port"; then
            echo -e " ${GREEN}Ready!${NC}" >&2
            return 0
        fi
        now=$(date +%s)
        (( now - start >= timeout )) && break
        sleep "$HEALTH_CHECK_INTERVAL"
        printf "." >&2
        dots=$((dots + 1))
        if (( dots % 10 == 0 )); then
            printf " (%ss)" "$(( now - start ))" >&2
        fi
    done
    echo ""
    die "$name timeout on port $port (${timeout}s)"
}

# =============================================================================
# 清理（EXIT 兜底）
# =============================================================================
cleanup() {
    [[ "$CLEANUP_DONE" = "1" ]] && return
    CLEANUP_DONE=1
    echo ""
    log_step "Cleaning up..."
    local pid
    # DryRun 只做演示：绝不杀树/杀端口，否则一次试跑会清掉正在运行的服务
    if [[ "$DRY_RUN" = "1" ]]; then
        log_ok "Cleanup skipped (dry-run)"
        return
    fi
    for pid in "${CHILD_PIDS[@]}"; do
        [[ -z "$pid" ]] && continue
        if kill -0 "$pid" 2>/dev/null; then
            kill_tree "$pid"
            log_info "Stopped PID $pid"
        fi
    done
    local ports=() p fp
    p=$(read_port_file "$PORT_FILE" "$DEFAULT_BACKEND_PORT")
    [[ -n "$p" ]] && ports+=("$p")
    # 生产模式下没有 Vite 进程，不清理前端端口（避免误杀他人占用的端口）
    if [[ "$MODE" != "prod" ]]; then
        fp="$FRONTEND_PORT"
        [[ -z "$fp" ]] && fp=$(read_port_file "$FRONTEND_PORT_FILE" "")
        [[ -n "$fp" && "$fp" -gt 0 ]] && ports+=("$fp")
    fi
    for p in "${ports[@]}"; do
        kill_port_listener "$p" "service" >/dev/null
    done
    log_ok "Cleanup done"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

# =============================================================================
# 服务启动
# =============================================================================
find_python() {
    local path
    for path in ".venv/bin/python" "venv/bin/python"; do
        if [[ -x "$PROJECT_ROOT/$path" ]]; then
            echo "$PROJECT_ROOT/$path"; return 0
        fi
    done
    die "Python venv not found. Please ensure .venv or venv exists (python3 -m venv .venv)."
}

start_backend() {
    local backend_port use_reload=0 python_path
    backend_port=$(read_port_file "$PORT_FILE" "$DEFAULT_BACKEND_PORT")
    if [[ "$SKIP_BACKEND" = "1" || "$ELECTRON_ONLY" = "1" ]]; then
        if port_open "$backend_port"; then
            log_ok "Backend already running on port $backend_port"
            return 0
        fi
        die "Backend not running but skip flag set"
    fi

    # debug 模式启用 uvicorn --reload 后端热重载：保存 Python 文件即自动重启
    # 热重载的关键约束（与 Windows 版一致）：
    #   1. --reload 必须传 import path（backend.main:app），不能走 main.py 的 __main__
    #   2. reload 重启 worker 时端口必须固定 → 脚本侧协商端口并设 VELLUMA_PORT
    #   3. __main__ 不执行 → save_port 不会被调用 → port.txt 必须由脚本侧写好
    [[ "$MODE" = "debug" ]] && use_reload=1
    if [[ "$use_reload" = "1" ]]; then
        # die 发生在 $() 子 shell 内：|| exit 1 让父进程同步失败并触发 EXIT 清理
        backend_port=$(resolve_backend_port) || exit 1
        export VELLUMA_PORT="$backend_port"
        log_info "Debug mode: backend hot-reload enabled (VELLUMA_PORT=$backend_port)"
    fi

    log_step "Starting Backend..."

    if port_open "$backend_port"; then
        if [[ "$FORCE" = "1" ]]; then
            kill_port_listener "$backend_port" "backend" >/dev/null
        else
            if [[ "$use_reload" = "1" ]]; then
                log_ok "Backend already running on port $backend_port (reload disabled for existing process)"
            else
                log_ok "Backend already running on port $backend_port"
            fi
            return 0
        fi
    fi

    python_path=$(find_python) || exit 1
    log_info "Using Python: $python_path"

    export PYTHONUNBUFFERED=1

    if [[ "$DRY_RUN" = "1" ]]; then
        if [[ "$use_reload" = "1" ]]; then
            log_info "[DryRun] Would start (reload): $python_path -m uvicorn backend.main:app --host 127.0.0.1 --port $backend_port --reload --reload-dir backend --app-dir ."
        else
            log_info "[DryRun] Would start: $python_path -m $PYTHON_MODULE"
        fi
        return 0
    fi

    if [[ "$use_reload" = "1" ]]; then
        # --app-dir .：让 backend.main 可作为顶层模块 import（cwd 已是项目根）
        # --reload-dir backend：仅监听 backend/ 下的 .py 变更，避免误重启
        # 输出重定向进 [backend] 前缀合流（监控台）；worker 重启继承同一管道，日志不断流
        # stdin 接 /dev/null：切断终端继承，vite/npm 类子进程的 TTY readline 不会因
        # 终端侧变动 EPIPE 崩溃（与 Windows 版 stdin 关闭策略对称）
        (cd "$PROJECT_ROOT" && exec "$python_path" -m uvicorn backend.main:app \
            --host 127.0.0.1 --port "$backend_port" \
            --reload --reload-dir "$PROJECT_ROOT/backend" --app-dir "$PROJECT_ROOT") \
            < /dev/null > >(prefix_stream backend 36) 2>&1 &
        CHILD_PIDS+=($!)
        BACKEND_PID=$!
        log_wait "Waiting for backend (reload)..."
        wait_for_service "$backend_port" "Backend (reload)" "$BACKEND_TIMEOUT"
        log_ok "Backend ready at http://127.0.0.1:$backend_port (hot-reload ON)"
        return 0
    fi

    # dev/prod 模式：走 main.py 的 __main__（内部 find_available_port + save_port）
    # 后台运行输出进 [backend] 前缀合流（监控台），uvicorn 日志实时可见
    (cd "$PROJECT_ROOT" && exec "$python_path" -m "$PYTHON_MODULE") \
        < /dev/null > >(prefix_stream backend 36) 2>&1 &
    CHILD_PIDS+=($!)
    BACKEND_PID=$!

    # 轮询端口文件等待后端启动
    log_wait "Waiting for backend..."
    local start now actual_port=""
    start=$(date +%s)
    while :; do
        sleep "$HEALTH_CHECK_INTERVAL"
        actual_port=$(read_port_file "$PORT_FILE" "")
        if [[ -n "$actual_port" ]] && port_open "$actual_port"; then
            break
        fi
        actual_port=""
        now=$(date +%s)
        (( now - start >= BACKEND_TIMEOUT )) && break
    done
    [[ -z "$actual_port" ]] && die "Backend failed to start within ${BACKEND_TIMEOUT}s"
    log_ok "Backend ready at http://127.0.0.1:$actual_port"
}

start_frontend_build() {
    # 生产模式专用：npm run build 生成 dist/ 供 Electron loadFile 载入
    if [[ "$SKIP_FRONTEND" = "1" ]]; then
        log_info "SkipFrontend set, assuming dist/ already built"
        return 0
    fi

    log_step "Building frontend (npm run build)..."

    if [[ ! -d "$FRONTEND_DIR/node_modules" ]]; then
        die "node_modules not found. Please run: cd frontend && npm install"
    fi

    if [[ "$DRY_RUN" = "1" ]]; then
        log_info "[DryRun] Would run: npm run build (cwd: $FRONTEND_DIR)"
        return 0
    fi

    # 前台同步执行，失败即中止
    (cd "$FRONTEND_DIR" && npm run build) || die "npm run build failed"

    if [[ ! -f "$FRONTEND_DIR/dist/index.html" ]]; then
        die "Build completed but dist/index.html not found at $FRONTEND_DIR/dist/index.html"
    fi

    log_ok "Frontend built to dist/"
}

start_frontend() {
    # 开发/调试模式：启动 Vite dev server（端口动态协商）
    local frontend_port
    frontend_port=$(resolve_frontend_port) || exit 1
    FRONTEND_PORT="$frontend_port"

    if [[ "$SKIP_FRONTEND" = "1" || "$ELECTRON_ONLY" = "1" ]]; then
        if port_open "$frontend_port"; then
            log_ok "Frontend already running on port $frontend_port"
            return 0
        fi
        die "Frontend not running but skip flag set"
    fi

    log_step "Starting Frontend (port $frontend_port)..."

    if [[ ! -d "$FRONTEND_DIR/node_modules" ]]; then
        die "node_modules not found. Please run: cd frontend && npm install"
    fi

    if port_open "$frontend_port"; then
        if [[ "$FORCE" = "1" ]]; then
            kill_port_listener "$frontend_port" "frontend" >/dev/null
        else
            log_ok "Frontend already running on port $frontend_port"
            return 0
        fi
    fi

    log_info "Starting Vite dev server..."

    # 设置环境变量供 vite.config.js 读取（双保险：env + frontend_port.txt）
    export VELLUMA_FRONTEND_PORT="$frontend_port"

    if [[ "$DRY_RUN" = "1" ]]; then
        log_info "[DryRun] Would start: npm run dev (cwd: $FRONTEND_DIR, port $frontend_port)"
        return 0
    fi

    (cd "$FRONTEND_DIR" && exec npm run dev) < /dev/null > >(prefix_stream vite 32) 2>&1 &
    CHILD_PIDS+=($!)
    VITE_PID=$!
    CHILD_PIDS+=($!)

    log_wait "Waiting for frontend (port $frontend_port)..."
    wait_for_service "$frontend_port" "Frontend" "$FRONTEND_TIMEOUT"
    log_ok "Frontend ready at http://127.0.0.1:$frontend_port"
}

start_electron() {
    local backend_port fe_port
    backend_port=$(read_port_file "$PORT_FILE" "$DEFAULT_BACKEND_PORT")

    # 公共环境变量
    export VELLUMA_BACKEND_PORT="$backend_port"
    # 生产模式不启动 Vite，FRONTEND_PORT 可能为空——读端口文件兜底，再不行留空
    fe_port="$FRONTEND_PORT"
    if [[ -z "$fe_port" && "$MODE" = "prod" ]]; then
        fe_port=$(read_port_file "$FRONTEND_PORT_FILE" "")
    fi
    if [[ -n "$fe_port" ]]; then
        export VELLUMA_FRONTEND_PORT="$fe_port"
    else
        unset VELLUMA_FRONTEND_PORT 2>/dev/null || true
    fi
    export VELLUMA_SERVICES_READY=1

    # 模式差异：生产模式设 NODE_ENV=production，让 main.cjs 走 loadFile('../dist/index.html')
    # 开发/调试模式保持 NODE_ENV 不设（main.cjs 的 isDev = true，走 loadURL + openDevTools）
    if [[ "$MODE" = "prod" ]]; then
        export NODE_ENV="production"
        log_info "NODE_ENV=production (Electron will load dist/index.html)"
    else
        unset NODE_ENV 2>/dev/null || true
        log_info "NODE_ENV unset (Electron will load Vite dev server, DevTools auto-open)"
    fi

    log_step "Starting Electron..."

    if [[ "$DRY_RUN" = "1" ]]; then
        log_info "[DryRun] Would run: npm run electron:dev (cwd: $FRONTEND_DIR)"
        return 0
    fi

    # 启动摘要（Electron 前台阻塞运行，摘要须在其启动前打印）
    echo ""
    echo -e "${GREEN}============================================================${NC}" >&2
    log_ok "All services started!"
    echo "" >&2
    echo -e "${GRAY}  Backend:  http://127.0.0.1:$backend_port${NC}" >&2
    echo -e "${GRAY}  API Docs: http://127.0.0.1:$backend_port/docs${NC}" >&2
    if [[ "$MODE" = "prod" ]]; then
        echo -e "${GRAY}  Frontend: dist/index.html (built)${NC}" >&2
    else
        echo -e "${GRAY}  Frontend: http://127.0.0.1:$FRONTEND_PORT (Vite dev)${NC}" >&2
    fi
    echo "" >&2
    echo -e "${YELLOW}  Electron is running. Close window to stop all services.${NC}" >&2
    echo -e "${GREEN}============================================================${NC}" >&2

    # 后台运行以便拿到 pid（写状态 JSON 供网页监控台展示），摘要随后打印
    # 注意：electron:dev = "npm run build && electron ."
    #   - 生产模式：build 已由 start_frontend_build 完成，这里再 build 一次是幂等的
    #   - 开发/调试模式：build 产物不会被 main.cjs 使用（走 loadURL），仅浪费数秒，可接受
    (cd "$FRONTEND_DIR" && exec npm run electron:dev) < /dev/null > >(prefix_stream electron 33) 2>&1 &
    ELECTRON_PID=$!
    CHILD_PIDS+=("$ELECTRON_PID")
}

# =============================================================================
# 网页监控台（scripts/dev_dashboard.py，纯标准库）：读会话日志 + 状态 JSON
# =============================================================================
write_dev_status() {
    # 状态 JSON 与 Windows 版 Write-DevStatus 同构（网页监控台两端共用）
    [[ "$DRY_RUN" = "1" ]] && return 0
    mkdir -p "$PROJECT_ROOT/data"
    local bp vp ep
    [[ -n "$BACKEND_PID" ]] && bp="$BACKEND_PID" || bp=null
    [[ -n "$VITE_PID" ]] && vp="$VITE_PID" || vp=null
    [[ -n "$ELECTRON_PID" ]] && ep="$ELECTRON_PID" || ep=null
    local bport vport
    bport=$(read_port_file "$PORT_FILE" "$DEFAULT_BACKEND_PORT")
    vport="$FRONTEND_PORT"
    [[ -z "$vport" ]] && vport=null
    cat > "$PROJECT_ROOT/data/dev_status.json" << EOF
{
  "mode": "$MODE",
  "started_at": "$(date '+%Y-%m-%d %H:%M:%S')",
  "log_dir": "$PROJECT_ROOT/logs",
  "services": {
    "backend": { "pid": $bp, "port": $bport, "state": "running" },
    "vite": { "pid": $vp, "port": $vport, "state": "running" },
    "electron": { "pid": $ep, "port": null, "state": "running" }
  }
}
EOF
}

start_dashboard() {
    # 失败不阻塞启动（监控台降级为纯终端合流）
    [[ "$NO_DASHBOARD" = "1" || "$DRY_RUN" = "1" || -z "$CONSOLE_LOG" ]] && return 0
    local py="" p
    if [[ -x "$PROJECT_ROOT/.venv/bin/python3" ]]; then
        py="$PROJECT_ROOT/.venv/bin/python3"
    elif [[ -x "$PROJECT_ROOT/venv/bin/python3" ]]; then
        py="$PROJECT_ROOT/venv/bin/python3"
    elif command -v python3 >/dev/null 2>&1; then
        py="python3"
    fi
    [[ -z "$py" || ! -f "$PROJECT_ROOT/scripts/dev_dashboard.py" ]] && return 0
    for p in $(seq 8180 8189); do
        if ! port_open "$p"; then
            mkdir -p "$PROJECT_ROOT/logs"
            ("$py" "$PROJECT_ROOT/scripts/dev_dashboard.py" \
                --dir "$PROJECT_ROOT/logs" --status "$PROJECT_ROOT/data/dev_status.json" \
                --port "$p") > "$PROJECT_ROOT/logs/dashboard.log" 2>&1 &
            CHILD_PIDS+=($!)
            DASH_URL="http://127.0.0.1:$p"
            log_ok "Dashboard: $DASH_URL（已自动打开浏览器）"
            open "$DASH_URL" >/dev/null 2>&1 || true
            return 0
        fi
    done
    log_info "Dashboard: no free port in 8180..8189, skipped"
}

# =============================================================================
# Main
# =============================================================================
show_banner() {
    # 全部脚本自身输出走 stderr（与日志一致），stdout 留给子进程，避免管道下交错
    echo -e "\n${CYAN}============================================================" >&2
    echo -e "     Velluma AI Novel Writing Assistant" >&2
    echo -e "     Mode: $(echo "$MODE" | tr '[:lower:]' '[:upper:]')  ($OSTYPE)" >&2
    echo -e "============================================================${NC}" >&2
    echo "" >&2
}

main() {
    show_banner

    log_info "Project root: $PROJECT_ROOT"

    # dev_*.log（网页监控台数据源）恒写；合流日志 CONSOLE_LOG 受 --no-log 门控
    mkdir -p "$PROJECT_ROOT/logs"
    if [[ "$DRY_RUN" != "1" && "$NO_LOG" != "1" ]]; then
        CONSOLE_LOG="$PROJECT_ROOT/logs/console_${MODE}_$(date +%Y%m%d_%H%M%S).log"
        log_info "Console log: $CONSOLE_LOG"
    fi

    if [[ "$DRY_RUN" = "1" ]]; then
        log_info "DryRun mode: no processes will be started"
    fi
    if [[ "$FORCE" = "1" ]]; then
        log_info "Force mode: will clean port conflicts"
    fi

    start_backend

    # 按模式分流前端阶段
    if [[ "$MODE" = "prod" ]]; then
        start_frontend_build
    else
        start_frontend
    fi

    start_electron

    # Electron 已后台化：落状态 JSON + 拉起网页监控台（两者失败均不阻塞）
    write_dev_status
    start_dashboard

    if [[ "$DRY_RUN" = "1" ]]; then
        log_info "DryRun complete, skipping wait"
        return 0
    fi

    # 等待 Electron 退出（关窗 = 全部收摊，走 EXIT 清理）
    wait "$ELECTRON_PID" || true
    # bash 不等进程替换排空：稍候让 prefix_stream 冲掉管道尾行，再打退出日志
    sleep 0.3
    echo ""
    log_info "Electron exited"
}

main
