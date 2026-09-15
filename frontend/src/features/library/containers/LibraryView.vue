<script setup lang="ts">
/**
 * 书架页（V3.1 F1 新建，规格 §3 + §8；2026-09-15 向导退役后为唯一建书入口）。
 *
 * 职责：
 * - 书籍卡片网格（封面 + 书名 + 题材 + 章节数 + 字数）
 * - "新建书籍"：轻表单（书名/题材/核心设定/一句话打算）——意图直落第 1 章
 *   spine（打算的最高置信源），其余设定随写作在世界页/写作台生长
 *   （novel-wizard 五步向导 2026-09-15 整体退役：三书零本向导出品，前置
 *   规划流程与「打字即激活、设定随写作生长」的写作台思路相悖）
 * - 点击书籍卡片进入写作台
 * - 卡片右键/管理：编辑/删除书籍
 */
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import Icon from '../../../components/Icon.vue'
import { useAppStore } from '../../app/useAppStore'
import { useToast } from '../../../composables/useToast'
import { useConfirmDialog } from '../../../composables/useConfirmDialog'
import MarkdownImportModal from '../../import-markdown/containers/MarkdownImportModal.vue'
import { chapterApi } from '../../../services/api'
import { adaptiveApi } from '../../../services/api/domain/adaptive.api'
import { countChapterWords } from '../../../shared/utils/htmlText'
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

const showEditModal = ref(false)
const editingBook = ref<Book | null>(null)
const editForm = ref({ title: '', genre: '', core_motifs_taboos: '' })

// 新建表单（唯一建书入口）
const showQuickCreate = ref(false)
const quickForm = ref({ title: '', genre: '', core_motifs_taboos: '', intent: '' })

onMounted(async () => {
  if (books.value.length === 0) {
    try {
      await store.loadBooks()
    } catch (e: any) {
      showToast('加载书籍失败：' + (e?.message || '未知错误'), 'error')
    }
  }
})

// 书籍统计预取缓存（只读，hover 时填充；当前书直接用 store 数据）
const statsMap = ref<Record<string, { chapterCount: number; totalWords: number }>>({})

