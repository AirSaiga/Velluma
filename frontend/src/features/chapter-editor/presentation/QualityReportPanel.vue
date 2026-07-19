<script setup lang="ts">
import { ref, watch, toRef } from 'vue'
import { useFocusTrap } from '../../../composables/useFocusTrap'
import { qualityReportApi } from '../../../services/api'
import { useToast } from '../../../composables/useToast'
import type { QualityReport, FindingItem, MetricsBlock } from '../../../types'

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

const report = ref<QualityReport | null>(null)
const isLoading = ref(false)
const isRerunning = ref(false)
const errorText = ref('')

async function loadReport() {
  if (!props.chapterId) return
  isLoading.value = true
  errorText.value = ''
  try {
    report.value = await qualityReportApi.get(props.chapterId, props.runId)
  } catch (err: any) {
    // 404 时给出更友好的提示（本章尚无报告）
    const msg = err?.message || ''
    if (msg.includes('404') || msg.includes('尚无质量报告')) {
      errorText.value = '本章尚无质量报告，可点击「重新审计」触发'
    } else {
      errorText.value = msg || '加载质量报告失败'
      showToast(errorText.value, 'error')
    }
  } finally {
    isLoading.value = false
  }
}

async function rerunAudit() {
  if (!props.chapterId || isRerunning.value) return
  isRerunning.value = true
  errorText.value = ''
  try {
    report.value = await qualityReportApi.rerun(props.chapterId, props.runId)
    showToast('重新审计完成', 'success')
  } catch (err: any) {
    errorText.value = err?.message || '重新审计失败'
    showToast(errorText.value, 'error')
  } finally {
    isRerunning.value = false
  }
}

watch(() => props.show, (newShow) => {
  if (newShow) loadReport()
}, { immediate: true })

function formatMetric(v: number | undefined, digits = 2): string {
  if (v === undefined || v === null) return '-'
  return Number(v).toFixed(digits)
}

function formatPercent(v: number | undefined): string {
  if (v === undefined || v === null) return '-'
  return (Number(v) * 100).toFixed(1) + '%'
}

const verdictLabelMap: Record<string, { label: string; cls: string }> = {
  pass: { label: '通过', cls: 'bg-green-100 text-green-700' },
  pass_with_fixes: { label: '通过（待修复）', cls: 'bg-yellow-100 text-yellow-700' },
  fail: { label: '不通过', cls: 'bg-red-100 text-red-700' },
  unaudited: { label: '未审计（降级）', cls: 'bg-orange-100 text-orange-700' },
}

function verdictInfo(v?: string | null) {
  if (!v) return { label: '未知', cls: 'bg-gray-100 text-gray-600' }
  return verdictLabelMap[v] || { label: v, cls: 'bg-gray-100 text-gray-600' }
}

const severityClsMap: Record<string, string> = {
  blocker: 'bg-red-100 text-red-700',
  warning: 'bg-yellow-100 text-yellow-700',
  info: 'bg-blue-100 text-blue-700',
}

const categoryLabelMap: Record<string, string> = {
  timeline: '时间线',
  characterization: '角色刻画',
  worldview: '世界观',
  fact: '事实细节',
  style: '叙事风格',
}

