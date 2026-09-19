<script setup lang="ts">
/**
 * 导入预览表格（Markdown 导入向导 Step 2）。
 *
 * 职责：纯展示——渲染可编辑表格，用户可调整章节号/章节名、删除行、上下移动。
 * 通过 emits 将变更上抛容器，不直接修改 props。
 */
import { computed } from 'vue'
import Icon from '../../../components/Icon.vue'
import type { ImportEntry } from '../composables/useMarkdownImport'

const props = defineProps<{
  /** 待导入条目列表 */
  entries: ImportEntry[]
  /** 已存在的章节号集合（用于冲突检测高亮） */
  existingChapterNumbers: number[]
  /** 冲突的章节号列表（validate 结果） */
  conflictNumbers: number[]
}>()

const emit = defineEmits<{
  'update-entry': [id: string, partial: Partial<ImportEntry>]
  'remove-entry': [id: string]
  'move-entry': [id: string, direction: 'up' | 'down']
  'start-import': []
}>()

/** 某条目的章节号是否冲突 */
function isConflict(entry: ImportEntry): boolean {
  return props.conflictNumbers.includes(entry.chapterNumber)
}

/** 格式化字数显示 */
function formatWordCount(count: number): string {
  if (count >= 1000) return (count / 1000).toFixed(1) + 'k'
  return String(count)
}

/** 更新章节号 */
function onNumberChange(entry: ImportEntry, value: string) {
  const num = parseInt(value, 10)
  if (!isNaN(num) && num >= 1) {
    emit('update-entry', entry.id, { chapterNumber: num })
  }
}

/** 更新章节名 */
function onNameChange(entry: ImportEntry, value: string) {
  emit('update-entry', entry.id, { chapterName: value })
}

/** 是否可以导入（无冲突且有条目） */
const canImport = computed(() => props.conflictNumbers.length === 0 && props.entries.length > 0)

function handleImport() {
  if (canImport.value) emit('start-import')
}
</script>

<template>
  <div class="preview-table-wrapper">
    <!-- 冲突提示 -->
    <div v-if="conflictNumbers.length > 0" class="conflict-banner">
      <Icon name="exclamation-circle" :size="16" />
      <span>章节号冲突：第 {{ conflictNumbers.join('、') }} 章与现有章节或表内重复，请调整后再导入</span>
    </div>

    <div class="table-hint">
      <Icon name="information-circle" :size="14" />
      <span>章节号默认从现有最大值 +1 递增，可点击单元格调整；双击章节名编辑</span>
    </div>

    <!-- 表格 -->
    <div class="preview-table">
      <div class="table-head">
        <div class="col-seq">序</div>
        <div class="col-num">章节号</div>
        <div class="col-name">章节名</div>
        <div class="col-file">文件名</div>
        <div class="col-words">字数</div>
        <div class="col-actions">操作</div>
      </div>
      <div class="table-body">
        <div
          v-for="(entry, idx) in entries"
          :key="entry.id"
          class="table-row"
          :class="{ conflict: isConflict(entry) }"
        >
          <div class="col-seq">{{ idx + 1 }}</div>
          <div class="col-num">
            <input
              type="number"
              min="1"
              class="num-input"
              :value="entry.chapterNumber"
              :class="{ 'has-error': isConflict(entry) }"
              @input="onNumberChange(entry, ($event.target as HTMLInputElement).value)"
            />
          </div>
          <div class="col-name">
            <input
              type="text"
              class="name-input"
              :value="entry.chapterName"
              placeholder="(未命名)"
              @input="onNameChange(entry, ($event.target as HTMLInputElement).value)"
            />
          </div>
          <div class="col-file" :title="entry.fileName">{{ entry.fileName }}</div>
          <div class="col-words">{{ formatWordCount(entry.wordCount) }}</div>
          <div class="col-actions">
            <button
              class="action-btn"
              title="上移"
              :disabled="idx === 0"
              @click="emit('move-entry', entry.id, 'up')"
            >
              <Icon name="chevron-up" :size="14" />
            </button>
            <button
              class="action-btn"
              title="下移"
              :disabled="idx === entries.length - 1"
              @click="emit('move-entry', entry.id, 'down')"
            >
              <Icon name="chevron-down" :size="14" />
            </button>
            <button
              class="action-btn danger"
              title="删除"
              @click="emit('remove-entry', entry.id)"
            >
              <Icon name="trash" :size="14" />
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- 底部操作 -->
    <div class="table-footer">
      <span class="entry-count">共 {{ entries.length }} 章</span>
      <button
        class="btn-primary"
        :disabled="!canImport"
        @click="handleImport"
      >
        <Icon name="arrow-up-tray" :size="15" />
        <span>导入 {{ entries.length }} 章</span>
      </button>
    </div>
  </div>
