<template>
  <div class="plan-card" :class="{ 'selected': isSelected }" @click="$emit('select', plan.plan_type)">
    <div class="plan-header">
      <div class="plan-type-badge" :class="plan.plan_type">
        {{ planTypeName }}
      </div>
      <div class="plan-time">{{ plan.estimated_time }}</div>
    </div>
    
    <div class="plan-body">
      <h4 class="plan-name">{{ plan.plan_name }}</h4>
      <p class="plan-desc">{{ plan.description }}</p>
      
      <div class="plan-reasoning">
        <span class="reasoning-icon">💡</span>
        <span>{{ plan.reasoning }}</span>
      </div>
      
      <div class="plan-risks" v-if="plan.risk_hints.length > 0">
        <div class="risk-label">风险提示：</div>
        <ul class="risk-list">
          <li v-for="(risk, idx) in plan.risk_hints" :key="idx">
            ⚠️ {{ risk }}
          </li>
        </ul>
      </div>
    </div>
    
    <div class="plan-footer">
      <button class="select-btn" :class="{ 'selected': isSelected }">
        {{ isSelected ? '已选择' : '选择此方案' }}
      </button>
    </div>
  </div>
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
    balanced: '推荐',
    fast: '快速',
    quality: '质量',
    creative: '创意'
  }
  return names[props.plan.plan_type]
})
</script>

<style scoped>
.plan-card {
  border: 1px solid #e5e7eb;
  border-radius: 0.5rem;
  overflow: hidden;
  cursor: pointer;
  transition: all 0.2s;
}

.plan-card:hover {
  border-color: #93c5fd;
  box-shadow: 0 2px 8px rgba(59, 130, 246, 0.15);
}

.plan-card.selected {
  border-color: #3b82f6;
  box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.2);
}

.plan-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.5rem 1rem;
  background: #f9fafb;
}

.plan-type-badge {
  padding: 0.125rem 0.5rem;
  font-size: 0.75rem;
  font-weight: 500;
  border-radius: 0.25rem;
}

.plan-type-badge.balanced {
  background: #d1fae5;
  color: #065f46;
}

.plan-type-badge.fast {
  background: #fef3c7;
  color: #92400e;
}

.plan-type-badge.quality {
  background: #ede9fe;
  color: #5b21b6;
}

.plan-type-badge.creative {
  background: #fce7f3;
  color: #9d174d;
}

.plan-time {
  font-size: 0.75rem;
  color: #6b7280;
}

.plan-body {
  padding: 1rem;
}

.plan-name {
  font-size: 1rem;
  font-weight: 600;
  color: #1f2937;
}

.plan-desc {
  font-size: 0.875rem;
  color: #4b5563;
  margin-top: 0.25rem;
}

.plan-reasoning {
  margin-top: 0.75rem;
  padding: 0.5rem;
  background: #eff6ff;
  border-radius: 0.375rem;
  font-size: 0.875rem;
  color: #1e40af;
  display: flex;
  gap: 0.5rem;
}

.plan-risks {
  margin-top: 0.75rem;
}

.risk-label {
  font-size: 0.75rem;
  font-weight: 500;
  color: #6b7280;
  margin-bottom: 0.25rem;
}

.risk-list {
  font-size: 0.75rem;
  color: #d97706;
}

.plan-footer {
  padding: 0 1rem 1rem;
}

.select-btn {
  width: 100%;
  padding: 0.5rem;
  font-size: 0.875rem;
  font-weight: 500;
  border-radius: 0.375rem;
  border: 1px solid #3b82f6;
  color: #3b82f6;
  background: transparent;
  cursor: pointer;
  transition: all 0.2s;
}

.select-btn:hover {
  background: #eff6ff;
}

.select-btn.selected {
  background: #3b82f6;
  color: white;
}
</style>
