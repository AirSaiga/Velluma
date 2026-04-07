<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount, watch, computed } from 'vue'
import CharacterPanel from '../../../components/CharacterPanel.vue'
import ChapterEditor from '../../../components/ChapterEditor.vue'
import CritiquePanel from '../../../components/CritiquePanel.vue'
import WorldviewSettings from '../../../components/WorldviewSettings.vue'
import MapSettings from '../../../components/MapSettings.vue'
import GoldenSnippetsManager from '../../../components/GoldenSnippetsManager.vue'
import SettingsModal from '../../../components/SettingsModal.vue'
import DebugPromptWindow from '../../../components/DebugPromptWindow.vue'
import { bookApi, characterApi, chapterApi, relationshipApi, generateApi } from '../../../services/api'
import { useTheme } from '../../../composables/useTheme'
import { useToast } from '../../../composables/useToast'
import { useConfirmDialog } from '../../../composables/useConfirmDialog'
import Toast from '../../../components/Toast.vue'
import ConfirmDialog from '../../../components/ConfirmDialog.vue'
import { loadUiPrefs, saveUiPrefs } from '../../../composables/useUiPrefs'

const { initTheme } = useTheme()
const { toasts, showToast, removeToast } = useToast()
const { visible: confirmDialogVisible, options: confirmDialogOptions, show: showConfirm, handleConfirm: handleConfirmDialog, handleCancel: handleCancelDialog } = useConfirmDialog()

const isDebugMode = computed(() => {
  const urlParams = new URLSearchParams(window.location.search)
  return urlParams.get('debug') === 'true'
})

const books = ref([])
const currentBookId = ref(null)
const selectedChapterId = ref<string | null>(null)
const characters = ref([])
const chapters = ref([])
const relationships = ref([])
const apiConfig = ref({
  provider: 'openrouter',
  api_key: '',
  base_url: '',
  model: 'google/gemini-2.0-flash-001',
  reasoning_model: '',
  creative_model: '',
  proxy_enabled: true,
  proxy_url: ''
})
const uiPrefs = ref(loadUiPrefs())
const loading = ref(false)
const critiqueResult = ref<any>(null)
const critiqueLoading = ref(false)
const editorFocusedEntity = ref('')
let editorEntityDecayTimer: ReturnType<typeof setTimeout> | null = null
const showBookModal = ref(false)
const showManageBookModal = ref(false)
const showSettingsModal = ref(false)
const notesStatus = ref('idle')
const notesError = ref('')
const localBookNotes = ref('')
const chapterEditorRef = ref<any>(null)
const bookForm = ref({ title: '', genre: '', global_sys_prompt: '', core_motifs_taboos: '' })
const manageBookForm = ref({ title: '', genre: '', core_motifs_taboos: '' })
const CURRENT_BOOK_STORAGE_KEY = 'velluma_current_book_id'

// ========== 沉浸式模式状态 ==========
const isZenMode = ref(uiPrefs.value.zenMode ?? true) // 默认开启沉浸模式
const showLeftTrigger = ref(false)
const showTopTrigger = ref(false)
const showRightTrigger = ref(false)
const leftPanelExpanded = ref(false)
const topPanelExpanded = ref(false)
const rightPanelExpanded = ref(false)
const activeFloatingTab = ref<string | null>(null)

// ========== 书籍栏状态 ==========
const showBookDropdown = ref(false)
const bookDropdownRef = ref<HTMLElement | null>(null)
let topTriggerTimer: ReturnType<typeof setTimeout> | null = null

const sortedChapters = computed(() => {
  return [...chapters.value].sort((a, b) => a.chapter_number - b.chapter_number)
})

const currentBook = computed(() => {
  return books.value.find((b) => b.id === currentBookId.value) || null
})

const selectedChapter = computed(() => {
  return chapters.value.find((c) => c.id === selectedChapterId.value) || null
})

const autoHighlightedCharacterIds = computed(() => {
  const focused = editorFocusedEntity.value.trim().toLowerCase()
  const selectedIds = selectedChapter.value?.character_ids || []
  const merged = new Set<string>(selectedIds)
  if (focused) {
    for (const char of characters.value) {
      const name = (char?.name || '').toLowerCase()
      if (name && (name.includes(focused) || focused.includes(name))) {
        merged.add(char.id)
      }
    }
  }
  return Array.from(merged)
})

const autoHighlightedCharacterNames = computed(() => {
  const idSet = new Set(autoHighlightedCharacterIds.value)
  return characters.value
    .filter((char) => idSet.has(char.id))
    .map((char) => char.name)
})

const rightTab = computed({
  get: () => uiPrefs.value.rightTab || 'characters',
  set: (val) => handleRightTabChange(val),
})

const floatingTabs = [
  { key: 'characters', label: '角色', icon: '👤', shortcut: '1' },
  { key: 'worldview', label: '规则', icon: '📜', shortcut: '2' },
  { key: 'style', label: '风格', icon: '✨', shortcut: '3' },
  { key: 'map', label: '地图', icon: '📍', shortcut: '4' },
  { key: 'critique', label: '指导', icon: '📝', shortcut: '5' },
  { key: 'notes', label: '笔记', icon: '📒', shortcut: '6' },
]

// 切换沉浸模式
function toggleZenMode() {
  isZenMode.value = !isZenMode.value
  uiPrefs.value = { ...uiPrefs.value, zenMode: isZenMode.value }
  saveUiPrefs(uiPrefs.value)
}

// 展开左侧面板
function expandLeftPanel() {
  leftPanelExpanded.value = true
  showLeftTrigger.value = false
}

// 收起左侧面板
function collapseLeftPanel() {
  leftPanelExpanded.value = false
}

// 展开顶部面板
function expandTopPanel() {
  if (topTriggerTimer) {
    clearTimeout(topTriggerTimer)
    topTriggerTimer = null
  }
  topPanelExpanded.value = true
  showTopTrigger.value = false
}

// 收起顶部面板
function collapseTopPanel() {
  topPanelExpanded.value = false
}