</template>

<style scoped>
.preview-table-wrapper {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.conflict-banner {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.5rem 0.75rem;
  background: color-mix(in srgb, var(--danger) 8%, transparent);
  border: 1px solid color-mix(in srgb, var(--danger) 20%, transparent);
  border-radius: var(--radius-sm);
  font-size: 0.8125rem;
  color: var(--danger);
}

.table-hint {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  font-size: 0.75rem;
  color: var(--text-muted);
}

.preview-table {
  border: 1px solid var(--line-faint);
  border-radius: var(--radius-sm);
  overflow: hidden;
  max-height: 340px;
  overflow-y: auto;
}

.table-head {
  display: grid;
  grid-template-columns: 32px 80px 1fr 160px 60px 100px;
  gap: 0.5rem;
  padding: 0.5rem 0.625rem;
  background: var(--bg-tertiary);
  border-bottom: 1px solid var(--line-faint);
  font-size: var(--text-xs);
  font-weight: 600;
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.02em;
  position: sticky;
  top: 0;
  z-index: 1;
}

.table-body {
  display: flex;
  flex-direction: column;
}

.table-row {
  display: grid;
  grid-template-columns: 32px 80px 1fr 160px 60px 100px;
  gap: 0.5rem;
  padding: 0.4375rem 0.625rem;
  border-bottom: 1px solid var(--line-faint);
  align-items: center;
  font-size: 0.8125rem;
  transition: background var(--dur-1) var(--ease-out);
}

.table-row:last-child {
  border-bottom: none;
}

.table-row:hover {
  background: var(--state-hover);
}

.table-row.conflict {
  background: color-mix(in srgb, var(--danger) 4%, transparent);
}

.col-seq {
  font-size: 0.75rem;
  color: var(--text-muted);
  font-variant-numeric: tabular-nums;
}

.col-num {
  min-width: 0;
}

.num-input,
.name-input {
  width: 100%;
  padding: 0.25rem 0.375rem;
  font-size: 0.8125rem;
  background: var(--bg-primary);
  border: 1px solid var(--line);
  border-radius: var(--radius-xs);
  color: var(--text-primary);
  font-family: inherit;
}

.num-input {
  text-align: center;
  font-variant-numeric: tabular-nums;
}

.num-input.has-error {
  border-color: var(--danger);
  background: color-mix(in srgb, var(--danger) 5%, transparent);
}

.num-input:focus,
.name-input:focus {
  outline: none;
  border-color: var(--accent-500);
}

.col-file {
  font-size: 0.75rem;
  color: var(--text-muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  min-width: 0;
}

.col-words {
  font-size: 0.75rem;
  color: var(--text-secondary);
  font-variant-numeric: tabular-nums;
  text-align: right;
}

.col-actions {
  display: flex;
  gap: 0.125rem;
  justify-content: flex-end;
}

.action-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 1.5rem;
  height: 1.5rem;
  padding: 0;
  background: transparent;
  border: none;
  border-radius: var(--radius-xs);
  color: var(--text-muted);
  cursor: pointer;
  transition: all var(--dur-1) var(--ease-out);
}

.action-btn:hover:not(:disabled) {
  background: var(--state-hover);
  color: var(--text-primary);
}

.action-btn.danger:hover {
  color: var(--danger);
  background: color-mix(in srgb, var(--danger) 8%, transparent);
}

.action-btn:disabled {
  opacity: 0.3;
  cursor: not-allowed;
}

.table-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding-top: 0.5rem;
}

.entry-count {
  font-size: 0.8125rem;
  color: var(--text-secondary);
}

.btn-primary {
  display: inline-flex;
  align-items: center;
  gap: 0.375rem;
  padding: 0.5rem 1rem;
  font-size: 0.8125rem;
  font-weight: 500;
  background: var(--accent-500);
  color: var(--bg-canvas);
  border: none;
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: background var(--dur-2) var(--ease-out);
}

.btn-primary:hover:not(:disabled) {
  background: var(--accent-600);
}

.btn-primary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
</style>
