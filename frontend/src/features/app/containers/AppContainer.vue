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
import Icon from '../../../components/Icon.vue'
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
  { key: 'characters', label: '角色', icon: 'users', shortcut: '1' },
  { key: 'worldview', label: '规则', icon: 'book-open', shortcut: '2' },
  { key: 'style', label: '风格', icon: 'sparkles', shortcut: '3' },
  { key: 'map', label: '地图', icon: 'map-pin', shortcut: '4' },
  { key: 'critique', label: '指导', icon: 'light-bulb', shortcut: '5' },
  { key: 'notes', label: '笔记', icon: 'pencil-square', shortcut: '6' },
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
        <Icon name="book" :size="14" class="trigger-icon" />
        <span class="trigger-book">{{ currentBook?.title || '选择书籍开始创作' }}</span>
        <template v-if="currentBook && selectedChapter">
          <span class="divider"></span>
          <span>第 {{ selectedChapter.chapter_number }} 章</span>
        </template>
        <button class="expand-btn" @click.stop="expandTopPanel" title="展开工具栏">
          <Icon name="chevron-down" :size="12" />
        </button>
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
                <Icon name="book" :size="16" class="book-icon" />
                <span class="book-name">{{ currentBook?.title || '选择书籍' }}</span>
                <Icon name="chevron-down" :size="12" class="dropdown-arrow" :class="{ 'open': showBookDropdown }" />
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
                      <Icon v-if="book.id === currentBookId" name="check" :size="14" class="active-indicator" />
                    </button>
                    <div v-if="books.length === 0" class="empty-books">
                      暂无书籍，点击 + 创建
                    </div>
                  </div>
                </div>
              </Transition>
            </div>
            
            <button @click="showBookModal = true" class="btn-icon" title="新建书籍">
              <Icon name="plus" :size="18" />
            </button>
            <button @click="openManageBookModal" class="btn-icon" title="管理书籍" :disabled="!currentBookId">
              <Icon name="pencil" :size="16" />
            </button>
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
            <button @click="showSettingsModal = true" class="btn-icon" title="设置">
              <Icon name="settings" :size="16" />
            </button>
            <button @click="toggleZenMode" class="btn-icon zen-toggle" :class="{ 'active': isZenMode }" title="沉浸模式 (Ctrl+Shift+Z)">
              <Icon name="maximize" :size="16" />
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
            <h3><Icon name="document" :size="12" /> 章节</h3>
            <button v-if="isZenMode" class="btn-icon" @click="collapseLeftPanel">
              <Icon name="chevron-left" :size="16" />
            </button>
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
            <Icon :name="tab.icon" :size="18" class="tab-icon-svg" />
            <span class="tab-shortcut">{{ tab.shortcut }}</span>
          </button>
        </div>
      </div>
      
      <!-- 右侧面板内容 -->
      <Transition name="slide-right">
        <div v-if="rightPanelExpanded" class="right-panel">
          <div class="right-panel-header">
            <span>{{ floatingTabs.find(t => t.key === activeFloatingTab)?.label }}</span>
            <button class="btn-icon" @click="closeRightPanel">
              <Icon name="close" :size="18" />
            </button>
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
      <span v-if="!isZenMode">
        <template v-if="currentBook">
          {{ currentBook.title }} · 第 {{ selectedChapter?.chapter_number || '-' }} 章
        </template>
        <template v-else>未选择书籍</template>
      </span>
      <span v-else>第 {{ selectedChapter?.chapter_number || '-' }} 章，共 {{ sortedChapters.length }} 章</span>
      <span v-if="isZenMode" class="zen-hint">按 Ctrl+Shift+Z 退出沉浸模式</span>
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
/* ========================================
   Design System - 极简优雅风格
   ======================================== */

