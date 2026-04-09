<template>
  <div class="intent-panel-layout">
    <!-- 左侧导航栏 -->
    <aside class="panel-sidebar">
      <div class="sidebar-header">
        <div class="brand-icon">
          <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z" />
          </svg>
        </div>
        <h2 class="brand-title">AI 智能创作</h2>
      </div>

      <nav class="sidebar-nav">
        <button
          v-for="(page, idx) in workflowPages"
          :key="page.key"
          type="button"
          class="nav-node"
          :class="{
            'is-active': currentWorkflowPage === page.key,
            'is-complete': isWorkflowPageComplete(page.key),
            'is-disabled': !canSwitchWorkflowPage(page.key)
          }"
          :disabled="!canSwitchWorkflowPage(page.key)"
          @click="setWorkflowPage(page.key)"
        >
          <div class="node-indicator">
            <div class="node-dot">
              <svg v-if="isWorkflowPageComplete(page.key) && currentWorkflowPage !== page.key" class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="3" d="M5 13l4 4L19 7" />
              </svg>
              <span v-else>{{ idx + 1 }}</span>
            </div>
            <div class="node-line" v-if="idx < workflowPages.length - 1"></div>
          </div>
          
          <div class="node-content">
            <div class="node-header">
              <div class="node-title">{{ page.label }}</div>
              <div class="node-badge" v-if="page.required">必选</div>
            </div>
            
            <!-- 动态摘要展示 -->
            <div class="node-summary-wrapper">
              <Transition name="fade-slide" mode="out-in">
                <div v-if="page.key === 'setup' && hasSelection" class="node-summary">
                  已选 {{ selectedIntents.length }} 意图, {{ selectedGoals.length }} 目标
                </div>
                <div v-else-if="page.key === 'plan' && selectedPlanType" class="node-summary">
                  {{ getPlanName(selectedPlanType) }}
                </div>
                <div v-else-if="page.key === 'expert' && overrideCount > 0" class="node-summary">
                  {{ overrideCount }} 项参数已覆盖
                </div>
                <div v-else class="node-desc">{{ page.desc }}</div>
              </Transition>
            </div>
          </div>
        </button>
      </nav>

      <!-- 左侧底部操作栏 -->
      <div class="sidebar-footer">
        <button
          class="sidebar-action-btn ghost"
          :disabled="!canGenerate"
          @click="handleSave"
        >
          <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 7H5a2 2 0 00-2 2v9a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-3m-1 4l-3 3m0 0l-3-3m3 3V4" />
          </svg>
          保存设置
        </button>
      </div>
    </aside>

    <!-- 右侧内容区 -->
    <main class="panel-main">
      <div class="main-scroll-area">
        <Transition name="fade-slide-up" mode="out-in">
          
          <!-- 1. 意图与目标 -->
          <section v-if="currentWorkflowPage === 'setup'" key="setup" class="workflow-section">
            <div class="section-header">
              <h1 class="section-title">设定创作基调</h1>
              <p class="section-desc">选择您的核心意图与具体目标，AI 将据此规划最合适的生成策略。</p>
            </div>
            
            <div class="setup-content-stack">
              <IntentSelector />
              <div class="content-divider"></div>
              <GoalSelector />
            </div>
          </section>

          <!-- 2. 推荐方案 -->
          <section v-else-if="currentWorkflowPage === 'plan'" key="plan" class="workflow-section">
            <div class="section-header">
              <h1 class="section-title">推荐生成方案</h1>
              <p class="section-desc">基于您的设定，我们为您准备了以下生成策略。</p>
            </div>
            
            <div v-if="!hasSelection" class="empty-state">
              <div class="empty-icon">⚠️</div>
              <p>请先返回上一步，至少选择 1 个创作意图。</p>
            </div>
            <div v-else class="plans-grid">
              <RecommendedPlanCard
                v-for="plan in recommendedPlans"
                :key="plan.plan_id"
                :plan="plan"
                :is-selected="selectedPlanType === plan.plan_type"
                @select="selectPlanType"
              />
            </div>
          </section>

          <!-- 3. 基础调整 -->
          <section v-else-if="currentWorkflowPage === 'adjust'" key="adjust" class="workflow-section">
            <div class="section-header">
              <h1 class="section-title">基础调整</h1>
              <p class="section-desc">微调篇幅与补充说明，确保内容完全符合您的要求。</p>
            </div>
            
            <div class="adjustments-stack">
              <div class="control-card">
                <div class="control-header">
                  <div class="control-icon-box">
                    <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" /></svg>
                  </div>
                  <span class="control-title">本章篇幅</span>
                </div>
                <div class="word-count-control">
                  <button class="count-btn" @click="wordCount = Math.max(500, wordCount - 500)" :disabled="wordCount <= 500">
                    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M20 12H4" /></svg>
                  </button>
                  <div class="count-display">
                    <span class="count-value">{{ wordCount.toLocaleString() }}</span>
                    <span class="count-unit">字</span>
                  </div>
                  <button class="count-btn" @click="wordCount = Math.min(10000, wordCount + 500)" :disabled="wordCount >= 10000">
                    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4" /></svg>
                  </button>
                </div>
              </div>

              <div class="control-card">
                <div class="control-header">
                  <div class="control-icon-box">
                    <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" /></svg>
                  </div>
                  <span class="control-title">附加说明</span>
                </div>
                <textarea 
                  v-model="authorIntent"
                  class="sleek-textarea"
                  placeholder="在此输入任何额外的提示，例如：增加悬疑感、强化反派气场..."
                  rows="4"
                ></textarea>
              </div>
            </div>
          </section>

          <!-- 4. 专家模式 -->
          <section v-else-if="currentWorkflowPage === 'expert'" key="expert" class="workflow-section">
            <div class="section-header">
              <h1 class="section-title">专家控制中心</h1>
              <p class="section-desc">深度介入 AI 的生成逻辑。仅建议有经验的创作者使用。</p>
            </div>
            
            <div class="expert-panel-wrapper">
              <ExpertOverridePanel
                :is-expanded="true"
                :recommended-policy="recommendedPlan?.policy || null"
              />
            </div>
          </section>
        </Transition>
        
        <!-- 底部留白 -->
        <div class="bottom-spacer"></div>

      </div>
    </main>
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
  selectedGoals,
  hasSelection,
  recommendedPlans,
  recommendedPlan,
  selectedPlanType,
  overrideCount,
  selectPlanType,
  buildPayload
} = useIntentDrivenConfig()

