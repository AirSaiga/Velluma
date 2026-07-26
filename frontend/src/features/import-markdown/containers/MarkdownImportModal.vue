<script setup lang="ts">
/**
 * Markdown 批量导入章节向导容器（三步状态机）。
 *
 * 职责：
 * - 持有 useMarkdownImport 组合函数的状态
 * - 按 step 渲染对应的展示组件
 * - 协调关闭确认（导入中需二次确认）
 * - 处理"下一步/上一步"流转
 *
 * 分层：本容器消费 services（通过 store），展示组件只通过 props/emits 通信。
 */
import { ref, computed } from 'vue'
import Icon from '../../../components/Icon.vue'
import { useAppStore } from '../../app/useAppStore'
import { useToast } from '../../../composables/useToast'
import { useConfirmDialog } from '../../../composables/useConfirmDialog'
import { useMarkdownImport } from '../composables/useMarkdownImport'
import FileDropZone from '../presentation/FileDropZone.vue'
import ImportPreviewTable from '../presentation/ImportPreviewTable.vue'
import ImportProgressTracker from '../presentation/ImportProgressTracker.vue'

const store = useAppStore()
const { showToast } = useToast()
const { show: showConfirm } = useConfirmDialog()

const {
  step,
  entries,
  skippedFiles,
  isImporting,
  completedCount,
  successCount,
  errorCount,
  totalCount,
  progressPercent,
  ingestFiles,
  updateEntry,
  removeEntry,
  moveEntry,
  clearEntries,
  validate,
  executeImport,
  abortImport,
  backToPreview,
  reset,
} = useMarkdownImport(store)

/** 是否正在解析文件（ingestFiles 执行中） */
const parsing = ref(false)

/** 当前校验冲突（preview 步骤实时计算） */
const validation = computed(() => validate())

/** 已存在的章节号集合 */
const existingChapterNumbers = computed(() =>
  store.chapters.value.map((c) => c.chapter_number),
)

/** 步骤标题映射 */
const stepTitle = computed(() => {
  switch (step.value) {
    case 'select':
      return '选择 Markdown 文件'
    case 'preview':
      return '确认导入内容'
    case 'importing':
      return '导入进度'
    case 'done':
      return '导入完成'
    default:
      return '导入 Markdown'
  }
})

/** 步骤序号（1-3，done 归到 3） */
const stepNumber = computed(() => {
  switch (step.value) {
    case 'select':
      return 1
    case 'preview':
      return 2
    default:
      return 3
  }
})

/**
 * 处理文件选择（FileDropZone emit）。
 * 调用 ingestFiles 异步读取+解析，parsing 状态控制 loading。
 */
async function handleFilesSelected(files: File[]) {
  parsing.value = true
  try {
    await ingestFiles(files)
    if (skippedFiles.value.length > 0) {
      showToast(`已跳过 ${skippedFiles.value.length} 个无效文件`, 'warning')
    }
  } catch (e: any) {
    showToast('文件解析失败：' + (e.message || '未知错误'), 'error')
  } finally {
    parsing.value = false
  }
}

/** 触发导入（校验通过后执行） */
async function handleStartImport() {
  const result = validate()
  if (!result.ok) {
    showToast('请先解决章节号冲突', 'warning')
    return
  }
  try {
    await executeImport()
  } catch (e: any) {
    showToast('导入过程出错：' + (e.message || '未知错误'), 'error')
  }
}

/** 中止导入（Step 3） */
async function handleCancelImport() {
  const ok = await showConfirm({
    title: '中止导入',
    message: '确定中止剩余章节的导入吗？已创建的章节不会删除。',
    warning: '未导入的章节将丢失。',
  })
  if (ok) {
    abortImport()
    showToast('已中止导入', 'info')
  }
}

/** 回到 Step 2 重试失败条目 */
function handleRetry() {
  backToPreview()
}

/** 关闭 Modal（带确认） */
async function handleClose() {
  // 导入进行中需确认
  if (isImporting.value) {
    const ok = await showConfirm({
      title: '关闭导入窗口',
      message: '正在导入中，关闭窗口将中止剩余导入。确定关闭吗？',
      warning: '已创建的章节不会删除。',
    })
    if (!ok) return
    abortImport()
  }
  reset()
  emit('close')
}

