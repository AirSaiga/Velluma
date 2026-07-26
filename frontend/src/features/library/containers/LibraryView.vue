<script setup lang="ts">
/**
 * 书架页（V3.1 F1 新建，规格 §3 + §8）。
 *
 * 职责：
 * - 书籍卡片网格（封面色块 + 书名 + 题材 + 章节数 + 最近编辑）
 * - "新建书籍"入口：启用现成的 novel-wizard（5 步向导）
 * - 点击书籍卡片进入写作台
 * - 卡片右键/管理：编辑/删除书籍
 *
 * 设计依据：规格 §3 "书架：书籍卡片网格；'新建书籍'启用现成的 novel-wizard"
 */
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import Icon from '../../../components/Icon.vue'
import { useAppStore } from '../../app/useAppStore'
import { useToast } from '../../../composables/useToast'
import { useConfirmDialog } from '../../../composables/useConfirmDialog'
import { NovelCreationWizard } from '../../novel-wizard'
import MarkdownImportModal from '../../import-markdown/containers/MarkdownImportModal.vue'
import { chapterApi } from '../../../services/api'
import type { Book, Chapter } from '../../../types'

const router = useRouter()
const store = useAppStore()
const { showToast } = useToast()
const { show: showConfirm } = useConfirmDialog()

// 解构出 ref 供模板自动解包使用（store.xxx 是 Ref，模板里 store.xxx 不会自动解包）
const books = store.books
const currentBookId = store.currentBookId
const chapters = store.chapters
const loading = store.loading

const showWizard = ref(false)
const showEditModal = ref(false)
const editingBook = ref<Book | null>(null)
const editForm = ref({ title: '', genre: '', core_motifs_taboos: '' })

// 简易新建表单（与 novel-wizard 互斥：默认走向导，也可用简易快速创建）
const showQuickCreate = ref(false)
const quickForm = ref({ title: '', genre: '', global_sys_prompt: '', core_motifs_taboos: '' })

onMounted(async () => {
  if (books.value.length === 0) {
    await store.loadBooks()
  }
})

// 书籍统计预取缓存（只读，hover 时填充；当前书直接用 store 数据）
const statsMap = ref<Record<string, { chapterCount: number; totalWords: number }>>({})

function bookStats(book: Book): { chapterCount: number; totalWords: number } {
  // 若当前 store 的 chapters 属于本书，用之；否则用 hover 预取的只读统计
  if (currentBookId.value === book.id) {
    const chaps = chapters.value
    const totalWords = chaps.reduce((sum, c) => sum + (c.content_text?.length || 0), 0)
    return { chapterCount: chaps.length, totalWords }
  }
  return statsMap.value[book.id] ?? { chapterCount: 0, totalWords: 0 }
}

function hasStats(book: Book): boolean {
  return currentBookId.value === book.id || book.id in statsMap.value
}

function openBook(book: Book) {
  router.push({ name: 'workspace', params: { bookId: book.id } })
}

async function loadBookStats(book: Book) {
  // 只读预取章节统计：不切换全局当前书（避免 hover 触发整书重载）
  if (currentBookId.value === book.id || book.id in statsMap.value) return
  try {
    const chaps: Chapter[] = await chapterApi.getAll(book.id)
    statsMap.value[book.id] = {
      chapterCount: chaps.length,
      totalWords: chaps.reduce((sum, c) => sum + (c.content_text?.length || 0), 0),
    }
  } catch {
    // 预取失败静默忽略，卡片仍显示占位
  }
}

function startWizard() {
  showWizard.value = true
}

function startQuickCreate() {
  quickForm.value = { title: '', genre: '', global_sys_prompt: '', core_motifs_taboos: '' }
  showQuickCreate.value = true
}

async function submitQuickCreate() {
  if (!quickForm.value.title.trim()) {
    showToast('请填写书名', 'warning')
    return
  }
  try {
    const newBook = await store.createBook({
      title: quickForm.value.title,
      genre: quickForm.value.genre,
      global_sys_prompt: quickForm.value.global_sys_prompt,
      core_motifs_taboos: quickForm.value.core_motifs_taboos,
    } as Partial<Book>)
    showQuickCreate.value = false
    showToast('书籍已创建', 'success')
    if (newBook) openBook(newBook)
  } catch (e: any) {
    showToast('创建失败：' + e.message, 'error')
  }
}

function openEditModal(book: Book) {
  editingBook.value = book
  editForm.value = {
    title: book.title || '',
    genre: book.genre || '',
    core_motifs_taboos: book.core_motifs_taboos || '',
  }
  showEditModal.value = true
}