/* ---------- CSS 变量 ---------- */
.immersive-app {
  /* 颜色系统 - 柔和的暖灰色调 */
  --color-bg-canvas: #faf9f7;
  --color-bg-primary: #ffffff;
  --color-bg-secondary: #f5f4f2;
  --color-bg-tertiary: #edebe8;
  
  /* 文字颜色 */
  --color-text-primary: #1a1a1a;
  --color-text-secondary: #5c5c5c;
  --color-text-tertiary: #8a8a8a;
  --color-text-muted: #a8a8a8;
  
  /* 强调色 - 柔和的茶色 */
  --color-accent: #c4a77d;
  --color-accent-light: #e8dcc8;
  --color-accent-dark: #9a7d5a;
  
  /* 边框 */
  --color-border: rgba(0, 0, 0, 0.06);
  --color-border-hover: rgba(0, 0, 0, 0.12);
  
  /* 阴影层级 */
  --shadow-xs: 0 1px 2px rgba(0, 0, 0, 0.02);
  --shadow-sm: 0 2px 8px rgba(0, 0, 0, 0.04);
  --shadow-md: 0 4px 16px rgba(0, 0, 0, 0.06);
  --shadow-lg: 0 8px 32px rgba(0, 0, 0, 0.08);
  --shadow-xl: 0 16px 48px rgba(0, 0, 0, 0.12);
  
  /* 字体大小 - 4px网格 */
  --text-xs: 11px;    /* 辅助文字 */
  --text-sm: 13px;    /* 次要文字 */
  --text-base: 14px;  /* 正文 */
  --text-md: 15px;    /* 强调正文 */
  --text-lg: 17px;    /* 小标题 */
  --text-xl: 20px;    /* 章节标题 */
  
  /* 行高 */
  --leading-tight: 1.25;
  --leading-normal: 1.5;
  --leading-relaxed: 1.75;
  
  /* 间距 - 4px网格 */
  --space-1: 4px;
  --space-2: 8px;
  --space-3: 12px;
  --space-4: 16px;
  --space-5: 20px;
  --space-6: 24px;
  --space-8: 32px;
  
  /* 圆角 */
  --radius-sm: 6px;
  --radius-md: 10px;
  --radius-lg: 14px;
  --radius-xl: 20px;
  --radius-full: 9999px;
  
  /* 过渡 */
  --transition-fast: 150ms ease;
  --transition-normal: 250ms cubic-bezier(0.4, 0, 0.2, 1);
  --transition-slow: 350ms cubic-bezier(0.4, 0, 0.2, 1);
  
  /* 应用变量 */
  --bg-canvas: var(--color-bg-canvas);
  --bg-primary: var(--color-bg-primary);
  --bg-panel: var(--color-bg-secondary);
  --text-primary: var(--color-text-primary);
  --text-secondary: var(--color-text-secondary);
  --text-muted: var(--color-text-tertiary);
  --border-color: var(--color-border);
  --accent-500: var(--color-accent);
  --accent-100: var(--color-accent-light);
  --accent-700: var(--color-accent-dark);
  
  position: fixed;
  inset: 0;
  display: flex;
  flex-direction: column;
  background: var(--color-bg-canvas);
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', sans-serif;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}

/* Zen Mode - 更沉浸 */
.zen-mode {
  --panel-bg: rgba(255, 255, 255, 0.92);
  --panel-shadow: var(--shadow-lg);
}

/* ========================================
   顶部触发条
   ======================================== */
.top-trigger-zone {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  height: 24px;
  z-index: 100;
}

.top-trigger-bar {
  position: absolute;
  top: 0;
  left: 50%;
  transform: translateX(-50%) translateY(-100%);
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-2) var(--space-5);
  background: var(--panel-bg);
  backdrop-filter: blur(20px) saturate(180%);
  border-radius: 0 0 var(--radius-lg) var(--radius-lg);
  box-shadow: var(--panel-shadow);
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  letter-spacing: 0.01em;
  transition: transform var(--transition-slow);
  max-width: 80vw;
}

.top-trigger-bar.visible {
  transform: translateX(-50%) translateY(0);
}

.top-trigger-bar .trigger-book {
  font-weight: 500;
  color: var(--color-text-primary);
  max-width: 180px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.top-trigger-bar .divider {
  width: 1px;
  height: 12px;
  background: var(--color-border-hover);
}

.expand-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  margin-left: var(--space-1);
  background: transparent;
  border: none;
  border-radius: var(--radius-sm);
  color: var(--color-text-tertiary);
  font-size: 10px;
  cursor: pointer;
  transition: all var(--transition-fast);
}

