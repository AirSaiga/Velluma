<template>
  <div class="intent-driven-panel">
    <!-- 头部沉浸区 -->
    <div class="panel-hero">
      <div class="hero-badge">
        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z" />
        </svg>
        <span>AI 智能创作</span>
      </div>
      <h2 class="hero-title">让 AI 理解你的创作意图</h2>
      <p class="hero-subtitle">选择创作方向，系统将自动优化生成策略</p>
    </div>

    <!-- 主内容区 -->
    <div class="panel-content">
      <!-- 意图选择区 -->
      <section class="content-section">
        <IntentSelector />
      </section>
      
      <!-- 章节目标区（可折叠） -->
      <section class="content-section">
        <button 
          class="section-toggle" 
          :class="{ 'is-open': showGoals }"
          @click="showGoals = !showGoals"
        >
          <div class="toggle-icon">
            <svg class="w-4 h-4" :class="{ 'rotate-180': showGoals }" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
            </svg>
          </div>
          <span class="toggle-label">章节目标</span>
          <span class="toggle-badge">可选</span>
          <div class="toggle-hint">设定本章要达成的具体目标</div>
        </button>
        <Transition name="expand">
          <div v-show="showGoals" class="section-body">
            <GoalSelector />
          </div>
        </Transition>
      </section>
      
      <!-- 推荐方案区 -->
      <Transition name="fade-up">
        <section v-if="hasSelection" class="content-section">
          <div class="section-header">
            <div class="section-icon recommended">
              <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
              </svg>
            </div>
            <div class="section-info">
              <h4 class="section-title">推荐方案</h4>
              <p class="section-desc">基于您的意图匹配的最佳生成策略</p>
            </div>
          </div>
          <div class="plans-grid">
            <RecommendedPlanCard
              v-for="plan in recommendedPlans"
              :key="plan.plan_id"
              :plan="plan"
              :is-selected="selectedPlanType === plan.plan_type"
              @select="selectPlanType"
            />
          </div>
        </section>
      </Transition>
      
      <!-- 基础可调项 -->
      <Transition name="fade-up">
        <section v-if="hasSelection" class="content-section">
          <div class="section-header">
            <div class="section-icon adjustments">
              <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 6V4m0 2a2 2 0 100 4m0-4a2 2 0 110 4m-6 8a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4m6 6v10m6-2a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4" />
              </svg>
            </div>
            <div class="section-info">
              <h4 class="section-title">基础调整</h4>
              <p class="section-desc">微调生成参数以获得理想效果</p>
            </div>
          </div>
          
          <div class="adjustments-grid">
            <div class="adjustment-card">
              <label class="adjustment-label">
                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                </svg>
                本章篇幅
              </label>
              <div class="word-count-control">
                <button 
                  class="count-btn" 
                  @click="wordCount = Math.max(500, wordCount - 500)"
                  :disabled="wordCount <= 500"
                >
                  <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M20 12H4" />
                  </svg>
                </button>
                <div class="count-display">
                  <span class="count-value">{{ wordCount.toLocaleString() }}</span>
                  <span class="count-unit">字</span>
                </div>
                <button 
                  class="count-btn" 
                  @click="wordCount = Math.min(10000, wordCount + 500)"
                  :disabled="wordCount >= 10000"
                >
                  <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4" />
                  </svg>
                </button>
              </div>
            </div>
            
            <div class="adjustment-card full-width">
              <label class="adjustment-label">
                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
                </svg>
                附加说明
              </label>
              <textarea 
                v-model="authorIntent"
                class="intent-textarea"
                placeholder="补充个性化要求，如：增加悬疑感、重点描写环境、强化人物对话..."
                rows="3"
              />
            </div>
          </div>
        </section>
      </Transition>
      
      <!-- 专家模式折叠区 -->
      <Transition name="fade-up">
        <section v-if="hasSelection" class="content-section expert-section">
          <button 
            class="expert-toggle" 
            :class="{ 'is-open': isExpertModeExpanded, 'has-overrides': hasOverrides }"
            @click="toggleExpertMode"
          >
            <div class="toggle-main">
              <div class="toggle-icon expert">
                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19.428 15.428a2 2 0 00-1.022-.547l-2.387-.477a6 6 0 00-3.86.517l-.318.158a6 6 0 01-3.86.517L6.05 15.21a2 2 0 00-1.806.547M8 4h8l-1 1v5.172a2 2 0 00.586 1.414l5 5c1.26 1.26.367 3.414-1.415 3.414H4.828c-1.782 0-2.674-2.154-1.414-3.414l5-5A2 2 0 009 10.172V5L8 4z" />
                </svg>
              </div>
              <div class="toggle-info">
                <span class="toggle-label">专家模式</span>
                <span class="toggle-desc">高级参数手动调整</span>
              </div>
            </div>
            <div class="toggle-badges">
              <span v-if="hasOverrides" class="override-badge">
                {{ overrideCount }} 项已修改
              </span>
              <svg class="w-5 h-5 toggle-arrow" :class="{ 'rotate-180': isExpertModeExpanded }" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
              </svg>
            </div>
          </button>
          
          <ExpertOverridePanel
            :is-expanded="isExpertModeExpanded"
            :recommended-policy="recommendedPlan?.policy || null"
          />
        </section>
      </Transition>
    </div>
    
    <!-- 底部操作栏 -->
    <Transition name="slide-up">
      <div v-if="hasSelection" class="panel-footer">
        <div class="generation-preview">
          <div class="preview-item">
            <div class="preview-icon">
              <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M7 20l4-16m2 16l4-16M6 9h14M4 15h14" />
              </svg>
            </div>
            <div class="preview-info">
              <span class="preview-label">{{ selectedIntents.length }} 个创作意图</span>
              <span class="preview-value">已选择</span>
            </div>
          </div>
          <div class="preview-divider"></div>
          <div class="preview-item">
            <div class="preview-icon time">
              <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
            </div>
            <div class="preview-info">
              <span class="preview-label">预计时间</span>
              <span class="preview-value">{{ recommendedPlan?.estimated_time || '2-3 分钟' }}</span>
            </div>
          </div>
          <div class="preview-divider"></div>
          <div class="preview-item">
            <div class="preview-icon words">
              <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
              </svg>
            </div>
            <div class="preview-info">
              <span class="preview-label">生成长度</span>
              <span class="preview-value">{{ wordCount.toLocaleString() }} 字</span>
            </div>
          </div>
        </div>
        
        <div class="footer-actions">
          <button
            class="action-btn secondary"
            :disabled="!canGenerate"
            @click="handleSave"
          >
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 7H5a2 2 0 00-2 2v9a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-3m-1 4l-3 3m0 0l-3-3m3 3V4" />
            </svg>
            保存设置
          </button>
          <button
            class="action-btn primary"
            :disabled="!canGenerate"
            @click="handleGenerate"
          >
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z" />
            </svg>
            开始生成
          </button>
        </div>
      </div>
    </Transition>
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
  save: [payload: any]
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

