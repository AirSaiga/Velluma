<template>
  <div class="goal-selector">
    <div class="selector-header">
      <div class="header-icon">
        <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4" />
        </svg>
      </div>
      <div class="header-content">
        <h4 class="header-title">这一章要完成什么？</h4>
        <p class="header-desc">设定具体目标，让 AI 更精准地把控剧情走向</p>
      </div>
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
        <div class="goal-checkbox">
          <Transition name="check">
            <svg v-if="selectedGoals.includes(goal.id)" class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="3" d="M5 13l4 4L19 7" />
            </svg>
          </Transition>
        </div>
        <div class="goal-content">
          <div class="goal-name">{{ goal.display_name }}</div>
          <div class="goal-desc">{{ goal.description }}</div>
        </div>
        <div class="goal-indicator" :class="{ 'is-selected': selectedGoals.includes(goal.id) }">
          <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
        </div>
      </button>
    </div>
    
    <!-- 已选摘要 -->
    <Transition name="fade-up">
      <div v-if="selectedGoals.length > 0" class="selection-summary">
        <div class="summary-header">
          <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" />
          </svg>
          <span>已选择 {{ selectedGoals.length }} 项目标</span>
        </div>
        <div class="summary-tags">
          <span v-for="goalId in selectedGoals" :key="goalId" class="summary-tag">
            {{ getGoalName(goalId) }}
          </span>
        </div>
      </div>
    </Transition>
  </div>
</template>

<script setup lang="ts">
import { useIntentDrivenConfig } from '../useIntentDrivenConfig'

const {
  goalTemplates,
  selectedGoals,
  toggleGoal
} = useIntentDrivenConfig()

function getGoalName(goalId: string): string {
  const goal = goalTemplates.value.find(g => g.id === goalId)
  return goal?.display_name || goalId
}
</script>

<style scoped>
.goal-selector {
  padding: 0.5rem 0;
}

.selector-header {
  display: flex;
  align-items: flex-start;
  gap: 0.875rem;
  margin-bottom: 1rem;
  padding: 0 0.25rem;
}

.header-icon {
  width: 2.5rem;
  height: 2.5rem;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #dbeafe 0%, #bfdbfe 100%);
  color: #2563eb;
  border-radius: 0.625rem;
  flex-shrink: 0;
}

.header-content {
  flex: 1;
  min-width: 0;
}