.expand-btn:hover {
  background: var(--color-bg-tertiary);
  color: var(--color-text-primary);
}

/* ========================================
   顶部面板
   ======================================== */
.top-panel {
  flex-shrink: 0;
  background: var(--color-bg-primary);
  border-bottom: 1px solid var(--color-border);
  padding: var(--space-3) var(--space-5);
}

.top-panel-content {
  display: flex;
  align-items: center;
  gap: var(--space-6);
  max-width: 1400px;
  margin: 0 auto;
}

/* ---------- 书籍选择器 ---------- */
.book-selector {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  position: relative;
}

.custom-book-dropdown {
  position: relative;
}

.book-dropdown-trigger {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  height: 36px;
  padding: 0 var(--space-3);
  background: var(--color-bg-secondary);
  border: 1px solid transparent;
  border-radius: var(--radius-md);
  font-size: var(--text-sm);
  color: var(--color-text-primary);
  cursor: pointer;
  transition: all var(--transition-fast);
  min-width: 160px;
  max-width: 220px;
}

.book-dropdown-trigger:hover:not(:disabled) {
  background: var(--color-bg-tertiary);
  border-color: var(--color-border-hover);
}

.book-dropdown-trigger:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.custom-book-dropdown.open .book-dropdown-trigger {
  background: var(--color-bg-primary);
  border-color: var(--color-accent);
  box-shadow: 0 0 0 3px rgba(196, 167, 125, 0.12);
}

.book-icon {
  font-size: 15px;
  opacity: 0.8;
}

.book-name {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  text-align: left;
  font-weight: 500;
  letter-spacing: 0.01em;
}

.dropdown-arrow {
  font-size: 9px;
  color: var(--color-text-tertiary);
  transition: transform var(--transition-fast);
}

.dropdown-arrow.open {
  transform: rotate(180deg);
}

.book-dropdown-menu {
  position: absolute;
  top: calc(100% + var(--space-2));
  left: 0;
  min-width: 240px;
  max-width: 300px;
  background: rgba(255, 255, 255, 0.98);
  backdrop-filter: blur(20px);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-xl);
  z-index: 200;
  overflow: hidden;
}

.dropdown-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: var(--space-3) var(--space-4);
  border-bottom: 1px solid var(--color-border);
}

.dropdown-header span:first-child {
  font-size: var(--text-xs);
  font-weight: 600;
  color: var(--color-text-tertiary);
  text-transform: uppercase;
  letter-spacing: 0.08em;
}

.book-count {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
  background: var(--color-bg-secondary);
  padding: var(--space-1) var(--space-2);
  border-radius: var(--radius-full);
}

.book-list {
  max-height: 260px;
  overflow-y: auto;
  padding: var(--space-2);
}

.book-option {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  width: 100%;
  padding: var(--space-2) var(--space-3);
  border: none;
  border-radius: var(--radius-md);
  background: transparent;
  cursor: pointer;
  text-align: left;
  transition: all var(--transition-fast);
}

.book-option:hover {
  background: var(--color-bg-secondary);
}

.book-option.active {
  background: var(--color-accent-light);
}