type WorkflowPageKey = 'setup' | 'plan' | 'adjust' | 'expert'
const workflowPages: Array<{ key: WorkflowPageKey; label: string; required: boolean; desc: string }> = [
  { key: 'setup', label: '意图与目标', required: true, desc: '设定基调与方向' },
  { key: 'plan', label: '推荐方案', required: true, desc: '选择最佳策略' },
  { key: 'adjust', label: '基础调整', required: false, desc: '篇幅与细节补充' },
  { key: 'expert', label: '专家模式', required: false, desc: '高级参数控制' }
]

const currentWorkflowPage = ref<WorkflowPageKey>('setup')
const wordCount = ref(3000)
const authorIntent = ref('')

const canGenerate = computed(() => {
  return hasSelection.value && wordCount.value >= 500
})

const currentWorkflowIndex = computed(() => {
  return workflowPages.findIndex(page => page.key === currentWorkflowPage.value)
})

const canGoWorkflowPrev = computed(() => currentWorkflowIndex.value > 0)

const canProceedCurrentPage = computed(() => {
  if (currentWorkflowPage.value === 'setup') {
    return selectedIntents.value.length > 0
  }
  if (currentWorkflowPage.value === 'plan') {
    return hasSelection.value && recommendedPlans.value.length > 0 && Boolean(selectedPlanType.value)
  }
  return true
})

const currentPageBlockReason = computed(() => {
  if (currentWorkflowPage.value === 'setup' && selectedIntents.value.length === 0) {
    return '请至少选择 1 个创作意图后再进入下一步'
  }
  if (currentWorkflowPage.value === 'plan') {
    if (!hasSelection.value) {
      return '请先完成意图与目标设置'
    }
    if (recommendedPlans.value.length === 0) {
      return '暂无可用推荐方案，请先调整意图与目标'
    }
    if (!selectedPlanType.value) {
      return '请选择一个推荐方案'
    }
  }
  return ''
})

const canGoWorkflowNext = computed(() => {
  return currentWorkflowIndex.value < workflowPages.length - 1
})

