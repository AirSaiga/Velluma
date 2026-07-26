<script setup lang="ts">
/**
 * BS-ADF 降级段占位符（V5 新建）。
 *
 * 职责：渲染过程中某段多次失败降级后，在结果中显示一个虚线黄框占位，
 * 提供两个动作：
 * - 重新渲染（rerender）：调用 rerenderBeat 重试该段
 * - 跳过（skip）：保留占位，继续看其他段
 *
 * 视觉语言：虚线琥珀色边框，照搬现有 .empty-inline 的虚线风格。
 */
import { computed } from 'vue'
import type { DegradedBeat, BeatSlot } from '../../../services/api/domain'

const props = defineProps<{
  degraded: DegradedBeat
  /** 槽位卡句柄：Track B confirm 后 beatSlots 已清空，DB slot 可能过期，
   *  找不到时为 undefined——此时只显示「跳过」按钮（rerender 需要 slot 数据）。 */
  slot?: BeatSlot
}>()

const emit = defineEmits<{
  (e: 'rerender', slot: BeatSlot): void
  (e: 'skip'): void
}>()

const REASON_LABEL: Record<string, string> = {
  ai_smell: 'AI 腔过重',
  coverage_fail: '锚点覆盖不足',
  gate_fail: '质检未通过',
  llm_error: '模型调用错误',
}

const reasonLabel = computed(() => REASON_LABEL[props.degraded.reason] || props.degraded.reason)
</script>

<template>
  <div class="degraded-placeholder">
    <div class="dp-head">
      <span class="dp-icon">⚠</span>
      <span class="dp-seg">段 {{ degraded.segment_index + 1 }} 降级</span>
    </div>
    <div class="dp-reason">
      原因：{{ reasonLabel }}（已尝试 {{ degraded.attempts }} 次）
    </div>
    <div class="dp-summary" v-if="slot">
      <span class="dp-type">{{ slot.beat_type }}</span>
      <span class="dp-target">{{ slot.target_word_count }} 字目标</span>
    </div>
    <div class="dp-actions">
      <button class="dp-btn primary" :disabled="!slot" @click="slot && emit('rerender', slot)">
        重新渲染
      </button>
      <button class="dp-btn" @click="emit('skip')">跳过</button>
    </div>
  </div>
</template>

<style scoped>
.degraded-placeholder {
  padding: 0.625rem 0.75rem;
  border: 1px dashed #d97706;
  border-radius: 0.5rem;
  background: rgba(217, 119, 6, 0.05);
}
.dp-head {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  font-size: 0.75rem;
  font-weight: 500;
  color: #92400e;
  margin-bottom: 0.25rem;
}
.dp-icon { font-size: 0.875rem; }
.dp-reason {
  font-size: 0.6875rem;
  color: var(--text-muted);
  margin-bottom: 0.375rem;
}
.dp-summary {
  display: flex;
  gap: 0.5rem;
  font-size: 0.6875rem;
  color: var(--text-secondary);
  margin-bottom: 0.5rem;
}
.dp-type {
  padding: 0.0625rem 0.375rem;
  background: var(--hover-bg);
  border-radius: 0.25rem;
}
.dp-target { color: var(--text-muted); }

.dp-actions {
  display: flex;
  gap: 0.375rem;
}
.dp-btn {
  padding: 0.25rem 0.625rem;
  font-size: 0.6875rem;
  border: 1px solid var(--border-color);
  background: var(--bg-secondary);
  color: var(--text-primary);
  border-radius: 0.25rem;
  cursor: pointer;
}
.dp-btn:hover { opacity: 0.85; }
.dp-btn.primary {
  background: var(--accent-500);
  color: white;
  border-color: var(--accent-500);
}
.dp-btn.primary:hover { background: var(--accent-600); }
</style>
