<script setup lang="ts">
/**
 * 写作台（V3.1 F2 三栏重构，规格 §4）。
 *
 * 三栏布局：
 * - 左栏 Binder：章节导航（树/列表 + 状态徽标 + 新建章节）
 * - 中栏：TipTap 编辑器（复用 ChapterEditorContainer）+ 状态栏
 *   生成进行中时，编辑器上方叠加 GenerationOverlay 覆盖面板（显示进度，遮挡编辑器）
 * - 右栏 Inspector：规划/精修/反馈/Canon 四 tab（大纲/标题编辑在「规划」tab）
 *
 * splitpanes 提供可拖拽分隔（依赖已装）。
 */
import { ref, watch, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Splitpanes, Pane } from 'splitpanes'
import 'splitpanes/dist/splitpanes.css'
import Icon from '../../../components/Icon.vue'
import ChapterEditor from '../../../components/ChapterEditor.vue'
import ChapterBadges from '../presentation/ChapterBadges.vue'
import InspectorPanel from './InspectorPanel.vue'
import GenerationOverlay from '../../generation/presentation/GenerationOverlay.vue'
import { useGenerationSession } from '../../generation/composables/useGenerationSession'
import { useAppStore } from '../../app/useAppStore'
import { useToast } from '../../../composables/useToast'
import { useConfirmDialog } from '../../../composables/useConfirmDialog'
import { loadUiPrefs, saveUiPrefs } from '../../../composables/useUiPrefs'
import type { Chapter } from '../../../types'

const route = useRoute()
const router = useRouter()
const store = useAppStore()
const { showToast } = useToast()
const { show: showConfirm } = useConfirmDialog()

// 解构 ref 供模板使用
const currentBook = store.currentBook
const chapters = store.chapters
const sortedChapters = store.sortedChapters
const selectedChapterId = store.selectedChapterId
const selectedChapter = store.selectedChapter
const loading = store.loading
const characters = store.characters
const apiConfig = store.apiConfig

const bookIdFromRoute = computed(() => (route.params.bookId as string) || null)
const chapterIdFromRoute = computed(() => (route.params.chapterId as string) || null)

// V4.x 重构：共享 session（Inspector 和中栏覆盖面板都用同一个）
const session = useGenerationSession()

// 生成进行中：stage 非 idle（覆盖面板叠加在编辑器上，物理遮挡使其不可操作）
const isGenerating = computed(() =>
  session.generating.value && session.stage.value !== 'idle',
)

// 生成完成时自动把正文写入章节
watch(() => session.stage.value, (newStage) => {
  if (newStage === 'done' && session.streamText.value) {
    handleGenerated(session.streamText.value)
  }
})

// 同步路由 bookId 到 store
watch(
  bookIdFromRoute,
  (newBookId) => {
    if (newBookId && newBookId !== store.currentBookId.value) {
      store.selectBook(newBookId)
    } else if (newBookId && store.books.value.length === 0) {
      store.loadBooks().then(() => {
        if (newBookId !== store.currentBookId.value) store.selectBook(newBookId)
      })
    }
  },
  { immediate: true }
)

// 同步路由 chapterId 到 store
watch(
  chapterIdFromRoute,
  (newChapterId) => {
    if (newChapterId && newChapterId !== store.selectedChapterId.value) {
      store.selectChapter(newChapterId)
    }
  },
  { immediate: true }
)

// store.selectedChapterId 变化时同步回路由
watch(selectedChapterId, (newId) => {
  if (!bookIdFromRoute.value) return
  const currentRouteChapter = chapterIdFromRoute.value
  if (newId !== currentRouteChapter) {
    router.replace({
      name: 'workspace',
      params: { bookId: bookIdFromRoute.value, chapterId: newId || undefined },
    })
  }
})

// 章节切换/进入：恢复该章的上次生成产物（localStorage 持久化）
// immediate=true 确保刷新后首屏即恢复；切章时 loadForChapter 内部会先 persist 旧章
watch(selectedChapterId, (newId) => {
  if (newId) {
    session.loadForChapter(newId)
  }
}, { immediate: true })

