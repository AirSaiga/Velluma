<script setup>
import { ref, watch } from 'vue'
import WorldviewSettings from './WorldviewSettings.vue'

const props = defineProps({
  bookConfig: {
    type: Object,
    default: () => ({ global_sys_prompt: '', id: null, title: '', genre: '' })
  },
  initialTab: {
    type: String,
    default: 'prompt'
  },
  updateBook: {
    type: Function,
    required: true
  }
})

const emit = defineEmits(['tab-change'])

const activeTab = ref(props.initialTab || 'prompt')

const localGlobalPrompt = ref(props.bookConfig.global_sys_prompt || '')
const promptStatus = ref('idle')
const promptError = ref('')

watch(() => props.bookConfig, (newVal) => {
  localGlobalPrompt.value = newVal.global_sys_prompt || ''
  promptStatus.value = 'idle'
  promptError.value = ''
}, { immediate: true })

watch(() => props.initialTab, (val) => {
  if (!val) return
  activeTab.value = val
})

watch(activeTab, (val) => {
  emit('tab-change', val)
})

watch(localGlobalPrompt, () => {
  if (!props.bookConfig?.id) return
  promptStatus.value = 'dirty'
  promptError.value = ''
})

async function saveGlobalPrompt() {
  if (!props.bookConfig?.id) return
  promptStatus.value = 'saving'
  promptError.value = ''
  try {
    await props.updateBook({ global_sys_prompt: localGlobalPrompt.value })
    promptStatus.value = 'saved'
    setTimeout(() => {
      if (promptStatus.value === 'saved') {
        promptStatus.value = 'idle'
      }
    }, 1500)
  } catch (e) {
    promptStatus.value = 'error'
    promptError.value = e?.message || '保存失败'
  }
}
</script>

<template>
  <div class="h-full flex flex-col bg-[var(--bg-secondary)] border-l border-[var(--border-color)]">
    <div class="p-4 border-b border-[var(--border-color)]">
      <h2 class="text-lg font-semibold text-[var(--text-primary)]">书籍配置</h2>
      <div class="mt-3 flex items-center gap-2">
        <button
          class="px-3 py-1.5 text-sm rounded-lg border transition-colors"
          :class="activeTab === 'prompt' ? 'bg-[var(--bg-tertiary)] border-[var(--text-muted)] text-[var(--text-primary)]' : 'bg-transparent border-[var(--border-color)] text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--hover-bg)]'"
          @click="activeTab = 'prompt'"
        >
          提示词
        </button>
        <button
          class="px-3 py-1.5 text-sm rounded-lg border transition-colors"
          :class="activeTab === 'worldview' ? 'bg-[var(--bg-tertiary)] border-[var(--text-muted)] text-[var(--text-primary)]' : 'bg-transparent border-[var(--border-color)] text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--hover-bg)]'"
          @click="activeTab = 'worldview'"
          :disabled="!bookConfig.id"
        >
          世界观
        </button>
        <button
          class="px-3 py-1.5 text-sm rounded-lg border transition-colors"
          :class="activeTab === 'book' ? 'bg-[var(--bg-tertiary)] border-[var(--text-muted)] text-[var(--text-primary)]' : 'bg-transparent border-[var(--border-color)] text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--hover-bg)]'"
          @click="activeTab = 'book'"
          :disabled="!bookConfig.id"
        >
          书籍
        </button>
      </div>
    </div>
    
    <div class="flex-1 overflow-y-auto p-4 space-y-6">
      <div v-if="activeTab === 'prompt'">
        <label class="block text-sm font-medium text-[var(--text-primary)] mb-2">
          全局系统提示词
        </label>
        <p class="text-xs text-[var(--text-muted)] mb-2">
          作为全书基调，影响所有章节的生成
        </p>
        <textarea
          v-model="localGlobalPrompt"
          rows="12"
          class="w-full px-3 py-2 bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-lg text-[var(--text-primary)] text-sm focus:outline-none focus:border-primary-500 resize-none"
          placeholder="例如：这是一本硬科幻小说，文风偏向刘慈欣，冷峻克制..."
        />
        <div class="mt-3 flex items-center justify-between gap-3">
          <div class="text-xs">
            <span v-if="promptStatus === 'dirty'" class="text-[var(--text-muted)]">未保存</span>
            <span v-else-if="promptStatus === 'saving'" class="text-[var(--text-muted)]">保存中...</span>
            <span v-else-if="promptStatus === 'saved'" class="text-[var(--text-muted)]">已保存</span>
            <span v-else-if="promptStatus === 'error'" class="text-rose-400">{{ promptError }}</span>
          </div>
          <button
            class="px-3 py-1.5 text-sm bg-primary-600 hover:bg-primary-500 disabled:bg-[var(--bg-tertiary)] disabled:text-[var(--text-muted)] text-white rounded-lg transition-colors"
            :disabled="!bookConfig.id || promptStatus === 'saving'"
            @click="saveGlobalPrompt"
          >
            保存
          </button>
        </div>
      </div>

      <div v-else-if="activeTab === 'worldview'">
        <WorldviewSettings
          :book-id="bookConfig.id"
        />
      </div>

      <div v-else-if="activeTab === 'book'">
        <div class="p-3 bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-lg">
          <div class="text-sm font-medium text-[var(--text-primary)]">书籍信息</div>
          <div class="mt-2 text-xs text-[var(--text-muted)]">
            书名与删除等管理入口将在此处提供
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
