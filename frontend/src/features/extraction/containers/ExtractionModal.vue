<script setup lang="ts">
/**
 * 正文逆向提取弹窗容器（承载 analyze → review → confirm 全流程）。
 *
 * 职责：
 * - 持有 useExtractionSession 状态机
 * - 按步骤渲染对应视图（分析中 spinner / 预览面板 / 提交进度 / 完成）
 * - 处理关闭确认
 */
import { ref, computed, watch } from 'vue'
import Icon from '../../../components/Icon.vue'
import { useToast } from '../../../composables/useToast'
import { useExtractionSession } from '../composables/useExtractionSession'
import ExtractionPreviewPanel from '../presentation/ExtractionPreviewPanel.vue'
import type { ConfirmedExtraction } from '../composables/useExtractionSession'

const props = defineProps<{
  /** 要分析的章节 ID */
  chapterId: string
}>()

const emit = defineEmits<{
  close: []
  completed: []
}>()

const { showToast } = useToast()
const session = useExtractionSession()

/** 是否已启动 analyze（避免 watch 重复触发） */
const started = ref(false)

/** 步骤标题 */
const stepTitle = computed(() => {
  switch (session.step.value) {
    case 'idle':
      return '准备分析'
    case 'analyzing':
      return '正在分析正文'
    case 'reviewing':
      return '提取结果预览'
    case 'committing':
      return '正在写入数据库'
    case 'done':
      return '提取完成'
    default:
      return '正文逆向提取'
  }
})

/** 启动分析（Modal 打开时自动触发一次） */
function startAnalysis() {
  if (started.value) return
  started.value = true
  session.startAnalyze(props.chapterId).catch((e: any) => {
    showToast('分析失败：' + (e?.message || '未知错误'), 'error')
  })
}

/** 失败重试（2026-09-04 审计修复）：error 态下作者可重跑分析（绕过 started 一次性守卫） */
function retryAnalysis() {
  session.startAnalyze(props.chapterId).catch((e: any) => {
    showToast('分析失败：' + (e?.message || '未知错误'), 'error')
  })
}

// 组件挂载即启动
startAnalysis()

/** 处理确认 */
async function handleConfirm(confirmed: ConfirmedExtraction) {
  await session.startConfirm(props.chapterId, confirmed)
}

/** 完成后通知父组件 */
watch(
  () => session.step.value,
  (newStep) => {
    if (newStep === 'done') {
      const stats = session.commitStats.value
      if (stats) {
        const total =
          stats.characters + stats.relationships + stats.locations + stats.assets + stats.foreshadows
        showToast(
          `已入库：角色${stats.characters} · 关系${stats.relationships} · 地点${stats.locations} · 资产${stats.assets} · 伏笔${stats.foreshadows} · 记忆${stats.memories}`,
          'success',
        )
      }
      emit('completed')
    }
  },
)

/** 关闭 */
function handleClose() {
  if (session.isProcessing.value) {
    // 进行中不直接关（由 confirm dialog 守卫）
    return
  }
  session.reset()
  emit('close')
}

const stepLabel: Record<string, string> = {
  characters: '角色',
  relationships: '关系',
  locations: '地点',
  assets: '资产',
  foreshadows: '伏笔',
  memories: '向量记忆',
}
</script>

<template>
  <div class="modal-overlay" @click.self="!session.isProcessing.value && handleClose()">
    <div class="modal-content extraction-modal">
      <!-- 头部 -->
      <header class="modal-header">
        <h2 class="modal-title">{{ stepTitle }}</h2>
        <button
          class="close-btn"
          title="关闭"
          :disabled="session.isProcessing.value"
          @click="handleClose"
        >
          <Icon name="x-mark" :size="18" />
        </button>
      </header>

      <!-- 内容区 -->
      <div class="modal-body">
        <!-- 失败（2026-09-04 审计修复）：此前 onError 置 error + step 回 idle，
             而模板把 idle 也渲染成加载视图——失败后永远转圈，无任何错误提示 -->
        <div v-if="session.error.value && session.step.value === 'idle'" class="error-view">
          <Icon name="exclamation-circle" :size="40" class="error-icon" />
          <p class="loading-text">分析失败</p>
          <p class="loading-hint">{{ session.error.value }}</p>
          <div class="error-actions">
            <button class="retry-btn" @click="retryAnalysis">重试</button>
            <button class="close-text-btn" @click="handleClose">关闭</button>
          </div>
        </div>

        <!-- idle / analyzing：加载中 -->
        <div v-else-if="session.step.value === 'idle' || session.step.value === 'analyzing'" class="loading-view">
          <Icon name="arrow-path" :size="40" class="spin" />
          <p class="loading-text">LLM 正在分析正文，提取角色、关系、地点、资产和伏笔……</p>
          <p class="loading-hint">这可能需要 30-60 秒</p>
        </div>

        <!-- reviewing：预览确认 -->
        <ExtractionPreviewPanel
          v-else-if="session.step.value === 'reviewing' && session.result.value"
          :result="session.result.value"
          @confirm="handleConfirm"
          @cancel="handleClose"
        />

        <!-- committing：提交进度 -->
        <div v-else-if="session.step.value === 'committing'" class="committing-view">
          <Icon name="arrow-path" :size="32" class="spin" />
          <p class="loading-text">正在写入数据库……</p>
          <div class="progress-steps">
            <div
              v-for="(ps, idx) in session.progressSteps.value"
              :key="idx"
              class="progress-step"
            >
              <Icon name="check-circle" :size="14" />
              <span>{{ stepLabel[ps.step] || ps.step }}：{{ ps.created }} 项</span>
            </div>
          </div>
        </div>

        <!-- done：完成 -->
        <div v-else-if="session.step.value === 'done'" class="done-view">
          <div class="done-icon">
            <Icon name="check-circle" :size="48" />
          </div>
          <h3>提取完成</h3>
          <div v-if="session.commitStats.value" class="commit-summary">
            <div class="summary-row">
              <span>角色</span><span>{{ session.commitStats.value.characters }}</span>
            </div>
            <div class="summary-row">
              <span>关系</span><span>{{ session.commitStats.value.relationships }}</span>
            </div>
            <div class="summary-row">
              <span>地点</span><span>{{ session.commitStats.value.locations }}</span>
            </div>
            <div class="summary-row">
              <span>资产</span><span>{{ session.commitStats.value.assets }}</span>
            </div>
            <div class="summary-row">
              <span>伏笔</span><span>{{ session.commitStats.value.foreshadows }}</span>
            </div>
            <div class="summary-row">
              <span>向量记忆</span><span>{{ session.commitStats.value.memories }}</span>
            </div>
          </div>
          <button class="btn-primary" @click="handleClose">完成</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 200;
  padding: 2rem;
  backdrop-filter: blur(2px);
}

