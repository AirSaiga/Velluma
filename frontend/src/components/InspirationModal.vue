<script setup lang="ts">
/**
 * 找灵感弹窗（02 §5 收编 ModalShell；四类 chip 色改语义 token，深色适配自动获得）。
 */
import { ref, watch } from 'vue'
import ModalShell from './ModalShell.vue'
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
  plot_twist: 'idea-chip--warn',
  key_conflict: 'idea-chip--danger',
  new_hook: 'idea-chip--mint',
  smooth_narrative: 'idea-chip--info'
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
</script>

<template>
  <ModalShell
    v-if="show"
    title="找灵感"
    subtitle="给这章出几个点子"
    width="48rem"
    @close="closeModal"
  >
    <div class="mb-4">
      <label class="block text-xs font-medium text-[var(--text-muted)] mb-1.5">你想要什么方向？（可空）</label>
      <div class="flex gap-2">
        <textarea
          v-model="authorIntent"
          rows="2"
          class="im-input flex-1"
          placeholder="你想看到什么类型的灵感？例如：'增加悬疑感'，'让主角陷入困境'..."
          @keydown.enter.prevent="fetchInspirations"
        />
        <button
          @click="fetchInspirations"
          :disabled="loading"
          class="im-go"
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
        <div class="absolute inset-0 rounded-full border-4 border-accent-100"></div>
        <div class="absolute inset-0 rounded-full border-4 border-accent-500 border-t-transparent animate-spin spin-reduced"></div>
      </div>
      <p class="text-sm text-[var(--text-secondary)]">正在想点子…</p>
    </div>

    <div v-else-if="error" class="flex flex-col items-center justify-center py-8">
      <div class="w-12 h-12 mb-4 rounded-full bg-[color-mix(in_srgb,var(--danger)_12%,transparent)] flex items-center justify-center">
        <svg class="w-6 h-6 text-[var(--danger)]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"/>
        </svg>
      </div>
      <p class="text-sm text-[var(--danger)] mb-3">{{ error }}</p>
      <button @click="fetchInspirations" class="im-go im-go--retry">重试</button>
    </div>

    <div v-else-if="inspirations.length > 0" class="space-y-4">
      <div
        v-for="(idea, index) in inspirations"
        :key="index"
        class="im-card space-y-3"
      >
        <div class="flex items-center justify-between gap-2">
          <div class="flex items-center gap-2">
            <span class="idea-chip" :class="ideaTypeColors[idea.idea_type]">
              {{ ideaTypeLabels[idea.idea_type] }}
            </span>
            <input
              v-model="idea.title"
              class="im-title"
              placeholder="输入标题..."
            />
          </div>
        </div>

        <div class="space-y-2">
          <label class="text-xs text-[var(--text-muted)]">描述</label>
          <textarea v-model="idea.description" rows="3" class="im-input w-full" placeholder="输入描述..."></textarea>
        </div>

        <div class="space-y-2">
          <label class="text-xs text-[var(--text-muted)]">影响</label>
          <textarea v-model="idea.impact" rows="2" class="im-input w-full" placeholder="输入影响说明..."></textarea>
        </div>

        <div class="flex justify-end pt-2">
          <button @click="applyToOutline(idea)" class="im-apply">
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

    <template #footer>
      <button
        @click="fetchInspirations"
        :disabled="loading"
        class="im-secondary"
      >
        再想几个
      </button>
      <button @click="closeModal" class="im-secondary">关闭</button>
    </template>
  </ModalShell>
</template>

<style scoped>
.im-input {
  padding: 8px 12px;
  border-radius: var(--radius-lg);
  background: var(--surface-overlay);
  border: 1px solid var(--border-color);
  font-size: var(--text-xs);
  line-height: var(--lh-normal);
  color: var(--text-primary);
  outline: none;
  resize: vertical;
}
.im-input:focus {
  border-color: var(--accent-500);
}
.im-go {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 4px;
  min-width: 60px;
  padding: 0 16px;
  border: none;
  border-radius: var(--radius-lg);
  background: var(--accent-500);
  color: var(--bg-canvas);
  font-size: var(--text-xs);
  font-weight: 500;
  cursor: pointer;
  transition: background var(--dur-2) var(--ease-out);
}
.im-go:hover:not(:disabled) { background: var(--accent-600); }
.im-go:disabled { opacity: 0.5; cursor: not-allowed; }
.im-go--retry { padding: 8px 16px; min-width: 0; font-size: var(--text-sm); }
.im-card {
  padding: var(--space-4);
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  transition: box-shadow var(--dur-3) var(--ease-out);
}
.im-card:hover { box-shadow: var(--shadow-md); }
.im-title {
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--text-primary);
  background: transparent;
  border: none;
  border-bottom: 1px solid transparent;
  outline: none;
  padding: 0 2px;
}
.im-title:hover { border-bottom-color: var(--border-color); }
.im-title:focus { border-bottom-color: var(--accent-500); }
.im-apply {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  border: none;
  border-radius: var(--radius-md);
  background: var(--accent-500);
  color: var(--bg-canvas);
  font-size: var(--text-xs);
  font-weight: 500;
  cursor: pointer;
  transition: background var(--dur-2) var(--ease-out);
}
.im-apply:hover { background: var(--accent-600); }
.im-secondary {
  padding: 6px 12px;
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  background: var(--bg-secondary);
  color: var(--text-secondary);
  font-size: var(--text-xs);
  cursor: pointer;
  transition: all var(--dur-2) var(--ease-out);
}
.im-secondary:hover:not(:disabled) { background: var(--state-hover); color: var(--text-primary); }
.im-secondary:disabled { opacity: 0.4; cursor: not-allowed; }
/* 四类灵感 chip：语义 token（02 §1.6），深色适配由 token 自动获得 */
.idea-chip {
  padding: 2px 8px;
  font-size: var(--text-xs);
  font-weight: 500;
  border-radius: var(--radius-pill);
  border: 1px solid transparent;
  white-space: nowrap;
}
.idea-chip--warn {
  background: color-mix(in srgb, var(--warn) 10%, transparent);
  color: var(--warn);
  border-color: color-mix(in srgb, var(--warn) 35%, transparent);
}
.idea-chip--danger {
  background: color-mix(in srgb, var(--danger) 10%, transparent);
  color: var(--danger);
  border-color: color-mix(in srgb, var(--danger) 35%, transparent);
}
.idea-chip--mint {
  background: color-mix(in srgb, var(--mint) 10%, transparent);
  color: var(--mint-ink);
  border-color: color-mix(in srgb, var(--mint) 35%, transparent);
}
.idea-chip--info {
  background: color-mix(in srgb, var(--info) 10%, transparent);
  color: var(--info);
  border-color: color-mix(in srgb, var(--info) 35%, transparent);
}
</style>
