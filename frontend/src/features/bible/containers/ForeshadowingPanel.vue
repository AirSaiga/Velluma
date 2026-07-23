<script setup lang="ts">
/**
 * 伏笔账本面板（V3.1 F4，规格 §7）。
 *
 * PlotLedger 表格视图：内容/状态/埋设章/回收章/证据。
 * 自动登记条目（setup_graph_auto 来源）带"AI 登记"徽标。
 * 支持手动添加、编辑（内容/类型/状态）、删除。
 *
 * 状态：open（埋设中）→ closed（已回收）/ dropped（已废弃）。
 *
 * 后端：GET/POST /api/books/{id}/ledgers，PUT/DELETE /api/ledgers/{id}。
 */
import { ref, computed, onMounted, watch } from 'vue'
import Icon from '../../../components/Icon.vue'
import { plotLedgerApi, type PlotLedgerEntry } from '../../../services/api/domain'
import { useToast } from '../../../composables/useToast'
import { useConfirmDialog } from '../../../composables/useConfirmDialog'

const props = defineProps<{
  bookId: string
}>()

const { showToast } = useToast()
const { show: showConfirm } = useConfirmDialog()

const entries = ref<PlotLedgerEntry[]>([])
const loading = ref(false)
const error = ref<string | null>(null)
const filterStatus = ref<'all' | 'open' | 'closed' | 'dropped'>('all')

async function load() {
  if (!props.bookId) return
  loading.value = true
  error.value = null
  try {
    entries.value = await plotLedgerApi.listByBook(props.bookId)
  } catch (e: any) {
    error.value = e.message
    entries.value = []
  } finally {
    loading.value = false
  }
}

onMounted(load)
watch(() => props.bookId, load)

const filtered = computed(() => {
  if (filterStatus.value === 'all') return entries.value
  return entries.value.filter((e) => e.status === filterStatus.value)
})

const counts = computed(() => ({
  all: entries.value.length,
  open: entries.value.filter((e) => e.status === 'open').length,
  closed: entries.value.filter((e) => e.status === 'closed').length,
  dropped: entries.value.filter((e) => e.status === 'dropped').length,
}))

function statusLabel(status: string): string {
  switch (status) {
    case 'open': return '埋设中'
    case 'closed': return '已回收'
    case 'dropped': return '已废弃'
    default: return status
  }
}

function statusClass(status: string): string {
  switch (status) {
    case 'open': return 'open'
    case 'closed': return 'closed'
    case 'dropped': return 'dropped'
    default: return ''
  }
}

function isAutoRegistered(entry: PlotLedgerEntry): boolean {
  return entry.meta?.source === 'setup_graph_auto' || entry.meta?.source === 'detonation_chain'
}

function evidence(entry: PlotLedgerEntry): string | null {
  const ev = entry.meta?.planted_in_text
  if (typeof ev === 'string' && ev) return ev
  return null
}

// ============================================================
// 手动维护：添加 / 编辑 / 删除
// ============================================================

interface EditForm {
  id: string | null
  content: string
  entry_type: string
  status: 'open' | 'closed' | 'dropped'
  hook_id: string
  created_at_chapter: number | null
}

const showEditor = ref(false)
const saving = ref(false)
const form = ref<EditForm>({ id: null, content: '', entry_type: 'foreshadow', status: 'open', hook_id: '', created_at_chapter: null })

const isEditing = computed(() => form.value.id !== null)
const canSave = computed(() => form.value.content.trim().length > 0 && !saving.value)

function openCreate() {
  form.value = { id: null, content: '', entry_type: 'foreshadow', status: 'open', hook_id: '', created_at_chapter: null }
  showEditor.value = true
}

function openEdit(entry: PlotLedgerEntry) {
  form.value = {
    id: entry.id,
    content: entry.content,
    entry_type: entry.entry_type || 'foreshadow',
    status: entry.status,
    hook_id: entry.hook_id || '',
    created_at_chapter: entry.created_at_chapter ?? null,
  }
  showEditor.value = true
}

function closeEditor() {
  showEditor.value = false
}