// 三栏分栏宽度（持久化）
const splitSizes = ref<number[]>(loadUiPrefs().splitSizes || [20, 55, 25])
// 警示：splitpanes v4 的 resized 载荷是对象 { event, index, panes: [{min,max,size}] }（v3 才是数组）。
// 且 resized 在 document mouseup 监听器内同步 emit——这里一旦抛异常，库的 mousemove/mouseup
// 监听器永远不会被移除，拖拽会"卡住停不下来"，因此必须容错、绝不能向上抛。
function onResize(payload: { panes?: { size: number }[] }) {
  try {
    const panes = payload?.panes
    if (!Array.isArray(panes)) return
    const next = panes.map((p) => p.size)
    // 防御：splitpanes 偶发返回空数组
    if (next.length === 3 && next.every((n) => typeof n === 'number' && n > 0)) {
      splitSizes.value = next
      saveUiPrefs({ ...loadUiPrefs(), splitSizes: next })
    }
  } catch (e) {
    console.error('[Workspace] 保存分栏宽度失败', e)
  }
}

const chapterEditorRef = ref<any>(null)

async function createChapter() {
  const maxNumber =
    chapters.value.length > 0
      ? Math.max(...chapters.value.map((c) => c.chapter_number))
      : 0
  try {
    await store.createChapter({
      chapter_number: maxNumber + 1,
      chapter_name: `第${maxNumber + 1}章`,
      title: '',
      outline_text: '',
      content_text: '',
      status: 'draft',
    })
    showToast('已新建章节', 'success')
  } catch (e: any) {
    showToast('新建失败：' + e.message, 'error')
  }
}

function backToLibrary() {
  router.push({ name: 'library' })
}

async function handleUpdateChapter(id: string, updates: Record<string, unknown>) {
  try {
    await store.updateChapter(id, updates as any)
  } catch (e: any) {
    showToast('保存失败：' + e.message, 'error')
  }
}

function handleRefreshCharacters() {
  store.refreshCharacters()
}

// 生成完成：把正文灌入编辑器（通过 chapterEditorRef）
async function handleGenerated(text: string) {
  if (selectedChapter.value && text) {
    try {
      await store.updateChapter(selectedChapter.value.id, { content_text: text, draft_text: text })
      showToast('已生成并写入章节', 'success')
    } catch (e: any) {
      showToast('写入失败：' + e.message, 'error')
    }
  }
}

// 审校问题点击定位：滚动编辑器到 offset 并临时高亮（V3.1 F4）
function handleJumpToOffset(offset: [number, number] | undefined) {
  if (!offset) return
  chapterEditorRef.value?.scrollToOffset?.(offset)
}

const wordCount = computed(() => (selectedChapter.value?.content_text || '').length)

// 删除章节（悬停章节行出现入口，确认后调用 store.deleteChapter）
async function confirmDeleteChapter(ch: Chapter) {
  const ok = await showConfirm({
    title: '删除章节',
    message: `确定删除第 ${ch.chapter_number} 章「${ch.title || ch.chapter_name || '未命名'}」吗？`,
    warning: '章节正文、节拍与铺垫结构将一并删除，不可恢复。',
  })
  if (!ok) return
  try {
    await store.deleteChapter(ch.id)
    showToast('章节已删除', 'success')
  } catch (e: any) {
    showToast('删除章节失败: ' + (e.message || '未知错误'), 'error')
  }
}
</script>

