<script setup lang="ts">
/**
 * 书籍还原 Modal（书架「还原备份」入口，三步：选文件 → 预览 → 导入）。
 *
 * 职责：
 * - 单文件选择（.vellumabook / .json），客户端 FileReader 读文本、
 *   backupPreview 纯函数出摘要（不触网）
 * - 预览与书架现状对拍：同 ID 已在书架 → 红字预警 + 禁用确认
 *   （还原=原样放回，后端也会 409 拒绝重复还原——这里是提前告知）
 * - FormData 上传 POST /books/restore，完成后 emit('restored') 让书架刷新
 *
 * 分层：本容器消费 services/api；预览解析是 features/library 纯函数
 * （backupPreview.ts，有对拍单测）。未复用 import-markdown 的
 * FileDropZone——那边是多选 .md 语义与写死文案，这里单文件+专属文案。
 */
import { computed, ref } from 'vue'
import Icon from '../../../components/Icon.vue'
import ModalShell from '../../../components/ModalShell.vue'
import { useAppStore } from '../../app/useAppStore'
import { bookApi } from '../../../services/api'
import { conflictsWithShelf, formatExportedAt, parseBackupPreview, type BackupPreview } from '../backupPreview'

const store = useAppStore()
const emit = defineEmits<{ close: []; restored: [] }>()

type Step = 'select' | 'preview' | 'importing' | 'done'
const step = ref<Step>('select')

const selectedFile = ref<File | null>(null)
const preview = ref<BackupPreview | null>(null)
const previewError = ref('')
const reading = ref(false)
const importError = ref('')
const report = ref<any>(null)

const fileInputRef = ref<HTMLInputElement | null>(null)
const isDragOver = ref(false)

const conflict = computed(() =>
  preview.value ? conflictsWithShelf(preview.value, store.books.value.map((b) => b.id)) : false,
)

function reset() {
  step.value = 'select'
  selectedFile.value = null
  preview.value = null
  previewError.value = ''
  importError.value = ''
  report.value = null
}

function acceptFile(file: File | undefined) {
  if (!file) return
  selectedFile.value = file
  previewError.value = ''
  preview.value = null
  reading.value = true
  const reader = new FileReader()
  reader.onload = () => {
    reading.value = false
    const parsed = parseBackupPreview(String(reader.result || ''))
    if (!parsed.ok) {
      previewError.value = parsed.error || '备份文件无法识别'
      return
    }
    preview.value = parsed
    step.value = 'preview'
  }
  reader.onerror = () => {
    reading.value = false
    previewError.value = '文件读取失败'
  }
  reader.readAsText(file)
}

function onDrop(e: DragEvent) {
  isDragOver.value = false
  acceptFile(e.dataTransfer?.files?.[0])
}

function onFileInputChange(e: Event) {
  const target = e.target as HTMLInputElement
  acceptFile(target.files?.[0])
  target.value = '' // 重置以支持重复选择同一文件
}

function backToSelect() {
  reset()
}

async function handleRestore() {
  if (!selectedFile.value || !preview.value?.ok || conflict.value) return
  step.value = 'importing'
  importError.value = ''
  try {
    report.value = await bookApi.restoreBackup(selectedFile.value)
    step.value = 'done'
    emit('restored')
  } catch (e: any) {
    importError.value = e?.message || '未知错误'
    step.value = 'preview'
  }
}

function handleDone() {
  reset()
  emit('close')
}
</script>

<template>
  <ModalShell title="还原备份" width="480px" @close="step !== 'importing' && (reset(), emit('close'))">
    <template #subtitle>从备份文件把一本书原样放回书架</template>

    <div class="restore-body">
      <!-- 第一步：选文件 -->
      <div v-if="step === 'select'" class="picker-wrap">
        <div
          class="pick-area"
          :class="{ 'drag-over': isDragOver, reading }"
          @drop.prevent="onDrop"
          @dragover.prevent="isDragOver = true"
          @dragleave.prevent="isDragOver = false"
          @click="fileInputRef?.click()"
          role="button"
          tabindex="0"
          @keydown.enter="fileInputRef?.click()"
        >
          <Icon name="arrow-down-tray" :size="32" />
          <p class="pick-title">{{ reading ? '正在读取…' : '选择备份文件' }}</p>
          <p class="pick-hint">{{ reading ? '请稍候' : '点击选择，或把文件拖到这里' }}</p>
          <p class="pick-format">.vellumabook 备份文件 · 单文件</p>
        </div>
        <input
          ref="fileInputRef"
          type="file"
          accept=".vellumabook,.json"
          class="file-input-hidden"
          @change="onFileInputChange"
        />
        <p v-if="previewError" class="pick-error">
          <Icon name="exclamation-circle" :size="14" />
          {{ previewError }}
        </p>
      </div>

      <!-- 第二步：预览 -->
      <div v-else-if="step === 'preview'" class="preview-wrap">
        <div class="preview-card">
          <div class="preview-head">
            <Icon name="book" :size="20" />
            <div>
              <p class="preview-title">{{ preview?.title }}</p>
              <p class="preview-meta">
                {{ preview?.chapterCount ?? 0 }} 章<template v-if="preview?.genre"> · {{ preview.genre }}</template>
              </p>
            </div>
          </div>
          <p v-if="preview?.exportedAt" class="preview-row">
            备份时间：{{ formatExportedAt(preview.exportedAt) }}
          </p>
          <p v-if="selectedFile" class="preview-row">来自文件：{{ selectedFile.name }}</p>
        </div>

        <div v-if="conflict" class="conflict-tip">
          <Icon name="exclamation-circle" :size="14" />
          <span>书架中已存在这本书（还原不会产生副本）。若想重来的话，请先在书架删除它。</span>
        </div>
        <p v-if="importError" class="pick-error">
          <Icon name="exclamation-circle" :size="14" />
          还原失败：{{ importError }}
        </p>

        <div class="preview-actions">
          <button class="btn-ghost" @click="backToSelect">重新选择</button>
          <button class="btn-primary btn-primary-instrument" :disabled="conflict" @click="handleRestore">
            <Icon name="arrow-uturn-right" :size="14" />
            <span>放回书架</span>
          </button>
        </div>
      </div>

      <!-- 第三步：导入中 / 完成 -->
      <div v-else-if="step === 'importing'" class="progress-wrap">
        <Icon name="arrow-path" :size="28" class="spin" />
        <p class="progress-title">正在还原《{{ preview?.title }}》…</p>
        <p class="progress-hint">数据量大的备份可能需要一点时间</p>
      </div>
      <div v-else-if="step === 'done'" class="done-wrap">
        <Icon name="check-circle" :size="28" class="done-icon" />
        <p class="done-title">《{{ report?.book_title || preview?.title }}》已放回书架</p>
        <p class="done-hint">
          共 {{ report?.table_counts ? Object.values(report.table_counts).reduce((a: number, b: any) => a + (b || 0), 0) : '—' }} 条数据<template v-if="report?.images"> · {{ report.images }} 张地图底图</template>
        </p>
        <p v-if="report?.warnings?.length" class="done-warn">
          <Icon name="information-circle" :size="13" />
          {{ report.warnings.length }} 条版本差异提示（不影响使用）
        </p>
        <button class="btn-primary btn-primary-instrument" @click="handleDone">完成</button>
      </div>
    </div>
  </ModalShell>
