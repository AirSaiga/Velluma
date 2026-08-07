<script setup lang="ts">
/**
 * 生成状态条（原生成覆盖面板，重构精简）。
 *
 * 职责：生成进行中在编辑器区域下方显示一行极简状态条
 * （阶段 + N/M 进度 + 细进度条 + 取消按钮）。
 * 实时渲染文不在此处展示——已改为直接灌入正文编辑框
 * （buildGenerationPreview.ts → ChapterEditor 只读预览，段级隔离）。
 * 完整进度信息（定档卡/等待提示/字数/事件/重试）统一在右栏
 * GenerationStepper 展示，此处不再重复。
 *
 * 取消按钮全局只保留这一处（无论右栏在哪个 tab 都可见）。
 * 失败态显示一行错误条（错误文案 + 重试 + 关闭）。
 *
 * 数据源：useGenerationSession 的状态。
 */
import { computed, ref } from 'vue'
import Icon from '../../../components/Icon.vue'
import type { GenerationSession } from '../composables/useGenerationSession'

const props = defineProps<{
  session: GenerationSession
}>()

const emit = defineEmits<{
  (e: 'cancel'): void
  (e: 'retry'): void
}>()

const stage = computed(() => props.session.stage.value)
const stepProgress = computed(() => props.session.stepProgress.value)
const errorText = computed(() => props.session.error.value)

// 后处理阶段（末段锁死后 PRUNE/审计/守卫，全章已锁段 + 终稿都在内存里）：
// 取消会丢弃全部已生成内容，二次确认防误触——此阶段耗时最长（数分钟），
// 误点一次取消的代价是整章重来（后端内存态 + 前端快照都无法恢复）。
const POST_PROCESS_STAGES = ['assembling', 'zone_writing', 'auditing', 'refining']
const inPostProcess = computed(() => POST_PROCESS_STAGES.includes(stage.value))
const confirmCancel = ref(false)
let _cancelConfirmTimer: ReturnType<typeof setTimeout> | null = null
function onCancel() {
  if (inPostProcess.value && !confirmCancel.value) {
    confirmCancel.value = true
    if (_cancelConfirmTimer) clearTimeout(_cancelConfirmTimer)
    _cancelConfirmTimer = setTimeout(() => { confirmCancel.value = false }, 3000)
    return
  }
  confirmCancel.value = false
  emit('cancel')
}

const progressPercent = computed(() => {
  const p = stepProgress.value
  if (!p || !p.total || p.index == null) return null
  return Math.round((p.index / p.total) * 100)
})

/** 阶段映射为展示标签 + 配色 */
const stageDisplay = computed(() => {
  const map: Record<string, { label: string; icon: string; color: string }> = {
    idle: { label: '待命', icon: '○', color: '#94a3b8' },
    tier_classifying: { label: '准备中', icon: '◌', color: '#3b82f6' },
    tier_decided: { label: '篇幅已定', icon: '●', color: '#10b981' },
    setup_growing: { label: '梳理脉络', icon: '◌', color: '#3b82f6' },
    zone_writing: { label: '写作中', icon: '✎', color: '#f59e0b' },
    assembling: { label: '拼接全文', icon: '◌', color: '#3b82f6' },
    auditing: { label: '结构检查', icon: '🔍', color: '#8b5cf6' },
    refining: { label: '润色', icon: '✎', color: '#f59e0b' },
    // BS-ADF 专属阶段
    beat_pending: { label: '分镜编辑', icon: '✎', color: '#f59e0b' },
    beat_rendering: { label: '渲染中', icon: '✎', color: '#f59e0b' },
    beat_stepping: { label: '逐段推进', icon: '⌨', color: '#8b5cf6' },
    beat_branch_choosing: { label: '待选走向', icon: '⑂', color: '#8b5cf6' },
    done: { label: '完成', icon: '✓', color: '#10b981' },
    error: { label: '失败', icon: '✗', color: '#dc2626' },
  }
  return map[stage.value] || { label: stage.value, icon: '?', color: '#94a3b8' }
})

const spinning = computed(() =>
  stage.value.includes('writing')
  || stage.value === 'refining'
  || stage.value === 'tier_classifying'
  || stage.value === 'beat_rendering'
  || stage.value === 'beat_stepping'
)
</script>

