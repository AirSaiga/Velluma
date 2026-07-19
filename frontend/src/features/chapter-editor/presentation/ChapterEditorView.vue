<script setup lang="ts">
import { ref, watch, computed } from 'vue'
import RichTextEditor from '../../../components/RichTextEditor.vue'
import WorkflowProgressGraph from '../../../components/WorkflowProgressGraph.vue'
import ClarificationModal from './ClarificationModal.vue'
import AgenticSettingsModal from './AgenticSettingsModal.vue'
import BeatReviewModal from './BeatReviewModal.vue'
import CompletionModal from './CompletionModal.vue'
import PublishModal from './PublishModal.vue'
import type { ApiConfig, Chapter, Character, ChapterCard } from '../../../types'
import type { Asset } from '../../../shared/types'
import type { BeatEditorItem } from '../../../types'

const props = defineProps<{
  beatPreviewError: string
  beatPreviewLoading: boolean
  chapterSummary: string | null
  characterUpdates: Array<{
    character_id: string
    character_name: string
    old_state: string
    new_state: string
  }>
  characterExtraction: any
  characters: Character[]
  assets?: Asset[]
  toggleAsset: (assetId: string) => void
  isAssetSelected: (assetId: string) => boolean
  closeAgenticSettingsModal: () => void
  closeBeatReviewModal: () => void
  closeCompletionModal: () => void
  closePublishModal: () => void
  confirmBeatsAndGenerate: () => void
  completionMessage: string
  completionTitle: string
  formError: string
  getBeatHookLabel: (beat: BeatEditorItem) => string
  getMetaCollapsedLabel: () => string
  getWorkflowStageLabel: () => string
  handleContentUpdate: (content: string) => void
  handleEditorEntityFocus: (keyword: string) => void
  handleFormatText: (text: string) => void
  handleOptimize: () => void
  handlePartialOptimize: (payload: { selection: any, instruction: string, mode?: string, tone?: string | null }) => void
  handleOutlineInput: (event: Event) => void
  handleAssetsSchemaInput: (event: Event) => void
  handleTitleInput: (event: Event) => void
  inspirationActiveCharacterIds: string[]
  isAgenticMode: boolean
  isCharacterSelected: (charId: string) => boolean
  isEditorDisabled: boolean
  isFormatting: boolean
  isGenerating: boolean
  isLoadingOverlay: boolean
  isPublishing: boolean
  isStreamMode: boolean
  localMetaCollapsed: boolean
  openAgenticSettingsModal: () => void
  openInspirationModal: () => void
  optimizationFeedback: string
  previewBeats: BeatEditorItem[]
  publishChapter: () => void
  selectedChapter: Chapter | null
  setEditorRef: (editor: any) => void
  scrollToCritique: (comment: any) => void
  setOptimizationFeedback: (value: string) => void
  showAgenticSettingsModal: boolean
  showBeatReviewModal: boolean
  showCompletionModal: boolean
  showInspirationModal: boolean
  showPublishModal: boolean
  showClarificationModal: boolean
  isClarifyingOutline: boolean
  clarificationResult: {
    is_ambiguous: boolean
    identified_issues?: string[]
    clarification_suggestions?: string[]
    refined_text?: string
  } | null
  closeClarificationModal: () => void
  handleApplyClarification: (newOutlineText: string) => void
  handleSubmitClarificationAnswers: (answers: { questionId: string, answer: string }[], originalOutline: string) => void
  startGenerate: () => void
  toggleAgenticMode: () => void
  toggleCharacter: (charId: string) => void
  toggleMetaCollapsed: () => void
  toggleStreamMode: () => void
  workflowState: any
  apiConfig: ApiConfig
  bookId?: string
  critiqueResult?: any
  saveStatus?: 'idle' | 'saving' | 'saved' | 'error'
  lastSavedAt?: Date | null
  cancelGeneration?: () => void
  updatePreviewBeats?: (beats: BeatEditorItem[]) => void
  // CP2.5b：合并闸门——章节卡 + 重规划
  chapterCard?: ChapterCard | null
  planDegraded?: { reason: string; action: string; detail?: string } | null
  regenerateBeats?: (editedCardFields: Record<string, any>) => Promise<boolean>
  // CP4.5：skip_plan_gate 兼容开关已移除
}>()

const emit = defineEmits<{
  (e: 'request-critique', content: string): void
  (e: 'intent-generate', payload: any): void
  (e: 'intent-save', payload: any): void
  (e: 'update:previewBeats', beats: BeatEditorItem[]): void
  (e: 'regenerate-beats', editedCardFields: Record<string, any>): void
}>()

