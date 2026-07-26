<script setup lang="ts">
/**
 * 生成完成弹窗（ADF 生成 / Refinery 精修共用）。
 *
 * 职责：完成后展示数据总结（字数/耗时/climax 评分/审计结论）+ 行动按钮。
 * 受控方式：show prop + close 事件（与 PublishModal 一致）。
 * 统计数据防御式渲染——后端 stats 字段不一定全有，缺的字段不显示对应行。
 */
import { ref, computed } from 'vue'
import { useFocusTrap } from '../../../composables/useFocusTrap'

const props = defineProps<{
  show: boolean
  /** 完成来源，决定标题文案 */
  mode: 'adf' | 'refinery' | 'bsadf' | null
  /** 章节标题（展示用） */
  chapterTitle?: string
  /** 后端 stats（word_count / audit_climax_score / final_word_count / operations_executed 等），
   *  含前端注入的 duration_ms */
  stats: Record<string, any> | null
  /** 是否存在下一章（控制"生成下一章"次按钮） */
  hasNextChapter?: boolean
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'next-chapter'): void
}>()

const modalRef = ref<HTMLElement | null>(null)
const showRef = computed(() => props.show)
useFocusTrap(modalRef, showRef, { onEscape: () => emit('close') })

// ---- 派生展示数据（防御式：字段不存在则该项为 null，模板 v-if 跳过）----
const title = computed(() => {
  if (props.mode === 'refinery') return '精修完成'
  if (props.mode === 'bsadf') return '章节生成完成'
  return '章节生成完成'
})

/** 字数：ADF 用 word_count，Refinery 用 final_word_count */
const wordCount = computed(() => {
  const s = props.stats
  if (!s) return null
  const wc = s.word_count ?? s.final_word_count
  return typeof wc === 'number' ? wc : null
})

/** 耗时（ms → 可读字符串） */
const duration = computed(() => {
  const ms = props.stats?.duration_ms
  if (typeof ms !== 'number') return null
  const totalSec = Math.round(ms / 1000)
  if (totalSec < 60) return `${totalSec} 秒`
  const m = Math.floor(totalSec / 60)
  const s = totalSec % 60
  return s === 0 ? `${m} 分钟` : `${m} 分 ${s} 秒`
})

/** ADF climax 评分（仅 ADF 有） */
const climaxScore = computed(() => {
  const score = props.stats?.audit_climax_score
  return typeof score === 'number' ? score : null
})

/** ADF 审计结论（仅 ADF 有） */
const auditVerdict = computed(() => {
  const v = props.stats?.audit_verdict
  return typeof v === 'string' && v ? v : null
})

/** Refinery 手术执行数（仅 Refinery 有） */
const operationsExecuted = computed(() => {
  const n = props.stats?.operations_executed
  return typeof n === 'number' ? n : null
})

const VERDICT_LABELS: Record<string, string> = {
  pass: '通过',
  pass_with_fixes: '修改后通过',
  needs_refinement: '需要精修',
  needs_final_touch: '需要再修',
  fail: '未通过',
  unaudited: '未审校',
}
function verdictLabel(v: string) {
  return VERDICT_LABELS[v] || v
}
</script>

<template>
  <Teleport to="body">
    <Transition name="modal">
      <div
        v-if="show"
        ref="modalRef"
        class="fixed inset-0 z-50 flex items-center justify-center bg-black/45 p-3"
        @click.self="emit('close')"
      >
        <div class="bg-[var(--bg-primary)] rounded-2xl shadow-2xl w-full max-w-md max-h-[85vh] overflow-hidden flex flex-col">
          <!-- 头部 -->
          <div class="p-4 border-b border-[var(--border-color)] flex items-start justify-between">
            <div>
              <h3 class="text-base font-semibold text-[var(--text-primary)] flex items-center gap-2">
                <span class="text-green-500">✓</span>
                {{ title }}
              </h3>
              <p v-if="chapterTitle" class="text-xs text-[var(--text-muted)] mt-1 truncate max-w-[300px]">
                《{{ chapterTitle }}》
              </p>
            </div>
            <button
              @click="emit('close')"
              class="p-1 text-[var(--text-muted)] hover:text-[var(--text-primary)] flex-shrink-0"
              title="关闭"
            >
              <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
              </svg>
            </button>
          </div>

          <!-- 数据统计区（防御式：每项数据存在才渲染） -->
          <div class="p-4 overflow-y-auto">
            <div class="grid grid-cols-2 gap-3">
              <div v-if="wordCount !== null" class="stat-card">
                <div class="stat-num">{{ wordCount.toLocaleString() }}</div>
                <div class="stat-label">字数</div>
              </div>
              <div v-if="duration !== null" class="stat-card">
                <div class="stat-num">{{ duration }}</div>
                <div class="stat-label">耗时</div>
              </div>
              <div v-if="climaxScore !== null" class="stat-card">
                <div class="stat-num">{{ climaxScore }}/10</div>
                <div class="stat-label">高潮评分</div>
              </div>
              <div v-if="operationsExecuted !== null" class="stat-card">
                <div class="stat-num">{{ operationsExecuted }}</div>
                <div class="stat-label">手术处数</div>
              </div>
            </div>

            <!-- 审计结论（仅 ADF 且有 verdict 时显示） -->
            <div v-if="auditVerdict" class="mt-3 p-2.5 bg-[var(--bg-panel)] rounded-lg text-xs flex items-center justify-between">
              <span class="text-[var(--text-muted)]">结构审计</span>
              <span class="font-medium text-[var(--text-primary)]">{{ verdictLabel(auditVerdict) }}</span>
            </div>
          </div>

          <!-- 底部行动按钮 -->
          <div class="p-3 border-t border-[var(--border-color)] flex justify-end gap-2">
            <button
              v-if="hasNextChapter"
              @click="emit('next-chapter')"
              class="px-4 py-1.5 text-xs rounded-lg border border-[var(--border-color)] text-[var(--text-secondary)] hover:bg-[var(--hover-bg)] hover:text-[var(--text-primary)]"
            >
              生成下一章
            </button>
            <button
              @click="emit('close')"
              class="px-4 py-1.5 text-xs rounded-lg bg-[var(--accent-500)] text-white hover:bg-[var(--accent-600)]"
            >
              查看本章
            </button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.stat-card {
  background: var(--bg-panel);
  border-radius: 0.5rem;
  padding: 0.75rem;
  text-align: center;
}
.stat-num {
  font-family: var(--font-heading);
  font-size: 1.25rem;
  font-weight: 600;
  color: var(--accent-500);
  line-height: 1.1;
}
.stat-label {
  font-size: 0.6875rem;
  color: var(--text-muted);
  margin-top: 0.25rem;
}
</style>
