<script setup lang="ts">
/**
 * 导入进度追踪（Markdown 导入向导 Step 3）。
 *
 * 职责：纯展示——进度条 + 逐条状态 + 完成/DONE 摘要视图。
 * 分两种状态：
 *   - importing：显示进度条和逐条状态
 *   - done：显示成功/失败摘要，提供"重试失败"或"完成"按钮
 */
import { computed } from 'vue'
import Icon from '../../../components/Icon.vue'
import type { ImportEntry } from '../composables/useMarkdownImport'

const props = defineProps<{
  /** 待导入条目列表（含实时状态） */
  entries: ImportEntry[]
  /** 进度百分比（0-100） */
  progressPercent: number
  /** 是否正在导入中 */
  isImporting: boolean
  /** 成功数 */
  successCount: number
  /** 失败数 */
  errorCount: number
  /** 总数 */
  totalCount: number
}>()

const emit = defineEmits<{
  cancel: []
  done: []
  retry: []
}>()

const isDone = computed(() => !props.isImporting)
const hasErrors = computed(() => props.errorCount > 0)

/** 状态图标 */
function statusIcon(status: ImportEntry['status']): string {
  switch (status) {
    case 'success':
      return 'check-circle'
    case 'error':
      return 'x-circle'
    case 'importing':
      return 'arrow-path'
    default:
      return 'clock'
  }
}

/** 状态文字 */
function statusLabel(status: ImportEntry['status']): string {
  switch (status) {
    case 'success':
      return '成功'
    case 'error':
      return '失败'
    case 'importing':
      return '导入中…'
    default:
      return '等待中'
  }
}
</script>

<template>
  <div class="progress-tracker">
    <!-- 导入中 -->
    <template v-if="isImporting">
      <div class="progress-header">
        <span class="progress-title">导入中… ({{ successCount + errorCount }}/{{ totalCount }})</span>
      </div>
      <div class="progress-bar-wrapper">
        <div class="progress-bar" :style="{ width: progressPercent + '%' }"></div>
      </div>
      <div class="progress-percent">{{ progressPercent }}%</div>

      <div class="entry-status-list">
        <div
          v-for="entry in entries"
          :key="entry.id"
          class="entry-status-row"
          :class="entry.status"
        >
          <Icon
            :name="statusIcon(entry.status)"
            :size="16"
            :class="{ spin: entry.status === 'importing' }"
          />
          <span class="entry-num">第{{ entry.chapterNumber }}章</span>
          <span class="entry-name">{{ entry.chapterName || '(未命名)' }}</span>
          <span class="entry-status-text">{{ statusLabel(entry.status) }}</span>
          <span v-if="entry.status === 'error' && entry.error" class="entry-error" :title="entry.error">
            {{ entry.error }}
          </span>
        </div>
      </div>

      <div class="tracker-actions">
        <button class="btn-secondary" @click="emit('cancel')">
          <span>中止剩余导入</span>
        </button>
      </div>
    </template>

    <!-- 完成 -->
    <template v-else>
      <div class="done-summary">
        <div class="done-icon" :class="{ 'has-error': hasErrors }">
          <Icon :name="hasErrors ? 'exclamation-circle' : 'check-circle'" :size="48" />
        </div>
        <h3 class="done-title">导入完成</h3>
        <p class="done-stats">
          <span class="stat-success">✓ 成功 {{ successCount }} 章</span>
          <span v-if="hasErrors" class="stat-error">· ✕ 失败 {{ errorCount }} 章</span>
        </p>

        <!-- 失败详情 -->
        <div v-if="hasErrors" class="error-details">
          <p class="error-details-title">失败详情：</p>
          <div
            v-for="entry in entries.filter((e) => e.status === 'error')"
            :key="entry.id"
            class="error-detail-row"
          >
            <Icon name="x-circle" :size="14" />
            <span class="err-name">第{{ entry.chapterNumber }}章 {{ entry.chapterName || '(未命名)' }}</span>
            <span class="err-msg">{{ entry.error }}</span>
          </div>
        </div>
      </div>

      <div class="tracker-actions">
        <button v-if="hasErrors" class="btn-secondary" @click="emit('retry')">
          <Icon name="arrow-path" :size="15" />
          <span>重试失败章节</span>
        </button>
        <button class="btn-primary" @click="emit('done')">
          <span>完成</span>
        </button>
      </div>
    </template>
  </div>
