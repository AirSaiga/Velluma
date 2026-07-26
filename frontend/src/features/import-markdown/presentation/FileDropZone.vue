<script setup lang="ts">
/**
 * 文件拖拽/选择区（Markdown 导入向导 Step 1）。
 *
 * 职责：纯展示——拖拽区域 + 文件选择按钮，过滤非 .md 文件后回传 File[]。
 * 不处理解析逻辑（由容器通过 useMarkdownImport.ingestFiles 完成）。
 */
import { ref } from 'vue'
import Icon from '../../../components/Icon.vue'

defineProps<{
  /** 被跳过的文件列表（空文件/读取失败） */
  skippedFiles?: { fileName: string; reason: string }[]
  /** 是否正在解析中（ingestFiles 异步执行时） */
  parsing?: boolean
}>()

const emit = defineEmits<{
  'files-selected': [File[]]
}>()

const isDragOver = ref(false)
const fileInputRef = ref<HTMLInputElement | null>(null)

function onDrop(e: DragEvent) {
  isDragOver.value = false
  const files = Array.from(e.dataTransfer?.files || [])
  const mdFiles = files.filter((f) => /\.(md|markdown)$/i.test(f.name))
  if (mdFiles.length > 0) {
    emit('files-selected', mdFiles)
  }
}

function onDragOver() {
  isDragOver.value = true
}

function onDragLeave() {
  isDragOver.value = false
}

function onFileInputChange(e: Event) {
  const target = e.target as HTMLInputElement
  const files = Array.from(target.files || [])
  if (files.length > 0) {
    emit('files-selected', files)
  }
  // 重置 input 以便重复选择同一文件
  target.value = ''
}

function triggerFileInput() {
  fileInputRef.value?.click()
}
</script>

<template>
  <div class="file-drop-zone">
    <div
      class="drop-area"
      :class="{ 'drag-over': isDragOver, parsing }"
      @drop.prevent="onDrop"
      @dragover.prevent="onDragOver"
      @dragleave.prevent="onDragLeave"
      @click="triggerFileInput"
      role="button"
      tabindex="0"
      @keydown.enter="triggerFileInput"
    >
      <div v-if="parsing" class="drop-icon parsing">
        <Icon name="arrow-path" :size="40" class="spin" />
      </div>
      <div v-else class="drop-icon">
        <Icon name="arrow-up-tray" :size="40" />
      </div>
      <p class="drop-title">{{ parsing ? '正在解析…' : '拖拽 .md 文件到此处' }}</p>
      <p class="drop-hint">{{ parsing ? '请稍候' : '或点击选择文件' }}</p>
      <p class="drop-format">仅支持 .md / .markdown · 可多选</p>
    </div>

    <input
      ref="fileInputRef"
      type="file"
      accept=".md,.markdown"
      multiple
      class="file-input-hidden"
      @change="onFileInputChange"
    />

    <!-- 被跳过的文件提示 -->
    <div v-if="skippedFiles && skippedFiles.length > 0" class="skipped-list">
      <div v-for="(item, idx) in skippedFiles" :key="idx" class="skipped-item">
        <Icon name="exclamation-circle" :size="14" />
        <span class="skip-name">{{ item.fileName }}</span>
        <span class="skip-reason">{{ item.reason }}，将跳过</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.file-drop-zone {
  display: flex;
  flex-direction: column;
  gap: 0.875rem;
}

.drop-area {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 0.375rem;
  padding: 2.5rem 1.5rem;
  border: 2px dashed var(--border-color);
  border-radius: 0.625rem;
  cursor: pointer;
  transition: all 0.15s ease;
  text-align: center;
  background: var(--bg-primary);
}

.drop-area:hover,
.drop-area.drag-over {
  border-color: var(--accent-500);
  background: var(--hover-bg);
}

.drop-area.parsing {
  pointer-events: none;
  opacity: 0.7;
}

.drop-icon {
  color: var(--text-muted);
  margin-bottom: 0.5rem;
}

.drop-icon.parsing {
  color: var(--accent-500);
}

.drop-title {
  font-size: 0.9375rem;
  font-weight: 500;
  color: var(--text-primary);
  margin: 0;
}

.drop-hint {
  font-size: 0.8125rem;
  color: var(--text-secondary);
  margin: 0;
}

.drop-format {
  font-size: 0.6875rem;
  color: var(--text-muted);
  margin: 0.375rem 0 0;
}

.file-input-hidden {
  display: none;
}

.skipped-list {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  padding: 0.625rem 0.75rem;
  background: rgba(245, 158, 11, 0.08);
  border: 1px solid rgba(245, 158, 11, 0.2);
  border-radius: 0.375rem;
}

.skipped-item {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  font-size: 0.75rem;
  color: #b45309;
}

.skip-name {
  font-weight: 500;
}

.skip-reason {
  opacity: 0.8;
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
</style>
