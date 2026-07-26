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
import MarkdownImportModal from '../../import-markdown/containers/MarkdownImportModal.vue'
import ExtractionModal from '../../extraction/containers/ExtractionModal.vue'
import InspectorPanel from './InspectorPanel.vue'
import GenerationOverlay from '../../generation/presentation/GenerationOverlay.vue'
import { useGenerationSession } from '../../generation/composables/useGenerationSession'
import { useAppStore } from '../../app/useAppStore'
import { useToast } from '../../../composables/useToast'
import { useConfirmDialog } from '../../../composables/useConfirmDialog'
import { useNotifyPrefs } from '../../../composables/useNotifyPrefs'
import CompletionModal from '../../generation/presentation/CompletionModal.vue'
import { loadUiPrefs, saveUiPrefs } from '../../../composables/useUiPrefs'
import type { Chapter } from '../../../types'

const route = useRoute()
const router = useRouter()
const store = useAppStore()
const { showToast } = useToast()
const { show: showConfirm } = useConfirmDialog()
const { prefs: notifyPrefs } = useNotifyPrefs()

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

// 保存状态（状态栏显示；实际写库在下方 handleUpdateChapter）
const saveStatus = ref<'idle' | 'saving' | 'saved' | 'error'>('idle')

// 完成弹窗状态
const completionVisible = ref(false)

// 生成/精修失败：session.error 原先全前端无渲染点，SSE 失败后用户无感知。
// 这里统一弹 error toast 并清空（stage 保持 'error'，由 Stepper/Overlay 展示失败态与重试入口）
watch(() => session.error.value, (err) => {
  if (err) {
    showToast(err, 'error')
    session.error.value = null
  }
})