function categoryLabel(c?: string): string {
  if (!c) return '其他'
  return categoryLabelMap[c] || c
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
          <h3 class="text-sm font-semibold">质量报告（双层审计）</h3>
          <div class="flex items-center gap-2">
            <button
              @click="rerunAudit"
              :disabled="isRerunning"
              class="px-2 py-1 text-xs rounded bg-[var(--accent-500)] text-white hover:opacity-90 disabled:opacity-50"
            >
              {{ isRerunning ? '审计中...' : '重新审计' }}
            </button>
            <button @click="emit('close')" class="text-[var(--text-muted)] hover:text-[var(--text-primary)]">✕</button>
          </div>
        </div>

        <div class="p-4 overflow-y-auto">
          <div v-if="isLoading" class="text-center py-8 text-[var(--text-muted)] text-sm">加载中...</div>
          <div v-else-if="errorText" class="text-center py-8 text-[var(--text-muted)] text-sm">
            {{ errorText }}
          </div>
          <div v-else-if="!report" class="text-center py-8 text-[var(--text-muted)] text-sm">
            暂无数据
          </div>
          <div v-else class="space-y-4">
            <!-- Verdict 徽章 -->
            <div class="flex items-center gap-3 flex-wrap">
              <span
                class="inline-block px-2 py-1 text-xs font-medium rounded"
                :class="verdictInfo(report.verdict).cls"
              >结论：{{ verdictInfo(report.verdict).label }}</span>
              <span
                v-if="report.degraded"
                class="inline-block px-2 py-1 text-xs rounded bg-orange-100 text-orange-700"
              >降级：{{ report.degraded.reason }}</span>
              <span class="text-xs text-[var(--text-muted)]">
                {{ new Date(report.created_at).toLocaleString() }}
              </span>
            </div>

            <!-- 量化指标卡片 -->
            <div class="grid grid-cols-5 gap-2">
              <div class="p-2 bg-[var(--bg-panel)] rounded text-center">
                <div class="text-[10px] text-[var(--text-muted)]">禁词/千字</div>
                <div class="text-base font-semibold text-[var(--text-primary)]">
                  {{ formatMetric(report.metrics.cliche_hits_per_1k, 2) }}
                </div>
              </div>
              <div class="p-2 bg-[var(--bg-panel)] rounded text-center">
                <div class="text-[10px] text-[var(--text-muted)]">句长 CV</div>
                <div class="text-base font-semibold text-[var(--text-primary)]">
                  {{ formatMetric(report.metrics.sentence_len_cv, 2) }}
                </div>
              </div>
              <div class="p-2 bg-[var(--bg-panel)] rounded text-center">
                <div class="text-[10px] text-[var(--text-muted)]">对话占比</div>
                <div class="text-base font-semibold text-[var(--text-primary)]">
                  {{ formatPercent(report.metrics.dialogue_ratio) }}
                </div>
              </div>
              <div class="p-2 bg-[var(--bg-panel)] rounded text-center">
                <div class="text-[10px] text-[var(--text-muted)]">字数达标</div>
                <div class="text-base font-semibold text-[var(--text-primary)]">
                  {{ formatPercent(report.metrics.word_achieve_rate) }}
                </div>
              </div>
              <div class="p-2 bg-[var(--bg-panel)] rounded text-center">
                <div class="text-[10px] text-[var(--text-muted)]">红线违反</div>
                <div
                  class="text-base font-semibold"
                  :class="(report.metrics.red_line_violations ?? 0) > 0 ? 'text-red-500' : 'text-green-500'"
                >
                  {{ report.metrics.red_line_violations ?? 0 }}
                </div>
              </div>
            </div>

            <!-- Findings 列表 -->
            <div>
              <div class="text-xs text-[var(--text-muted)] mb-2">
                发现（{{ report.findings.length }} 条）
              </div>
              <div v-if="report.findings.length === 0" class="text-center py-4 text-[var(--text-muted)] text-xs">
                无发现（双层审计均通过）
              </div>
              <div v-else class="space-y-2">
                <div
                  v-for="(f, idx) in report.findings"
                  :key="idx"
                  class="p-2 border border-[var(--border-color)] rounded text-xs"
                >
                  <div class="flex items-center gap-2 mb-1 flex-wrap">
                    <span
                      class="inline-block px-1.5 py-0.5 text-[10px] rounded font-medium"
                      :class="severityClsMap[f.severity] || 'bg-gray-100 text-gray-600'"
                    >{{ f.severity }}</span>
                    <span class="inline-block px-1.5 py-0.5 text-[10px] rounded bg-[var(--bg-panel)] text-[var(--text-secondary)]">
                      {{ categoryLabel(f.category) }}
                    </span>
                    <span v-if="f.beat_id !== null && f.beat_id !== undefined" class="text-[10px] text-[var(--text-muted)]">
                      Beat {{ f.beat_id }}
                    </span>
                    <span v-if="f.offset" class="text-[10px] text-[var(--text-muted)]">
                      偏移 [{{ f.offset[0] }}, {{ f.offset[1] }}]
                    </span>
                  </div>
                  <div class="text-[var(--text-primary)]">{{ f.detail }}</div>
                  <div v-if="f.quote" class="mt-1 text-[var(--text-muted)] italic">
                    「{{ f.quote }}」
                  </div>
                  <div v-if="f.suggestion" class="mt-1 text-green-700">
                    建议：{{ f.suggestion }}
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </Teleport>
</template>