function bookStats(book: Book): { chapterCount: number; totalWords: number } {
  // 若当前 store 的 chapters 属于本书，用之；否则用 hover 预取的只读统计
  if (currentBookId.value === book.id) {
    const chaps = chapters.value
    // 字数口径：剥 HTML 标签后计字符（此前 content_text.length 把标签计入，虚高）
    const totalWords = chaps.reduce((sum, c) => sum + countChapterWords(c.content_text || ''), 0)
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

function startQuickCreate() {
  quickForm.value = { title: '', genre: '', core_motifs_taboos: '', intent: '' }
  showQuickCreate.value = true
}

async function submitQuickCreate() {
  if (!quickForm.value.title.trim()) {
    showToast('请填写书名', 'warning')
    return
  }
  let newBook: Book | undefined
  try {
    newBook = await store.createBook({
      title: quickForm.value.title,
      genre: quickForm.value.genre,
      core_motifs_taboos: quickForm.value.core_motifs_taboos,
    } as Partial<Book>)
  } catch (e: any) {
    showToast('创建失败：' + e.message, 'error')
    return
  }
  if (!newBook) return

  // 一句话打算 → 第 1 章 spine.intent（作者亲笔=最高置信意图源，向导退役后
  // 唯一保留的意图通道；不填则跳过，进写作台「打算」面板随时补）
  const intent = quickForm.value.intent.trim()
  if (intent) {
    try {
      const ch = await chapterApi.create({
        book_id: newBook.id,
        chapter_number: 1,
        chapter_name: '第1章',
      } as any)
      // 意图截 60 字（同 useChapterSpine 截幅）；spine 失败不阻塞开书
      await adaptiveApi
        .patchSpine((ch as any)?.id || '', { intent: { text: intent.slice(0, 60), source: 'author' } })
        .catch(() => {})
    } catch {
      /* 第 1 章创建失败不阻塞：意图进写作台再补 */
    }
  }

  showQuickCreate.value = false
  showToast('书籍已创建', 'success')
  // D2 修复（GUI 实测 2026-08-30）：路由 fade 是 out-in——旧视图离场与弹窗
  // 离场过渡并发时换装可能被挂起（URL 已切、视图停在书架+弹窗 >25s）。
  // 先关弹窗、等它的 0.2s 离场完成再跳转，彻底错开两段过渡。
  setTimeout(() => openBook(newBook!), 250)
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
        <p class="page-subtitle"><span class="tnum">{{ books.length }}</span> 卷藏书 · 点击进入写作</p>
      </div>
      <div class="header-actions">
        <button class="btn-primary btn-primary-instrument" @click="startQuickCreate">
          <Icon name="plus" :size="16" />
          <span>新建书籍</span>
        </button>
      </div>
    </header>

    <!-- 空状态 -->
    <div v-if="isEmpty && !loading" class="empty-state">
      <h2 class="empty-state__title">开始你的第一本书</h2>
      <p>起个书名就能开写——角色、世界观随写作慢慢长出来。</p>
      <div class="empty-actions">
        <button class="btn-primary btn-primary-instrument" @click="startQuickCreate">
          <Icon name="plus" :size="16" />
          <span>新建书籍</span>
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
        <div class="book-cover" :style="{ background: bookCloth(book) }">
          <!-- 几何母题：按书名 hash 六选一，同色系烫印质感，题材中立 -->
          <svg class="cover-motif" viewBox="0 0 300 400" preserveAspectRatio="xMidYMid slice" aria-hidden="true">
            <g v-if="coverMotif(book) === 'arcs'" fill="none" stroke="rgba(255,255,255,0.14)" stroke-width="26">
              <circle cx="318" cy="-52" r="128" />
              <circle cx="318" cy="-52" r="200" opacity="0.62" />
              <circle cx="318" cy="-52" r="272" opacity="0.38" />
              <circle cx="318" cy="-52" r="344" opacity="0.22" />
            </g>
            <g v-else-if="coverMotif(book) === 'stripes'" fill="rgba(255,255,255,0.13)" transform="rotate(-18 150 200)">
              <rect x="-60" y="112" width="420" height="34" />
              <rect x="-60" y="188" width="420" height="34" />
              <rect x="-60" y="264" width="420" height="34" opacity="0.5" />
            </g>
            <g v-else-if="coverMotif(book) === 'dots'" fill="rgba(255,255,255,0.15)">
              <circle v-for="p in DOT_GRID" :key="p.x + '-' + p.y" :cx="p.x" :cy="p.y" r="6" />
            </g>
            <g v-else-if="coverMotif(book) === 'ridge'" fill="none" stroke="rgba(255,255,255,0.15)" stroke-width="22" stroke-linecap="round" stroke-linejoin="round">
              <polyline points="-20,300 70,190 150,265 240,140 320,230" />
              <polyline points="-20,360 80,290 170,340 260,240 320,300" opacity="0.45" />
            </g>
            <g v-else-if="coverMotif(book) === 'moon'">
              <circle cx="208" cy="120" r="112" fill="rgba(255,255,255,0.13)" />
              <circle cx="208" cy="120" r="112" fill="none" stroke="rgba(255,255,255,0.1)" stroke-width="2" />
            </g>
            <g v-else stroke="rgba(255,255,255,0.14)" stroke-width="2">
              <path d="M60 0V400 M120 0V400 M180 0V400 M240 0V400" />
              <path d="M0 100H300 M0 200H300 M0 300H300" />
              <rect x="180" y="100" width="60" height="100" fill="rgba(255,255,255,0.16)" stroke="none" />
            </g>
          </svg>
          <div class="cover-titles">
            <span v-if="book.genre" class="cover-genre">{{ book.genre }}</span>
            <span class="cover-name" :style="{ fontSize: coverNameFont(book.title) }">{{ book.title || '未命名' }}</span>
          </div>
        </div>
        <div class="book-info">
          <h3 class="book-title">{{ book.title }}</h3>
          <p class="book-stats">
            <template v-if="hasStats(book)"
              >{{ bookStats(book).chapterCount }} 章 · {{ formatWords(bookStats(book).totalWords) }}</template
            >
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

      <!-- 新书幽灵卡：网格尾部常驻，虚线书位 -->
      <button class="book-card ghost-card" type="button" @click="startQuickCreate">
        <div class="ghost-cover">
          <Icon name="plus" :size="20" />
          <span class="ghost-label">新的一本书</span>
        </div>
        <div class="book-info">
          <h3 class="book-title">开新书</h3>
          <p class="book-stats">起个书名，马上开写</p>
        </div>
      </button>
    </div>

    <!-- 快速创建 Modal（唯一建书入口） -->
    <Transition name="modal">
      <div v-if="showQuickCreate" class="modal-overlay" @click.self="showQuickCreate = false">
        <div class="modal-content quick-create-modal">
          <h3>新建书籍</h3>
          <div class="form-field">
            <label>书名 *</label>
            <input v-model="quickForm.title" class="field" placeholder="为这本书起个名字" autofocus />
          </div>
          <div class="form-field">
            <label>题材</label>
            <input v-model="quickForm.genre" class="field" placeholder="如：奇幻、科幻、悬疑" />
          </div>
          <div class="form-field">
            <label>一句话打算</label>
            <textarea
              v-model="quickForm.intent"
              class="field"
              rows="2"
              placeholder="这本书大概要写什么（可不填，进写作台「打算」面板随时补）"
            />
          </div>
          <div class="form-field">
            <label>核心设定与禁忌</label>
            <textarea v-model="quickForm.core_motifs_taboos" class="field" rows="3" placeholder="世界观要点、需要避免的内容" />
          </div>
          <div class="modal-actions">
            <button class="btn-secondary btn-ghost" @click="showQuickCreate = false">取消</button>
            <button class="btn-primary btn-primary-instrument" @click="submitQuickCreate">创建并进入写作</button>
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
            <input v-model="editForm.title" class="field" />
          </div>
          <div class="form-field">
            <label>题材</label>
            <input v-model="editForm.genre" class="field" />
          </div>
          <div class="form-field">
            <label>核心设定与禁忌</label>
            <textarea v-model="editForm.core_motifs_taboos" class="field" rows="3" />
          </div>
          <div class="modal-actions">
            <button class="btn-secondary btn-ghost" @click="showEditModal = false">取消</button>
            <button class="btn-primary btn-primary-instrument" @click="submitEdit">保存</button>
          </div>
        </div>
      </div>
    </Transition>

    <!-- Markdown 批量导入 Modal -->
    <MarkdownImportModal v-if="showImportModal" @close="showImportModal = false" />
  </div>
</template>

<script lang="ts">
// 封面底色：低饱和深色板（浅深双主题下同一副面孔——封面是「内容」而非
// UI 表皮，不进全局 token）。按书名 hash 稳定取色：同一本书永远同一件书衣。
function bookCloth(book: Book): string {
  const palettes = ['#34506b', '#7a3e3e', '#52466b', '#3f5747', '#75563a', '#514c46']
  const name = book.title || book.id || ''
  let hash = 0
  for (let i = 0; i < name.length; i++) {
    hash = (hash * 31 + name.charCodeAt(i)) | 0
  }
  return palettes[Math.abs(hash) % palettes.length]
}

// 母题类型：hash 右移取独立位，与底色不相关——同色不同纹、同纹不同色都可能出现
type MotifKey = 'arcs' | 'stripes' | 'dots' | 'ridge' | 'moon' | 'grid'
function coverMotif(book: Book): MotifKey {
  const keys: MotifKey[] = ['arcs', 'stripes', 'dots', 'ridge', 'moon', 'grid']
  const name = book.title || book.id || ''
  let hash = 0
  for (let i = 0; i < name.length; i++) {
    hash = (hash * 31 + name.charCodeAt(i)) | 0
  }
  return keys[Math.abs(hash >> 3) % keys.length]
}

// dots 母题的点阵坐标（6 列 × 8 行，封面 viewBox 300×400）
const DOT_GRID: Array<{ x: number; y: number }> = (() => {
  const pts: Array<{ x: number; y: number }> = []
  for (let row = 0; row < 8; row++) {
    for (let col = 0; col < 6; col++) {
      pts.push({ x: 36 + col * 46, y: 34 + row * 46 })
    }
  }
  return pts
})()

// 封面书名字号：短书名大字、长书名降档（另有两行 clamp 兜底）
function coverNameFont(title?: string): string {
  const len = (title || '').length
  if (len <= 4) return '1.375rem'
  if (len <= 8) return '1.125rem'
  return '0.9375rem'
}

// 字数人话化：≥1 万收敛为「X.X 万字」
function formatWords(words: number): string {
  if (words >= 10000) return `${(words / 10000).toFixed(1)} 万字`
  return `${words} 字`
}
</script>

<style scoped>
.library-view {
  height: 100%;
  overflow-y: auto;
  background: var(--bg-primary);
  padding: 2.5rem 2.75rem 3rem;
}

.library-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  margin-bottom: 2.25rem;
}

.page-title {
  font-family: var(--font-heading);
  font-size: var(--text-3xl);
  letter-spacing: 0.08em;
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

/* N3 §4：新建表单（非书封部分）收编仪器工具类——书封六色板豁免面不动 */
.btn-primary,
.btn-secondary {
  /* 挂点：皮肤由 .btn-primary-instrument / .btn-ghost 提供 */
}

/* 空状态 */
.empty-state {
  /* 04 §D3 空态统一规格：全局类出 ❦ 饰符，此处只留节奏微调 */
  padding: var(--space-12) var(--space-8);
}

.empty-state__title {
  font-family: var(--font-heading);
  font-size: var(--text-xl);
  font-weight: 500;
  color: var(--text-primary);
  margin: 0;
}

.empty-state p {
  font-size: var(--text-sm);
  line-height: var(--lh-normal);
  margin: 0 0 var(--space-3);
}

.empty-actions {
  display: flex;
  gap: 0.625rem;
}

/* 书籍网格 */
.books-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(215px, 1fr));
  gap: var(--space-5);
}

.book-card {
  position: relative;
  background: var(--bg-canvas);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-sm);
  padding: var(--space-3) var(--space-3) var(--space-4);
  cursor: pointer;
  transition: all 0.18s ease;
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  font: inherit;
  text-align: left;
}