async function save() {
  if (!canSave.value) return
  saving.value = true
  try {
    const payload = {
      content: form.value.content.trim(),
      entry_type: form.value.entry_type,
      status: form.value.status,
      hook_id: form.value.hook_id.trim() || null,
      created_at_chapter: form.value.created_at_chapter,
    }
    if (isEditing.value) {
      await plotLedgerApi.update(form.value.id!, payload)
      showToast('伏笔已更新', 'success')
    } else {
      await plotLedgerApi.create(props.bookId, {
        ...payload,
        ledger_key: `manual-${Date.now()}`,
        meta: { source: 'manual' },
      })
      showToast('伏笔已添加', 'success')
    }
    closeEditor()
    await load()
  } catch (e: any) {
    showToast((isEditing.value ? '更新失败: ' : '添加失败: ') + (e.message || '未知错误'), 'error')
  } finally {
    saving.value = false
  }
}

async function removeEntry(entry: PlotLedgerEntry) {
  const ok = await showConfirm({
    title: '删除伏笔',
    message: `确定删除这条伏笔吗？\n「${entry.content.slice(0, 60)}${entry.content.length > 60 ? '…' : ''}」`,
    warning: '此操作不可恢复。若只是不再需要，建议在编辑中改为「已废弃」状态。',
  })
  if (!ok) return
  try {
    await plotLedgerApi.remove(entry.id)
    showToast('伏笔已删除', 'success')
    await load()
  } catch (e: any) {
    showToast('删除失败: ' + (e.message || '未知错误'), 'error')
  }
}
</script>

