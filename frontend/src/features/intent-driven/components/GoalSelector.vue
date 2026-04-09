<template>
  <div class="goal-selector">
    <div class="selector-header">
      <h3 class="selector-title">具体目标</h3>
      <span class="optional-badge">可选</span>
    </div>
    
    <div class="goals-grid">
      <button
        v-for="goal in goalTemplates"
        :key="goal.id"
        type="button"
        class="goal-card"
        :class="{ 'selected': selectedGoals.includes(goal.id) }"
        @click="toggleGoal(goal.id)"
      >
        <!-- 复选框 -->
        <div class="goal-checkbox">
          <svg class="w-3.5 h-3.5 check-icon" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="3" d="M5 13l4 4L19 7" />
          </svg>
        </div>
        
        <!-- 内容 -->
        <div class="goal-content">
          <div class="goal-name">{{ goal.display_name }}</div>
          <div class="goal-desc">{{ goal.description }}</div>
        </div>
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { useIntentDrivenConfig } from '../useIntentDrivenConfig'

const {
  goalTemplates,
  selectedGoals,
  toggleGoal
} = useIntentDrivenConfig()
</script>

<style scoped>
.goal-selector {
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
}

/* 标题区 */
.selector-header {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.selector-title {
  font-size: 1.125rem;
  font-weight: 600;
  color: var(--text-primary, #0f172a);
  letter-spacing: -0.01em;
  margin: 0;
}

.optional-badge {
  font-size: 0.75rem;
  font-weight: 500;
  color: #64748b;
  background: #f1f5f9;
  padding: 0.25rem 0.625rem;
  border-radius: 9999px;
}

/* 目标网格 */
.goals-grid {
  display: grid;
  grid-template-columns: repeat(1, 1fr);
  gap: 0.75rem;
}

@media (min-width: 768px) {
  .goals-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}

/* 目标卡片：无边框轻量级 */
.goal-card {
  display: flex;
  align-items: flex-start;
  gap: 0.875rem;
  padding: 1rem 1.125rem;
  background: rgba(255, 255, 255, 0.4);
  border: 1px solid rgba(226, 232, 240, 0.6);
  border-radius: 0.875rem;
  cursor: pointer;
  text-align: left;
  transition: all 0.25s cubic-bezier(0.2, 0.8, 0.2, 1);
}

.goal-card:hover {
  background: rgba(255, 255, 255, 0.9);
  border-color: rgba(148, 163, 184, 0.3);
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(15, 23, 42, 0.03);
}

.goal-card.selected {
  background: rgba(99, 102, 241, 0.03);
  border-color: rgba(99, 102, 241, 0.3);
}

/* 复选框 (圆形微发光) */
.goal-checkbox {
  width: 1.25rem;
  height: 1.25rem;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 0.375rem;
  border: 1.5px solid #cbd5e1;
  background: transparent;
  flex-shrink: 0;
  margin-top: 0.125rem;
  transition: all 0.2s ease;
}

.check-icon {
  color: white;
  opacity: 0;
  transform: scale(0.5);
  transition: all 0.2s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.goal-card:hover .goal-checkbox {
  border-color: #94a3b8;
}

.goal-card.selected .goal-checkbox {
  background: #6366f1;
  border-color: #6366f1;
  box-shadow: 0 2px 6px rgba(99, 102, 241, 0.3);
}

.goal-card.selected .check-icon {
  opacity: 1;
  transform: scale(1);
}

/* 内容区 */
.goal-content {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.goal-name {
  font-size: 0.875rem;
  font-weight: 600;
  color: #1e293b;
  transition: color 0.2s ease;
}

.goal-card.selected .goal-name {
  color: #4338ca;
}

.goal-desc {
  font-size: 0.75rem;
  color: #64748b;
  line-height: 1.4;
}

/* 深色模式 */
@media (prefers-color-scheme: dark) {
  .selector-title {
    color: #f1f5f9;
  }
  
  .optional-badge {
    background: #1e293b;
    color: #94a3b8;
  }
  
  .goal-card {
    background: rgba(30, 41, 59, 0.4);
    border-color: rgba(51, 65, 85, 0.6);
  }
  
  .goal-card:hover {
    background: rgba(30, 41, 59, 0.8);
    border-color: rgba(71, 85, 105, 0.8);
  }
  
  .goal-card.selected {
    background: rgba(99, 102, 241, 0.1);
    border-color: rgba(99, 102, 241, 0.4);
  }
  
  .goal-checkbox {
    border-color: #475569;
  }
  
  .goal-card:hover .goal-checkbox {
    border-color: #64748b;
  }
  
  .goal-card.selected .goal-checkbox {
    background: #6366f1;
    border-color: #6366f1;
  }
  
  .goal-name {
    color: #f1f5f9;
  }
  
  .goal-card.selected .goal-name {
    color: #c7d2fe;
  }
  
  .goal-desc {
    color: #94a3b8;
  }
}
</style>
