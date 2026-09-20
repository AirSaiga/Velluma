#!/bin/bash
# =============================================================================
# Velluma 正式生产环境·macOS 一键三端（后端 + 预构建前端 + Electron 生产壳）
# =============================================================================
# scripts/macos/prod/ 四件套的编排核心（与 scripts/macos/dev/start-all.sh 完全独立、
# 互不复用）。本脚本位于 scripts/macos/prod/ 下，项目根 = 脚本目录的曾祖父目录。
#   - 后端：python -m backend.main（无热重载，走 main.py __main__ 的内部端口扫描
#     并自写 data/port.txt）；
#   - 前端：npm run build 预构建 dist/（不启动 Vite dev server）；
#   - Electron：NODE_ENV=production 走 loadFile('../dist/index.html')，不开 DevTools。
# flags:
#   --force / -Force           端口被占用时强制清理后重启
#   --skip-backend / -SkipBackend    跳过后端（假设已运行）
#   --skip-frontend / -SkipFrontend  跳过构建（断言 dist 已在）
#   --electron-only / -ElectronOnly  只启动 Electron（假设前后端已就绪）
#   --dry-run / -DryRun        仅打印将执行的命令，不启动任何进程
#   --no-log / -NoLog          关闭会话日志落盘
#
# 监控台：输出逐行彩色前缀合流 + tee 到 logs/console_prod_<时间戳>.log；
# Ctrl+C（trap 兜底清理）停止全部。网页监控台已隔离到 scripts/monitor/。
#
# 行为契约（与 Windows 双端、monitor 监督者一致，check_launcher_contract.py 对拍）：
#   - 端口写 data/port.txt（vite.config.js / electron/main.cjs 读）
#   - 为 Electron 设 VELLUMA_BACKEND_PORT / VELLUMA_SERVICES_READY / NODE_ENV=production
#   - DryRun 不写端口文件、不杀任何进程
#   - Electron 一律 electron:nobuild（= 直接 "electron ."；loadURL/loadFile 由 NODE_ENV
#     决定，dist 已构建再 build 一次纯属浪费）
#   - 每次启动重建 logs/dev_*.log
#   - 退出时按进程树清理，再兜底清理端口监听者，避免孤儿进程占用端口
# =============================================================================

FORCE=0
SKIP_BACKEND=0
SKIP_FRONTEND=0
ELECTRON_ONLY=0
DRY_RUN=0
NO_LOG=0
BACKEND_PID=""
ELECTRON_PID=""

usage() {
    # 头部注释块即用法：从源码抽取到最后一行注释为止（不写死行号——改头注释不用同步）
    awk 'NR>1 && /^#/ { sub(/^# ?/, ""); print; next } NR>1 { exit }' "${BASH_SOURCE[0]}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --force|-Force) FORCE=1; shift ;;
        --skip-backend|-SkipBackend) SKIP_BACKEND=1; shift ;;
        --skip-frontend|-SkipFrontend) SKIP_FRONTEND=1; shift ;;
        --electron-only|-ElectronOnly) ELECTRON_ONLY=1; shift ;;
        --dry-run|-DryRun) DRY_RUN=1; shift ;;
        --no-log|-NoLog) NO_LOG=1; shift ;;
        -h|--help) usage; exit 0 ;;
        *) echo "未知参数: $1"; usage; exit 1 ;;
    esac
done

# =============================================================================
# Config
# =============================================================================
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# scripts/macos/prod/ → 项目根要向上三层
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

DEFAULT_BACKEND_PORT=8002
BACKEND_PORT_MAX=8100        # 与 backend/core/config.py、stop-velluma 孤儿清扫段对齐
BACKEND_TIMEOUT=60
HEALTH_CHECK_INTERVAL=0.5
PYTHON_MODULE="backend.main"
PORT_FILE="$PROJECT_ROOT/data/port.txt"
FRONTEND_PORT_FILE="$PROJECT_ROOT/data/frontend_port.txt"
FRONTEND_DIR="$PROJECT_ROOT/frontend"

CHILD_PIDS=()
CLEANUP_DONE=0
CONSOLE_LOG=""               # 会话日志路径（main 里初始化；空 = 不落盘）
SYS_LOG=""                   # logs/dev_sys.log（停脚本/监控台 sys 车道；空 = 不写）