/** 完成并关闭 */
function handleDone() {
  if (successCount.value > 0) {
    showToast(`成功导入 ${successCount.value} 章`, 'success')
  }
  reset()
  emit('close')
}

/** 回到上一步（preview → select） */
function handleBack() {
  if (step.value === 'preview') {
    clearEntries()
  }
}

const emit = defineEmits<{
  close: []
}>()
</script>

<template>
  <div class="modal-overlay" @click.self="!isImporting && handleClose()">
    <div class="modal-content import-modal">
      <!-- 头部 -->
      <header class="modal-header">
        <div class="header-left">
          <h2 class="modal-title">{{ stepTitle }}</h2>
          <!-- 步骤指示器 -->
          <div class="step-indicator">
            <div
              v-for="n in 3"
              :key="n"
              class="step-dot"
              :class="{ active: stepNumber >= n, current: stepNumber === n }"
            ></div>
          </div>
        </div>
        <button class="close-btn" title="关闭" @click="handleClose">
          <Icon name="x-mark" :size="18" />
        </button>
      </header>

      <!-- 内容区 -->
      <div class="modal-body">
        <!-- Step 1：文件选择 -->
        <FileDropZone
          v-if="step === 'select'"
          :skipped-files="skippedFiles"
          :parsing="parsing"
          @files-selected="handleFilesSelected"
        />

        <!-- Step 2：预览确认 -->
        <ImportPreviewTable
          v-else-if="step === 'preview'"
          :entries="entries"
          :existing-chapter-numbers="existingChapterNumbers"
          :conflict-numbers="validation.conflicts"
          @update-entry="updateEntry"
          @remove-entry="removeEntry"
          @move-entry="moveEntry"
          @start-import="handleStartImport"
        />

        <!-- Step 3：进度 / 完成 -->
        <ImportProgressTracker
          v-else-if="step === 'importing' || step === 'done'"
          :entries="entries"
          :progress-percent="progressPercent"
          :is-importing="isImporting"
          :success-count="successCount"
          :error-count="errorCount"
          :total-count="totalCount"
          @cancel="handleCancelImport"
          @done="handleDone"
          @retry="handleRetry"
        />
      </div>

      <!-- 底部操作（仅 preview 步骤显示返回） -->
      <footer v-if="step === 'preview'" class="modal-footer">
        <button class="btn-secondary" @click="handleBack">
          <Icon name="arrow-left" :size="14" />
          <span>重新选择</span>
        </button>
      </footer>
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

.import-modal {
  background: var(--bg-canvas);
  border-radius: 0.625rem;
  width: 100%;
  max-width: 720px;
  max-height: 85vh;
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

.header-left {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.modal-title {
  font-family: var(--font-heading);
  font-size: 1.0625rem;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0;
}

.step-indicator {
  display: flex;
  gap: 0.375rem;
}

.step-dot {
  width: 1.75rem;
  height: 3px;
  border-radius: 2px;
  background: var(--border-color);
  transition: background 0.2s ease;
}

.step-dot.active {
  background: var(--accent-500);
}

.step-dot.current {
  background: var(--accent-600);
  box-shadow: 0 0 0 2px rgba(var(--accent-500-rgb, 124, 58, 237), 0.2);
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

.close-btn:hover {
  background: var(--hover-bg);
  color: var(--text-primary);
}

.modal-body {
  flex: 1;
  overflow-y: auto;
  padding: 1.25rem;
  min-height: 0;
}

.modal-footer {
  display: flex;
  justify-content: flex-start;
  padding: 0.75rem 1.25rem;
  border-top: 1px solid var(--border-color);
  flex-shrink: 0;
}

.btn-secondary {
  display: inline-flex;
  align-items: center;
  gap: 0.375rem;
  padding: 0.4375rem 0.75rem;
  font-size: 0.8125rem;
  font-weight: 500;
  background: var(--bg-canvas);
  color: var(--text-primary);
  border: 1px solid var(--border-color);
  border-radius: 0.375rem;
  cursor: pointer;
  transition: all 0.15s ease;
}

.btn-secondary:hover {
  background: var(--hover-bg);
}
</style>