// 处理顶部触发条鼠标离开（添加延迟避免闪烁）
function handleTopTriggerLeave() {
  if (topTriggerTimer) clearTimeout(topTriggerTimer)
  topTriggerTimer = setTimeout(() => {
    showTopTrigger.value = false
  }, 300)
}

// 处理顶部触发条鼠标进入
function handleTopTriggerEnter() {
  if (topTriggerTimer) {
    clearTimeout(topTriggerTimer)
    topTriggerTimer = null
  }
  showTopTrigger.value = true
}

// 切换书籍下拉
function toggleBookDropdown() {
  showBookDropdown.value = !showBookDropdown.value
}

// 选择书籍
function selectBook(bookId: string) {
  currentBookId.value = bookId
  showBookDropdown.value = false
}

// 点击外部关闭书籍下拉
function handleClickOutside(e: MouseEvent) {
  if (bookDropdownRef.value && !bookDropdownRef.value.contains(e.target as Node)) {
    showBookDropdown.value = false
  }
}

// 切换右侧面板
function toggleRightPanel(tab: string) {
  if (activeFloatingTab.value === tab) {
    activeFloatingTab.value = null
    rightPanelExpanded.value = false
  } else {
    activeFloatingTab.value = tab
    rightPanelExpanded.value = true
  }
}

// 关闭右侧面板
function closeRightPanel() {
  activeFloatingTab.value = null
  rightPanelExpanded.value = false
}

// 选择章节
function selectChapter(chapterId: string) {
  selectedChapterId.value = chapterId
  // 选择后自动收起左侧面板
  if (isZenMode.value) {
    leftPanelExpanded.value = false
  }
}

watch(currentBook, (book) => {
  localBookNotes.value = book?.global_sys_prompt || ''
  notesStatus.value = 'idle'
  notesError.value = ''
}, { immediate: true })

watch(localBookNotes, () => {
  if (!currentBook.value) return
  notesStatus.value = 'dirty'
  notesError.value = ''
})

watch(chapters, (list) => {
  if (list.length === 0) {
    selectedChapterId.value = null
    return
  }
  const hasSelected = !!selectedChapterId.value && list.some((c) => c.id === selectedChapterId.value)
  if (!hasSelected) {
    selectedChapterId.value = sortedChapters.value[0].id
  }
}, { deep: true })

async function loadBooks() {
  try {
    books.value = await bookApi.getAll()
    if (books.value.length === 0) {
      currentBookId.value = null
      return
    }

    const savedBookId = localStorage.getItem(CURRENT_BOOK_STORAGE_KEY)
    const hasSavedBook = !!savedBookId && books.value.some(book => book.id === savedBookId)
    const nextBookId = hasSavedBook ? savedBookId : books.value[0].id

    if (currentBookId.value !== nextBookId) {
      currentBookId.value = nextBookId
    }
  } catch (error) {
    console.error('加载书籍失败:', error)
  }
}

async function loadCurrentBookData() {
  if (!currentBookId.value) {
    characters.value = []
    chapters.value = []
    relationships.value = []
    selectedChapterId.value = null
    return
  }

  loading.value = true
  try {
    const [chars, chaps, rels] = await Promise.all([
      characterApi.getAll(currentBookId.value),
      chapterApi.getAll(currentBookId.value),
      relationshipApi.getAll(currentBookId.value)
    ])
    characters.value = chars
    relationships.value = rels

    const chaptersWithEntities = await Promise.all(
      chaps.map(async (chapter) => {
        try {
          const entityData = await chapterApi.getEntities(chapter.id)
          return { ...chapter, character_ids: entityData.entity_ids || [] }
        } catch {
          return { ...chapter, character_ids: [] }
        }
      })
    )
    chapters.value = chaptersWithEntities
    selectedChapterId.value = chaptersWithEntities.length > 0
      ? [...chaptersWithEntities].sort((a, b) => a.chapter_number - b.chapter_number)[0].id
      : null
  } catch (error) {
    console.error('加载数据失败:', error)
  } finally {
    loading.value = false
  }
}

watch(currentBookId, (newBookId) => {
  if (newBookId) {
    localStorage.setItem(CURRENT_BOOK_STORAGE_KEY, newBookId)
  } else {
    localStorage.removeItem(CURRENT_BOOK_STORAGE_KEY)
  }
  loadCurrentBookData()
})

async function createBook() {
  if (!bookForm.value.title.trim()) return
  try {
    const newBook = await bookApi.create({
      ...bookForm.value,
      global_sys_prompt: bookForm.value.global_sys_prompt || '',
      core_motifs_taboos: bookForm.value.core_motifs_taboos || ''
    })
    books.value.push(newBook)
    currentBookId.value = newBook.id
    showBookModal.value = false
    bookForm.value = { title: '', genre: '', global_sys_prompt: '', core_motifs_taboos: '' }
  } catch (error) {
    showToast('创建失败: ' + error.message, 'error')
  }
}

async function updateBook(data) {
  if (!currentBookId.value) return
  try {
    const updated = await bookApi.update(currentBookId.value, data)
    const index = books.value.findIndex(b => b.id === currentBookId.value)
    if (index !== -1) {
      books.value[index] = updated
    }
    return updated
  } catch (error) {
    console.error('更新失败:', error)
    throw error
  }
}

async function saveBookNotes() {
  if (!currentBook.value) return
  notesStatus.value = 'saving'
  notesError.value = ''
  try {
    await updateBook({ global_sys_prompt: localBookNotes.value })
    notesStatus.value = 'saved'
    setTimeout(() => {
      if (notesStatus.value === 'saved') {
        notesStatus.value = 'idle'
      }
    }, 1400)
  } catch (error) {
    notesStatus.value = 'error'
    notesError.value = error?.message || '保存失败'
  }
}

async function updateApiConfig(data) {
  apiConfig.value = { ...apiConfig.value, ...data }
  localStorage.setItem('velluma_api_config', JSON.stringify(apiConfig.value))
}

