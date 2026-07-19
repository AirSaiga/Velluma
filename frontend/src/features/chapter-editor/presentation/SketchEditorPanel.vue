<script setup lang="ts">
import { ref, watch, toRef, computed } from 'vue'
import { useFocusTrap } from '../../../composables/useFocusTrap'
import type { SketchSegment, SketchEmotionPoint } from '../../../types'

const props = defineProps<{
  show: boolean
  segments: SketchSegment[]
  emotionArc?: SketchEmotionPoint[]
  sketchTextPreview?: string
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'confirm', editedSegments: SketchSegment[] | null): void
}>()

const modalRef = ref<HTMLElement | null>(null)
const showRef = toRef(props, 'show')
useFocusTrap(modalRef, showRef, { onEscape: () => emit('close') })

// 本地可编辑副本（深拷贝，避免直接改 props）
const editableSegments = ref<SketchSegment[]>([])

watch(
  () => [props.show, props.segments],
  ([newShow, newSegs]) => {
    if (newShow && Array.isArray(newSegs)) {
      // 深拷贝 segments 供编辑
      editableSegments.value = (newSegs as SketchSegment[]).map(s => ({ ...s }))
    }
  },
  { immediate: true, deep: true }
)

const hasSegments = computed(() => editableSegments.value.length > 0)

const emotionLabel = (point: SketchEmotionPoint): string => {
  const parts: string[] = []
  if (point.beat_index !== undefined) parts.push(`拍${point.beat_index}`)
  if (point.emotion) parts.push(String(point.emotion))
  if (point.intensity !== undefined) parts.push(`强度 ${point.intensity}`)
  return parts.join(' · ') || JSON.stringify(point)
}

function confirmWithEdits() {
  // 用户编辑后的 segments（仅 text + transition_to_next 可能被改）
  emit('confirm', editableSegments.value.slice())
}

function confirmWithOriginal() {
  // 使用原始骨架（null 表示不覆盖）
  emit('confirm', null)
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
      <div class="bg-[var(--bg-primary)] rounded-2xl shadow-2xl w-full max-w-3xl max-h-[85vh] overflow-hidden flex flex-col">
        <div class="p-3 border-b border-[var(--border-color)] flex items-center justify-between">
          <div>
            <h3 class="text-sm font-semibold">速写骨架编辑（CP4.2）</h3>
            <p class="text-[10px] text-[var(--text-muted)] mt-0.5">
              生成主流程开始前的速写骨架。可编辑每段叙述与衔接句，确认后用于本拍扩写参考。
            </p>
          </div>
          <button @click="emit('close')" class="text-[var(--text-muted)] hover:text-[var(--text-primary)]">✕</button>
        </div>

        <div class="p-4 overflow-y-auto flex-1">
          <div v-if="!hasSegments" class="text-center py-8 text-[var(--text-muted)] text-sm">
            暂无速写骨架数据（可能未启用 sketch 先行模式或生成失败）
          </div>

          <div v-else class="space-y-3">
            <!-- 情绪曲线（只读） -->
            <div v-if="emotionArc && emotionArc.length > 0" class="p-2 bg-[var(--bg-panel)] rounded">
              <div class="text-[10px] text-[var(--text-muted)] mb-1">情绪曲线（只读参考）</div>
              <div class="flex flex-wrap gap-1.5">
                <span
                  v-for="(point, idx) in emotionArc"
                  :key="idx"
                  class="inline-block px-1.5 py-0.5 text-[10px] rounded bg-[var(--bg-primary)] border border-[var(--border-color)] text-[var(--text-secondary)]"
                >{{ emotionLabel(point) }}</span>
              </div>
            </div>

            <!-- 全文预览（只读） -->
            <div v-if="sketchTextPreview" class="p-2 bg-[var(--bg-panel)] rounded">
              <div class="text-[10px] text-[var(--text-muted)] mb-1">速写全文预览（前 600 字，只读）</div>
              <div class="text-xs text-[var(--text-secondary)] italic line-clamp-3">{{ sketchTextPreview }}</div>
            </div>

            <!-- 分段编辑列表 -->
            <div>
              <div class="text-xs text-[var(--text-muted)] mb-2">
                分段（{{ editableSegments.length }} 段，可编辑 text + 衔接句）
              </div>
              <div class="space-y-2">
                <div
                  v-for="(seg, idx) in editableSegments"
                  :key="idx"
                  class="p-2 border border-[var(--border-color)] rounded"
                >
                  <div class="flex items-center gap-2 mb-1.5">
                    <span class="inline-block px-1.5 py-0.5 text-[10px] rounded bg-accent-50 text-accent-600 font-medium">
                      拍 {{ seg.beat_index }}
                    </span>
                    <span v-if="seg.beat_id" class="text-[10px] text-[var(--text-muted)]">{{ seg.beat_id }}</span>
                  </div>
                  <textarea
                    v-model="seg.text"
                    rows="3"
                    class="w-full text-xs border border-[var(--border-color)] rounded px-2 py-1.5 outline-none focus:border-[var(--accent-600)] resize-y bg-[var(--bg-canvas)] text-[var(--text-primary)]"
                    placeholder="本拍骨架叙述（主干动作与转折）"
                  />
                  <div class="mt-1.5">
                    <div class="text-[10px] text-[var(--text-muted)] mb-0.5">衔接句（到下一拍）</div>
                    <textarea
                      v-model="seg.transition_to_next"
                      rows="1"
                      class="w-full text-xs border border-[var(--border-color)] rounded px-2 py-1 outline-none focus:border-[var(--accent-600)] resize-y bg-[var(--bg-canvas)] text-[var(--text-secondary)]"
                      placeholder="可选：到下一拍的衔接句原文"
                    />
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <div class="p-3 border-t border-[var(--border-color)] flex items-center justify-end gap-2">
          <button
            @click="confirmWithOriginal"
            class="px-3 py-1.5 text-xs rounded-md bg-parchment-100 text-ink-600 hover:bg-parchment-200 transition-colors"
            title="使用原始骨架，不覆盖"
          >
            使用原始骨架
          </button>
          <button
            @click="confirmWithEdits"
            :disabled="!hasSegments"
            class="px-3 py-1.5 text-xs rounded-md bg-accent-600 text-white hover:bg-accent-500 transition-colors disabled:opacity-40"
            title="使用编辑后的骨架"
          >
            确认使用编辑后骨架
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>
