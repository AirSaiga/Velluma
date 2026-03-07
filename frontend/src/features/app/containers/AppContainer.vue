<script setup lang="ts">
import { ref, onMounted, watch, computed } from 'vue'
import CharacterPanel from '../../../components/CharacterPanel.vue'
import ChapterEditor from '../../../components/ChapterEditor.vue'
import WorldviewSettings from '../../../components/WorldviewSettings.vue'
import MapSettings from '../../../components/MapSettings.vue'
import SettingsModal from '../../../components/SettingsModal.vue'
import DebugPromptWindow from '../../../components/DebugPromptWindow.vue'
import { bookApi, characterApi, chapterApi, relationshipApi } from '../../../services/api'
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
  model: 'google/gemini-2.0-flash-001'
})
const uiPrefs = ref(loadUiPrefs())
const loading = ref(false)
const showBookModal = ref(false)
const showManageBookModal = ref(false)
const showSettingsModal = ref(false)
const notesStatus = ref('idle')
const notesError = ref('')
const localBookNotes = ref('')
const bookForm = ref({ title: '', genre: '', global_sys_prompt: '', core_motifs_taboos: '' })
const manageBookForm = ref({ title: '', genre: '', core_motifs_taboos: '' })
const CURRENT_BOOK_STORAGE_KEY = 'velluma_current_book_id'

const sortedChapters = computed(() => {
  return [...chapters.value].sort((a, b) => a.chapter_number - b.chapter_number)
})

const currentBook = computed(() => {
  return books.value.find((b) => b.id === currentBookId.value) || null
})

const selectedChapter = computed(() => {
  return chapters.value.find((c) => c.id === selectedChapterId.value) || null
})

const rightTab = computed({
  get: () => uiPrefs.value.rightTab || 'characters',
  set: (val) => handleRightTabChange(val),
})

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

