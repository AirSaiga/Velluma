# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""==== 启动脚本契约自检 ====

2026-09-19 目录重组后，启动编排按「环境/功能完全隔离」分成多个自持文件夹：

    scripts/dev/start-all.ps1            开发（热重载）编排·Windows
    scripts/prod/start-all.ps1           生产编排·Windows
    scripts/macos/dev/start-all.sh       开发（热重载）编排·macOS/Linux
    scripts/macos/prod/start-all.sh      生产编排·macOS/Linux
    scripts/monitor/dev_dashboard.py     后台监督者+网页监控台（monitor 私有副本）
    scripts/{dev,prod}/start-backend*.   单服务前台脚本（dev 侧持有端口协商）
    scripts/stop-velluma.ps1             收摊脚本的孤儿清扫端口段
    frontend/src/services/api/transport/base.ts   前端 dev-server 端口判定

隔离的代价是同一组契约数字写进更多文件——历史已经飘过（前端扫描上界
5274 / 5275 / 5285 三版并存，监控台与收摊脚本覆盖范围对不上）。本脚本把这些
数字抽出来对拍，防静默漂移：

  - 后端端口段：8002~8100（与 backend/core/config.py 的 DEFAULT_PORT..MAX_PORT 对齐）
  - 前端端口段：5175~5285（仅 dev 环境持有：prod 无 Vite、无前端端口协商）
  - 全部 Electron 启动路径统一 electron:nobuild（loadURL/loadFile 由 NODE_ENV 决定）

用法：
    python scripts/check_launcher_contract.py     # CI 与本地都可跑，不一致即退出 1