<template>
  <div class="foreshadowing-panel">
    <header class="panel-header">
      <div>
        <h1 class="page-title">伏笔账本</h1>
        <p class="page-subtitle">{{ counts.all }} 条 · 自动登记 + 手动维护</p>
      </div>
      <div class="header-actions">
        <div class="filter-tabs">
          <button
            v-for="opt in [
              { k: 'all', l: '全部' },
              { k: 'open', l: '埋设中' },
              { k: 'closed', l: '已回收' },
              { k: 'dropped', l: '已废弃' },
            ]"
            :key="opt.k"
            class="filter-btn"
            :class="{ active: filterStatus === opt.k }"
            @click="filterStatus = opt.k as any"
          >
            {{ opt.l }}（{{ (counts as any)[opt.k] }}）
          </button>
        </div>
        <button class="add-btn" @click="openCreate">
          <Icon name="plus" :size="13" />
          手动添加
        </button>
      </div>
    </header>

    <div v-if="loading" class="loading">加载中…</div>
    <div v-else-if="error" class="error">{{ error }}</div>
    <div v-else-if="filtered.length === 0" class="empty">
      <div class="empty-icon"><Icon name="link" :size="48" /></div>
      <h2>暂无伏笔</h2>
      <p>伏笔会在生成后自动登记，也可以点击右上角「手动添加」。</p>
    </div>

    <div v-else class="ledger-list">
      <article v-for="entry in filtered" :key="entry.id" class="ledger-item">
        <div class="item-header">
          <span class="item-status" :class="statusClass(entry.status)">{{ statusLabel(entry.status) }}</span>
          <span v-if="entry.entry_type" class="item-type">{{ entry.entry_type }}</span>
          <span v-if="isAutoRegistered(entry)" class="item-auto" title="由铺垫结构图自动登记">AI 登记</span>
          <span v-if="entry.created_at_chapter" class="item-chapter">埋于第 {{ entry.created_at_chapter }} 章</span>
          <span class="item-actions">
            <button class="action-btn" title="编辑" @click="openEdit(entry)">编辑</button>
            <button class="action-btn danger" title="删除" @click="removeEntry(entry)">删除</button>
          </span>
        </div>
        <p class="item-content">{{ entry.content }}</p>
        <div v-if="evidence(entry)" class="item-evidence">
          <span class="evidence-label">证据：</span>
          <span class="evidence-text">「{{ evidence(entry) }}」</span>
        </div>
      </article>
    </div>

    <!-- 添加 / 编辑弹窗 -->
    <div v-if="showEditor" class="editor-overlay" @click.self="closeEditor">
      <div class="editor-modal">
        <h3 class="editor-title">{{ isEditing ? '编辑伏笔' : '手动添加伏笔' }}</h3>

        <label class="field-label">内容 <span class="required">*</span></label>
        <textarea
          v-model="form.content"
          rows="3"
          class="field-textarea"
          placeholder="这条伏笔是什么？（例：铁皮箱三十年未被移动，唯独顶部灰尘有断点）"
        />

        <div class="field-row">
          <div class="field-col">
            <label class="field-label">类型</label>
            <select v-model="form.entry_type" class="field-select">
              <option value="foreshadow">foreshadow（伏笔）</option>
              <option value="callback">callback（呼应）</option>
              <option value="twist">twist（反转）</option>
            </select>
          </div>
          <div class="field-col">
            <label class="field-label">状态</label>
            <select v-model="form.status" class="field-select">
              <option value="open">埋设中</option>
              <option value="closed">已回收</option>
              <option value="dropped">已废弃</option>
            </select>
          </div>
        </div>

        <div class="field-row">
          <div class="field-col">
            <label class="field-label">钩子编号（可选）</label>
            <input v-model="form.hook_id" class="field-input" placeholder="如 hk-001" />
          </div>
          <div class="field-col">
            <label class="field-label">埋设于第几章（可选）</label>
            <input
              v-model.number="form.created_at_chapter"
              type="number"
              min="1"
              class="field-input"
              placeholder="章节号"
            />
          </div>
        </div>

        <div class="editor-actions">
          <button class="btn-cancel" @click="closeEditor">取消</button>
          <button class="btn-save" :disabled="!canSave" @click="save">
            {{ saving ? '保存中…' : '保存' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.foreshadowing-panel {
  height: 100%;
  overflow-y: auto;
  background: var(--bg-canvas);
  padding: 1.5rem 2rem;
}

.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  margin-bottom: 1.25rem;
  flex-wrap: wrap;
  gap: 0.75rem;
}

.page-title {
  font-family: var(--font-heading);
  font-size: 1.25rem;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0;
}

.page-subtitle {
  font-size: 0.75rem;
  color: var(--text-muted);
  margin: 0.125rem 0 0;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex-wrap: wrap;
}

.filter-tabs {
  display: flex;
  gap: 0.25rem;
  background: var(--bg-secondary);
  padding: 0.1875rem;
  border-radius: 0.375rem;
}

.filter-btn {
  padding: 0.25rem 0.625rem;
  font-size: 0.75rem;
  background: transparent;
  border: none;
  border-radius: 0.25rem;
  color: var(--text-secondary);
  cursor: pointer;
  transition: all 0.15s ease;
}

.filter-btn:hover {
  color: var(--text-primary);
}

.filter-btn.active {
  background: var(--bg-canvas);
  color: var(--accent-500);
  font-weight: 500;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.06);
}

.add-btn {
  display: flex;
  align-items: center;
  gap: 0.25rem;
  padding: 0.3125rem 0.75rem;
  font-size: 0.75rem;
  font-weight: 500;
  background: var(--accent-500);
  color: #fff;
  border: none;
  border-radius: 0.375rem;
  cursor: pointer;
  transition: background 0.15s ease;
}

.add-btn:hover {
  background: var(--accent-600, #6a5b9e);
}

.loading,
.error {
  padding: 2rem;
  text-align: center;
  color: var(--text-muted);
  font-size: 0.875rem;
}

.empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 3rem 2rem;
  text-align: center;
  color: var(--text-muted);
}

.empty-icon {
  margin-bottom: 1rem;
  opacity: 0.6;
}

.empty h2 {
  font-family: var(--font-heading);
  font-size: 1.0625rem;
  font-weight: 500;
  color: var(--text-secondary);
  margin: 0 0 0.5rem;
}

.empty p {
  font-size: 0.8125rem;
  line-height: 1.7;
  margin: 0;
}