async function submitEdit() {
  if (!editingBook.value || !editForm.value.title.trim()) return
  try {
    // 显式传被编辑书的 id，避免误改全局当前书
    await store.updateBook(editingBook.value.id, {
      title: editForm.value.title,
      genre: editForm.value.genre,
      core_motifs_taboos: editForm.value.core_motifs_taboos,
    })
    showEditModal.value = false
    showToast('已保存', 'success')
  } catch (e: any) {
    showToast('保存失败：' + e.message, 'error')
  }
}

async function deleteBook(book: Book) {
  const ok = await showConfirm({
    title: '确认删除',
    message: `确定要删除《${book.title}》吗？此操作会删除其下所有章节与角色。`,
    warning: '此操作不可撤销',
  })
  if (!ok) return
  try {
    await store.deleteBook(book.id)
    showToast('已删除', 'success')
  } catch (e: any) {
    showToast('删除失败：' + e.message, 'error')
  }
}

// novel-wizard 完成回调（向导 emit start-generation，payload 为嵌套的 WizardFormData）
async function onWizardFinish(formData: any) {
  try {
    // 字段映射：向导的嵌套结构 → 后端 Book 模型支持的扁平字段
    // （world/locations/rules 等后端无对应列的内容并入 worldview_settings dict）
    const newBook = await store.createBook({
      title: formData.story?.title?.trim() || '未命名',
      genre: formData.story?.genre,
      global_sys_prompt: formData.story?.styleGuide,
      core_motifs_taboos: formData.story?.themesAndTaboos,
      worldview_settings: {
        background: formData.world?.background ?? [],
        locations: formData.world?.locations ?? [],
        rules: formData.world?.rules ?? [],
      },
    } as Partial<Book>)
    showWizard.value = false
    showToast('书籍已创建', 'success')
    if (newBook) openBook(newBook)
  } catch (e: any) {
    showToast('创建失败：' + e.message, 'error')
  }
}

function onWizardCancel() {
  showWizard.value = false
}

const isEmpty = computed(() => books.value.length === 0)

// Markdown 批量导入：从指定书籍卡片触发（需先选中该书）
const showImportModal = ref(false)
const importTargetBookId = ref<string | null>(null)

function openImportModal(book: Book) {
  // 选中目标书（store.currentBookId 决定导入去向）
  store.selectBook(book.id)
  importTargetBookId.value = book.id
  showImportModal.value = true
}</script>

