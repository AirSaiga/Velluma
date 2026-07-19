<script setup lang="ts">
import { ref, watch, toRef } from 'vue'
import { useFocusTrap } from '../../../composables/useFocusTrap'
import { costReportApi } from '../../../services/api'
import { useToast } from '../../../composables/useToast'
import type { CostReport } from '../../../types'

const props = defineProps<{
  show: boolean
  chapterId: string
  runId?: string
}>()

const emit = defineEmits<{
  (e: 'close'): void
}>()

const { showToast } = useToast()
const modalRef = ref<HTMLElement | null>(null)
const showRef = toRef(props, 'show')
useFocusTrap(modalRef, showRef, { onEscape: () => emit('close') })

const report = ref<CostReport | null>(null)
const isLoading = ref(false)
const errorText = ref('')

async function loadReport() {
  if (!props.chapterId) return
  isLoading.value = true
  errorText.value = ''
  try {
    report.value = await costReportApi.get(props.chapterId, props.runId)
  } catch (err: any) {
    errorText.value = err?.message || '加载成本报告失败'
    showToast(errorText.value, 'error')
  } finally {
    isLoading.value = false
  }
}

watch(() => props.show, (newShow) => {
  if (newShow) loadReport()
}, { immediate: true })

function formatNum(n: number | undefined): string {
  if (n === undefined || n === null) return '-'
  return n.toLocaleString()
}

const stageLabelMap: Record<string, string> = {
  'planning.beats': '节拍规划',
  'planning.pov': 'POV 分配',
  'intent_and_sketch.beat_1': '思考层·拍1',
  'sketch': '速写骨架',
  'sketch.generation': '速写生成',
  'stitching': '统稿缝合',
  'reviewing.alignment': '对抗校对',
  'refining.chapter': '全局精修',
  'refining.global': '全局精修',
}

function getStageLabel(stage: string): string {
  // 匹配 drafting.beat_N
  const draftMatch = stage.match(/^drafting\.beat_(\d+)$/)
  if (draftMatch) return `正文·拍${draftMatch[1]}`
  const refineMatch = stage.match(/^refining\.beat\.(.+)$/)
  if (refineMatch) return `精修·${refineMatch[1]}`
  return stageLabelMap[stage] || stage
}
</script>

