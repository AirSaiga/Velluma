<script setup lang="ts">
/**
 * 文风页顶部常驻状态条（设计稿 §6.2：一句话总结 + [▶ 试听]）。
 *
 * 用一句话回答「我的文风现在是什么状态」——样本规模 / 句长起伏健康度 /
 * 对话占比 / 负面清单生效数，全部来自实测指纹（纯算法，非 AI 猜测）。
 * sticky 钉在滚动列顶部；▶ 试听点击后由容器滚动到试听横条。
 */
import { computed } from 'vue'

const props = defineProps<{
  sampleCount: number
  /** 语料聚合指纹（无样本时为 null） */
  cv: number | null
  cvHealthy: [number, number] | null
  dialogueRatio: number | null
  negativeCount: number
}>()

const emit = defineEmits<{
  (e: 'audition'): void
}>()

const line = computed(() => {
  const parts: string[] = []
  if (props.sampleCount > 0) parts.push(`已测 ${props.sampleCount} 条样本`)
  if (props.cv !== null && props.cvHealthy) {
    const [lo, hi] = props.cvHealthy
    const tag = props.cv < lo ? '偏匀速' : props.cv > hi ? '偏跳' : '健康'
    parts.push(`句长起伏 ${props.cv.toFixed(2)}（${tag}）`)
  }
  if (props.dialogueRatio !== null && props.dialogueRatio > 0) {
    parts.push(`对话占比 ${Math.round(props.dialogueRatio * 100)}%`)
  }
  if (props.negativeCount > 0) parts.push(`负面清单 ${props.negativeCount} 条生效`)
  return parts.join(' · ')
})

const fallback = '还没有可总结的笔迹——在「你的字」贴入样本后，这里会用一句话告诉你文风的状态。'
</script>

<template>
  <aside class="status-strip">
    <span class="status-text">{{ line || fallback }}</span>
    <button class="status-audition" title="跳到试听横条——调了看得见" @click="emit('audition')">
      ▶ 试听
    </button>
  </aside>
</template>

<style scoped>
.status-strip {
  position: sticky;
  top: 0;
  z-index: var(--z-sticky);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  padding: 0.4375rem 0.25rem;
  background: color-mix(in srgb, var(--bg-canvas) 88%, transparent);
  backdrop-filter: blur(4px);
  border-bottom: 1px solid var(--border-color);
}
.status-text {
  overflow: hidden;
  font-size: var(--text-sm);
  white-space: nowrap;
  text-overflow: ellipsis;
  color: var(--text-secondary);
}
.status-audition {
  flex-shrink: 0;
  min-height: 28px;
  padding: 0.1875rem 0.625rem;
  font-size: var(--text-xs);
  color: var(--accent-500);
  background: transparent;
  border: 1px solid color-mix(in srgb, var(--accent-500) 35%, var(--border-color));
  border-radius: 999px;
  cursor: pointer;
}
.status-audition:hover {
  color: white;
  background: var(--accent-500);
  border-color: var(--accent-500);
}
</style>
