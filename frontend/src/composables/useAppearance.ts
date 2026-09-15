/**
 * 外观系统（docs/design/theme-system/01-theme-architecture.md §1.2）
 *
 * 二维正交：主题 id（挂 documentElement.dataset.theme）× 明暗 mode（挂 .dark class）。
 * 持久化：localStorage `velluma:appearance:v1`（JSON，设备本地——防闪烁要求同步可读，
 * localStorage 是唯一同步可读存储；外观重设 10 秒，可接受换 origin 漂移）。
 * 旧键 `velluma_theme`（'light'|'dark'）读取后迁移为 paper 主题对应 mode。
 *
 * ⚠ 防闪烁对拍契约：frontend/index.html 内联脚本与本文件 parse()/apply() 逻辑同源，
 * 改一边必须改另一边（脚本头部注释同述）。
 */
import { ref, computed } from 'vue'

export type ThemeId = 'paper' | 'minimal' | 'soft' | 'pro' | 'anime'
export type AppearanceMode = 'system' | 'light' | 'dark'
export type BgTexture = 'grain' | 'weave'

export type BgSpec =
  | { kind: 'theme' } // 跟随主题 --bg-primary（默认）
  | { kind: 'color'; color: string; veil?: number } // 自选纯色 + 遮罩 0~0.8
  | { kind: 'image'; dataUrl: string; veil: number } // 本地图片（已压缩 dataURL）+ 遮罩
  | { kind: 'texture'; texture: BgTexture; veil?: number } // 内置纸纹

export interface Appearance {
  theme: ThemeId
  mode: AppearanceMode
  bg: BgSpec
  motionLow: boolean
}

const STORAGE_KEY = 'velluma:appearance:v1'
const LEGACY_KEY = 'velluma_theme'

export const THEME_IDS: ThemeId[] = ['paper', 'minimal', 'soft', 'pro', 'anime']

/** 内置纸纹（4KB 内 SVG data-URI；⚠ 与 index.html 内联脚本 TEXTURES 对拍，改一边必须改另一边） */
const TEXTURES: Record<BgTexture, string> = {
  grain:
    "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='140' height='140'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.82' numOctaves='2' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='140' height='140' filter='url(%23n)' opacity='0.55'/%3E%3C/svg%3E\")",
  weave:
    "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='120' height='120'%3E%3Cdefs%3E%3Cpattern id='w' width='12' height='12' patternUnits='userSpaceOnUse'%3E%3Cpath d='M0 6 Q3 3 6 6 T12 6' fill='none' stroke='%23000' stroke-opacity='0.16' stroke-width='1'/%3E%3Cpath d='M0 12 Q3 9 6 12 T12 12' fill='none' stroke='%23000' stroke-opacity='0.10' stroke-width='1'/%3E%3C/pattern%3E%3C/defs%3E%3Crect width='120' height='120' fill='url(%23w)'/%3E%3C/svg%3E\")",
}

/**
 * 纸面淡剂量纸纹（04 §A1：桌面纹理 0.55 彩噪靠白纱压淡，直接叠纸面会脏——
 * 纸面用灰度化+16% 低不透明变体；浅纸显暗粒、深纸显亮粒，单档两用不分明暗）。
 * 写入 --paper-texture，由 .paper-face/.paper-card/.toc-page/写作台纸列消费。
 */
const PAPER_TEXTURES: Record<BgTexture, string> = {
  grain:
    "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='140' height='140'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.82' numOctaves='2' stitchTiles='stitch'/%3E%3CfeColorMatrix type='saturate' values='0'/%3E%3C/filter%3E%3Crect width='140' height='140' filter='url(%23n)' opacity='0.16'/%3E%3C/svg%3E\")",
  weave:
    "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='120' height='120'%3E%3Cdefs%3E%3Cpattern id='w' width='12' height='12' patternUnits='userSpaceOnUse'%3E%3Cpath d='M0 6 Q3 3 6 6 T12 6' fill='none' stroke='%23808080' stroke-opacity='0.14' stroke-width='1'/%3E%3Cpath d='M0 12 Q3 9 6 12 T12 12' fill='none' stroke='%23808080' stroke-opacity='0.09' stroke-width='1'/%3E%3C/pattern%3E%3C/defs%3E%3Crect width='120' height='120' fill='url(%23w)'/%3E%3C/svg%3E\")",
}

const DEFAULT_APPEARANCE: Appearance = {
  theme: 'paper',
  mode: 'system',
  bg: { kind: 'theme' },
  motionLow: false,
}

function isThemeId(v: unknown): v is ThemeId {
  return typeof v === 'string' && (THEME_IDS as string[]).includes(v)
}

function parseBg(raw: unknown): BgSpec {
  if (!raw || typeof raw !== 'object') return { kind: 'theme' }
  const b = raw as Record<string, unknown>
  if (b.kind === 'color' && typeof b.color === 'string' && b.color) {
    return { kind: 'color', color: b.color, veil: clampVeil(b.veil, 0.55) }
  }
  if (b.kind === 'image' && typeof b.dataUrl === 'string' && b.dataUrl) {
    return { kind: 'image', dataUrl: b.dataUrl, veil: clampVeil(b.veil, 0.55) }
  }
  if (b.kind === 'texture' && (b.texture === 'grain' || b.texture === 'weave')) {
    return { kind: 'texture', texture: b.texture, veil: clampVeil(b.veil, 0.35) }
  }
  return { kind: 'theme' }
}

function clampVeil(v: unknown, fallback: number): number {
  const n = typeof v === 'number' ? v : fallback
  return Math.min(0.8, Math.max(0, n))
}