function handleSave() {
  const payload = buildPayload({
    chapterId: props.chapterId,
    apiConfig: props.apiConfig,
    wordCount: wordCount.value,
    authorIntent: authorIntent.value
  })

  emit('save', payload)
}

function handleGenerate() {
  const payload = buildPayload({
    chapterId: props.chapterId,
    apiConfig: props.apiConfig,
    wordCount: wordCount.value,
    authorIntent: authorIntent.value,
    generate: true
  })

  emit('generate', payload)
}
</script>

<style scoped>
/* 面板容器 */
.intent-driven-panel {
  display: flex;
  flex-direction: column;
  min-height: 100%;
  background: var(--bg-canvas, #f8fafc);
}

/* 头部沉浸区 */
.panel-hero {
  padding: 2rem 1.5rem 1.5rem;
  background: linear-gradient(135deg, var(--accent-500, #6366f1) 0%, var(--accent-600, #4f46e5) 100%);
  color: white;
  text-align: center;
  position: relative;
  overflow: hidden;
}

.panel-hero::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: 
    radial-gradient(circle at 20% 80%, rgba(255,255,255,0.1) 0%, transparent 50%),
    radial-gradient(circle at 80% 20%, rgba(255,255,255,0.1) 0%, transparent 50%);
  pointer-events: none;
}

.hero-badge {
  display: inline-flex;
  align-items: center;
  gap: 0.375rem;
  padding: 0.375rem 0.875rem;
  background: rgba(255,255,255,0.15);
  backdrop-filter: blur(8px);
  border-radius: 9999px;
  font-size: 0.75rem;
  font-weight: 500;
  margin-bottom: 0.75rem;
  position: relative;
  border: 1px solid rgba(255,255,255,0.2);
}

.hero-title {
  font-size: 1.5rem;
  font-weight: 700;
  margin-bottom: 0.375rem;
  position: relative;
  text-shadow: 0 1px 2px rgba(0,0,0,0.1);
}

.hero-subtitle {
  font-size: 0.875rem;
  opacity: 0.9;
  position: relative;
}

/* 主内容区 */
.panel-content {
  flex: 1;
  padding: 1.25rem;
  padding-bottom: 2rem; /* 增加底部 padding */
  display: flex;
  flex-direction: column;
  gap: 1rem;
  overflow-y: auto;
}

.content-section {
  background: var(--bg-primary, white);
  border-radius: 1rem;
  border: 1px solid var(--border-color, #e2e8f0);
  overflow: visible; /* 改为 visible 避免截断内部内容 */
  transition: box-shadow 0.2s ease;
}

.content-section:hover {
  box-shadow: 0 4px 12px rgba(0,0,0,0.04);
}

/* 区域折叠按钮 */
.section-toggle {
  width: 100%;
  padding: 1rem 1.25rem;
  display: flex;
  align-items: center;
  gap: 0.75rem;
  background: transparent;
  border: none;
  cursor: pointer;
  transition: all 0.2s ease;
  text-align: left;
}

.section-toggle:hover {
  background: var(--bg-hover, #f8fafc);
}

.section-toggle.is-open {
  border-bottom: 1px solid var(--border-color, #e2e8f0);
}

.toggle-icon {
  width: 2rem;
  height: 2rem;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--bg-canvas, #f1f5f9);
  border-radius: 0.5rem;
  color: var(--text-secondary, #64748b);
  transition: all 0.2s ease;
}

.section-toggle:hover .toggle-icon {
  background: var(--accent-50, #eef2ff);
  color: var(--accent-500, #6366f1);
}

.toggle-icon svg {
  transition: transform 0.3s ease;
}

.toggle-label {
  font-size: 0.9375rem;
  font-weight: 600;
  color: var(--text-primary, #1e293b);
}

.toggle-badge {
  padding: 0.125rem 0.5rem;
  background: var(--bg-canvas, #f1f5f9);
  color: var(--text-muted, #94a3b8);
  font-size: 0.6875rem;
  font-weight: 500;
  border-radius: 9999px;
}

.toggle-hint {
  margin-left: auto;
  font-size: 0.8125rem;
  color: var(--text-muted, #94a3b8);
}

.section-body {
  padding: 1rem 1.25rem 1.25rem;
}

/* 区域头部 */
.section-header {
  padding: 1.25rem;
  display: flex;
  align-items: flex-start;
  gap: 0.875rem;
  border-bottom: 1px solid var(--border-color, #e2e8f0);
}

.section-icon {
  width: 2.25rem;
  height: 2.25rem;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 0.625rem;
  flex-shrink: 0;
}

.section-icon.recommended {
  background: linear-gradient(135deg, #fef3c7 0%, #fde68a 100%);
  color: #d97706;
}

.section-icon.adjustments {
  background: linear-gradient(135deg, #dbeafe 0%, #93c5fd 100%);
  color: #2563eb;
}

.section-info {
  flex: 1;
  min-width: 0;
}

.section-title {
  font-size: 0.9375rem;
  font-weight: 600;
  color: var(--text-primary, #1e293b);
  margin-bottom: 0.25rem;
}

.section-desc {
  font-size: 0.8125rem;
  color: var(--text-secondary, #64748b);
}

/* 方案网格 */
.plans-grid {
  padding: 1.25rem;
  display: grid;
  grid-template-columns: repeat(1, 1fr);
  gap: 0.875rem;
}

@media (min-width: 768px) {
  .plans-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}

/* 调整区网格 */
.adjustments-grid {
  padding: 1.25rem;
  display: grid;
  grid-template-columns: repeat(1, 1fr);
  gap: 1rem;
}

@media (min-width: 640px) {
  .adjustments-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}

.adjustment-card {
  padding: 1rem;
  background: var(--bg-canvas, #f8fafc);
  border-radius: 0.75rem;
  border: 1px solid var(--border-color, #e2e8f0);
}

.adjustment-card.full-width {
  grid-column: 1 / -1;
}

.adjustment-label {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.8125rem;
  font-weight: 500;
  color: var(--text-secondary, #64748b);
  margin-bottom: 0.75rem;
}

/* 字数控制 */
.word-count-control {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.75rem;
}

.count-btn {
  width: 2.25rem;
  height: 2.25rem;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--bg-primary, white);
  border: 1px solid var(--border-color, #e2e8f0);
  border-radius: 0.5rem;
  color: var(--text-secondary, #64748b);
  cursor: pointer;
  transition: all 0.2s ease;
}

.count-btn:hover:not(:disabled) {
  background: var(--accent-50, #eef2ff);
  border-color: var(--accent-200, #c7d2fe);
  color: var(--accent-600, #4f46e5);
}

.count-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.count-display {
  display: flex;
  align-items: baseline;
  gap: 0.25rem;
  min-width: 5rem;
  justify-content: center;
}

.count-value {
  font-size: 1.25rem;
  font-weight: 700;
  color: var(--text-primary, #1e293b);
  font-variant-numeric: tabular-nums;
}

.count-unit {
  font-size: 0.75rem;
  color: var(--text-muted, #94a3b8);
}

/* 意图输入框 */
.intent-textarea {
  width: 100%;
  padding: 0.875rem 1rem;
  background: var(--bg-primary, white);
  border: 1px solid var(--border-color, #e2e8f0);
  border-radius: 0.625rem;
  font-size: 0.875rem;
  color: var(--text-primary, #1e293b);
  resize: vertical;
  min-height: 5rem;
  transition: all 0.2s ease;
}

.intent-textarea:focus {
  outline: none;
  border-color: var(--accent-400, #818cf8);
  box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.1);
}

.intent-textarea::placeholder {
  color: var(--text-muted, #94a3b8);
}

/* 专家模式区 */
.expert-section {
  background: var(--bg-canvas, #f8fafc);
}

.expert-toggle {
  width: 100%;
  padding: 1rem 1.25rem;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  background: transparent;
  border: none;
  cursor: pointer;
  transition: all 0.2s ease;
}

.expert-toggle:hover {
  background: var(--bg-hover, #f1f5f9);
}

.toggle-main {
  display: flex;
  align-items: center;
  gap: 0.875rem;
}

.toggle-icon.expert {
  width: 2.25rem;
  height: 2.25rem;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #ede9fe 0%, #c4b5fd 100%);
  color: #7c3aed;
  border-radius: 0.625rem;
}

.expert-toggle.has-overrides .toggle-icon.expert {
  background: linear-gradient(135deg, #fef3c7 0%, #fcd34d 100%);
  color: #d97706;
}

.toggle-info {
  text-align: left;
}

.toggle-label {
  display: block;
  font-size: 0.9375rem;
  font-weight: 600;
  color: var(--text-primary, #1e293b);
  margin-bottom: 0.125rem;
}

.toggle-desc {
  font-size: 0.8125rem;
  color: var(--text-secondary, #64748b);
}

.toggle-badges {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.override-badge {
  padding: 0.25rem 0.625rem;
  background: linear-gradient(135deg, #fef3c7 0%, #fde68a 100%);
  color: #b45309;
  font-size: 0.75rem;
  font-weight: 500;
  border-radius: 9999px;
}

.toggle-arrow {
  color: var(--text-muted, #94a3b8);
  transition: transform 0.3s ease;
}

/* 底部操作栏 */
.panel-footer {
  padding: 1rem 1.25rem;
  background: var(--bg-primary, white);
  border-top: 1px solid var(--border-color, #e2e8f0);
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

@media (min-width: 640px) {
  .panel-footer {
    flex-direction: row;
    align-items: center;
    justify-content: space-between;
  }
}

.generation-preview {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  flex-wrap: wrap;
}

.preview-item {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.preview-icon {
  width: 1.75rem;
  height: 1.75rem;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--bg-canvas, #f1f5f9);
  border-radius: 0.375rem;
  color: var(--text-muted, #94a3b8);
}

.preview-icon.time {
  background: linear-gradient(135deg, #dbeafe 0%, #bfdbfe 100%);
  color: #3b82f6;
}

.preview-icon.words {
  background: linear-gradient(135deg, #d1fae5 0%, #a7f3d0 100%);
  color: #10b981;
}

.preview-info {
  display: flex;
  flex-direction: column;
}

.preview-label {
  font-size: 0.6875rem;
  color: var(--text-muted, #94a3b8);
}

.preview-value {
  font-size: 0.8125rem;
  font-weight: 600;
  color: var(--text-primary, #1e293b);
}

.preview-divider {
  width: 1px;
  height: 2rem;
  background: var(--border-color, #e2e8f0);
}

.footer-actions {
  display: flex;
  gap: 0.625rem;
}

.action-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  padding: 0.625rem 1.25rem;
  font-size: 0.875rem;
  font-weight: 500;
  border-radius: 0.625rem;
  border: none;
  cursor: pointer;
  transition: all 0.2s ease;
}

.action-btn.secondary {
  background: var(--bg-canvas, #f1f5f9);
  color: var(--text-secondary, #64748b);
  border: 1px solid var(--border-color, #e2e8f0);
}

.action-btn.secondary:hover:not(:disabled) {
  background: var(--bg-hover, #e2e8f0);
  color: var(--text-primary, #1e293b);
}

.action-btn.primary {
  background: linear-gradient(135deg, var(--accent-500, #6366f1) 0%, var(--accent-600, #4f46e5) 100%);
  color: white;
  box-shadow: 0 4px 12px rgba(99, 102, 241, 0.3);
}

.action-btn.primary:hover:not(:disabled) {
  transform: translateY(-1px);
  box-shadow: 0 6px 16px rgba(99, 102, 241, 0.4);
}

.action-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
  transform: none !important;
  box-shadow: none !important;
}

/* 过渡动画 */
.expand-enter-active,
.expand-leave-active {
  transition: all 0.3s ease;
  max-height: 500px;
  overflow: hidden;
}

.expand-enter-from,
.expand-leave-to {
  max-height: 0;
  opacity: 0;
}

.fade-up-enter-active {
  transition: all 0.4s cubic-bezier(0.16, 1, 0.3, 1);
}

.fade-up-enter-from {
  opacity: 0;
  transform: translateY(12px);
}

.slide-up-enter-active {
  transition: all 0.4s cubic-bezier(0.16, 1, 0.3, 1);
}

.slide-up-enter-from {
  opacity: 0;
  transform: translateY(20px);
}

/* 深色模式适配 */
@media (prefers-color-scheme: dark) {
  .panel-hero {
    background: linear-gradient(135deg, #4f46e5 0%, #3730a3 100%);
  }
  
  .content-section {
    background: #1e293b;
    border-color: #334155;
  }
  
  .section-toggle:hover,
  .expert-toggle:hover {
    background: #0f172a;
  }
  
  .adjustment-card {
    background: #0f172a;
    border-color: #334155;
  }
  
  .count-btn {
    background: #1e293b;
    border-color: #334155;
  }
  
  .intent-textarea {
    background: #1e293b;
    border-color: #334155;
    color: #f1f5f9;
  }
  
  .expert-section {
    background: #0f172a;
  }
  
  .panel-footer {
    background: #1e293b;
    border-color: #334155;
  }
  
  .action-btn.secondary {
    background: #334155;
    border-color: #475569;
    color: #94a3b8;
  }
}
</style>
