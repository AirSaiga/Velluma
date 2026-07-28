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
    tier_classifying: { label: '准备中', icon: '◌', color: '#3b82f6' },
    tier_decided: { label: '篇幅已定', icon: '●', color: '#10b981' },
    setup_growing: { label: '梳理脉络', icon: '◌', color: '#3b82f6' },
    setup_ready: { label: '脉络就绪', icon: '●', color: '#10b981' },
    zone_writing: { label: '写作中', icon: '✎', color: '#f59e0b' },
    climax_writing: { label: '写高潮', icon: '✎', color: '#dc2626' },
    climax_ready: { label: '高潮就绪', icon: '●', color: '#10b981' },
    assembling: { label: '拼接全文', icon: '◌', color: '#3b82f6' },
    auditing: { label: '结构检查', icon: '🔍', color: '#8b5cf6' },
    refining: { label: '润色', icon: '✎', color: '#f59e0b' },
    // BS-ADF 专属阶段
    beat_pending: { label: '分镜编辑', icon: '✎', color: '#f59e0b' },
    beat_rendering: { label: '渲染中', icon: '✎', color: '#f59e0b' },
    beat_stepping: { label: '逐段推进', icon: '⌨', color: '#8b5cf6' },
    done: { label: '完成', icon: '✓', color: '#10b981' },
    error: { label: '失败', icon: '✗', color: '#dc2626' },
  }
  return map[stage.value] || { label: stage.value, icon: '?', color: '#94a3b8' }
})

/** 友好的等待态文案：当处于 BS-ADF 的长耗时阶段（分镜卡扩写）时，
 *  给出更明确的"正在做什么 + 预估耗时"提示，避免用户以为卡死。 */
const waitingHint = computed(() => {
  const label = stepProgress.value?.label || ''
  const p = stepProgress.value
  // 分镜卡扩写阶段：每卡 ~10s
  if (label.includes('分镜卡扩写') && p?.index != null && p?.total) {
    const remaining = Math.max(0, p.total - p.index)
    const eta = remaining * 12  // 预估每卡 12 秒
    return `正在为每段扩写画面焦点与细节（剩余约 ${remaining} 段，预计 ${eta} 秒）`
  }
  // 通用等待
  if (stage.value === 'tier_classifying') {
    return '正在梳理前文脉络、设计本章高潮与定档篇幅…'
  }
  return ''
})
</script>

<template>
  <div class="generation-overlay">
    <div class="overlay-card">
      <!-- 阶段标识 -->
      <div class="stage-row" :style="{ color: stageDisplay.color }">
        <span class="stage-icon" :class="{ spin: stage.includes('writing') || stage === 'refining' || stage === 'tier_classifying' || stage === 'beat_rendering' || stage === 'beat_stepping' }">
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

      <!-- 等待态文案：BS-ADF 长耗时阶段显示具体在做什么 + 预估耗时 -->
      <div v-else-if="stage !== 'error'" class="word-count muted">
        {{ waitingHint || 'AI 正在思考…' }}
      </div>

      <!-- NLE-ADF：实时正文流（非遮挡） -->
      <div
        v-if="streamTextLen > 0 || Object.keys(session.segmentTexts.value).length > 0"
        class="live-text-area"
      >
        <div class="live-text-label">实时正文</div>
        <div class="live-text-content">
          <template v-if="stage === 'beat_stepping' || stage === 'beat_rendering'">
            <div
              v-for="slot in session.beatSlots.value"
              :key="slot.beat_id"
              class="segment-block"
              :class="{
                'is-locked': session.lockedBeatIds.value.has(slot.beat_id),
                'is-ready': session.readyBeatId.value === slot.beat_id,
                'is-rendering': session.renderingBeatId.value === slot.beat_id,
              }"
            >
              <div class="segment-label">
                段 {{ slot.segment_index + 1 }}
                <span v-if="session.lockedBeatIds.value.has(slot.beat_id)">🔒</span>
                <span v-else-if="session.readyBeatId.value === slot.beat_id">⏎ Space</span>
              </div>
              <div class="segment-text">{{ session.segmentTexts.value[slot.beat_id] || '' }}</div>
            </div>
          </template>
          <template v-else>
            {{ session.streamText.value }}
          </template>
        </div>
      </div>

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
  position: relative;
  inset: auto;
  z-index: 10;
  display: flex;
  flex-direction: column;
  align-items: stretch;
  justify-content: flex-start;
  background: var(--bg-secondary);
  border-top: 1px solid var(--border-color);
  padding: 12px 16px;
  max-height: 280px;
  overflow-y: auto;
}

.overlay-card {
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: 0.75rem;
  padding: 0;
  text-align: left;
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

/* NLE-ADF：实时正文流（非遮挡） */
.live-text-area {
  margin-top: 0.5rem;
  border-top: 1px dashed var(--border-color);
  padding-top: 0.5rem;
}
.live-text-label {
  font-size: 0.75rem;
  color: var(--text-secondary);
  margin-bottom: 0.25rem;
}
.live-text-content {
  font-size: 0.875rem;
  line-height: 1.7;
  white-space: pre-wrap;
  max-height: 200px;
  overflow-y: auto;
}
.segment-block {
  margin-bottom: 0.75rem;
  padding: 0.5rem;
  border-radius: 0.25rem;
}
.segment-block.is-locked {
  background: var(--bg-primary);
  opacity: 0.85;
}
.segment-block.is-ready {
  background: color-mix(in srgb, var(--accent-500, #4f46e5) 12%, transparent);
  border-left: 3px solid var(--accent-500, #4f46e5);
}
.segment-block.is-rendering {
  opacity: 0.6;
}
.segment-label {
  font-size: 0.6875rem;
  color: var(--text-secondary);
  margin-bottom: 0.25rem;
}
.segment-text {
  font-size: 0.875rem;
}
</style>
