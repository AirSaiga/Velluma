<script setup lang="ts">
/**
 * 生成覆盖面板（V4.x 重构）。
 *
 * 职责：生成进行中以绝对定位覆盖在中栏编辑器区域上方，显示阶段进度，
 * 物理遮挡编辑器使其不可操作。生成完成后面板消失，正文已灌入编辑器。
 *
 * 不显示正文（仅字数）；详细统计/精修/反馈统一去右栏 Inspector 查看。
 *
 * 数据源：useGenerationSession 的状态。
 */
import { computed } from 'vue'
import Icon from '../../../components/Icon.vue'
import type { GenerationSession } from '../composables/useGenerationSession'

const props = defineProps<{
  session: GenerationSession
}>()

const emit = defineEmits<{
  (e: 'cancel'): void
  (e: 'retry'): void
}>()

const stage = computed(() => props.session.stage.value)
const stepProgress = computed(() => props.session.stepProgress.value)
const errorText = computed(() => props.session.error.value)
const streamTextLen = computed(() => props.session.streamText.value.length)

const progressPercent = computed(() => {
  const p = stepProgress.value
  if (!p || !p.total || p.index == null) return null
  return Math.round((p.index / p.total) * 100)
})

/** 阶段映射为展示标签 + 配色 */
const stageDisplay = computed(() => {
  const map: Record<string, { label: string; icon: string; color: string }> = {
    idle: { label: '待命', icon: '○', color: '#94a3b8' },
    tier_classifying: { label: '分析中', icon: '◌', color: '#3b82f6' },
    tier_decided: { label: '篇幅已定', icon: '●', color: '#10b981' },
    setup_growing: { label: '梳理脉络', icon: '◌', color: '#3b82f6' },
    setup_ready: { label: '脉络就绪', icon: '●', color: '#10b981' },
    zone_writing: { label: '写作中', icon: '✎', color: '#f59e0b' },
    climax_writing: { label: '写高潮', icon: '✎', color: '#dc2626' },
    climax_ready: { label: '高潮就绪', icon: '●', color: '#10b981' },
    assembling: { label: '拼接全文', icon: '◌', color: '#3b82f6' },
    auditing: { label: '结构检查', icon: '🔍', color: '#8b5cf6' },
    refining: { label: '润色', icon: '✎', color: '#f59e0b' },
    done: { label: '完成', icon: '✓', color: '#10b981' },
    error: { label: '失败', icon: '✗', color: '#dc2626' },
  }
  return map[stage.value] || { label: stage.value, icon: '?', color: '#94a3b8' }
})
</script>

<template>
  <div class="generation-overlay">
    <div class="overlay-card">
      <!-- 阶段标识 -->
      <div class="stage-row" :style="{ color: stageDisplay.color }">
        <span class="stage-icon" :class="{ spin: stage.includes('writing') || stage === 'refining' }">
          {{ stageDisplay.icon }}
        </span>
        <span class="stage-label">{{ stageDisplay.label }}</span>
        <span v-if="stepProgress?.label" class="stage-step">· {{ stepProgress.label }}</span>
      </div>

      <!-- 进度条 -->
      <div v-if="progressPercent != null" class="progress-wrap">
        <div class="progress-track">
          <div class="progress-fill" :style="{ width: progressPercent + '%' }"></div>
        </div>
        <span class="progress-text">
          {{ stepProgress?.index || 0 }} / {{ stepProgress?.total }} 段
        </span>
      </div>

      <!-- 流式字数（不显示正文） -->
      <div v-if="streamTextLen > 0" class="word-count">
        已生成 {{ streamTextLen }} 字
      </div>

      <!-- 等待态文案 -->
      <div v-else-if="stage !== 'error'" class="word-count muted">AI 正在思考…</div>

      <!-- 失败态：错误文案 + 重试（error 原文可能已被 toast watcher 消费，给兜底文案） -->
      <div v-if="stage === 'error'" class="error-text">
        {{ errorText || '生成或精修过程出错，请重试。' }}
      </div>
      <button v-if="stage === 'error'" class="btn-retry" @click="emit('retry')">
        <Icon name="arrow-path" :size="13" />
        <span>重试</span>
      </button>

      <!-- 取消按钮（失败态下作为关闭面板） -->
      <button class="btn-cancel" @click="emit('cancel')">
        <Icon name="x-mark" :size="13" />
        <span>{{ stage === 'error' ? '关闭' : '取消生成' }}</span>
      </button>
    </div>
  </div>
</template>

<style scoped>
.generation-overlay {
  position: absolute;
  inset: 0;
  z-index: 20;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--bg-primary);
  background: color-mix(in srgb, var(--bg-primary) 82%, transparent);
  backdrop-filter: blur(4px);
}

.overlay-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 1rem;
  padding: 2.5rem 3rem;
  text-align: center;
}

/* 阶段标识 */
.stage-row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 1.125rem;
  font-weight: 600;
}
.stage-icon {
  font-size: 1.5rem;
  line-height: 1;
}
.stage-icon.spin {
  animation: spin 1.5s linear infinite;
  display: inline-block;
}
@keyframes spin {
  to { transform: rotate(360deg); }
}
.stage-step {
  color: var(--text-muted);
  font-weight: 400;
  font-size: 0.9375rem;
}

/* 进度条 */
.progress-wrap {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.375rem;
  width: 280px;
}
.progress-track {
  width: 100%;
  height: 4px;
  background: var(--bg-tertiary);
  border-radius: 2px;
  overflow: hidden;
}
.progress-fill {
  height: 100%;
  background: var(--accent-500);
  border-radius: 2px;
  transition: width 0.4s ease;
}
.progress-text {
  font-size: 0.75rem;
  color: var(--text-muted);
  font-variant-numeric: tabular-nums;
}

/* 字数 */
.word-count {
  font-size: 0.8125rem;
  color: var(--text-secondary);
}
.word-count.muted {
  color: var(--text-muted);
}

/* 失败态 */
.error-text {
  max-width: 320px;
  font-size: 0.8125rem;
  color: #dc2626;
  line-height: 1.6;
  word-break: break-word;
}

.btn-retry {
  display: inline-flex;
  align-items: center;
  gap: 0.375rem;
  padding: 0.4375rem 1.25rem;
  font-size: 0.75rem;
  font-weight: 500;
  background: var(--accent-500);
  color: white;
  border: none;
  border-radius: 0.375rem;
  cursor: pointer;
  transition: background 0.15s ease;
}
.btn-retry:hover {
  background: var(--accent-600);
}

/* 取消按钮 */
.btn-cancel {
  display: inline-flex;
  align-items: center;
  gap: 0.375rem;
  padding: 0.4375rem 1rem;
  font-size: 0.75rem;
  background: transparent;
  border: 1px solid var(--border-color);
  border-radius: 0.375rem;
  color: var(--text-secondary);
  cursor: pointer;
  transition: all 0.15s ease;
}
.btn-cancel:hover {
  color: #dc2626;
  border-color: #dc2626;
}
</style>
