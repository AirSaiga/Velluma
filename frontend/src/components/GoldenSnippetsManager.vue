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

const emit = defineEmits(['update-snippets', 'update-blacklist'])

const activeTab = ref('golden') // 'golden' | 'blacklist'
const isLoading = ref(false)
const isSaving = ref(false)
const status = ref('idle')
const errorText = ref('')

const goldenSnippets = ref([])
const styleBlacklist = ref([])

let autosaveTimer
const AUTOSAVE_DELAY_MS = 2000

async function loadData() {
  if (!props.bookId) return
  isLoading.value = true
  try {
    const [goldenData, blacklistData] = await Promise.all([
      bookApi.getGoldenSnippets(props.bookId),
      bookApi.getStyleBlacklist(props.bookId)
    ])
    goldenSnippets.value = (goldenData.golden_snippets || []).map((text, index) => ({
      id: `golden_${index}_${Date.now()}`,
      text: text || ''
    }))
    styleBlacklist.value = (blacklistData.style_blacklist || []).map((text, index) => ({
      id: `blacklist_${index}_${Date.now()}`,
      text: text || ''
    }))
    status.value = 'idle'
    errorText.value = ''
  } catch (error) {
    console.error('加载数据失败:', error)
    status.value = 'error'
    errorText.value = '加载失败'
  } finally {
    isLoading.value = false
  }
}

function makeId(prefix) {
  return `${prefix}_${Date.now()}_${Math.random().toString(16).slice(2)}`
}

async function saveData() {
  if (!props.bookId) return
  isSaving.value = true
  status.value = 'saving'
  errorText.value = ''
  try {
    const goldenData = goldenSnippets.value.map(item => item.text).filter(text => text.trim())
    const blacklistData = styleBlacklist.value.map(item => item.text).filter(text => text.trim())
    
    await Promise.all([
      bookApi.updateGoldenSnippets(props.bookId, goldenData),
      bookApi.updateStyleBlacklist(props.bookId, blacklistData)
    ])
    
    emit('update-snippets', goldenData)
    emit('update-blacklist', blacklistData)
    status.value = 'saved'
    setTimeout(() => {
      if (status.value === 'saved') status.value = 'idle'
    }, 1500)
  } catch (error) {
    console.error('保存失败:', error)
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
    saveData()
  }, AUTOSAVE_DELAY_MS)
}

function addGoldenSnippet() {
  goldenSnippets.value.unshift({ id: makeId('golden'), text: '' })
  markDirty()
}

function addBlacklistItem() {
  styleBlacklist.value.unshift({ id: makeId('blacklist'), text: '' })
  markDirty()
}

async function removeGoldenSnippet(id) {
  const ok = await showConfirm({
    title: '确认删除',
    message: '确定要删除这个黄金锚点片段吗？'
  })
  if (!ok) return
  goldenSnippets.value = goldenSnippets.value.filter(item => item.id !== id)
  markDirty()
}

async function removeBlacklistItem(id) {
  const ok = await showConfirm({
    title: '确认删除',
    message: '确定要删除这个黑名单条目吗？'
  })
  if (!ok) return
  styleBlacklist.value = styleBlacklist.value.filter(item => item.id !== id)
  markDirty()
}

function updateGoldenText(id, newText) {
  const item = goldenSnippets.value.find(item => item.id === id)
  if (item) {
    item.text = newText
    markDirty()
  }
}

function updateBlacklistText(id, newText) {
  const item = styleBlacklist.value.find(item => item.id === id)
  if (item) {
    item.text = newText
    markDirty()
  }
}

const statusText = {
  idle: '',
  dirty: '有未保存的更改',
  saving: '保存中...',
  saved: '已保存',
  error: ''
}

watch(() => props.bookId, (newId) => {
  if (newId) {
    loadData()
  }
}, { immediate: true })

onUnmounted(() => {
  clearTimeout(autosaveTimer)
  if (status.value === 'dirty' && !isSaving.value) {
    saveData()
  }
})
</script>