# =============================================================================
# 日志（一律走 stderr：端口协商等函数经 $() 捕获返回值，stdout 不能混入日志）
# 叙事同时落 logs/dev_sys.log（网页监控台的 sys 车道，与 Windows Write-SysLog 对称）
# =============================================================================
CYAN='\033[36m'; GREEN='\033[32m'; RED='\033[31m'; GRAY='\033[90m'; YELLOW='\033[33m'; NC='\033[0m'
log_sys()     { [[ -z "$SYS_LOG" ]] && return 0; printf '%s %s\n' "$(date +%H:%M:%S)" "$1" >> "$SYS_LOG" 2>/dev/null || true; }
log_step()    { echo -e "\n${CYAN}[>] $1${NC}" >&2; log_sys "[>] $1"; }
log_ok()      { echo -e "${GREEN}[OK] $1${NC}" >&2; log_sys "[OK] $1"; }
log_err()     { echo -e "${RED}[ERR] $1${NC}" >&2; log_sys "[ERR] $1"; }
log_info()    { echo -e "${GRAY}[*] $1${NC}" >&2; log_sys "[*] $1"; }
log_wait()    { echo -ne "${YELLOW}[...] $1${GRAY}" >&2; log_sys "[..] $1"; }
die()         { echo "" >&2; log_err "$1"; exit 1; }

# =============================================================================
# 监控台：三端输出逐行彩色前缀合流 + tee 会话日志
# =============================================================================
# 用法：cmd > >(prefix_stream backend 36) 2>&1（36=青 32=绿 33=黄）
# 屏幕行带 ANSI 色；同时写 logs/dev_<label>.log（"HH:mm:ss 原始行"，网页监控台的
# 数据源，与 Windows 读线泵同格式——改格式须同步 monitor/dev_dashboard.py 的 LINE_RE）
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

# prod 无脚本侧端口协商：后端走 main.py __main__ 的内部扫描并自写 port.txt，
# 前端无 dev server。端口段常量（8002~8100）与全端契约一致，
# check_launcher_contract.py 对拍。

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
    local ports=() p
    p=$(read_port_file "$PORT_FILE" "$DEFAULT_BACKEND_PORT")
    [[ -n "$p" ]] && ports+=("$p")
    # prod 无 Vite，不清理前端端口（历史 frontend_port.txt 是 dev 会话留的，别误杀他人占用者）
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
    local backend_port python_path
    backend_port=$(read_port_file "$PORT_FILE" "$DEFAULT_BACKEND_PORT")
    if [[ "$SKIP_BACKEND" = "1" || "$ELECTRON_ONLY" = "1" ]]; then
        if port_open "$backend_port"; then
            log_ok "Backend already running on port $backend_port"
            return 0
        fi
        die "Backend not running but skip flag set"
    fi

    # prod 环境：走 main.py 的 __main__（内部 find_available_port + save_port），无热重载
    #——uvicorn --reload 属于 dev 环境的形态（scripts/macos/dev/start-all.sh）
    log_step "Starting Backend..."

    if port_open "$backend_port"; then
        if [[ "$FORCE" = "1" ]]; then
            kill_port_listener "$backend_port" "backend" >/dev/null
        else
            log_ok "Backend already running on port $backend_port"
            return 0
        fi
    fi

    python_path=$(find_python) || exit 1
    log_info "Using Python: $python_path"

    export PYTHONUNBUFFERED=1

    if [[ "$DRY_RUN" = "1" ]]; then
        log_info "[DryRun] Would start: $python_path -m $PYTHON_MODULE"
        return 0
    fi

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
    local dist_index="$FRONTEND_DIR/dist/index.html"
    if [[ "$SKIP_FRONTEND" = "1" ]]; then
        # 跳过构建 = 断言 dist 已在（Electron 随后 loadFile 它）——缺了当场说清楚，别等白屏
        [[ -f "$dist_index" ]] || die "SkipFrontend set but dist/index.html missing（先跑一次 npm run build 或去掉 --skip-frontend）"
        log_info "SkipFrontend set, using existing dist/"
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

    if [[ ! -f "$dist_index" ]]; then
        die "Build completed but dist/index.html not found at $dist_index"
    fi

    log_ok "Frontend built to dist/"
}