function getPlanName(type: string) {
  const map: Record<string, string> = {
    balanced: '均衡推荐',
    fast: '快速生成',
    quality: '高质量',
    creative: '创意优先'
  }
  return map[type] || type
}

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

function isWorkflowPageComplete(page: WorkflowPageKey): boolean {
  if (page === 'setup') {
    return selectedIntents.value.length > 0
  }
  if (page === 'plan') {
    return hasSelection.value && recommendedPlans.value.length > 0 && Boolean(selectedPlanType.value)
  }
  return true
}

function canSwitchWorkflowPage(page: WorkflowPageKey): boolean {
  const targetIndex = workflowPages.findIndex(item => item.key === page)
  if (targetIndex <= currentWorkflowIndex.value) {
    return true
  }
  for (let i = currentWorkflowIndex.value; i < targetIndex; i++) {
    const pageKey = workflowPages[i].key
    if (pageKey === 'setup' && selectedIntents.value.length === 0) {
      return false
    }
    if (pageKey === 'plan') {
      if (!hasSelection.value || recommendedPlans.value.length === 0 || !selectedPlanType.value) {
        return false
      }
    }
  }
  return true
}

function setWorkflowPage(page: WorkflowPageKey) {
  if (canSwitchWorkflowPage(page)) {
    currentWorkflowPage.value = page
  }
}

function goWorkflowPrev() {
  if (!canGoWorkflowPrev.value) return
  const prev = workflowPages[currentWorkflowIndex.value - 1]
  currentWorkflowPage.value = prev.key
}

function goWorkflowNext() {
  if (!canGoWorkflowNext.value || !canProceedCurrentPage.value) return
  const next = workflowPages[currentWorkflowIndex.value + 1]
  currentWorkflowPage.value = next.key
}
</script>