function selectChapter(chapterId: string) {
  selectedChapterId.value = chapterId
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

onMounted(async () => {
  const savedConfig = localStorage.getItem('velluma_api_config')
  if (savedConfig) {
    apiConfig.value = JSON.parse(savedConfig)
  }
  await loadBooks()
  initTheme()
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
  <div v-else class="h-full w-full bg-[var(--bg-primary)] p-3">
    <div class="h-full min-h-0 rounded-2xl bg-[var(--bg-canvas)]/90 shadow-[0_20px_60px_rgba(20,33,61,0.08)] overflow-hidden">
      <div class="h-full min-h-0 grid grid-cols-[220px_minmax(0,1fr)_280px]">
        <aside class="h-full min-h-0 flex flex-col bg-transparent px-3 py-3">
          <div class="flex items-center justify-between mb-2">
            <h1 class="text-xs font-semibold tracking-wide text-[var(--text-secondary)]">写作大纲</h1>
            <button
              @click="showSettingsModal = true"
              class="p-1.5 rounded-full text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-white/80 transition-colors"
              title="设置"
            >
              <svg xmlns="http://www.w3.org/2000/svg" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.38a2 2 0 0 0-.73-2.73l-.15-.1a2 2 0 0 1-1-1.72v-.51a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"></path><circle cx="12" cy="12" r="3"></circle></svg>
            </button>
          </div>

          <div class="space-y-1.5">
            <select
              :value="currentBookId"
              @change="handleBookChange"
              class="w-full px-2 py-1.5 bg-white/90 rounded-xl text-xs focus:outline-none ring-1 ring-transparent focus:ring-[var(--accent-500)]"
            >
              <option v-for="book in books" :key="book.id" :value="book.id">
                {{ book.title }}
              </option>
            </select>
            <div class="flex items-center gap-1.5">
              <button
                @click="showBookModal = true"
                class="flex-1 px-2 py-1.5 rounded-xl bg-indigo-600 text-white text-xs font-medium shadow-sm ring-1 ring-indigo-600/40 hover:bg-indigo-500 transition-colors"
              >
                新建
              </button>
              <button
                @click="openManageBookModal"
                :disabled="!currentBookId"
                class="px-2 py-1.5 rounded-xl bg-white/90 text-xs text-[var(--text-secondary)] hover:text-[var(--text-primary)] disabled:opacity-40 transition-colors"
              >
                管理
              </button>
            </div>
            <button
              @click="createChapterFromOutlinePanel"
              class="w-full px-2 py-1.5 rounded-xl bg-indigo-600 text-white text-xs font-medium shadow-sm ring-1 ring-indigo-600/40 hover:bg-indigo-500 transition-colors"
            >
              新建章节
            </button>
          </div>

          <div class="mt-2 flex-1 min-h-0 overflow-y-auto pr-1 space-y-1">
            <div v-if="loading" class="text-center py-3 text-xs text-[var(--text-muted)]">加载中...</div>
            <button
              v-for="chapter in sortedChapters"
              :key="chapter.id"
              @click="selectChapter(chapter.id)"
              class="relative w-full text-left px-2 py-1.5 rounded-xl transition-all group"
              :class="selectedChapterId === chapter.id
                ? 'bg-white text-[var(--text-primary)] shadow-sm'
                : 'text-[var(--text-secondary)] hover:bg-white/70'"
            >
              <span
                class="absolute left-0 top-1 bottom-1 w-0.5 rounded-r-full bg-[var(--accent-500)] transition-opacity"
                :class="selectedChapterId === chapter.id ? 'opacity-100' : 'opacity-0 group-hover:opacity-40'"
              />
              <div class="flex items-center justify-between pl-1.5">
                <div class="min-w-0">
                  <p class="text-xs font-medium truncate" :class="!chapter.title ? 'text-[var(--text-muted)] italic' : ''">
                    {{ chapter.title || `(无标题)` }}
                  </p>
                  <p class="text-[10px] text-[var(--text-muted)] mt-0.5">Ch.{{ chapter.chapter_number }}</p>
                </div>
                <div class="flex items-center gap-1">
                  <button
                    @click.stop="generateChapterEmbedding(chapter.id)"
                    class="opacity-0 group-hover:opacity-100 p-0.5 text-[var(--text-muted)] hover:text-indigo-500 transition"
                    title="生成向量"
                  >
                    <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z"/>
                    </svg>
                  </button>
                  <button
                    @click.stop="deleteChapter(chapter.id)"
                    class="opacity-0 group-hover:opacity-100 p-0.5 text-[var(--text-muted)] hover:text-rose-400 transition"
                  >
                    <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
                    </svg>
                  </button>
                </div>
              </div>
            </button>
            <div v-if="sortedChapters.length === 0" class="text-center py-4 text-xs text-[var(--text-muted)]">
              暂无章节
            </div>
          </div>
        </aside>

        <main class="h-full min-h-0 overflow-hidden border-x border-white/60">
          <ChapterEditor
            :selected-chapter="selectedChapter"
            :characters="characters"
            :api-config="apiConfig"
            :book-id="currentBookId"
            :meta-collapsed="uiPrefs.chapterMetaCollapsed"
            @update-chapter="updateChapter"
            @update-meta-collapsed="handleMetaCollapsedChange"
            @refresh-characters="loadCharacters"
          />
        </main>

        <aside class="h-full min-h-0 flex flex-col bg-transparent px-3 py-3">
          <div class="flex items-center justify-between mb-2">
            <div class="flex items-center gap-1">
              <button
                class="px-2 py-1 rounded-lg text-xs transition-colors ring-1"
                :class="rightTab === 'characters' ? 'bg-indigo-600 text-white ring-indigo-600/40' : 'bg-white/90 text-slate-700 ring-slate-300 hover:bg-white'"
                @click="rightTab = 'characters'"
              >
                角色
              </button>
              <button
                class="px-2 py-1 rounded-lg text-xs transition-colors ring-1"
                :class="rightTab === 'worldview' ? 'bg-indigo-600 text-white ring-indigo-600/40' : 'bg-white/90 text-slate-700 ring-slate-300 hover:bg-white'"
                @click="rightTab = 'worldview'"
              >
                规则
              </button>
              <button
                class="px-2 py-1 rounded-lg text-xs transition-colors ring-1"
                :class="rightTab === 'map' ? 'bg-indigo-600 text-white ring-indigo-600/40' : 'bg-white/90 text-slate-700 ring-slate-300 hover:bg-white'"
                @click="rightTab = 'map'"
              >
                地图
              </button>
              <button
                class="px-2 py-1 rounded-lg text-xs transition-colors ring-1"
                :class="rightTab === 'notes' ? 'bg-indigo-600 text-white ring-indigo-600/40' : 'bg-white/90 text-slate-700 ring-slate-300 hover:bg-white'"
                @click="rightTab = 'notes'"
              >
                笔记
              </button>
            </div>
            <div class="flex items-center gap-1">
              <button
                @click="saveBookNotes"
                :disabled="!currentBookId || notesStatus === 'saving'"
                class="px-2 py-1 text-xs text-[var(--text-muted)] hover:text-[var(--accent-500)] disabled:opacity-40 transition-colors"
              >
                {{ notesStatus === 'saved' ? '已保存' : '保存' }}
              </button>
            </div>
          </div>

          <div class="mt-1 flex-1 min-h-0 overflow-hidden rounded-xl bg-white/70">
            <CharacterPanel
              v-if="rightTab === 'characters'"
              :characters="characters"
              :relationships="relationships"
              :selected-chapter-id="selectedChapterId"
              :api-config="apiConfig"
              @create-character="createCharacter"
              @update-character="updateCharacter"
              @delete-character="deleteCharacter"
              @create-relationship="createRelationship"
              @update-relationship="updateRelationship"
              @delete-relationship="deleteRelationship"
            />

            <div v-else-if="rightTab === 'worldview'" class="h-full overflow-y-auto p-3">
              <WorldviewSettings v-if="currentBookId" :book-id="currentBookId" />
              <div v-else class="h-full flex items-center justify-center text-xs text-[var(--text-muted)]">请先选择书籍</div>
            </div>

            <div v-else-if="rightTab === 'map'" class="h-full overflow-y-auto">
              <MapSettings 
                v-if="selectedChapter" 
                :chapter="selectedChapter" 
                @update-chapter="updateChapter"
              />
              <div v-else class="h-full flex items-center justify-center text-xs text-[var(--text-muted)]">请先选择章节</div>
            </div>

            <div v-else class="h-full overflow-y-auto p-3">
              <h3 class="text-xs font-medium text-[var(--text-primary)]">创作笔记</h3>
              <textarea
                v-model="localBookNotes"
                rows="12"
                class="mt-2 w-full px-2 py-2 rounded-xl bg-[var(--bg-panel)] text-[var(--text-primary)] text-xs resize-none focus:outline-none ring-1 ring-transparent focus:ring-[var(--accent-500)]"
                placeholder="记录风格、基调、伏笔或暂存思路..."
              />
              <div v-if="notesStatus === 'dirty'" class="text-[10px] text-[var(--text-muted)] mt-1">未保存</div>
            </div>
          </div>
        </aside>
      </div>
    </div>

    <SettingsModal
      :is-open="showSettingsModal"
      :config="apiConfig"
      @close="showSettingsModal = false"
      @save="updateApiConfig"
    />

    <div v-if="showBookModal" class="fixed inset-0 bg-black/35 flex items-center justify-center z-50" @click.self="showBookModal = false">
      <div class="bg-[var(--bg-secondary)] rounded-2xl p-6 w-full max-w-md mx-4">
        <h3 class="text-lg font-semibold text-[var(--text-primary)] mb-4">新建书籍</h3>

        <div class="space-y-4">
          <div>
            <label class="block text-sm text-[var(--text-muted)] mb-1">书名</label>
            <input
              v-model="bookForm.title"
              type="text"
              class="w-full px-3 py-2 rounded-xl bg-[var(--bg-panel)] text-[var(--text-primary)] focus:outline-none ring-1 ring-transparent focus:ring-[var(--accent-500)]"
              placeholder="输入书籍名称"
            />
          </div>

          <div>
            <label class="block text-sm text-[var(--text-muted)] mb-1">类型</label>
            <input
              v-model="bookForm.genre"
              type="text"
              class="w-full px-3 py-2 rounded-xl bg-[var(--bg-panel)] text-[var(--text-primary)] focus:outline-none ring-1 ring-transparent focus:ring-[var(--accent-500)]"
              placeholder="如：科幻、奇幻、都市"
            />
          </div>

          <div>
            <label class="block text-sm text-[var(--text-muted)] mb-1">全局提示词 (可选)</label>
            <textarea
              v-model="bookForm.global_sys_prompt"
              rows="3"
              class="w-full px-3 py-2 rounded-xl bg-[var(--bg-panel)] text-[var(--text-primary)] focus:outline-none ring-1 ring-transparent focus:ring-[var(--accent-500)] resize-none"
              placeholder="书籍的整体风格和基调..."
            />
          </div>

          <div>
            <label class="block text-sm text-[var(--text-muted)] mb-1">核心母题与禁忌 (可选)</label>
            <textarea
              v-model="bookForm.core_motifs_taboos"
              rows="3"
              class="w-full px-3 py-2 rounded-xl bg-[var(--bg-panel)] text-[var(--text-primary)] focus:outline-none ring-1 ring-transparent focus:ring-[var(--accent-500)] resize-none"
              placeholder="列出本书的核心主题、反复出现的意象，以及绝对不能出现的情节或风格..."
            />
          </div>
        </div>

        <div class="flex justify-end gap-3 mt-6">
          <button
            @click="showBookModal = false"
            class="px-4 py-2 text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors"
          >
            取消
          </button>
          <button
            @click="createBook"
            class="px-4 py-2 rounded-full bg-[var(--accent-500)] text-white transition-colors"
          >
            创建
          </button>
        </div>
      </div>
    </div>

    <div v-if="showManageBookModal" class="fixed inset-0 bg-black/35 flex items-center justify-center z-50" @click.self="showManageBookModal = false">
      <div class="bg-[var(--bg-secondary)] rounded-2xl p-6 w-full max-w-md mx-4">
        <h3 class="text-lg font-semibold text-[var(--text-primary)] mb-4">管理书籍</h3>

        <div class="space-y-4">
          <div>
            <label class="block text-sm text-[var(--text-muted)] mb-1">书名</label>
            <input
              v-model="manageBookForm.title"
              type="text"
              class="w-full px-3 py-2 rounded-xl bg-[var(--bg-panel)] text-[var(--text-primary)] focus:outline-none ring-1 ring-transparent focus:ring-[var(--accent-500)]"
              placeholder="输入书籍名称"
            />
          </div>

          <div>
            <label class="block text-sm text-[var(--text-muted)] mb-1">类型</label>
            <input
              v-model="manageBookForm.genre"
              type="text"
              class="w-full px-3 py-2 rounded-xl bg-[var(--bg-panel)] text-[var(--text-primary)] focus:outline-none ring-1 ring-transparent focus:ring-[var(--accent-500)]"
              placeholder="如：科幻、奇幻、都市"
            />
          </div>

          <div>
            <label class="block text-sm text-[var(--text-muted)] mb-1">核心母题与禁忌 (可选)</label>
            <textarea
              v-model="manageBookForm.core_motifs_taboos"
              rows="3"
              class="w-full px-3 py-2 rounded-xl bg-[var(--bg-panel)] text-[var(--text-primary)] focus:outline-none ring-1 ring-transparent focus:ring-[var(--accent-500)] resize-none"
              placeholder="列出本书的核心主题、反复出现的意象，以及绝对不能出现的情节或风格..."
            />
          </div>
        </div>

        <div class="flex items-center justify-between gap-3 mt-6">
          <button
            @click="deleteCurrentBook"
            class="px-4 py-2 text-rose-500 hover:bg-rose-500/10 rounded-xl transition-colors"
          >
            删除书籍
          </button>
          <div class="flex gap-3">
            <button
              @click="showManageBookModal = false"
              class="px-4 py-2 text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors"
            >
              取消
            </button>
            <button
              @click="saveManageBook"
              class="px-4 py-2 rounded-full bg-[var(--accent-500)] text-white transition-colors"
            >
              保存
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
