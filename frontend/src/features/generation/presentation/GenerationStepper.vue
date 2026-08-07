<script setup lang="ts">
/**
 * 生成步骤流（V3.1 F3 新建，规格 §5.1；后重构为右栏完整进度中心）。
 *
 * 嵌入右栏「规划」tab，非模态呈现生成流程的当前阶段，是生成进度的
 * 唯一完整展示处（底部 GenerationOverlay 仅保留一行极简状态条 + 实时正文流）。
 *
 * 显示：
 * - 定档通知卡（tier + 理由）
 * - 步骤条（当前阶段 + 进度）
 * - 等待提示（长耗时阶段的具体动作 + 预估耗时）/ 已生成字数
 * - 飞行中调节事件通知卡（升档建议/压抑校准/并章建议）
 * - 降级事件、失败重试
 */
import { computed } from 'vue'
import Icon from '../../../components/Icon.vue'
import type { GenerationSession } from '../composables/useGenerationSession'
import { formatDegradedReason } from '../../../shared/constants/degradation'

const props = defineProps<{
  session: GenerationSession
}>()

const emit = defineEmits<{
  (e: 'retry'): void
  (e: 'dismiss-inflight', index: number): void
}>()

const stage = computed(() => props.session.stage.value)
const tierDecision = computed(() => props.session.tierDecision.value)
const stepProgress = computed(() => props.session.stepProgress.value)
const generating = computed(() => props.session.generating.value)
const errorText = computed(() => props.session.error.value)
const inflightEvents = computed(() => props.session.inflightEvents.value)
const degraded = computed(() => props.session.degraded.value)
const streamTextLen = computed(() => props.session.streamText.value.length)
/** Loop1 大纲自检结论（enable_outline_self_check 固定开，2×reasoning LLM 必跑；
 *  此前产出存 loop1Result 后无任何 UI 消费，作者不知大纲有结构性问题） */
const loop1 = computed(() => props.session.loop1Result.value)

const progressPercent = computed(() => {
  const p = stepProgress.value
  if (!p || !p.total || p.index == null) return null
  return Math.round((p.index / p.total) * 100)
})

/** 友好的等待态文案：BS-ADF 长耗时阶段（分镜卡扩写 / 后处理）给出
 *  "正在做什么 + 预估耗时"提示，避免用户以为卡死。
 *  后处理阶段（PRUNE/ANCHOR_AUDIT/REFINE/BEAT_PATCH/CONSISTENCY_GUARD）在
 *  末段锁死后逐个同步跑，慢模型下单阶段可达数分钟，是最容易让用户误判
 *  "卡死"的空窗——这里用 mapBsadfStageToLabel 产出的中文 label 做匹配。 */