<template>
  <div class="workspace-view">
    <Splitpanes class="workspace-split" @resized="onResize">
      <!-- 左栏：章节导航 Binder -->
      <Pane :size="splitSizes[0]" :min-size="14" :max-size="32" class="binder-pane">
        <aside class="binder">
          <div class="binder-header">
            <button class="icon-btn" @click="backToLibrary" title="返回书架">
              <Icon name="arrow-left" :size="15" />
            </button>
            <span class="binder-title" :title="currentBook?.title">{{
              currentBook?.title || '未选择书籍'
            }}</span>
          </div>

          <div v-if="loading" class="binder-loading">加载中…</div>
          <div v-else class="chapter-list">
            <div
              v-for="ch in sortedChapters"
              :key="ch.id"
              class="chapter-item"
              :class="{ active: ch.id === selectedChapterId }"
              role="button"
              tabindex="0"
              @click="store.selectChapter(ch.id)"
              @keydown.enter="store.selectChapter(ch.id)"
            >
              <span class="ch-num">{{ ch.chapter_number }}</span>
              <span class="ch-name">{{ ch.title || ch.chapter_name || '(未命名)' }}</span>
              <ChapterBadges :chapter="ch" />
              <button
                class="ch-delete"
                title="删除章节"
                @click.stop="confirmDeleteChapter(ch)"
              >
                <Icon name="trash" :size="12" />
              </button>
            </div>
          </div>

          <button class="new-chapter-btn" @click="createChapter">
            <Icon name="plus" :size="14" />
            <span>新建章节</span>
          </button>
        </aside>
      </Pane>

      <!-- 中栏：编辑器 + 状态栏 -->
      <Pane :size="splitSizes[1]" :min-size="30" class="editor-pane">
        <main class="editor-area">
          <!-- 编辑器（复用 ChapterEditorContainer 全套）；生成中叠加覆盖面板 -->
          <div v-if="selectedChapter" class="editor-host">
            <ChapterEditor
              ref="chapterEditorRef"
              :selected-chapter="selectedChapter"
              :characters="characters"
              :api-config="apiConfig"
              :book-id="currentBook?.id"
              @update-chapter="handleUpdateChapter"
              @refresh-characters="handleRefreshCharacters"
            />
            <!-- 生成覆盖面板：绝对定位遮挡编辑器，显示进度 -->
            <GenerationOverlay
              v-if="isGenerating"
              :session="session"
              @cancel="session.cancel"
            />
          </div>

          <!-- 空状态 -->
          <div v-else class="empty-editor">
            <div class="empty-icon"><Icon name="pencil-square" :size="48" /></div>
            <h2>选择一个章节开始写作</h2>
            <p>从左侧选择章节，或新建一个章节。</p>
            <button class="btn-primary" @click="createChapter">
              <Icon name="plus" :size="15" />
              <span>新建章节</span>
            </button>
          </div>

          <!-- 状态栏 -->
          <footer v-if="selectedChapter" class="status-bar">
            <span>{{ wordCount }} 字</span>
            <span v-if="chapterEditorRef?.saveStatus?.value === 'saving'">保存中…</span>
            <span v-else-if="chapterEditorRef?.saveStatus?.value === 'saved'" class="muted">已保存</span>
          </footer>
        </main>
      </Pane>

      <!-- 右栏：Inspector 智能副驾 -->
      <Pane :size="splitSizes[2]" :min-size="16" :max-size="40" class="inspector-pane">
        <InspectorPanel
          :external-session="session"
          @generate="() => {}"
          @generated="handleGenerated"
          @jump-to-offset="handleJumpToOffset"
        />
      </Pane>
    </Splitpanes>
  </div>
</template>

<style scoped>
.workspace-view {
  width: 100%;
  height: 100%;
  overflow: hidden;
  background: var(--bg-primary);
}

.workspace-split {
  height: 100%;
}

/* splitpanes 主题适配 */
.workspace-split :deep(.splitpanes__splitter) {
  background: var(--border-color);
  position: relative;
}
.workspace-split :deep(.splitpanes__splitter::before) {
  content: '';
  position: absolute;
  left: 0;
  top: 0;
  right: 0;
  bottom: 0;
  background: transparent;
  transition: background 0.15s ease;
}
.workspace-split :deep(.splitpanes__splitter:hover::before) {
  background: var(--accent-500);
  opacity: 0.2;
}

/* Binder */
.binder {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--bg-secondary);
  overflow: hidden;
}

.binder-header {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  padding: 0.5rem 0.625rem;
  border-bottom: 1px solid var(--border-color);
}