<template>
  <div class="generation-statusbar">
    <!-- 一行极简状态条 -->
    <div class="status-row">
      <template v-if="stage !== 'error'">
        <span class="status-icon" :class="{ spin: spinning }" :style="{ color: stageDisplay.color }">
          {{ stageDisplay.icon }}
        </span>
        <span class="status-label">
          {{ stageDisplay.label }}<span v-if="stepProgress?.label" class="status-step">· {{ stepProgress.label }}</span>
        </span>
        <span v-if="stepProgress?.index != null && stepProgress?.total" class="status-count">
          {{ stepProgress.index }}/{{ stepProgress.total }} 段
        </span>
        <div v-if="progressPercent != null" class="progress-track">
          <div class="progress-fill" :style="{ width: progressPercent + '%' }"></div>
        </div>
        <button
          class="btn-cancel"
          :class="{ danger: confirmCancel }"
          :title="inPostProcess ? '取消将丢弃全部已生成内容（含已锁段落）' : '取消生成'"
          @click="onCancel"
        >
          <Icon name="x-mark" :size="12" />
          <span>{{ confirmCancel ? '确认取消？' : '取消' }}</span>
        </button>
      </template>

      <!-- 失败态：一行错误条（error 原文可能已被 toast watcher 消费，给兜底文案） -->
      <template v-else>
        <span class="error-icon">✗</span>
        <span class="error-label">{{ errorText || '生成或精修过程出错，请重试。' }}</span>
        <button class="btn-retry" @click="emit('retry')">
          <Icon name="arrow-path" :size="12" />
          <span>重试</span>
        </button>
        <button class="btn-cancel" @click="emit('cancel')">
          <Icon name="x-mark" :size="12" />
          <span>关闭</span>
        </button>
      </template>
    </div>

    <!-- 实时正文流已移除：渲染文改为直接灌入正文编辑框（段级隔离预览，
         见 buildGenerationPreview.ts + WorkspaceView.generationPreviewHtml） -->
  </div>
</template>

<style scoped>
.generation-statusbar {
  position: relative;
  z-index: 10;
  display: flex;
  flex-direction: column;
  align-items: stretch;
  background: var(--bg-secondary);
  border-top: 1px solid var(--border-color);
  padding: 6px 12px;
  max-height: 280px;
  overflow-y: auto;
}

/* 一行状态条 */
.status-row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.8125rem;
  min-height: 24px;
}
.status-icon {
  font-size: 1rem;
  line-height: 1;
}
.status-icon.spin {
  animation: spin 1.5s linear infinite;
  display: inline-block;
}
@keyframes spin {
  to { transform: rotate(360deg); }
}
.status-label {
  font-weight: 500;
  color: var(--text-primary);
  white-space: nowrap;
}
.status-step {
  color: var(--text-muted);
  font-weight: 400;
  margin-left: 0.375rem;
}
.status-count {
  font-size: 0.75rem;
  color: var(--text-muted);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

/* 内嵌细进度条（占满剩余宽度） */
.progress-track {
  flex: 1;
  min-width: 60px;
  height: 3px;
  background: var(--bg-tertiary);
  border-radius: 2px;
  overflow: hidden;
}
.progress-fill {
  height: 100%;
  background: var(--accent-500);
  border-radius: 2px;
  transition: width 0.4s ease;
}

/* 取消按钮（全局唯一） */
.btn-cancel {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  padding: 0.25rem 0.625rem;
  font-size: 0.6875rem;
  background: transparent;
  border: 1px solid var(--border-color);
  border-radius: 0.25rem;
  color: var(--text-secondary);
  cursor: pointer;
  white-space: nowrap;
  transition: all 0.15s ease;
}
.btn-cancel:hover {
  color: #dc2626;
  border-color: #dc2626;
}
.btn-cancel.danger {
  color: #fff;
  background: #dc2626;
  border-color: #dc2626;
}
.btn-cancel.danger:hover {
  background: #b91c1c;
  border-color: #b91c1c;
}

/* 失败态一行错误条 */
.error-icon {
  color: #dc2626;
  font-weight: 600;
}
.error-label {
  flex: 1;
  font-size: 0.75rem;
  color: #dc2626;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.btn-retry {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  padding: 0.25rem 0.75rem;
  font-size: 0.6875rem;
  font-weight: 500;
  background: var(--accent-500);
  color: white;
  border: none;
  border-radius: 0.25rem;
  cursor: pointer;
  white-space: nowrap;
  transition: background 0.15s ease;
}
.btn-retry:hover {
  background: var(--accent-600);
}
</style>
