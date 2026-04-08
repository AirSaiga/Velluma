<script setup>
import { ref, watch, onUnmounted, computed } from 'vue'
import { bookApi } from '../services/api'
import { useToast } from '../composables/useToast'
import { useConfirmDialog } from '../composables/useConfirmDialog'
import { PanelContainer, PanelSection, PanelCard, PanelEmpty, PanelFormField } from './panels'
import Icon from './Icon.vue'

const { showToast } = useToast()
const { show: showConfirm } = useConfirmDialog()

const props = defineProps({
  bookId: {
    type: String,
    required: true
  }
})

const emit = defineEmits(['update-snippets', 'update-blacklist', 'close'])

const activeTab = ref('golden')
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

function addItem() {
  if (activeTab.value === 'golden') {
    goldenSnippets.value.unshift({ id: makeId('golden'), text: '' })
  } else {
    styleBlacklist.value.unshift({ id: makeId('blacklist'), text: '' })
  }
  markDirty()
}

async function removeItem(id) {
  const ok = await showConfirm({
    title: '确认删除',
    message: activeTab.value === 'golden' 
      ? '确定要删除这个黄金锚点片段吗？'
      : '确定要删除这个黑名单条目吗？'
  })
  if (!ok) return
  
  if (activeTab.value === 'golden') {
    goldenSnippets.value = goldenSnippets.value.filter(item => item.id !== id)
  } else {
    styleBlacklist.value = styleBlacklist.value.filter(item => item.id !== id)
  }
  markDirty()
}

function updateItemText(id, newText) {
  if (activeTab.value === 'golden') {
    const item = goldenSnippets.value.find(item => item.id === id)
    if (item) {
      item.text = newText
      markDirty()
    }
  } else {
    const item = styleBlacklist.value.find(item => item.id === id)
    if (item) {
      item.text = newText
      markDirty()
    }
  }
}

function handleClose() {
  emit('close')
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

const tabs = [
  { key: 'golden', label: '黄金锚点', icon: 'star', description: '添加文本片段作为AI生成的风格参考' },
  { key: 'blacklist', label: '风格黑名单', icon: 'no-symbol', description: '添加需要避免的表达方式或禁用词' }
]

const currentTab = computed(() => tabs.find(t => t.key === activeTab.value))
const currentItems = computed(() => activeTab.value === 'golden' ? goldenSnippets.value : styleBlacklist.value)

const statusConfig = {
  idle: { text: '', type: 'default' },
  dirty: { text: '有未保存的更改', type: 'warning' },
  saving: { text: '保存中...', type: 'info' },
  saved: { text: '已保存', type: 'success' },
  error: { text: errorText, type: 'error' }
}
</script>

<template>
  <PanelContainer
    :title="currentTab.label"
    :icon="currentTab.icon"
    :description="currentTab.description"
    :loading="isLoading"
    :header-actions="[
      { icon: 'plus', label: '新增条目', onClick: addItem, variant: 'primary' }
    ]"
    @close="handleClose"
  >
    <div class="snippets-content">
      <!-- Tab 切换 -->
      <div class="tab-switcher">
        <button
          v-for="tab in tabs"
          :key="tab.key"
          class="tab-btn"
          :class="{ active: activeTab === tab.key }"
          @click="activeTab = tab.key"
        >
          <Icon :name="tab.icon" :size="14" />
          <span>{{ tab.label }}</span>
        </button>
      </div>

      <!-- 状态提示 -->
      <div v-if="statusConfig[status].type !== 'default'" class="status-bar" :class="statusConfig[status].type">
        <Icon 
          :name="status === 'saving' ? 'arrow-path' : status === 'saved' ? 'check' : status === 'error' ? 'exclamation-circle' : 'information-circle'" 
          :size="14" 
        />
        <span>{{ statusConfig[status].text }}</span>
      </div>

      <!-- 内容列表 -->
      <div class="items-list">
        <PanelCard
          v-for="(item, index) in currentItems"
          :key="item.id"
          :title="`条目 ${currentItems.length - index}`"
          :highlight="item.text ? 'none' : 'weak'"
          :actions="[
            { icon: 'trash', label: '删除', onClick: () => removeItem(item.id), variant: 'danger' }
          ]"
        >
          <template #default>
            <textarea
              :value="item.text"
              @input="updateItemText(item.id, $event.target.value)"
              :rows="activeTab === 'golden' ? 4 : 2"
              class="item-textarea"
              :placeholder="activeTab === 'golden' ? '输入文本片段，AI会学习这些片段的写作风格...' : '输入需要避免的表达方式或禁用词...'"
            />
          </template>
        </PanelCard>

        <PanelEmpty
          v-if="currentItems.length === 0"
          :icon="currentTab.icon"
          :title="`暂无${currentTab.label}`"
          :description="`点击「新增条目」按钮添加第一个${currentTab.label}`"
          action-label="新增条目"
          @action="addItem"
        />
      </div>
    </div>

    <template #footer>
      <button 
        class="save-btn" 
        :class="{ 'has-changes': status === 'dirty' }"
        :disabled="isSaving || status === 'idle'"
        @click="saveData"
      >
        <Icon :name="isSaving ? 'arrow-path' : 'check'" :size="14" />
        {{ isSaving ? '保存中...' : status === 'dirty' ? '保存更改' : '已保存' }}
      </button>
    </template>
  </PanelContainer>
</template>

<style scoped>
.snippets-content {
  display: flex;
  flex-direction: column;
  gap: 16px;
  height: 100%;
  min-height: 0;
}

.tab-switcher {
  display: flex;
  gap: 4px;
  padding: 4px;
  background: var(--bg-panel);
  border-radius: 10px;
}

.tab-btn {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 8px 12px;
  font-size: 12px;
  font-weight: 500;
  color: var(--text-muted);
  background: transparent;
  border: none;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.tab-btn:hover {
  color: var(--text-primary);
  background: var(--hover-bg);
}

.tab-btn.active {
  color: white;
  background: var(--accent-500);
}

.status-bar {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 12px;
  border-radius: 8px;
  font-size: 12px;
  font-weight: 500;
}

.status-bar.warning {
  background: #fef3c7;
  color: #d97706;
}

.status-bar.info {
  background: #dbeafe;
  color: #2563eb;
}

.status-bar.success {
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
  flex: 1;
  overflow-y: auto;
}

.item-textarea {
  width: 100%;
  padding: 10px 12px;
  font-size: 13px;
  line-height: 1.6;
  color: var(--text-primary);
  background: var(--bg-panel);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  resize: vertical;
  min-height: 80px;
  transition: all 0.2s ease;
}

.item-textarea:focus {
  outline: none;
  border-color: var(--accent-500);
  background: var(--bg-primary);
  box-shadow: 0 0 0 3px rgba(124, 106, 173, 0.1);
}

.item-textarea::placeholder {
  color: var(--text-muted);
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
</style>
