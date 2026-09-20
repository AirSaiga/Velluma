const STORAGE_KEY = 'velluma_ui_prefs_v1'

import { ref } from 'vue'

const DEFAULT_PREFS = {
  version: 1,
  splitSizes: [22, 56, 22],
  rightTab: 'characters',
  chapterMetaCollapsed: false,
  sidebarCollapsed: false,
  rightDrawerOpen: false,
  chapterDirPinned: false,
  zenMode: true,
  worldSliceCollapsed: false,
  worldReaderView: false,
  /** 开章卡（01 下一阶段）：空章「打算」页顶部的四面镜子；关掉=写作体验与现状一致 */
  openingCardEnabled: true,
  /** 渐进引导（引导体系重构 2026-09-20）：各就地提示的已看次数——看过 N 次自动淡出 */
  hintsSeen: {} as Record<string, number>,
}

export type UiPrefs = typeof DEFAULT_PREFS

/**
 * 开章卡开关的响应式镜像（GUI 交叉验证缺陷 #1a 修复）：localStorage 读取不具
 * 响应性，computed 直接读 loadUiPrefs() 在切换开关后不会失效——卡要等切章/
 * 字数变化才消失，违反设计稿「关掉即整块消失」。唯一写口=setOpeningCardEnabled
 * （同时写镜像与存储）；消费面（InspectorPanel）读 ref 即时生效。
 */
export const openingCardEnabled = ref(loadUiPrefs().openingCardEnabled)

export function setOpeningCardEnabled(v: boolean): void {
  openingCardEnabled.value = v
  saveUiPrefs({ ...loadUiPrefs(), openingCardEnabled: v })
}

export function loadUiPrefs(): UiPrefs {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return { ...DEFAULT_PREFS }
    const parsed = JSON.parse(raw)
    if (!parsed || parsed.version !== 1) return { ...DEFAULT_PREFS }
    const normalizedRightTab = parsed.rightTab === 'prompt'
      ? 'notes'
      : parsed.rightTab === 'book'
        ? 'notes'
        : parsed.rightTab
    return {
      ...DEFAULT_PREFS,
      ...parsed,
      rightTab: normalizedRightTab || DEFAULT_PREFS.rightTab,
      splitSizes: Array.isArray(parsed.splitSizes) && parsed.splitSizes.length === 3 ? parsed.splitSizes : DEFAULT_PREFS.splitSizes,
      hintsSeen: { ...DEFAULT_PREFS.hintsSeen, ...(parsed.hintsSeen || {}) },
    }
  } catch {
    return { ...DEFAULT_PREFS }
  }
}

export function saveUiPrefs(prefs: UiPrefs) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(prefs))
}

export function resetUiPrefs() {
  localStorage.removeItem(STORAGE_KEY)
}