.binder-title {
  flex: 1;
  font-size: 0.8125rem;
  font-weight: 600;
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.icon-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 1.5rem;
  height: 1.5rem;
  background: transparent;
  border: none;
  border-radius: 0.25rem;
  color: var(--text-secondary);
  cursor: pointer;
  transition: all 0.15s ease;
}
.icon-btn:hover {
  background: var(--hover-bg);
  color: var(--text-primary);
}

.binder-loading {
  padding: 1rem;
  font-size: 0.75rem;
  color: var(--text-muted);
  text-align: center;
}

.chapter-list {
  flex: 1;
  overflow-y: auto;
  padding: 0.375rem;
  display: flex;
  flex-direction: column;
  gap: 0.125rem;
}

.chapter-item {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  width: 100%;
  padding: 0.4375rem 0.5rem;
  background: transparent;
  border: none;
  border-radius: 0.25rem;
  text-align: left;
  cursor: pointer;
  transition: background 0.15s ease;
}

.chapter-item:hover {
  background: var(--hover-bg);
}

.chapter-item.active {
  background: var(--hover-bg);
}

.ch-num {
  font-size: 0.6875rem;
  color: var(--text-muted);
  font-variant-numeric: tabular-nums;
  flex-shrink: 0;
  min-width: 1.25rem;
}

.ch-delete {
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 1.25rem;
  height: 1.25rem;
  padding: 0;
  background: transparent;
  border: none;
  border-radius: 0.25rem;
  color: var(--text-muted);
  cursor: pointer;
  opacity: 0;
  transition: opacity 0.15s ease, color 0.15s ease, background 0.15s ease;
}

.chapter-item:hover .ch-delete {
  opacity: 1;
}

.ch-delete:hover {
  color: #dc2626;
  background: rgba(220, 38, 38, 0.08);
}

.chapter-item.active .ch-num {
  color: var(--accent-500);
  font-weight: 600;
}

.ch-name {
  flex: 1;
  font-size: 0.75rem;
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.chapter-item.active .ch-name {
  color: var(--accent-500);
  font-weight: 500;
}

.new-chapter-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0.375rem;
  margin: 0.375rem;
  padding: 0.4375rem;
  background: transparent;
  border: 1px dashed var(--border-color);
  border-radius: 0.25rem;
  font-size: 0.75rem;
  color: var(--text-secondary);
  cursor: pointer;
  transition: all 0.15s ease;
  flex-shrink: 0;
}

.new-chapter-btn:hover {
  border-color: var(--accent-500);
  color: var(--accent-500);
}

/* 中栏 */
.editor-area {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--bg-primary);
  overflow: hidden;
}

.editor-host {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  min-height: 0;
  position: relative; /* 供 GenerationOverlay 绝对定位 */
}

/* 空状态 */
.empty-editor {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: var(--text-muted);
  text-align: center;
  padding: 2rem;
}

.empty-icon {
  margin-bottom: 1rem;
  opacity: 0.7;
}

.empty-editor h2 {
  font-family: var(--font-heading);
  font-size: 1.0625rem;
  font-weight: 500;
  color: var(--text-secondary);
  margin: 0 0 0.375rem;
}

.empty-editor p {
  font-size: 0.8125rem;
  margin: 0 0 1.25rem;
}

.btn-primary {
  display: inline-flex;
  align-items: center;
  gap: 0.375rem;
  padding: 0.4375rem 0.875rem;
  font-size: 0.8125rem;
  font-weight: 500;
  background: var(--accent-500);
  color: white;
  border: none;
  border-radius: 0.375rem;
  cursor: pointer;
  transition: background 0.15s ease;
}
.btn-primary:hover {
  background: var(--accent-600);
}

/* 状态栏 */
.status-bar {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.25rem 0.875rem;
  background: var(--bg-tertiary);
  border-top: 1px solid var(--border-color);
  font-size: 0.6875rem;
  color: var(--text-muted);
  font-variant-numeric: tabular-nums;
}

.status-bar .active {
  color: var(--accent-500);
}

.status-bar .muted {
  opacity: 0.7;
}
</style>
