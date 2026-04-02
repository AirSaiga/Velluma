<script setup lang="ts">
import { ref } from 'vue'
import ChapterEditorContainer from '../features/chapter-editor/containers/ChapterEditorContainer.vue'
import type { Chapter, Character, ApiConfig } from '../types'

const props = defineProps<{
  selectedChapter: Chapter | null
  characters: Character[]
  apiConfig: ApiConfig
  bookId?: string | null
  metaCollapsed?: boolean
  critiqueResult?: any
}>()

const emit = defineEmits(['update-chapter', 'update-meta-collapsed', 'refresh-characters', 'editor-entity-focus', 'request-critique', 'intent-generate', 'intent-save'])

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

function scrollToCritique(comment: any) {
  if (containerRef.value?.scrollToCritique) {
    containerRef.value.scrollToCritique(comment)
  }
}

defineExpose({
  scrollToCritique
})
</script>

<template>
  <ChapterEditorContainer
    ref="containerRef"
    :selected-chapter="props.selectedChapter"
    :characters="props.characters"
    :api-config="props.apiConfig"
    :book-id="props.bookId"
    :meta-collapsed="props.metaCollapsed"
    :critique-result="props.critiqueResult"
    @update-chapter="handleUpdateChapter"
    @update-meta-collapsed="handleMetaCollapsed"
    @refresh-characters="handleRefreshCharacters"
    @editor-entity-focus="handleEditorEntityFocus"
    @request-critique="(content) => emit('request-critique', content)"
    @intent-generate="(payload) => emit('intent-generate', payload)"
    @intent-save="(payload) => emit('intent-save', payload)"
  />
</template>
