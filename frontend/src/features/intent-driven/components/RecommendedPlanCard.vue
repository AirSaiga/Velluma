<template>
  <button 
    type="button"
    class="plan-card" 
    :class="{ 'selected': isSelected }" 
    @click="$emit('select', plan.plan_type)"
  >
    <!-- 选中指示条 -->
    <div class="selection-bar"></div>
    
    <!-- 头部 -->
    <div class="plan-header">
      <div class="plan-type-badge" :class="plan.plan_type">
        <span class="badge-icon">{{ typeIcon }}</span>
        <span class="badge-text">{{ planTypeName }}</span>
      </div>
      <div class="plan-time">
        <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
        {{ plan.estimated_time }}
      </div>
    </div>
    
    <!-- 主体 -->
    <div class="plan-body">
      <h4 class="plan-name">{{ plan.plan_name }}</h4>
      <p class="plan-desc">{{ plan.description }}</p>
      
      <div class="plan-reasoning">
        <div class="reasoning-icon">
          <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
          </svg>
        </div>
        <span>{{ plan.reasoning }}</span>
      </div>
      
      <div v-if="plan.risk_hints.length > 0" class="plan-risks">
        <div class="risk-header">
          <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
          </svg>
          <span>注意事项</span>
        </div>
        <ul class="risk-list">
          <li v-for="(risk, idx) in plan.risk_hints" :key="idx">
            {{ risk }}
          </li>
        </ul>
      </div>
    </div>
    
    <!-- 底部 -->
    <div class="plan-footer">
      <div class="select-indicator" :class="{ 'is-selected': isSelected }">
        <svg v-if="isSelected" class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" />
        </svg>
        <span v-else>选择方案</span>
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
  position: relative;
  display: flex;
  flex-direction: column;
  background: var(--bg-canvas, #f8fafc);
  border: 2px solid var(--border-color, #e2e8f0);
  border-radius: 1rem;
  overflow: hidden;
  cursor: pointer;
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  text-align: left;
}

.plan-card:hover {
  background: var(--bg-primary, white);
  border-color: var(--accent-300, #a5b4fc);
  transform: translateY(-3px);
  box-shadow: 0 16px 32px rgba(99, 102, 241, 0.12);
}

.plan-card.selected {
  background: linear-gradient(135deg, #eef2ff 0%, #e0e7ff 100%);
  border-color: var(--accent-500, #6366f1);
  box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.15), 0 16px 32px rgba(99, 102, 241, 0.2);
}

/* 选中指示条 */
.selection-bar {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 3px;
  background: linear-gradient(90deg, var(--accent-500, #6366f1), var(--accent-400, #818cf8));
  transform: scaleX(0);
  transition: transform 0.3s ease;
}

.plan-card.selected .selection-bar {
  transform: scaleX(1);
}

/* 头部 */
.plan-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 1rem 1.25rem 0.75rem;
}

.plan-type-badge {
  display: inline-flex;
  align-items: center;
  gap: 0.375rem;
  padding: 0.5rem 0.875rem;
  font-size: 0.75rem;
  font-weight: 600;
  border-radius: 9999px;
  letter-spacing: 0.025em;
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.05);
}

.badge-icon {
  font-size: 0.875rem;
}

.plan-type-badge.balanced {
  background: linear-gradient(135deg, #d1fae5 0%, #a7f3d0 100%);
  color: #065f46;
}

.plan-type-badge.fast {
  background: linear-gradient(135deg, #fef3c7 0%, #fde68a 100%);
  color: #92400e;
}

.plan-type-badge.quality {
  background: linear-gradient(135deg, #ede9fe 0%, #ddd6fe 100%);
  color: #5b21b6;
}

.plan-type-badge.creative {
  background: linear-gradient(135deg, #fce7f3 0%, #fbcfe8 100%);
  color: #9d174d;
}

.plan-time {
  display: flex;
  align-items: center;
  gap: 0.25rem;
  font-size: 0.75rem;
  color: var(--text-muted, #94a3b8);
}

/* 主体 */
.plan-body {
  flex: 1;
  padding: 0 1.25rem 1rem;
}

.plan-name {
  font-size: 1rem;
  font-weight: 700;
  color: var(--text-primary, #1e293b);
  margin-bottom: 0.5rem;
  transition: color 0.2s ease;
}

.plan-card.selected .plan-name {
  color: var(--accent-700, #4338ca);
}

.plan-desc {
  font-size: 0.875rem;
  color: var(--text-secondary, #64748b);
  line-height: 1.6;
  margin-bottom: 1rem;
}

/* 推荐理由 */
.plan-reasoning {
  display: flex;
  align-items: flex-start;
  gap: 0.625rem;
  padding: 0.875rem 1rem;
  background: linear-gradient(135deg, #eff6ff 0%, #dbeafe 100%);
  border: 1px solid #bfdbfe;
  border-radius: 0.75rem;
  font-size: 0.8125rem;
  color: #1e40af;
  line-height: 1.6;
}

.reasoning-icon {
  flex-shrink: 0;
  width: 1.75rem;
  height: 1.75rem;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(255,255,255,0.7);
  border-radius: 0.5rem;
  color: #3b82f6;
}

/* 风险提示 */
.plan-risks {
  margin-top: 0.875rem;
  padding: 0.875rem 1rem;
  background: linear-gradient(135deg, #fffbeb 0%, #fef3c7 100%);
  border: 1px solid #fde68a;
  border-radius: 0.75rem;
}

.risk-header {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.75rem;
  font-weight: 600;
  color: #b45309;
  margin-bottom: 0.5rem;
}

.risk-list {
  list-style: none;
  padding: 0;
  margin: 0;
  font-size: 0.75rem;
  color: #92400e;
  line-height: 1.6;
}

.risk-list li {
  position: relative;
  padding-left: 1rem;
  margin-bottom: 0.25rem;
}

.risk-list li:last-child {
  margin-bottom: 0;
}

.risk-list li::before {
  content: '•';
  position: absolute;
  left: 0.25rem;
  color: #f59e0b;
  font-weight: bold;
  font-size: 1rem;
  line-height: 1.4;
}

/* 底部 */
.plan-footer {
  padding: 0.875rem 1.25rem;
  border-top: 1px solid var(--border-color, #e2e8f0);
  background: rgba(255,255,255,0.6);
}

.plan-card.selected .plan-footer {
  background: rgba(255,255,255,0.8);
  border-color: var(--accent-300, #a5b4fc);
}

.select-indicator {
  width: 100%;
  padding: 0.625rem;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  font-size: 0.875rem;
  font-weight: 600;
  color: var(--text-secondary, #64748b);
  background: var(--bg-canvas, #f1f5f9);
  border: 2px solid var(--border-color, #e2e8f0);
  border-radius: 0.625rem;
  transition: all 0.2s ease;
}

.select-indicator.is-selected {
  background: linear-gradient(135deg, var(--accent-500, #6366f1) 0%, var(--accent-600, #4f46e5) 100%);
  border-color: transparent;
  color: white;
  box-shadow: 0 4px 12px rgba(99, 102, 241, 0.3);
}

.plan-card:hover .select-indicator:not(.is-selected) {
  background: var(--accent-50, #eef2ff);
  border-color: var(--accent-400, #818cf8);
  color: var(--accent-700, #4338ca);
}

/* 深色模式 */
@media (prefers-color-scheme: dark) {
  .plan-card {
    background: #0f172a;
    border-color: #334155;
  }
  
  .plan-card:hover {
    background: #1e293b;
    border-color: #4f46e5;
  }
  
  .plan-card.selected {
    background: linear-gradient(135deg, #1e1b4b 0%, #312e81 100%);
    border-color: #6366f1;
  }
  
  .plan-name {
    color: #f1f5f9;
  }
  
  .plan-card.selected .plan-name {
    color: #a5b4fc;
  }
  
  .plan-desc {
    color: #94a3b8;
  }
  
  .plan-reasoning {
    background: linear-gradient(135deg, #1e3a8a 0%, #1e40af 100%);
    color: #bfdbfe;
  }
  
  .reasoning-icon {
    background: rgba(0,0,0,0.2);
  }
  
  .plan-risks {
    background: linear-gradient(135deg, #78350f 0%, #92400e 100%);
  }
  
  .risk-header {
    color: #fcd34d;
  }
  
  .risk-list {
    color: #fde68a;
  }
  
  .plan-footer {
    border-color: #334155;
    background: rgba(15, 23, 42, 0.5);
  }
  
  .plan-card.selected .plan-footer {
    border-color: #4f46e5;
  }
  
  .select-indicator {
    background: #1e293b;
    border-color: #334155;
    color: #94a3b8;
  }
  
  .select-indicator.is-selected {
    background: linear-gradient(135deg, #4f46e5 0%, #3730a3 100%);
  }
  
  .plan-card:hover .select-indicator:not(.is-selected) {
    background: #312e81;
    border-color: #4f46e5;
    color: #a5b4fc;
  }
  
  .plan-time {
    color: #64748b;
  }
}
</style>
