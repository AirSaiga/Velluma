<script setup lang="ts">
import { ref } from 'vue'
import ChapterEditorContainer from '../features/chapter-editor/containers/ChapterEditorContainer.vue'
import type { ApiConfig, Chapter, Character } from '../types'
import type { EntityFocusPayload } from '../shared/types'

const props = defineProps<{
  selectedChapter: Chapter | null
  characters: Character[]
  apiConfig: ApiConfig
  bookId?: string | null
  metaCollapsed?: boolean
  /** 保存状态（WorkspaceView 落库状态下传，页面头显示） */
  saveStatus?: 'idle' | 'saving' | 'saved' | 'error'
  lastSavedAt?: Date | null
  /** 当前章节字数（WorkspaceView 剥 HTML 计字符，页面头 meta 行显示） */
  wordCount?: number
  /** AI 状态短句（08 期 §4.2：顶栏退役后透传至页面头 meta 行） */
  aiStateLabel?: string
  aiStateError?: boolean
}>()

const emit = defineEmits(['update-chapter', 'update-meta-collapsed', 'refresh-characters', 'editor-entity-focus'])

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

function handleEditorEntityFocus(payload: EntityFocusPayload) {
  emit('editor-entity-focus', payload)
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
    :save-status="props.saveStatus"
    :last-saved-at="props.lastSavedAt"
    :word-count="props.wordCount"
    :ai-state-label="props.aiStateLabel"
    :ai-state-error="props.aiStateError"
    @update-chapter="handleUpdateChapter"
    @update-meta-collapsed="handleMetaCollapsed"
    @refresh-characters="handleRefreshCharacters"
    @editor-entity-focus="handleEditorEntityFocus"
  >
    <template #page-top><slot name="page-top" /></template>
  </ChapterEditorContainer>
</template>
