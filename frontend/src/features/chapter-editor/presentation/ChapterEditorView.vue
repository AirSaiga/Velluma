<script setup lang="ts">
import { ref, watch } from 'vue'
import RichTextEditor from '../../../components/RichTextEditor.vue'
import type { AgenticFormState, Chapter, Character, ConfirmedStoryBeat } from '../../../types'

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
  closePublishModal: () => void
  confirmBeatsAndGenerate: () => void
  firstFieldFeedback: string
  formError: string
  getAgenticFieldFeedbackText: (field: keyof AgenticFormState) => string
  getAgenticFieldInputType: (field: keyof AgenticFormState) => string
  getAgenticFieldMax: (field: keyof AgenticFormState) => number | undefined
  getAgenticFieldMin: (field: keyof AgenticFormState) => number
  getAgenticFieldStep: (field: keyof AgenticFormState) => number
  getAgenticFieldValue: (field: keyof AgenticFormState) => number
  getBeatHookLabel: (beat: ConfirmedStoryBeat) => string
  getMetaCollapsedLabel: () => string
  getWorkflowStageLabel: () => string
  handleContentUpdate: (content: string) => void
  handleOptimize: () => void
  handleOutlineInput: (event: Event) => void
  handleTitleInput: (event: Event) => void
  isAgenticMode: boolean
  isCharacterSelected: (charId: string) => boolean
  isEditorDisabled: boolean
  isGenerating: boolean
  isLoadingOverlay: boolean
  isPublishing: boolean
  isStreamMode: boolean
  localMetaCollapsed: boolean
  normalizeAgenticField: () => void
  openAgenticSettingsModal: () => void
  optimizationFeedback: string
  previewBeats: ConfirmedStoryBeat[]
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
  showPublishModal: boolean
  startGenerate: () => void
  toggleAgenticMode: () => void
  toggleCharacter: (charId: string) => void
  toggleMetaCollapsed: () => void
  toggleStreamMode: () => void
  wordCountMax: number
  wordCountMin: number
  workflowState: any
}>()

const editorRef = ref<any>(null)
watch(editorRef, (editor) => {
  props.setEditorRef(editor)
})

function handleWordCountInput(event: Event) {
  const target = event.target as HTMLInputElement
  props.setWordCount(Number(target.value))
}

function handleOptimizationFeedbackInput(event: Event) {
  const target = event.target as HTMLInputElement
  props.setOptimizationFeedback(target.value)
}
</script>