<template>
  <Teleport to="body">
    <div
      v-if="show"
      ref="modalRef"
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/45 p-3"
      @click.self="emit('close')"
    >
      <div class="bg-[var(--bg-primary)] rounded-2xl shadow-2xl w-full max-w-3xl max-h-[80vh] overflow-hidden flex flex-col">
        <div class="p-3 border-b border-[var(--border-color)] flex items-center justify-between">
          <h3 class="text-sm font-semibold">成本报告（Token 计量）</h3>
          <button @click="emit('close')" class="text-[var(--text-muted)] hover:text-[var(--text-primary)]">✕</button>
        </div>

        <div class="p-4 overflow-y-auto">
          <div v-if="isLoading" class="text-center py-8 text-[var(--text-muted)] text-sm">加载中...</div>
          <div v-else-if="errorText" class="text-center py-8 text-red-500 text-sm">{{ errorText }}</div>
          <div v-else-if="!report || report.stages.length === 0" class="text-center py-8 text-[var(--text-muted)] text-sm">
            暂无成本数据（可能本章尚未生成或未启用观测层）
          </div>
          <div v-else class="space-y-4">
            <!-- 汇总卡片 -->
            <div class="grid grid-cols-4 gap-2">
              <div class="p-2 bg-[var(--bg-panel)] rounded text-center">
                <div class="text-[10px] text-[var(--text-muted)]">总调用</div>
                <div class="text-lg font-semibold text-[var(--text-primary)]">{{ report.totals.calls }}</div>
              </div>
              <div class="p-2 bg-[var(--bg-panel)] rounded text-center">
                <div class="text-[10px] text-[var(--text-muted)]">总 Token</div>
                <div class="text-lg font-semibold text-[var(--accent-500)]">{{ formatNum(report.totals.total_tokens) }}</div>
              </div>
              <div class="p-2 bg-[var(--bg-panel)] rounded text-center">
                <div class="text-[10px] text-[var(--text-muted)]">Thinking</div>
                <div class="text-lg font-semibold" :class="report.totals.thinking_tokens > 0 ? 'text-orange-500' : 'text-green-500'">
                  {{ formatNum(report.totals.thinking_tokens) }}
                </div>
              </div>
              <div class="p-2 bg-[var(--bg-panel)] rounded text-center">
                <div class="text-[10px] text-[var(--text-muted)]">降级次数</div>
                <div class="text-lg font-semibold" :class="report.totals.degraded_count > 0 ? 'text-orange-500' : 'text-[var(--text-primary)]'">
                  {{ report.totals.degraded_count }}
                </div>
              </div>
            </div>

            <!-- 分阶段表 -->
            <table class="w-full text-xs">
              <thead>
                <tr class="border-b border-[var(--border-color)] text-[var(--text-muted)]">
                  <th class="py-2 text-left">阶段</th>
                  <th class="py-2 text-right">调用</th>
                  <th class="py-2 text-right">输入</th>
                  <th class="py-2 text-right">输出</th>
                  <th class="py-2 text-right">Thinking</th>
                  <th class="py-2 text-right">延迟(ms)</th>
                  <th class="py-2 text-right">槽位</th>
                  <th class="py-2 text-right">降级</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="stage in report.stages"
                  :key="stage.stage"
                  class="border-b border-[var(--border-color)] border-opacity-30"
                >
                  <td class="py-1.5 text-[var(--text-secondary)]">{{ getStageLabel(stage.stage) }}</td>
                  <td class="py-1.5 text-right">{{ stage.calls }}</td>
                  <td class="py-1.5 text-right">{{ formatNum(stage.prompt_tokens) }}</td>
                  <td class="py-1.5 text-right">{{ formatNum(stage.completion_tokens) }}</td>
                  <td class="py-1.5 text-right" :class="stage.thinking_tokens > 0 ? 'text-orange-500' : 'text-[var(--text-muted)]'">
                    {{ stage.thinking_tokens > 0 ? formatNum(stage.thinking_tokens) : '-' }}
                  </td>
                  <td class="py-1.5 text-right text-[var(--text-muted)]">{{ formatNum(stage.latency_ms_avg) }}</td>
                  <td class="py-1.5 text-right">
                    <span
                      v-for="slot in stage.model_slots"
                      :key="slot"
                      class="inline-block px-1 py-0.5 ml-0.5 text-[9px] rounded"
                      :class="slot === 'creative' ? 'bg-green-100 text-green-700' : 'bg-blue-100 text-blue-700'"
                    >{{ slot }}</span>
                  </td>
                  <td class="py-1.5 text-right" :class="stage.degraded_count > 0 ? 'text-orange-500' : 'text-[var(--text-muted)]'">
                    {{ stage.degraded_count > 0 ? stage.degraded_count : '-' }}
                  </td>
                </tr>
              </tbody>
              <tfoot>
                <tr class="border-t-2 border-[var(--border-color)] font-semibold">
                  <td class="py-2">合计</td>
                  <td class="py-2 text-right">{{ report.totals.calls }}</td>
                  <td class="py-2 text-right">{{ formatNum(report.totals.prompt_tokens) }}</td>
                  <td class="py-2 text-right">{{ formatNum(report.totals.completion_tokens) }}</td>
                  <td class="py-2 text-right" :class="report.totals.thinking_tokens > 0 ? 'text-orange-500' : ''">
                    {{ formatNum(report.totals.thinking_tokens) }}
                  </td>
                  <td class="py-2 text-right text-[var(--text-muted)]">-</td>
                  <td class="py-2"></td>
                  <td class="py-2 text-right">{{ report.totals.degraded_count }}</td>
                </tr>
              </tfoot>
            </table>
          </div>
        </div>

        <div class="p-3 border-t border-[var(--border-color)] flex justify-end">
          <button @click="emit('close')" class="px-3 py-1.5 text-xs rounded bg-[var(--bg-panel)] hover:bg-parchment-100">关闭</button>
        </div>
      </div>
    </div>
  </Teleport>
</template>