.book-option-title {
  flex: 1;
  font-size: var(--text-sm);
  color: var(--color-text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.book-option.active .book-option-title {
  color: var(--color-accent-dark);
  font-weight: 500;
}

.book-option-genre {
  font-size: var(--text-xs);
  color: var(--color-text-tertiary);
  background: var(--color-bg-tertiary);
  padding: 2px 8px;
  border-radius: var(--radius-full);
}

.active-indicator {
  width: 18px;
  height: 18px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--color-accent);
  color: white;
  font-size: 10px;
  border-radius: var(--radius-full);
  flex-shrink: 0;
}

.empty-books {
  padding: var(--space-6) var(--space-4);
  text-align: center;
  font-size: var(--text-sm);
  color: var(--color-text-tertiary);
}

/* ---------- 章节信息 ---------- */
.chapter-info {
  flex: 1;
  display: flex;
  align-items: center;
  gap: var(--space-3);
}

.chapter-label {
  font-size: var(--text-xs);
  font-weight: 600;
  color: var(--color-text-tertiary);
  text-transform: uppercase;
  letter-spacing: 0.06em;
}

.chapter-title-input {
  flex: 1;
  max-width: 360px;
  height: 36px;
  padding: 0 var(--space-3);
  border: 1px solid transparent;
  border-radius: var(--radius-md);
  background: transparent;
  font-size: var(--text-md);
  color: var(--color-text-primary);
  letter-spacing: 0.01em;
  transition: all var(--transition-fast);
}

.chapter-title-input::placeholder {
  color: var(--color-text-muted);
}

.chapter-title-input:hover {
  background: var(--color-bg-secondary);
}

.chapter-title-input:focus {
  background: var(--color-bg-primary);
  border-color: var(--color-border-hover);
  outline: none;
}

.top-actions {
  display: flex;
  align-items: center;
  gap: var(--space-1);
}

.collapse-btn {
  position: absolute;
  bottom: -18px;
  left: 50%;
  transform: translateX(-50%);
  height: 18px;
  padding: 0 var(--space-4);
  background: var(--color-bg-primary);
  border: 1px solid var(--color-border);
  border-top: none;
  border-radius: 0 0 var(--radius-md) var(--radius-md);
  font-size: 9px;
  color: var(--color-text-muted);
  cursor: pointer;
  transition: all var(--transition-fast);
}

.collapse-btn:hover {
  color: var(--color-text-secondary);
  height: 22px;
}

/* ========================================
   主内容区
   ======================================== */
.main-area {
  flex: 1;
  display: flex;
  overflow: hidden;
  position: relative;
}

/* ---------- 左侧触发条 ---------- */
.left-trigger {
  position: absolute;
  left: 0;
  top: 0;
  bottom: 32px;
  width: 12px;
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
  gap: var(--space-3);
  padding: var(--space-4) var(--space-2);
  background: var(--panel-bg);
  backdrop-filter: blur(20px);
  border-radius: 0 var(--radius-lg) var(--radius-lg) 0;
  box-shadow: var(--panel-shadow);
  transition: transform var(--transition-normal);
}

.left-trigger-content.visible {
  transform: translateY(-50%) translateX(0);
}

.chapter-dots {
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.chapter-dot {
  width: 5px;
  height: 5px;
  border-radius: var(--radius-full);
  background: var(--color-text-muted);
  opacity: 0.35;
  transition: all var(--transition-fast);
}

.chapter-dot.active {
  background: var(--color-accent);
  opacity: 1;
  transform: scale(1.4);
}

.trigger-label {
  font-size: var(--text-xs);
  font-weight: 500;
  color: var(--color-text-tertiary);
  writing-mode: vertical-rl;
  text-orientation: mixed;
  letter-spacing: 0.15em;
}

/* ---------- 左侧面板 ---------- */
.left-panel {
  width: 220px;
  flex-shrink: 0;
  background: var(--color-bg-primary);
  border-right: 1px solid var(--color-border);
  display: flex;
  flex-direction: column;
  padding: var(--space-4);
}

.left-panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--space-4);
}

.left-panel-header h3 {
  margin: 0;
  font-size: var(--text-xs);
  font-weight: 600;
  color: var(--color-text-tertiary);
  text-transform: uppercase;
  letter-spacing: 0.08em;
}

.chapters-list {
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  margin-bottom: var(--space-3);
}

.chapter-item {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: all var(--transition-fast);
}

.chapter-item:hover {
  background: var(--color-bg-secondary);
}

.chapter-item.active {
  background: var(--color-accent-light);
}

.ch-number {
  font-size: var(--text-xs);
  font-weight: 600;
  color: var(--color-text-muted);
  min-width: 20px;
}

.chapter-item.active .ch-number {
  color: var(--color-accent-dark);
}

