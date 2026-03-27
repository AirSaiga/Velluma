const STORAGE_KEY = 'velluma_ui_prefs_v1'

const DEFAULT_PREFS = {
  version: 1,
  splitSizes: [22, 56, 22],
  rightTab: 'characters',
  chapterMetaCollapsed: false,
  sidebarCollapsed: false,
  rightDrawerOpen: false,
}

export type UiPrefs = typeof DEFAULT_PREFS

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