function handleRightTabChange(tab) {
  uiPrefs.value = { ...uiPrefs.value, rightTab: tab }
  saveUiPrefs(uiPrefs.value)
}

function handleMetaCollapsedChange(val) {
  uiPrefs.value = { ...uiPrefs.value, chapterMetaCollapsed: !!val }
  saveUiPrefs(uiPrefs.value)
}

function handleBookChange(event: Event) {
  const target = event.target as HTMLSelectElement
  currentBookId.value = target.value || null
}

async function handleRequestCritique(content: string) {
  if (!content) return
  if (content.length < 10) {
    showToast('章节内容太短，无法进行审阅（至少10个字）', 'warning')
    return
  }
  
  activeFloatingTab.value = 'critique'
  rightPanelExpanded.value = true
  critiqueLoading.value = true
  critiqueResult.value = null
  
  try {
    const result = await generateApi.critiqueChapter({
      chapter_content: content,
      chapter_title: selectedChapter.value?.title || '',
      api_key: apiConfig.value.api_key,
      base_url: apiConfig.value.base_url,
      model: apiConfig.value.reasoning_model || apiConfig.value.model
    })
    critiqueResult.value = result
  } catch (error: any) {
    showToast('获取指导失败: ' + (error.message || '未知错误'), 'error')
  } finally {
    critiqueLoading.value = false
  }
}

function handleJumpToCritique(comment: any) {
  if (!comment) return
  if (chapterEditorRef.value?.scrollToCritique) {
    chapterEditorRef.value.scrollToCritique(comment)
  }
}

function handleCloseCritique() {
  critiqueResult.value = null
}

function handleEditorEntityFocus(keyword: string) {
  const nextKeyword = (keyword || '').trim()
  editorFocusedEntity.value = nextKeyword
  if (editorEntityDecayTimer) {
    clearTimeout(editorEntityDecayTimer)
    editorEntityDecayTimer = null
  }
  if (!nextKeyword) return
  editorEntityDecayTimer = setTimeout(() => {
    editorFocusedEntity.value = ''
    editorEntityDecayTimer = null
  }, 2200)
}

async function createCharacter(data, onDone) {
  if (!currentBookId.value) {
    showToast('请先创建或选择一本书籍', 'warning')
    onDone?.(false)
    return
  }
  try {
    const newChar = await characterApi.create({
      ...data,
      book_id: currentBookId.value
    })
    characters.value.push(newChar)
    onDone?.(true)
  } catch (error) {
    showToast('创建失败: ' + error.message, 'error')
    onDone?.(false)
  }
}

async function updateCharacter(id, data, onDone) {
  try {
    const updated = await characterApi.update(id, data)
    const index = characters.value.findIndex(c => c.id === id)
    if (index !== -1) {
      characters.value[index] = updated
    }
    onDone?.(true)
  } catch (error) {
    showToast('更新失败: ' + error.message, 'error')
    onDone?.(false)
  }
}

async function deleteCharacter(id) {
  try {
    await characterApi.delete(id)
    characters.value = characters.value.filter(c => c.id !== id)
  } catch (error) {
    showToast('删除失败: ' + error.message, 'error')
  }
}

async function createRelationship(data) {
  if (!currentBookId.value) {
    showToast('请先创建或选择一本书籍', 'warning')
    return
  }
  try {
    const newRel = await relationshipApi.create({
      ...data,
      book_id: currentBookId.value
    })
    relationships.value.push(newRel)
  } catch (error) {
    showToast('创建失败: ' + error.message, 'error')
  }
}

async function updateRelationship(id, data) {
  try {
    const updated = await relationshipApi.update(id, data)
    const index = relationships.value.findIndex(r => r.id === id)
    if (index !== -1) {
      relationships.value[index] = updated
    }
  } catch (error) {
    showToast('更新失败: ' + error.message, 'error')
  }
}

async function deleteRelationship(id) {
  try {
    await relationshipApi.delete(id)
    relationships.value = relationships.value.filter(r => r.id !== id)
  } catch (error) {
    showToast('删除失败: ' + error.message, 'error')
  }
}

async function createChapter(data) {
  if (!currentBookId.value) {
    showToast('请先创建或选择一本书籍', 'warning')
    return
  }
  try {
    const newChapter = await chapterApi.create({
      ...data,
      book_id: currentBookId.value
    })
    chapters.value.push(newChapter)
    selectedChapterId.value = newChapter.id
    return newChapter
  } catch (error) {
    showToast('创建失败: ' + error.message, 'error')
  }
}

async function createChapterFromOutlinePanel() {
  const maxNumber = chapters.value.length > 0
    ? Math.max(...chapters.value.map(c => c.chapter_number))
    : 0
  await createChapter({
    chapter_number: maxNumber + 1,
    chapter_name: `第${maxNumber + 1}章`,
    title: '',
    outline_text: '',
    content_text: '',
    status: 'draft'
  })
}

async function updateChapter(id, data) {
  let retries = 3
  while (retries >= 0) {
    try {
      const { character_ids, ...chapterData } = data

      if (Object.keys(chapterData).length > 0) {
        const updated = await chapterApi.update(id, chapterData)
        const index = chapters.value.findIndex(c => c.id === id)
        if (index !== -1) {
          chapters.value[index] = { ...chapters.value[index], ...updated }
        }
      }

      if (character_ids !== undefined) {
        await chapterApi.updateEntities(id, character_ids)
        const index = chapters.value.findIndex(c => c.id === id)
        if (index !== -1) {
          chapters.value[index].character_ids = character_ids
        }
      }
      break
    } catch (error) {
      const isNetworkError = error.message.includes('Failed to fetch') || error.message.toLowerCase().includes('network error')
      if (isNetworkError && retries > 0) {
        console.warn(`更新失败，正在重试 (${retries}次剩余)...`, error)
        retries--
        await new Promise(resolve => setTimeout(resolve, 1000))
        continue
      }

      showToast('更新失败: ' + error.message, 'error')
      break
    }
  }
}

