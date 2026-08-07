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
  /** 生成预览 HTML（非 null 时编辑器默认只读显示预览，替代章节正文） */
  previewHtml?: string | null
  /** 主编辑器直改：步进裁决窗口期预览可编辑 */
  previewEditable?: boolean
  /** 主编辑器直改：当前可编辑段的 segment_index */
  previewSegmentIndex?: number | null
}>()

const emit = defineEmits(['update-chapter', 'update-meta-collapsed', 'refresh-characters', 'editor-entity-focus', 'preview-segment-edit'])
// 警示：必须直接传入响应式 props 对象；展开 {...props} 会在 setup 时拍快照，
// 导致 composable 内的 computed/watch 永远停留在初始值（编辑器不显示）。
const viewModel = useChapterEditorContainer(props, emit)

defineExpose({
  isPublishing: viewModel.isPublishing,
  saveStatus: viewModel.saveStatus,
  lastSavedAt: viewModel.lastSavedAt,
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
    :preview-html="props.previewHtml"
    :preview-editable="props.previewEditable"
    :preview-segment-index="props.previewSegmentIndex"
    @preview-segment-edit="(text: string) => emit('preview-segment-edit', text)"
    :set-editor-ref="viewModel.setEditorRef"
    :show-publish-modal="viewModel.showPublishModal.value"
    :book-id="props.bookId"
    :save-status="viewModel.saveStatus.value"
    :last-saved-at="viewModel.lastSavedAt.value"
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
