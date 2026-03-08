<script setup lang="ts">
import { ref, watch } from 'vue'
import RichTextEditor from '../../../components/RichTextEditor.vue'
import type { AgenticFormState, ApiConfig, Chapter, Character, PacingStyle } from '../../../types'
import type { AgenticFieldOption } from '../../../composables/useAgenticConfig'

interface BeatPreviewItem {
  position: number
  beat_id?: string
  summary: string
  location?: string
  pov_character?: string
  anchor_pov?: string
  original_actor?: string
  action_summary?: string
  openingState: string
  stoppingState: string
  forbiddenEventsText: string
  word_count_target: number
  target_words: number
  hook_ids: string[]
}

const props = defineProps<{
  AGENTIC_FIELD_CONFIG: Record<string, any>
  AGENTIC_GROUPS: Record<string, any>
  agenticForm: AgenticFormState
  agenticGroupFields: Record<string, Array<keyof AgenticFormState>>
  agenticValidation: { errors: string[] }
  beatPreviewError: string
  beatPreviewLoading: boolean
  canSubmitAgentic: boolean
  chapterSummary: string | null
  characterUpdates: Array<{
    character_id: string
    character_name: string
    old_state: string
    new_state: string
  }>
  characters: Character[]
  closeAgenticSettingsModal: () => void
  closeBeatReviewModal: () => void
  closeCompletionModal: () => void
  closePublishModal: () => void
  confirmBeatsAndGenerate: () => void
  completionMessage: string
  completionTitle: string
  firstFieldFeedback: string
  formError: string
  getAgenticFieldFeedbackText: (field: keyof AgenticFormState) => string
  getAgenticFieldInputType: (field: keyof AgenticFormState) => string
  getAgenticFieldOptions: (field: keyof AgenticFormState) => AgenticFieldOption[]
  getAgenticFieldMax: (field: keyof AgenticFormState) => number | undefined
  getAgenticFieldMin: (field: keyof AgenticFormState) => number
  getAgenticFieldStep: (field: keyof AgenticFormState) => number
  getAgenticFieldValue: (field: keyof AgenticFormState) => string | number
  getBeatHookLabel: (beat: BeatPreviewItem) => string
  getMetaCollapsedLabel: () => string
  getPacingStyleValue: () => PacingStyle
  getTensionLevelValue: () => number
  getWorkflowStageLabel: () => string
  handlePacingStyleInput: (event: Event) => void
  handleContentUpdate: (content: string) => void
  handleEditorEntityFocus: (keyword: string) => void
  handleFormatText: (text: string) => void
  handleOptimize: () => void
  handlePartialOptimize: (payload: { selection: any, instruction: string }) => void
  handleOutlineInput: (event: Event) => void
  handleTensionLevelInput: (event: Event) => void
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
  normalizeAgenticField: () => void
  openAgenticSettingsModal: () => void
  openInspirationModal: () => void
  isAgenticFieldSelect: (field: keyof AgenticFormState) => boolean
  pacingStyleOptions: Array<{ value: PacingStyle; label: string }>
  optimizationFeedback: string
  previewBeats: BeatPreviewItem[]
  anchorPov: string | null
  publishChapter: () => void
  ragWeightTotal: number
  restoreAgenticDefaults: () => void
  restoreAgenticField: (field: keyof AgenticFormState) => void
  selectedChapter: Chapter | null
  setAgenticFieldValue: (field: keyof AgenticFormState, event: Event) => void
  setEditorRef: (editor: any) => void
  setOptimizationFeedback: (value: string) => void
  setWordCount: (value: number) => void
  showAgenticSettingsModal: boolean
  showBeatReviewModal: boolean
  showCompletionModal: boolean
  showInspirationModal: boolean
  showPublishModal: boolean
  startGenerate: () => void
  toggleAgenticMode: () => void
  toggleCharacter: (charId: string) => void
  toggleMetaCollapsed: () => void
  toggleStreamMode: () => void
  wordCountMax: number
  wordCountMin: number
  workflowState: any
  apiConfig: ApiConfig
  bookId?: string
  critiqueResult?: any
}>()

