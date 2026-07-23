<script setup lang="ts">
/**
 * 精修进度可视化（V4.1 Refinery Progress，问题 5 修复）。
 *
 * 职责：精修阶段（confirmRefinery 后到 done 前）显示手术进度
 * - 每个手术一行（operation_id + diff_summary + applied 状态）
 * - 整体回读结论
 * - 当前 stage 提示（SURGERY / REREAD / POLISH）
 */
import { computed } from 'vue'
import type { RefinerySurgery, RefineryHolisticVerdict } from '../../../services/api/domain'

const props = defineProps<{
  surgeries: RefinerySurgery[]
  holisticVerdict: RefineryHolisticVerdict | null
  stageLabel: string  // 来自 session.stepProgress.label
  stage: string       // session.stage.value
}>()

const totalApplied = computed(() => props.surgeries.filter(s => s.applied).length)
const totalFailed = computed(() => props.surgeries.filter(s => !s.applied).length)

const verdictLabel = computed(() => {
  if (!props.holisticVerdict) return ''
  if (props.holisticVerdict.verdict === 'pass') return '✓ 通过'
  return '⚠ 需要再修'
})
</script>

<template>
  <div class="refinery-progress">
    <header class="rp-header">
      <div class="rp-stage">
        <span class="rp-spinner" v-if="stage === 'refining'">⟳</span>
        <span class="rp-stage-label">{{ stageLabel || '润色中' }}</span>
      </div>
      <div class="rp-stats" v-if="surgeries.length">
        {{ totalApplied }} 成功 / {{ totalFailed }} 失败 / 共 {{ surgeries.length }}
      </div>
    </header>

    <!-- 手术列表 -->
    <div class="surgery-list" v-if="surgeries.length">
      <div
        v-for="(s, idx) in surgeries"
        :key="s.operation_id || idx"
        class="surgery-item"
        :class="{ failed: !s.applied }"
      >
        <div class="surgery-head">
          <span class="surgery-id">{{ s.operation_id || `修改 ${idx + 1}` }}</span>
          <span class="surgery-status" :class="{ ok: s.applied, fail: !s.applied }">
            {{ s.applied ? '✓' : '✗' }}
          </span>
        </div>
        <div class="surgery-diff">{{ s.diff_summary || '（无变更说明）' }}</div>
      </div>
    </div>

    <!-- 等待状态 -->
    <div v-else-if="stage === 'refining'" class="rp-waiting">
      <span class="rp-spinner">⟳</span>
      <span>{{ stageLabel || '修改中…' }}</span>
    </div>

    <!-- 整体回读结论 -->
    <div v-if="holisticVerdict" class="holistic-card" :class="`verdict-${holisticVerdict.verdict}`">
      <div class="holistic-head">
        <span>通读检查</span>
        <span class="verdict-tag">{{ verdictLabel }}</span>
      </div>
      <div v-if="holisticVerdict.remaining_issues.length" class="remaining">
        <div v-for="(issue, i) in holisticVerdict.remaining_issues" :key="i" class="remaining-item">
          · {{ issue }}
        </div>
      </div>
      <div v-if="holisticVerdict.final_touch_suggestion" class="final-touch">
        建议：{{ holisticVerdict.final_touch_suggestion }}
      </div>
    </div>
  </div>
</template>

<style scoped>
.refinery-progress {
  padding: 0.75rem;
  background: var(--bg-secondary);
  border-radius: 0.375rem;
  border-left: 3px solid var(--accent-500);
}
.rp-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 0.5rem;
}
.rp-stage {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  font-size: 0.8125rem;
  font-weight: 500;
}
.rp-spinner {
  display: inline-block;
  animation: spin 1.2s linear infinite;
  color: var(--accent-500);
}
@keyframes spin {
  to { transform: rotate(360deg); }
}
.rp-stats { font-size: 0.6875rem; color: var(--text-muted); }

.surgery-list {
  display: flex;
  flex-direction: column;
  gap: 0.375rem;
  margin-bottom: 0.5rem;
}
.surgery-item {
  padding: 0.5rem 0.625rem;
  background: var(--bg-primary);
  border-radius: 0.25rem;
  border-left: 2px solid #10b981;
}
.surgery-item.failed { border-left-color: #dc2626; opacity: 0.7; }
.surgery-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 0.25rem;
}
.surgery-id { font-size: 0.6875rem; color: var(--text-muted); font-family: monospace; }
.surgery-status { font-size: 0.75rem; font-weight: 600; }
.surgery-status.ok { color: #10b981; }
.surgery-status.fail { color: #dc2626; }
.surgery-diff { font-size: 0.75rem; color: var(--text-secondary); }

.rp-waiting {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 1rem;
  color: var(--text-muted);
  font-size: 0.75rem;
}

.holistic-card {
  margin-top: 0.5rem;
  padding: 0.5rem 0.625rem;
  background: var(--bg-primary);
  border-radius: 0.25rem;
  border-left: 2px solid #f59e0b;
}
.holistic-card.verdict-pass { border-left-color: #10b981; }
.holistic-card.verdict-needs_final_touch { border-left-color: #f59e0b; }
.holistic-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 0.25rem;
  font-size: 0.75rem;
}
.verdict-tag {
  padding: 0.125rem 0.375rem;
  border-radius: 0.25rem;
  font-size: 0.625rem;
  font-weight: 600;
}
.verdict-pass .verdict-tag { background: #d1fae5; color: #065f46; }
.verdict-needs_final_touch .verdict-tag { background: #fef3c7; color: #92400e; }
.remaining { font-size: 0.6875rem; color: var(--text-muted); margin-bottom: 0.25rem; }
.remaining-item { line-height: 1.5; }
.final-touch {
  font-size: 0.6875rem;
  color: var(--text-secondary);
  font-style: italic;
  padding-top: 0.25rem;
  border-top: 1px dashed var(--border-color);
  margin-top: 0.25rem;
}
</style>
