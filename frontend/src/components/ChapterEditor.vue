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
    @update-chapter="handleUpdateChapter"
    @update-meta-collapsed="handleMetaCollapsed"
    @refresh-characters="handleRefreshCharacters"
    @editor-entity-focus="handleEditorEntityFocus"
  />
</template>
