<script setup lang="ts">
/**
 * 世界观设定面板（M5 自 components/WorldviewSettings 迁入世界页，由 WorldviewModal 承载）。
 *
 * 保留原面板全部行为：三种历史格式归一化（纯字符串 / 旧 dict / {version:1, items}）、
 * 2s 防抖自动保存、四态状态条、导入/导出 JSON、卸载兜底保存。
 * 与原版的差异：去掉 PanelContainer 外壳（头部由 ModalShell 提供），保存成功后广播
 * velluma:world-refresh（世界观文本进生成上下文，通知写作侧数据已变）。
 */
import { ref, watch, onUnmounted } from 'vue'
import { bookApi } from '../../../services/api'
import { useToast } from '../../../composables/useToast'
import { useConfirmDialog } from '../../../composables/useConfirmDialog'
import { PanelEmpty } from '../../../components/panels'
import Icon from '../../../components/Icon.vue'
import ModalShell from './ModalShell.vue'
import { WORLD_REFRESH_EVENT } from '../composables/useWorldSlice'

const props = defineProps<{ bookId: string }>()

const { showToast } = useToast()
const { show: showConfirm } = useConfirmDialog()

interface WorldviewItem {
  id: string
  title: string
  content: string
}

type SaveStatus = 'idle' | 'dirty' | 'saving' | 'saved' | 'error'

const isLoading = ref(false)
const isSaving = ref(false)
const status = ref<SaveStatus>('idle')
const errorText = ref('')
const showImportExport = ref(false)
const importExportText = ref('')

const items = ref<WorldviewItem[]>([])
let autosaveTimer: ReturnType<typeof setTimeout> | undefined
const AUTOSAVE_DELAY_MS = 2000

async function loadWorldview() {
  if (!props.bookId) {
    items.value = []
    return
  }
  isLoading.value = true
  try {
    const data = await bookApi.getWorldview(props.bookId)
    items.value = normalizeToItems(data.worldview_settings)
    status.value = 'idle'
    errorText.value = ''
  } catch (error) {
    console.error('加载世界观设定失败:', error)
    items.value = []
    status.value = 'error'
    errorText.value = '加载失败'
  } finally {
    isLoading.value = false
  }
}

function makeId() {
  return `${Date.now()}_${Math.random().toString(16).slice(2)}`
}

function normalizeToItems(worldviewSettings: any): WorldviewItem[] {
  if (!worldviewSettings) return []

  if (typeof worldviewSettings === 'string') {
    try {
      const parsed = JSON.parse(worldviewSettings)
      return normalizeToItems(parsed)
    } catch {
      return [{ id: makeId(), title: '未结构化内容', content: worldviewSettings }]
    }
  }

  if (typeof worldviewSettings === 'object') {
    if (worldviewSettings.version === 1 && Array.isArray(worldviewSettings.items)) {
      return worldviewSettings.items.map((it: any) => ({
        id: it.id || makeId(),
        title: it.title || '',
        content: it.content || '',
      }))
    }

    const entries = Object.entries(worldviewSettings)
    return entries.map(([k, v]) => ({
      id: makeId(),
      title: k,
      content: typeof v === 'string' ? v : JSON.stringify(v ?? '', null, 2),
    }))
  }

  return []
}

function toPayload() {
  return {
    version: 1,
    items: items.value.map((it) => ({
      id: it.id,
      title: it.title,
      content: it.content,
    })),
  }
}

async function saveWorldview() {
  if (!props.bookId) return
  isSaving.value = true
  status.value = 'saving'
  errorText.value = ''
  try {
    await bookApi.updateWorldview(props.bookId, {
      worldview_settings: toPayload(),
    })
    status.value = 'saved'
    window.dispatchEvent(new CustomEvent(WORLD_REFRESH_EVENT))
    setTimeout(() => {
      if (status.value === 'saved') status.value = 'idle'
    }, 1500)
  } catch (error: any) {
    console.error('保存世界观设定失败:', error)
    status.value = 'error'
    errorText.value = error?.message || '保存失败'
  } finally {
    isSaving.value = false
  }
}

function markDirty() {
  if (isLoading.value) return
  status.value = 'dirty'
  errorText.value = ''
  clearTimeout(autosaveTimer)
  autosaveTimer = setTimeout(() => {
    if (status.value !== 'dirty' || isSaving.value) return
    saveWorldview()
  }, AUTOSAVE_DELAY_MS)
}

function addItem() {
  items.value.unshift({ id: makeId(), title: '', content: '' })
  markDirty()
}

async function removeItem(id: string) {
  const ok = await showConfirm({
    title: '确认删除',
    message: '确定要删除这一条设定吗？',
  })
  if (!ok) return
  items.value = items.value.filter((it) => it.id !== id)
  markDirty()
}

function openImportExport() {
  showImportExport.value = true
  importExportText.value = JSON.stringify(toPayload(), null, 2)
}

function applyImport() {
  try {
    const parsed = JSON.parse(importExportText.value || '')
    items.value = normalizeToItems(parsed)
    showImportExport.value = false
    markDirty()
    showToast('导入成功', 'success')
  } catch {
    showToast('导入内容不是合法 JSON', 'error')
  }
}

watch(
  () => props.bookId,
  (newId) => {
    if (newId) {
      loadWorldview()
    } else {
      items.value = []
    }
  },
  { immediate: true },
)

onUnmounted(() => {
  clearTimeout(autosaveTimer)
  if (status.value === 'dirty' && !isSaving.value) {
    saveWorldview()
  }
})
</script>

