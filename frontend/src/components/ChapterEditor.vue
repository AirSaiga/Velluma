<script setup lang="ts">
import { ref } from 'vue'
import ChapterEditorContainer from '../features/chapter-editor/containers/ChapterEditorContainer.vue'
import type { ApiConfig, Chapter, Character } from '../types'

const props = defineProps<{
  selectedChapter: Chapter | null
  characters: Character[]
  apiConfig: ApiConfig
  bookId?: string | null
  metaCollapsed?: boolean
  /** 生成预览 HTML（非 null 时编辑器默认只读显示预览，替代章节正文） */
  previewHtml?: string | null
  /** 主编辑器直改：步进裁决窗口期预览可编辑 */
  previewEditable?: boolean
  /** 主编辑器直改：当前可编辑段的 segment_index */
  previewSegmentIndex?: number | null
}>()

const emit = defineEmits(['update-chapter', 'update-meta-collapsed', 'refresh-characters', 'editor-entity-focus', 'preview-segment-edit'])

const containerRef = ref<any>(null)

function handleUpdateChapter(id: string, updates: Record<string, unknown>) {
  emit('update-chapter', id, updates)
}

function handleMetaCollapsed(value: boolean) {
  emit('update-meta-collapsed', value)
}

function handleRefreshCharacters() {
  emit('refresh-characters')
}

function handleEditorEntityFocus(keyword: string) {
  emit('editor-entity-focus', keyword)
}
</script>

<template>
  <ChapterEditorContainer
    ref="containerRef"
    :selected-chapter="props.selectedChapter"
    :characters="props.characters"
    :api-config="props.apiConfig"
    :book-id="props.bookId"
    :meta-collapsed="props.metaCollapsed"
    :preview-html="props.previewHtml"
    :preview-editable="props.previewEditable"
    :preview-segment-index="props.previewSegmentIndex"
    @update-chapter="handleUpdateChapter"
    @update-meta-collapsed="handleMetaCollapsed"
    @refresh-characters="handleRefreshCharacters"
    @editor-entity-focus="handleEditorEntityFocus"
    @preview-segment-edit="(text: string) => emit('preview-segment-edit', text)"
  />
</template>