.ch-title {
  flex: 1;
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.chapter-item.active .ch-title {
  color: var(--color-accent-dark);
  font-weight: 500;
}

/* ---------- 编辑器容器 ---------- */
.editor-container {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  padding: var(--space-5);
}

.zen-mode .editor-container {
  padding: var(--space-8) var(--space-6);
}

/* ---------- 右侧悬浮工具栏 ---------- */
.right-floating-bar {
  position: absolute;
  right: var(--space-4);
  top: 50%;
  transform: translateY(-50%);
  z-index: 40;
  transition: right var(--transition-normal);
}

.right-floating-bar.panel-open {
  right: 344px;
}

.floating-tabs {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  padding: var(--space-2);
  background: var(--panel-bg);
  backdrop-filter: blur(20px);
  border-radius: var(--radius-xl);
  box-shadow: var(--shadow-md);
}

.floating-tab {
  position: relative;
  width: 40px;
  height: 40px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 1px;
  border: none;
  border-radius: var(--radius-md);
  background: transparent;
  cursor: pointer;
  transition: all var(--transition-fast);
}

.floating-tab:hover {
  background: var(--color-bg-secondary);
}

.floating-tab.active {
  background: var(--color-accent);
  color: white;
  box-shadow: var(--shadow-sm);
}

.tab-icon {
  font-size: 17px;
  line-height: 1;
}

.tab-shortcut {
  font-size: 8px;
  opacity: 0.5;
  font-weight: 600;
}

/* ---------- 右侧面板 ---------- */
.right-panel {
  position: absolute;
  right: 0;
  top: 0;
  bottom: 0;
  width: 320px;
  background: var(--panel-bg);
  backdrop-filter: blur(20px);
  box-shadow: -2px 0 32px rgba(0, 0, 0, 0.06);
  display: flex;
  flex-direction: column;
  z-index: 35;
}

.right-panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-4) var(--space-5);
  border-bottom: 1px solid var(--color-border);
}

.right-panel-header span {
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--color-text-primary);
  letter-spacing: 0.01em;
}

.right-panel-content {
  flex: 1;
  overflow-y: auto;
  padding: var(--space-4);
}

/* ---------- 状态栏 ---------- */
.status-bar {
  flex-shrink: 0;
  height: 28px;
  padding: 0 var(--space-5);
  background: var(--color-bg-primary);
  border-top: 1px solid var(--color-border);
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: var(--text-xs);
  color: var(--color-text-muted);
}

.status-bar.minimal {
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
  transition: opacity var(--transition-normal);
}

.status-bar.minimal:hover .zen-hint {
  opacity: 0.5;
}

/* ========================================
   通用按钮样式
   ======================================== */
.btn-icon {
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: none;
  border-radius: var(--radius-md);
  background: transparent;
  color: var(--color-text-secondary);
  font-size: 15px;
  cursor: pointer;
  transition: all var(--transition-fast);
}

.btn-icon:hover:not(:disabled) {
  background: var(--color-bg-secondary);
  color: var(--color-text-primary);
}

.btn-icon:disabled {
  opacity: 0.35;
  cursor: not-allowed;
}

.btn-icon.zen-toggle.active {
  background: var(--color-accent-light);
  color: var(--color-accent-dark);
}

.btn-primary {
  height: 32px;
  padding: 0 var(--space-4);
  background: var(--color-accent);
  border: none;
  border-radius: var(--radius-md);
  font-size: var(--text-sm);
  font-weight: 500;
  color: white;
  cursor: pointer;
  transition: all var(--transition-fast);
  letter-spacing: 0.01em;
}

.btn-primary:hover {
  background: var(--color-accent-dark);
  transform: translateY(-1px);
  box-shadow: var(--shadow-sm);
}

.btn-danger {
  height: 32px;
  padding: 0 var(--space-4);
  background: #dc4446;
  border: none;
  border-radius: var(--radius-md);
  font-size: var(--text-sm);
  font-weight: 500;
  color: white;
  cursor: pointer;
  transition: all var(--transition-fast);
}

.btn-danger:hover {
  background: #c53030;
}

/* ========================================
   模态框
   ======================================== */
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.35);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 200;
}

