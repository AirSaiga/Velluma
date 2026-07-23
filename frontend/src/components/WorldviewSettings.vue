<script setup>
import { ref, watch, onUnmounted } from 'vue'
import { bookApi } from '../services/api'
import { useToast } from '../composables/useToast'
import { useConfirmDialog } from '../composables/useConfirmDialog'
import { PanelContainer, PanelCard, PanelEmpty } from './panels'
import Icon from './Icon.vue'

const { showToast } = useToast()
const { show: showConfirm } = useConfirmDialog()

const props = defineProps({
  bookId: {
    type: String,
    default: null
  },
  closable: {
    type: Boolean,
    default: true
  }
})

const emit = defineEmits(['update-worldview', 'close'])

const isLoading = ref(false)
const isSaving = ref(false)
const status = ref('idle')
const errorText = ref('')
const showImportExport = ref(false)
const importExportText = ref('')

const items = ref([])
let autosaveTimer
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

function normalizeToItems(worldviewSettings) {
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
      return worldviewSettings.items.map((it) => ({
        id: it.id || makeId(),
        title: it.title || '',
        content: it.content || ''
      }))
    }

    const entries = Object.entries(worldviewSettings)
    return entries.map(([k, v]) => ({
      id: makeId(),
      title: k,
      content: typeof v === 'string' ? v : JSON.stringify(v ?? '', null, 2)
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
      content: it.content
    }))
  }
}