function handleUpdatePreviewBeats(beats: BeatEditorItem[]) {
  props.updatePreviewBeats?.(beats)
  emit('update:previewBeats', beats)
}

// CP2.5b：用户编辑章节卡后触发节拍重规划
async function handleRegenerateBeats(editedCardFields: Record<string, any>) {
  if (props.regenerateBeats) {
    await props.regenerateBeats(editedCardFields)
  } else {
    emit('regenerate-beats', editedCardFields)
  }
}

const saveStatusLabel = computed(() => {
  switch (props.saveStatus) {
    case 'saving': return '保存中...'
    case 'saved': return props.lastSavedAt ? `已保存 ${formatTime(props.lastSavedAt)}` : '已保存'
    case 'error': return '保存失败'
    default: return ''
  }
})

function formatTime(date: Date) {
  const now = new Date()
  const diff = Math.floor((now.getTime() - date.getTime()) / 1000)
  if (diff < 5) return '刚刚'
  if (diff < 60) return `${diff}秒前`
  if (diff < 3600) return `${Math.floor(diff / 60)}分钟前`
  return `${date.getHours().toString().padStart(2, '0')}:${date.getMinutes().toString().padStart(2, '0')}`
}

const editorRef = ref<any>(null)
watch(editorRef, (editor) => {
  props.setEditorRef(editor)
})

watch(() => props.critiqueResult, (newVal) => {
  if (!editorRef.value) return
  if (newVal) {
    editorRef.value.setCritiqueData(newVal)
  } else {
    editorRef.value.setCritiqueData(null)
  }
})

</script>