const waitingHint = computed(() => {
  const label = stepProgress.value?.label || ''
  const p = stepProgress.value
  // 分镜卡扩写阶段：每卡 ~12s
  if (label.includes('分镜卡扩写') && p?.index != null && p?.total) {
    const remaining = Math.max(0, p.total - p.index)
    const eta = remaining * 12
    return `正在为每段扩写画面焦点与细节（剩余约 ${remaining} 段，预计 ${eta} 秒）`
  }
  // 通用等待
  if (stage.value === 'tier_classifying') {
    return '正在梳理前文脉络、设计本章高潮与定档篇幅…'
  }
  // 后处理阶段：末段锁死后逐个跑，耗时较长，给出"正在做什么 + ETA"安抚
  // label 来自 useGenerationSession.ts mapBsadfStageToLabel 的中文映射
  if (label.includes('重构剪枝')) {
    return '正在逐段去除 AI 腔、重构表达（通常 1-3 分钟，请勿关闭）'
  }
  if (label.includes('锚点审计')) {
    return '正在核对必现画面与情绪是否到位…'
  }
  if (label.includes('条件补埋')) {
    return '正在补写遗漏的铺垫…'
  }
  if (label.includes('补写遗漏节拍')) {
    return '正在为缺失节拍补写过渡段…'
  }
  if (label.includes('一致性守卫')) {
    return '正在全文校验设定 / 人名 / 状态一致性（最耗时，约 2-4 分钟，请耐心等待）'
  }
  // assembling 是 ALL_BEATS_LOCKED 后进入后处理的过渡态
  if (stage.value === 'assembling') {
    return '全部段落已锁定，正在进入精修与一致性校验…'
  }
  return ''
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

    <!-- Loop1 大纲自检结论（生成前/槽位卡阶段展示；violations/hard_facts 此前被静默吞掉） -->
    <details v-if="loop1" class="loop1-card" :class="{ warn: !loop1.critique_pass }">
      <summary>
        <span v-if="loop1.critique_pass">✓ 大纲自检通过</span>
        <span v-else>⚠ 大纲自检：发现 {{ loop1.violations.length }} 处需注意</span>
      </summary>
      <div class="loop1-body">
        <!-- 违规项（critique_pass=false 时才有） -->
        <div v-if="loop1.violations.length > 0" class="loop1-section">
          <div class="loop1-section-title">需注意</div>
          <ul class="loop1-list">
            <li v-for="(v, i) in loop1.violations" :key="i">
              <span class="loop1-content">{{ v.content || v.reason || JSON.stringify(v) }}</span>
              <span v-if="v.reason && v.content" class="loop1-reason">（{{ v.reason }}）</span>
            </li>
          </ul>
        </div>
        <!-- 硬事实（提取自大纲，供作者核对 AI 理解是否正确） -->
        <details v-if="loop1.hard_facts.length > 0" class="loop1-facts">
          <summary>AI 从大纲提取的 {{ loop1.hard_facts.length }} 条硬事实（点开核对）</summary>
          <ul class="loop1-list">
            <li v-for="(f, i) in loop1.hard_facts" :key="i">
              <span v-if="f.category" class="loop1-tag">{{ f.category }}</span>
              <span class="loop1-content">{{ f.content }}</span>
            </li>
          </ul>
        </details>
      </div>
    </details>

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
      <!-- 等待提示（长耗时阶段的具体动作 + 预估耗时）/ 已生成字数 -->
      <div v-if="generating && streamTextLen > 0" class="step-sub">
        已生成 {{ streamTextLen }} 字
      </div>
      <div v-else-if="generating && waitingHint" class="step-sub">
        {{ waitingHint }}
      </div>
    </div>

    <!-- 失败态：错误文案 + 重试入口 -->
    <!-- 注意：error 原文可能已被 WorkspaceView 的 toast watcher 消费清空，给兜底文案 -->
    <div v-if="stage === 'error'" class="error-card">
      <div class="error-header">
        <Icon name="exclamation-circle" :size="14" />
        <span>生成失败</span>
      </div>
      <p class="error-text">{{ errorText || '生成或精修过程出错，请重试。' }}</p>
      <button class="inflight-btn primary" @click="emit('retry')">重试</button>
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
        <button class="inflight-btn" @click="emit('dismiss-inflight', idx)">忽略</button>
      </div>
    </div>

    <!-- 降级事件 -->
    <details v-if="degraded.length > 0" class="degraded-details">
      <summary>{{ degraded.length }} 个降级事件（建议在分镜卡里「重写本段」修复）</summary>
      <ul class="degraded-list">
        <li v-for="(d, i) in degraded" :key="i">
          <span class="deg-reason">{{ formatDegradedReason(d.reason) }}</span>
          <span v-if="d.detail" class="deg-action">{{ d.phase }}：{{ d.detail }}</span>
          <span v-else-if="d.phase" class="deg-action">阶段：{{ d.phase }}</span>
        </li>
      </ul>
    </details>
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

/* 等待提示 / 已生成字数 */
.step-sub {
  margin-top: 0.375rem;
  font-size: 0.6875rem;
  color: var(--text-muted);
  line-height: 1.5;
}

/* 失败态卡片 */
.error-card {
  background: var(--bg-canvas);
  border: 1px solid #dc2626;
  border-left-width: 3px;
  border-radius: 0.375rem;
  padding: 0.625rem 0.75rem;
}

.error-header {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  color: #dc2626;
  font-size: 0.75rem;
  font-weight: 600;
}

.error-text {
  font-size: 0.6875rem;
  color: var(--text-secondary);
  line-height: 1.5;
  margin: 0.375rem 0 0.5rem;
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

/* Loop1 大纲自检结论 */
.loop1-card {
  margin-top: 0.5rem;
  padding: 0.5rem 0.625rem;
  border-radius: 0.5rem;
  background: var(--bg-panel);
  border: 1px solid var(--border-color);
  font-size: 0.75rem;
}
.loop1-card.warn {
  border-color: #fde68a;
  background: #fffbeb;
}
.loop1-card summary {
  cursor: pointer;
  font-weight: 500;
  color: var(--text-primary);
}
.loop1-card.warn summary {
  color: #b45309;
}
.loop1-body {
  margin-top: 0.375rem;
  display: flex;
  flex-direction: column;
  gap: 0.375rem;
}
.loop1-section-title {
  font-size: 0.6875rem;
  color: var(--text-muted);
  margin-bottom: 0.125rem;
}
.loop1-list {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 0.1875rem;
}
.loop1-list li {
  font-size: 0.6875rem;
  line-height: 1.5;
  color: var(--text-secondary);
}
.loop1-content {
  color: var(--text-primary);
}
.loop1-reason {
  color: var(--text-muted);
}
.loop1-tag {
  display: inline-block;
  margin-right: 0.25rem;
  padding: 0 0.3rem;
  border-radius: 0.25rem;
  background: var(--bg-tertiary);
  font-size: 0.625rem;
  color: var(--text-muted);
}
.loop1-facts {
  font-size: 0.6875rem;
  color: var(--text-muted);
}
.loop1-facts summary {
  cursor: pointer;
  padding: 0.125rem 0;
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
</style>
