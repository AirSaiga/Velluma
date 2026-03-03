<script setup>
import { ref, watch } from 'vue'
import { bookApi } from '../composables/useApi'

const props = defineProps({
  bookId: {
    type: String,
    required: true
  }
})

const emit = defineEmits(['update-worldview'])

const localWorldview = ref('')
const isLoading = ref(false)
const isSaving = ref(false)
const lastSaved = ref(false)

async function loadWorldview() {
  if (!props.bookId) return
  isLoading.value = true
  try {
    const data = await bookApi.getWorldview(props.bookId)
    localWorldview.value = typeof data.worldview_settings === 'string' ? data.worldview_settings : JSON.stringify(data.worldview_settings || {})
  } catch (error) {
    console.error('加载世界观设定失败:', error)
    localWorldview.value = ''
  } finally {
    isLoading.value = false
  }
}

async function saveWorldview() {
  if (!props.bookId) return
  isSaving.value = true
  lastSaved.value = false
  try {
    const data = await bookApi.updateWorldview(props.bookId, {
      worldview_settings: localWorldview.value
    })
    emit('update-worldview', data)
    lastSaved.value = true
    setTimeout(() => {
      lastSaved.value = false
    }, 2000)
  } catch (error) {
    console.error('保存世界观设定失败:', error)
  } finally {
    isSaving.value = false
  }
}

watch(() => props.bookId, (newId) => {
  if (newId) {
    loadWorldview()
  }
}, { immediate: true })
</script>

<template>
  <div class="worldview-editor">
    <div class="flex items-center justify-between mb-2">
      <label class="block text-sm font-medium text-[var(--text-primary)]">
        世界观设定
      </label>
      <div class="flex items-center gap-2">
        <span v-if="isSaving" class="text-xs text-[var(--text-muted)]">
          保存中...
        </span>
        <span v-else-if="lastSaved" class="text-xs text-[var(--text-muted)]">
          已保存
        </span>
        <button
          @click="saveWorldview"
          :disabled="isSaving"
          class="px-3 py-1 text-sm bg-primary-600 hover:bg-primary-500 disabled:bg-[var(--bg-tertiary)] text-white rounded transition-colors"
        >
          保存
        </button>
      </div>
    </div>
    <p class="text-xs text-[var(--text-muted)] mb-2">
      定义故事的世界背景、规则、历史等设定，会在生成章节时自动融入
    </p>
    <textarea
      v-model="localWorldview"
      @blur="saveWorldview"
      rows="12"
      class="w-full px-3 py-2 bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-lg text-[var(--text-primary)] text-sm focus:outline-none focus:border-primary-500 resize-none"
      placeholder="例如：
【时代背景】
21世纪末，全球气候变暖导致海平面上升...

【世界规则】
这个世界的魔法基于星尘能量...

【重要历史】
三战结束后，联合国解体..."
    />
    <div v-if="isLoading" class="text-xs text-[var(--text-muted)] mt-1">
      加载中...
    </div>
  </div>
</template>