// 生成完成时自动把正文写入章节
// 警示：必须用 oldStage 区分"真正的生成完成"vs"恢复/切章"——
// loadForChapter 恢复快照时会把 stage 设为 'done'（中断态有正文也强制 done），
// 若不过滤 oldStage，每次切回已完成章节/刷新首屏都会重触发 handleGenerated，
// 导致重复写库 + 误弹完成弹窗 + 误发系统通知。
// 真正完成：oldStage 是生成中的状态（非 idle/done）；恢复：oldStage 是 idle/done。
watch(() => session.stage.value, (newStage, oldStage) => {
  if (newStage === 'done' && oldStage !== 'idle' && oldStage !== 'done' && session.streamText.value) {
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
  saveStatus.value = 'idle'
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

// Markdown 批量导入章节（复用 import-markdown feature）
const showImportModal = ref(false)
function openImportModal() {
  if (!currentBook.value?.id) {
    showToast('请先选择书籍', 'warning')
    return
  }
  showImportModal.value = true
}

// 正文逆向提取（复用 extraction feature）
const showExtractionModal = ref(false)
function openExtractionModal() {
  if (!selectedChapter.value?.id) {
    showToast('请先选择章节', 'warning')
    return
  }
  showExtractionModal.value = true
}
function onExtractionCompleted() {
  // 刷新章节列表（角色/关联可能已更新）
  store.loadCurrentBookData()
}

// 多选删除章节
const selectMode = ref(false) // 是否处于多选模式
const checkedIds = ref<Set<string>>(new Set()) // 勾选中的章节 ID
const batchDeleting = ref(false)

function toggleSelectMode() {
  selectMode.value = !selectMode.value
  if (!selectMode.value) {
    checkedIds.value.clear()
    lastCheckedId.value = null
  }
}

function exitSelectMode() {
  selectMode.value = false
  checkedIds.value.clear()
  lastCheckedId.value = null
}

// 上次勾选的章节 ID（用于 Shift+点击范围选择）
const lastCheckedId = ref<string | null>(null)

/** 单击章节行的处理（随模式切换行为） */
function handleChapterClick(ch: Chapter, event: MouseEvent | KeyboardEvent) {
  if (selectMode.value) {
    toggleCheck(ch.id, event.shiftKey)
  } else {
    store.selectChapter(ch.id)
  }
}

/** 切换某章的勾选状态；Shift+点击时区间勾选 */
function toggleCheck(id: string, shiftKey: boolean) {
  const ids = sortedChapters.value.map((c) => c.id)
  if (shiftKey && lastCheckedId.value && lastCheckedId.value !== id) {
    // 范围选择：从上次到当前，全部置为「选中」
    const from = ids.indexOf(lastCheckedId.value)
    const to = ids.indexOf(id)
    if (from !== -1 && to !== -1) {
      const [lo, hi] = from < to ? [from, to] : [to, from]
      for (let i = lo; i <= hi; i++) {
        checkedIds.value.add(ids[i])
      }
      // 触发响应式更新（Set mutation 需重新赋值）
      checkedIds.value = new Set(checkedIds.value)
      return
    }
  }
  // 普通切换
  const next = new Set(checkedIds.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  checkedIds.value = next
  lastCheckedId.value = id
}

/** 全选 / 取消全选 */
const allChecked = computed(
  () => sortedChapters.value.length > 0 && checkedIds.value.size === sortedChapters.value.length,
)
function toggleCheckAll() {
  if (allChecked.value) {
    checkedIds.value = new Set()
    lastCheckedId.value = null
  } else {
    checkedIds.value = new Set(sortedChapters.value.map((c) => c.id))
    lastCheckedId.value = null
  }
}

/** 批量删除已勾选章节 */
async function batchDeleteChapters() {
  const ids = [...checkedIds.value]
  if (ids.length === 0) return
  const ok = await showConfirm({
    title: '批量删除章节',
    message: `确定删除选中的 ${ids.length} 个章节吗？`,
    warning: '章节正文、节拍与铺垫结构将一并删除，不可恢复。',
  })
  if (!ok) return
  batchDeleting.value = true
  let okCount = 0
  let failCount = 0
  // 串行删除，避免后端竞态
  for (const id of ids) {
    try {
      await store.deleteChapter(id)
      okCount++
    } catch {
      failCount++
    }
  }
  batchDeleting.value = false
  if (failCount === 0) {
    showToast(`已删除 ${okCount} 章`, 'success')
  } else {
    showToast(`删除 ${okCount} 章成功，${failCount} 章失败`, 'warning')
  }
  exitSelectMode()
}

function backToLibrary() {
  router.push({ name: 'library' })
}

async function handleUpdateChapter(id: string, updates: Record<string, unknown>) {
  saveStatus.value = 'saving'
  try {
    await store.updateChapter(id, updates as any)
    saveStatus.value = 'saved'
  } catch (e: any) {
    saveStatus.value = 'error'
    showToast('保存失败：' + e.message, 'error')
  }
}

function handleRefreshCharacters() {
  store.refreshCharacters()
}

// 生成完成：把正文灌入编辑器（通过 chapterEditorRef）+ 弹完成弹窗
async function handleGenerated(text: string) {
  if (selectedChapter.value && text) {
    try {
      await store.updateChapter(selectedChapter.value.id, { content_text: text, draft_text: text })
      showToast('已生成并写入章节', 'success')
      // 应用内完成弹窗（受通知偏好开关控制）
      if (notifyPrefs.value.inApp) {
        completionVisible.value = true
      }
      // 系统通知（受开关控制；主进程会再次判断窗口焦点兜底分层）
      if (notifyPrefs.value.system && window.electronAPI) {
        const isRefinery = session.lastDoneMode.value === 'refinery'
        window.electronAPI.showCompletionNotification({
          title: isRefinery ? '精修完成' : '章节生成完成',
          body: `《${selectedChapter.value.title || selectedChapter.value.chapter_name || '未命名'}》已就绪`,
        })
      }
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
            <button
              class="icon-btn select-toggle"
              :class="{ active: selectMode }"
              :title="selectMode ? '退出多选' : '多选删除'"
              @click="toggleSelectMode"
            >
              <Icon name="check-badge" :size="15" />
            </button>
          </div>

          <!-- 多选模式：全选栏 -->
          <div v-if="selectMode && !loading" class="select-all-bar" @click="toggleCheckAll">
            <span class="select-checkbox" :class="{ checked: allChecked }">
              <Icon v-if="allChecked" name="check" :size="12" />
            </span>
            <span class="select-all-label">全选（{{ checkedIds.size }}/{{ sortedChapters.length }}）</span>
          </div>

          <div v-if="loading" class="binder-loading">加载中…</div>
          <div v-else class="chapter-list">
            <div
              v-for="ch in sortedChapters"
              :key="ch.id"
              class="chapter-item"
              :class="{ active: !selectMode && ch.id === selectedChapterId, checked: selectMode && checkedIds.has(ch.id) }"
              role="button"
              tabindex="0"
              @click="handleChapterClick(ch, $event)"
              @keydown.enter="handleChapterClick(ch, $event)"
            >
              <!-- 多选模式：复选框 -->
              <span v-if="selectMode" class="select-checkbox" :class="{ checked: checkedIds.has(ch.id) }">
                <Icon v-if="checkedIds.has(ch.id)" name="check" :size="12" />
              </span>
              <span class="ch-num">{{ ch.chapter_number }}</span>
              <span class="ch-name">{{ ch.title || ch.chapter_name || '(未命名)' }}</span>
              <ChapterBadges v-if="!selectMode" :chapter="ch" />
              <button
                v-if="!selectMode"
                class="ch-delete"
                title="删除章节"
                @click.stop="confirmDeleteChapter(ch)"
              >
                <Icon name="trash" :size="12" />
              </button>
            </div>
          </div>

          <!-- 多选模式：批量操作栏（替换底部按钮区） -->
          <div v-if="selectMode" class="batch-actions">
            <span class="batch-count">已选 {{ checkedIds.size }} 章</span>
            <div class="batch-btns">
              <button
                class="batch-delete-btn"
                :disabled="checkedIds.size === 0 || batchDeleting"
                @click="batchDeleteChapters"
              >
                <Icon name="trash" :size="14" />
                <span>{{ batchDeleting ? '删除中…' : '删除选中' }}</span>
              </button>
              <button class="batch-cancel-btn" @click="exitSelectMode">
                <span>取消</span>
              </button>
            </div>
          </div>

          <div v-if="!selectMode" class="binder-actions">
            <button class="new-chapter-btn" @click="createChapter">
              <Icon name="plus" :size="14" />
              <span>新建章节</span>
            </button>
            <button class="import-btn" title="从 .md 文件批量导入章节" @click="openImportModal">
              <Icon name="arrow-up-tray" :size="14" />
              <span>导入 .md</span>
            </button>
            <button
              class="analyze-btn"
              title="从当前章节正文逆向提取角色/地点/伏笔等"
              :disabled="!selectedChapter"
              @click="openExtractionModal"
            >
              <Icon name="sparkles" :size="14" />
              <span>分析</span>
            </button>
          </div>
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
            <!-- 生成覆盖面板：绝对定位遮挡编辑器，显示进度；失败态保持展示（含重试/关闭） -->
            <GenerationOverlay
              v-if="isGenerating || session.stage.value === 'error'"
              :session="session"
              @cancel="session.cancel"
              @retry="session.retry"
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
            <span v-if="saveStatus === 'saving'">保存中…</span>
            <span v-else-if="saveStatus === 'saved'" class="muted">已保存</span>
          </footer>
        </main>
      </Pane>

      <!-- 右栏：Inspector 智能副驾 -->
      <Pane :size="splitSizes[2]" :min-size="16" :max-size="40" class="inspector-pane">
        <InspectorPanel
          :external-session="session"
          @jump-to-offset="handleJumpToOffset"
        />
      </Pane>
    </Splitpanes>

    <!-- Markdown 批量导入 Modal -->
    <MarkdownImportModal v-if="showImportModal" @close="showImportModal = false" />

    <!-- 正文逆向提取 Modal -->
    <ExtractionModal
      v-if="showExtractionModal && selectedChapter"
      :chapter-id="selectedChapter.id"
      @close="showExtractionModal = false"
      @completed="onExtractionCompleted"
    />

    <!-- 生成完成弹窗 -->
    <CompletionModal
      :show="completionVisible"
      :mode="session.lastDoneMode.value"
      :chapter-title="selectedChapter?.title || selectedChapter?.chapter_name"
      :stats="session.finalStats.value"
      @close="completionVisible = false"
    />
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

.chapter-item.checked {
  background: rgba(var(--accent-500-rgb, 124, 58, 237), 0.08);
}

.select-toggle.active {
  color: var(--accent-500);
  background: rgba(var(--accent-500-rgb, 124, 58, 237), 0.1);
}

/* 多选：全选栏 */
.select-all-bar {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.4375rem 0.625rem;
  border-bottom: 1px solid var(--border-color);
  font-size: 0.75rem;
  color: var(--text-secondary);
  cursor: pointer;
  flex-shrink: 0;
  transition: background 0.15s ease;
}

.select-all-bar:hover {
  background: var(--hover-bg);
}

.select-all-label {
  user-select: none;
}

/* 复选框（全选栏和章节行共用） */
.select-checkbox {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 1rem;
  height: 1rem;
  border: 1.5px solid var(--border-color);
  border-radius: 0.1875rem;
  background: var(--bg-canvas);
  color: white;
  flex-shrink: 0;
  transition: all 0.15s ease;
}

.select-checkbox.checked {
  border-color: var(--accent-500);
  background: var(--accent-500);
}

/* 多选：批量操作栏 */
.batch-actions {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  padding: 0.75rem;
  border-top: 1px solid var(--border-color);
  background: var(--bg-tertiary);
  flex-shrink: 0;
}

.batch-count {
  font-size: 0.75rem;
  color: var(--text-secondary);
  text-align: center;
}

.batch-btns {
  display: flex;
  gap: 0.375rem;
}

.batch-delete-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0.375rem;
  flex: 1;
  padding: 0.4375rem;
  background: #dc2626;
  color: white;
  border: none;
  border-radius: 0.25rem;
  font-size: 0.75rem;
  cursor: pointer;
  transition: background 0.15s ease;
}

.batch-delete-btn:hover:not(:disabled) {
  background: #b91c1c;
}

.batch-delete-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.batch-cancel-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0.4375rem 0.75rem;
  background: transparent;
  color: var(--text-secondary);
  border: 1px solid var(--border-color);
  border-radius: 0.25rem;
  font-size: 0.75rem;
  cursor: pointer;
  transition: all 0.15s ease;
}

.batch-cancel-btn:hover {
  background: var(--hover-bg);
  color: var(--text-primary);
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

.binder-actions {
  display: flex;
  gap: 0.25rem;
  margin: 0.375rem;
  flex-shrink: 0;
}

.new-chapter-btn,
.import-btn,
.analyze-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0.375rem;
  flex: 1;
  padding: 0.4375rem;
  background: transparent;
  border: 1px dashed var(--border-color);
  border-radius: 0.25rem;
  font-size: 0.75rem;
  color: var(--text-secondary);
  cursor: pointer;
  transition: all 0.15s ease;
}

.new-chapter-btn:hover {
  border-color: var(--accent-500);
  color: var(--accent-500);
}

.import-btn:hover {
  border-color: var(--accent-500);
  color: var(--accent-500);
}

.analyze-btn:hover:not(:disabled) {
  border-color: var(--accent-500);
  color: var(--accent-500);
}

.analyze-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
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
