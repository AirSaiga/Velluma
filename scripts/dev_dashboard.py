# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""==== Velluma 开发监控台（网页版）====

启动脚本的配套观测面板：纯标准库 HTTP 服务（零第三方依赖、零构建），
tail 启动器写下的各服务日志文件（logs/dev_backend.log / dev_vite.log /
dev_electron.log / dev_sys.log，由 start.ps1 的读线泵落盘）+ 状态 JSON，
浏览器打开即三端彩色日志流。由 scripts/windows/start.ps1 / scripts/macos/start.sh
拉起并随其清理，不参与产品运行时，仅本地开发用。

端点：
  GET /    单页面板（内嵌 HTML，无外部资源）
  GET /api/logs?after=<URL编码的JSON，各文件字节偏移>
           → {"offsets": {...}, "lines": [{t,label,text}]}
  GET /api/status
           服务状态（状态 JSON + 端口 TCP 探活 + PID 存活核验）

警示：日志行格式由 start.ps1 的读线泵决定（"HH:mm:ss 原始行"），两端改格式须同步
本文件的 LINE_RE；文件名见 FILES。
"""
import argparse
import ctypes
import json
import os
import re
import signal
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

FILES = {
    "backend": "dev_backend.log",
    "vite": "dev_vite.log",
    "electron": "dev_electron.log",
    "sys": "dev_sys.log",
}
LINE_RE = re.compile(r"^(\d\d:\d\d:\d\d) (.*)$")
LABELS = ["sys", "backend", "vite", "electron"]
STATUS_PATH = ""
LOG_DIR = ""
STARTED = time.time()
DASH_PORT = 0

# ---- 监督者模式（后台模式的关键路径拥有者）----
# 为什么是 python：隐藏窗口的 powershell 主循环在本机环境屡次冻在入场（状态 JSON
# mtime 停在 started_at 即证据），而 python 仪表盘在同环境下多次全存活——进程树
# 主人换成 python。可见终端模式仍走 start.ps1，两路共享同一组日志/状态文件契约。
SUPERVISE = False
MODE = "dev"
ROOT = ""
RESTART_LIMIT = 2
PHASE = "booting"   # booting → backend → vite → electron → ready（网页进度条数据源）
# RLock：后端热重载线程持锁调 spawn_all_single → spawn_service 再拿锁（同线程可重入）
_service_lock = threading.RLock()
_services = {}      # key → {"proc": Popen, "port": int|None, "writer": file}
# 自愈重启计数：必须独立于 _services 生命周期——条目内字段会随「pop 旧条目 → spawn
# 重建（归零）」冲掉，快照浅拷贝上的自增也到不了注册表，写条目内=上限恒失效
_restart_counts = {}
_shutdown = threading.Event()


def _thread_autopsy(args):
    # pythonw 下 sys.stderr 是 None，线程异常会静默蒸发（heartbeat 停了但进程活着，
    # 无任何痕迹）——所有线程异常强制落 dev_sys.log
    try:
        import traceback
        err = "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback))
        write_sys_log("THREAD CRASH in {0}: {1}".format(getattr(args.thread, "name", "?"), err[-1500:]))
    except Exception:
        pass


threading.excepthook = _thread_autopsy


def now_ts():
    return time.strftime("%H:%M:%S")


def write_sys_log(line):
    try:
        with open(os.path.join(LOG_DIR, FILES["sys"]), "a", encoding="utf-8") as f:
            f.write("{0} {1}\n".format(now_ts(), line))
    except OSError:
        pass


def spawn_service(key, args, cwd, extra_env, port):
    # 子进程三护：stdin=DEVNULL（切断 TTY 继承，vite 的 readline 快捷键在共享终端
    # 下会 EPIPE 崩掉整个 dev server）；stdout/stderr 由读线线程加时间戳落
    # logs/dev_<key>.log；Windows 下 CREATE_NO_WINDOW 不弹窗。
    logfile = os.path.join(LOG_DIR, FILES[key])
    writer = open(logfile, "ab")
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env.update({k: v for k, v in extra_env.items() if v is not None})
    for k, v in extra_env.items():
        if v is None and k in env:
            del env[k]
    creationflags = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW
    # POSIX：独立进程组（stop_all 整组终止用）；Windows 无进程组概念，走 taskkill /T 树杀
    posix_kwargs = {"start_new_session": True} if os.name != "nt" else {}
    proc = subprocess.Popen(
        args, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        creationflags=creationflags, **posix_kwargs,
    )

    def pump(stream, writer, key):
        for raw in iter(stream.readline, b""):
            line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
            line = re.sub("\u001b\\[[0-9;]*[A-Za-z]", "", line)
            try:
                writer.write(("{0} {1}\n".format(now_ts(), line)).encode("utf-8"))
                writer.flush()
            except (OSError, ValueError):
                break

    threading.Thread(target=pump, args=(proc.stdout, writer, key), daemon=True).start()
    with _service_lock:
        _services[key] = {"proc": proc, "port": port, "writer": writer}
    write_sys_log("[OK] {0} started (pid {1})".format(key, proc.pid))
    return proc


def scan_free_port(start, end, exclude=()):
    used = set(exclude)
    for p in range(start, end + 1):
        if p in used:
            continue
        if not probe_port(p):
            return p
    raise RuntimeError("no free port in {0}..{1}".format(start, end))


def read_recorded_port(path, default):
    try:
        with open(path) as f:
            v = int(f.read().strip())
            return v if v > 0 else default
    except (OSError, ValueError):
        return default


def wait_port(port, timeout):
    dl = time.time() + timeout
    while time.time() < dl:
        if probe_port(port):
            return True
        time.sleep(0.5)
    return False


def venv_python():
    # venv 解释器：Windows 是 Scripts/python.exe，POSIX 是 bin/python3（旧实现自愈
    # 重启路径写死 Windows 路径，macOS/Linux 下自愈必失败）
    p = os.path.join(ROOT, ".venv", "Scripts", "python.exe")
    if not os.path.exists(p):
        p = os.path.join(ROOT, ".venv", "bin", "python3")
    return p


def npm(*args):
    # npm 在 Windows 上是 cmd 批处理，须经 cmd /c；POSIX 直接 exec
    base = ["cmd", "/c", "npm"] if os.name == "nt" else ["npm"]
    return base + list(args)


def backend_args(port):
    # ⚠ 不传 --reload（2026-09-06 实测死路）：uvicorn 的 Windows reload restart 靠
    # os.kill(worker, CTRL_C_EVENT)——需要真实控制台；监督者 CREATE_NO_WINDOW + pythonw
    # 链下事件打不到 worker，reloader 卡死在 process.join()（表现=打印 Reloading... 后
    # 永不重启，前台 Git Bash 同样复现）。debug 模式的 backend/**/*.py 热重载由监督者
    # 自己的 _backend_reload_watcher 承担（杀树重拉，走同一条自愈链路）。
    return [venv_python(), "-m", "uvicorn", "backend.main:app",
            "--host", "127.0.0.1", "--port", str(port), "--app-dir", ROOT]


def append_build_log(text):
    # 构建输出落 dev_<key>.log 同格式（"HH:mm:ss 原始行"）——pythonw 下没有控制台可回显，
    # 落文件才能让网页监控台看到构建过程与失败原因
    try:
        with open(os.path.join(LOG_DIR, FILES["vite"]), "a", encoding="utf-8") as f:
            for line in text.splitlines():
                f.write("{0} {1}\n".format(now_ts(), line))
    except OSError:
        pass


def spawn_all():
    # 端口协商与 start.ps1 同契约：recorded 且空闲则复用，否则扫描并写回端口文件。
    # 启动带阶段推进（PHASE → 网页进度条）：backend 起来再起前端，前端起来再起
    # electron——electron 加载的就是前端的 URL，顺序起避免首屏 ERR_CONNECTION_REFUSED。
    # prod 分支与 start.ps1 同构：npm run build 产 dist，再直接 electron .（不起 Vite）。
    global PHASE
    data_dir = os.path.join(ROOT, "data")
    port_file = os.path.join(data_dir, "port.txt")
    fe_file = os.path.join(data_dir, "frontend_port.txt")
    frontend_dir = os.path.join(ROOT, "frontend")

    backend_port = read_recorded_port(port_file, 8002)
    if probe_port(backend_port):
        backend_port = scan_free_port(8002, 8100)
    with open(port_file, "w") as f:
        f.write(str(backend_port))

    PHASE = "backend"
    spawn_service("backend", backend_args(backend_port), ROOT,
                  {"VELLUMA_PORT": str(backend_port)}, backend_port)
    write_dev_status()
    if not wait_port(backend_port, 60):
        write_sys_log("backend port not up in 60s, continuing")

    if MODE == "prod":
        # 生产体验：前端构建一次，Electron 以 NODE_ENV=production 走 loadFile('../dist/index.html')
        # ⚠ 构建输出必须自己接管道读走：pythonw 下父进程无控制台，子进程继承句柄可能直接失败
        # ⚠ CREATE_NO_WINDOW 同 spawn_service：句柄重定向不阻止控制台程序新建可见控制台，
        #    不加此标志 npm build 的 30~60 秒 = 黑窗常驻 30~60 秒
        PHASE = "electron"
        write_sys_log("prod: npm run build ...")
        try:
            build = subprocess.run(npm("run", "build"), cwd=frontend_dir,
                                   stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT,
                                   creationflags=0x08000000 if os.name == "nt" else 0)
        except OSError as e:
            write_sys_log("npm run build 无法启动: {0}（electron 不启动）".format(e))
            write_dev_status()
            return
        out = build.stdout.decode("utf-8", errors="replace").rstrip()
        append_build_log(out)
        if build.returncode != 0:
            write_sys_log("npm run build 失败 (exit {0})：\n{1}".format(
                build.returncode, "\n".join(out.splitlines()[-15:])))
            write_dev_status()
            return
        write_sys_log("prod: build 完成，拉起 Electron")
        fe_recorded = read_recorded_port(fe_file, 0)
        spawn_service("electron", npm("run", "electron:nobuild"), frontend_dir,
                      {"VELLUMA_BACKEND_PORT": str(backend_port),
                       "VELLUMA_FRONTEND_PORT": str(fe_recorded) if fe_recorded else None,
                       "VELLUMA_SERVICES_READY": "1",
                       "NODE_ENV": "production"}, None)
        return

    fe_port = read_recorded_port(fe_file, 5175)
    if probe_port(fe_port):
        fe_port = scan_free_port(5175, 5285)
    with open(fe_file, "w") as f:
        f.write(str(fe_port))

    PHASE = "vite"
    spawn_service("vite", npm("run", "dev"), frontend_dir,
                  {"VELLUMA_FRONTEND_PORT": str(fe_port)}, fe_port)
    write_dev_status()
    if not wait_port(fe_port, 30):
        write_sys_log("vite port not up in 30s, continuing")

    # dev/debug 走 electron:nobuild：electron:dev 里的 vite build 产物在开发模式
    # 根本不会被加载（main.cjs 走 loadURL 的 vite dev server），白等 30~60 秒
    PHASE = "electron"
    spawn_service("electron", npm("run", "electron:nobuild"), frontend_dir,
                  {"VELLUMA_BACKEND_PORT": str(backend_port),
                   "VELLUMA_FRONTEND_PORT": str(fe_port),
                   "VELLUMA_SERVICES_READY": "1",
                   "NODE_ENV": None}, None)


def _taskkill_tree(pid, proc=None):
    # Windows 树杀统一入口（2026-09-11「莫名黑窗 + 孤儿 backend」事故）三护：
    # ① CREATE_NO_WINDOW：pythonw 无控制台，taskkill 这类控制台程序不带此标志会
    #    **弹一个可见的新控制台**——debug 热重载一次一发、停机一服务一发；用户关掉
    #    弹窗即打断 taskkill → 杀失败 → 服务孤儿持端口（当晚 stop_all 对 backend
    #    开火无效、uvicorn 对活 20+ 分钟，正是此路径）。
    # ② 杀据落日志：旧实现 capture_output=True 吞掉一切，杀失败零痕迹无从追查。
    # ③ 杀后核验 + 补一发：用 Popen 句柄 poll 核验（不受 PID 重用影响——pid_alive
    #    裸查 pid 会在 PID 被复用后误杀无辜）；仍活补一发，两发不中大声记日志。
    creationflags = 0x08000000 if os.name == "nt" else 0
    for attempt in (1, 2):
        try:
            r = subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)],
                               capture_output=True, creationflags=creationflags)
            if r.returncode != 0:
                msg = (r.stderr or r.stdout or b"").decode("gbk", errors="replace").strip()
                write_sys_log("taskkill {0} attempt {1} rc={2}: {3}".format(
                    pid, attempt, r.returncode, msg))
        except OSError as e:
            write_sys_log("taskkill {0} attempt {1} OSError: {2}".format(pid, attempt, e))
        time.sleep(0.8)
        if proc is None or proc.poll() is not None:
            return True
    write_sys_log("taskkill {0}: STILL ALIVE after 2 attempts — 孤儿风险，可用 stop-velluma.bat 收拾".format(pid))
    return False


def stop_all():
    with _service_lock:
        items = list(_services.items())
    # ⚠ 只杀活 PID（2026-09-11）：死条目（electron 收摊锚点/自愈上限耗尽放弃者）一律
    # 跳过——taskkill 对死 pid 并非"仅报错无副作用"：PID 被 Windows 回收后 /T 会把
    # 无辜进程整树带走；放弃重启的死条目可能已死数小时，回收窗口完全敞开。
    for key, info in items:
        if info["proc"].poll() is not None:
            write_sys_log("{0} already exited (pid {1}), skip kill".format(key, info["proc"].pid))
            continue
        if os.name == "nt":
            # ⚠ Windows 两条路都是坑（均实测复现）：terminate=TerminateProcess 只杀 cmd 树根，
            # 且根死后 taskkill /T 失去遍历起点（对死 pid 报"找不到"）——npm→node 孙链在两种
            # 顺序下都会孤儿持端口。必须树杀一步到位：/F 强杀对 dev server 无损（SQLite WAL
            # 容错，无优雅退出需求）。
            _taskkill_tree(info["proc"].pid, info["proc"])
        else:
            # POSIX：spawn_service 以 start_new_session 建独立进程组，先整组 SIGTERM 礼貌段，
            # 2s 后整组 SIGKILL——kill 单 pid 只杀 npm 主进程，node 孙链不随父死同样会孤儿
            try:
                os.killpg(os.getpgid(info["proc"].pid), signal.SIGTERM)
            except OSError:
                pass
    if os.name != "nt":
        time.sleep(2)
        for key, info in items:
            if info["proc"].poll() is None:
                try:
                    os.killpg(os.getpgid(info["proc"].pid), signal.SIGKILL)
                except OSError:
                    pass
    for key, info in items:
        try:
            info["writer"].close()
        except (OSError, ValueError):
            pass


def _backend_py_mtimes():
    # backend/**/*.py 的 mtime 快照（排除 __pycache__）——监督者热重载的比对基线
    out = {}
    root = os.path.join(ROOT, "backend")
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for fn in filenames:
            if fn.endswith(".py"):
                p = os.path.join(dirpath, fn)
                try:
                    out[p] = os.stat(p).st_mtime
                except OSError:
                    pass
    return out


def _backend_reload_watcher():
    # 监督者内建后端热重载（debug 模式专用，2026-09-06）。
    # 为什么不用 uvicorn --reload：其 Windows restart 靠 CTRL_C_EVENT 打断 worker，
    # 需要真实控制台——CREATE_NO_WINDOW/pythonw 与 Git Bash 等无控制台环境下
    # reloader 检测到变化后卡死在 process.join()，永不重启（实测复现，见 spawn_all 注）。
    # 机制：2s 轮询 mtime 快照，变化后防抖 1.5s（编辑器批量落盘合并成一次重启），
    # 锁内杀树重拉（与自愈同链路；全程持锁让 supervisor_loop 的心跳永远看到
    # 活进程，不会误触发自愈计数）。显式重载不占 RESTART_LIMIT。
    baseline = _backend_py_mtimes()
    while not _shutdown.is_set():
        time.sleep(2)
        if _shutdown.is_set():
            break
        current = _backend_py_mtimes()
        changed = {p for p in set(baseline) | set(current)
                   if baseline.get(p) != current.get(p)}
        if not changed:
            continue
        # 防抖：等文件静默（1.5s 无新变化）再动手
        while not _shutdown.is_set():
            time.sleep(1.5)
            current = _backend_py_mtimes()
            if current == baseline or {p for p in set(baseline) | set(current)
                                       if baseline.get(p) != current.get(p)} == changed:
                break
            changed = {p for p in set(baseline) | set(current)
                       if baseline.get(p) != current.get(p)}
        if _shutdown.is_set():
            break
        write_sys_log("backend reload: {0} file(s) changed ({1}) — restarting".format(
            len(changed), ", ".join(os.path.basename(p) for p in sorted(changed)[:4])
            + (" …" if len(changed) > 4 else "")))
        with _service_lock:
            info = _services.get("backend")
            if info is None or info["proc"].poll() is not None:
                # backend 本就不在（自愈上限耗尽等）：照常重拉一次，给作者一条活路
                _services.pop("backend", None)
            elif os.name == "nt":
                _taskkill_tree(info["proc"].pid, info["proc"])
                _services.pop("backend", None)
            else:
                try:
                    os.killpg(os.getpgid(info["proc"].pid), signal.SIGTERM)
                except OSError:
                    pass
                _services.pop("backend", None)
            # info 可能为 None（backend 本就不在：拉起失败/自愈上限耗尽）——
            # 2026-09-06 审计修复：无守卫的 info["writer"] 抛 TypeError 不在原
            # except 元组内，观察者线程整条击毙、下面的「照常重拉」也到不了
            if info is not None:
                try:
                    info["writer"].close()
                except (OSError, ValueError):
                    pass
            _restart_counts.pop("backend", None)  # 显式重载不占自愈上限
            spawn_all_single("backend")
            write_dev_status()
        baseline = _backend_py_mtimes()


def supervisor_loop():
    # 心跳：状态 JSON 每 5s 刷新；backend/vite 意外退出自愈重启（上限 2 次）；
    # electron 退出 = 收摊契约（停掉其余服务后退出）
    global PHASE
    while not _shutdown.is_set():
        time.sleep(5)
        with _service_lock:
            snapshot = {k: dict(v) for k, v in _services.items()}
        for key, info in snapshot.items():
            code = info["proc"].poll()
            if code is None:
                continue
            write_sys_log("{0} exited (code {1})".format(key, code))
            if key == "electron":
                write_sys_log("electron exit = shutting down all services")
                _shutdown.set()
                break
            if _restart_counts.get(key, 0) < RESTART_LIMIT:
                _restart_counts[key] = _restart_counts.get(key, 0) + 1
                write_sys_log("{0} auto-restart ({1}/{2})".format(key, _restart_counts[key], RESTART_LIMIT))
                with _service_lock:
                    _services.pop(key, None)
                try:
                    info["writer"].close()
                except (OSError, ValueError):
                    pass
                spawn_all_single(key)
            else:
                write_sys_log("{0} reached restart limit, giving up".format(key))
                # 死条目即时出册（2026-09-11）：留在 _services 里，停机 stop_all 会
                # 对它的死 PID 开火——PID 被 Windows 回收后 = 误杀无辜进程整树
                with _service_lock:
                    dead = _services.pop(key, None)
                if dead is not None:
                    try:
                        dead["writer"].close()
                    except (OSError, ValueError):
                        pass
        # 阶段推进：electron 存活且前后端端口就绪 → ready（网页进度条转绿）
        if PHASE == "electron":
            b = snapshot.get("backend")
            v = snapshot.get("vite")
            e = snapshot.get("electron")
            # prod 不启 Vite（dist 直接 loadFile）——vite 缺席不算未就绪，
            # 否则进度条永远停在「正在拉起应用窗口」
            vite_ok = MODE == "prod" or (
                v is not None and v["proc"].poll() is None and probe_port(v["port"]))
            if (b and e and vite_ok and b["proc"].poll() is None
                    and e["proc"].poll() is None and probe_port(b["port"])):
                PHASE = "ready"
                write_sys_log("all services ready")
        write_dev_status()
    # 收摊契约：electron 退出（_shutdown 已置位）→ 停掉其余服务再退出
    stop_all()
    # 最后一笔把状态 JSON 改写成「全停」，别让陈旧的 running 心跳留给停脚本开火
    write_stopped_status()


def spawn_all_single(key):
    # 自愈重启单服务（端口沿用上次的协商结果）
    data_dir = os.path.join(ROOT, "data")
    frontend_dir = os.path.join(ROOT, "frontend")
    if key == "backend":
        port = read_recorded_port(os.path.join(data_dir, "port.txt"), 8002)
        spawn_service("backend", backend_args(port), ROOT, {"VELLUMA_PORT": str(port)}, port)
    elif key == "vite":
        port = read_recorded_port(os.path.join(data_dir, "frontend_port.txt"), 5175)
        spawn_service("vite", npm("run", "dev"), frontend_dir,
                      {"VELLUMA_FRONTEND_PORT": str(port)}, port)


def write_dev_status():
    # 监督者模式下的状态 JSON（与 start.ps1 心跳同 schema）
    services = {}
    with _service_lock:
        snapshot = {k: dict(v) for k, v in _services.items()}
    for key in ("backend", "vite", "electron"):
        info = snapshot.get(key)
        if info:
            services[key] = {
                "pid": info["proc"].pid,
                "port": info["port"],
                "state": "running" if info["proc"].poll() is None else "exited",
            }
        else:
            services[key] = {"pid": None, "port": None, "state": "-"}
    payload = {
        "mode": MODE,
        "hidden": True,
        "supervised": True,
        "phase": PHASE,
        "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "log_dir": LOG_DIR,
        "services": services,
        "dashboard": {"pid": os.getpid(), "port": DASH_PORT},
    }
    try:
        with open(STATUS_PATH, "w", encoding="utf-8") as f:
            json.dump(payload, f)
    except OSError:
        pass


def write_stopped_status():
    # 停机即除牌（2026-09-11）：监督者优雅停机后把状态 JSON 改写为「全停」——旧实现
    # 最后一笔心跳永远停在 running，停机数小时后 JSON 里的 PID 被 Windows 回收，
    # stop-velluma.ps1 拿陈旧 PID 开火时白名单只挡得住名字对不上的、同名照杀。
    # （taskkill /F 强杀监督者的路径写不了这最后一笔，由停脚本的新鲜度闸兜底。）
    payload = {
        "mode": MODE,
        "hidden": True,
        "supervised": True,
        "phase": "stopped",
        "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "log_dir": LOG_DIR,
        "services": {key: {"pid": None, "port": None, "state": "stopped"}
                     for key in ("backend", "vite", "electron")},
        "dashboard": {"pid": None, "port": None},
    }
    try:
        with open(STATUS_PATH, "w", encoding="utf-8") as f:
            json.dump(payload, f)
    except OSError:
        pass


def tail_file(path, after):
    # 增量读单文件：从字节偏移 after 起，只返回完整行（不完整尾行扣住不发）。
    # 文件变小（新一轮启动重建）→ 偏移失效归零，前端按 offsets 回跳清屏。
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            if after > size:
                after = 0
            if after >= size:
                return after, []
            f.seek(after)
            chunk = f.read(262144)
    except OSError:
        return 0, []
    cut = chunk.rfind(b"\n")
    if cut < 0:
        return after, []
    text = chunk[:cut].decode("utf-8", errors="replace")
    out = []
    for raw in text.split("\n"):
        raw = raw.rstrip("\r")
        if not raw:
            continue
        m = LINE_RE.match(raw)
        if m:
            out.append({"t": m.group(1), "label": "", "text": m.group(2)})
        else:
            out.append({"t": "", "label": "", "text": raw})
    return after + cut + 1, out


def build_logs(after_map):
    lines = []
    offsets = {}
    for label in LABELS:
        after = int(after_map.get(label, 0) or 0)
        off, file_lines = tail_file(os.path.join(LOG_DIR, FILES[label]), after)
        offsets[label] = off
        for l in file_lines:
            l["label"] = label
        lines.extend(file_lines)
    return {"offsets": offsets, "lines": lines}


def probe_port(port):
    # 端口探活：0.25s 超时，探不动即视为不在线（本地开发面板，宁严勿假绿）
    if not port:
        return None
    try:
        with socket.create_connection(("127.0.0.1", int(port)), timeout=0.25):
            return True
    except OSError:
        return False


def pid_alive(pid):
    # PID 存活检查：Windows 走 OpenProcess（⚠ 不能用 os.kill(pid,0)——Windows 上它
    # 会 TerminateProcess 真杀进程），POSIX 走 kill 0 信号探测
    if not pid:
        return None
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return None
    if os.name == "nt":
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        try:
            kernel32 = ctypes.windll.kernel32
            h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if not h:
                return False
            try:
                code = ctypes.c_ulong()
                if kernel32.GetExitCodeProcess(h, ctypes.byref(code)):
                    return code.value == STILL_ACTIVE
                return None
            finally:
                kernel32.CloseHandle(h)
        except Exception:
            return None
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def build_status():
    data = {}
    try:
        with open(STATUS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {}
    services = {}
    for key in ("backend", "vite", "electron"):
        info = data.get("services", {}).get(key, {}) or {}
        port = info.get("port")
        state = info.get("state") or "-"
        alive = probe_port(port) if port else None
        pa = pid_alive(info.get("pid")) if state == "running" else None
        if state == "running" and pa is False:
            state = "exited"  # 启动器心跳可能冻结，PID 已死即如实标退出
        elif state == "running" and alive is False and key in ("backend", "vite"):
            state = "down"  # PID 还在但端口不收包
        services[key] = {
            "pid": info.get("pid"),
            "port": port,
            "state": state,
            "alive": alive,
        }
    return {
        "mode": data.get("mode") or "-",
        "started_at": data.get("started_at"),
        "log_dir": data.get("log_dir") or LOG_DIR,
        "phase": data.get("phase") or "ready",
        "uptime_s": int(time.time() - STARTED),
        "services": services,
    }


PAGE = """<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Velluma 开发监控台</title>
<style>
  :root {
    --bg:#f5f1e8; --panel:#fffdf8; --edge:#e6dfd0; --ink:#3b352b; --dim:#9a917d;
    --accent:#7c5cd6;
    --c-backend:#46689b; --c-vite:#3e8e63; --c-electron:#a8722a; --c-sys:#9a917d; --c-raw:#6f675a;
  }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--bg); color:var(--ink);
         font:13px/1.65 Consolas,"Cascadia Mono","Microsoft YaHei Mono",monospace; }
  header { display:flex; align-items:center; gap:12px; padding:10px 20px; flex-wrap:wrap;
           border-bottom:1px solid var(--edge); background:rgba(255,253,248,.9);
           backdrop-filter:blur(8px); position:sticky; top:0; z-index:2; }
  header h1 { font-size:16px; margin:0; font-weight:400; letter-spacing:.3px;
              font-family:Georgia,"Times New Roman","Source Han Serif SC","Noto Serif SC",serif; }
  header h1 em { font-style:italic; color:var(--accent); }
  .mode { color:var(--accent); background:#f1ecfb; border:1px solid #ded2f5; border-radius:999px; padding:1px 12px; font-size:11px; }
  .pill { display:inline-flex; align-items:center; gap:6px; border:1px solid var(--edge);
          background:var(--panel); border-radius:999px; padding:2px 12px; font-size:11px; color:var(--dim); }
  .pill b { color:var(--ink); font-weight:600; }
  .dot { width:8px; height:8px; border-radius:50%; background:#cfc7b4; }
  .dot.on  { background:#43a06b; box-shadow:0 0 0 3px rgba(67,160,107,.15); }
  .dot.off { background:#cf6f62; }
  .dot.ext { background:#c9922e; }
  #bar { display:flex; flex-wrap:wrap; gap:8px; padding:10px 20px; border-bottom:1px solid var(--edge);
         position:sticky; top:45px; background:var(--bg); z-index:2; }
  button { background:var(--panel); color:var(--dim); border:1px solid var(--edge);
           border-radius:999px; padding:3px 14px; font:inherit; font-size:12px; cursor:pointer; }
  button:hover { color:var(--ink); border-color:#c9bfa8; }
  button.act { color:#fff; background:var(--accent); border-color:var(--accent); }
  #sheet { max-width:1150px; margin:20px auto 80px; background:var(--panel);
           border:1px solid var(--edge); border-radius:12px;
           box-shadow:0 1px 3px rgba(100,90,70,.06), 0 10px 26px rgba(100,90,70,.05); }
  #feed { padding:14px 22px 36px; }
  .ln { display:flex; gap:12px; padding:2px 0 2px 12px; white-space:pre-wrap; word-break:break-all;
        border-left:2px solid var(--edge); }
  .ln .t  { color:#b3ab97; flex:0 0 60px; }
  .ln .lb { flex:0 0 68px; font-weight:600; }
  .lb.backend{color:var(--c-backend)} .lb.vite{color:var(--c-vite)}
  .lb.electron{color:var(--c-electron)} .lb.sys{color:var(--c-sys)} .lb.raw{color:var(--c-raw)}
  .ln.backend  { border-left-color:#c9d8ee; }
  .ln.vite     { border-left-color:#cfe6d8; }
  .ln.electron { border-left-color:#ecdcc2; }
  .ln.sys      { border-left-color:#e4ddcf; }
  .ln.raw      { border-left-color:#e4ddcf; }
  .ln.hidden { display:none; }
  #jump { position:fixed; right:26px; bottom:26px; display:none; background:var(--panel);
          box-shadow:0 2px 8px rgba(100,90,70,.15); }
  #boot { display:none; align-items:center; gap:10px; padding:9px 20px; font-size:12px;
          background:#faf1d8; color:#8a6a1c; border-bottom:1px solid #ead9a8; }
  #boot.done { background:#e9f4ea; color:#35784e; border-bottom-color:#cfe4d2; }
  footer { position:fixed; left:0; right:0; bottom:0; padding:5px 20px; font-size:11px;
           color:var(--dim); background:rgba(255,253,248,.92); border-top:1px solid var(--edge); }

  /* ---- 分辨率自适应 ---- */
  /* 宽屏（≥1600）：纸卡放宽，长日志行不至于拖太长 */
  @media (min-width:1600px) {
    #sheet { max-width:1360px; }
  }
  /* 中窄（≤900，半屏窗口）：header 取消吸顶（换行后高度不定，吸顶条会错位），
     筛选条回落为普通换行流，纸卡贴边收窄 */
  @media (max-width:900px) {
    header { position:static; }
    #bar { position:static; padding:8px 14px; }
    #sheet { margin:12px 14px 70px; }
    #feed { padding:10px 14px 24px; }
  }
  /* 窄（≤640，小窗/高分屏缩放）：压缩固定列宽与间距 */
  @media (max-width:640px) {
    body { font-size:12px; }
    .ln { gap:8px; padding-left:8px; }
    .ln .t  { flex-basis:50px; }
    .ln .lb { flex-basis:56px; }
    #jump { right:14px; bottom:64px; }
  }
  /* 极窄（≤440）：时间与标签独占一行，正文换行铺满 */
  @media (max-width:440px) {
    .ln { display:block; padding-left:10px; }
    .ln .t  { display:inline-block; flex:none; margin-right:8px; }
    .ln .lb { display:inline-block; flex:none; margin-right:8px; }
  }
</style>
</head>
<body>
<header>
  <h1><em>Velluma</em> · 开发监控台</h1>
  <span class="mode" id="mode">-</span>
  <span class="pill"><span class="dot" id="dot-backend"></span><b>后端</b><span id="p-backend">-</span></span>
  <span class="pill"><span class="dot" id="dot-vite"></span><b>前端</b><span id="p-vite">-</span></span>
  <span class="pill"><span class="dot" id="dot-electron"></span><b>Electron</b><span id="p-electron">-</span></span>
  <span class="pill" id="uptime">-</span>
</header>
<div id="boot"><span>⏳</span><span id="boot-text">正在启动…</span></div>
<div id="bar">
  <button data-f="all" class="act">全部 [0]</button>
  <button data-f="backend">后端 [1]</button>
  <button data-f="vite">前端 [2]</button>
  <button data-f="electron">Electron [3]</button>
  <button id="pause">暂停 [空格]</button>
</div>
<div id="sheet"><div id="feed"></div></div>
<button id="jump">↓ 回到底部</button>
<footer id="foot"></footer>
<script>
const COLOR = { backend:"#46689b", vite:"#3e8e63", electron:"#a8722a", sys:"#9a917d", raw:"#6f675a" };
let offsets = { backend:0, vite:0, electron:0, sys:0 };
let paused = false, filter = "all", feed = document.getElementById("feed");
let pending = [];

function esc(s){ return s.replace(/[&<>]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;"}[c])); }
function atBottom(){ return window.innerHeight + window.scrollY >= document.body.scrollHeight - 40; }
function render(lines){
  for (const l of lines) {
    const d = document.createElement("div");
    d.className = "ln " + l.label + (filter !== "all" && l.label !== filter ? " hidden" : "");
    d.dataset.label = l.label;
    d.innerHTML = '<span class="t">' + esc(l.t) + '</span><span class="lb ' + l.label + '">' +
                  l.label + '</span><span style="color:' + (COLOR[l.label] || "#6f675a") + '">' + esc(l.text) + "</span>";
    pending.push(d);
  }
  if (!pending.length) return;
  if (atBottom()) { for (const d of pending) feed.appendChild(d); pending = [];
                    window.scrollTo(0, document.body.scrollHeight); }
  else if (pending.length > 400) { pending = pending.slice(-400); }
}
setInterval(async () => {
  if (paused) return;
  try {
    const r = await fetch("/api/logs?after=" + encodeURIComponent(JSON.stringify(offsets)));
    const d = await r.json();
    let reset = false;
    for (const k of Object.keys(offsets)) {
      if ((d.offsets[k] ?? 0) < offsets[k]) reset = true;   // 日志重建（新一次启动）
    }
    if (reset) { feed.innerHTML = ""; pending = []; }
    offsets = d.offsets;
    render(d.lines);
  } catch (e) { /* 服务重启期间请求失败静默，下一轮再试 */ }
}, 1000);

function pill(key, s) {
  const dot = document.getElementById("dot-" + key), txt = document.getElementById("p-" + key);
  let cls = "", label = "-";
  if (s.state === "running") { cls = "on"; label = ":" + (s.port ?? "GUI"); }
  else if (s.state === "external") { cls = "ext"; label = "外部:" + (s.port ?? ""); }
  else if (s.state === "down") { cls = "off"; label = ":" + s.port + " 无响应"; }
  else if (s.state === "exited") { cls = "off"; label = "已退出"; }
  dot.className = "dot " + cls;
  txt.textContent = label;
}
const PHASE_TEXT = {
  booting: "正在启动后端…", backend: "正在启动后端…",
  vite: "后端已就绪 · 正在启动前端…",
  electron: "前端已就绪 · 正在拉起应用窗口…"
};
let readyShown = false;
setInterval(async () => {
  try {
    const s = await (await fetch("/api/status")).json();
    document.getElementById("mode").textContent = s.mode;
    document.getElementById("uptime").textContent = "已运行 " + Math.floor(s.uptime_s / 60) + " 分钟";
    for (const k of ["backend", "vite", "electron"]) pill(k, s.services[k] || {});
    const boot = document.getElementById("boot"), txt = document.getElementById("boot-text");
    const ph = s.phase || "ready";
    if (ph !== "ready") {
      boot.style.display = "flex"; boot.classList.remove("done"); readyShown = false;
      txt.textContent = PHASE_TEXT[ph] || ph;
    } else if (!readyShown) {
      readyShown = true;
      boot.style.display = "flex"; boot.className = "done";
      txt.textContent = "✓ 全部就绪——应用窗口已打开";
      setTimeout(() => { boot.style.display = "none"; }, 8000);
    }
  } catch (e) {}
}, 3000);

for (const b of document.querySelectorAll("#bar button[data-f]"))
  b.onclick = () => setFilter(b.dataset.f);
function setFilter(f) {
  filter = f;
  for (const b of document.querySelectorAll("#bar button[data-f]"))
    b.classList.toggle("act", b.dataset.f === f);
  for (const d of feed.children) d.classList.toggle("hidden", f !== "all" && d.dataset.label !== f);
}
const pauseBtn = document.getElementById("pause");
pauseBtn.onclick = () => { paused = !paused; pauseBtn.classList.toggle("act", paused);
                           pauseBtn.textContent = paused ? "继续 [空格]" : "暂停 [空格]"; };
document.getElementById("jump").onclick = () => window.scrollTo(0, document.body.scrollHeight);
window.addEventListener("scroll", () => {
  document.getElementById("jump").style.display = atBottom() ? "none" : "block";
});
window.addEventListener("keydown", (e) => {
  if (e.key === "1") setFilter("backend");
  else if (e.key === "2") setFilter("vite");
  else if (e.key === "3") setFilter("electron");
  else if (e.key === "0") setFilter("all");
  else if (e.key === " ") { pauseBtn.onclick(); e.preventDefault(); }
});
fetch("/api/status").then(r => r.json()).then(s => {
  document.getElementById("foot").textContent =
    "日志 " + (s.log_dir || "-") + "\\dev_*.log · 每秒增量拉取 · 快捷键 1/2/3/0 聚焦 · 空格暂停";
});
</script>
</body>
</html>
"""

class Handler(BaseHTTPRequestHandler):
    def _send(self, code, ctype, body):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/":
            body = PAGE.encode("utf-8")
            self._send(200, "text/html; charset=utf-8", body)
        elif u.path == "/api/logs":
            after_map = {}
            try:
                after_map = json.loads(parse_qs(u.query).get("after", ["{}"])[0])
            except (ValueError, TypeError):
                pass
            body = json.dumps(build_logs(after_map)).encode("utf-8")
            self._send(200, "application/json; charset=utf-8", body)
        elif u.path == "/api/status":
            body = json.dumps(build_status()).encode("utf-8")
            self._send(200, "application/json; charset=utf-8", body)
        else:
            self._send(404, "text/plain; charset=utf-8", b"not found")

    def log_message(self, *args):
        # 静默访问日志：面板每秒轮询，照默认实现打 stdout 会刷爆启动器控制台
        pass


def main():
    global LOG_DIR, STATUS_PATH, STARTED, SUPERVISE, MODE, ROOT, DASH_PORT
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True, help="日志目录（监督者写 dev_*.log）")
    ap.add_argument("--status", required=True, help="状态 JSON 路径（监督者心跳写入）")
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--supervise", action="store_true",
                    help="监督者模式：拉起并看护 backend/vite/electron（后台模式的关键路径）")
    ap.add_argument("--mode", default="dev", choices=["dev", "debug", "prod"])
    ap.add_argument("--root", default="", help="项目根（监督者模式必填）")
    args = ap.parse_args()
    LOG_DIR = args.dir
    STATUS_PATH = args.status
    if args.supervise:
        # 单实例护栏：状态 JSON 新鲜且其 dashboard pid 还活着 = 已有监督者在跑，
        # 直接退出（快速双击/杀软沙箱预执行会制造双实例，第二棵服务树只会添乱）
        try:
            mtime = os.path.getmtime(STATUS_PATH)
            with open(STATUS_PATH, encoding="utf-8") as f:
                old_pid = (json.load(f).get("dashboard") or {}).get("pid")
            if old_pid and pid_alive(old_pid) and (time.time() - mtime) < 120:
                write_sys_log("another supervisor (pid {0}) is alive, exiting".format(old_pid))
                # pythonw 下 sys.stdout 是 None，裸 print 会 AttributeError 崩溃退出
                # （行为上碰巧也是退出，但崩溃路径；控制台手动跑时保留回显）
                if sys.stdout:
                    print("supervisor already running (pid {0})".format(old_pid))
                return
        except (OSError, ValueError):
            pass
        os.makedirs(LOG_DIR, exist_ok=True)
        os.makedirs(os.path.dirname(STATUS_PATH), exist_ok=True)
        # --port 0：8180 起自动扫空闲端口（vbs 入口不做端口协商，保持入口极简）
        if args.port > 0:
            DASH_PORT = args.port
        else:
            DASH_PORT = scan_free_port(8180, 8199)
    else:
        DASH_PORT = args.port
    STARTED = time.time()
    if args.supervise:
        SUPERVISE = True
        MODE = args.mode
        ROOT = os.path.abspath(args.root)
        # 每次启动重建日志视图（自愈重启走 "ab" 追加，不受影响）——⚠ 必须在写任何
        # sys 叙事之前：先写后截会把本轮第一条叙事自己擦掉
        for f in FILES.values():
            try:
                open(os.path.join(LOG_DIR, f), "wb").close()
            except OSError:
                pass
        write_sys_log("supervisor starting (mode={0})".format(MODE))
        # ⚠ 页面优先：HTTP 服务先起 + 浏览器先开（双击后 2~3 秒内就有反馈），服务树
        # 在页面背后由 spawn_all 跟上——phase 变化即时写状态 JSON，进度横幅实时可见。
        # 旧实现是等三端全部起来才起页面，那几秒~十几秒的盲区正是「不知道启动了没」的来源。
        global PHASE
        PHASE = "booting"
        write_dev_status()
        srv = ThreadingHTTPServer(("127.0.0.1", DASH_PORT), Handler)
        srv.daemon_threads = True
        threading.Thread(target=srv.serve_forever, daemon=True).start()

        # 后台模式无终端反馈，浏览器是唯一界面：页面一起来就打开
        def _open_browser():
            time.sleep(0.8)
            try:
                import webbrowser
                webbrowser.open("http://127.0.0.1:{0}".format(DASH_PORT))
            except Exception:
                pass
        threading.Thread(target=_open_browser, daemon=True).start()

        try:
            spawn_all()
        except Exception as e:
            # 拉起失败也要让页面活着显示状态（异常进 dev_sys.log，pills 如实变红）
            write_sys_log("spawn_all failed: {0}".format(e))
        if MODE == "debug":
            threading.Thread(target=_backend_reload_watcher, daemon=True,
                             name="backend-reload-watcher").start()
        supervisor_loop()          # 主线程常驻：心跳/自愈/收摊契约
    # ⚠ 绑定必须用 DASH_PORT（--port 0 = 自动扫描），绑 args.port 会拿到系统随机端口，
    # 仪表盘在扫描出的端口上不可达（2026-09-05 实机踩过）
    if not SUPERVISE:
        srv = ThreadingHTTPServer(("127.0.0.1", DASH_PORT), Handler)
        srv.daemon_threads = True
        srv.serve_forever()


if __name__ == "__main__":
    main()
