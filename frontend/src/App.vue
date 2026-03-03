<script setup>
import { ref, onMounted, watch, computed } from 'vue'
import { Splitpanes, Pane } from 'splitpanes'
import 'splitpanes/dist/splitpanes.css'
import CharacterPanel from './components/CharacterPanel.vue'
import ChapterEditor from './components/ChapterEditor.vue'
import BookConfigPanel from './components/BookConfigPanel.vue'
import SettingsModal from './components/SettingsModal.vue'
import DebugPromptWindow from './components/DebugPromptWindow.vue'
import { bookApi, characterApi, chapterApi, relationshipApi } from './composables/useApi'
import { useTheme } from './composables/useTheme'
import { loadUiPrefs, saveUiPrefs } from './composables/useUiPrefs'

const { initTheme } = useTheme()

const isDebugMode = computed(() => {
  const urlParams = new URLSearchParams(window.location.search)
  return urlParams.get('debug') === 'true'
})

const books = ref([])
const currentBookId = ref(null)
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
const bookForm = ref({ title: '', genre: '', global_sys_prompt: '' })
const manageBookForm = ref({ title: '', genre: '' })

async function loadBooks() {
  try {
    books.value = await bookApi.getAll()
    if (books.value.length > 0 && !currentBookId.value) {
      currentBookId.value = books.value[0].id
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
  } catch (error) {
    console.error('加载数据失败:', error)
  } finally {
    loading.value = false
  }
}

watch(currentBookId, loadCurrentBookData)

async function createBook() {
  if (!bookForm.value.title.trim()) return
  try {
    const newBook = await bookApi.create({
      ...bookForm.value,
      global_sys_prompt: bookForm.value.global_sys_prompt || ''
    })
    books.value.push(newBook)
    currentBookId.value = newBook.id
    showBookModal.value = false
    bookForm.value = { title: '', genre: '', global_sys_prompt: '' }
  } catch (error) {
    alert('创建失败: ' + error.message)
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

async function updateApiConfig(data) {
  apiConfig.value = { ...apiConfig.value, ...data }
  localStorage.setItem('velluma_api_config', JSON.stringify(apiConfig.value))
}

function handleSplitResized(sizes) {
  if (!Array.isArray(sizes) || sizes.length !== 3) return
  uiPrefs.value = { ...uiPrefs.value, splitSizes: sizes }
  saveUiPrefs(uiPrefs.value)
}

function handleRightTabChange(tab) {
  uiPrefs.value = { ...uiPrefs.value, rightTab: tab }
  saveUiPrefs(uiPrefs.value)
}

function handleMetaCollapsedChange(val) {
  uiPrefs.value = { ...uiPrefs.value, chapterMetaCollapsed: !!val }
  saveUiPrefs(uiPrefs.value)
}

async function createCharacter(data) {
  if (!currentBookId.value) {
    alert('请先创建或选择一本书籍')
    return
  }
  try {
    const newChar = await characterApi.create({
      ...data,
      book_id: currentBookId.value
    })
    characters.value.push(newChar)
  } catch (error) {
    alert('创建失败: ' + error.message)
  }
}

async function updateCharacter(id, data) {
  try {
    const updated = await characterApi.update(id, data)
    const index = characters.value.findIndex(c => c.id === id)
    if (index !== -1) {
      characters.value[index] = updated
    }
  } catch (error) {
    alert('更新失败: ' + error.message)
  }
}

async function deleteCharacter(id) {
  try {
    await characterApi.delete(id)
    characters.value = characters.value.filter(c => c.id !== id)
  } catch (error) {
    alert('删除失败: ' + error.message)
  }
}

async function createRelationship(data) {
  if (!currentBookId.value) {
    alert('请先创建或选择一本书籍')
    return
  }
  try {
    const newRel = await relationshipApi.create({
      ...data,
      book_id: currentBookId.value
    })
    relationships.value.push(newRel)
  } catch (error) {
    alert('创建失败: ' + error.message)
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
    alert('更新失败: ' + error.message)
  }
}

async function deleteRelationship(id) {
  try {
    await relationshipApi.delete(id)
    relationships.value = relationships.value.filter(r => r.id !== id)
  } catch (error) {
    alert('删除失败: ' + error.message)
  }
}

async function createChapter(data) {
  if (!currentBookId.value) {
    alert('请先创建或选择一本书籍')
    return
  }
  try {
    const newChapter = await chapterApi.create({
      ...data,
      book_id: currentBookId.value
    })
    chapters.value.push(newChapter)
  } catch (error) {
    alert('创建失败: ' + error.message)
  }
}

async function updateChapter(id, data) {
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
  } catch (error) {
    alert('更新失败: ' + error.message)
  }
}

async function deleteChapter(id) {
  try {
    await chapterApi.delete(id)
    chapters.value = chapters.value.filter(c => c.id !== id)
  } catch (error) {
    alert('删除失败: ' + error.message)
  }
}

async function saveGeneratedContent(chapterId, content) {
  try {
    const updated = await chapterApi.update(chapterId, { content_text: content })
    const index = chapters.value.findIndex(c => c.id === chapterId)
    if (index !== -1) {
      chapters.value[index] = updated
    }
  } catch (error) {
    console.error('保存失败:', error)
  }
}

function getCurrentBook() {
  return books.value.find(b => b.id === currentBookId.value)
}

function openManageBookModal() {
  const book = getCurrentBook()
  if (!book) return
  manageBookForm.value = {
    title: book.title || '',
    genre: book.genre || ''
  }
  showManageBookModal.value = true
}

async function saveManageBook() {
  if (!currentBookId.value) return
  if (!manageBookForm.value.title.trim()) return
  await updateBook({
    title: manageBookForm.value.title,
    genre: manageBookForm.value.genre
  })
  showManageBookModal.value = false
}

async function deleteCurrentBook() {
  if (!currentBookId.value) return
  const book = getCurrentBook()
  const ok = confirm(`确定要删除书籍 "${book?.title || ''}" 吗？此操作会删除其下所有章节与角色。`)
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
    alert('删除失败: ' + error.message)
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
  <DebugPromptWindow v-if="isDebugMode" />
  <div v-else class="h-full w-full bg-[var(--bg-primary)] flex flex-col">
    <div class="h-14 flex-shrink-0 flex items-center justify-between px-4 border-b border-[var(--border-color)] bg-[var(--bg-secondary)]">
      <div class="flex items-center gap-3">
        <h1 class="text-lg font-bold text-[var(--text-primary)]">Velluma AI</h1>
        
        <div class="flex items-center gap-2 ml-6">
          <select
            :value="currentBookId"
            @change="e => currentBookId = e.target.value"
            class="px-3 py-1.5 bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-lg text-[var(--text-primary)] text-sm focus:outline-none focus:border-primary-500 min-w-[160px]"
          >
            <option v-for="book in books" :key="book.id" :value="book.id">
              {{ book.title }}
            </option>
          </select>

          <button
            @click="openManageBookModal"
            :disabled="!currentBookId"
            class="p-1.5 text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--hover-bg)] disabled:opacity-40 disabled:hover:bg-transparent rounded-lg transition-colors"
            title="管理书籍"
          >
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z"/>
            </svg>
          </button>
          
          <button
            @click="showBookModal = true"
            class="p-1.5 text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--hover-bg)] rounded-lg transition-colors"
            title="新建书籍"
          >
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"/>
            </svg>
          </button>
        </div>
      </div>
      
      <button
        @click="showSettingsModal = true"
        class="p-2 text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--hover-bg)] rounded-lg transition-colors flex items-center gap-2 text-sm"
        title="设置"
      >
        <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.38a2 2 0 0 0-.73-2.73l-.15-.1a2 2 0 0 1-1-1.72v-.51a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"></path><circle cx="12" cy="12" r="3"></circle></svg>
        <span>设置</span>
      </button>
    </div>
    
    <div class="flex-1 min-h-0 relative">
      <splitpanes class="default-theme" style="height: 100%" @resized="handleSplitResized">
        <pane min-size="15" :size="uiPrefs.splitSizes[0]">
          <div class="h-full overflow-hidden bg-[var(--bg-secondary)] border-r border-[var(--border-color)]">
            <CharacterPanel
              :characters="characters"
              :relationships="relationships"
              @create-character="createCharacter"
              @update-character="updateCharacter"
              @delete-character="deleteCharacter"
              @create-relationship="createRelationship"
              @update-relationship="updateRelationship"
              @delete-relationship="deleteRelationship"
            />
          </div>
        </pane>
        
        <pane min-size="30" :size="uiPrefs.splitSizes[1]">
          <div class="h-full overflow-hidden bg-[var(--bg-primary)]">
            <ChapterEditor
              :chapters="chapters"
              :characters="characters"
              :api-config="apiConfig"
              :meta-collapsed="uiPrefs.chapterMetaCollapsed"
              @create-chapter="createChapter"
              @update-chapter="updateChapter"
              @delete-chapter="deleteChapter"
              @save-generated="saveGeneratedContent"
              @update-meta-collapsed="handleMetaCollapsedChange"
              @refresh-characters="loadCharacters"
            />
          </div>
        </pane>
        
        <pane min-size="15" :size="uiPrefs.splitSizes[2]">
          <div class="h-full overflow-hidden bg-[var(--bg-secondary)] border-l border-[var(--border-color)]">
            <BookConfigPanel
              :book-config="getCurrentBook() || {}"
              :update-book="updateBook"
              :initial-tab="uiPrefs.rightTab"
              @tab-change="handleRightTabChange"
            />
          </div>
        </pane>
      </splitpanes>
    </div>
    
    <SettingsModal
      :is-open="showSettingsModal"
      :config="apiConfig"
      @close="showSettingsModal = false"
      @save="updateApiConfig"
    />
    
    <div v-if="showBookModal" class="fixed inset-0 bg-black/50 flex items-center justify-center z-50" @click.self="showBookModal = false">
      <div class="bg-[var(--bg-secondary)] rounded-xl border border-[var(--border-color)] p-6 w-full max-w-md mx-4">
        <h3 class="text-lg font-semibold text-[var(--text-primary)] mb-4">新建书籍</h3>
        
        <div class="space-y-4">
          <div>
            <label class="block text-sm text-[var(--text-muted)] mb-1">书名</label>
            <input
              v-model="bookForm.title"
              type="text"
              class="w-full px-3 py-2 bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-lg text-[var(--text-primary)] focus:outline-none focus:border-primary-500"
              placeholder="输入书籍名称"
            />
          </div>
          
          <div>
            <label class="block text-sm text-[var(--text-muted)] mb-1">类型</label>
            <input
              v-model="bookForm.genre"
              type="text"
              class="w-full px-3 py-2 bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-lg text-[var(--text-primary)] focus:outline-none focus:border-primary-500"
              placeholder="如：科幻、奇幻、都市"
            />
          </div>
          
          <div>
            <label class="block text-sm text-[var(--text-muted)] mb-1">全局提示词 (可选)</label>
            <textarea
              v-model="bookForm.global_sys_prompt"
              rows="3"
              class="w-full px-3 py-2 bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-lg text-[var(--text-primary)] focus:outline-none focus:border-primary-500 resize-none"
              placeholder="书籍的整体风格和基调..."
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
            class="px-4 py-2 bg-primary-600 hover:bg-primary-500 text-white rounded-lg transition-colors"
          >
            创建
          </button>
        </div>
      </div>
    </div>

    <div v-if="showManageBookModal" class="fixed inset-0 bg-black/50 flex items-center justify-center z-50" @click.self="showManageBookModal = false">
      <div class="bg-[var(--bg-secondary)] rounded-xl border border-[var(--border-color)] p-6 w-full max-w-md mx-4">
        <h3 class="text-lg font-semibold text-[var(--text-primary)] mb-4">管理书籍</h3>

        <div class="space-y-4">
          <div>
            <label class="block text-sm text-[var(--text-muted)] mb-1">书名</label>
            <input
              v-model="manageBookForm.title"
              type="text"
              class="w-full px-3 py-2 bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-lg text-[var(--text-primary)] focus:outline-none focus:border-primary-500"
              placeholder="输入书籍名称"
            />
          </div>

          <div>
            <label class="block text-sm text-[var(--text-muted)] mb-1">类型</label>
            <input
              v-model="manageBookForm.genre"
              type="text"
              class="w-full px-3 py-2 bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-lg text-[var(--text-primary)] focus:outline-none focus:border-primary-500"
              placeholder="如：科幻、奇幻、都市"
            />
          </div>
        </div>

        <div class="flex items-center justify-between gap-3 mt-6">
          <button
            @click="deleteCurrentBook"
            class="px-4 py-2 text-rose-400 hover:bg-rose-500/10 rounded-lg transition-colors"
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
              class="px-4 py-2 bg-primary-600 hover:bg-primary-500 text-white rounded-lg transition-colors"
            >
              保存
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style>
/* Splitpanes Theme Customization */
.splitpanes.default-theme .splitpanes__splitter {
  background-color: var(--border-color) !important;
  box-sizing: border-box;
  position: relative;
  flex-shrink: 0;
  width: 4px !important;
  border-left: none !important;
  border-right: none !important;
}

.splitpanes.default-theme .splitpanes__splitter:before,
.splitpanes.default-theme .splitpanes__splitter:after {
  background-color: var(--text-muted) !important;
  opacity: 0.5;
}

.splitpanes.default-theme .splitpanes__splitter:hover {
  background-color: var(--primary-color, #3b82f6) !important;
}

.splitpanes.default-theme .splitpanes__pane {
  background-color: transparent !important;
}
</style>