.header-title {
  font-size: 0.9375rem;
  font-weight: 600;
  color: var(--text-primary, #1e293b);
  margin-bottom: 0.25rem;
}

.header-desc {
  font-size: 0.8125rem;
  color: var(--text-secondary, #64748b);
  line-height: 1.4;
}

.optional-badge {
  padding: 0.25rem 0.625rem;
  background: var(--bg-canvas, #f1f5f9);
  color: var(--text-muted, #94a3b8);
  font-size: 0.6875rem;
  font-weight: 500;
  border-radius: 9999px;
  flex-shrink: 0;
}

/* 目标网格 */
.goals-grid {
  display: grid;
  grid-template-columns: repeat(1, 1fr);
  gap: 0.625rem;
}

@media (min-width: 640px) {
  .goals-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}

/* 目标卡片 */
.goal-card {
  display: flex;
  align-items: flex-start;
  gap: 0.75rem;
  padding: 0.875rem 1rem;
  background: var(--bg-canvas, #f8fafc);
  border: 1px solid var(--border-color, #e2e8f0);
  border-radius: 0.75rem;
  cursor: pointer;
  transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
  text-align: left;
}

.goal-card:hover {
  background: var(--bg-primary, white);
  border-color: var(--accent-300, #a5b4fc);
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(99, 102, 241, 0.1);
}

.goal-card.selected {
  background: linear-gradient(135deg, #eef2ff 0%, #e0e7ff 100%);
  border-color: var(--accent-500, #6366f1);
  box-shadow: 0 0 0 2px rgba(99, 102, 241, 0.15);
}

/* 复选框 */
.goal-checkbox {
  width: 1.5rem;
  height: 1.5rem;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--bg-primary, white);
  border: 2px solid var(--border-color, #cbd5e1);
  border-radius: 0.375rem;
  color: white;
  flex-shrink: 0;
  margin-top: 0.125rem;
  transition: all 0.2s ease;
}

.goal-card:hover .goal-checkbox {
  border-color: var(--accent-300, #a5b4fc);
}

.goal-card.selected .goal-checkbox {
  background: var(--accent-500, #6366f1);
  border-color: var(--accent-500, #6366f1);
}

/* 内容区 */
.goal-content {
  flex: 1;
  min-width: 0;
}

.goal-name {
  font-size: 0.875rem;
  font-weight: 600;
  color: var(--text-primary, #1e293b);
  margin-bottom: 0.25rem;
  transition: color 0.2s ease;
}

.goal-card.selected .goal-name {
  color: var(--accent-700, #4338ca);
}

.goal-desc {
  font-size: 0.75rem;
  color: var(--text-muted, #94a3b8);
  line-height: 1.4;
}

.goal-card.selected .goal-desc {
  color: var(--accent-600, #4f46e5);
}

/* 指示器 */
.goal-indicator {
  width: 1.75rem;
  height: 1.75rem;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-muted, #cbd5e1);
  opacity: 0;
  transform: scale(0.8);
  transition: all 0.2s ease;
}

.goal-card:hover .goal-indicator:not(.is-selected) {
  opacity: 0.5;
  transform: scale(1);
}

.goal-indicator.is-selected {
  opacity: 1;
  transform: scale(1);
  color: var(--accent-500, #6366f1);
}

/* 选中摘要 */
.selection-summary {
  margin-top: 1rem;
  padding: 0.875rem 1rem;
  background: linear-gradient(135deg, #eef2ff 0%, #e0e7ff 100%);
  border: 1px solid var(--accent-200, #c7d2fe);
  border-radius: 0.75rem;
  animation: slide-up 0.3s ease;
}

@keyframes slide-up {
  from {
    opacity: 0;
    transform: translateY(8px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.summary-header {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  font-size: 0.8125rem;
  font-weight: 500;
  color: var(--accent-700, #4338ca);
  margin-bottom: 0.625rem;
}

.summary-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 0.375rem;
}

.summary-tag {
  padding: 0.25rem 0.625rem;
  background: white;
  border: 1px solid var(--accent-300, #a5b4fc);
  border-radius: 9999px;
  font-size: 0.75rem;
  font-weight: 500;
  color: var(--accent-700, #4338ca);
}

/* 动画 */
.check-enter-active,
.check-leave-active {
  transition: all 0.2s ease;
}

.check-enter-from,
.check-leave-to {
  opacity: 0;
  transform: scale(0.5);
}

.fade-up-enter-active {
  transition: all 0.3s ease;
}

.fade-up-enter-from {
  opacity: 0;
  transform: translateY(8px);
}

/* 深色模式 */
@media (prefers-color-scheme: dark) {
  .header-icon {
    background: linear-gradient(135deg, #1e3a8a 0%, #1e40af 100%);
    color: #60a5fa;
  }
  
  .optional-badge {
    background: #334155;
    color: #64748b;
  }
  
  .goal-card {
    background: #0f172a;
    border-color: #334155;
  }
  
  .goal-card:hover {
    background: #1e293b;
    border-color: #4f46e5;
  }
  
  .goal-card.selected {
    background: linear-gradient(135deg, #1e1b4b 0%, #312e81 100%);
    border-color: #6366f1;
  }
  
  .goal-checkbox {
    background: #1e293b;
    border-color: #475569;
  }
  
  .goal-card.selected .goal-checkbox {
    background: #4f46e5;
    border-color: #4f46e5;
  }
  
  .goal-name {
    color: #f1f5f9;
  }
  
  .goal-card.selected .goal-name {
    color: #a5b4fc;
  }
  
  .goal-desc {
    color: #64748b;
  }
  
  .goal-card.selected .goal-desc {
    color: #818cf8;
  }
  
  .goal-indicator {
    color: #475569;
  }
  
  .goal-indicator.is-selected {
    color: #6366f1;
  }
  
  .selection-summary {
    background: linear-gradient(135deg, #1e1b4b 0%, #312e81 100%);
    border-color: #4f46e5;
  }
  
  .summary-header {
    color: #a5b4fc;
  }
  
  .summary-tag {
    background: #0f172a;
    border-color: #4f46e5;
    color: #a5b4fc;
  }
}
</style>
