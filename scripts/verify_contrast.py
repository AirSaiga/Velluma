# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors

"""==== UX 重构地基 · 对比度验证（docs/design/ux-redesign/00-foundation.md 附录 A）====

WCAG 相对亮度公式复算地基 token 的前景/背景组合。口径分两层：

- 承诺组（FAIL 级，退出码 1）：设计稿 token 表承诺的口径——
  文字三级 on --bg-primary（§1.2/§2.4 实测列同口径），
  状态色 on 自身 -bg 与 on --bg-primary（§2.5「fg 于自身 -bg 上」）。
- 观测组（WARN 级，不失败）：faint 全组合 + 文字三级 on 次级底组合。
  ⚠ 已知设计矛盾两处（改 token 属设计决定，待设计侧裁决后再升入承诺组）：
  1. faint：§2.4 门槛「大字 ≥3.0」，但 §2.5 表格浅色给值 #a89e90 自标实测 2.4——
     设计稿给的值过不了自己定的门槛（深色 #6b6459 = 3.03 压线）；
     faint 使用纪律=「纯装饰、禁承载信息」，WCAG 对纯装饰豁免，按观测组处理。
  2. 次级底：§2.4 明文「深色 muted 不变（4.7 ✅）」是按 on bg-primary 口径的结论，
     与附录 A「全部 fg-on-bg 组合」字面冲突——深色 muted/faint 在
     bg-secondary/bg-tertiary/bg-canvas 上不足 4.5/3.0（最差 2.48，浅色 faint 同族）。

门槛：正文/辅助文字 ≥ 4.5；faint 装饰档 ≥ 3.0（大字档）。
跑一次即弃或留 CI 皆可：python scripts/verify_contrast.py

==== ---- ===="""


def _lin(c):
    c /= 255
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def lum(hexc):
    hexc = hexc.lstrip('#')
    r, g, b = (int(hexc[i:i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def ratio(fg, bg):
    a, b = sorted((lum(fg), lum(bg)), reverse=True)
    return (a + 0.05) / (b + 0.05)


# 双主题 token 值（与 frontend/src/style.css :root / :root.dark 同源，改 token 先改这里）
LIGHT = {
    'bg': '#f7f4ed', 'bg-secondary': '#faf8f4', 'bg-tertiary': '#f0ece3', 'bg-canvas': '#fefdfb',
    'text-primary': '#2c2c2c', 'text-secondary': '#6b6560', 'text-muted': '#756c5e', 'text-faint': '#a89e90',
    'ok': '#047857', 'ok-bg': '#d1fae5', 'warn': '#b45309', 'warn-bg': '#fef3c7',
    'danger': '#b91c1c', 'danger-bg': '#fee2e2', 'info': '#1d4ed8', 'info-bg': '#dbeafe',
}
DARK = {
    'bg': '#1a1815', 'bg-secondary': '#211f1b', 'bg-tertiary': '#2c2923', 'bg-canvas': '#1e1c18',
    'text-primary': '#ede8df', 'text-secondary': '#bfb8ab', 'text-muted': '#8a8275', 'text-faint': '#6b6459',
    'ok': '#34d399', 'ok-bg': '#0f2b22', 'warn': '#fbbf24', 'warn-bg': '#33270e',
    'danger': '#f87171', 'danger-bg': '#3a1a1a', 'info': '#93c5fd', 'info-bg': '#15243d',
}

# 承诺组（FAIL 级）与观测组（WARN 级）断言表：(前景, 背景, 自定义门槛)
PROMISE_CASES = []
WATCH_CASES = []
for theme in ('light', 'dark'):
    t = LIGHT if theme == 'light' else DARK
    # 文字三级：承诺口径只对 --bg-primary（§2.4 token 表实测列同口径）；
    # faint 与次级底组合进观测组（见模块 docstring 的两处设计矛盾说明）
    for bgk in ('bg', 'bg-secondary', 'bg-tertiary', 'bg-canvas'):
        promise = bgk == 'bg'
        for tk, floor in (('text-primary', 4.5), ('text-secondary', 4.5),
                          ('text-muted', 4.5), ('text-faint', 3.0)):
            (PROMISE_CASES if promise and tk != 'text-faint' else WATCH_CASES).append(
                (f'{theme} {tk} on {bgk}', t[tk], t[bgk], floor))
    # 状态色四组：前景 on 自身 -bg + on 页面底（§2.5 承诺口径）
    for st in ('ok', 'warn', 'danger', 'info'):
        PROMISE_CASES.append((f'{theme} {st} on {st}-bg', t[st], t[f'{st}-bg'], 4.5))
        PROMISE_CASES.append((f'{theme} {st} on bg', t[st], t['bg'], 4.5))


def main():
    failed = []
    for name, fg, bg, floor in PROMISE_CASES:
        r = ratio(fg, bg)
        mark = 'PASS' if r >= floor else 'FAIL'
        if r < floor:
            failed.append((name, r, floor))
        print(f'[{mark}] {name:42s} {r:5.2f} (need {floor})')
    warned = []
    for name, fg, bg, floor in WATCH_CASES:
        r = ratio(fg, bg)
        mark = 'PASS' if r >= floor else 'WARN'
        if r < floor:
            warned.append((name, r, floor))
        print(f'[{mark}] {name:42s} {r:5.2f} (need {floor})')
    if warned:
        print(f'\n观测组 {len(warned)} 组低于门槛（设计矛盾待裁决，见模块 docstring，不判失败）：')
        for name, r, floor in warned:
            print(f'  - {name}: {r:.2f} < {floor}')
    if failed:
        print(f'\n承诺组 {len(failed)} 组不达标')
        raise SystemExit(1)
    print(f'\n承诺组全部 {len(PROMISE_CASES)} 组达标（WCAG AA）；观测组 {len(warned)} 组待设计裁决')


if __name__ == '__main__':
    main()