.ledger-list {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.ledger-item {
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 0.375rem;
  padding: 0.75rem 0.875rem;
}

.item-header {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  margin-bottom: 0.375rem;
  flex-wrap: wrap;
}

.item-status {
  font-size: 0.625rem;
  font-weight: 600;
  padding: 0.125rem 0.4375rem;
  border-radius: 0.1875rem;
}

.item-status.open { background: rgba(217, 119, 6, 0.12); color: #d97706; }
.item-status.closed { background: rgba(22, 163, 74, 0.12); color: #16a34a; }
.item-status.dropped { background: var(--bg-tertiary); color: var(--text-muted); }

.item-type,
.item-chapter {
  font-size: 0.625rem;
  color: var(--text-muted);
}

.item-auto {
  font-size: 0.625rem;
  padding: 0.0625rem 0.3125rem;
  background: rgba(124, 106, 173, 0.12);
  color: var(--accent-500);
  border-radius: 0.1875rem;
}

.item-actions {
  margin-left: auto;
  display: flex;
  gap: 0.375rem;
  opacity: 0;
  transition: opacity 0.15s ease;
}

.ledger-item:hover .item-actions {
  opacity: 1;
}

.action-btn {
  font-size: 0.6875rem;
  padding: 0.125rem 0.5rem;
  background: transparent;
  border: 1px solid var(--border-color);
  border-radius: 0.25rem;
  color: var(--text-secondary);
  cursor: pointer;
  transition: all 0.15s ease;
}

.action-btn:hover {
  color: var(--accent-500);
  border-color: var(--accent-500);
}

.action-btn.danger:hover {
  color: #dc2626;
  border-color: #dc2626;
}

.item-content {
  font-size: 0.8125rem;
  line-height: 1.6;
  color: var(--text-primary);
  margin: 0;
}

.item-evidence {
  margin-top: 0.375rem;
  font-size: 0.6875rem;
  line-height: 1.5;
}

.evidence-label {
  color: var(--text-muted);
}

.evidence-text {
  color: var(--text-secondary);
  font-style: italic;
}

/* 添加 / 编辑弹窗 */
.editor-overlay {
  position: fixed;
  inset: 0;
  z-index: 50;
  background: rgba(18, 24, 38, 0.35);
  display: flex;
  align-items: center;
  justify-content: center;
}

.editor-modal {
  width: 26rem;
  max-width: calc(100vw - 2rem);
  background: var(--bg-canvas);
  border-radius: 0.625rem;
  box-shadow: 0 12px 40px rgba(18, 24, 38, 0.2);
  padding: 1.25rem;
}

.editor-title {
  font-family: var(--font-heading);
  font-size: 1rem;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0 0 0.875rem;
}

.field-label {
  display: block;
  font-size: 0.6875rem;
  font-weight: 500;
  color: var(--text-secondary);
  margin-bottom: 0.25rem;
}

.required {
  color: #dc2626;
}

.field-textarea,
.field-input,
.field-select {
  width: 100%;
  font-size: 0.8125rem;
  color: var(--text-primary);
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 0.375rem;
  padding: 0.4375rem 0.625rem;
  outline: none;
  resize: vertical;
}

.field-textarea:focus,
.field-input:focus,
.field-select:focus {
  border-color: var(--accent-500);
}

.field-row {
  display: flex;
  gap: 0.75rem;
  margin-top: 0.75rem;
}

.field-col {
  flex: 1;
  min-width: 0;
}

.editor-actions {
  display: flex;
  justify-content: flex-end;
  gap: 0.5rem;
  margin-top: 1rem;
}

.btn-cancel {
  font-size: 0.75rem;
  padding: 0.375rem 0.875rem;
  background: transparent;
  border: 1px solid var(--border-color);
  border-radius: 0.375rem;
  color: var(--text-secondary);
  cursor: pointer;
}

.btn-cancel:hover {
  color: var(--text-primary);
}

.btn-save {
  font-size: 0.75rem;
  font-weight: 500;
  padding: 0.375rem 0.875rem;
  background: var(--accent-500);
  color: #fff;
  border: none;
  border-radius: 0.375rem;
  cursor: pointer;
}

.btn-save:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
</style>
