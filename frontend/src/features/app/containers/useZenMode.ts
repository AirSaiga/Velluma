import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import type { UiPrefs } from '../../../composables/useUiPrefs'

export interface FloatingTab {
  key: string
  label: string
  icon: string
  shortcut: string
}

export function useZenMode(options: {
  uiPrefs: { value: UiPrefs }
  onToggleZenMode: () => void
  saveUiPrefs: (prefs: UiPrefs) => void
  onSelectBook: (bookId: string) => void
  closeRightPanel: () => void
}) {
  const { uiPrefs, onToggleZenMode, saveUiPrefs, onSelectBook, closeRightPanel } = options

  const isZenMode = ref(uiPrefs.value.zenMode ?? true)
  const showLeftTrigger = ref(false)
  const showTopTrigger = ref(false)
  const leftPanelExpanded = ref(false)
  const topPanelExpanded = ref(false)
  const rightPanelExpanded = ref(false)
  const activeFloatingTab = ref<string | null>(null)

  const showBookDropdown = ref(false)
  const bookDropdownRef = ref<HTMLElement | null>(null)
  let topTriggerTimer: ReturnType<typeof setTimeout> | null = null

  const floatingTabs: FloatingTab[] = [
    { key: 'characters', label: '角色', icon: 'users', shortcut: '1' },
    { key: 'worldview', label: '规则', icon: 'book-open', shortcut: '2' },
    { key: 'style', label: '风格', icon: 'sparkles', shortcut: '3' },
    { key: 'map', label: '地图', icon: 'map-pin', shortcut: '4' },
    { key: 'critique', label: '指导', icon: 'light-bulb', shortcut: '5' },
    { key: 'notes', label: '笔记', icon: 'pencil-square', shortcut: '6' },
    { key: 'assets', label: '资产', icon: 'archive', shortcut: '7' },
  ]

  const rightTab = computed({
    get: () => uiPrefs.value.rightTab || 'characters',
    set: (val: string) => handleRightTabChange(val),
  })

  function toggleZenMode() {
    isZenMode.value = !isZenMode.value
    uiPrefs.value = { ...uiPrefs.value, zenMode: isZenMode.value }
    saveUiPrefs(uiPrefs.value)
    onToggleZenMode()
  }

  function expandLeftPanel() {
    leftPanelExpanded.value = true
    showLeftTrigger.value = false
  }

  function collapseLeftPanel() {
    leftPanelExpanded.value = false
  }

  function expandTopPanel() {
    if (topTriggerTimer) {
      clearTimeout(topTriggerTimer)
      topTriggerTimer = null
    }
    topPanelExpanded.value = true
    showTopTrigger.value = false
  }

  function collapseTopPanel() {
    topPanelExpanded.value = false
  }

  function handleTopTriggerLeave() {
    if (topTriggerTimer) clearTimeout(topTriggerTimer)
    topTriggerTimer = setTimeout(() => {
      showTopTrigger.value = false
    }, 300)
  }

  function handleTopTriggerEnter() {
    if (topTriggerTimer) {
      clearTimeout(topTriggerTimer)
      topTriggerTimer = null
    }
    showTopTrigger.value = true
  }

  function toggleBookDropdown() {
    showBookDropdown.value = !showBookDropdown.value
  }

  function selectBook(bookId: string) {
    showBookDropdown.value = false
    onSelectBook(bookId)
  }

  function handleClickOutside(e: MouseEvent) {
    if (bookDropdownRef.value && !bookDropdownRef.value.contains(e.target as Node)) {
      showBookDropdown.value = false
    }
  }

  function toggleRightPanel(tab: string) {
    if (activeFloatingTab.value === tab) {
      activeFloatingTab.value = null
      rightPanelExpanded.value = false
    } else {
      activeFloatingTab.value = tab
      rightPanelExpanded.value = true
    }
  }

  function closeRightPanelLocal() {
    activeFloatingTab.value = null
    rightPanelExpanded.value = false
    closeRightPanel()
  }

  function handleRightTabChange(tab: string) {
    uiPrefs.value = { ...uiPrefs.value, rightTab: tab }
    saveUiPrefs(uiPrefs.value)
  }

  function handleKeyDown(e: KeyboardEvent) {
    if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key === 'Z') {
      e.preventDefault()
      toggleZenMode()
      return
    }

    if ((e.ctrlKey || e.metaKey) && !e.shiftKey && e.key >= '1' && e.key <= '7') {
      e.preventDefault()
      const index = parseInt(e.key) - 1
      if (index < floatingTabs.length) {
        toggleRightPanel(floatingTabs[index].key)
      }
      return
    }

    if (e.key === 'Escape') {
      leftPanelExpanded.value = false
      topPanelExpanded.value = false
      closeRightPanelLocal()
    }
  }

  onMounted(() => {
    window.addEventListener('keydown', handleKeyDown)
    document.addEventListener('click', handleClickOutside)
  })

  onBeforeUnmount(() => {
    if (topTriggerTimer) {
      clearTimeout(topTriggerTimer)
      topTriggerTimer = null
    }
    window.removeEventListener('keydown', handleKeyDown)
    document.removeEventListener('click', handleClickOutside)
  })

  return {
    isZenMode,
    showLeftTrigger,
    showTopTrigger,
    leftPanelExpanded,
    topPanelExpanded,
    rightPanelExpanded,
    activeFloatingTab,
    floatingTabs,
    showBookDropdown,
    bookDropdownRef,
    rightTab,
    toggleZenMode,
    selectBook,
    expandLeftPanel,
    collapseLeftPanel,
    expandTopPanel,
    collapseTopPanel,
    handleTopTriggerLeave,
    handleTopTriggerEnter,
    toggleBookDropdown,
    handleClickOutside,
    toggleRightPanel,
    closeRightPanel: closeRightPanelLocal,
    handleRightTabChange,
    handleKeyDown,
  }
}