.book-card:hover {
  border-color: var(--accent-400);
  transform: translateY(-2px);
  box-shadow: var(--shadow-lg);
}

/* 深色主题：黑阴影透明度加深一档，保住 hover 的浮起感 */
:global(html.dark) .book-card:hover {
  box-shadow: var(--shadow-lg);
}

/* 封面底：径向柔光 + 经纬细纹 + 内衬描边（哑光纸板质感），
   底色由 bookCloth() 按书名 hash 供给；封面是内容，双主题同一副面孔 */
.book-cover {
  position: relative;
  width: 100%;
  aspect-ratio: 3 / 4;
  border-radius: var(--radius-xs);
  background-image:
    radial-gradient(130% 95% at 50% 38%, rgba(255, 255, 255, 0.06), transparent 62%),
    repeating-linear-gradient(90deg, rgba(255, 255, 255, 0.03) 0 1px, transparent 1px 3px),
    repeating-linear-gradient(0deg, rgba(0, 0, 0, 0.05) 0 1px, transparent 1px 4px);
  box-shadow:
    inset 0 0 0 1px rgba(0, 0, 0, 0.24),
    inset 0 1px 0 rgba(255, 255, 255, 0.08);
  overflow: hidden;
  transition: box-shadow 0.18s ease;
}

