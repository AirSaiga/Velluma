<template>
  <div class="goal-selector">
    <div class="selector-header">
      <h4 class="selector-title">这一章要完成什么？</h4>
      <span class="optional-tag">可选</span>
    </div>
    
    <div class="goal-list">
      <div
        v-for="goal in goalTemplates"
        :key="goal.id"
        class="goal-item"
        :class="{ 'selected': selectedGoals.includes(goal.id) }"
        @click="toggleGoal(goal.id)"
      >
        <div class="goal-checkbox">
          <span v-if="selectedGoals.includes(goal.id)">✓</span>
        </div>
        <div class="goal-content">
          <div class="goal-name">{{ goal.display_name }}</div>
          <div class="goal-desc">{{ goal.description }}</div>
        </div>
      </div>
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
  padding: 1rem;
  background: #f9fafb;
  border-radius: 0.5rem;
}

.selector-header {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 0.75rem;
}

.selector-title {
  font-size: 0.875rem;
  font-weight: 500;
  color: #374151;
}

.optional-tag {
  font-size: 0.75rem;
  padding: 0.125rem 0.375rem;
  background: #e5e7eb;
  color: #6b7280;
  border-radius: 0.25rem;
}

.goal-list {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.goal-item {
  display: flex;
  align-items: flex-start;
  gap: 0.75rem;
  padding: 0.5rem;
  border: 1px solid #e5e7eb;
  border-radius: 0.375rem;
  cursor: pointer;
  transition: all 0.2s;
}

.goal-item:hover {
  border-color: #93c5fd;
}

.goal-item.selected {
  border-color: #3b82f6;
  background: #eff6ff;
}

.goal-checkbox {
  width: 1.25rem;
  height: 1.25rem;
  border: 1px solid #d1d5db;
  border-radius: 0.25rem;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 0.75rem;
  color: #3b82f6;
  flex-shrink: 0;
  margin-top: 0.125rem;
}

.goal-item.selected .goal-checkbox {
  border-color: #3b82f6;
  background: #3b82f6;
  color: white;
}

.goal-name {
  font-size: 0.875rem;
  font-weight: 500;
  color: #1f2937;
}

.goal-desc {
  font-size: 0.75rem;
  color: #6b7280;
  margin-top: 0.125rem;
}
</style>