const emit = defineEmits<{
  (e: 'request-critique', content: string): void
}>()

const editorRef = ref<any>(null)
watch(editorRef, (editor) => {
  props.setEditorRef(editor)
})

watch(() => props.critiqueResult, (newVal) => {
  if (newVal && editorRef.value) {
    editorRef.value.setCritiqueData(newVal)
  }
})

</script>

<template>
  <div class="h-full flex flex-col overflow-hidden px-6 py-4">
    <div v-if="selectedChapter" class="max-w-[920px] w-full mx-auto flex flex-col h-full space-y-3">
      <div class="flex items-center justify-between gap-3 flex-shrink-0">
        <div class="flex-1 flex items-center gap-2">
          <span class="text-lg font-bold text-[var(--text-primary)] shrink-0">
            {{ selectedChapter.chapter_name || `第${selectedChapter.chapter_number}章` }}
          </span>
          <input
            :value="selectedChapter.title"
            @input="handleTitleInput"
            class="flex-1 text-lg font-semibold text-[var(--text-primary)] bg-transparent hover:bg-black/5 focus:bg-white focus:ring-1 focus:ring-[var(--accent-500)] focus:outline-none px-2 py-1 rounded-lg transition-all placeholder:text-[var(--text-muted)] placeholder:font-normal"
            placeholder="输入章节标题..."
          />
        </div>
        <button
          @click="publishChapter"
          :disabled="isPublishing || isGenerating"
          class="px-3 py-1.5 rounded-lg text-xs font-medium transition-colors flex items-center gap-1.5 shadow-sm"
          :class="selectedChapter.status === 'published' 
            ? 'bg-emerald-50 text-emerald-600 ring-1 ring-emerald-200 hover:bg-emerald-100' 
            : 'bg-white text-slate-600 ring-1 ring-slate-200 hover:bg-slate-50'"
        >
          <svg v-if="isPublishing" class="animate-spin h-3.5 w-3.5" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
          </svg>
          <svg v-else class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path v-if="selectedChapter.status === 'published'" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" />
            <path v-else stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8.684 13.342C8.886 12.938 9 12.482 9 12c0-.482-.114-.938-.316-1.342m0 2.684a3 3 0 110-2.684m0 2.684l6.632 3.316m-6.632-6l6.632-3.316m0 0a3 3 0 105.367-2.684 3 3 0 00-5.367 2.684zm0 9.316a3 3 0 105.368 2.684 3 3 0 00-5.368-2.684z" />
          </svg>
          {{ selectedChapter.status === 'published' ? '已发布' : '发布' }}
        </button>
      </div>

      <div class="rounded-xl bg-[var(--bg-panel)] px-3 py-2.5 space-y-2 flex-shrink-0">
        <div class="flex items-start gap-2">
          <textarea
            :value="selectedChapter.outline_text"
            @input="handleOutlineInput"
            rows="2"
            class="flex-1 px-2 py-1.5 rounded-lg bg-white text-[var(--text-primary)] text-xs focus:outline-none ring-1 ring-transparent focus:ring-[var(--accent-500)] resize-none"
            placeholder="输入章节摘要..."
          />
        </div>

        <div class="flex flex-wrap items-center gap-2">
          <span class="text-[10px] text-[var(--text-muted)]">人物:</span>
          <button
            v-for="char in characters"
            :key="char.id"
            @click="toggleCharacter(char.id)"
            class="px-2 py-0.5 text-[10px] rounded-full transition-all ring-1"
            :class="isCharacterSelected(char.id)
              ? 'bg-indigo-100 text-indigo-700 ring-indigo-300'
              : 'bg-white text-slate-700 ring-slate-300 hover:bg-slate-50'"
          >
            {{ char.name }}
          </button>
          <span v-if="characters.length === 0" class="text-[10px] text-[var(--text-muted)]">暂无</span>
        </div>

        <div class="flex items-center justify-between gap-2">
          <div class="flex-1"></div>
          <div class="flex items-center gap-2">
            <button
              @click="openInspirationModal"
              :disabled="isGenerating"
              title="点子启发"
              class="h-7 w-7 flex items-center justify-center rounded-lg bg-white text-[var(--text-secondary)] text-sm ring-1 ring-slate-200 hover:bg-slate-50 disabled:opacity-40 transition-colors"
            >
              <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
              </svg>
            </button>
            <button
              @click="emit('request-critique', selectedChapter.content_text || selectedChapter.draft_text || '')"
              :disabled="isGenerating"
              title="获取主编指导"
              class="h-7 px-2 flex items-center justify-center rounded-lg bg-white text-[var(--text-secondary)] text-sm ring-1 ring-slate-200 hover:bg-slate-50 disabled:opacity-40 transition-colors gap-1"
            >
              <span>📝</span>
              <span class="hidden xl:inline text-xs">主编指导</span>
            </button>
            <button
              @click="openAgenticSettingsModal"
              :disabled="isGenerating || !isAgenticMode"
              title="智能生成设置"
              class="h-7 w-7 flex items-center justify-center rounded-lg bg-white text-[var(--text-secondary)] text-sm ring-1 ring-slate-200 disabled:opacity-40"
            >
              ⚙️
            </button>
            <button
              @click="startGenerate"
              :disabled="isGenerating || beatPreviewLoading || !selectedChapter.outline_text.trim() || (isAgenticMode && !canSubmitAgentic)"
              class="px-4 py-1.5 rounded-lg bg-[var(--accent-500)] text-white text-xs font-semibold shadow-sm shadow-indigo-400/40 disabled:opacity-40 transition-colors"
            >
              {{ beatPreviewLoading ? '规划中...' : (isGenerating ? '生成中...' : '✨ 智能生成本章') }}
            </button>
          </div>
        </div>
      </div>

      <div class="relative rounded-2xl bg-white shadow-[0_8px_20px_rgba(18,38,63,0.06)] flex-1 min-h-0 flex flex-col overflow-hidden">
        <div
          v-if="isGenerating && isAgenticMode"
          class="absolute inset-0 z-10 flex items-center justify-center bg-white/78 backdrop-blur-[1px] rounded-2xl transition-all duration-300"
        >
          <div class="flex items-center gap-2 rounded-full bg-white px-4 py-2 ring-1 ring-indigo-100 shadow-sm">
            <div class="w-4 h-4 rounded-full border-2 border-indigo-500 border-t-transparent animate-spin"></div>
            <div class="text-xs font-medium text-indigo-700">
              {{ getWorkflowStageLabel() }}...
            </div>
          </div>
        </div>

        <div
          v-if="beatPreviewLoading"
          class="absolute inset-0 z-10 flex flex-col items-center justify-center bg-white/80 backdrop-blur-[2px] rounded-2xl transition-all duration-300"
        >
          <div class="relative flex items-center justify-center w-24 h-24 mb-8">
            <div class="absolute inset-0 rounded-full border-[6px] border-indigo-50"></div>
            <div class="absolute inset-0 rounded-full border-[6px] border-indigo-500 border-t-transparent animate-spin"></div>
          </div>

          <div class="flex flex-col items-center gap-3">
            <h3 class="text-3xl font-bold text-indigo-900 tracking-tight">
              正在规划节拍...
            </h3>
            <p class="text-lg text-indigo-600/90 font-medium max-w-xl text-center px-6 leading-relaxed">
              正在根据大纲和前文分析剧情走向...
            </p>
          </div>
        </div>

        <div
          v-if="isPublishing"
          class="absolute inset-0 z-10 flex flex-col items-center justify-center bg-white/80 backdrop-blur-[2px] rounded-2xl transition-all duration-300"
        >
          <div class="relative flex items-center justify-center w-24 h-24 mb-8">
            <div class="absolute inset-0 rounded-full border-[6px] border-indigo-50"></div>
            <div class="absolute inset-0 rounded-full border-[6px] border-indigo-500 border-t-transparent animate-spin"></div>
          </div>

          <div class="flex flex-col items-center gap-3">
            <h3 class="text-3xl font-bold text-indigo-900 tracking-tight">
              发布中...
            </h3>
            <p class="text-lg text-indigo-600/90 font-medium max-w-xl text-center px-6 leading-relaxed">
              正在更新章节状态及角色动态...
            </p>
          </div>
        </div>

        <RichTextEditor
          ref="editorRef"
          :id="selectedChapter.id"
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

  <div
    v-if="showAgenticSettingsModal && isAgenticMode"
    class="fixed inset-0 z-50 flex items-center justify-center bg-black/45 p-3"
    @click.self="closeAgenticSettingsModal"
  >
    <div class="bg-[var(--bg-primary)] rounded-2xl shadow-2xl w-full max-w-5xl max-h-[85vh] overflow-hidden">
      <div class="p-3 border-b border-white/60 flex items-center justify-between">
        <h3 class="text-sm font-semibold text-[var(--text-primary)]">智能生成设置</h3>
        <button @click="closeAgenticSettingsModal" class="p-1 text-[var(--text-muted)] hover:text-[var(--text-primary)]">
          <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
          </svg>
        </button>
      </div>
      <div class="p-3 overflow-y-auto max-h-[calc(85vh-56px)] space-y-2.5">
        <div class="flex items-center justify-between">
          <p class="text-[10px] text-[var(--text-muted)]">可按需调节以下参数，生成时会自动写入请求。</p>
          <button
            @click="restoreAgenticDefaults"
            :disabled="isGenerating"
            class="px-2 py-0.5 rounded-md text-[10px] bg-white text-[var(--text-secondary)] ring-1 ring-slate-200 disabled:opacity-40"
          >
            恢复推荐值
          </button>
        </div>
        <div class="grid grid-cols-1 md:grid-cols-3 gap-2">
          <section
            v-for="(fieldKeys, groupKey) in agenticGroupFields"
            :key="groupKey"
            class="rounded-lg bg-white p-2 ring-1 ring-slate-200/90 space-y-2"
          >
            <header>
              <h4 class="text-[11px] font-semibold text-[var(--text-primary)]">{{ AGENTIC_GROUPS[groupKey].title }}</h4>
              <p class="text-[10px] text-[var(--text-muted)] mt-0.5">{{ AGENTIC_GROUPS[groupKey].description }}</p>
            </header>
            <div class="space-y-1.5">
              <div
                v-for="field in fieldKeys"
                :key="field"
                class="rounded-md border border-slate-200/90 px-2 py-1.5"
                :class="getAgenticFieldFeedbackText(field) ? 'border-rose-300 bg-rose-50/40' : 'bg-white'"
              >
                <div class="flex items-center justify-between gap-2">
                  <label class="text-[10px] font-medium text-[var(--text-primary)]">{{ AGENTIC_FIELD_CONFIG[field].label }}</label>
                  <button
                    @click="restoreAgenticField(field)"
                    :disabled="isGenerating"
                    class="text-[10px] text-[var(--text-muted)] hover:text-[var(--text-primary)] disabled:opacity-40"
                  >
                    还原
                  </button>
                </div>
                <p class="text-[10px] text-[var(--text-muted)] mt-0.5">{{ AGENTIC_FIELD_CONFIG[field].description }}</p>
                <div class="flex items-center gap-2 mt-1">
                  <textarea
                    v-if="getAgenticFieldInputType(field) === 'textarea'"
                    :value="getAgenticFieldValue(field)"
                    @input="setAgenticFieldValue(field, $event)"
                    @blur="normalizeAgenticField"
                    :disabled="isGenerating"
                    class="w-full px-1.5 py-1 rounded bg-white ring-1 ring-slate-200 text-[11px] disabled:opacity-60 resize-none"
                    rows="3"
                  ></textarea>
                  <select
                    v-else-if="isAgenticFieldSelect(field)"
                    :value="getAgenticFieldValue(field)"
                    @change="setAgenticFieldValue(field, $event)"
                    @blur="normalizeAgenticField"
                    :disabled="isGenerating"
                    class="w-full px-1.5 py-1 rounded bg-white ring-1 ring-slate-200 text-[11px] disabled:opacity-60"
                  >
                    <option
                      v-for="option in getAgenticFieldOptions(field)"
                      :key="`${field}-${option.value}`"
                      :value="option.value"
                    >
                      {{ option.label }}
                    </option>
                  </select>
                  <input
                    v-else
                    :value="getAgenticFieldValue(field)"
                    @input="setAgenticFieldValue(field, $event)"
                    @blur="normalizeAgenticField"
                    :type="getAgenticFieldInputType(field)"
                    :step="getAgenticFieldStep(field)"
                    :min="getAgenticFieldMin(field)"
                    :max="getAgenticFieldMax(field)"
                    :disabled="isGenerating"
                    class="w-full px-1.5 py-1 rounded bg-white ring-1 ring-slate-200 text-[11px] disabled:opacity-60"
                  />
                </div>
                <div class="flex items-center justify-between mt-1">
                  <span class="text-[10px] text-[var(--text-muted)]">{{ AGENTIC_FIELD_CONFIG[field].rangeHint }}</span>
                  <span class="text-[10px] text-[var(--text-muted)]">{{ AGENTIC_FIELD_CONFIG[field].recommended }}</span>
                </div>
                <p v-if="getAgenticFieldFeedbackText(field)" class="text-[10px] text-rose-500 mt-1">
                  {{ getAgenticFieldFeedbackText(field) }}
                </p>
              </div>
            </div>
          </section>
        </div>
        <div class="flex items-center justify-between text-[10px]">
          <span class="text-[var(--text-muted)]">三项回顾偏好合计</span>
          <span :class="Math.abs(ragWeightTotal - 1) <= 0.001 ? 'text-emerald-600 font-medium' : 'text-rose-500 font-medium'">{{ ragWeightTotal }}</span>
        </div>
        <p v-if="formError || firstFieldFeedback || agenticValidation.errors.length > 0" class="text-[10px] text-rose-500">
          {{ formError || firstFieldFeedback || agenticValidation.errors[0] }}
        </p>
      </div>
    </div>
  </div>

  <div
    v-if="showBeatReviewModal && isAgenticMode"
    class="fixed inset-0 z-50 flex items-center justify-center bg-black/45 p-3"
  >
    <div class="bg-[var(--bg-primary)] rounded-2xl shadow-2xl w-full max-w-4xl max-h-[85vh] overflow-hidden">
      <div class="p-3 border-b border-white/60 flex items-center justify-between">
        <h3 class="text-sm font-semibold text-[var(--text-primary)]">剧情节拍预览</h3>
        <button @click="closeBeatReviewModal" class="p-1 text-[var(--text-muted)] hover:text-[var(--text-primary)]">
          <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
          </svg>
        </button>
      </div>
      <div class="p-4 overflow-y-auto max-h-[calc(85vh-124px)] space-y-3">
        <div v-if="anchorPov" class="mb-3 px-3 py-2 bg-amber-50 border border-amber-200 rounded-lg">
          <div class="text-xs font-semibold text-amber-700">🎯 本章锚点视点 (Anchor POV)</div>
          <div class="text-sm font-bold text-amber-800">{{ anchorPov }}</div>
          <div class="text-[10px] text-amber-600 mt-1">所有 Beats 将统一使用此视点进行叙事</div>
        </div>
        <div v-if="beatPreviewError" class="text-xs text-rose-500">
          {{ beatPreviewError }}
        </div>
        <div v-for="beat in previewBeats" :key="`${beat.position}-${beat.beat_id || beat.summary}`" class="bg-white rounded-xl border border-slate-200 p-3 space-y-2">
          <div class="flex items-center justify-between gap-2">
            <div class="text-xs font-semibold text-[var(--text-primary)]">节拍 {{ beat.position }}</div>
            <div class="text-[10px] text-[var(--text-muted)]">建议字数 {{ beat.word_count_target || beat.target_words || 0 }}</div>
          </div>
          <textarea
            v-model="beat.summary"
            class="w-full px-2 py-1.5 rounded-lg bg-slate-50 border border-slate-200 text-xs text-[var(--text-primary)] focus:outline-none focus:ring-1 focus:ring-[var(--accent-500)] focus:border-[var(--accent-500)] resize-y"
            rows="3"
            placeholder="输入节拍内容..."
          ></textarea>
          <div class="grid grid-cols-1 md:grid-cols-2 gap-2 text-[10px] text-[var(--text-secondary)]">
            <div>场景：{{ beat.location || '未指定' }}</div>
            <div>视角：{{ beat.pov_character || '未指定' }}</div>
            <div>动作摘要：{{ beat.action_summary || '未指定' }}</div>
            <div>绑定伏笔：{{ getBeatHookLabel(beat) }}</div>
          </div>
          <div class="grid grid-cols-1 md:grid-cols-2 gap-2">
            <div>
              <label class="block text-[10px] text-[var(--text-muted)] mb-1">本段开场状态</label>
              <input
                v-model="beat.openingState"
                class="w-full px-2 py-1.5 rounded-lg bg-slate-50 border border-slate-200 text-xs text-[var(--text-primary)] focus:outline-none focus:ring-1 focus:ring-[var(--accent-500)] focus:border-[var(--accent-500)]"
                placeholder="例如：双方试探，尚未摊牌"
              />
            </div>
            <div>
              <label class="block text-[10px] text-[var(--text-muted)] mb-1">本段停在何处</label>
              <input
                v-model="beat.stoppingState"
                class="w-full px-2 py-1.5 rounded-lg bg-slate-50 border border-slate-200 text-xs text-[var(--text-primary)] focus:outline-none focus:ring-1 focus:ring-[var(--accent-500)] focus:border-[var(--accent-500)]"
                placeholder="例如：关系仍紧绷但未爆发"
              />
            </div>
          </div>
          <div>
            <label class="block text-[10px] text-[var(--text-muted)] mb-1">本段禁止发生</label>
            <textarea
              v-model="beat.forbiddenEventsText"
              class="w-full px-2 py-1.5 rounded-lg bg-slate-50 border border-slate-200 text-xs text-[var(--text-primary)] focus:outline-none focus:ring-1 focus:ring-[var(--accent-500)] focus:border-[var(--accent-500)] resize-y"
              rows="2"
              placeholder="每行一条，例如：主角主动出手"
            ></textarea>
          </div>
        </div>
      </div>
      <div class="p-3 border-t border-white/60 flex items-center justify-end gap-2">
        <button @click="closeBeatReviewModal" class="px-3 py-1.5 rounded-lg bg-white text-[var(--text-secondary)] text-xs ring-1 ring-slate-200">
          取消
        </button>
        <button
          @click="confirmBeatsAndGenerate"
          :disabled="previewBeats.length === 0 || isGenerating"
          class="px-3 py-1.5 rounded-lg bg-[var(--accent-500)] text-white text-xs font-medium disabled:opacity-40"
        >
          确认并生成正文
        </button>
      </div>
    </div>
  </div>

  <div v-if="showPublishModal" class="fixed inset-0 z-50 flex items-center justify-center bg-black/50" @click.self="closePublishModal">
    <div class="bg-[var(--bg-primary)] rounded-2xl shadow-2xl w-full max-w-2xl max-h-[80vh] overflow-hidden">
      <div class="p-4 border-b border-white/60 flex items-center justify-between">
        <h3 class="text-lg font-semibold text-[var(--text-primary)]">发布成功</h3>
        <button @click="closePublishModal" class="p-1 text-[var(--text-muted)] hover:text-[var(--text-primary)]">
          <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
          </svg>
        </button>
      </div>
      <div class="p-4 overflow-y-auto max-h-[70vh] space-y-6">
        <div v-if="chapterSummary" class="bg-[var(--bg-panel)] rounded-xl p-4 border border-[var(--border-color)]">
          <h4 class="text-sm font-semibold text-[var(--text-primary)] mb-2 flex items-center gap-2">
            <svg class="w-4 h-4 text-indigo-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
            </svg>
            本章摘要 (自动生成)
          </h4>
          <p class="text-sm text-[var(--text-secondary)] leading-relaxed">{{ chapterSummary }}</p>
        </div>

        <div v-if="characterUpdates.length > 0">
          <h4 class="text-sm font-semibold text-[var(--text-primary)] mb-3 flex items-center gap-2">
            <svg class="w-4 h-4 text-emerald-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0zm6 3a2 2 0 11-4 0 2 2 0 014 0zM7 10a2 2 0 11-4 0 2 2 0 014 0z" />
            </svg>
            角色状态更新
          </h4>
          <div class="grid gap-3">
            <div v-for="update in characterUpdates" :key="update.character_id" class="p-3 bg-[var(--bg-panel)] rounded-xl border border-[var(--border-color)]">
              <div class="flex items-center justify-between mb-2">
                <span class="font-medium text-indigo-400 text-sm">{{ update.character_name }}</span>
              </div>
              <div class="grid grid-cols-2 gap-4 text-xs">
                <div class="opacity-70">
                  <div class="mb-1 text-[var(--text-muted)]">旧状态</div>
                  <div class="text-[var(--text-secondary)] whitespace-pre-wrap">{{ update.old_state || '暂无' }}</div>
                </div>
                <div>
                  <div class="mb-1 text-[var(--text-muted)]">新状态</div>
                  <div class="text-[var(--text-primary)] whitespace-pre-wrap">{{ update.new_state || '暂无' }}</div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <div v-if="!chapterSummary && characterUpdates.length === 0" class="text-center text-[var(--text-muted)] py-4">
          发布成功，暂无状态变更。
        </div>
      </div>
      <div class="p-4 border-t border-white/60 flex justify-end">
        <button @click="closePublishModal" class="px-4 py-2 bg-[var(--accent-500)] text-white text-sm font-medium rounded-lg hover:bg-[var(--accent-600)] transition-colors">
          完成
        </button>
      </div>
    </div>
  </div>

  <!-- Completion Modal -->
  <div v-if="showCompletionModal" class="fixed inset-0 z-[60] flex items-center justify-center bg-black/50 backdrop-blur-sm">
      <div class="bg-white dark:bg-slate-800 rounded-xl shadow-2xl w-full max-w-md border border-[var(--border-color)] p-6 transform transition-all animate-in fade-in zoom-in-95 duration-200">
        <div class="flex items-start gap-4">
          <div class="flex-shrink-0 w-10 h-10 rounded-full bg-green-100 flex items-center justify-center">
            <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="text-green-600"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><polyline points="22 4 12 14.01 9 11.01"></polyline></svg>
          </div>
          <div class="flex-1">
            <h3 class="text-lg font-semibold text-slate-900 dark:text-white mb-2">{{ completionTitle || '生成完成' }}</h3>
            <p class="text-slate-600 dark:text-slate-300 text-sm leading-relaxed whitespace-pre-line">{{ completionMessage }}</p>
          </div>
        </div>
        <div class="mt-6 flex justify-end">
          <button
            @click="closeCompletionModal"
            class="px-4 py-2 bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg font-medium transition-colors focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-2"
          >
            确定
          </button>
        </div>
      </div>
  </div>

</template>