</template>

<style scoped>
.progress-tracker {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.progress-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.progress-title {
  font-size: 0.9375rem;
  font-weight: 500;
  color: var(--text-primary);
}

.progress-bar-wrapper {
  width: 100%;
  height: 6px;
  background: var(--bg-tertiary);
  border-radius: 3px;
  overflow: hidden;
}

.progress-bar {
  height: 100%;
  background: var(--accent-500);
  border-radius: 3px;
  transition: width 0.3s ease;
}

.progress-percent {
  font-size: 0.75rem;
  color: var(--text-muted);
  font-variant-numeric: tabular-nums;
  text-align: right;
}

.entry-status-list {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  max-height: 280px;
  overflow-y: auto;
  padding-right: 0.25rem;
}

.entry-status-row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.375rem 0.5rem;
  border-radius: 0.25rem;
  font-size: 0.8125rem;
  background: var(--bg-primary);
}

.entry-status-row.success {
  color: #059669;
}

.entry-status-row.error {
  color: #dc2626;
  background: rgba(220, 38, 38, 0.04);
}

.entry-status-row.importing {
  color: var(--accent-500);
}

.entry-status-row.pending {
  color: var(--text-muted);
}

.entry-num {
  font-weight: 500;
  flex-shrink: 0;
  min-width: 3.5rem;
}

.entry-name {
  flex: 1;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  color: var(--text-primary);
}

.entry-status-text {
  flex-shrink: 0;
  font-size: 0.75rem;
}

.entry-error {
  font-size: 0.6875rem;
  opacity: 0.8;
  max-width: 180px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.spin {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from {
    transform: rotate(0deg);
  }
  to {
    transform: rotate(360deg);
  }
}

/* 完成视图 */
.done-summary {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.5rem;
  padding: 1rem 0;
  text-align: center;
}

.done-icon {
  color: #059669;
  margin-bottom: 0.5rem;
}

.done-icon.has-error {
  color: #f59e0b;
}

.done-title {
  font-family: var(--font-heading);
  font-size: 1.125rem;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0;
}

.done-stats {
  font-size: 0.875rem;
  color: var(--text-secondary);
  margin: 0;
}

.stat-success {
  color: #059669;
  font-weight: 500;
}

.stat-error {
  color: #dc2626;
  font-weight: 500;
}

.error-details {
  margin-top: 0.75rem;
  width: 100%;
  text-align: left;
  padding: 0.75rem;
  background: rgba(220, 38, 38, 0.04);
  border: 1px solid rgba(220, 38, 38, 0.15);
  border-radius: 0.375rem;
}

.error-details-title {
  font-size: 0.75rem;
  font-weight: 600;
  color: #dc2626;
  margin: 0 0 0.5rem;
}

.error-detail-row {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  font-size: 0.75rem;
  color: var(--text-secondary);
  margin-bottom: 0.25rem;
}

.err-name {
  font-weight: 500;
  white-space: nowrap;
}

.err-msg {
  opacity: 0.8;
}

.tracker-actions {
  display: flex;
  justify-content: flex-end;
  gap: 0.5rem;
  padding-top: 0.5rem;
}

.btn-primary,
.btn-secondary {
  display: inline-flex;
  align-items: center;
  gap: 0.375rem;
  padding: 0.5rem 1rem;
  font-size: 0.8125rem;
  font-weight: 500;
  border-radius: 0.375rem;
  cursor: pointer;
  transition: all 0.15s ease;
  border: 1px solid transparent;
}

.btn-primary {
  background: var(--accent-500);
  color: white;
}

.btn-primary:hover {
  background: var(--accent-600);
}

.btn-secondary {
  background: var(--bg-canvas);
  color: var(--text-primary);
  border-color: var(--border-color);
}

.btn-secondary:hover {
  background: var(--hover-bg);
}
</style>