export function parseAppearance(raw: string | null): Appearance {
  if (!raw) return { ...DEFAULT_APPEARANCE }
  try {
    const a = JSON.parse(raw) as Record<string, unknown>
    return {
      theme: isThemeId(a.theme) ? a.theme : 'paper',
      mode: a.mode === 'light' || a.mode === 'dark' || a.mode === 'system' ? a.mode : 'system',
      bg: parseBg(a.bg),
      motionLow: a.motionLow === true,
    }
  } catch {
    return { ...DEFAULT_APPEARANCE }
  }
}

function prefersDark(): boolean {
  return typeof window.matchMedia === 'function' && window.matchMedia('(prefers-color-scheme: dark)').matches
}

function resolveDark(mode: AppearanceMode): boolean {
  if (mode === 'dark') return true
  if (mode === 'light') return false
  return prefersDark()
}

/**
 * 把外观落到 DOM。全部同步完成（index.html 内联脚本是首帧版本，本函数是运行时版本）。
 * 背景属性写在 documentElement 上（body::before/::after 经继承消费）。
 */
export function applyAppearance(ap: Appearance): void {
  const de = document.documentElement
  de.dataset.theme = ap.theme
  const dark = resolveDark(ap.mode)
  de.classList.toggle('dark', dark)
  de.classList.toggle('motion-low', ap.motionLow)

  const s = de.style
  if (ap.bg.kind === 'theme') {
    s.removeProperty('--user-bg-color')
    s.removeProperty('--user-bg-image')
    s.removeProperty('--user-bg-veil')
    s.removeProperty('--paper-texture') // 纸纹随背景种类回落 :root 的 none
    return
  }
  const veil = 'veil' in ap.bg ? (ap.bg.veil as number) : 0.55
  const veilColor = dark ? `rgba(0,0,0,${veil})` : `rgba(255,255,255,${veil})`
  if (ap.bg.kind === 'color') {
    s.setProperty('--user-bg-color', ap.bg.color)
    s.removeProperty('--user-bg-image')
    s.removeProperty('--paper-texture')
  } else if (ap.bg.kind === 'image') {
    s.removeProperty('--user-bg-color')
    s.setProperty('--user-bg-image', ap.bg.dataUrl)
    s.removeProperty('--paper-texture')
  } else {
    // texture：桌面层黑纹纸纹叠主题底色；纸面层走淡剂量变体（04 §A1）
    s.removeProperty('--user-bg-color')
    s.setProperty('--user-bg-image', TEXTURES[ap.bg.texture])
    s.setProperty('--paper-texture', PAPER_TEXTURES[ap.bg.texture])
  }
  s.setProperty('--user-bg-veil', veilColor)
}

function persist(ap: Appearance): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(ap))
  } catch {
    /* 存储满（背景图 dataURL 超限）时静默：本次会话仍生效，下次启动回默认 */
  }
}

/** 旧键迁移：velluma_theme('light'|'dark') → 新键 paper 主题对应 mode；读后删旧键 */
function migrateLegacy(): AppearanceMode | null {
  try {
    const legacy = localStorage.getItem(LEGACY_KEY)
    if (legacy === 'dark' || legacy === 'light') {
      localStorage.removeItem(LEGACY_KEY)
      return legacy
    }
  } catch {
    /* ignore */
  }
  return null
}

/* ---- 模块单例状态 ---- */
const appearanceRef = ref<Appearance>({ ...DEFAULT_APPEARANCE })
let systemWatcher: MediaQueryList | null = null

export function useAppearance() {
  const appearance = appearanceRef
  const resolvedDark = computed(() => resolveDark(appearanceRef.value.mode))

  /** 启动对齐（首帧已由 index.html 内联脚本处理，此处读存储后二次对齐 + 注册监听） */
  const initAppearance = () => {
    let ap: Appearance
    try {
      ap = parseAppearance(localStorage.getItem(STORAGE_KEY))
    } catch {
      ap = { ...DEFAULT_APPEARANCE }
    }
    const legacyMode = migrateLegacy()
    if (legacyMode && !localStorage.getItem(STORAGE_KEY)) {
      ap = { ...ap, mode: legacyMode }
    }
    appearanceRef.value = ap
    applyAppearance(ap)
    persist(ap)
    if (!systemWatcher && typeof window.matchMedia === 'function') {
      systemWatcher = window.matchMedia('(prefers-color-scheme: dark)')
      const onChange = () => {
        if (appearanceRef.value.mode === 'system') applyAppearance(appearanceRef.value)
      }
      if (typeof systemWatcher.addEventListener === 'function') {
        systemWatcher.addEventListener('change', onChange)
      } else if (typeof (systemWatcher as unknown as { addListener?: unknown }).addListener === 'function') {
        ;(systemWatcher as MediaQueryList & { addListener(l: (e: MediaQueryListEvent) => void): void }).addListener(onChange)
      }
    }
  }

  const update = (patch: Partial<Appearance>) => {
    appearanceRef.value = { ...appearanceRef.value, ...patch }
    applyAppearance(appearanceRef.value)
    persist(appearanceRef.value)
  }

  const setTheme = (theme: ThemeId) => update({ theme })
  const setMode = (mode: AppearanceMode) => update({ mode })
  const setBg = (bg: BgSpec) => update({ bg })
  const setMotionLow = (motionLow: boolean) => update({ motionLow })

  return { appearance, resolvedDark, initAppearance, setTheme, setMode, setBg, setMotionLow }
}
