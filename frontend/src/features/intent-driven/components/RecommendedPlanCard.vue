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
          <span class="badge-icon">{{ typeIcon }}</span>
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
          <!-- 推荐理由 (Why it fits) -->
          <div class="plan-reasoning">
            <div class="reasoning-title">
              <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z" />
              </svg>
              推荐理由
            </div>
            <p class="reasoning-text">{{ plan.reasoning }}</p>
          </div>
          
          <!-- 注意事项 (Trade-offs) -->
          <div v-if="plan.risk_hints.length > 0" class="plan-risks">
            <div class="risks-title">
              <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
              </svg>
              注意事项
            </div>
            <ul class="risks-list">
              <li v-for="(risk, idx) in plan.risk_hints" :key="idx">{{ risk }}</li>
            </ul>
          </div>
        </div>

        <!-- 选择指示器 -->
        <div class="plan-action">
          <div class="select-ring">
            <svg class="w-4 h-4 check-icon" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="3" d="M5 13l4 4L19 7" />
            </svg>
          </div>
        </div>
      </div>
    </div>
  </button>
</template>

<script setup lang="ts">
import { computed } from 'vue'
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
    balanced: '⚖️',
    fast: '⚡',
    quality: '✨',
    creative: '🎨'
  }
  return icons[props.plan.plan_type]
})
</script>

<style scoped>
.plan-card {
  width: 100%;
  background: rgba(255, 255, 255, 0.7);
  backdrop-filter: blur(20px);
  border: 1px solid rgba(226, 232, 240, 0.8);
  border-radius: 1rem;
  padding: 1.25rem;
  text-align: left;
  cursor: pointer;
  transition: all 0.3s cubic-bezier(0.2, 0.8, 0.2, 1);
  box-shadow: 0 2px 4px -1px rgba(0, 0, 0, 0.02);
  position: relative;
  overflow: hidden;
}

.plan-card::before {
  content: '';
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 4px;
  background: transparent;
  transition: background 0.3s ease;
}

.plan-card:hover {
  background: rgba(255, 255, 255, 0.95);
  transform: translateX(4px);
  box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.05), 0 4px 6px -2px rgba(0, 0, 0, 0.02);
  border-color: rgba(203, 213, 225, 0.8);
}

.plan-card.is-selected {
  background: rgba(255, 255, 255, 1);
  border-color: #6366f1;
  box-shadow: 0 0 0 1px #6366f1, 0 10px 15px -3px rgba(99, 102, 241, 0.1);
}

