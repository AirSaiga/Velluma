<script setup lang="ts">
import { ref, watch } from 'vue'
import type { InspirationIdea, InspirationIdeaType } from '../types'
import { generateApi } from '../services/api'

const props = defineProps<{
  show: boolean
  bookId: string | null | undefined
  chapterId: string
  chapterTitle?: string
  currentContext: string
  activeCharacterIds: string[]
  initialAuthorIntent?: string
}>()

const emit = defineEmits<{
  'update:show': [value: boolean]
  'apply-to-outline': [content: string]
}>()

const loading = ref(false)
const error = ref('')
const inspirations = ref<InspirationIdea[]>([])
const authorIntent = ref('')

const ideaTypeLabels: Record<InspirationIdeaType, string> = {
  plot_twist: '剧情转折',
  key_conflict: '关键冲突',
  new_hook: '新设伏笔',
  smooth_narrative: '平稳叙事'
}

const ideaTypeColors: Record<InspirationIdeaType, string> = {
  plot_twist: 'bg-amber-100 text-amber-700 ring-amber-300',
  key_conflict: 'bg-rose-100 text-rose-700 ring-rose-300',
  new_hook: 'bg-emerald-100 text-emerald-700 ring-emerald-300',
  smooth_narrative: 'bg-blue-100 text-blue-700 ring-blue-300'
}

watch(() => props.show, async (newVal) => {
  if (newVal) {
    authorIntent.value = props.initialAuthorIntent || ''
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
      chapter_title: props.chapterTitle,
      current_context_snippet: props.currentContext,
      active_character_ids: props.activeCharacterIds,
      author_intent: authorIntent.value
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
  <Transition name="modal">
    <div
      v-if="show"
      class="fixed inset-0 z-[var(--z-modal)] flex items-center justify-center bg-black/40 backdrop-blur-sm p-3"
      @click="handleBackdropClick"
    >
      <div class="modal-content bg-[var(--bg-primary)] rounded-2xl shadow-xl w-full max-w-3xl max-h-[85vh] overflow-hidden">
      <div class="p-4 border-b border-white/60 flex items-center justify-between">
        <div>
          <h3 class="text-base font-heading font-semibold text-[var(--text-primary)]">找灵感</h3>
          <p class="text-xs text-[var(--text-muted)] mt-0.5">给这章出几个点子</p>
        </div>
        <button @click="closeModal" class="p-1 text-[var(--text-muted)] hover:text-[var(--text-primary)]">
          <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
          </svg>
        </button>
      </div>

      <div class="p-4 overflow-y-auto max-h-[calc(85vh-120px)]">
        <div class="mb-4">
          <label class="block text-xs font-medium text-[var(--text-muted)] mb-1.5">你想要什么方向？（可空）</label>
          <div class="flex gap-2">
            <textarea
              v-model="authorIntent"
              rows="2"
              class="flex-1 px-3 py-2 rounded-xl bg-[var(--bg-panel)] ring-1 ring-[var(--border-color)] text-xs text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-[var(--accent-500)]/40 resize-none"
              placeholder="你想看到什么类型的灵感？例如：'增加悬疑感'，'让主角陷入困境'..."
              @keydown.enter.prevent="fetchInspirations"
            />
            <button
              @click="fetchInspirations"
              :disabled="loading"
              class="px-4 rounded-xl bg-accent-500 text-white text-xs font-medium hover:bg-accent-600 disabled:opacity-50 transition-colors flex flex-col items-center justify-center gap-1 min-w-[60px]"
            >
              <svg v-if="loading" class="animate-spin spin-reduced h-4 w-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
              </svg>
              <span v-else>生成</span>
            </button>
          </div>
        </div>

        <div v-if="loading" class="flex flex-col items-center justify-center py-8">
          <div class="relative flex items-center justify-center w-16 h-16 mb-4">
            <div class="absolute inset-0 rounded-full border-4 border-accent-50"></div>
            <div class="absolute inset-0 rounded-full border-4 border-accent-500 border-t-transparent animate-spin spin-reduced"></div>
          </div>
          <p class="text-sm text-[var(--text-secondary)]">正在想点子…</p>
        </div>

        <div v-else-if="error" class="flex flex-col items-center justify-center py-8">
          <div class="w-12 h-12 mb-4 rounded-full bg-rose-100 flex items-center justify-center">
            <svg class="w-6 h-6 text-rose-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"/>
            </svg>
          </div>
          <p class="text-sm text-rose-500 mb-3">{{ error }}</p>
          <button
            @click="fetchInspirations"
            class="px-4 py-2 rounded-xl bg-accent-500 text-white text-sm hover:bg-accent-600 transition-colors"
          >
            重试
          </button>
        </div>

        <div v-else-if="inspirations.length > 0" class="space-y-4">
          <div
            v-for="(idea, index) in inspirations"
            :key="index"
            class="bg-parchment-50 rounded-xl ring-1 ring-[var(--border-color)]/60 p-4 space-y-3 hover:shadow-md transition-all duration-200"
          >
            <div class="flex items-center justify-between gap-2">
              <div class="flex items-center gap-2">
                <span
                  class="px-2 py-0.5 text-xs font-medium rounded-full ring-1"
                  :class="ideaTypeColors[idea.idea_type]"
                >
                  {{ ideaTypeLabels[idea.idea_type] }}
                </span>
                <input
                  v-model="idea.title"
                  class="text-sm font-semibold text-[var(--text-primary)] bg-transparent border-b border-transparent hover:border-ink-300 focus:border-accent-500 focus:outline-none px-0.5"
                  placeholder="输入标题..."
                />
              </div>
            </div>

            <div class="space-y-2">
              <label class="text-xs text-[var(--text-muted)]">描述</label>
              <textarea
                v-model="idea.description"
                rows="3"
                class="w-full px-3 py-2 rounded-xl bg-[var(--bg-panel)] ring-1 ring-[var(--border-color)] text-xs text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-[var(--accent-500)]/40 resize-y"
                placeholder="输入描述..."
              ></textarea>
            </div>

            <div class="space-y-2">
              <label class="text-xs text-[var(--text-muted)]">影响</label>
              <textarea
                v-model="idea.impact"
                rows="2"
                class="w-full px-3 py-2 rounded-xl bg-[var(--bg-panel)] ring-1 ring-[var(--border-color)] text-xs text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-[var(--accent-500)]/40 resize-y"
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
                收进大纲
              </button>
            </div>
          </div>
        </div>

        <div v-else class="flex flex-col items-center justify-center py-8">
          <p class="text-sm text-[var(--text-muted)]">还没想到点子</p>
        </div>
      </div>

      <div class="p-4 border-t border-white/60 flex items-center justify-between">
        <button
          @click="fetchInspirations"
          :disabled="loading"
          class="px-3 py-1.5 rounded-xl bg-parchment-50 text-[var(--text-secondary)] text-xs ring-1 ring-[var(--border-color)]/60 hover:bg-ink-50 hover:shadow-md transition-all duration-200 disabled:opacity-40"
        >
          再想几个
        </button>
        <button
          @click="closeModal"
          class="px-4 py-1.5 rounded-xl bg-[var(--bg-panel)] text-[var(--text-secondary)] text-xs hover:bg-ink-50 hover:shadow-md transition-all duration-200"
        >
          关闭
        </button>
      </div>
      </div>
    </div>
  </Transition>
</template>
