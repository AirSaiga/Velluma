<script setup lang="ts">
import type { Chapter, Character } from '../../../types'
import ChapterEditorView from '../presentation/ChapterEditorView.vue'
import InspirationModal from '../../../components/InspirationModal.vue'
import { useChapterEditorContainer } from './useChapterEditorContainer'

interface ApiConfig {
  api_key: string
  base_url: string
  model: string
}

const props = defineProps<{
  selectedChapter: Chapter | null
  characters: Character[]
  apiConfig: ApiConfig
  bookId?: string
  metaCollapsed?: boolean
}>()

const emit = defineEmits(['update-chapter', 'update-meta-collapsed', 'refresh-characters'])
const viewModel = useChapterEditorContainer(props, emit)
</script>

<template>
  <ChapterEditorView
    :AGENTIC_FIELD_CONFIG="viewModel.AGENTIC_FIELD_CONFIG"
    :AGENTIC_GROUPS="viewModel.AGENTIC_GROUPS"
    :agentic-form="viewModel.agenticForm.value"
    :agentic-group-fields="viewModel.agenticGroupFields.value"
    :agentic-validation="viewModel.agenticValidation.value"
    :beat-preview-error="viewModel.beatPreviewError.value"
    :beat-preview-loading="viewModel.beatPreviewLoading.value"
    :can-submit-agentic="viewModel.canSubmitAgentic.value"
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
    :first-field-feedback="viewModel.firstFieldFeedback.value"
    :form-error="viewModel.formError.value"
    :get-agentic-field-feedback-text="viewModel.getAgenticFieldFeedbackText"
    :get-agentic-field-input-type="viewModel.getAgenticFieldInputType"
    :get-agentic-field-max="viewModel.getAgenticFieldMax"
    :get-agentic-field-min="viewModel.getAgenticFieldMin"
    :get-agentic-field-step="viewModel.getAgenticFieldStep"
    :get-agentic-field-value="viewModel.getAgenticFieldValue"
    :get-beat-hook-label="viewModel.getBeatHookLabel"
    :get-meta-collapsed-label="viewModel.getMetaCollapsedLabel"
    :get-pacing-style-value="viewModel.getPacingStyleValue"
    :get-tension-level-value="viewModel.getTensionLevelValue"
    :get-workflow-stage-label="viewModel.getWorkflowStageLabel"
    :handle-pacing-style-input="viewModel.handlePacingStyleInput"
    :handle-content-update="viewModel.handleContentUpdate"
    :handle-format-text="viewModel.handleFormatText"
    :handle-optimize="viewModel.handleOptimize"
    :handle-partial-optimize="viewModel.handlePartialOptimize"
    :handle-outline-input="viewModel.handleOutlineInput"
    :handle-tension-level-input="viewModel.handleTensionLevelInput"
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
    :normalize-agentic-field="viewModel.normalizeAgenticField"
    :open-agentic-settings-modal="viewModel.openAgenticSettingsModal"
    :open-inspiration-modal="viewModel.openInspirationModal"
    :pacing-style-options="viewModel.pacingStyleOptions"
    :optimization-feedback="viewModel.optimizationFeedback.value"
    :preview-beats="viewModel.previewBeats.value"
    :publish-chapter="viewModel.publishChapter"
    :rag-weight-total="viewModel.ragWeightTotal.value"
    :restore-agentic-defaults="viewModel.restoreAgenticDefaults"
    :restore-agentic-field="viewModel.restoreAgenticField"
    :selected-chapter="viewModel.selectedChapter.value"
    :set-agentic-field-value="viewModel.setAgenticFieldValue"
    :set-editor-ref="viewModel.setEditorRef"
    :set-optimization-feedback="viewModel.setOptimizationFeedback"
    :set-word-count="viewModel.setWordCount"
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
    :word-count-max="viewModel.wordCountMax.value"
    :word-count-min="viewModel.wordCountMin.value"
    :workflow-state="viewModel.workflowState.value"
    :api-config="props.apiConfig"
    :book-id="props.bookId"
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
