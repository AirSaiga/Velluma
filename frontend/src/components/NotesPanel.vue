<script setup>
import { ref, watch, onUnmounted } from 'vue'
import { PanelContainer } from './panels'
import Icon from './Icon.vue'

const props = defineProps({
  book: {
    type: Object,
    default: null
  },
  saveNotes: {
    type: Function,
    required: true
  }
})

const emit = defineEmits(['update:book', 'close'])

const localNotes = ref('')
const status = ref('idle') // idle, dirty, saving, saved, error
const errorText = ref('')

let autosaveTimer
const AUTOSAVE_DELAY_MS = 2000

watch(() => props.book, (book) => {
  if (book && !isDirty()) {
    localNotes.value = book.global_sys_prompt || ''
    status.value = 'idle'
  }
}, { immediate: true, deep: true })

function isDirty() {
  return status.value === 'dirty' || status.value === 'saving'
}

function markDirty() {
  status.value = 'dirty'
  errorText.value = ''
  clearTimeout(autosaveTimer)
  autosaveTimer = setTimeout(() => {
    if (status.value === 'dirty') {
      saveNotes()
    }
  }, AUTOSAVE_DELAY_MS)
}

async function saveNotes() {
  if (!props.book) return
  status.value = 'saving'
  errorText.value = ''
  
  try {
    await props.saveNotes(localNotes.value)
    status.value = 'saved'
    setTimeout(() => {
      if (status.value === 'saved') status.value = 'idle'
    }, 1500)
  } catch (error) {
    status.value = 'error'
    errorText.value = error?.message || '保存失败'
  }
}

function handleClose() {
  emit('close')
}

onUnmounted(() => {
  clearTimeout(autosaveTimer)
  if (status.value === 'dirty') {
    saveNotes()
  }
})

const statusConfig = {
  idle: { text: '自动保存已开启', icon: 'check-circle', type: 'default' },
  dirty: { text: '有未保存的更改', icon: 'pencil', type: 'warning' },
  saving: { text: '保存中...', icon: 'arrow-path', type: 'info' },
  saved: { text: '已保存', icon: 'check', type: 'success' },
  error: { text: errorText, icon: 'exclamation-circle', type: 'error' }
}
</script>

<template>
  <PanelContainer
    title="创作笔记"
    icon="pencil-square"
    description="记录创作灵感、想法和待办事项"
    @close="handleClose"
  >
    <div class="notes-content">
      <!-- 状态栏 -->
      <div class="status-bar" :class="statusConfig[status].type">
        <Icon :name="statusConfig[status].icon" :size="12" />
        <span>{{ statusConfig[status].text }}</span>
      </div>

      <!-- 笔记编辑区 -->
      <textarea
        v-model="localNotes"
        class="notes-textarea"
        placeholder="在此记录您的创作笔记...

可以记录：
- 创作灵感
- 待办事项
- 情节构思
- 角色设定想法
- 其他备注"
        @input="markDirty"
      />

      <!-- 快捷提示 -->
      <div class="notes-tips">
        <h4>💡 提示</h4>
        <ul>
          <li>笔记会自动保存</li>
          <li>支持多行文本</li>
          <li>可在全局提示词中使用</li>
        </ul>
      </div>
    </div>

    <template #footer>
      <button 
        class="save-btn" 
        :class="{ 'has-changes': status === 'dirty' }"
        :disabled="status === 'saving' || status === 'idle'"
        @click="saveNotes"
      >
        <Icon :name="status === 'saving' ? 'arrow-path' : 'check'" :size="14" />
        {{ status === 'saving' ? '保存中...' : status === 'dirty' ? '立即保存' : '已保存' }}
      </button>
    </template>
  </PanelContainer>
</template>

<style scoped>
.notes-content {
  display: flex;
  flex-direction: column;
  gap: 16px;
  height: 100%;
  min-height: 0;
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

.status-bar.default {
  background: #f3f4f6;
  color: #6b7280;
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

.notes-textarea {
  flex: 1;
  width: 100%;
  padding: 14px;
  font-size: 14px;
  line-height: 1.7;
  color: var(--text-primary);
  background: var(--bg-panel);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  resize: none;
  transition: all 0.2s ease;
}

.notes-textarea:focus {
  outline: none;
  border-color: var(--accent-500);
  background: var(--bg-primary);
  box-shadow: 0 0 0 3px rgba(124, 106, 173, 0.1);
}

.notes-textarea::placeholder {
  color: var(--text-muted);
}

.notes-tips {
  padding: 14px;
  background: linear-gradient(135deg, rgba(124, 106, 173, 0.05), rgba(124, 106, 173, 0.02));
  border: 1px solid rgba(124, 106, 173, 0.1);
  border-radius: 12px;
}

.notes-tips h4 {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-secondary);
  margin-bottom: 8px;
}

.notes-tips ul {
  list-style: none;
  padding: 0;
  margin: 0;
}

.notes-tips li {
  font-size: 12px;
  color: var(--text-muted);
  padding: 3px 0;
  padding-left: 14px;
  position: relative;
}

.notes-tips li::before {
  content: '•';
  position: absolute;
  left: 0;
  color: var(--accent-500);
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
