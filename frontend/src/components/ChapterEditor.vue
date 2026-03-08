<script setup lang="ts">
import ChapterEditorContainer from '../features/chapter-editor/containers/ChapterEditorContainer.vue'
import type { Chapter, Character, ApiConfig } from '../types'

const props = defineProps<{
  selectedChapter: Chapter | null
  characters: Character[]
  apiConfig: ApiConfig
  bookId?: string | null
  metaCollapsed?: boolean
}>()

const emit = defineEmits(['update-chapter', 'update-meta-collapsed', 'refresh-characters', 'editor-entity-focus'])

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
    :selected-chapter="props.selectedChapter"
    :characters="props.characters"
    :api-config="props.apiConfig"
    :book-id="props.bookId"
    :meta-collapsed="props.metaCollapsed"
    @update-chapter="handleUpdateChapter"
    @update-meta-collapsed="handleMetaCollapsed"
    @refresh-characters="handleRefreshCharacters"
    @editor-entity-focus="handleEditorEntityFocus"
  />
</template>