<template>
  <div class="library-view">
    <header class="library-header">
      <div>
        <h1 class="page-title">书架</h1>
        <p class="page-subtitle">{{ books.length }} 本书 · 点击进入写作</p>
      </div>
      <div class="header-actions">
        <button class="btn-secondary" @click="startQuickCreate">
          <Icon name="plus" :size="16" />
          <span>快速创建</span>
        </button>
        <button class="btn-primary" @click="startWizard">
          <Icon name="sparkles" :size="16" />
          <span>新建书籍向导</span>
        </button>
      </div>
    </header>

    <!-- 空状态 -->
    <div v-if="isEmpty && !loading" class="empty-state">
      <div class="empty-icon"><Icon name="book" :size="48" /></div>
      <h2>开始你的第一本书</h2>
      <p>用向导一步步搭建故事骨架，或快速创建一本空白书籍。</p>
      <div class="empty-actions">
        <button class="btn-primary" @click="startWizard">
          <Icon name="sparkles" :size="16" />
          <span>使用向导创建</span>
        </button>
        <button class="btn-secondary" @click="startQuickCreate">
          <Icon name="plus" :size="16" />
          <span>快速创建</span>
        </button>
      </div>
    </div>

    <!-- 书籍网格 -->
    <div v-else class="books-grid">
      <article
        v-for="book in books"
        :key="book.id"
        class="book-card"
        @click="openBook(book)"
        @mouseenter="loadBookStats(book)"
      >
        <div class="book-cover" :style="{ background: coverGradient(book) }">
          <span class="cover-title">{{ book.title?.charAt(0) || '?' }}</span>
        </div>
        <div class="book-info">
          <h3 class="book-title">{{ book.title }}</h3>
          <p v-if="book.genre" class="book-genre">{{ book.genre }}</p>
          <p class="book-stats">
            <span v-if="hasStats(book)">{{ bookStats(book).chapterCount }} 章</span>
            <span v-else class="muted">点击查看</span>
          </p>
        </div>
        <div class="book-actions" @click.stop>
          <button class="icon-btn" title="导入 .md 章节" @click="openImportModal(book)">
            <Icon name="arrow-up-tray" :size="14" />
          </button>
          <button class="icon-btn" title="编辑" @click="openEditModal(book)">
            <Icon name="pencil" :size="14" />
          </button>
          <button class="icon-btn danger" title="删除" @click="deleteBook(book)">
            <Icon name="trash" :size="14" />
          </button>
        </div>
      </article>
    </div>

    <!-- 快速创建 Modal -->
    <Transition name="modal">
      <div v-if="showQuickCreate" class="modal-overlay" @click.self="showQuickCreate = false">
        <div class="modal-content quick-create-modal">
          <h3>快速创建书籍</h3>
          <div class="form-field">
            <label>书名 *</label>
            <input v-model="quickForm.title" placeholder="为这本书起个名字" autofocus />
          </div>
          <div class="form-field">
            <label>题材</label>
            <input v-model="quickForm.genre" placeholder="如：奇幻、科幻、悬疑" />
          </div>
          <div class="form-field">
            <label>核心设定与禁忌</label>
            <textarea v-model="quickForm.core_motifs_taboos" rows="3" placeholder="世界观要点、需要避免的内容" />
          </div>
          <div class="form-field">
            <label>全局提示词（可选）</label>
            <textarea v-model="quickForm.global_sys_prompt" rows="2" placeholder="注入 LLM 的全局约束" />
          </div>
          <div class="modal-actions">
            <button class="btn-secondary" @click="showQuickCreate = false">取消</button>
            <button class="btn-primary" @click="submitQuickCreate">创建</button>
          </div>
        </div>
      </div>
    </Transition>

    <!-- 编辑 Modal -->
    <Transition name="modal">
      <div v-if="showEditModal" class="modal-overlay" @click.self="showEditModal = false">
        <div class="modal-content edit-modal">
          <h3>编辑书籍</h3>
          <div class="form-field">
            <label>书名</label>
            <input v-model="editForm.title" />
          </div>
          <div class="form-field">
            <label>题材</label>
            <input v-model="editForm.genre" />
          </div>
          <div class="form-field">
            <label>核心设定与禁忌</label>
            <textarea v-model="editForm.core_motifs_taboos" rows="3" />
          </div>
          <div class="modal-actions">
            <button class="btn-secondary" @click="showEditModal = false">取消</button>
            <button class="btn-primary" @click="submitEdit">保存</button>
          </div>
        </div>
      </div>
    </Transition>

    <!-- novel-wizard 向导（事件名与 NovelCreationWizard 的 emit 对齐） -->
    <Transition name="modal">
      <div v-if="showWizard" class="wizard-overlay">
        <NovelCreationWizard @start-generation="onWizardFinish" @close="onWizardCancel" />
      </div>
    </Transition>

    <!-- Markdown 批量导入 Modal -->
    <MarkdownImportModal v-if="showImportModal" @close="showImportModal = false" />
  </div>
</template>

<script lang="ts">
// 封面色块的渐变生成（基于书名 hash，稳定且无 emoji）
function coverGradient(book: Book): string {
  const palettes = [
    'linear-gradient(135deg, #6d5dab 0%, #a78bfa 100%)',
    'linear-gradient(135deg, #0369a1 0%, #38bdf8 100%)',
    'linear-gradient(135deg, #b45309 0%, #fbbf24 100%)',
    'linear-gradient(135deg, #047857 0%, #34d399 100%)',
    'linear-gradient(135deg, #be185d 0%, #f472b6 100%)',
    'linear-gradient(135deg, #4a4540 0%, #a89e90 100%)',
  ]
  const name = book.title || book.id || ''
  let hash = 0
  for (let i = 0; i < name.length; i++) {
    hash = (hash * 31 + name.charCodeAt(i)) | 0
  }
  return palettes[Math.abs(hash) % palettes.length]
}
</script>

<style scoped>
.library-view {
  height: 100%;
  overflow-y: auto;
  background: var(--bg-primary);
  padding: 2rem 2.5rem;
}

.library-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  margin-bottom: 2rem;
}

.page-title {
  font-family: var(--font-heading);
  font-size: 1.5rem;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0;
}

.page-subtitle {
  font-size: 0.8125rem;
  color: var(--text-muted);
  margin: 0.25rem 0 0;
}

.header-actions {
  display: flex;
  gap: 0.5rem;
}

