<script setup>
import { ref, watch } from 'vue'
import WorldviewSettings from './WorldviewSettings.vue'

const props = defineProps({
  bookConfig: {
    type: Object,
    default: () => ({ global_sys_prompt: '', id: null })
  }
})

const emit = defineEmits(['update-book-config'])

const localGlobalPrompt = ref(props.bookConfig.global_sys_prompt || '')

watch(() => props.bookConfig, (newVal) => {
  localGlobalPrompt.value = newVal.global_sys_prompt || ''
}, { immediate: true })

function saveGlobalPrompt() {
  emit('update-book-config', { global_sys_prompt: localGlobalPrompt.value })
}

function handleWorldviewUpdate(data) {
  console.log('世界观设定已更新:', data)
}
</script>

<template>
  <div class="h-full flex flex-col bg-[var(--bg-secondary)] border-l border-[var(--border-color)]">
    <div class="p-4 border-b border-[var(--border-color)]">
      <h2 class="text-lg font-semibold text-[var(--text-primary)]">书籍配置</h2>
    </div>
    
    <div class="flex-1 overflow-y-auto p-4 space-y-6">
      <div>
        <label class="block text-sm font-medium text-[var(--text-primary)] mb-2">
          全局系统提示词
        </label>
        <p class="text-xs text-[var(--text-muted)] mb-2">
          作为全书基调，影响所有章节的生成
        </p>
        <textarea
          v-model="localGlobalPrompt"
          @blur="saveGlobalPrompt"
          rows="12"
          class="w-full px-3 py-2 bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-lg text-[var(--text-primary)] text-sm focus:outline-none focus:border-primary-500 resize-none"
          placeholder="例如：这是一本硬科幻小说，文风偏向刘慈欣，冷峻克制..."
        />
      </div>

      <div v-if="bookConfig.id" class="border-t border-[var(--border-color)] pt-6">
        <WorldviewSettings
          :book-id="bookConfig.id"
          @update-worldview="handleWorldviewUpdate"
        />
      </div>
    </div>
  </div>
</template>