<template>
  <div class="wv-panel">
    <!-- 工具行：状态条 + 动作 -->
    <div class="wv-toolbar">
      <div v-if="status !== 'idle'" class="status-bar" :class="status">
        <Icon
          :name="status === 'saving' ? 'arrow-path' : status === 'saved' ? 'check' : status === 'error' ? 'exclamation-circle' : 'information-circle'"
          :size="14"
        />
        <span>{{ status === 'dirty' ? '有未保存的更改' : status === 'saving' ? '保存中…' : status === 'saved' ? '已保存' : errorText }}</span>
      </div>
      <div v-else class="wv-toolbar-hint">自动保存（停笔 2 秒）· 进 AI 生成上下文</div>
      <div class="wv-actions">
        <button class="wv-btn" @click="openImportExport">
          <Icon name="arrow-up-tray" :size="13" />
          导入/导出
        </button>
        <button class="wv-btn primary" @click="addItem">
          <Icon name="plus" :size="13" />
          新增条目
        </button>
      </div>
    </div>

    <!-- 空状态 -->
    <PanelEmpty
      v-if="items.length === 0 && !isLoading"
      icon="book-open"
      title="暂无设定条目"
      description="世界背景、规则、历史——点击「新增条目」记下第一条"
      action-label="新增条目"
      @action="addItem"
    />

    <!-- 设定列表 -->
    <div v-else class="items-list">
      <div v-for="item in items" :key="item.id" class="item-card">
        <input
          v-model="item.title"
          type="text"
          class="item-title-input"
          placeholder="输入条目标题…"
          @input="markDirty"
        />
        <textarea
          v-model="item.content"
          rows="3"
          class="item-content-textarea"
          placeholder="填写详细设定内容…"
          @input="markDirty"
        />
        <div class="item-actions">
          <button class="action-btn danger" @click="removeItem(item.id)">
            <Icon name="trash" :size="12" />
            删除
          </button>
        </div>
      </div>
    </div>

    <div class="wv-footer">
      <button
        class="save-btn"
        :class="{ 'has-changes': status === 'dirty' }"
        :disabled="isSaving || status === 'idle' || !bookId"
        @click="saveWorldview"
      >
        <Icon :name="isSaving ? 'arrow-path' : 'check'" :size="14" />
        {{ isSaving ? '保存中…' : status === 'dirty' ? '保存更改' : '已保存' }}
      </button>
    </div>

    <!-- 导入/导出模态框 -->
    <ModalShell
      v-if="showImportExport"
      title="世界观导入 / 导出"
      width="640px"
      @close="showImportExport = false"
    >
      <textarea
        v-model="importExportText"
        rows="14"
        class="import-export-textarea"
        placeholder="在此粘贴 JSON 数据进行导入…"
      />
      <template #footer>
        <button class="wv-btn" @click="showImportExport = false">关闭</button>
        <button class="wv-btn primary" @click="applyImport">导入并应用</button>
      </template>
    </ModalShell>
  </div>
</template>

<style scoped>
.wv-panel {
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-height: 240px;
}

.wv-toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.wv-toolbar-hint {
  font-size: 11px;
  color: var(--text-muted);
}

.wv-actions {
  margin-left: auto;
  display: flex;
  gap: 6px;
}

.wv-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 5px 10px;
  font-size: 12px;
  font-family: inherit;
  color: var(--text-secondary);
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 7px;
  cursor: pointer;
  transition: all 0.15s ease;
}

.wv-btn:hover {
  color: var(--text-primary);
  border-color: var(--accent-500);
}

.wv-btn.primary {
  background: var(--accent-500);
  border-color: var(--accent-500);
  color: #fff;
}

.wv-btn.primary:hover {
  background: var(--accent-600);
}

.status-bar {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 5px 10px;
  border-radius: 8px;
  font-size: 12px;
  font-weight: 500;
}

.status-bar.dirty {
  background: #fef3c7;
  color: #d97706;
}

.status-bar.saving {
  background: #dbeafe;
  color: #2563eb;
}

.status-bar.saved {
  background: #d1fae5;
  color: #059669;
}

.status-bar.error {
  background: #fee2e2;
  color: #dc2626;
}

.items-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.item-card {
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  padding: 12px 14px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.item-title-input {
  width: 100%;
  padding: 7px 10px;
  font-size: 13px;
  font-weight: 500;
  color: var(--text-primary);
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  font-family: inherit;
  transition: all 0.2s ease;
}

.item-title-input:focus {
  outline: none;
  border-color: var(--accent-500);
}

.item-content-textarea {
  width: 100%;
  padding: 8px 10px;
  font-size: 13px;
  line-height: 1.6;
  color: var(--text-primary);
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  font-family: inherit;
  resize: vertical;
  min-height: 72px;
  transition: all 0.2s ease;
}

.item-content-textarea:focus {
  outline: none;
  border-color: var(--accent-500);
}

.item-actions {
  display: flex;
  justify-content: flex-end;
}

.action-btn {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px 8px;
  font-size: 11px;
  font-weight: 500;
  font-family: inherit;
  color: var(--text-muted);
  background: transparent;
  border: none;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.action-btn.danger:hover {
  background: #fee2e2;
  color: #dc2626;
}

.wv-footer {
  padding-top: 4px;
}

.save-btn {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 9px;
  font-size: 13px;
  font-weight: 500;
  font-family: inherit;
  color: var(--text-muted);
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.save-btn.has-changes {
  background: var(--accent-500);
  color: white;
  border-color: var(--accent-500);
}

.save-btn.has-changes:hover {
  background: var(--accent-600);
}

.save-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.import-export-textarea {
  width: 100%;
  padding: 12px;
  font-family: ui-monospace, monospace;
  font-size: 12px;
  line-height: 1.5;
  color: var(--text-primary);
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  resize: vertical;
  min-height: 300px;
}

.import-export-textarea:focus {
  outline: none;
  border-color: var(--accent-500);
}
</style>
