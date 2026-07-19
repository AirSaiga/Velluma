<template>
  <button
    type="button"
    class="plan-card"
    :class="{ 'is-selected': isSelected, [plan.plan_type]: true }"
    @click="$emit('select', plan.plan_type)"
  >
    <div class="plan-card-inner">
      <!-- 左侧：徽标与标题 -->
      <div class="plan-header">
        <div class="plan-badge">
          <span class="badge-icon"><Icon :name="typeIcon" :size="14" /></span>
          <span class="badge-text">{{ planTypeName }}</span>
        </div>
        <div class="plan-info">
          <h4 class="plan-name">{{ plan.plan_name }}</h4>
          <p class="plan-desc">{{ plan.description }}</p>
        </div>
      </div>

      <!-- 右侧：详情与操作 -->
      <div class="plan-details">
        <div class="details-content">
          <!-- 推荐理由 -->
          <div class="plan-reasoning">
            <div class="reasoning-title">
              <Icon name="light-bulb" :size="14" />
              推荐理由
            </div>
            <p class="reasoning-text">{{ plan.reasoning }}</p>
          </div>

          <!-- 技术摘要 -->
          <div class="plan-tech">
            <div class="tech-title">
              <Icon name="settings" :size="14" />
              技术摘要
            </div>
            <div class="tech-tags">
              <span class="tech-tag">{{ tierLabel }}</span>
              <span class="tech-tag">张力 {{ plan.policy.tension_level }}/5</span>
              <span class="tech-tag">{{ paceLabel }}</span>
              <span class="tech-tag">{{ refinementLabel }}</span>
            </div>
          </div>
        </div>

        <!-- 选择指示器 -->
        <div class="plan-action">
          <div class="select-ring">
            <Icon name="check" :size="14" class="check-icon" />
          </div>
        </div>
      </div>
    </div>
  </button>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import Icon from '@/components/Icon.vue'
import type { RecommendedPlan, PlanType } from '@/types/intentDriven'

const props = defineProps<{
  plan: RecommendedPlan
  isSelected: boolean
}>()

defineEmits<{
  select: [planType: PlanType]
}>()

const planTypeName = computed(() => {
  const names: Record<PlanType, string> = {
    balanced: '均衡推荐',
    fast: '快速生成',
    quality: '高质量',
    creative: '创意优先'
  }
  return names[props.plan.plan_type]
})

const typeIcon = computed(() => {
  const icons: Record<PlanType, string> = {
    balanced: 'check-badge',
    fast: 'rocket',
    quality: 'star',
    creative: 'paint-brush'
  }
  return icons[props.plan.plan_type]
})

const tierNames: Record<string, string> = {
  TIER_1_FAST: '自由创作',
  TIER_2_STANDARD: '标准编排',
  TIER_3_FORTRESS: '严选打磨'
}
const tierLabel = computed(() => tierNames[props.plan.policy.workflow_tier] || props.plan.policy.workflow_tier)

const paceNames: Record<string, string> = {
  slow_burn: '舒缓',
  balanced: '均衡',
  fast_paced: '紧凑'
}
const paceLabel = computed(() => paceNames[props.plan.policy.pacing_style] || props.plan.policy.pacing_style)

const refinementNames: Record<string, string> = {
  light: '轻度润色',
  standard: '标准精修',
  deep: '深度打磨'
}
const refinementLabel = computed(() => refinementNames[props.plan.policy.refinement_depth] || props.plan.policy.refinement_depth)
</script>

