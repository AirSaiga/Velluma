<script setup lang="ts">
/**
 * 生成步骤流（V3.1 F3 新建，规格 §5.1）。
 *
 * 嵌入右栏「本章」tab，非模态呈现生成流程的当前阶段。
 * 按档位自动开合三确认点（高潮点/铺垫结构/高潮段成稿）。
 *
 * 显示：
 * - 定档通知卡（tier + 理由）
 * - 步骤条（当前阶段 + 进度）
 * - 飞行中调节事件通知卡（升档建议/压抑校准/并章建议）
 * - 流式正文进度
 */
import { computed } from 'vue'
import Icon from '../../../components/Icon.vue'
import type { GenerationSession } from '../composables/useGenerationSession'

const props = defineProps<{
  session: GenerationSession
}>()

const emit = defineEmits<{
  (e: 'cancel'): void
  (e: 'accept-tier-upgrade', event: any): void
  (e: 'dismiss-inflight', index: number): void
}>()

const stage = computed(() => props.session.stage.value)
const tierDecision = computed(() => props.session.tierDecision.value)
const stepProgress = computed(() => props.session.stepProgress.value)
const generating = computed(() => props.session.generating.value)
const inflightEvents = computed(() => props.session.inflightEvents.value)
const degraded = computed(() => props.session.degraded.value)

const progressPercent = computed(() => {
  const p = stepProgress.value
  if (!p || !p.total || p.index == null) return null
  return Math.round(((p.index - 1) / p.total) * 100)
})

function tierChinese(tier?: string): string {
  switch (tier) {
    case 'climax': return '高潮章'
    case 'turn': return '转折章'
    case 'progress': return '推进章'
    case 'transition': return '过渡章'
    default: return tier || ''
  }
}

function inflightLabel(type: string): string {
  switch (type) {
    case 'climax_rewrite': return '高潮段重写'
    case 'over_suppressed_detected': return '压抑校准'
    case 'premature_suspicion_detected': return '泄底检查'
    case 'merge_suggestion': return '并章建议'
    case 'tier_upgrade_suggest': return '升档建议'
    default: return type
  }
}
</script>

<template>
  <div class="generation-stepper">
    <!-- 定档通知卡 -->
    <div v-if="tierDecision" class="tier-card">
      <div class="tier-header">
        <span class="tier-dot" :class="tierDecision.tier"></span>
        <span class="tier-name">{{ tierChinese(tierDecision.tier) }}</span>
      </div>
      <p class="tier-reason">{{ tierDecision.reason }}</p>
      <div v-if="tierDecision.climax_score != null" class="tier-meta">
        高潮强度 {{ tierDecision.climax_score }}/10
      </div>
    </div>

    <!-- 步骤条 -->
    <div v-if="generating || stage === 'done'" class="step-bar">
      <div class="step-header">
        <Icon
          :name="stage === 'done' ? 'check' : 'arrow-path'"
          :size="14"
          :class="{ 'spin': generating }"
        />
        <span class="step-label">
          {{ stage === 'done' ? '生成完成' : stepProgress?.label || '处理中…' }}
        </span>
        <span v-if="stepProgress?.index && stepProgress?.total" class="step-count">
          {{ stepProgress.index }}/{{ stepProgress.total }}
        </span>
      </div>
      <div v-if="progressPercent != null && generating" class="progress-track">
        <div class="progress-fill" :style="{ width: progressPercent + '%' }"></div>
      </div>
    </div>

    <!-- 飞行中调节事件 -->
    <div v-for="(ev, idx) in inflightEvents" :key="idx" class="inflight-card">
      <div class="inflight-header">
        <Icon name="information-circle" :size="13" />
        <span class="inflight-type">{{ inflightLabel(ev.type) }}</span>
      </div>
      <p v-if="ev.reason" class="inflight-reason">{{ ev.reason }}</p>
      <div v-if="ev.suggestion_type === 'merge'" class="inflight-detail">
        {{ ev.detail || '' }}
      </div>
      <div class="inflight-actions">
        <button
          v-if="ev.type === 'tier_upgrade_suggest'"
          class="inflight-btn primary"
          @click="emit('accept-tier-upgrade', ev)"
        >采纳升档</button>
        <button class="inflight-btn" @click="emit('dismiss-inflight', idx)">忽略</button>
      </div>
    </div>

    <!-- 降级事件 -->
    <details v-if="degraded.length > 0" class="degraded-details">
      <summary>{{ degraded.length }} 个降级事件（已兜底）</summary>
      <ul class="degraded-list">
        <li v-for="(d, i) in degraded" :key="i">
          <span class="deg-reason">{{ d.reason }}</span>
          <span class="deg-action">兜底：{{ d.action }}</span>
        </li>
      </ul>
    </details>

    <!-- 取消按钮 -->
    <button v-if="generating" class="btn-cancel" @click="emit('cancel')">
      <Icon name="x-mark" :size="13" />
      <span>取消生成</span>
    </button>
  </div>