<template>
  <div class="snippets-manager">
    <!-- Tab Switcher -->
    <div class="flex items-center gap-1 mb-3 bg-[var(--bg-panel)] p-1 rounded-lg">
      <button
        @click="activeTab = 'golden'"
        :class="[
          'flex-1 px-3 py-1.5 text-xs font-medium rounded-md transition-colors',
          activeTab === 'golden'
            ? 'bg-[var(--accent-500)] text-white'
            : 'text-[var(--text-muted)] hover:text-[var(--text-primary)]'
        ]"
      >
        黄金锚点
      </button>
      <button
        @click="activeTab = 'blacklist'"
        :class="[
          'flex-1 px-3 py-1.5 text-xs font-medium rounded-md transition-colors',
          activeTab === 'blacklist'
            ? 'bg-[var(--accent-500)] text-white'
            : 'text-[var(--text-muted)] hover:text-[var(--text-primary)]'
        ]"
      >
        风格黑名单
      </button>
    </div>

    <!-- Header -->
    <div class="flex items-center justify-between mb-2">
      <div class="flex items-center gap-2">
        <label class="block text-xs font-medium text-[var(--text-primary)]">
          {{ activeTab === 'golden' ? '黄金锚点' : '风格黑名单' }}
        </label>
        <span
          v-if="status !== 'idle' && status !== 'error'"
          :class="[
            'text-[10px] px-1.5 py-0.5 rounded-full',
            status === 'dirty' ? 'bg-amber-500/10 text-amber-500' : '',
            status === 'saving' ? 'bg-blue-500/10 text-blue-500' : '',
            status === 'saved' ? 'bg-green-500/10 text-green-500' : ''
          ]"
        >
          {{ statusText[status] }}
        </span>
        <span
          v-if="status === 'error'"
          class="text-[10px] px-1.5 py-0.5 rounded-full bg-rose-500/10 text-rose-500"
        >
          {{ errorText }}
        </span>
      </div>
      <div class="flex items-center gap-1">
        <button
          @click="activeTab === 'golden' ? addGoldenSnippet() : addBlacklistItem()"
          class="px-2 py-0.5 text-[10px] bg-white hover:bg-[var(--bg-panel)] text-[var(--text-muted)] hover:text-[var(--text-primary)] rounded-lg transition-colors"
          :disabled="isLoading"
        >
          +新增
        </button>
        <button
          @click="saveData"
          :disabled="isSaving"
          class="px-2 py-0.5 text-[10px] bg-[var(--accent-500)] disabled:bg-[var(--bg-panel)] text-white rounded-lg transition-colors"
        >
          保存
        </button>
      </div>
    </div>

    <!-- Description -->
    <p class="text-[10px] text-[var(--text-muted)] mb-2">
      {{ activeTab === 'golden' 
        ? '添加文本片段作为AI生成的风格参考，AI会学习这些片段的写作风格' 
        : '添加需要避免的表达方式或禁用词，AI生成时会主动规避' }}
    </p>

    <!-- Loading -->
    <div v-if="isLoading" class="text-[10px] text-[var(--text-muted)] mt-1">加载中...</div>

    <!-- Golden Snippets List -->
    <div v-else-if="activeTab === 'golden'" class="space-y-2">
      <div v-if="goldenSnippets.length === 0" class="p-3 bg-[var(--bg-panel)] rounded-xl text-[10px] text-[var(--text-muted)]">
        暂无黄金锚点，点击"+新增"添加参考文本片段
      </div>

      <div
        v-for="item in goldenSnippets"
        :key="item.id"
        class="p-2 bg-[var(--bg-panel)] rounded-xl group"
      >
        <div class="flex items-start gap-2">
          <div class="flex-1">
            <textarea
              :value="item.text"
              @input="updateGoldenText(item.id, $event.target.value)"
              rows="3"
              class="w-full px-2 py-1.5 bg-white rounded-lg text-xs text-[var(--text-primary)] focus:outline-none ring-1 ring-transparent focus:ring-[var(--accent-500)] resize-none"
              placeholder="输入文本片段..."
            />
          </div>
          <button
            class="p-1 text-[var(--text-muted)] hover:text-rose-400 hover:bg-rose-500/10 rounded transition-colors opacity-0 group-hover:opacity-100"
            @click="removeGoldenSnippet(item.id)"
            title="删除"
          >
            <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/>
            </svg>
          </button>
        </div>
      </div>
    </div>

    <!-- Blacklist List -->
    <div v-else class="space-y-2">
      <div v-if="styleBlacklist.length === 0" class="p-3 bg-[var(--bg-panel)] rounded-xl text-[10px] text-[var(--text-muted)]">
        暂无黑名单条目，点击"+新增"添加需要避免的表达方式
      </div>

      <div
        v-for="item in styleBlacklist"
        :key="item.id"
        class="p-2 bg-[var(--bg-panel)] rounded-xl group"
      >
        <div class="flex items-center gap-2">
          <div class="flex-1">
            <input
              :value="item.text"
              @input="updateBlacklistText(item.id, $event.target.value)"
              type="text"
              class="w-full px-2 py-1.5 bg-white rounded-lg text-xs text-[var(--text-primary)] focus:outline-none ring-1 ring-transparent focus:ring-[var(--accent-500)]"
              placeholder="输入需要避免的表达方式..."
            />
          </div>
          <button
            class="p-1 text-[var(--text-muted)] hover:text-rose-400 hover:bg-rose-500/10 rounded transition-colors opacity-0 group-hover:opacity-100"
            @click="removeBlacklistItem(item.id)"
            title="删除"
          >
            <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/>
            </svg>
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