</template>

<style scoped>
.restore-body {
  padding: 0 1.25rem 1.25rem;
}

/* 选文件区 */
.pick-area {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.375rem;
  padding: 2.25rem 1.5rem;
  border: 2px dashed var(--border-color);
  border-radius: var(--radius-lg);
  cursor: pointer;
  text-align: center;
  color: var(--text-muted);
  transition: all var(--dur-2) var(--ease-out);
  background: var(--bg-primary);
}

.pick-area:hover,
.pick-area.drag-over {
  border-color: var(--accent-500);
  background: var(--state-hover);
}

.pick-area.reading {
  pointer-events: none;
  opacity: 0.7;
}

.pick-title {
  font-size: 0.9375rem;
  font-weight: 500;
  color: var(--text-primary);
  margin: 0.25rem 0 0;
}

.pick-hint {
  font-size: 0.8125rem;
  color: var(--text-secondary);
  margin: 0;
}

.pick-format {
  font-size: var(--text-xs);
  color: var(--text-muted);
  margin: 0.375rem 0 0;
}

.file-input-hidden {
  display: none;
}

.pick-error {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  font-size: 0.8125rem;
  color: var(--danger);
  margin: 0.75rem 0 0;
}

/* 预览区 */
.preview-card {
  border: 1px solid var(--line-faint);
  border-radius: var(--radius-md);
  padding: 0.875rem 1rem;
  background: var(--bg-primary);
}

.preview-head {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  color: var(--accent-600);
}

.preview-title {
  font-family: var(--font-heading);
  font-size: 1rem;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0;
}

.preview-meta {
  font-size: var(--text-xs);
  color: var(--text-muted);
  margin: 0.125rem 0 0;
}

.preview-row {
  font-size: 0.8125rem;
  color: var(--text-secondary);
  margin: 0.5rem 0 0;
}

.conflict-tip {
  display: flex;
  align-items: flex-start;
  gap: 0.375rem;
  font-size: 0.8125rem;
  color: var(--danger);
  margin-top: 0.75rem;
  line-height: var(--lh-normal);
}

.conflict-tip svg {
  flex-shrink: 0;
  margin-top: 0.125rem;
}

.preview-actions {
  display: flex;
  justify-content: flex-end;
  gap: 0.5rem;
  margin-top: 1rem;
}

.btn-ghost {
  display: inline-flex;
  align-items: center;
  padding: 0.4375rem 0.75rem;
  font-size: 0.8125rem;
  font-weight: 500;
  background: var(--bg-canvas);
  color: var(--text-primary);
  border: 1px solid var(--line-faint);
  border-radius: var(--radius-sm);
  cursor: pointer;
}

.btn-ghost:hover {
  background: var(--state-hover);
}

.btn-primary:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

/* 导入中 / 完成 */
.progress-wrap,
.done-wrap {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.375rem;
  padding: 2rem 1rem;
  text-align: center;
}

.progress-wrap {
  color: var(--accent-500);
}

.progress-title {
  font-size: 0.9375rem;
  font-weight: 500;
  color: var(--text-primary);
  margin: 0.5rem 0 0;
}

.progress-hint {
  font-size: 0.8125rem;
  color: var(--text-muted);
  margin: 0;
}

.done-icon {
  color: var(--accent-600);
}

.done-title {
  font-family: var(--font-heading);
  font-size: 1rem;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0.5rem 0 0;
}

.done-hint {
  font-size: 0.8125rem;
  color: var(--text-secondary);
  margin: 0;
}

.done-warn {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  font-size: var(--text-xs);
  color: var(--text-muted);
  margin: 0.25rem 0 0;
}

.done-wrap .btn-primary {
  margin-top: 0.75rem;
}

.spin {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}
</style>