.book-card:hover .book-cover {
  box-shadow:
    inset 0 0 0 1px rgba(0, 0, 0, 0.28),
    inset 0 1px 0 rgba(255, 255, 255, 0.1),
    0 1px 0 rgba(0, 0, 0, 0.12);
}

/* 几何母题：铺满封面的低对比烫印图形（题材中立，hash 六选一） */
.cover-motif {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
}

/* 封面书名区：底部渐晕压深保可读，母题重心在上 2/3 让位 */
.cover-titles {
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  padding: 2.25rem 1rem 1rem;
  background: linear-gradient(to top, rgba(0, 0, 0, 0.36), rgba(0, 0, 0, 0.14) 55%, transparent);
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.cover-genre {
  font-size: 0.6875rem;
  letter-spacing: 0.22em;
  color: rgba(255, 255, 255, 0.68);
}

.cover-name {
  font-family: var(--font-heading);
  font-weight: 600;
  line-height: 1.3;
  color: rgba(255, 255, 255, 0.96);
  text-shadow: 0 1px 4px rgba(0, 0, 0, 0.25);
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
  overflow: hidden;
}

/* 新书幽灵卡：虚线书位。边框取 faint 档而非常规 border——虚线本身的
   存在感弱于实线，深色主题下常规 --border-color (#3a3530) 几乎不可见 */
.ghost-card {
  background: transparent;
  border: 1px dashed var(--text-faint);
  align-items: stretch;
}

.ghost-card:hover {
  border-color: var(--accent-400);
  background: var(--bg-canvas);
  transform: translateY(-2px);
}

.ghost-cover {
  width: 100%;
  aspect-ratio: 3 / 4;
  border-radius: var(--radius-xs);
  border: 1px dashed var(--text-faint);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  color: var(--text-secondary);
  transition: color 0.18s ease, border-color 0.18s ease;
}

.ghost-card:hover .ghost-cover {
  color: var(--accent-500);
  border-color: var(--accent-400);
}

.ghost-label {
  font-family: var(--font-heading);
  font-size: var(--text-sm);
  letter-spacing: 0.15em;
}

.book-info {
  flex: 1;
  min-width: 0;
  padding: 0 var(--space-1);
}

.book-title {
  font-family: var(--font-heading);
  font-size: var(--text-md);
  font-weight: 600;
  color: var(--text-primary);
  margin: 0 0 0.375rem;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.book-stats {
  font-size: var(--text-xs);
  color: var(--text-muted);
  margin: 0;
}

.book-actions {
  position: absolute;
  top: var(--space-2);
  right: var(--space-2);
  display: flex;
  gap: 0.25rem;
  /* 02 期 §8 H3：focus-within 键盘对等（opacity 保 tab 序） */
  opacity: 0;
  transition: opacity 0.15s ease;
}

.book-card:hover .book-actions,
.book-card:focus-within .book-actions {
  opacity: 1;
}

.icon-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 1.75rem;
  height: 1.75rem;
  /* 纸色底：钮落在深色书衣上，双主题恒定（封面上的控件跟封面走） */
  background: color-mix(in srgb, var(--paper-bg) 92%, transparent);
  border: 1px solid rgba(0, 0, 0, 0.18);
  border-radius: var(--radius-xs);
  color: var(--text-secondary);
  cursor: pointer;
  transition: all 0.15s ease;
}
.icon-btn:hover {
  background: var(--paper-bg);
  color: var(--text-primary);
}
/* 02 期 §8 H3：删除（破坏性）钮常态 45% 低显 */
.icon-btn.danger {
  opacity: 0.45;
}
.icon-btn.danger:hover,
.icon-btn.danger:focus-visible {
  opacity: 1;
}
.icon-btn.danger:hover {
  color: var(--danger);
  border-color: var(--danger);
}

/* Modal 通用 */
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.4);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: var(--z-overlay);
  padding: 2rem;
}

.modal-content {
  background: var(--bg-canvas);
  border-radius: var(--radius-md);
  padding: 1.5rem;
  width: 100%;
  max-width: 420px;
  box-shadow: var(--shadow-lg);
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

/* N3 §4：表单控件收编 .field（皮肤工具类提供） */
.form-field input,
.form-field textarea {
  /* 挂点：皮肤由 .field 提供 */
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
