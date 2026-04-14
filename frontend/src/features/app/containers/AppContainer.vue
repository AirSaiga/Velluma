<script setup lang="ts">
import { ref, onMounted, computed, watch } from 'vue'
import CharacterPanel from '../../../components/CharacterPanel.vue'
import { AssetPanel } from '../../asset-panel'
import { useAssetContainer } from '../../asset-panel'
import { ChapterEditor } from '../../chapter-editor'
import CritiquePanel from '../../../components/CritiquePanel.vue'
import WorldviewSettings from '../../../components/WorldviewSettings.vue'
import MapSettings from '../../../components/MapSettings.vue'
import GoldenSnippetsManager from '../../../components/GoldenSnippetsManager.vue'
import SettingsModal from '../../../components/SettingsModal.vue'
import NotesPanel from '../../../components/NotesPanel.vue'
import DebugPromptWindow from '../../../components/DebugPromptWindow.vue'
import { generateApi, chapterApi } from '../../../services/api'
import { useTheme } from '../../../composables/useTheme'
import { useToast } from '../../../composables/useToast'
import { useConfirmDialog } from '../../../composables/useConfirmDialog'
import Toast from '../../../components/Toast.vue'
import ConfirmDialog from '../../../components/ConfirmDialog.vue'
import Icon from '../../../components/Icon.vue'
import { saveUiPrefs } from '../../../composables/useUiPrefs'

import { useAppState } from './useAppState'
import { useZenMode } from './useZenMode'
import { useBookManager } from './useBookManager'
import { useChapterManager } from './useChapterManager'
import { useCharacterManager } from './useCharacterManager'
import { useBookNotes } from './useBookNotes'
import { useCritique } from './useCritique'
import { useEntityFocus } from './useEntityFocus'

const { initTheme } = useTheme()
const { toasts, showToast, removeToast } = useToast()
const { visible: confirmDialogVisible, options: confirmDialogOptions, show: showConfirm, handleConfirm: handleConfirmDialog, handleCancel: handleCancelDialog } = useConfirmDialog()

const isDebugMode = computed(() => {
  const urlParams = new URLSearchParams(window.location.search)
  return urlParams.get('debug') === 'true'
})

const showSettingsModal = ref(false)
const chapterEditorRef = ref<any>(null)

// ========== 防抖标题输入 ==========
function debounce<T extends (...args: any[]) => any>(fn: T, delay: number) {
  let timer: ReturnType<typeof setTimeout> | null = null
  return (...args: Parameters<T>) => {
    if (timer) clearTimeout(timer)
    timer = setTimeout(() => fn(...args), delay)
  }
}

const debouncedUpdateChapterTitle = debounce((id: string, title: string) => {
  updateChapter(id, { title })
}, 600)

function handleTopTitleInput(e: Event) {
  if (!selectedChapter.value) return
  debouncedUpdateChapterTitle(selectedChapter.value.id, (e.target as HTMLInputElement).value)
}

function handleTopTitleBlur(e: Event) {
  if (!selectedChapter.value) return
  debouncedUpdateChapterTitle(selectedChapter.value.id, (e.target as HTMLInputElement).value)
}

// ========== Zen Mode 首次引导 ==========
const ZEN_HINT_KEY = 'velluma_zen_hint_shown'
const showZenHint = ref(false)

function toggleZenModeWithHint() {
  toggleZenMode()
  if (isZenMode.value && !localStorage.getItem(ZEN_HINT_KEY)) {
    showZenHint.value = true
    localStorage.setItem(ZEN_HINT_KEY, '1')
    setTimeout(() => { showZenHint.value = false }, 3500)
  }
}

// ========== 全局活动状态 ==========
const globalActivity = computed(() => {
  if (loading.value) return '加载书籍数据中...'
  if (critiqueLoading.value) return '主编审阅中...'
  return null
})

const {
  books,
  currentBookId,
  selectedChapterId,
  characters,
  chapters,
  relationships,
  apiConfig,
  uiPrefs,
  loading,
  sortedChapters,
  currentBook,
  selectedChapter,
  loadBooks,
  loadCurrentBookData,
  updateApiConfig
} = useAppState()

const {
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
  closeRightPanel,
  handleRightTabChange
} = useZenMode({
  uiPrefs,
  onToggleZenMode: () => {},
  saveUiPrefs,
  onSelectBook: (bookId: string) => {
    currentBookId.value = bookId
  },
  closeRightPanel: () => {}
})

