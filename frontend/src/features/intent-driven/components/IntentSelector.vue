<template>
  <div class="intent-selector">
    <div class="selector-header">
      <h3 class="selector-title">这一章要什么效果？</h3>
      <p class="selector-hint">选择创作意图，系统将自动推荐最佳生成策略</p>
    </div>
    
    <div class="intent-grid">
      <div
        v-for="intent in intentTemplates"
        :key="intent.id"
        class="intent-card"
        :class="{
          'selected': selectedIntents.includes(intent.id),
          'disabled': !canSelectMore && !selectedIntents.includes(intent.id)
        }"
        @click="toggleIntent(intent.id)"
        @mouseenter="hoveredIntent = intent.id"
        @mouseleave="hoveredIntent = null"
      >
        <div class="intent-icon">{{ intent.icon }}</div>
        <div class="intent-name">{{ intent.display_name }}</div>
        <div class="intent-desc">{{ intent.short_desc }}</div>
        
        <div class="intent-tooltip" v-if="hoveredIntent === intent.id">
          <div class="tooltip-title">{{ intent.display_name }}</div>
          <div class="tooltip-desc">{{ intent.detailed_desc }}</div>
          <div class="tooltip-scenarios">
            <div class="tooltip-label">适用场景：</div>
            <ul>
              <li v-for="(scenario, idx) in intent.applicable_scenarios" :key="idx">
                {{ scenario }}
              </li>
            </ul>
          </div>
          <div class="tooltip-style">
            <div class="tooltip-label">风格建议：</div>
            <span>{{ intent.style_recommendation }}</span>
          </div>
        </div>
      </div>
    </div>
    
    <div class="selection-summary" v-if="selectedIntents.length > 0">
      <div class="summary-label">已选择意图：</div>
      <div class="summary-tags">
        <span 
          v-for="intent in selectedIntentTemplates" 
          :key="intent.id"
          class="intent-tag"
        >
          {{ intent.icon }} {{ intent.display_name }}
          <button class="tag-remove" @click.stop="toggleIntent(intent.id)">×</button>
        </span>
      </div>
      <div class="combo-hint" v-if="selectedIntents.length === 2">
        💡 组合意图：系统将智能合并两个意图的策略
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useIntentDrivenConfig } from '../useIntentDrivenConfig'

const hoveredIntent = ref<string | null>(null)

const {
  intentTemplates,
  state,
  selectedIntents,
  selectedIntentTemplates,
  canSelectMore,
  toggleIntent
} = useIntentDrivenConfig()
</script>

<style scoped>
.intent-selector {
  padding: 1rem;
  background: white;
  border-radius: 0.5rem;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
}

.selector-header {
  margin-bottom: 1rem;
  text-align: center;
}

.selector-title {
  font-size: 1.125rem;
  font-weight: 600;
  color: #1f2937;
}

.selector-hint {
  font-size: 0.875rem;
  color: #6b7280;
  margin-top: 0.25rem;
}

.intent-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 0.75rem;
}

@media (min-width: 768px) {
  .intent-grid {
    grid-template-columns: repeat(4, 1fr);
  }
}

.intent-card {
  position: relative;
  padding: 0.75rem;
  border: 1px solid #e5e7eb;
  border-radius: 0.5rem;
  cursor: pointer;
  transition: all 0.2s;
}

.intent-card:hover {
  border-color: #93c5fd;
  box-shadow: 0 2px 8px rgba(59, 130, 246, 0.15);
}

.intent-card.selected {
  border-color: #3b82f6;
  background: #eff6ff;
  box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.2);
}

.intent-card.disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.intent-icon {
  font-size: 1.5rem;
  text-align: center;
  margin-bottom: 0.25rem;
}

.intent-name {
  font-size: 0.875rem;
  font-weight: 500;
  text-align: center;
  color: #1f2937;
}

.intent-desc {
  font-size: 0.75rem;
  text-align: center;
  color: #6b7280;
  margin-top: 0.25rem;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.intent-tooltip {
  position: absolute;
  left: 0;
  right: 0;
  top: 100%;
  margin-top: 0.5rem;
  padding: 0.75rem;
  background: #1f2937;
  color: white;
  border-radius: 0.5rem;
  font-size: 0.75rem;
  z-index: 10;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
}

.tooltip-title {
  font-weight: 600;
  font-size: 0.875rem;
  margin-bottom: 0.5rem;
}

.tooltip-desc {
  color: #d1d5db;
  margin-bottom: 0.5rem;
}

.tooltip-scenarios {
  margin-bottom: 0.5rem;
}

.tooltip-label {
  color: #9ca3af;
  margin-bottom: 0.25rem;
}

.tooltip-scenarios ul {
  list-style: disc;
  padding-left: 1rem;
  color: #d1d5db;
}

.tooltip-scenarios li {
  margin-bottom: 0.125rem;
}

.tooltip-style {
  color: #d1d5db;
}

.selection-summary {
  margin-top: 1rem;
  padding: 0.75rem;
  background: #f9fafb;
  border-radius: 0.5rem;
}

.summary-label {
  font-size: 0.875rem;
  font-weight: 500;
  color: #4b5563;
  margin-bottom: 0.5rem;
}

.summary-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
}

.intent-tag {
  display: inline-flex;
  align-items: center;
  padding: 0.25rem 0.75rem;
  background: #dbeafe;
  color: #1e40af;
  font-size: 0.875rem;
  border-radius: 9999px;
}

.tag-remove {
  margin-left: 0.25rem;
  width: 1rem;
  height: 1rem;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  background: transparent;
  border: none;
  color: #3b82f6;
  cursor: pointer;
}

.tag-remove:hover {
  background: #bfdbfe;
}

.combo-hint {
  margin-top: 0.5rem;
  font-size: 0.75rem;
  color: #6b7280;
}
</style>