.plan-card.is-selected::before {
  background: linear-gradient(180deg, #6366f1, #818cf8);
}

.plan-card-inner {
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
}

@media (min-width: 768px) {
  .plan-card-inner {
    flex-direction: row;
    align-items: stretch;
  }
}

/* 左侧：徽标与标题 */
.plan-header {
  flex: 0 0 240px;
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  padding-right: 1.25rem;
}

@media (min-width: 768px) {
  .plan-header {
    border-right: 1px dashed rgba(226, 232, 240, 0.8);
  }
}

.plan-badge {
  display: inline-flex;
  align-items: center;
  gap: 0.375rem;
  padding: 0.25rem 0.625rem;
  border-radius: 9999px;
  font-size: 0.6875rem;
  font-weight: 600;
  background: #f1f5f9;
  color: #475569;
  border: 1px solid #e2e8f0;
  width: fit-content;
}

.plan-card.balanced .plan-badge {
  background: rgba(16, 185, 129, 0.1);
  color: #059669;
  border-color: rgba(16, 185, 129, 0.2);
}

.plan-card.fast .plan-badge {
  background: rgba(245, 158, 11, 0.1);
  color: #d97706;
  border-color: rgba(245, 158, 11, 0.2);
}

.plan-card.quality .plan-badge {
  background: rgba(99, 102, 241, 0.1);
  color: #4f46e5;
  border-color: rgba(99, 102, 241, 0.2);
}

.plan-card.creative .plan-badge {
  background: rgba(236, 72, 153, 0.1);
  color: #db2777;
  border-color: rgba(236, 72, 153, 0.2);
}

.plan-info {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.plan-name {
  font-size: 1.125rem;
  font-weight: 700;
  color: #0f172a;
  margin: 0;
  letter-spacing: -0.01em;
}

.plan-desc {
  font-size: 0.8125rem;
  color: #64748b;
  margin: 0;
  line-height: 1.5;
}

/* 右侧：详情与操作 */
.plan-details {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 1.5rem;
}

.details-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

@media (min-width: 1024px) {
  .details-content {
    flex-direction: row;
    align-items: stretch;
  }
}

.plan-reasoning, .plan-risks {
  flex: 1;
  border-radius: 0.625rem;
  padding: 0.75rem 1rem;
  font-size: 0.8125rem;
}

.plan-reasoning {
  background: linear-gradient(180deg, rgba(248, 250, 252, 0.8) 0%, rgba(241, 245, 249, 0.4) 100%);
  border: 1px solid rgba(226, 232, 240, 0.6);
}

.plan-risks {
  background: rgba(255, 251, 235, 0.5);
  border: 1px solid rgba(253, 230, 138, 0.5);
}

.reasoning-title, .risks-title {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  font-size: 0.6875rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  margin-bottom: 0.375rem;
}

.reasoning-title { color: #6366f1; }
.risks-title { color: #d97706; }

.reasoning-text {
  color: #334155;
  line-height: 1.5;
  margin: 0;
}

.risks-list {
  margin: 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.risks-list li {
  position: relative;
  padding-left: 0.875rem;
  color: #92400e;
  line-height: 1.4;
}

.risks-list li::before {
  content: '';
  position: absolute;
  left: 0;
  top: 0.45rem;
  width: 4px;
  height: 4px;
  border-radius: 50%;
  background: #f59e0b;
}

/* 选择指示器 */
.plan-action {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
}

.select-ring {
  width: 1.5rem;
  height: 1.5rem;
  border-radius: 50%;
  border: 2px solid #cbd5e1;
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
  border-color: #94a3b8;
}

.plan-card.is-selected .select-ring {
  background: #6366f1;
  border-color: #6366f1;
  box-shadow: 0 2px 6px rgba(99, 102, 241, 0.3);
}

.plan-card.is-selected .check-icon {
  opacity: 1;
  transform: scale(1);
}

/* 深色模式 */
@media (prefers-color-scheme: dark) {
  .plan-card {
    background: rgba(30, 41, 59, 0.6);
    border-color: rgba(51, 65, 85, 0.8);
  }

  .plan-card:hover {
    background: rgba(30, 41, 59, 0.95);
    border-color: rgba(71, 85, 105, 0.8);
  }

  .plan-card.is-selected {
    background: rgba(15, 23, 42, 0.95);
    border-color: #6366f1;
    box-shadow: 0 0 0 1px #6366f1, 0 10px 15px -3px rgba(0, 0, 0, 0.5);
  }

  .plan-header {
    border-color: rgba(71, 85, 105, 0.8);
  }

  .plan-name { color: #f8fafc; }
  .plan-desc { color: #94a3b8; }

  .plan-reasoning {
    background: rgba(15, 23, 42, 0.4);
    border-color: rgba(51, 65, 85, 0.6);
  }

  .reasoning-title { color: #818cf8; }
  .reasoning-text { color: #cbd5e1; }

  .plan-risks {
    background: rgba(120, 53, 15, 0.2);
    border-color: rgba(180, 83, 9, 0.3);
  }

  .risks-title { color: #fbbf24; }
  .risks-list li { color: #fde68a; }

  .select-ring { border-color: #475569; }
  .plan-card:hover .select-ring { border-color: #64748b; }
}
</style>