<style scoped>
.plan-card {
  width: 100%;
  background: var(--bg-panel, #f0ece3);
  border: 1px solid var(--border-color, #e0dbd3);
  border-radius: 12px;
  padding: 1.25rem;
  text-align: left;
  cursor: pointer;
  transition: all 0.25s ease;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.02);
  position: relative;
  overflow: hidden;
}

.plan-card::before {
  content: '';
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 3px;
  background: transparent;
  transition: background 0.25s ease;
}

.plan-card:hover {
  background: var(--bg-canvas, #fefdfb);
  border-color: var(--hover-bg, #eee9df);
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.04);
  transform: translateX(2px);
}

.plan-card.is-selected {
  background: rgba(124, 106, 173, 0.04);
  border-color: var(--accent-500, #7c6aad);
  box-shadow: 0 0 0 1px var(--accent-500, #7c6aad), 0 4px 16px rgba(124, 106, 173, 0.08);
}

.plan-card.is-selected::before {
  background: var(--accent-500, #7c6aad);
}

.plan-card-inner {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

@media (min-width: 768px) {
  .plan-card-inner {
    flex-direction: row;
    align-items: stretch;
  }
}

/* 左侧：徽标与标题 */
.plan-header {
  flex: 0 0 200px;
  display: flex;
  flex-direction: column;
  gap: 0.625rem;
  padding-right: 1rem;
}

@media (min-width: 768px) {
  .plan-header {
    border-right: 1px dashed var(--border-color, #e0dbd3);
  }
}

.plan-badge {
  display: inline-flex;
  align-items: center;
  gap: 0.375rem;
  padding: 0.2rem 0.5rem;
  border-radius: 9999px;
  font-size: 11px;
  font-weight: 600;
  background: var(--bg-canvas, #fefdfb);
  color: var(--text-secondary, #6b6560);
  border: 1px solid var(--border-color, #e0dbd3);
  width: fit-content;
}

.plan-card.balanced .plan-badge {
  background: rgba(124, 106, 173, 0.08);
  color: var(--accent-500, #7c6aad);
  border-color: rgba(124, 106, 173, 0.2);
}

.plan-card.fast .plan-badge {
  background: rgba(201, 164, 92, 0.08);
  color: #b08a3a;
  border-color: rgba(201, 164, 92, 0.2);
}

.plan-card.quality .plan-badge {
  background: rgba(124, 106, 173, 0.08);
  color: var(--accent-500, #7c6aad);
  border-color: rgba(124, 106, 173, 0.2);
}

.plan-card.creative .plan-badge {
  background: rgba(192, 132, 133, 0.08);
  color: #a86869;
  border-color: rgba(192, 132, 133, 0.2);
}

.plan-info {
  display: flex;
  flex-direction: column;
  gap: 0.125rem;
}

.plan-name {
  font-size: 15px;
  font-weight: 700;
  color: var(--text-primary, #2c2c2c);
  margin: 0;
  letter-spacing: -0.01em;
}

.plan-desc {
  font-size: 12px;
  color: var(--text-muted, #a89e90);
  margin: 0;
  line-height: 1.5;
}

/* 右侧：详情与操作 */
.plan-details {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 1.25rem;
}

.details-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 0.625rem;
}

@media (min-width: 1024px) {
  .details-content {
    flex-direction: row;
    align-items: stretch;
  }
}

.plan-reasoning, .plan-tech {
  flex: 1;
  border-radius: 10px;
  padding: 0.625rem 0.875rem;
  font-size: 12px;
}

.plan-reasoning {
  background: var(--bg-canvas, #fefdfb);
  border: 1px solid var(--border-color, #e0dbd3);
}

.plan-tech {
  background: rgba(124, 106, 173, 0.04);
  border: 1px solid rgba(124, 106, 173, 0.12);
}

.reasoning-title, .tech-title {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  font-size: 10px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  margin-bottom: 0.375rem;
}

.reasoning-title { color: var(--accent-500, #7c6aad); }
.tech-title { color: var(--accent-500, #7c6aad); }

.reasoning-text {
  color: var(--text-secondary, #6b6560);
  line-height: 1.5;
  margin: 0;
}

.tech-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 0.375rem;
}

.tech-tag {
  font-size: 11px;
  padding: 0.15rem 0.5rem;
  background: rgba(124, 106, 173, 0.08);
  color: var(--accent-500, #7c6aad);
  border-radius: 4px;
  font-weight: 500;
}

/* 选择指示器 */
.plan-action {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
}

.select-ring {
  width: 1.25rem;
  height: 1.25rem;
  border-radius: 50%;
  border: 1.5px solid var(--border-color, #e0dbd3);
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s cubic-bezier(0.34, 1.56, 0.64, 1);
  background: transparent;
}

.check-icon {
  color: white;
  opacity: 0;
  transform: scale(0.5);
  transition: all 0.2s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.plan-card:hover .select-ring {
  border-color: var(--text-muted, #a89e90);
}

.plan-card.is-selected .select-ring {
  background: var(--accent-500, #7c6aad);
  border-color: var(--accent-500, #7c6aad);
  box-shadow: 0 2px 6px rgba(124, 106, 173, 0.25);
}

.plan-card.is-selected .check-icon {
  opacity: 1;
  transform: scale(1);
}

/* 深色模式 */
@media (prefers-color-scheme: dark) {
  .plan-card {
    background: var(--bg-panel, #2c2923);
    border-color: var(--border-color, #3a3530);
  }

  .plan-card:hover {
    background: var(--bg-canvas, #1e1c18);
    border-color: var(--hover-bg, #33302a);
  }

  .plan-card.is-selected {
    background: rgba(167, 139, 250, 0.06);
    border-color: var(--accent-500, #a78bfa);
    box-shadow: 0 0 0 1px var(--accent-500, #a78bfa), 0 4px 16px rgba(167, 139, 250, 0.06);
  }

  .plan-header {
    border-color: var(--border-color, #3a3530);
  }

  .plan-name { color: var(--text-primary, #ede8df); }
  .plan-desc { color: var(--text-muted, #8a8275); }

  .plan-reasoning {
    background: var(--bg-canvas, #1e1c18);
    border-color: var(--border-color, #3a3530);
  }

  .reasoning-title { color: var(--accent-500, #a78bfa); }
  .reasoning-text { color: var(--text-secondary, #bfb8ab); }

  .plan-tech {
    background: rgba(167, 139, 250, 0.06);
    border-color: rgba(167, 139, 250, 0.15);
  }

  .tech-title { color: var(--accent-500, #a78bfa); }
  .tech-tag {
    background: rgba(167, 139, 250, 0.12);
    color: var(--accent-500, #a78bfa);
  }

  .select-ring { border-color: var(--border-color, #3a3530); }
  .plan-card:hover .select-ring { border-color: var(--text-muted, #8a8275); }
}
</style>
