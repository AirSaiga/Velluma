<script setup lang="ts">
import { ref, watch } from 'vue'
import type { InspirationIdea, InspirationIdeaType } from '../types'
import { generateApi } from '../services/api'

interface ApiConfig {
  api_key: string
  base_url: string
  model: string
}

const props = defineProps<{
  show: boolean
  bookId: string | null | undefined
  chapterId: string
  currentContext: string
  activeCharacterIds: string[]
  apiConfig: ApiConfig
}>()

const emit = defineEmits<{
  'update:show': [value: boolean]
  'apply-to-outline': [content: string]
}>()

const loading = ref(false)
const error = ref('')
const inspirations = ref<InspirationIdea[]>([])

const ideaTypeLabels: Record<InspirationIdeaType, string> = {
  plot_twist: '剧情转折',
  key_conflict: '关键冲突',
  new_hook: '新设伏笔'
}

const ideaTypeColors: Record<InspirationIdeaType, string> = {
  plot_twist: 'bg-amber-100 text-amber-700 ring-amber-300',
  key_conflict: 'bg-rose-100 text-rose-700 ring-rose-300',
  new_hook: 'bg-emerald-100 text-emerald-700 ring-emerald-300'
}

watch(() => props.show, async (newVal) => {
  if (newVal) {
    await fetchInspirations()
  }
})

async function fetchInspirations() {
  if (!props.bookId || !props.chapterId) {
    error.value = '缺少书籍或章节信息'
    return
  }

  loading.value = true
  error.value = ''
  inspirations.value = []

  try {
    const response = await generateApi.generateInspiration({
      book_id: props.bookId,
      chapter_id: props.chapterId,
      current_context_snippet: props.currentContext,
      active_character_ids: props.activeCharacterIds,
      temperature: 0.9,
      api_key: props.apiConfig.api_key,
      base_url: props.apiConfig.base_url,
      model: props.apiConfig.model || 'gpt-4o-mini'
    })

    inspirations.value = response.inspirations || []
  } catch (e: any) {
    error.value = e.message || '获取灵感失败'
  } finally {
    loading.value = false
  }
}

function applyToOutline(idea: InspirationIdea) {
  const content = `${idea.title}: ${idea.description}`
  emit('apply-to-outline', content)
  emit('update:show', false)
}

function closeModal() {
  emit('update:show', false)
}

function handleBackdropClick(e: MouseEvent) {
  if (e.target === e.currentTarget) {
    closeModal()
  }
}
</script>

<template>
  <div
    v-if="show"
    class="fixed inset-0 z-50 flex items-center justify-center bg-black/45 p-3"
    @click="handleBackdropClick"
  >
    <div class="bg-[var(--bg-primary)] rounded-2xl shadow-2xl w-full max-w-3xl max-h-[85vh] overflow-hidden">
      <div class="p-4 border-b border-white/60 flex items-center justify-between">
        <div>
          <h3 class="text-base font-semibold text-[var(--text-primary)]">点子启发</h3>
          <p class="text-[11px] text-[var(--text-muted)] mt-0.5">为您的剧情提供灵感火花</p>
        </div>
        <button @click="closeModal" class="p-1 text-[var(--text-muted)] hover:text-[var(--text-primary)]">
          <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
          </svg>
        </button>
      </div>

      <div class="p-4 overflow-y-auto max-h-[calc(85vh-120px)]">
        <div v-if="loading" class="flex flex-col items-center justify-center py-12">
          <div class="relative flex items-center justify-center w-16 h-16 mb-4">
            <div class="absolute inset-0 rounded-full border-4 border-indigo-50"></div>
            <div class="absolute inset-0 rounded-full border-4 border-indigo-500 border-t-transparent animate-spin"></div>
          </div>
          <p class="text-sm text-[var(--text-secondary)]">正在思考灵感...</p>
        </div>

        <div v-else-if="error" class="flex flex-col items-center justify-center py-12">
          <div class="w-12 h-12 mb-4 rounded-full bg-rose-100 flex items-center justify-center">
            <svg class="w-6 h-6 text-rose-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"/>
            </svg>
          </div>
          <p class="text-sm text-rose-500 mb-3">{{ error }}</p>
          <button
            @click="fetchInspirations"
            class="px-4 py-2 rounded-lg bg-indigo-500 text-white text-sm hover:bg-indigo-600 transition-colors"
          >
            重试
          </button>
        </div>

        <div v-else-if="inspirations.length > 0" class="space-y-4">
          <div
            v-for="(idea, index) in inspirations"
            :key="index"
            class="bg-white rounded-xl border border-slate-200 p-4 space-y-3"
          >
            <div class="flex items-center justify-between gap-2">
              <div class="flex items-center gap-2">
                <span
                  class="px-2 py-0.5 text-[10px] font-medium rounded-full ring-1"
                  :class="ideaTypeColors[idea.idea_type]"
                >
                  {{ ideaTypeLabels[idea.idea_type] }}
                </span>
                <input
                  v-model="idea.title"
                  class="text-sm font-semibold text-[var(--text-primary)] bg-transparent border-b border-transparent hover:border-slate-300 focus:border-indigo-500 focus:outline-none px-0.5"
                  placeholder="输入标题..."
                />
              </div>
            </div>

            <div class="space-y-2">
              <label class="text-[10px] text-[var(--text-muted)]">描述</label>
              <textarea
                v-model="idea.description"
                rows="3"
                class="w-full px-3 py-2 rounded-lg bg-slate-50 border border-slate-200 text-xs text-[var(--text-primary)] focus:outline-none focus:ring-1 focus:ring-indigo-500 focus:border-indigo-500 resize-y"
                placeholder="输入描述..."
              ></textarea>
            </div>

            <div class="space-y-2">
              <label class="text-[10px] text-[var(--text-muted)]">影响</label>
              <textarea
                v-model="idea.impact"
                rows="2"
                class="w-full px-3 py-2 rounded-lg bg-slate-50 border border-slate-200 text-xs text-[var(--text-primary)] focus:outline-none focus:ring-1 focus:ring-indigo-500 focus:border-indigo-500 resize-y"
                placeholder="输入影响说明..."
              ></textarea>
            </div>

            <div class="flex justify-end pt-2">
              <button
                @click="applyToOutline(idea)"
                class="px-3 py-1.5 rounded-lg bg-[var(--accent-500)] text-white text-xs font-medium hover:bg-[var(--accent-600)] transition-colors flex items-center gap-1.5"
              >
                <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4"/>
                </svg>
                应用到大纲
              </button>
            </div>
          </div>
        </div>

        <div v-else class="flex flex-col items-center justify-center py-12">
          <p class="text-sm text-[var(--text-muted)]">暂无灵感数据</p>
        </div>
      </div>

      <div class="p-4 border-t border-white/60 flex items-center justify-between">
        <button
          @click="fetchInspirations"
          :disabled="loading"
          class="px-3 py-1.5 rounded-lg bg-white text-[var(--text-secondary)] text-xs ring-1 ring-slate-200 hover:bg-slate-50 disabled:opacity-40 transition-colors"
        >
          重新生成
        </button>
        <button
          @click="closeModal"
          class="px-4 py-1.5 rounded-lg bg-[var(--bg-panel)] text-[var(--text-secondary)] text-xs hover:bg-slate-100 transition-colors"
        >
          关闭
        </button>
      </div>
    </div>
  </div>
</template>