.btn-primary,
.btn-secondary {
  display: inline-flex;
  align-items: center;
  gap: 0.375rem;
  padding: 0.4375rem 0.875rem;
  font-size: 0.8125rem;
  font-weight: 500;
  border-radius: 0.375rem;
  cursor: pointer;
  transition: all 0.15s ease;
  border: 1px solid transparent;
}

.btn-primary {
  background: var(--accent-500);
  color: white;
}
.btn-primary:hover {
  background: var(--accent-600);
}

.btn-secondary {
  background: var(--bg-canvas);
  color: var(--text-primary);
  border-color: var(--border-color);
}
.btn-secondary:hover {
  background: var(--hover-bg);
}

/* 空状态 */
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 4rem 2rem;
  text-align: center;
  color: var(--text-secondary);
}

.empty-icon {
  color: var(--text-muted);
  margin-bottom: 1rem;
}

.empty-state h2 {
  font-family: var(--font-heading);
  font-size: 1.25rem;
  font-weight: 500;
  color: var(--text-primary);
  margin: 0 0 0.5rem;
}

.empty-state p {
  font-size: 0.875rem;
  margin: 0 0 1.5rem;
}

.empty-actions {
  display: flex;
  gap: 0.625rem;
}

/* 书籍网格 */
.books-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 1rem;
}

.book-card {
  position: relative;
  background: var(--bg-canvas);
  border: 1px solid var(--border-color);
  border-radius: 0.5rem;
  padding: 0.875rem;
  cursor: pointer;
  transition: all 0.15s ease;
  display: flex;
  flex-direction: column;
  gap: 0.625rem;
}

.book-card:hover {
  border-color: var(--accent-500);
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.06);
}

.book-cover {
  width: 100%;
  aspect-ratio: 3 / 4;
  border-radius: 0.375rem;
  display: flex;
  align-items: center;
  justify-content: center;
  color: rgba(255, 255, 255, 0.95);
  font-family: var(--font-heading);
  font-size: 2.5rem;
  font-weight: 600;
  text-shadow: 0 1px 3px rgba(0, 0, 0, 0.2);
}

.book-info {
  flex: 1;
  min-width: 0;
}

.book-title {
  font-size: 0.9375rem;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0 0 0.125rem;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.book-genre {
  font-size: 0.75rem;
  color: var(--accent-500);
  margin: 0 0 0.25rem;
}

.book-stats {
  font-size: 0.6875rem;
  color: var(--text-muted);
  margin: 0;
}

.book-stats .muted {
  opacity: 0.6;
}

.book-actions {
  position: absolute;
  top: 0.5rem;
  right: 0.5rem;
  display: flex;
  gap: 0.25rem;
  opacity: 0;
  transition: opacity 0.15s ease;
}

.book-card:hover .book-actions {
  opacity: 1;
}

.icon-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 1.75rem;
  height: 1.75rem;
  background: var(--bg-canvas);
  border: 1px solid var(--border-color);
  border-radius: 0.25rem;
  color: var(--text-secondary);
  cursor: pointer;
  transition: all 0.15s ease;
}
.icon-btn:hover {
  background: var(--hover-bg);
  color: var(--text-primary);
}
.icon-btn.danger:hover {
  color: #dc2626;
  border-color: #dc2626;
}

/* Modal 通用 */
.modal-overlay,
.wizard-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.4);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
  padding: 2rem;
}

.modal-content {
  background: var(--bg-canvas);
  border-radius: 0.5rem;
  padding: 1.5rem;
  width: 100%;
  max-width: 420px;
  box-shadow: 0 10px 40px rgba(0, 0, 0, 0.15);
}

.wizard-overlay {
  padding: 1rem;
}

.modal-content h3 {
  font-family: var(--font-heading);
  font-size: 1.0625rem;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0 0 1rem;
}

.form-field {
  margin-bottom: 0.875rem;
}

.form-field label {
  display: block;
  font-size: 0.75rem;
  font-weight: 500;
  color: var(--text-secondary);
  margin-bottom: 0.25rem;
}

.form-field input,
.form-field textarea {
  width: 100%;
  padding: 0.4375rem 0.625rem;
  font-size: 0.8125rem;
  font-family: inherit;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 0.25rem;
  color: var(--text-primary);
  resize: vertical;
}

.form-field input:focus,
.form-field textarea:focus {
  outline: none;
  border-color: var(--accent-500);
}

.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 0.5rem;
  margin-top: 1rem;
}

.modal-enter-active,
.modal-leave-active {
  transition: opacity 0.2s ease;
}
.modal-enter-from,
.modal-leave-to {
  opacity: 0;
}
</style>