<template>
  <div class="h-full flex flex-col overflow-hidden px-6 py-4">
    <div v-if="selectedChapter" class="max-w-[920px] w-full mx-auto flex flex-col h-full space-y-3">
      <!-- 章节标题行 -->
      <div class="flex items-center justify-between gap-3 flex-shrink-0">
        <div class="flex-1 flex items-center gap-2">
          <span class="text-xl font-heading font-bold text-[var(--text-primary)] shrink-0">
            {{ selectedChapter.chapter_name || `第${selectedChapter.chapter_number}章` }}
          </span>
          <input
            :value="selectedChapter.title"
            @input="handleTitleInput"
            class="flex-1 text-xl font-heading font-semibold text-[var(--text-primary)] bg-transparent hover:bg-black/5 focus:bg-[var(--bg-canvas)] focus:ring-1 focus:ring-[var(--accent-500)] focus:outline-none px-3 py-1.5 rounded-lg transition-all placeholder:text-[var(--text-muted)] placeholder:font-normal"
            placeholder="输入章节标题..."
          />
          <span
            v-if="saveStatusLabel"
            class="text-[11px] text-[var(--text-muted)] transition-opacity"
            :class="saveStatus === 'saving' ? 'opacity-100' : 'opacity-80'"
          >
            {{ saveStatusLabel }}
          </span>
        </div>
        <button
          @click="publishChapter"
          :disabled="isPublishing || isGenerating"
          class="px-3 py-1.5 rounded-lg text-xs font-medium transition-colors flex items-center gap-1.5 shadow-sm"
          :class="selectedChapter.status === 'published' 
            ? 'bg-emerald-50 text-emerald-600 ring-1 ring-emerald-200 hover:bg-emerald-100' 
            : 'bg-[var(--bg-primary)] text-ink-600 ring-1 ring-[var(--border-color)] hover:bg-parchment-100'"
        >
          <svg v-if="isPublishing" class="animate-spin h-3.5 w-3.5" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
          </svg>
          <template v-else>
            <svg v-if="selectedChapter.status === 'published'" class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" />
            </svg>
            <svg v-else class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" />
            </svg>
          </template>
          {{ selectedChapter.status === 'published' ? '已发布 · 点击撤回' : '发布' }}
        </button>
      </div>

      <!-- 章节大纲与生成 -->
      <div class="rounded-xl bg-[var(--bg-panel)] flex-shrink-0 overflow-hidden border border-[var(--border-color)]/50 transition-all duration-300">
        <div class="px-3 py-2.5 flex items-start gap-3">
          <div class="flex-1 min-w-0">
            <label class="text-[10px] font-medium text-[var(--text-secondary)] mb-1 block flex items-center gap-1">
              <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/>
              </svg>
              章节大纲
            </label>
            <textarea
              :value="selectedChapter.outline_text"
              @input="handleOutlineInput"
              rows="2"
              class="w-full px-2.5 py-2 rounded-lg bg-[var(--bg-canvas)] text-[var(--text-primary)] text-xs leading-relaxed focus:outline-none ring-1 ring-transparent focus:ring-[var(--accent-500)] resize-none"
              placeholder="简述本章的主要情节、场景和冲突..."
            />
          </div>
          
          <!-- 主要操作区 -->
          <div class="flex flex-col gap-2 flex-shrink-0">
            <button
              @click="startGenerate"
              :disabled="isGenerating || beatPreviewLoading || isClarifyingOutline || !selectedChapter.outline_text.trim()"
              class="h-9 px-4 rounded-lg bg-[var(--accent-500)] text-white text-xs font-semibold shadow-sm shadow-accent-400/30 disabled:opacity-40 transition-all hover:bg-accent-600 hover:shadow-md flex items-center gap-1.5"
            >
              <svg v-if="beatPreviewLoading || isGenerating || isClarifyingOutline" class="animate-spin h-3.5 w-3.5" fill="none" viewBox="0 0 24 24">
                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
              </svg>
              <svg v-else class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z" />
              </svg>
              {{ isClarifyingOutline ? '澄清中' : (beatPreviewLoading ? '规划中' : (isGenerating ? '生成中' : '智能生成')) }}
            </button>

            <!-- CP4.5：skip_plan_gate 兼容开关已移除（合并闸门为唯一路径）-->

            <div class="flex items-center justify-center gap-1">
              <button
                @click="openInspirationModal"
                :disabled="isGenerating"
                title="获取灵感"
                class="h-7 w-8 flex items-center justify-center rounded-md text-[var(--text-muted)] hover:text-[var(--accent-500)] hover:bg-accent-50 disabled:opacity-40 transition-colors"
              >
                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
                </svg>
              </button>
              <button
                @click="emit('request-critique', editorRef?.getContent() || selectedChapter.content_text || selectedChapter.draft_text || '')"
                :disabled="isGenerating"
                title="主编指导"
                class="h-7 w-8 flex items-center justify-center rounded-md text-[var(--text-muted)] hover:text-[var(--accent-500)] hover:bg-accent-50 disabled:opacity-40 transition-colors"
              >
                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-3 7h3m-3 4h3m-6-4h.01M9 16h.01" />
                </svg>
              </button>
              <button
                @click="openAgenticSettingsModal"
                :disabled="isGenerating || !isAgenticMode"
                title="生成参数设置"
                class="h-7 w-8 flex items-center justify-center rounded-md text-[var(--text-muted)] hover:text-[var(--accent-500)] hover:bg-accent-50 disabled:opacity-40 transition-colors"
              >
                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 6V4m0 2a2 2 0 100 4m0-4a2 2 0 110 4m-6 8a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4m6 6v10m6-2a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4" />
                </svg>
              </button>
            </div>
          </div>
        </div>
      </div>

      <!-- 编辑器区域 -->
      <div class="relative rounded-2xl bg-parchment-50 shadow-[0_8px_20px_rgba(18,38,63,0.06)] flex-1 min-h-0 flex flex-col overflow-hidden">
        <div
          v-if="isGenerating && isAgenticMode"
          class="absolute inset-0 z-10 flex items-center justify-center bg-parchment-50/85 backdrop-blur-sm rounded-2xl transition-all duration-300"
        >
          <div class="w-full max-w-2xl mx-4">
            <div class="bg-[var(--bg-primary)] rounded-2xl p-6 shadow-xl ring-1 ring-[var(--border-color)]">
              <WorkflowProgressGraph
                :current-event="workflowState?.currentEvent"
                :message="workflowState?.message"
                :iteration="workflowState?.iteration"
                :revision-count="workflowState?.revisionCount"
              />
              <div class="flex justify-center mt-5">
                <button
                  v-if="cancelGeneration"
                  @click="cancelGeneration"
                  class="px-4 py-2 text-sm rounded-lg bg-rose-50 text-rose-600 hover:bg-rose-100 ring-1 ring-rose-200 transition-colors flex items-center gap-1.5"
                >
                  <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
                  </svg>
                  取消生成
                </button>
              </div>
            </div>
          </div>
        </div>

        <div
          v-if="beatPreviewLoading"
          class="absolute inset-0 z-10 flex items-center justify-center bg-parchment-50/85 backdrop-blur-sm rounded-2xl transition-all duration-300"
        >
          <div class="w-full max-w-2xl mx-4">
            <div class="bg-[var(--bg-primary)] rounded-2xl p-6 shadow-xl ring-1 ring-[var(--border-color)]">
              <WorkflowProgressGraph
                current-event="PLANNING"
                message="正在根据大纲和前文分析剧情走向..."
                :iteration="1"
                :revision-count="0"
              />
            </div>
          </div>
        </div>

        <div
          v-if="isPublishing"
          class="absolute inset-0 z-10 flex flex-col items-center justify-center bg-parchment-50/80 backdrop-blur-[2px] rounded-2xl transition-all duration-300"
        >
          <div class="relative flex items-center justify-center w-24 h-24 mb-8">
            <div class="absolute inset-0 rounded-full border-[6px] border-accent-100"></div>
            <div class="absolute inset-0 rounded-full border-[6px] border-accent-500 border-t-transparent animate-spin"></div>
          </div>

          <div class="flex flex-col items-center gap-3">
            <h3 class="text-3xl font-heading font-bold text-accent-900 tracking-tight">
              发布中...
            </h3>
            <p class="text-lg text-accent-600/90 font-medium max-w-xl text-center px-6 leading-relaxed">
              正在更新章节状态及角色动态...
            </p>
          </div>
        </div>

        <RichTextEditor
          ref="editorRef"
          :id="selectedChapter.id"
          :book-id="bookId"
          :model-value="selectedChapter.content_text || selectedChapter.draft_text || ''"
          @update:model-value="handleContentUpdate"
          @entity-focus-change="handleEditorEntityFocus"
          @request-format="handleFormatText"
          @request-partial-optimize="handlePartialOptimize"
          :disabled="isEditorDisabled"
          :is-formatting="isFormatting"
          placeholder="在此处开始写作或生成内容..."
        />
      </div>
    </div>

    <div v-else class="h-full flex items-center justify-center">
      <div class="text-center">
        <div class="w-12 h-12 mx-auto mb-3 rounded-full bg-[var(--bg-panel)] flex items-center justify-center">
          <svg class="w-6 h-6 text-[var(--text-muted)]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/>
          </svg>
        </div>
        <p class="text-xs text-[var(--text-muted)]">选择一个章节或新建章节开始编辑</p>
      </div>
    </div>
  </div>

  <AgenticSettingsModal
    :show="showAgenticSettingsModal && isAgenticMode"
    :selected-chapter="selectedChapter"
    :api-config="apiConfig"
    @close="closeAgenticSettingsModal"
    @save="(payload) => { closeAgenticSettingsModal(); emit('intent-save', payload); }"
    @generate="(payload) => { closeAgenticSettingsModal(); emit('intent-generate', payload); }"
  />

  <BeatReviewModal
    :show="showBeatReviewModal && isAgenticMode"
    :preview-beats="previewBeats"
    :beat-preview-error="beatPreviewError"
    :chapter-card="chapterCard"
    :plan-degraded="planDegraded"
    :beat-preview-loading="beatPreviewLoading"
    @close="closeBeatReviewModal"
    @confirm="confirmBeatsAndGenerate"
    @update:previewBeats="handleUpdatePreviewBeats"
    @regenerate="handleRegenerateBeats"
  />

  <ClarificationModal
    :show="showClarificationModal"
    :clarification-result="clarificationResult"
    @close="closeClarificationModal"
    @apply="handleApplyClarification"
    @submit-answers="handleSubmitClarificationAnswers"
  />

  <CompletionModal
    :show="showCompletionModal"
    :title="completionTitle"
    :message="completionMessage"
    @close="closeCompletionModal"
  />

  <PublishModal
    :show="showPublishModal"
    :character-updates="characterUpdates"
    :character-extraction="characterExtraction"
    @close="closePublishModal"
  />
</template>

<style scoped>
/* 模态框动画 */
.modal-backdrop-enter-active,
.modal-backdrop-leave-active {
  transition: opacity 0.3s ease;
}

.modal-backdrop-enter-from,
.modal-backdrop-leave-to {
  opacity: 0;
}

.modal-content-enter-active {
  transition: all 0.4s cubic-bezier(0.16, 1, 0.3, 1);
}

.modal-content-leave-active {
  transition: all 0.2s ease;
}

.modal-content-enter-from {
  opacity: 0;
  transform: scale(0.95) translateY(20px);
}

.modal-content-leave-to {
  opacity: 0;
  transform: scale(0.98);
}
</style>