async function handleIntentSave(payload: any) {
  if (!selectedChapter.value) {
    showToast('请先选择章节', 'warning')
    return
  }

  try {
    const updates = {
      creative_intents: payload.creative_intents || [],
      chapter_goals: payload.chapter_goals || [],
      selected_plan_type: payload.selected_plan_type,
      user_overrides: payload.user_overrides || {},
      word_count: payload.word_count,
      author_intent: payload.author_intent
    }

    await chapterApi.update(selectedChapter.value.id, updates)

    const index = chapters.value.findIndex(c => c.id === selectedChapter.value?.id)
    if (index !== -1) {
      chapters.value[index] = { ...chapters.value[index], ...updates }
    }

    showToast('设置已保存', 'success')
  } catch (error: any) {
    showToast('保存设置失败: ' + error.message, 'error')
  }
}

async function deleteChapter(id) {
  const target = chapters.value.find((c) => c.id === id)
  const ok = await showConfirm({ title: '确认删除', message: `确定要删除"${target?.title || '该章节'}"吗？` })
  if (!ok) return
  try {
    await chapterApi.delete(id)
    chapters.value = chapters.value.filter(c => c.id !== id)
    if (selectedChapterId.value === id) {
      selectedChapterId.value = sortedChapters.value[0]?.id || null
    }
  } catch (error) {
    showToast('删除失败: ' + error.message, 'error')
  }
}

async function generateChapterEmbedding(id) {
  const target = chapters.value.find((c) => c.id === id)
  if (!target?.summary) {
    showToast('该章节暂无摘要，请先发布章节生成摘要', 'warning')
    return
  }
  try {
    const result = await chapterApi.generateEmbedding(id, {})
    showToast(`向量生成成功！维度: ${result.vector_dim}`, 'success')
  } catch (error) {
    showToast('生成失败: ' + error.message, 'error')
  }
}

function openManageBookModal() {
  if (!currentBook.value) return
  manageBookForm.value = {
    title: currentBook.value.title || '',
    genre: currentBook.value.genre || '',
    core_motifs_taboos: currentBook.value.core_motifs_taboos || ''
  }
  showManageBookModal.value = true
}

async function saveManageBook() {
  if (!currentBookId.value) return
  if (!manageBookForm.value.title.trim()) return
  await updateBook({
    title: manageBookForm.value.title,
    genre: manageBookForm.value.genre,
    core_motifs_taboos: manageBookForm.value.core_motifs_taboos
  })
  showManageBookModal.value = false
}

async function deleteCurrentBook() {
  if (!currentBookId.value) return
  const ok = await showConfirm({
    title: '确认删除',
    message: `确定要删除书籍 "${currentBook.value?.title || ''}" 吗？此操作会删除其下所有章节与角色。`,
    warning: '此操作不可撤销'
  })
  if (!ok) return
  try {
    const deletingId = currentBookId.value
    await bookApi.delete(deletingId)
    books.value = books.value.filter(b => b.id !== deletingId)
    if (books.value.length > 0) {
      currentBookId.value = books.value[0].id
    } else {
      currentBookId.value = null
    }
    showManageBookModal.value = false
  } catch (error) {
    showToast('删除失败: ' + error.message, 'error')
  }
}

async function loadCharacters() {
  if (!currentBookId.value) return
  try {
    const chars = await characterApi.getAll(currentBookId.value)
    characters.value = chars
  } catch (error) {
    console.error('加载角色失败:', error)
  }
}

// 键盘快捷键
function handleKeyDown(e: KeyboardEvent) {
  // Ctrl/Cmd + Shift + Z: 切换沉浸模式
  if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key === 'Z') {
    e.preventDefault()
    toggleZenMode()
    return
  }
  
  // Ctrl/Cmd + 1-6: 切换右侧面板
  if ((e.ctrlKey || e.metaKey) && !e.shiftKey && e.key >= '1' && e.key <= '6') {
    e.preventDefault()
    const index = parseInt(e.key) - 1
    if (index < floatingTabs.length) {
      toggleRightPanel(floatingTabs[index].key)
    }
    return
  }
  
  // Esc: 关闭所有面板
  if (e.key === 'Escape') {
    leftPanelExpanded.value = false
    topPanelExpanded.value = false
    closeRightPanel()
    return
  }
}

onMounted(async () => {
  const savedConfig = localStorage.getItem('velluma_api_config')
  if (savedConfig) {
    apiConfig.value = JSON.parse(savedConfig)
  }
  await loadBooks()
  initTheme()
  
  // 绑定键盘事件
  window.addEventListener('keydown', handleKeyDown)
  // 绑定点击外部事件
  document.addEventListener('click', handleClickOutside)
})

onBeforeUnmount(() => {
  if (editorEntityDecayTimer) {
    clearTimeout(editorEntityDecayTimer)
    editorEntityDecayTimer = null
  }
  if (topTriggerTimer) {
    clearTimeout(topTriggerTimer)
    topTriggerTimer = null
  }
  window.removeEventListener('keydown', handleKeyDown)
  document.removeEventListener('click', handleClickOutside)
})
</script>

