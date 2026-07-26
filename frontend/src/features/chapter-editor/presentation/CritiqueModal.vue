<script setup lang="ts">
/**
 * 章节审阅结果弹窗（毒舌编辑视角）。
 *
 * 数据来源：POST /api/critique_chapter（reviewApi.critiqueChapter），
 * 纯文本审阅，不依赖数据库上下文。
 */
import { ref, computed } from 'vue'
import { useFocusTrap } from '../../../composables/useFocusTrap'
import type { CritiqueItem } from '../../../services/api/domain/review.api'

const props = defineProps<{
  show: boolean
  loading: boolean
  comments: CritiqueItem[]
  overallPraise: string
}>()

const emit = defineEmits<{
  (e: 'close'): void
}>()

const modalRef = ref<HTMLElement | null>(null)
const showRef = computed(() => props.show)
useFocusTrap(modalRef, showRef, { onEscape: () => emit('close') })
</script>

<template>
  <Teleport to="body">
    <div
      v-if="show"
      ref="modalRef"
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/45 p-3"
      @click.self="emit('close')"
    >
      <div class="bg-[var(--bg-primary)] rounded-2xl shadow-2xl w-full max-w-xl max-h-[85vh] overflow-hidden flex flex-col">
        <div class="p-3 border-b border-[var(--border-color)] flex items-center justify-between">
          <h3 class="text-sm font-semibold text-[var(--text-primary)]">编辑审阅</h3>
          <button @click="emit('close')" class="p-1 text-[var(--text-muted)] hover:text-[var(--text-primary)]">
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
            </svg>
          </button>
        </div>

        <div class="p-4 overflow-y-auto max-h-[calc(85vh-60px)]">
          <!-- 加载态 -->
          <div v-if="loading" class="flex flex-col items-center py-10 gap-3">
            <div class="w-8 h-8 rounded-full border-4 border-accent-100 border-t-accent-500 animate-spin"></div>
            <p class="text-xs text-[var(--text-muted)]">编辑正在逐字审阅本章…</p>
          </div>

          <template v-else>
            <!-- 总评 -->
            <div v-if="overallPraise" class="mb-4 p-3 bg-[var(--bg-panel)] rounded-lg">
              <h4 class="text-xs font-medium text-[var(--text-secondary)] mb-1">总评</h4>
              <p class="text-xs text-[var(--text-primary)] leading-relaxed">{{ overallPraise }}</p>
            </div>

            <!-- 审阅条目 -->
            <div v-if="comments.length > 0" class="space-y-3">
              <div
                v-for="(item, i) in comments"
                :key="i"
                class="p-3 bg-[var(--bg-panel)] rounded-lg text-xs space-y-1.5"
              >
                <div class="flex items-center gap-2">
                  <span class="px-2 py-0.5 text-[10px] rounded-full bg-amber-100 text-amber-700">{{ item.type }}</span>
                </div>
                <blockquote class="border-l-2 border-[var(--border-color)] pl-2 text-[var(--text-muted)] italic">
                  {{ item.exact_quote }}
                </blockquote>
                <div class="text-[var(--text-primary)]">
                  <span class="text-[var(--text-muted)]">读者感受：</span>{{ item.reader_feeling }}
                </div>
                <div class="text-emerald-700">
                  <span class="text-[var(--text-muted)]">修改建议：</span>{{ item.suggestion }}
                </div>
              </div>
            </div>

            <div v-else-if="!overallPraise" class="text-center text-sm text-[var(--text-muted)] py-6">
              暂无审阅结果
            </div>
          </template>
        </div>
      </div>
    </div>
  </Teleport>
</template>
