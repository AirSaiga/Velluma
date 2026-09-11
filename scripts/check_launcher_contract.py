# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""==== 启动脚本契约自检 ====

启动编排有三份实现（不同平台/运行方式各自的语言），却必须守同一套契约：

    scripts/windows/start.ps1         可见终端监控台（Windows）
    scripts/macos/start.sh            可见终端监控台（macOS/Linux）
    scripts/dev_dashboard.py          后台监督者（--supervise，两平台共用）
    scripts/windows/stop-velluma.ps1  收摊脚本的孤儿清扫端口段
    frontend/src/services/api/transport/base.ts   前端 dev-server 端口判定

契约本身没法用共享代码表达，就退化成"同一组数字写在五处"——历史上已经飘过
（前端扫描上界 5274 / 5275 / 5285 三版并存，监控台与收摊脚本覆盖范围对不上）。
本脚本把这些数字抽出来对拍，防静默漂移：

  - 后端端口段：8002~8100（与 backend/core/config.py 的 DEFAULT_PORT..MAX_PORT 对齐）
  - 前端端口段：5175~5285
  - 三份编排的 electron 启动脚本名一致（electron:nobuild——loadURL/loadFile 由
    NODE_ENV 决定，dev/debug 的 vite build 产物根本不会被加载）

用法：
    python scripts/check_launcher_contract.py     # CI 与本地都可跑，不一致即退出 1

⚠ 改端口段/换 electron npm script 时：改全部实现，再改本文件；本文件报错不是噪声，
是它刚刚拦下了一次真实漂移。
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PS1 = "scripts/windows/start.ps1"
SH = "scripts/macos/start.sh"
SUP = "scripts/dev_dashboard.py"
STOP = "scripts/windows/stop-velluma.ps1"
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
    # 端口常量一律按 int 取：三处解析结果要能直接互比（正则命中即字符串）
    v = grab(text, pattern, rel, what)
    return None if v is None else int(v)


def expect(rel, what, got, want):
    if got != want:
        failures.append("{0}: {1} = {2}，契约要求 {3}".format(rel, what, got, want))
    return "{0}: {1} = {2}".format(rel, what, got)


def parse_ps1():
    text = read(PS1)
    return {
        "backend": (grab_int(text, r"DefaultBackendPort\s*=\s*(\d+)", PS1, "DefaultBackendPort"),
                    grab_int(text, r"BackendPortMax\s*=\s*(\d+)", PS1, "BackendPortMax")),
        "frontend": (grab_int(text, r"DefaultFrontendPort\s*=\s*(\d+)", PS1, "DefaultFrontendPort"),
                     grab_int(text, r"FrontendPortMax\s*=\s*(\d+)", PS1, "FrontendPortMax")),
    }


def parse_sh():
    text = read(SH)
    return {
        "backend": (grab_int(text, r"^DEFAULT_BACKEND_PORT=(\d+)", SH, "DEFAULT_BACKEND_PORT"),
                    grab_int(text, r"^BACKEND_PORT_MAX=(\d+)", SH, "BACKEND_PORT_MAX")),
        "frontend": (grab_int(text, r"^DEFAULT_FRONTEND_PORT=(\d+)", SH, "DEFAULT_FRONTEND_PORT"),
                     grab_int(text, r"^FRONTEND_PORT_MAX=(\d+)", SH, "FRONTEND_PORT_MAX")),
    }


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
    out = []
    for rel in (PS1, SH, SUP):
        if ELECTRON_SCRIPT not in read(rel):
            failures.append("{0}: 未使用 {1}（三端须一致：dev/debug 下 vite build 产物不被加载）".format(
                rel, ELECTRON_SCRIPT))
        else:
            out.append("{0}: {1}".format(rel, ELECTRON_SCRIPT))
    return out


def main():
    print("启动脚本契约自检（后端 {0[0]}~{0[1]} / 前端 {1[0]}~{1[1]}）\n".format(
        BACKEND_RANGE, FRONTEND_RANGE))

    for rel, parsed in ((PS1, parse_ps1()), (SH, parse_sh()), (SUP, parse_supervisor())):
        for key, want in (("backend", BACKEND_RANGE), ("frontend", FRONTEND_RANGE)):
            got = parsed[key]
            print("  " + expect(rel, key, got, want))

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
        print("\n修法：改全部实现（三份编排 + 收摊脚本 + 前端判定），再改本文件的契约常量。")
        return 1
    print("\n✅ 三端契约一致。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
