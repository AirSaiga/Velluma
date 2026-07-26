<script setup lang="ts">
/**
 * BS-ADF 渲染进度可视化（V5 新建）。
 *
 * 职责：渲染阶段（Track A 全程 / Track B confirm 后到 done 前）显示
 * - 每段渲染状态（rendering / rendered / degraded）
 * - 降级段汇总
 * - 当前 stage 提示（来自 session.stepProgress.label）
 *
 * 照搬 RefineryProgress 的结构与视觉语言。
 */
import { computed } from 'vue'
import type { RenderProgress, DegradedBeat } from '../../../services/api/domain'

const props = defineProps<{
  progress: RenderProgress[]
  degraded: DegradedBeat[]
  stageLabel: string
}>()

const totalRendered = computed(() => props.progress.filter(p => p.status === 'rendered').length)
const totalRendering = computed(() => props.progress.filter(p => p.status === 'rendering').length)
const totalDegraded = computed(() => props.progress.filter(p => p.status === 'degraded').length)

const isBusy = computed(() => totalRendering.value > 0 || props.progress.length === 0)

function statusIcon(status: string): string {
  if (status === 'rendered') return '✓'
  if (status === 'rendering') return '⟳'
  if (status === 'degraded') return '⚠'
  return '○'
}

const degradedReasonLabel: Record<string, string> = {
  ai_smell: 'AI 腔',
  coverage_fail: '覆盖不足',
  gate_fail: '质检未过',
  llm_error: '模型错误',
}
</script>

<template>
  <div class="beat-progress">
    <header class="bp-header">
      <div class="bp-stage">
        <span class="bp-spinner" v-if="isBusy">⟳</span>
        <span class="bp-stage-label">{{ stageLabel || '渲染中' }}</span>
      </div>
      <div class="bp-stats" v-if="progress.length">
        {{ totalRendered }} 完成
        <span v-if="totalRendering">· {{ totalRendering }} 渲染中</span>
        <span v-if="totalDegraded">· {{ totalDegraded }} 降级</span>
        / 共 {{ progress.length }}
      </div>
    </header>

    <!-- 段列表 -->
    <div class="beat-list" v-if="progress.length">
      <div
        v-for="(p, idx) in progress"
        :key="p.beat_id || idx"
        class="beat-item"
        :class="`status-${p.status}`"
      >
        <div class="beat-head">
          <span class="beat-seg">段 {{ p.segment_index + 1 }}</span>
          <span class="beat-status-icon" :class="`icon-${p.status}`">
            {{ statusIcon(p.status) }}
          </span>
        </div>
        <div class="beat-meta">
          <span v-if="p.word_count" class="word-count">{{ p.word_count }} 字</span>
          <span v-if="p.status === 'degraded' && p.reason" class="degraded-reason">
            {{ degradedReasonLabel[p.reason] || p.reason }}
          </span>
        </div>
      </div>
    </div>

    <!-- 等待状态（已有 stageLabel 但首个 progress 还没到） -->
    <div v-else class="bp-waiting">
      <span class="bp-spinner">⟳</span>
      <span>{{ stageLabel || '准备中…' }}</span>
    </div>

    <!-- 降级汇总 -->
    <div v-if="degraded.length" class="degraded-card">
      <div class="degraded-head">
        <span>⚠ 降级段（{{ degraded.length }}）</span>
      </div>
      <div class="degraded-list">
        <div
          v-for="(d, i) in degraded"
          :key="d.beat_id || i"
          class="degraded-item"
        >
          段 {{ d.segment_index + 1 }}：{{ degradedReasonLabel[d.reason] || d.reason }}（尝试 {{ d.attempts }} 次）
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.beat-progress {
  padding: 0.75rem;
  background: var(--bg-secondary);
  border-radius: 0.5rem;
  border-left: 3px solid var(--accent-500);
}
.bp-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 0.5rem;
}
.bp-stage {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  font-size: 0.8125rem;
  font-weight: 500;
}
.bp-spinner {
  display: inline-block;
  animation: bp-spin 1.2s linear infinite;
  color: var(--accent-500);
}
@keyframes bp-spin {
  to { transform: rotate(360deg); }
}
.bp-stats { font-size: 0.6875rem; color: var(--text-muted); }

.beat-list {
  display: flex;
  flex-direction: column;
  gap: 0.375rem;
  margin-bottom: 0.5rem;
}
.beat-item {
  padding: 0.5rem 0.625rem;
  background: var(--bg-primary);
  border-radius: 0.375rem;
  border-left: 2px solid var(--text-muted);
}
.beat-item.status-rendering { border-left-color: var(--accent-500); }
.beat-item.status-rendered { border-left-color: #16a34a; }
.beat-item.status-degraded { border-left-color: #d97706; }
.beat-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 0.125rem;
}
.beat-seg { font-size: 0.6875rem; color: var(--text-muted); }
.beat-status-icon { font-size: 0.75rem; font-weight: 600; }
.beat-status-icon.icon-rendered { color: #16a34a; }
.beat-status-icon.icon-rendering { color: var(--accent-500); }
.beat-status-icon.icon-degraded { color: #d97706; }
.beat-meta {
  font-size: 0.6875rem;
  color: var(--text-muted);
  display: flex;
  gap: 0.5rem;
}
.beat-meta .degraded-reason { color: #d97706; }

.bp-waiting {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 1rem;
  color: var(--text-muted);
  font-size: 0.75rem;
}

.degraded-card {
  margin-top: 0.5rem;
  padding: 0.5rem 0.625rem;
  background: var(--bg-primary);
  border-radius: 0.375rem;
  border-left: 2px solid #d97706;
}
.degraded-head {
  font-size: 0.75rem;
  margin-bottom: 0.25rem;
  color: #92400e;
}
.degraded-list { font-size: 0.6875rem; color: var(--text-muted); }
.degraded-item { line-height: 1.5; }
</style>