const {
  showBookModal,
  showManageBookModal,
  bookForm,
  manageBookForm,
  createBook,
  updateBook,
  openManageBookModal,
  saveManageBook,
  deleteCurrentBook
} = useBookManager({
  books,
  currentBookId,
  currentBook,
  showToast,
  showConfirm
})

const {
  createChapter,
  createChapterFromOutlinePanel,
  updateChapter,
  deleteChapter,
  generateChapterEmbedding
} = useChapterManager({
  currentBookId,
  chapters,
  selectedChapterId,
  sortedChapters,
  showToast,
  showConfirm
})

const {
  editorFocusedEntity,
  handleEditorEntityFocus
} = useEntityFocus()

const selectedChapterCharacterIds = computed(() => selectedChapter.value?.character_ids || [])

const {
  autoHighlightedCharacterIds,
  autoHighlightedCharacterNames,
  createCharacter,
  updateCharacter,
  deleteCharacter,
  createRelationship,
  updateRelationship,
  deleteRelationship,
  loadCharacters
} = useCharacterManager({
  currentBookId,
  characters,
  relationships,
  editorFocusedEntity,
  selectedChapterCharacterIds,
  showToast
})

const {
  localBookNotes,
  notesStatus,
  notesError,
  saveBookNotes,
  saveBookNotesFn
} = useBookNotes({
  currentBook,
  updateBook,
  showToast
})

const {
  critiqueResult,
  critiqueLoading,
  handleRequestCritique,
  handleCloseCritique
} = useCritique({
  selectedChapter,
  apiConfig,
  showToast,
  setActiveFloatingTab: (tab: string | null) => { activeFloatingTab.value = tab },
  setRightPanelExpanded: (expanded: boolean) => { rightPanelExpanded.value = expanded }
})

const { assets, loadAssets } = useAssetContainer({ bookId: currentBookId.value || undefined })

watch(currentBookId, (newBookId) => {
  if (newBookId) {
    loadAssets()
  } else if (assets) {
    assets.value = []
  }
})

function handleMetaCollapsedChange(val: boolean) {
  uiPrefs.value = { ...uiPrefs.value, chapterMetaCollapsed: !!val }
  saveUiPrefs(uiPrefs.value)
}

function handleBookChange(event: Event) {
  const target = event.target as HTMLSelectElement
  currentBookId.value = target.value || null
}