.modal {
  background: var(--color-bg-primary);
  padding: var(--space-6);
  border-radius: var(--radius-xl);
  width: 90%;
  max-width: 420px;
  box-shadow: var(--shadow-xl);
}

.modal h3 {
  margin: 0 0 var(--space-4) 0;
  font-size: var(--text-lg);
  font-weight: 600;
  color: var(--color-text-primary);
  letter-spacing: -0.01em;
}

.modal input,
.modal textarea {
  width: 100%;
  padding: var(--space-2) var(--space-3);
  margin-bottom: var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-bg-secondary);
  font-size: var(--text-sm);
  color: var(--color-text-primary);
  transition: all var(--transition-fast);
}

.modal input:focus,
.modal textarea:focus {
  background: var(--color-bg-primary);
  border-color: var(--color-accent);
  box-shadow: 0 0 0 3px rgba(196, 167, 125, 0.1);
  outline: none;
}

.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-2);
  margin-top: var(--space-2);
}

.modal-actions button {
  height: 36px;
  padding: 0 var(--space-4);
  border: none;
  border-radius: var(--radius-md);
  background: var(--color-bg-secondary);
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  cursor: pointer;
  transition: all var(--transition-fast);
}

.modal-actions button:hover {
  background: var(--color-bg-tertiary);
  color: var(--color-text-primary);
}

.modal-actions .btn-primary,
.modal-actions .btn-danger {
  height: 36px;
}

/* ========================================
   笔记面板
   ======================================== */
.notes-panel {
  height: 100%;
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.notes-panel textarea {
  flex: 1;
  padding: var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-bg-secondary);
  resize: none;
  font-size: var(--text-sm);
  line-height: var(--leading-relaxed);
  color: var(--color-text-primary);
  transition: all var(--transition-fast);
}

.notes-panel textarea:focus {
  background: var(--color-bg-primary);
  border-color: var(--color-border-hover);
  outline: none;
}

.notes-panel button {
  height: 36px;
  background: var(--color-bg-secondary);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  cursor: pointer;
  transition: all var(--transition-fast);
}

.notes-panel button:hover:not(:disabled) {
  background: var(--color-bg-tertiary);
  color: var(--color-text-primary);
}

/* ========================================
   过渡动画
   ======================================== */
.slide-down-enter-active,
.slide-down-leave-active {
  transition: all var(--transition-normal);
}

.slide-down-enter-from,
.slide-down-leave-to {
  opacity: 0;
  transform: translateY(-12px);
}

.slide-left-enter-active,
.slide-left-leave-active {
  transition: all var(--transition-normal);
}

.slide-left-enter-from,
.slide-left-leave-to {
  opacity: 0;
  transform: translateX(-12px);
}

.slide-right-enter-active,
.slide-right-leave-active {
  transition: all var(--transition-normal);
}

.slide-right-enter-from,
.slide-right-leave-to {
  opacity: 0;
  transform: translateX(12px);
}

.dropdown-enter-active,
.dropdown-leave-active {
  transition: all var(--transition-fast);
}

.dropdown-enter-from,
.dropdown-leave-to {
  opacity: 0;
  transform: translateY(-6px) scale(0.98);
}

/* ========================================
   滚动条样式
   ======================================== */
::-webkit-scrollbar {
  width: 5px;
  height: 5px;
}

::-webkit-scrollbar-track {
  background: transparent;
}

::-webkit-scrollbar-thumb {
  background: var(--color-text-muted);
  border-radius: var(--radius-full);
  opacity: 0.25;
}

::-webkit-scrollbar-thumb:hover {
  opacity: 0.4;
}

/* ========================================
   响应式
   ======================================== */
@media (max-width: 768px) {
  .right-floating-bar {
    right: var(--space-2);
  }
  
  .floating-tabs {
    padding: var(--space-1);
  }
  
  .floating-tab {
    width: 36px;
    height: 36px;
  }
  
  .editor-container {
    padding: var(--space-4);
  }
  
  .top-panel-content {
    gap: var(--space-3);
  }
  
  .chapter-title-input {
    max-width: 200px;
  }
}
</style>