<template>
  <Toast :toasts="toasts" @remove="removeToast" />
  <ConfirmDialog
    :visible="confirmDialogVisible"
    :options="confirmDialogOptions"
    @confirm="handleConfirmDialog"
    @cancel="handleCancelDialog"
  />
  <DebugPromptWindow v-if="isDebugMode" />
  
  <!-- ========== 沉浸式主界面 ========== -->
  <div v-else class="immersive-app" :class="{ 'zen-mode': isZenMode }">
    
    <!-- 顶部触发条 (Zen Mode 下悬停显示) -->
    <div 
      v-if="isZenMode"
      class="top-trigger-zone"
      @mouseenter="handleTopTriggerEnter"
      @mouseleave="handleTopTriggerLeave"
    >
      <div class="top-trigger-bar" :class="{ 'visible': showTopTrigger && !topPanelExpanded }">
        <span class="trigger-book">📖 {{ currentBook?.title || '无书籍' }}</span>
        <span class="divider">|</span>
        <span>第 {{ selectedChapter?.chapter_number || '-' }} 章</span>
        <button class="expand-btn" @click.stop="expandTopPanel" title="展开工具栏">▼</button>
      </div>
    </div>
    
    <!-- 顶部展开面板 -->
    <Transition name="slide-down">
      <div v-if="!isZenMode || topPanelExpanded" class="top-panel">
        <div class="top-panel-content">
          <div class="book-selector" ref="bookDropdownRef">
            <!-- 自定义书籍下拉 -->
            <div class="custom-book-dropdown" :class="{ 'open': showBookDropdown }">
              <button 
                class="book-dropdown-trigger" 
                @click.stop="toggleBookDropdown"
                :disabled="books.length === 0"
                :title="currentBook?.title || '选择书籍'"
              >
                <span class="book-icon">📖</span>
                <span class="book-name">{{ currentBook?.title || '选择书籍' }}</span>
                <span class="dropdown-arrow" :class="{ 'open': showBookDropdown }">▼</span>
              </button>
              
              <Transition name="dropdown">
                <div v-if="showBookDropdown" class="book-dropdown-menu">
                  <div class="dropdown-header">
                    <span>我的书籍</span>
                    <span class="book-count">{{ books.length }}本</span>
                  </div>
                  <div class="book-list">
                    <button
                      v-for="book in books"
                      :key="book.id"
                      class="book-option"
                      :class="{ 'active': book.id === currentBookId }"
                      @click.stop="selectBook(book.id)"
                    >
                      <span class="book-option-title">{{ book.title }}</span>
                      <span v-if="book.genre" class="book-option-genre">{{ book.genre }}</span>
                      <span v-if="book.id === currentBookId" class="active-indicator">✓</span>
                    </button>
                    <div v-if="books.length === 0" class="empty-books">
                      暂无书籍，点击 + 创建
                    </div>
                  </div>
                </div>
              </Transition>
            </div>
            
            <button @click="showBookModal = true" class="btn-icon" title="新建书籍">+</button>
            <button @click="openManageBookModal" class="btn-icon" title="管理书籍" :disabled="!currentBookId">⚙</button>
          </div>
          
          <div class="chapter-info">
            <span class="chapter-label">
              {{ selectedChapter?.chapter_name || `第${selectedChapter?.chapter_number}章` }}
            </span>
            <input 
              :value="selectedChapter?.title" 
              @input="(e) => updateChapter(selectedChapter?.id, { title: e.target.value })"
              placeholder="章节标题..."
              class="chapter-title-input"
            />
          </div>
          
          <div class="top-actions">
            <button @click="showSettingsModal = true" class="btn-icon" title="设置">⚙️</button>
            <button @click="toggleZenMode" class="btn-icon zen-toggle" :class="{ 'active': isZenMode }" title="沉浸模式 (Ctrl+Shift+Z)">
              {{ isZenMode ? '⛶' : '⛶' }}
            </button>
          </div>
        </div>
        
        <button v-if="isZenMode" class="collapse-btn" @click="collapseTopPanel">▲</button>
      </div>
    </Transition>
    
    <!-- 主内容区 -->
    <div class="main-area">
      <!-- 左侧触发条 (Zen Mode) -->
      <div 
        v-if="isZenMode && !leftPanelExpanded"
        class="left-trigger"
        @mouseenter="showLeftTrigger = true"
        @mouseleave="showLeftTrigger = false"
        @click="expandLeftPanel"
      >
        <div class="left-trigger-content" :class="{ 'visible': showLeftTrigger }">
          <div class="chapter-dots">
            <div 
              v-for="ch in sortedChapters" 
              :key="ch.id"
              class="chapter-dot"
              :class="{ 'active': ch.id === selectedChapterId }"
              :title="ch.title || `第${ch.chapter_number}章`"
            />
          </div>
          <span class="trigger-label">章节</span>
        </div>
      </div>
      
      <!-- 左侧面板 -->
      <Transition name="slide-left">
        <div v-if="!isZenMode || leftPanelExpanded" class="left-panel">
          <div class="left-panel-header">
            <h3>📚 章节</h3>
            <button v-if="isZenMode" class="btn-icon" @click="collapseLeftPanel">←</button>
          </div>
          
          <div class="chapters-list">
            <div 
              v-for="chapter in sortedChapters"
              :key="chapter.id"
              class="chapter-item"
              :class="{ 'active': chapter.id === selectedChapterId }"
              @click="selectChapter(chapter.id)"
            >
              <span class="ch-number">{{ chapter.chapter_number }}</span>
              <span class="ch-title">{{ chapter.title || '(无标题)' }}</span>
            </div>
          </div>
          
          <button @click="createChapterFromOutlinePanel" class="btn-primary">
            + 新建章节
          </button>
        </div>
      </Transition>
      
      <!-- 编辑器区域 -->
      <div class="editor-container">
        <ChapterEditor
          ref="chapterEditorRef"
          :selected-chapter="selectedChapter"
          :characters="characters"
          :api-config="apiConfig"
          :book-id="currentBookId"
          :meta-collapsed="uiPrefs.chapterMetaCollapsed"
          :critique-result="critiqueResult"
          @update-chapter="updateChapter"
          @update-meta-collapsed="handleMetaCollapsedChange"
          @refresh-characters="loadCharacters"
          @editor-entity-focus="handleEditorEntityFocus"
          @request-critique="handleRequestCritique"
          @intent-save="handleIntentSave"
        />
      </div>
      
      <!-- 右侧悬浮工具栏 -->
      <div class="right-floating-bar" :class="{ 'panel-open': rightPanelExpanded }">
        <div class="floating-tabs">
          <button
            v-for="tab in floatingTabs"
            :key="tab.key"
            class="floating-tab"
            :class="{ 'active': activeFloatingTab === tab.key }"
            @click="toggleRightPanel(tab.key)"
            :title="`${tab.label} (Ctrl+${tab.shortcut})`"
          >
            <span class="tab-icon">{{ tab.icon }}</span>
            <span class="tab-shortcut">{{ tab.shortcut }}</span>
          </button>
        </div>
      </div>
      
      <!-- 右侧面板内容 -->
      <Transition name="slide-right">
        <div v-if="rightPanelExpanded" class="right-panel">
          <div class="right-panel-header">
            <span>{{ floatingTabs.find(t => t.key === activeFloatingTab)?.label }}</span>
            <button class="btn-icon" @click="closeRightPanel">×</button>
          </div>
          
          <div class="right-panel-content">
            <CharacterPanel
              v-if="activeFloatingTab === 'characters'"
              :characters="characters"
              :relationships="relationships"
              :selected-chapter-id="selectedChapterId"
              :prioritized-character-ids="autoHighlightedCharacterIds"
              :focused-entity="editorFocusedEntity"
              :api-config="apiConfig"
              @create-character="createCharacter"
              @update-character="updateCharacter"
              @delete-character="deleteCharacter"
              @create-relationship="createRelationship"
              @update-relationship="updateRelationship"
              @delete-relationship="deleteRelationship"
            />
            
            <WorldviewSettings
              v-else-if="activeFloatingTab === 'worldview'"
              :book-id="currentBookId"
            />
            
            <GoldenSnippetsManager
              v-else-if="activeFloatingTab === 'style'"
              :book-id="currentBookId"
            />
            
            <MapSettings
              v-else-if="activeFloatingTab === 'map'"
              :chapter="selectedChapter"
              :focused-entity="editorFocusedEntity"
              :active-character-names="autoHighlightedCharacterNames"
              @update-chapter="updateChapter"
            />
            
            <CritiquePanel
              v-else-if="activeFloatingTab === 'critique'"
              :result="critiqueResult"
              :loading="critiqueLoading"
              @jump-to-critique="handleJumpToCritique"
              @close-critique="handleCloseCritique"
            />
            
            <div v-else-if="activeFloatingTab === 'notes'" class="notes-panel">
              <textarea
                v-model="localBookNotes"
                placeholder="记录创作笔记..."
              />
              <button @click="saveBookNotes" :disabled="notesStatus === 'saving'">
                {{ notesStatus === 'saved' ? '已保存' : '保存' }}
              </button>
            </div>
          </div>
        </div>
      </Transition>
    </div>
    
    <!-- 底部状态栏 (Zen Mode 下极简) -->
    <div class="status-bar" :class="{ 'minimal': isZenMode }">
      <span v-if="!isZenMode">{{ currentBook?.title }} | 第 {{ selectedChapter?.chapter_number || '-' }} 章</span>
      <span v-else>{{ selectedChapter?.chapter_number || '-' }} / {{ sortedChapters.length }}</span>
      <span v-if="isZenMode" class="zen-hint">Ctrl+Shift+Z 退出沉浸</span>
    </div>
    
    <!-- ========== 模态框 ========== -->
    
    <!-- 新建书籍 -->
    <div v-if="showBookModal" class="modal-overlay" @click.self="showBookModal = false">
      <div class="modal">
        <h3>新建书籍</h3>
        <input v-model="bookForm.title" placeholder="书名" />
        <input v-model="bookForm.genre" placeholder="类型 (如：科幻、奇幻)" />
        <textarea v-model="bookForm.global_sys_prompt" placeholder="全局提示词 (可选)" rows="3" />
        <div class="modal-actions">
          <button @click="showBookModal = false">取消</button>
          <button @click="createBook" class="btn-primary">创建</button>
        </div>
      </div>
    </div>
    
    <!-- 管理书籍 -->
    <div v-if="showManageBookModal" class="modal-overlay" @click.self="showManageBookModal = false">
      <div class="modal">
        <h3>管理书籍</h3>
        <input v-model="manageBookForm.title" placeholder="书名" />
        <input v-model="manageBookForm.genre" placeholder="类型" />
        <textarea v-model="manageBookForm.core_motifs_taboos" placeholder="核心设定与禁忌" rows="3" />
        <div class="modal-actions">
          <button @click="deleteCurrentBook" class="btn-danger">删除书籍</button>
          <button @click="showManageBookModal = false">取消</button>
          <button @click="saveManageBook" class="btn-primary">保存</button>
        </div>
      </div>
    </div>
    
    <!-- 设置 -->
    <SettingsModal
      :is-open="showSettingsModal"
      :config="apiConfig"
      @close="showSettingsModal = false"
      @save="updateApiConfig"
    />
  </div>