async function saveWorldview() {
  if (!props.bookId) return
  isSaving.value = true
  status.value = 'saving'
  errorText.value = ''
  try {
    const data = await bookApi.updateWorldview(props.bookId, {
      worldview_settings: toPayload()
    })
    emit('update-worldview', data)
    status.value = 'saved'
    setTimeout(() => {
      if (status.value === 'saved') status.value = 'idle'
    }, 1500)
  } catch (error) {
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

async function removeItem(id) {
  const ok = await showConfirm({
    title: '确认删除',
    message: '确定要删除这一条设定吗？'
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

function handleClose() {
  emit('close')
}

watch(() => props.bookId, (newId) => {
  if (newId) {
    loadWorldview()
  } else {
    items.value = []
  }
}, { immediate: true })

onUnmounted(() => {
  clearTimeout(autosaveTimer)
  if (status.value === 'dirty' && !isSaving.value) {
    saveWorldview()
  }
})
</script>

<template>
  <PanelContainer
    title="世界观设定"
    icon="book-open"
    description="定义世界背景、规则、历史等设定"
    :loading="isLoading"
    :header-actions="[
      { icon: 'arrow-up-tray', label: '导入/导出', onClick: openImportExport },
      { icon: 'plus', label: '新增', onClick: addItem, variant: 'primary' }
    ]"
    :closable="closable"
    @close="handleClose"
  >
    <!-- 状态提示 -->
    <div v-if="status !== 'idle'" class="status-bar" :class="status">
      <Icon 
        :name="status === 'saving' ? 'arrow-path' : status === 'saved' ? 'check' : status === 'error' ? 'exclamation-circle' : 'information-circle'" 
        :size="14" 
      />
      <span>{{ status === 'dirty' ? '有未保存的更改' : status === 'saving' ? '保存中...' : status === 'saved' ? '已保存' : errorText }}</span>
    </div>

    <!-- 空状态 -->
    <PanelEmpty
      v-if="items.length === 0 && !isLoading"
      icon="book-open"
      :title="bookId ? '暂无设定条目' : '请先选择书籍'"
      :description="bookId ? '点击「新增」按钮开始添加世界观设定' : '选择书籍后即可编辑世界观设定'"
      :action-label="bookId ? '新增条目' : undefined"
      @action="addItem"
    />

    <!-- 设定列表 -->
    <div v-else class="items-list">
      <div
        v-for="item in items"
        :key="item.id"
        class="item-card"
      >
        <input
          v-model="item.title"
          type="text"
          class="item-title-input"
          placeholder="输入条目标题..."
          @input="markDirty"
        />
        <textarea
          v-model="item.content"
          rows="3"
          class="item-content-textarea"
          placeholder="填写详细设定内容..."
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

    <template #footer>
      <button 
        class="save-btn" 
        :class="{ 'has-changes': status === 'dirty' }"
        :disabled="isSaving || status === 'idle' || !bookId"
        @click="saveWorldview"
      >
        <Icon :name="isSaving ? 'arrow-path' : 'check'" :size="14" />
        {{ isSaving ? '保存中...' : status === 'dirty' ? '保存更改' : '已保存' }}
      </button>
    </template>
  </PanelContainer>

  <!-- 导入/导出模态框 -->
  <Transition name="modal">
    <div v-if="showImportExport" class="modal-overlay" @click.self="showImportExport = false">
      <div class="modal-content">
        <div class="drawer-header">
          <h3>世界观导入 / 导出</h3>
          <button class="close-btn" @click="showImportExport = false">
            <Icon name="close" :size="18" />
          </button>
        </div>
        
        <div class="modal-body">
          <textarea
            v-model="importExportText"
            rows="14"
            class="import-export-textarea"
            placeholder="在此粘贴 JSON 数据进行导入..."
          />
        </div>
        
        <div class="drawer-footer">
          <button class="btn-secondary" @click="showImportExport = false">关闭</button>
          <button class="btn-primary" @click="applyImport">导入并应用</button>
        </div>
      </div>
    </div>
  </Transition>
</template>

<style scoped>
.status-bar {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 12px;
  border-radius: 8px;
  font-size: 12px;
  font-weight: 500;
  margin-bottom: 12px;
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
  overflow-y: auto;
  flex: 1;
  min-height: 0;
}

.item-card {
  background: var(--bg-panel);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  padding: 14px 16px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.item-title-input {
  width: 100%;
  padding: 8px 12px;
  font-size: 13px;
  font-weight: 500;
  color: var(--text-primary);
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  transition: all 0.2s ease;
}

.item-title-input:focus {
  outline: none;
  border-color: var(--accent-500);
  box-shadow: 0 0 0 3px rgba(124, 106, 173, 0.1);
}

.item-content-textarea {
  width: 100%;
  padding: 10px 12px;
  font-size: 13px;
  line-height: 1.6;
  color: var(--text-primary);
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  resize: vertical;
  min-height: 80px;
  transition: all 0.2s ease;
}

.item-content-textarea:focus {
  outline: none;
  border-color: var(--accent-500);
  box-shadow: 0 0 0 3px rgba(124, 106, 173, 0.1);
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
  color: var(--text-muted);
  background: transparent;
  border: none;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.action-btn:hover {
  background: var(--hover-bg);
  color: var(--text-primary);
}

.action-btn.danger:hover {
  background: #fee2e2;
  color: #dc2626;
}

.save-btn {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 10px;
  font-size: 13px;
  font-weight: 500;
  color: var(--text-muted);
  background: var(--bg-panel);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.save-btn:hover:not(:disabled) {
  background: var(--hover-bg);
  color: var(--text-primary);
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

/* 模态框样式 */
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.4);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 200;
  padding: 20px;
}

.modal-content {
  background: var(--bg-primary);
  border-radius: 16px;
  width: 100%;
  max-width: 640px;
  max-height: 90vh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.2);
}

.drawer-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px;
  border-bottom: 1px solid var(--border-color);
}

.drawer-header h3 {
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
}

.close-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border-radius: 8px;
  border: none;
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  transition: all 0.2s ease;
}

.close-btn:hover {
  background: var(--bg-panel);
  color: var(--text-primary);
}

.modal-body {
  flex: 1;
  overflow-y: auto;
  padding: 20px;
}

.import-export-textarea {
  width: 100%;
  padding: 12px;
  font-family: 'Menlo', 'Monaco', 'Courier New', monospace;
  font-size: 12px;
  line-height: 1.5;
  color: var(--text-primary);
  background: var(--bg-panel);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  resize: vertical;
  min-height: 300px;
}

.import-export-textarea:focus {
  outline: none;
  border-color: var(--accent-500);
  box-shadow: 0 0 0 3px rgba(124, 106, 173, 0.1);
}

.drawer-footer {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  padding: 16px 20px;
  border-top: 1px solid var(--border-color);
  background: var(--bg-secondary);
}

.btn-primary {
  padding: 10px 20px;
  font-size: 13px;
  font-weight: 500;
  color: white;
  background: var(--accent-500);
  border: none;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.btn-primary:hover {
  background: var(--accent-600);
}

.btn-secondary {
  padding: 10px 20px;
  font-size: 13px;
  font-weight: 500;
  color: var(--text-secondary);
  background: var(--bg-panel);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.btn-secondary:hover {
  background: var(--hover-bg);
  color: var(--text-primary);
}

/* 过渡动画 */
.modal-enter-active,
.modal-leave-active {
  transition: all 0.25s ease;
}

.modal-enter-from,
.modal-leave-to {
  opacity: 0;
}

.modal-enter-from .modal-content,
.modal-leave-to .modal-content {
  transform: scale(0.95) translateY(10px);
  opacity: 0;
}

.modal-content {
  transition: all 0.25s ease;
}
</style>