start_electron() {
    local backend_port fe_port
    backend_port=$(read_port_file "$PORT_FILE" "$DEFAULT_BACKEND_PORT")

    # 公共环境变量；prod 不启 Vite，历史 frontend_port.txt 仅作环境变量兜底
    export VELLUMA_BACKEND_PORT="$backend_port"
    fe_port=$(read_port_file "$FRONTEND_PORT_FILE" "")
    if [[ -n "$fe_port" ]]; then
        export VELLUMA_FRONTEND_PORT="$fe_port"
    else
        unset VELLUMA_FRONTEND_PORT 2>/dev/null || true
    fi
    export VELLUMA_SERVICES_READY=1

    # prod：NODE_ENV=production，让 main.cjs 走 loadFile('../dist/index.html') 分支
    export NODE_ENV="production"
    log_info "NODE_ENV=production (Electron will load dist/index.html)"

    log_step "Starting Electron..."

    if [[ "$DRY_RUN" = "1" ]]; then
        log_info "[DryRun] Would run: npm run electron:nobuild (cwd: $FRONTEND_DIR)"
        return 0
    fi

    # 启动摘要（Electron 前台阻塞运行，摘要须在其启动前打印）
    echo ""
    echo -e "${GREEN}============================================================${NC}" >&2
    log_ok "All services started!"
    echo "" >&2
    echo -e "${GRAY}  Backend:  http://127.0.0.1:$backend_port${NC}" >&2
    echo -e "${GRAY}  API Docs: http://127.0.0.1:$backend_port/docs${NC}" >&2
    echo -e "${GRAY}  Frontend: dist/index.html (built)${NC}" >&2
    echo "" >&2
    echo -e "${YELLOW}  Electron is running. Close window to stop all services.${NC}" >&2
    echo -e "${GREEN}============================================================${NC}" >&2

    # 后台运行以便拿到 pid（写状态 JSON 供停脚本/监控台消费），摘要随后打印
    # electron:nobuild（= 直接 "electron ."）：dist 已由 start_frontend_build 构建并
    # 校验，再 build 一次（electron:* 系脚本）纯属浪费；loadURL/loadFile 由 NODE_ENV 决定。
    (cd "$FRONTEND_DIR" && exec npm run electron:nobuild) < /dev/null > >(prefix_stream electron 33) 2>&1 &
    ELECTRON_PID=$!
    CHILD_PIDS+=("$ELECTRON_PID")
}

# =============================================================================
# 状态 JSON（scripts/monitor/ 的监督者/网页监控台与停脚本消费）
# =============================================================================
write_dev_status() {
    # 状态 JSON 与 Windows 版 Write-DevStatus 同构（停脚本/监控台消费）
    # prod 无 Vite——vite 键恒空（schema 与 dev/监督者一致，消费方按空值跳过）
    [[ "$DRY_RUN" = "1" ]] && return 0
    mkdir -p "$PROJECT_ROOT/data"
    # 如实报状态：pid 在跑=running，pid 已死=exited，无 pid=-
    svc_state() {
        [[ -z "$1" ]] && { echo '"-"'; return; }
        if kill -0 "$1" 2>/dev/null; then echo '"running"'; else echo '"exited"'; fi
    }
    local bp ep bstate estate bport
    [[ -n "$BACKEND_PID" ]] && bp="$BACKEND_PID" || bp=null
    [[ -n "$ELECTRON_PID" ]] && ep="$ELECTRON_PID" || ep=null
    bstate=$(svc_state "$BACKEND_PID"); estate=$(svc_state "$ELECTRON_PID")
    bport=$(read_port_file "$PORT_FILE" "$DEFAULT_BACKEND_PORT")
    cat > "$PROJECT_ROOT/data/dev_status.json" << EOF
{
  "mode": "prod",
  "started_at": "$(date '+%Y-%m-%d %H:%M:%S')",
  "log_dir": "$PROJECT_ROOT/logs",
  "services": {
    "backend": { "pid": $bp, "port": $bport, "state": $bstate },
    "vite": { "pid": null, "port": null, "state": "-" },
    "electron": { "pid": $ep, "port": null, "state": $estate }
  }
}
EOF
}

# =============================================================================
# Main
# =============================================================================
show_banner() {
    # 全部脚本自身输出走 stderr（与日志一致），stdout 留给子进程，避免管道下交错
    echo -e "\n${CYAN}============================================================" >&2
    echo -e "     Velluma AI Novel Writing Assistant" >&2
    echo -e "     Mode: PROD  ($OSTYPE)" >&2
    echo -e "============================================================${NC}" >&2
    echo "" >&2
}

main() {
    show_banner

    # dev_*.log 恒写；合流日志 CONSOLE_LOG 受 --no-log 门控
    mkdir -p "$PROJECT_ROOT/logs"
    if [[ "$DRY_RUN" != "1" ]]; then
        # 每次启动重建 dev_*.log：与 Windows 读线泵「每次启动重建」同契约。
        SYS_LOG="$PROJECT_ROOT/logs/dev_sys.log"
        local f
        for f in backend electron sys; do : > "$PROJECT_ROOT/logs/dev_$f.log"; done
    fi
    if [[ "$DRY_RUN" != "1" && "$NO_LOG" != "1" ]]; then
        CONSOLE_LOG="$PROJECT_ROOT/logs/console_prod_$(date +%Y%m%d_%H%M%S).log"
        log_info "Console log: $CONSOLE_LOG"
    fi

    log_info "Project root: $PROJECT_ROOT"

    if [[ "$DRY_RUN" = "1" ]]; then
        log_info "DryRun mode: no processes will be started"
    fi
    if [[ "$FORCE" = "1" ]]; then
        log_info "Force mode: will clean port conflicts"
    fi

    start_backend
    start_frontend_build
    start_electron

    # Electron 已后台化：落状态 JSON（失败不阻塞）
    write_dev_status

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