<style scoped>
/* 核心布局: 左右分屏 */
.intent-panel-layout {
  display: flex;
  flex-direction: row;
  width: 100%;
  height: 100%;
  min-height: 0; /* 取消 600px 最小高度，允许完全自适应 */
  background: var(--bg-canvas, #f8fafc);
  overflow: hidden;
}

/* 左侧导航栏 */
.panel-sidebar {
  flex: 0 0 280px;
  display: flex;
  flex-direction: column;
  background: linear-gradient(180deg, #ffffff 0%, rgba(255,255,255,0.6) 100%);
  border-right: 1px solid rgba(226, 232, 240, 0.8);
  backdrop-filter: blur(20px);
  z-index: 10;
  height: 100%;
  overflow-y: auto;
}

.sidebar-header {
  padding: 2rem 1.5rem;
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.brand-icon {
  width: 2.5rem;
  height: 2.5rem;
  border-radius: 0.75rem;
  background: linear-gradient(135deg, #6366f1 0%, #4f46e5 100%);
  color: white;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 4px 12px rgba(99, 102, 241, 0.3);
}

.brand-title {
  font-size: 1.125rem;
  font-weight: 700;
  color: #0f172a;
  letter-spacing: -0.01em;
  margin: 0;
}

/* 垂直节点导航 */
.sidebar-nav {
  flex: 1;
  padding: 0 1.5rem;
  display: flex;
  flex-direction: column;
  gap: 1rem;
  position: relative;
}

.nav-node {
  position: relative;
  display: flex;
  align-items: flex-start;
  gap: 1rem;
  padding: 0;
  background: transparent;
  border: none;
  cursor: pointer;
  text-align: left;
  transition: opacity 0.3s ease;
}

.nav-node.is-disabled {
  cursor: not-allowed;
  opacity: 0.5;
}

.node-indicator {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
  z-index: 2;
  align-self: stretch; /* 占满整个节点高度 */
}

.node-dot {
  width: 2rem;
  height: 2rem;
  border-radius: 50%;
  background: white;
  border: 2px solid #cbd5e1;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 0.875rem;
  font-weight: 600;
  color: #94a3b8;
  transition: all 0.3s cubic-bezier(0.2, 0.8, 0.2, 1);
  box-shadow: 0 2px 4px rgba(0,0,0,0.02);
  flex-shrink: 0;
  position: relative; /* 为线定位 */
  z-index: 2;
}

.nav-node.is-active .node-dot {
  border-color: #6366f1;
  background: #6366f1;
  color: white;
  box-shadow: 0 0 0 4px rgba(99, 102, 241, 0.15);
  transform: scale(1.1);
}

.nav-node.is-complete:not(.is-active) .node-dot {
  border-color: #6366f1;
  background: white;
  color: #6366f1;
}

.node-line {
  position: absolute;
  top: 2rem; /* 从圆点底部开始 */
  bottom: -1rem; /* 延伸穿过 gap (gap 是 1rem) */
  left: 50%;
  transform: translateX(-50%);
  width: 2px;
  background: #e2e8f0;
  z-index: 1;
  transition: all 0.3s ease;
}

.nav-node.is-complete .node-line {
  background: #c7d2fe;
}

.node-content {
  flex: 1;
  padding-top: 0.25rem;
  padding-bottom: 2rem;
}

.node-header {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 0.25rem;
}

.node-title {
  font-size: 1rem;
  font-weight: 600;
  color: #475569;
  transition: color 0.3s ease;
}

.nav-node.is-active .node-title {
  color: #0f172a;
}

.nav-node.is-complete:not(.is-active) .node-title {
  color: #1e293b;
}

.node-badge {
  font-size: 0.6875rem;
  padding: 0.125rem 0.375rem;
  border-radius: 4px;
  background: rgba(99, 102, 241, 0.1);
  color: #6366f1;
  font-weight: 500;
}

.node-summary-wrapper {
  position: relative;
  min-height: 1.5rem;
}

.node-desc, .node-summary {
  font-size: 0.8125rem;
  line-height: 1.5;
}

.node-desc {
  color: #94a3b8;
}

.node-summary {
  color: #6366f1;
  font-weight: 500;
}

/* 左侧底部操作栏 */
.sidebar-footer {
  padding: 1.5rem;
  border-top: 1px solid rgba(226, 232, 240, 0.8);
  background: rgba(255, 255, 255, 0.6);
  margin-top: auto;
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.sidebar-action-btn {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  padding: 0.75rem 1.5rem;
  font-size: 0.875rem;
  font-weight: 600;
  border-radius: 0.75rem;
  border: 1px solid transparent;
  cursor: pointer;
  transition: all 0.2s ease;
}

.sidebar-action-btn.ghost {
  background: rgba(241, 245, 249, 0.86);
  color: var(--text-secondary, #64748b);
  border-color: var(--border-color, #e2e8f0);
}

.sidebar-action-btn.ghost:hover:not(:disabled) {
  background: white;
  border-color: var(--accent-300, #a5b4fc);
  color: var(--text-primary, #1e293b);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
}

.sidebar-action-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* 右侧主内容区 */
.panel-main {
  flex: 1;
  position: relative;
  background: var(--bg-canvas, #f8fafc);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  height: 100%;
}

.main-scroll-area {
  flex: 1;
  overflow-y: auto;
  padding: 2.5rem 3rem;
  scroll-behavior: smooth;
}

.workflow-section {
  max-width: 860px;
  margin: 0 auto;
}

.section-header {
  margin-bottom: 2rem;
}

.section-title {
  font-size: 1.875rem;
  font-weight: 800;
  color: #0f172a;
  letter-spacing: -0.02em;
  margin: 0 0 0.5rem 0;
}

.section-desc {
  font-size: 1rem;
  color: #64748b;
  margin: 0;
  line-height: 1.6;
}

/* 意图与目标堆叠 */
.setup-content-stack {
  display: flex;
  flex-direction: column;
  gap: 2rem;
}

.content-divider {
  height: 1px;
  background: linear-gradient(90deg, transparent 0%, rgba(226, 232, 240, 0.8) 50%, transparent 100%);
}

/* 推荐方案空状态 */
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 4rem 2rem;
  background: rgba(255, 255, 255, 0.5);
  border: 1px dashed #cbd5e1;
  border-radius: 1rem;
  text-align: center;
  color: #64748b;
}

.empty-icon {
  font-size: 2.5rem;
  margin-bottom: 1rem;
}

/* 方案网格 */
.plans-grid {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

/* 基础调整卡片 */
.adjustments-stack {
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
}

.control-card {
  background: rgba(255, 255, 255, 0.8);
  backdrop-filter: blur(12px);
  border: 1px solid rgba(226, 232, 240, 0.8);
  border-radius: 1rem;
  padding: 1.5rem;
  box-shadow: 0 4px 12px rgba(15, 23, 42, 0.02);
}

.control-header {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  margin-bottom: 1.25rem;
}

.control-icon-box {
  width: 2.5rem;
  height: 2.5rem;
  border-radius: 0.625rem;
  background: #f1f5f9;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #6366f1;
}

.control-title {
  font-size: 1rem;
  font-weight: 600;
  color: #1e293b;
}

.word-count-control {
  display: flex;
  align-items: center;
  gap: 1rem;
  background: #f8fafc;
  padding: 0.75rem;
  border-radius: 0.75rem;
  border: 1px solid #e2e8f0;
  width: fit-content;
}

.count-btn {
  width: 2.5rem;
  height: 2.5rem;
  border-radius: 0.5rem;
  border: none;
  background: white;
  color: #475569;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: all 0.2s ease;
  box-shadow: 0 1px 3px rgba(0,0,0,0.05);
}

.count-btn:hover:not(:disabled) {
  color: #6366f1;
  transform: translateY(-1px);
  box-shadow: 0 4px 6px rgba(99, 102, 241, 0.1);
}

.count-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.count-display {
  display: flex;
  align-items: baseline;
  gap: 0.25rem;
  min-width: 6rem;
  justify-content: center;
}

.count-value {
  font-size: 1.5rem;
  font-weight: 700;
  color: #6366f1;
  font-variant-numeric: tabular-nums;
}

.count-unit {
  font-size: 0.875rem;
  color: #64748b;
}

.sleek-textarea {
  width: 100%;
  padding: 1rem;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 0.75rem;
  font-size: 0.875rem;
  color: #1e293b;
  resize: vertical;
  min-height: 100px;
  transition: all 0.2s ease;
}

.sleek-textarea:focus {
  outline: none;
  background: white;
  border-color: #818cf8;
  box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.1);
}

.expert-panel-wrapper {
  background: rgba(255, 255, 255, 0.6);
  border-radius: 1rem;
  overflow: hidden;
}

.bottom-spacer {
  height: 120px; /* 悬浮底栏的高度缓冲 */
}

/* 悬浮底栏 */
.floating-action-bar-wrapper {
  position: absolute;
  bottom: 2rem;
  left: 0;
  right: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  pointer-events: none;
  z-index: 20;
}

.block-reason-toast {
  background: #fffbeb;
  color: #b45309;
  border: 1px solid #fde68a;
  padding: 0.5rem 1rem;
  border-radius: 9999px;
  font-size: 0.8125rem;
  font-weight: 500;
  margin-bottom: 0.75rem;
  box-shadow: 0 4px 12px rgba(245, 158, 11, 0.15);
  pointer-events: auto;
}

.floating-pill {
  display: flex;
  align-items: center;
  background: rgba(255, 255, 255, 0.85);
  backdrop-filter: blur(24px);
  border: 1px solid rgba(255, 255, 255, 0.5);
  border-radius: 9999px;
  padding: 0.5rem 0.5rem 0.5rem 1.5rem;
  box-shadow: 0 20px 40px -8px rgba(15, 23, 42, 0.15), 0 0 0 1px rgba(15, 23, 42, 0.05);
  pointer-events: auto;
}

.pill-info {
  display: flex;
  align-items: center;
  gap: 1rem;
  margin-right: 1.5rem;
}

.info-item {
  display: flex;
  flex-direction: column;
}

.info-label {
  font-size: 0.6875rem;
  color: #64748b;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.info-value {
  font-size: 0.875rem;
  font-weight: 600;
  color: #0f172a;
}

.info-divider {
  width: 1px;
  height: 2rem;
  background: #e2e8f0;
}

.pill-actions {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.pill-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0.75rem 1.5rem;
  border-radius: 9999px;
  font-size: 0.875rem;
  font-weight: 600;
  border: none;
  cursor: pointer;
  transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
}

.pill-btn.ghost {
  background: transparent;
  color: #64748b;
}

.pill-btn.ghost:hover {
  background: #f1f5f9;
  color: #0f172a;
}

.pill-btn.primary {
  background: #0f172a;
  color: white;
  box-shadow: 0 4px 12px rgba(15, 23, 42, 0.2);
}

.pill-btn.primary:hover:not(:disabled) {
  background: #1e293b;
  transform: translateY(-1px);
  box-shadow: 0 6px 16px rgba(15, 23, 42, 0.3);
}

.pill-btn.secondary {
  background: #f1f5f9;
  color: #475569;
}

.pill-btn.secondary:hover:not(:disabled) {
  background: #e2e8f0;
  color: #0f172a;
}

.pill-btn.generate {
  background: linear-gradient(135deg, #6366f1 0%, #4f46e5 100%);
  color: white;
  box-shadow: 0 4px 12px rgba(99, 102, 241, 0.3);
}

.pill-btn.generate:hover:not(:disabled) {
  transform: translateY(-1px);
  box-shadow: 0 8px 20px rgba(99, 102, 241, 0.4);
}

.pill-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
  transform: none !important;
  box-shadow: none !important;
}

/* 动画 */
.fade-slide-up-enter-active,
.fade-slide-up-leave-active {
  transition: all 0.4s cubic-bezier(0.2, 0.8, 0.2, 1);
}
.fade-slide-up-enter-from {
  opacity: 0;
  transform: translateY(20px);
}
.fade-slide-up-leave-to {
  opacity: 0;
  transform: translateY(-20px);
}

.fade-slide-enter-active,
.fade-slide-leave-active {
  transition: all 0.3s ease;
}
.fade-slide-enter-from {
  opacity: 0;
  transform: translateX(-10px);
}
.fade-slide-leave-to {
  opacity: 0;
  transform: translateX(10px);
}

.fade-up-enter-active,
.fade-up-leave-active {
  transition: all 0.3s ease;
}
.fade-up-enter-from,
.fade-up-leave-to {
  opacity: 0;
  transform: translateY(10px);
}

/* 深色模式 */
@media (prefers-color-scheme: dark) {
  .intent-panel-layout {
    background: #0f172a;
  }
  .panel-sidebar {
    background: linear-gradient(180deg, #1e293b 0%, rgba(30, 41, 59, 0.8) 100%);
    border-color: #334155;
  }
  .brand-title {
    color: #f8fafc;
  }
  .node-dot {
    background: #1e293b;
    border-color: #475569;
    color: #94a3b8;
  }
  .nav-node.is-active .node-dot {
    background: #4f46e5;
    border-color: #4f46e5;
    color: white;
  }
  .nav-node.is-complete:not(.is-active) .node-dot {
    background: #1e293b;
    border-color: #4f46e5;
    color: #818cf8;
  }
  .node-line {
    background: #334155;
  }
  .nav-node.is-complete .node-line {
    background: #4f46e5;
  }
  .node-title {
    color: #94a3b8;
  }
  .nav-node.is-active .node-title {
    color: #f8fafc;
  }
  .nav-node.is-complete:not(.is-active) .node-title {
    color: #cbd5e1;
  }
  .sidebar-footer {
    border-color: #334155;
    background: rgba(30, 41, 59, 0.6);
  }
  .sidebar-action-btn.ghost {
    background: #334155;
    border-color: #475569;
    color: #cbd5e1;
  }
  .sidebar-action-btn.ghost:hover:not(:disabled) {
    background: #475569;
    border-color: #64748b;
    color: #f8fafc;
  }
  .sidebar-action-btn.primary {
    background: #f8fafc;
    color: #0f172a;
    box-shadow: 0 4px 12px rgba(15, 23, 42, 0.2);
  }
  .sidebar-action-btn.primary:hover:not(:disabled) {
    background: #e2e8f0;
  }
  .panel-main {
    background: #0f172a;
  }
  .section-title {
    color: #f8fafc;
  }
  .section-desc {
    color: #94a3b8;
  }
  .content-divider {
    background: linear-gradient(90deg, transparent 0%, rgba(51, 65, 85, 0.8) 50%, transparent 100%);
  }
  .control-card {
    background: rgba(30, 41, 59, 0.6);
    border-color: rgba(71, 85, 105, 0.6);
  }
  .control-icon-box {
    background: #1e293b;
  }
  .control-title {
    color: #f8fafc;
  }
  .word-count-control {
    background: #1e293b;
    border-color: #334155;
  }
  .count-btn {
    background: #334155;
    color: #94a3b8;
  }
  .count-btn:hover:not(:disabled) {
    color: #818cf8;
  }
  .count-value {
    color: #818cf8;
  }
  .sleek-textarea {
    background: #1e293b;
    border-color: #334155;
    color: #f8fafc;
  }
  .sleek-textarea:focus {
    background: #0f172a;
    border-color: #6366f1;
  }
}
</style>
