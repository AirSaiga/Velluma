<script setup>
import { ref, watch, onUnmounted } from 'vue'
import { bookApi } from '../services/api'
import { useToast } from '../composables/useToast'
import { useConfirmDialog } from '../composables/useConfirmDialog'

const { showToast } = useToast()
const { show: showConfirm } = useConfirmDialog()

const props = defineProps({
  bookId: {
    type: String,
    required: true
  }
})

const emit = defineEmits(['update-worldview'])

const isLoading = ref(false)
const isSaving = ref(false)
const status = ref('idle')
const errorText = ref('')
const showImportExport = ref(false)
const importExportText = ref('')

const items = ref([])
let autosaveTimer

async function loadWorldview() {
  if (!props.bookId) return
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
      return [{ id: makeId(), title: '未结构化内容', content: worldviewSettings, collapsed: false }]
    }
  }

  if (typeof worldviewSettings === 'object') {
    if (worldviewSettings.version === 1 && Array.isArray(worldviewSettings.items)) {
      return worldviewSettings.items.map((it) => ({
        id: it.id || makeId(),
        title: it.title || '',
        content: it.content || '',
        collapsed: !!it.collapsed
      }))
    }

    const entries = Object.entries(worldviewSettings)
    return entries.map(([k, v]) => ({
      id: makeId(),
      title: k,
      content: typeof v === 'string' ? v : JSON.stringify(v ?? '', null, 2),
      collapsed: false
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
      collapsed: !!it.collapsed
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
  }, 1200)
}

function addItem() {
  items.value.unshift({ id: makeId(), title: '', content: '', collapsed: false })
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

function toggleItemCollapse(id) {
  const idx = items.value.findIndex((it) => it.id === id)
  if (idx === -1) return
  items.value[idx].collapsed = !items.value[idx].collapsed
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
  } catch {
    showToast('导入内容不是合法 JSON', 'error')
  }
}

watch(() => props.bookId, (newId) => {
  if (newId) {
    loadWorldview()
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
  <div class="worldview-editor">
    <div class="flex items-center justify-between mb-2">
      <label class="block text-xs font-medium text-[var(--text-primary)]">
        世界观设定
      </label>
      <div class="flex items-center gap-1">
        <button
          @click="openImportExport"
          class="px-2 py-0.5 text-[10px] bg-white hover:bg-[var(--bg-panel)] text-[var(--text-muted)] hover:text-[var(--text-primary)] rounded-lg transition-colors"
          :disabled="isLoading"
        >
          导入/导出
        </button>
        <button
          @click="addItem"
          class="px-2 py-0.5 text-[10px] bg-white hover:bg-[var(--bg-panel)] text-[var(--text-muted)] hover:text-[var(--text-primary)] rounded-lg transition-colors"
          :disabled="isLoading"
        >
          +新增
        </button>
        <button
          @click="saveWorldview"
          :disabled="isSaving"
          class="px-2 py-0.5 text-[10px] bg-[var(--accent-500)] disabled:bg-[var(--bg-panel)] text-white rounded-lg transition-colors"
        >
          保存
        </button>
      </div>
    </div>
    <p class="text-[10px] text-[var(--text-muted)] mb-2">
      定义世界背景、规则、历史等设定
    </p>
    <div v-if="isLoading" class="text-[10px] text-[var(--text-muted)] mt-1">加载中...</div>

    <div v-else class="space-y-2">
      <div v-if="items.length === 0" class="p-2 bg-[var(--bg-panel)] rounded-xl text-[10px] text-[var(--text-muted)]">
        暂无条目，点击"+新增"开始添加
      </div>

      <div
        v-for="it in items"
        :key="it.id"
        class="p-2 bg-[var(--bg-panel)] rounded-xl"
      >
        <div class="flex items-center gap-1.5">
          <button
            class="p-0.5 text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--hover-bg)] rounded transition-colors"
            @click="toggleItemCollapse(it.id)"
            :title="it.collapsed ? '展开' : '收起'"
          >
            <svg v-if="it.collapsed" class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7" />
            </svg>
            <svg v-else class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
            </svg>
          </button>

          <input
            v-model="it.title"
            @input="markDirty"
            type="text"
            class="flex-1 px-2 py-1 bg-white rounded-lg text-xs text-[var(--text-primary)] focus:outline-none ring-1 ring-transparent focus:ring-[var(--accent-500)]"
            placeholder="条目标题"
          />

          <button
            class="p-0.5 text-[var(--text-muted)] hover:text-rose-400 hover:bg-rose-500/10 rounded transition-colors"
            @click="removeItem(it.id)"
            title="删除"
          >
            <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/>
            </svg>
          </button>
        </div>

        <div v-show="!it.collapsed" class="mt-1.5">
          <textarea
            v-model="it.content"
            @input="markDirty"
            rows="4"
            class="w-full px-2 py-1.5 bg-white rounded-lg text-xs text-[var(--text-primary)] focus:outline-none ring-1 ring-transparent focus:ring-[var(--accent-500)] resize-none"
            placeholder="填写详细设定..."
          />
        </div>
      </div>
    </div>

    <div v-if="showImportExport" class="fixed inset-0 bg-black/50 flex items-center justify-center z-50" @click.self="showImportExport = false">
      <div class="bg-[var(--bg-secondary)] rounded-2xl p-6 w-full max-w-2xl mx-4 max-h-[90vh] overflow-y-auto">
        <h3 class="text-lg font-semibold text-[var(--text-primary)] mb-4">世界观导入 / 导出</h3>
        <textarea
          v-model="importExportText"
          rows="14"
          class="w-full px-3 py-2 bg-[var(--bg-panel)] rounded-xl text-[var(--text-primary)] text-sm focus:outline-none ring-1 ring-transparent focus:ring-[var(--accent-500)] resize-none font-mono"
        />
        <div class="flex justify-end gap-3 mt-4">
          <button
            @click="showImportExport = false"
            class="px-4 py-2 text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors"
          >
            关闭
          </button>
          <button
            @click="applyImport"
            class="px-4 py-2 bg-[var(--accent-500)] text-white rounded-full transition-colors"
          >
            导入并应用
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