function handleJumpToCritique(comment: any) {
  if (!comment) return
  if (chapterEditorRef.value?.scrollToCritique) {
    chapterEditorRef.value.scrollToCritique(comment)
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

async function handleIntentGenerate(payload: any) {
  if (!selectedChapter.value) {
    showToast('请先选择章节', 'warning')
    return
  }
  if (!apiConfig.value?.api_key) {
    showToast('请先配置 API Key', 'warning')
    return
  }

  try {
    await handleIntentSave(payload)
    const requestPayload = {
      ...payload,
      chapter_id: selectedChapter.value.id,
      api_key: apiConfig.value.api_key,
      base_url: apiConfig.value.base_url || undefined,
      model: apiConfig.value.reasoning_model || apiConfig.value.model,
      word_count: payload.word_count || 3000
    }

    const generatedContent = await new Promise<string>((resolve, reject) => {
      let buffer = ''
      generateApi.streamAgentic(
        requestPayload,
        {
          onChunk: (chunk: string) => {
            buffer += chunk
          },
          onDone: () => {
            resolve(buffer.trim())
          },
          onError: (error: string) => {
            reject(new Error(error))
          }
        },
        '/intent-driven/generate',
        true
      )
    })

    const contentText = generatedContent
    if (!contentText) {
      throw new Error('未生成有效正文内容')
    }
    await chapterApi.update(selectedChapter.value.id, {
      content_text: contentText
    })
    const index = chapters.value.findIndex(c => c.id === selectedChapter.value?.id)
    if (index !== -1) {
      chapters.value[index] = { ...chapters.value[index], content_text: contentText }
    }
    showToast('已完成生成并写入章节内容', 'success')
  } catch (error: any) {
    showToast('生成失败: ' + error.message, 'error')
  }
}

function selectChapter(chapterId: string) {
  selectedChapterId.value = chapterId
  if (isZenMode.value) {
    leftPanelExpanded.value = false
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
  
  <!-- ========== 沉浸式主界面 ========== -->
  <div v-else class="immersive-app" :class="{ 'zen-mode': isZenMode }">
    
    <!-- Zen Mode 首次引导 -->
    <Transition name="fade">
      <div
        v-if="showZenHint"
        class="fixed top-16 left-1/2 -translate-x-1/2 z-[110] px-5 py-3 rounded-xl bg-[var(--bg-primary)] shadow-xl border border-[var(--border-color)] text-sm text-[var(--text-primary)]"
      >
        <div class="flex items-center gap-3">
          <span class="text-[var(--accent-700)]">
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          </span>
          <div>
            <p class="font-medium">已进入沉浸模式</p>
            <p class="text-xs text-[var(--text-muted)] mt-0.5">按 <kbd class="px-1.5 py-0.5 bg-[var(--bg-panel)] rounded text-[10px]">Ctrl+Shift+Z</kbd> 退出，或点击顶部展开工具栏</p>
          </div>
        </div>
      </div>
    </Transition>

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
              @input="handleTopTitleInput"
              @blur="handleTopTitleBlur"
              placeholder="章节标题..."
              class="chapter-title-input"
            />
          </div>
          
          <div class="top-actions">
            <button @click="showSettingsModal = true" class="btn-icon" title="设置">
              <Icon name="settings" :size="16" />
            </button>
            <button @click="toggleZenModeWithHint" class="btn-icon zen-toggle" :class="{ 'active': isZenMode }" title="沉浸模式 (Ctrl+Shift+Z)">
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
          
          <div v-if="sortedChapters.length === 0" class="empty-chapters-state">
            <div class="empty-illustration">📝</div>
            <p class="empty-title">还没有章节</p>
            <p class="empty-desc">创建第一章，开启 AI 辅助创作之旅</p>
            <button @click="createChapterFromOutlinePanel" class="btn-primary mt-2">
              + 新建章节
            </button>
          </div>
          
          <button v-else @click="createChapterFromOutlinePanel" class="btn-primary">
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
          :assets="assets"
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
          @intent-generate="handleIntentGenerate"
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
          <div class="right-panel-content-modern">
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
              @close="closeRightPanel"
            />
            
            <AssetPanel
                  v-else-if="activeFloatingTab === 'assets'"
                  :book-id="currentBookId"
                  @close="closeRightPanel"
                />
                <WorldviewSettings
              v-else-if="activeFloatingTab === 'worldview'"
              :book-id="currentBookId"
              @close="closeRightPanel"
            />
            
            <GoldenSnippetsManager
              v-else-if="activeFloatingTab === 'style'"
              :book-id="currentBookId"
              @close="closeRightPanel"
            />
            
            <MapSettings
              v-else-if="activeFloatingTab === 'map'"
              :chapter="selectedChapter"
              :focused-entity="editorFocusedEntity"
              :active-character-names="autoHighlightedCharacterNames"
              @update-chapter="updateChapter"
              @close="closeRightPanel"
            />
            
            <CritiquePanel
              v-else-if="activeFloatingTab === 'critique'"
              :result="critiqueResult"
              :loading="critiqueLoading"
              @jump-to-critique="handleJumpToCritique"
              @close-critique="handleCloseCritique"
              @close="closeRightPanel"
            />
            
            <NotesPanel
              v-else-if="activeFloatingTab === 'notes'"
              :book="currentBook"
              :save-notes="saveBookNotesFn"
              @close="closeRightPanel"
            />
          </div>
        </div>
      </Transition>
    </div>
    
    <!-- 底部状态栏 (Zen Mode 下极简) -->
    <div class="status-bar" :class="{ 'minimal': isZenMode }">
      <span class="flex items-center gap-2">
        <template v-if="globalActivity">
          <span class="w-1.5 h-1.5 rounded-full bg-[var(--accent-500)] animate-pulse"></span>
          <span class="text-[var(--accent-700)]">{{ globalActivity }}</span>
        </template>
        <template v-else-if="!isZenMode">
          <template v-if="currentBook">
            {{ currentBook.title }} · 第 {{ selectedChapter?.chapter_number || '-' }} 章
          </template>
          <template v-else>未选择书籍</template>
        </template>
        <template v-else>
          第 {{ selectedChapter?.chapter_number || '-' }} 章，共 {{ sortedChapters.length }} 章
        </template>
      </span>
      <span v-if="isZenMode" class="zen-hint">按 Ctrl+Shift+Z 退出沉浸模式</span>
    </div>
    
    <!-- ========== 模态框 ========== -->
    
    <!-- 新建书籍 -->
    <div v-if="showBookModal" class="modal-overlay" @click.self="showBookModal = false">
      <div class="modal">
        <div class="modal-header">
          <h3>新建书籍</h3>
          <button class="btn-icon" @click="showBookModal = false">
            <Icon name="x-mark" :size="18" />
          </button>
        </div>
        <div class="modal-body">
          <input v-model="bookForm.title" placeholder="书名" />
          <input v-model="bookForm.genre" placeholder="类型 (如：科幻、奇幻)" />
          <textarea v-model="bookForm.global_sys_prompt" placeholder="全局提示词 (可选)" rows="3" />
        </div>
        <div class="modal-actions">
          <button @click="showBookModal = false">取消</button>
          <button @click="createBook" class="btn-primary">创建</button>
        </div>
      </div>
    </div>
    
    <!-- 管理书籍 -->
    <div v-if="showManageBookModal" class="modal-overlay" @click.self="showManageBookModal = false">
      <div class="modal">
        <div class="modal-header">
          <h3>管理书籍</h3>
          <button class="btn-icon" @click="showManageBookModal = false">
            <Icon name="x-mark" :size="18" />
          </button>
        </div>
        <div class="modal-body">
          <input v-model="manageBookForm.title" placeholder="书名" />
          <input v-model="manageBookForm.genre" placeholder="类型" />
          <textarea v-model="manageBookForm.core_motifs_taboos" placeholder="核心设定与禁忌" rows="3" />
        </div>
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

.empty-chapters-state {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  padding: var(--space-4);
  margin-bottom: var(--space-3);
  background: var(--color-bg-secondary);
  border-radius: var(--radius-lg);
  border: 1px dashed var(--color-border-hover);
}

.empty-illustration {
  font-size: 28px;
  margin-bottom: var(--space-2);
  opacity: 0.8;
}

.empty-title {
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--color-text-primary);
  margin: 0 0 var(--space-1) 0;
}

.empty-desc {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
  margin: 0 0 var(--space-2) 0;
  line-height: 1.5;
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
  padding: var(--space-8);
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
  right: 372px;
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
  width: 360px;
  background: var(--bg-primary);
  backdrop-filter: blur(20px);
  box-shadow: -4px 0 40px rgba(0, 0, 0, 0.08);
  display: flex;
  flex-direction: column;
  z-index: 35;
  overflow: hidden;
}

.right-panel-content-modern {
  flex: 1;
  overflow: hidden;
  display: flex;
  flex-direction: column;
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
  opacity: 0.35;
  transition: opacity var(--transition-normal);
}

.status-bar.minimal:hover .zen-hint {
  opacity: 0.8;
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
  border-radius: var(--radius-xl);
  width: 90%;
  max-width: 420px;
  box-shadow: var(--shadow-xl);
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-4) var(--space-5);
  border-bottom: 1px solid var(--color-border);
}

.modal-header h3 {
  margin: 0;
  font-size: var(--text-lg);
  font-weight: 600;
  color: var(--color-text-primary);
  letter-spacing: -0.01em;
}

.modal-body {
  padding: var(--space-5);
  display: flex;
  flex-direction: column;
}

.modal-body input,
.modal-body textarea {
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

.modal-body input:last-child,
.modal-body textarea:last-child {
  margin-bottom: 0;
}

.modal-body input:focus,
.modal-body textarea:focus {
  background: var(--color-bg-primary);
  border-color: var(--color-accent);
  box-shadow: 0 0 0 3px rgba(196, 167, 125, 0.1);
  outline: none;
}

.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-2);
  padding: var(--space-3) var(--space-5) var(--space-5);
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

.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.4s ease, transform 0.4s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
  transform: translateY(-8px);
}

/* ========================================
   滚动条样式
   ======================================== */
::-webkit-scrollbar {
  width: 6px;
  height: 6px;
}

::-webkit-scrollbar-track {
  background: transparent;
}

::-webkit-scrollbar-thumb {
  background: var(--color-text-muted);
  border-radius: var(--radius-full);
  opacity: 0.25;
}

:hover::-webkit-scrollbar {
  width: 10px;
  height: 10px;
}

::-webkit-scrollbar-thumb:hover {
  opacity: 0.5;
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
