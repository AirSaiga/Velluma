<template>
  <div class="intent-driven-panel">
    <!-- 意图选择区 -->
    <IntentSelector />
    
    <!-- 章节目标区（可折叠） -->
    <div class="section-collapsible">
      <button class="section-toggle" @click="showGoals = !showGoals">
        <span class="toggle-icon">{{ showGoals ? '▼' : '▶' }}</span>
        <span>章节目标（可选）</span>
      </button>
      <GoalSelector v-if="showGoals" />
    </div>
    
    <!-- 推荐方案区 -->
    <div class="recommended-plans" v-if="hasSelection">
      <h4 class="section-title">系统推荐方案</h4>
      <div class="plans-grid">
        <RecommendedPlanCard
          v-for="plan in recommendedPlans"
          :key="plan.plan_id"
          :plan="plan"
          :is-selected="selectedPlanType === plan.plan_type"
          @select="selectPlanType"
        />
      </div>
    </div>
    
    <!-- 基础可调项 -->
    <div class="basic-adjustments" v-if="hasSelection">
      <h4 class="section-title">基础调整</h4>
      <div class="adjustment-row">
        <label>本章篇幅</label>
        <input 
          type="number" 
          v-model.number="wordCount"
          min="500"
          max="10000"
          step="500"
        />
        <span class="unit">字</span>
      </div>
      <div class="adjustment-row">
        <label>附加说明</label>
        <textarea 
          v-model="authorIntent"
          placeholder="补充个性化要求，如“增加悬疑感”、“重点描写环境”等"
          rows="2"
        ></textarea>
      </div>
    </div>
    
    <!-- 专家模式折叠区 -->
    <div class="expert-section" v-if="hasSelection">
      <button class="expert-toggle" @click="toggleExpertMode">
        <span class="toggle-icon">{{ isExpertModeExpanded ? '▼' : '▶' }}</span>
        <span>专家模式（手动调参）</span>
        <span class="expert-badge" v-if="hasOverrides">
          {{ overrideCount }} 项已修改
        </span>
      </button>
      
      <ExpertOverridePanel
        :is-expanded="isExpertModeExpanded"
        :recommended-policy="recommendedPlan?.policy || null"
      />
    </div>
    
    <!-- 生成按钮 -->
    <div class="generate-actions">
      <button 
        class="generate-btn primary"
        :disabled="!canGenerate"
        @click="handleGenerate"
      >
        开始生成
      </button>
      <div class="generation-summary" v-if="hasSelection">
        <span class="summary-item">
          🎯 {{ selectedIntents.length }} 个意图
        </span>
        <span class="summary-item">
          ⏱️ {{ recommendedPlan?.estimated_time || '约 2-3 分钟' }}
        </span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { useIntentDrivenConfig } from '../useIntentDrivenConfig'
import IntentSelector from './IntentSelector.vue'
import GoalSelector from './GoalSelector.vue'
import RecommendedPlanCard from './RecommendedPlanCard.vue'
import ExpertOverridePanel from './ExpertOverridePanel.vue'

const props = defineProps<{
  chapterId: string
  apiConfig: {
    api_key: string
    base_url?: string
    model?: string
  }
}>()

const emit = defineEmits<{
  generate: [payload: any]
}>()

const {
  selectedIntents,
  hasSelection,
  recommendedPlans,
  recommendedPlan,
  selectedPlanType,
  hasOverrides,
  overrideCount,
  isExpertModeExpanded,
  selectPlanType,
  toggleExpertMode,
  buildPayload
} = useIntentDrivenConfig()

const showGoals = ref(false)
const wordCount = ref(3000)
const authorIntent = ref('')

const canGenerate = computed(() => {
  return hasSelection.value && wordCount.value >= 500
})

function handleGenerate() {
  const payload = buildPayload({
    chapterId: props.chapterId,
    apiConfig: props.apiConfig,
    wordCount: wordCount.value,
    authorIntent: authorIntent.value
  })
  
  emit('generate', payload)
}
</script>

<style scoped>
.intent-driven-panel {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.section-collapsible {
  border: 1px solid #e5e7eb;
  border-radius: 0.5rem;
  overflow: hidden;
}

.section-toggle {
  width: 100%;
  padding: 0.75rem 1rem;
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.875rem;
  font-weight: 500;
  color: #374151;
  background: #f9fafb;
  border: none;
  cursor: pointer;
}

.section-toggle:hover {
  background: #f3f4f6;
}

.toggle-icon {
  font-size: 0.75rem;
  color: #9ca3af;
}

.recommended-plans {
  padding: 1rem;
  background: white;
  border: 1px solid #e5e7eb;
  border-radius: 0.5rem;
}

.section-title {
  font-size: 0.875rem;
  font-weight: 600;
  color: #374151;
  margin-bottom: 0.75rem;
}

.plans-grid {
  display: grid;
  grid-template-columns: repeat(1, 1fr);
  gap: 0.75rem;
}

@media (min-width: 768px) {
  .plans-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}

@media (min-width: 1024px) {
  .plans-grid {
    grid-template-columns: repeat(3, 1fr);
  }
}

.basic-adjustments {
  padding: 1rem;
  background: #f9fafb;
  border-radius: 0.5rem;
}

.adjustment-row {
  display: flex;
  align-items: flex-start;
  gap: 0.75rem;
  margin-bottom: 0.75rem;
}

.adjustment-row:last-child {
  margin-bottom: 0;
}

.adjustment-row label {
  width: 6rem;
  font-size: 0.875rem;
  color: #374151;
  padding-top: 0.25rem;
}

.adjustment-row input[type="number"] {
  width: 8rem;
  padding: 0.375rem 0.75rem;
  border: 1px solid #d1d5db;
  border-radius: 0.375rem;
  font-size: 0.875rem;
}

.adjustment-row textarea {
  flex: 1;
  padding: 0.375rem 0.75rem;
  border: 1px solid #d1d5db;
  border-radius: 0.375rem;
  font-size: 0.875rem;
  resize: none;
}

.unit {
  font-size: 0.75rem;
  color: #9ca3af;
  padding-top: 0.375rem;
}

.expert-section {
  border: 1px solid #e5e7eb;
  border-radius: 0.5rem;
  overflow: hidden;
}

.expert-toggle {
  width: 100%;
  padding: 0.75rem 1rem;
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.875rem;
  font-weight: 500;
  color: #374151;
  background: #f9fafb;
  border: none;
  cursor: pointer;
}

.expert-toggle:hover {
  background: #f3f4f6;
}

.expert-badge {
  margin-left: auto;
  padding: 0.125rem 0.5rem;
  font-size: 0.75rem;
  background: #fef3c7;
  color: #92400e;
  border-radius: 0.25rem;
}

.generate-actions {
  padding-top: 1rem;
  border-top: 1px solid #e5e7eb;
}

.generate-btn {
  width: 100%;
  padding: 0.75rem;
  font-size: 1rem;
  font-weight: 600;
  border-radius: 0.5rem;
  border: none;
  cursor: pointer;
  transition: all 0.2s;
}

.generate-btn.primary {
  background: #3b82f6;
  color: white;
}

.generate-btn.primary:hover {
  background: #2563eb;
}

.generate-btn:disabled {
  background: #d1d5db;
  color: #6b7280;
  cursor: not-allowed;
}

.generation-summary {
  display: flex;
  justify-content: center;
  gap: 1rem;
  margin-top: 0.75rem;
  font-size: 0.875rem;
  color: #6b7280;
}

.summary-item {
  display: flex;
  align-items: center;
  gap: 0.25rem;
}
</style>