<template>
  <div class="h-full overflow-y-auto px-6 py-4">
    <div v-if="selectedChapter" class="max-w-[920px] mx-auto space-y-3">
      <div class="flex items-center justify-between gap-3">
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
          class="px-2 py-1 text-xs rounded-lg bg-white/90 text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-colors shadow-sm ring-1 ring-slate-900/5"
          @click="toggleMetaCollapsed"
        >
          {{ getMetaCollapsedLabel() }}
        </button>
      </div>

      <div v-show="!localMetaCollapsed" class="rounded-xl bg-[var(--bg-panel)] px-3 py-2.5 space-y-2">
        <div>
          <textarea
            :value="selectedChapter.outline_text"
            @input="handleOutlineInput"
            rows="2"
            class="w-full px-2 py-1.5 rounded-lg bg-white text-[var(--text-primary)] text-xs focus:outline-none ring-1 ring-transparent focus:ring-[var(--accent-500)] resize-none"
            placeholder="本章要发生的情节..."
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
          <div class="flex items-center gap-2">
            <span class="text-[10px] text-[var(--text-muted)]">字数:</span>
            <input
              type="range"
              :value="agenticForm.word_count"
              @input="handleWordCountInput"
              @change="normalizeAgenticField"
              :min="wordCountMin"
              :max="wordCountMax"
              step="100"
              class="w-24 h-1.5 rounded-full appearance-none cursor-pointer accent-[var(--accent-500)]"
            />
            <span class="text-[10px] font-medium text-[var(--accent-600)]">{{ agenticForm.word_count }}</span>
          </div>
          <div class="flex items-center gap-1">
            <button
              @click="toggleAgenticMode"
              :disabled="isGenerating"
              class="px-2 py-0.5 text-[10px] rounded-lg transition-colors"
              :class="isAgenticMode
                ? 'bg-[var(--accent-500)]/15 text-[var(--accent-600)]'
                : 'bg-white text-[var(--text-secondary)]'"
            >
              {{ isAgenticMode ? '智能生成' : '传统模式' }}
            </button>
            <button
              v-if="isAgenticMode"
              @click="openAgenticSettingsModal"
              :disabled="isGenerating"
              class="px-2 py-0.5 text-[10px] rounded-lg bg-white text-[var(--text-secondary)] disabled:opacity-40"
            >
              生成设置
            </button>
            <button
              v-if="isAgenticMode"
              @click="toggleStreamMode"
              :disabled="isGenerating"
              class="px-2 py-0.5 text-[10px] rounded-lg bg-white text-[var(--text-secondary)]"
            >
              {{ isStreamMode ? '流' : '一次' }}
            </button>
            <button
              @click="startGenerate"
              :disabled="isGenerating || beatPreviewLoading || !selectedChapter.outline_text.trim() || (isAgenticMode && !canSubmitAgentic)"
              class="px-3 py-1 rounded-lg bg-[var(--accent-500)] text-white text-xs font-medium disabled:opacity-40 transition-colors"
            >
              {{ beatPreviewLoading ? '规划中' : (isGenerating ? '生成中' : '生成') }}
            </button>
            <button
              @click="publishChapter"
              :disabled="isPublishing"
              class="px-3 py-1 rounded-lg bg-white text-[var(--text-secondary)] hover:text-[var(--text-primary)] text-xs disabled:opacity-40 transition-colors"
            >
              {{ isPublishing ? '发布中' : (selectedChapter.status === 'published' ? '已发布' : '发布') }}
            </button>
          </div>
        </div>

        <div v-if="selectedChapter.content_text || selectedChapter.draft_text" class="pt-2 border-t border-slate-100 mt-2">
          <div class="flex items-center gap-2">
            <input
              :value="optimizationFeedback"
              class="flex-1 px-2 py-1.5 rounded-lg bg-white text-[var(--text-primary)] text-xs focus:outline-none ring-1 ring-transparent focus:ring-[var(--accent-500)] placeholder:text-[var(--text-muted)]"
              placeholder="输入优化建议..."
              @input="handleOptimizationFeedbackInput"
              @keyup.enter="handleOptimize"
            />
            <button
              @click="handleOptimize"
              :disabled="isGenerating || !optimizationFeedback.trim()"
              class="px-3 py-1.5 rounded-lg bg-indigo-50 text-indigo-600 hover:bg-indigo-100 text-xs font-medium disabled:opacity-40 transition-colors flex items-center justify-center gap-1 shrink-0"
            >
              <span v-if="isGenerating && workflowState.currentEvent === 'REFINING'" class="w-3 h-3 border-2 border-current border-t-transparent rounded-full animate-spin"></span>
              {{ isGenerating && workflowState.currentEvent === 'REFINING' ? '优化中...' : '优化' }}
            </button>
          </div>
        </div>
      </div>

      <div class="relative rounded-2xl bg-white shadow-[0_8px_20px_rgba(18,38,63,0.06)] min-h-[60vh] flex flex-col">
        <div
          v-if="isGenerating && isAgenticMode"
          class="absolute inset-0 z-10 flex flex-col items-center justify-center bg-white/80 backdrop-blur-[2px] rounded-2xl transition-all duration-300"
        >
          <div class="relative flex items-center justify-center w-24 h-24 mb-8">
            <div class="absolute inset-0 rounded-full border-[6px] border-indigo-50"></div>
            <div class="absolute inset-0 rounded-full border-[6px] border-indigo-500 border-t-transparent animate-spin"></div>
            <div v-if="workflowState.iteration > 0" class="absolute inset-0 flex items-center justify-center text-3xl font-bold text-indigo-600">
              #{{ workflowState.iteration }}
            </div>
          </div>

          <div class="flex flex-col items-center gap-3">
            <h3 class="text-3xl font-bold text-indigo-900 tracking-tight">
              {{ getWorkflowStageLabel() }}...
            </h3>
            <p v-if="workflowState.message" class="text-lg text-indigo-600/90 font-medium max-w-xl text-center px-6 leading-relaxed">
              {{ workflowState.message }}
            </p>
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
          v-show="!isLoadingOverlay"
          :ref="editorRef"
          :id="selectedChapter.id"
          :model-value="selectedChapter.content_text || selectedChapter.draft_text || ''"
          @update:model-value="handleContentUpdate"
          :disabled="isEditorDisabled"
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
                  <input
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
    @click.self="closeBeatReviewModal"
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
                  <div class="text-[var(--text-secondary)] line-clamp-2">{{ update.old_state || '暂无' }}</div>
                </div>
                <div>
                  <div class="mb-1 text-[var(--text-muted)]">新状态</div>
                  <div class="text-[var(--text-primary)] line-clamp-2">{{ update.new_state || '暂无' }}</div>
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
</template>