</template>

<style scoped>
.generation-stepper {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

/* 定档通知卡 */
.tier-card {
  background: var(--bg-canvas);
  border: 1px solid var(--accent-500);
  border-left-width: 3px;
  border-radius: 0.375rem;
  padding: 0.625rem 0.75rem;
}

.tier-header {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  margin-bottom: 0.25rem;
}

.tier-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--accent-500);
}
.tier-dot.climax { background: #d97706; }
.tier-dot.turn { background: var(--accent-500); }
.tier-dot.progress { background: var(--text-muted); }
.tier-dot.transition { background: var(--text-muted); opacity: 0.5; }

.tier-name {
  font-size: 0.8125rem;
  font-weight: 600;
  color: var(--text-primary);
}

.tier-reason {
  font-size: 0.75rem;
  color: var(--text-secondary);
  line-height: 1.5;
  margin: 0;
}

.tier-meta {
  font-size: 0.6875rem;
  color: var(--text-muted);
  margin-top: 0.25rem;
}

/* 步骤条 */
.step-bar {
  background: var(--bg-canvas);
  border: 1px solid var(--border-color);
  border-radius: 0.375rem;
  padding: 0.5rem 0.625rem;
}

.step-header {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  font-size: 0.75rem;
  color: var(--text-secondary);
}

.step-label {
  flex: 1;
  color: var(--text-primary);
  font-weight: 500;
}

.step-count {
  font-size: 0.6875rem;
  color: var(--text-muted);
  font-variant-numeric: tabular-nums;
}

.spin {
  animation: spin 1.2s linear infinite;
  color: var(--accent-500);
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.progress-track {
  margin-top: 0.375rem;
  height: 2px;
  background: var(--bg-tertiary);
  border-radius: 1px;
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  background: var(--accent-500);
  transition: width 0.3s ease;
}

/* 飞行中调节 */
.inflight-card {
  background: var(--bg-canvas);
  border: 1px solid var(--border-color);
  border-left: 3px solid #d97706;
  border-radius: 0.375rem;
  padding: 0.5rem 0.625rem;
}

.inflight-header {
  display: flex;
  align-items: center;
  gap: 0.25rem;
  color: #d97706;
  font-size: 0.75rem;
  font-weight: 500;
}

.inflight-reason,
.inflight-detail {
  font-size: 0.6875rem;
  color: var(--text-secondary);
  line-height: 1.5;
  margin: 0.25rem 0 0;
}

.inflight-actions {
  display: flex;
  gap: 0.375rem;
  margin-top: 0.375rem;
}

.inflight-btn {
  font-size: 0.6875rem;
  padding: 0.1875rem 0.5rem;
  background: transparent;
  border: 1px solid var(--border-color);
  border-radius: 0.1875rem;
  color: var(--text-secondary);
  cursor: pointer;
}
.inflight-btn:hover {
  background: var(--hover-bg);
}
.inflight-btn.primary {
  background: var(--accent-500);
  color: white;
  border-color: var(--accent-500);
}

/* 降级事件 */
.degraded-details {
  font-size: 0.6875rem;
  color: var(--text-muted);
}
.degraded-details summary {
  cursor: pointer;
  padding: 0.25rem 0;
}
.degraded-list {
  list-style: none;
  padding: 0;
  margin: 0.25rem 0 0;
  display: flex;
  flex-direction: column;
  gap: 0.1875rem;
}
.degraded-list li {
  font-size: 0.625rem;
  display: flex;
  gap: 0.375rem;
}
.deg-reason { color: #dc2626; }
.deg-action { color: var(--text-muted); }

/* 取消按钮 */
.btn-cancel {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  padding: 0.3125rem 0.625rem;
  font-size: 0.6875rem;
  background: transparent;
  border: 1px solid var(--border-color);
  border-radius: 0.25rem;
  color: var(--text-secondary);
  cursor: pointer;
  align-self: flex-start;
}
.btn-cancel:hover {
  color: #dc2626;
  border-color: #dc2626;
}
</style>