</template>

<style scoped>
/* ========== 基础布局 ========== */
.immersive-app {
  position: fixed;
  inset: 0;
  display: flex;
  flex-direction: column;
  background: var(--bg-canvas, #faf8f5);
  font-family: system-ui, -apple-system, sans-serif;
}

/* ========== Zen Mode ========== */
.zen-mode {
  --panel-bg: rgba(255, 255, 255, 0.95);
  --panel-shadow: 0 8px 32px rgba(0, 0, 0, 0.12);
}

/* ========== 顶部触发条 ========== */
.top-trigger-zone {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  height: 20px;
  z-index: 100;
  cursor: default;
}

.top-trigger-bar {
  position: absolute;
  top: 0;
  left: 50%;
  transform: translateX(-50%) translateY(-100%);
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 20px;
  background: var(--panel-bg);
  backdrop-filter: blur(12px);
  border-radius: 0 0 16px 16px;
  box-shadow: var(--panel-shadow);
  font-size: 14px;
  color: var(--text-secondary, #666);
  transition: transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
  max-width: 80vw;
}

.top-trigger-bar.visible {
  transform: translateX(-50%) translateY(0);
}

.top-trigger-bar .trigger-book {
  font-weight: 500;
  max-width: 200px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.top-trigger-bar .divider {
  opacity: 0.3;
}

.expand-btn {
  background: none;
  border: none;
  cursor: pointer;
  padding: 4px 8px;
  margin-left: 4px;
  opacity: 0.5;
  transition: all 0.2s;
  border-radius: 4px;
}

.expand-btn:hover {
  opacity: 1;
  background: rgba(0,0,0,0.05);
}

/* ========== 顶部面板 ========== */
.top-panel {
  position: relative;
  flex-shrink: 0;
  background: var(--bg-primary, #fff);
  border-bottom: 1px solid var(--border-color, #e8e4df);
  padding: 12px 20px;
}

.top-panel-content {
  display: flex;
  align-items: center;
  gap: 20px;
  max-width: 1600px;
  margin: 0 auto;
}

.book-selector {
  display: flex;
  align-items: center;
  gap: 8px;
  position: relative;
}

/* 自定义书籍下拉 */
.custom-book-dropdown {
  position: relative;
}

.book-dropdown-trigger {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 14px;
  background: var(--bg-panel);
  border: 1px solid var(--border-color);
  border-radius: 10px;
  font-size: 14px;
  cursor: pointer;
  transition: all 0.2s;
  min-width: 180px;
  max-width: 260px;
}

.book-dropdown-trigger:hover:not(:disabled) {
  border-color: var(--accent-500);
  background: var(--bg-canvas);
}

.book-dropdown-trigger:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.custom-book-dropdown.open .book-dropdown-trigger {
  border-color: var(--accent-500);
  box-shadow: 0 0 0 3px rgba(212, 165, 116, 0.15);
}

.book-icon {
  font-size: 16px;
  flex-shrink: 0;
}

.book-name {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  text-align: left;
  font-weight: 500;
}

.dropdown-arrow {
  font-size: 10px;
  transition: transform 0.2s;
  opacity: 0.6;
}

.dropdown-arrow.open {
  transform: rotate(180deg);
}

.book-dropdown-menu {
  position: absolute;
  top: calc(100% + 6px);
  left: 0;
  min-width: 260px;
  max-width: 320px;
  background: var(--panel-bg);
  backdrop-filter: blur(12px);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  box-shadow: 0 10px 40px rgba(0, 0, 0, 0.15);
  z-index: 200;
  overflow: hidden;
}

.dropdown-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border-color);
  font-size: 12px;
  font-weight: 600;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.book-count {
  font-size: 11px;
  background: var(--bg-canvas);
  padding: 2px 8px;
  border-radius: 10px;
}

.book-list {
  max-height: 280px;
  overflow-y: auto;
  padding: 6px;
}

.book-option {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  padding: 10px 12px;
  border: none;
  border-radius: 8px;
  background: transparent;
  cursor: pointer;
  text-align: left;
  transition: all 0.15s;
  font-size: 14px;
}

.book-option:hover {
  background: var(--bg-canvas);
}

.book-option.active {
  background: var(--accent-100);
  color: var(--accent-700);
}

.book-option-title {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.book-option-genre {
  font-size: 11px;
  color: var(--text-muted);
  background: var(--bg-panel);
  padding: 2px 8px;
  border-radius: 10px;
  flex-shrink: 0;
}

.book-option.active .book-option-genre {
  background: rgba(255,255,255,0.5);
}

.active-indicator {
  font-size: 12px;
  width: 20px;
  height: 20px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--accent-500);
  color: white;
  border-radius: 50%;
  flex-shrink: 0;
}

.empty-books {
  padding: 24px 16px;
  text-align: center;
  color: var(--text-muted);
  font-size: 13px;
}

/* 下拉动画 */
.dropdown-enter-active,
.dropdown-leave-active {
  transition: all 0.2s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.dropdown-enter-from,
.dropdown-leave-to {
  opacity: 0;
  transform: translateY(-8px) scale(0.96);
}

.chapter-info {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 12px;
}

.chapter-label {
  font-weight: 600;
  color: var(--text-primary);
}

.chapter-title-input {
  flex: 1;
  max-width: 400px;
  padding: 6px 12px;
  border: 1px solid transparent;
  border-radius: 8px;
  background: transparent;
  font-size: 14px;
  transition: all 0.2s;
}

.chapter-title-input:hover,
.chapter-title-input:focus {
  border-color: var(--border-color);
  background: var(--bg-panel);
  outline: none;
}

.top-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.collapse-btn {
  position: absolute;
  bottom: -20px;
  left: 50%;
  transform: translateX(-50%);
  padding: 4px 16px;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-top: none;
  border-radius: 0 0 8px 8px;
  font-size: 10px;
  cursor: pointer;
  opacity: 0.5;
  transition: opacity 0.2s;
}

.collapse-btn:hover {
  opacity: 1;
}

/* ========== 主内容区 ========== */
.main-area {
  flex: 1;
  display: flex;
  overflow: hidden;
  position: relative;
}

/* ========== 左侧触发条 ========== */
.left-trigger {
  position: absolute;
  left: 0;
  top: 0;
  bottom: 40px;
  width: 8px;
  z-index: 50;
  cursor: pointer;
}

.left-trigger-content {
  position: absolute;
  left: 0;
  top: 50%;
  transform: translateY(-50%) translateX(-100%);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 16px 8px;
  background: var(--panel-bg);
  backdrop-filter: blur(12px);
  border-radius: 0 12px 12px 0;
  box-shadow: var(--panel-shadow);
  transition: transform 0.3s ease;
}

.left-trigger-content.visible {
  transform: translateY(-50%) translateX(0);
}

.chapter-dots {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.chapter-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--text-muted, #999);
  opacity: 0.4;
  transition: all 0.2s;
}

.chapter-dot.active {
  background: var(--accent-500, #d4a574);
  opacity: 1;
  transform: scale(1.3);
}

.trigger-label {
  font-size: 10px;
  color: var(--text-muted);
  writing-mode: vertical-rl;
  text-orientation: mixed;
  letter-spacing: 4px;
}

/* ========== 左侧面板 ========== */
.left-panel {
  width: 240px;
  flex-shrink: 0;
  background: var(--bg-primary);
  border-right: 1px solid var(--border-color);
  display: flex;
  flex-direction: column;
  padding: 16px;
}

.left-panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
}

.left-panel-header h3 {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
}

.chapters-list {
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-bottom: 12px;
}

.chapter-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.15s;
  font-size: 13px;
}

.chapter-item:hover {
  background: var(--bg-panel, #f5f3f0);
}

.chapter-item.active {
  background: var(--accent-100, #f0e6d9);
  color: var(--accent-700, #8b6914);
}

.ch-number {
  font-weight: 600;
  font-size: 12px;
  opacity: 0.6;
  min-width: 24px;
}

.ch-title {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* ========== 编辑器容器 ========== */
.editor-container {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  padding: 20px;
}

.zen-mode .editor-container {
  padding: 40px 60px;
}

/* ========== 右侧悬浮工具栏 ========== */
.right-floating-bar {
  position: absolute;
  right: 16px;
  top: 50%;
  transform: translateY(-50%);
  z-index: 40;
  transition: right 0.3s ease;
}

.right-floating-bar.panel-open {
  right: 336px;
}

.floating-tabs {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 8px;
  background: var(--panel-bg);
  backdrop-filter: blur(12px);
  border-radius: 16px;
  box-shadow: var(--panel-shadow);
}

.floating-tab {
  position: relative;
  width: 44px;
  height: 44px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 2px;
  border: none;
  border-radius: 12px;
  background: transparent;
  cursor: pointer;
  transition: all 0.2s;
}

.floating-tab:hover {
  background: var(--bg-panel);
}

.floating-tab.active {
  background: var(--accent-500);
  color: white;
}

.tab-icon {
  font-size: 18px;
  line-height: 1;
}

.tab-shortcut {
  font-size: 9px;
  opacity: 0.6;
}

/* ========== 右侧面板 ========== */
.right-panel {
  position: absolute;
  right: 0;
  top: 0;
  bottom: 0;
  width: 320px;
  background: var(--panel-bg);
  backdrop-filter: blur(12px);
  box-shadow: -4px 0 24px rgba(0, 0, 0, 0.08);
  display: flex;
  flex-direction: column;
  z-index: 35;
}

.right-panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px;
  border-bottom: 1px solid var(--border-color);
  font-weight: 600;
  font-size: 14px;
}

.right-panel-content {
  flex: 1;
  overflow-y: auto;
  padding: 16px 20px;
}

/* ========== 状态栏 ========== */
.status-bar {
  flex-shrink: 0;
  padding: 8px 20px;
  background: var(--bg-primary);
  border-top: 1px solid var(--border-color);
  font-size: 12px;
  color: var(--text-muted);
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.status-bar.minimal {
  padding: 6px 20px;
  background: transparent;
  border-top: none;
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  pointer-events: none;
}

.status-bar.minimal .zen-hint {
  opacity: 0;
  transition: opacity 0.3s;
}

.status-bar.minimal:hover .zen-hint {
  opacity: 0.6;
}

/* ========== 通用按钮样式 ========== */
.btn-icon {
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: none;
  border-radius: 8px;
  background: transparent;
  cursor: pointer;
  font-size: 16px;
  transition: all 0.2s;
}

.btn-icon:hover:not(:disabled) {
  background: var(--bg-panel);
}

.btn-icon:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.btn-icon.zen-toggle.active {
  background: var(--accent-100);
  color: var(--accent-700);
}

.btn-primary {
  padding: 10px 16px;
  background: var(--accent-500);
  color: white;
  border: none;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-primary:hover {
  background: var(--accent-600);
}

.btn-danger {
  padding: 10px 16px;
  background: #dc2626;
  color: white;
  border: none;
  border-radius: 8px;
  font-size: 13px;
  cursor: pointer;
}

/* ========== 模态框 ========== */
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 200;
}

.modal {
  background: var(--bg-primary);
  padding: 24px;
  border-radius: 16px;
  width: 90%;
  max-width: 480px;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.2);
}

.modal h3 {
  margin: 0 0 16px 0;
  font-size: 18px;
}

.modal input,
.modal textarea {
  width: 100%;
  padding: 10px 14px;
  margin-bottom: 12px;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  background: var(--bg-panel);
  font-size: 14px;
}

.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 16px;
}

.modal-actions button {
  padding: 8px 16px;
  border: none;
  border-radius: 8px;
  background: var(--bg-panel);
  cursor: pointer;
  font-size: 13px;
}

/* ========== 笔记面板 ========== */
.notes-panel {
  height: 100%;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.notes-panel textarea {
  flex: 1;
  padding: 12px;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  background: var(--bg-panel);
  resize: none;
  font-size: 13px;
  line-height: 1.6;
}

/* ========== 过渡动画 ========== */
.slide-down-enter-active,
.slide-down-leave-active {
  transition: all 0.3s ease;
}

.slide-down-enter-from,
.slide-down-leave-to {
  opacity: 0;
  transform: translateY(-20px);
}

.slide-left-enter-active,
.slide-left-leave-active {
  transition: all 0.3s ease;
}

.slide-left-enter-from,
.slide-left-leave-to {
  opacity: 0;
  transform: translateX(-20px);
}

.slide-right-enter-active,
.slide-right-leave-active {
  transition: all 0.3s ease;
}

.slide-right-enter-from,
.slide-right-leave-to {
  opacity: 0;
  transform: translateX(20px);
}

/* ========== 滚动条样式 ========== */
::-webkit-scrollbar {
  width: 6px;
  height: 6px;
}

::-webkit-scrollbar-track {
  background: transparent;
}

::-webkit-scrollbar-thumb {
  background: var(--text-muted, #999);
  border-radius: 3px;
  opacity: 0.3;
}

::-webkit-scrollbar-thumb:hover {
  opacity: 0.6;
}

/* ========== 响应式 ========== */
@media (max-width: 768px) {
  .right-floating-bar {
    right: 8px;
  }
  
  .floating-tabs {
    padding: 6px;
  }
  
  .floating-tab {
    width: 38px;
    height: 38px;
  }
  
  .editor-container {
    padding: 16px;
  }
}
</style>