⚠ 改端口段/换 electron npm script 时：改全部实现，再改本文件；本文件报错不是噪声，
是它刚刚拦下了一次真实漂移。
"""
import os
import re
import sys

# Windows 下 stdout 为管道/重定向时编码回落 ANSI 代码页（中文系统=GBK），
# 汇总段的 ⊇/✅/❌ 不在 GBK 内会 UnicodeEncodeError（交互式控制台走
# WriteConsoleW 不受影响，崩的是重定向场景）——统一 UTF-8，与 backend/main.py
# 启动期同款处理
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ---- 检查面（新布局）----
PS1_DEV_ALL = "scripts/dev/start-all.ps1"
PS1_PROD_ALL = "scripts/prod/start-all.ps1"
PS1_DEV_BACKEND = "scripts/dev/start-backend.ps1"
PS1_DEV_FRONTEND = "scripts/dev/start-frontend.ps1"
PS1_PROD_BACKEND = "scripts/prod/start-backend.ps1"
SH_DEV_ALL = "scripts/macos/dev/start-all.sh"
SH_PROD_ALL = "scripts/macos/prod/start-all.sh"
SH_DEV_BACKEND = "scripts/macos/dev/start-backend.sh"
SH_DEV_FRONTEND = "scripts/macos/dev/start-frontend.sh"
SH_PROD_BACKEND = "scripts/macos/prod/start-backend.sh"
SUP = "scripts/monitor/dev_dashboard.py"
STOP = "scripts/stop-velluma.ps1"
FE_BASE = "frontend/src/services/api/transport/base.ts"

# 契约本体（唯一的"应该值"）：两端编排端口段 + 统一 electron 启动脚本
BACKEND_RANGE = (8002, 8100)
FRONTEND_RANGE = (5175, 5285)
ELECTRON_SCRIPT = "electron:nobuild"

failures = []


def read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


def grab(text, pattern, rel, what, group=1):
    m = re.search(pattern, text, re.MULTILINE)
    if not m:
        failures.append("{0}: 找不到 {1}（正则 {2}）——若已改名，同步更新本脚本".format(rel, what, pattern))
        return None
    return m.group(group)


def grab_int(text, pattern, rel, what):
    # 端口常量一律按 int 取：多处解析结果要能直接互比（正则命中即字符串）
    v = grab(text, pattern, rel, what)
    return None if v is None else int(v)


def expect(rel, what, got, want):
    if got != want:
        failures.append("{0}: {1} = {2}，契约要求 {3}".format(rel, what, got, want))
    return "{0}: {1} = {2}".format(rel, what, got)


def parse_ps1(rel, keys):
    # keys ⊆ {"backend", "frontend"}：该文件应持有的端口段常量
    text = read(rel)
    out = {}
    if "backend" in keys:
        out["backend"] = (grab_int(text, r"DefaultBackendPort\s*=\s*(\d+)", rel, "DefaultBackendPort"),
                          grab_int(text, r"BackendPortMax\s*=\s*(\d+)", rel, "BackendPortMax"))
    if "frontend" in keys:
        out["frontend"] = (grab_int(text, r"DefaultFrontendPort\s*=\s*(\d+)", rel, "DefaultFrontendPort"),
                           grab_int(text, r"FrontendPortMax\s*=\s*(\d+)", rel, "FrontendPortMax"))
    return out


def parse_sh(rel, keys):
    text = read(rel)
    out = {}
    if "backend" in keys:
        out["backend"] = (grab_int(text, r"^DEFAULT_BACKEND_PORT=(\d+)", rel, "DEFAULT_BACKEND_PORT"),
                          grab_int(text, r"^BACKEND_PORT_MAX=(\d+)", rel, "BACKEND_PORT_MAX"))
    if "frontend" in keys:
        out["frontend"] = (grab_int(text, r"^DEFAULT_FRONTEND_PORT=(\d+)", rel, "DEFAULT_FRONTEND_PORT"),
                           grab_int(text, r"^FRONTEND_PORT_MAX=(\d+)", rel, "FRONTEND_PORT_MAX"))
    return out


PS1_SURFACES = [
    (PS1_DEV_ALL, {"backend", "frontend"}),
    (PS1_PROD_ALL, {"backend"}),
    (PS1_DEV_BACKEND, {"backend"}),
    (PS1_DEV_FRONTEND, {"frontend"}),
    (PS1_PROD_BACKEND, {"backend"}),
]
SH_SURFACES = [
    (SH_DEV_ALL, {"backend", "frontend"}),
    (SH_PROD_ALL, {"backend"}),
    (SH_DEV_BACKEND, {"backend"}),
    (SH_DEV_FRONTEND, {"frontend"}),
    (SH_PROD_BACKEND, {"backend"}),
]


def parse_supervisor():
    # 监督者用 scan_free_port(lo, hi) 表达同两段（另有 8180~8199 是监控台自身端口）
    pairs = set()
    for lo, hi in re.findall(r"scan_free_port\((\d+),\s*(\d+)\)", read(SUP)):
        pairs.add((int(lo), int(hi)))
    out = {}
    for key, want in (("backend", BACKEND_RANGE), ("frontend", FRONTEND_RANGE)):
        if want not in pairs:
            failures.append("{0}: 未找到 scan_free_port{1}（实际: {2}）".format(
                SUP, want, sorted(pairs)))
        out[key] = want if want in pairs else None
    return out


def parse_stop_sweep():
    # 收摊脚本的孤儿清扫段必须覆盖（不要求等于）服务端口段，否则残留进程扫不到
    sweeps = [(int(lo), int(hi)) for lo, hi in re.findall(
        r"\$_\.LocalPort\s+-ge\s+(\d+)\s+-and\s+\$_\.LocalPort\s+-le\s+(\d+)", read(STOP))]
    out = []
    for name, (want_lo, want_hi) in (("后端", BACKEND_RANGE), ("前端", FRONTEND_RANGE)):
        hit = [s for s in sweeps if s[0] <= want_lo and s[1] >= want_hi]
        if not hit:
            failures.append("{0}: 孤儿清扫段 {1} 未覆盖 {2}~{3}".format(STOP, sweeps, want_lo, want_hi))
            out.append("{0}: 未覆盖 {1}".format(name, want_lo))
        else:
            out.append("{0}: 覆盖（{1}~{2} ⊇ {3}~{4}）".format(name, hit[0][0], hit[0][1], want_lo, want_hi))
    return out


def parse_frontend():
    # 前端只要求"判定区间 ⊇ 脚本扫描段"：MIN 还要容下 Vite 自身的 5173/5174
    text = read(FE_BASE)
    lo = grab(text, r"DEV_SERVER_PORT_MIN\s*=\s*(\d+)", FE_BASE, "DEV_SERVER_PORT_MIN")
    hi = grab(text, r"DEV_SERVER_PORT_MAX\s*=\s*(\d+)", FE_BASE, "DEV_SERVER_PORT_MAX")
    if lo is None or hi is None:
        return None
    lo, hi = int(lo), int(hi)
    if not (lo <= FRONTEND_RANGE[0] and hi >= FRONTEND_RANGE[1]):
        failures.append("{0}: dev-server 区间 {1}~{2} 未覆盖脚本扫描段 {3}~{4}".format(
            FE_BASE, lo, hi, FRONTEND_RANGE[0], FRONTEND_RANGE[1]))
    return "{0}: dev-server 区间 {1}~{2}".format(FE_BASE, lo, hi)


def check_electron_script():
    # 一切 Electron 启动路径（编排核心 ×4 + 单飞脚本 ×4 + 监督者）都走 electron:nobuild
    surfaces = [
        PS1_DEV_ALL, PS1_PROD_ALL, PS1_DEV_ELECTRON, PS1_PROD_ELECTRON,
        SH_DEV_ALL, SH_PROD_ALL, SH_DEV_ELECTRON, SH_PROD_ELECTRON,
        SUP,
    ]
    out = []
    for rel in surfaces:
        if ELECTRON_SCRIPT not in read(rel):
            failures.append("{0}: 未使用 {1}（全端须一致：vite build 产物在 dev 不被加载）".format(
                rel, ELECTRON_SCRIPT))
        else:
            out.append("{0}: {1}".format(rel, ELECTRON_SCRIPT))
    return out


PS1_DEV_ELECTRON = "scripts/dev/start-electron.ps1"
PS1_PROD_ELECTRON = "scripts/prod/start-electron.ps1"
SH_DEV_ELECTRON = "scripts/macos/dev/start-electron.sh"
SH_PROD_ELECTRON = "scripts/macos/prod/start-electron.sh"


def main():
    print("启动脚本契约自检（后端 {0[0]}~{0[1]} / 前端 {1[0]}~{1[1]}）\n".format(
        BACKEND_RANGE, FRONTEND_RANGE))

    for rel, keys in PS1_SURFACES:
        for key in sorted(keys):
            want = BACKEND_RANGE if key == "backend" else FRONTEND_RANGE
            print("  " + expect(rel, key, parse_ps1(rel, {key})[key], want))

    for rel, keys in SH_SURFACES:
        for key in sorted(keys):
            want = BACKEND_RANGE if key == "backend" else FRONTEND_RANGE
            print("  " + expect(rel, key, parse_sh(rel, {key})[key], want))

    print("\n  —— 监督者（monitor 私有副本）")
    for key, want in (("backend", BACKEND_RANGE), ("frontend", FRONTEND_RANGE)):
        print("  " + expect(SUP, key, parse_supervisor()[key], want))

    print("\n  —— 收摊脚本孤儿清扫段（窗口自身端口段为 5175~5285 / 8002~8100）")
    for line in parse_stop_sweep():
        print("  " + line)

    print("\n  —— 前端 dev-server 判定")
    fe = parse_frontend()
    if fe:
        print("  " + fe)

    print("\n  —— electron 启动脚本名")
    for line in check_electron_script():
        print("  " + line)

    if failures:
        print("\n❌ 契约不一致 {0} 处：".format(len(failures)))
        for f in failures:
            print("   - " + f)
        print("\n修法：改全部实现（编排核心×4 + 单服务脚本 + 监督者副本 + 收摊脚本 + 前端判定），再改本文件的契约常量。")
        return 1
    print("\n✅ 全端契约一致。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
