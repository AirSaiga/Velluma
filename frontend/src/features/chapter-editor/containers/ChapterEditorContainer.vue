<script setup lang="ts">
import type { Chapter, Character, ApiConfig } from '../../../types'
import type { Asset } from '../../../shared/types'
import ChapterEditorView from '../presentation/ChapterEditorView.vue'
import InspirationModal from '../../../components/InspirationModal.vue'
import CritiqueModal from '../presentation/CritiqueModal.vue'
import { useChapterEditorContainer } from './useChapterEditorContainer'

const props = defineProps<{
  selectedChapter: Chapter | null
  characters: Character[]
  apiConfig: ApiConfig
  bookId?: string
  metaCollapsed?: boolean
  assets?: Asset[]
  /** 保存状态（真实落库在 WorkspaceView，经 props 下传显示在页面头） */
  saveStatus?: 'idle' | 'saving' | 'saved' | 'error'
  lastSavedAt?: Date | null
}>()

const emit = defineEmits(['update-chapter', 'update-meta-collapsed', 'refresh-characters', 'editor-entity-focus'])
// 警示：必须直接传入响应式 props 对象；展开 {...props} 会在 setup 时拍快照，
// 导致 composable 内的 computed/watch 永远停留在初始值（编辑器不显示）。
const viewModel = useChapterEditorContainer(props, emit)

defineExpose({
  isPublishing: viewModel.isPublishing,
  toggleCharacter: viewModel.toggleCharacter,
  toggleAsset: viewModel.toggleAsset,
  isCharacterSelected: viewModel.isCharacterSelected,
  isAssetSelected: viewModel.isAssetSelected,
  handleAssetsSchemaInput: viewModel.handleAssetsSchemaInput,
  viewModel,
})
</script>

<template>
  <ChapterEditorView
    :character-updates="viewModel.characterUpdates.value"
    :character-extraction="viewModel.characterExtraction.value"
    :close-publish-modal="viewModel.closePublishModal"
    :handle-content-update="viewModel.handleContentUpdate"
    :handle-editor-entity-focus="viewModel.handleEditorEntityFocus"
    :handle-format-text="viewModel.handleFormatText"
    :handle-partial-optimize="viewModel.handlePartialOptimize"
    :handle-title-input="viewModel.handleTitleInput"
    :is-editor-disabled="viewModel.isEditorDisabled.value"
    :is-formatting="viewModel.isFormatting.value"
    :is-publishing="viewModel.isPublishing.value"
    :open-inspiration-modal="viewModel.openInspirationModal"
    :open-critique-modal="viewModel.openCritiqueModal"
    :publish-chapter="viewModel.publishChapter"
    :selected-chapter="viewModel.selectedChapter.value"
    :set-editor-ref="viewModel.setEditorRef"
    :show-publish-modal="viewModel.showPublishModal.value"
    :book-id="props.bookId"
    :save-status="props.saveStatus"
    :last-saved-at="props.lastSavedAt"
  />

  <InspirationModal
    :show="viewModel.showInspirationModal.value"
    :book-id="props.bookId || ''"
    :chapter-id="viewModel.selectedChapter.value?.id || ''"
    :chapter-title="viewModel.selectedChapter.value?.title || ''"
    :current-context="viewModel.selectedChapter.value?.outline_text || viewModel.selectedChapter.value?.summary || ''"
    :active-character-ids="viewModel.inspirationActiveCharacterIds.value"
    :api-config="props.apiConfig"
    @update:show="viewModel.closeInspirationModal"
    @apply-to-outline="viewModel.handleApplyInspirationToOutline"
  />

  <CritiqueModal
    :show="viewModel.showCritiqueModal.value"
    :loading="viewModel.critiqueLoading.value"
    :comments="viewModel.critiqueComments.value"
    :overall-praise="viewModel.critiquePraise.value"
    @close="viewModel.closeCritiqueModal"
  />
</template>
