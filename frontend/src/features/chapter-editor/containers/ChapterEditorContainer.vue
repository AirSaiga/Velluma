<script setup lang="ts">
import type { Chapter, Character, ApiConfig } from '../../../types'
import ChapterEditorView from '../presentation/ChapterEditorView.vue'
import InspirationModal from '../../../components/InspirationModal.vue'
import { useChapterEditorContainer } from './useChapterEditorContainer'

const props = defineProps<{
  selectedChapter: Chapter | null
  characters: Character[]
  apiConfig: ApiConfig
  bookId?: string
  metaCollapsed?: boolean
  critiqueResult?: any
}>()

const emit = defineEmits(['update-chapter', 'update-meta-collapsed', 'refresh-characters', 'editor-entity-focus', 'request-critique', 'intent-generate', 'intent-save'])
const viewModel = useChapterEditorContainer(props, emit)

defineExpose({
  scrollToCritique: viewModel.scrollToCritique
})
</script>

<template>
  <ChapterEditorView
    :beat-preview-error="viewModel.beatPreviewError.value"
    :beat-preview-loading="viewModel.beatPreviewLoading.value"
    :chapter-summary="viewModel.chapterSummary.value"
    :character-updates="viewModel.characterUpdates.value"
    :characters="props.characters"
    :close-agentic-settings-modal="viewModel.closeAgenticSettingsModal"
    :close-beat-review-modal="viewModel.closeBeatReviewModal"
    :close-completion-modal="viewModel.closeCompletionModal"
    :close-publish-modal="viewModel.closePublishModal"
    :confirm-beats-and-generate="viewModel.confirmBeatsAndGenerate"
    :completion-message="viewModel.completionMessage.value"
    :completion-title="viewModel.completionTitle.value"
    :form-error="viewModel.formError.value"
    :get-beat-hook-label="viewModel.getBeatHookLabel"
    :get-meta-collapsed-label="viewModel.getMetaCollapsedLabel"
    :get-workflow-stage-label="viewModel.getWorkflowStageLabel"
    :handle-content-update="viewModel.handleContentUpdate"
    :handle-editor-entity-focus="viewModel.handleEditorEntityFocus"
    :handle-format-text="viewModel.handleFormatText"
    :handle-optimize="viewModel.handleOptimize"
    :handle-partial-optimize="viewModel.handlePartialOptimize"
    :handle-outline-input="viewModel.handleOutlineInput"
    :handle-assets-schema-input="viewModel.handleAssetsSchemaInput"
    :handle-title-input="viewModel.handleTitleInput"
    :inspiration-active-character-ids="viewModel.inspirationActiveCharacterIds.value"
    :is-agentic-mode="viewModel.isAgenticMode.value"
    :is-character-selected="viewModel.isCharacterSelected"
    :is-editor-disabled="viewModel.isEditorDisabled.value"
    :is-formatting="viewModel.isFormatting.value"
    :is-generating="viewModel.isGenerating.value"
    :is-loading-overlay="viewModel.isLoadingOverlay.value"
    :is-publishing="viewModel.isPublishing.value"
    :is-stream-mode="viewModel.isStreamMode.value"
    :local-meta-collapsed="viewModel.localMetaCollapsed.value"
    :open-agentic-settings-modal="viewModel.openAgenticSettingsModal"
    :open-inspiration-modal="viewModel.openInspirationModal"
    :optimization-feedback="viewModel.optimizationFeedback.value"
    :preview-beats="viewModel.previewBeats.value"
    :publish-chapter="viewModel.publishChapter"
    :selected-chapter="viewModel.selectedChapter.value"
    :set-editor-ref="viewModel.setEditorRef"
    :scroll-to-critique="viewModel.scrollToCritique"
    :set-optimization-feedback="viewModel.setOptimizationFeedback"
    :show-agentic-settings-modal="viewModel.showAgenticSettingsModal.value"
    :show-beat-review-modal="viewModel.showBeatReviewModal.value"
    :show-completion-modal="viewModel.showCompletionModal.value"
    :show-inspiration-modal="viewModel.showInspirationModal.value"
    :show-publish-modal="viewModel.showPublishModal.value"
    :start-generate="viewModel.startGenerate"
    :toggle-agentic-mode="viewModel.toggleAgenticMode"
    :toggle-character="viewModel.toggleCharacter"
    :toggle-meta-collapsed="viewModel.toggleMetaCollapsed"
    :toggle-stream-mode="viewModel.toggleStreamMode"
    :workflow-state="viewModel.workflowState.value"
    :api-config="props.apiConfig"
    :book-id="props.bookId"
    :critique-result="props.critiqueResult"
    @request-critique="(content) => emit('request-critique', content)"
    @intent-generate="(payload) => emit('intent-generate', payload)"
    @intent-save="(payload) => emit('intent-save', payload)"
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
</template>