.extraction-modal {
  background: var(--bg-canvas);
  border-radius: 0.625rem;
  width: 100%;
  max-width: 640px;
  max-height: 80vh;
  display: flex;
  flex-direction: column;
  box-shadow: 0 12px 48px rgba(0, 0, 0, 0.2);
}

.modal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 1rem 1.25rem;
  border-bottom: 1px solid var(--border-color);
  flex-shrink: 0;
}

.modal-title {
  font-family: var(--font-heading);
  font-size: 1.0625rem;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0;
}

.close-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 2rem;
  height: 2rem;
  background: transparent;
  border: none;
  border-radius: 0.375rem;
  color: var(--text-muted);
  cursor: pointer;
  transition: all 0.15s ease;
}

.close-btn:hover:not(:disabled) {
  background: var(--hover-bg);
  color: var(--text-primary);
}

.close-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.modal-body {
  flex: 1;
  overflow: hidden;
  padding: 1.25rem;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

/* 加载视图 */
.loading-view {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  color: var(--accent-500);
  text-align: center;
}

/* 失败态（2026-09-04 审计修复）：错误提示 + 重试/关闭 */
.error-view {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  color: #b0483c;
  text-align: center;
}

.error-icon {
  color: #b0483c;
}

.error-actions {
  display: flex;
  gap: 0.75rem;
  margin-top: 0.75rem;
}

.retry-btn {
  padding: 0.4rem 1.2rem;
  border: none;
  border-radius: 8px;
  background: var(--accent-500);
  color: #fff;
  font-size: 0.875rem;
  cursor: pointer;
}

.retry-btn:hover {
  filter: brightness(1.08);
}

.close-text-btn {
  padding: 0.4rem 1rem;
  border: none;
  background: transparent;
  color: var(--text-muted, inherit);
  font-size: 0.875rem;
  cursor: pointer;
}

.loading-text {
  font-size: 0.9375rem;
  font-weight: 500;
  color: var(--text-primary);
  margin: 0.5rem 0 0;
}

.loading-hint {
  font-size: 0.75rem;
  color: var(--text-muted);
  margin: 0;
}

.spin {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

/* 提交进度 */
.committing-view {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 0.75rem;
  color: var(--accent-500);
  text-align: center;
}

.progress-steps {
  display: flex;
  flex-direction: column;
  gap: 0.375rem;
  text-align: left;
}

.progress-step {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  font-size: 0.8125rem;
  color: #059669;
}

/* 完成视图 */
.done-view {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 0.75rem;
  text-align: center;
  padding: 1rem;
}

.done-icon {
  color: #059669;
}

.done-view h3 {
  font-family: var(--font-heading);
  font-size: 1.125rem;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0;
}

.commit-summary {
  width: 100%;
  max-width: 280px;
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.summary-row {
  display: flex;
  justify-content: space-between;
  padding: 0.375rem 0.625rem;
  font-size: 0.8125rem;
  background: var(--bg-primary);
  border-radius: 0.25rem;
}

.summary-row span:first-child {
  color: var(--text-secondary);
}

.summary-row span:last-child {
  font-weight: 600;
  color: var(--text-primary);
}

.btn-primary {
  display: inline-flex;
  align-items: center;
  gap: 0.375rem;
  padding: 0.5rem 1.5rem;
  font-size: 0.8125rem;
  font-weight: 500;
  background: var(--accent-500);
  color: white;
  border: none;
  border-radius: 0.375rem;
  cursor: pointer;
  transition: background 0.15s ease;
  margin-top: 0.5rem;
}

.btn-primary:hover {
  background: var(--accent-600);
}
</style>
