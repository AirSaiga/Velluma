<script setup lang="ts">
import { ref, watch, computed } from 'vue'
import RichTextEditor from '../../../components/RichTextEditor.vue'
import WorkflowProgressGraph from '../../../components/WorkflowProgressGraph.vue'
import { IntentDrivenPanel } from '../../intent-driven'
import type { AgenticFormState, ApiConfig, Chapter, Character, PacingStyle } from '../../../types'
import type { AgenticFieldOption, EditorMode } from '../../../composables/useAgenticConfig'

interface BeatPreviewItem {
  position: number
  beat_id?: string
  summary: string
  location?: string
  pov_character?: string
  pov_mode: 'single' | 'ensemble' | 'omniscient'
  pov_characters: string[]
  pov_aperture?: string
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
  editorMode: EditorMode
  editorModeConfig: { title: string; description: string; icon: string }
  visibleAgenticFields: string[]
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
  getAgenticFieldValue: (field: keyof AgenticFormState) => string | number | boolean
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
  handleAssetsSchemaInput: (event: Event) => void
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
  publishChapter: () => void
  ragWeightTotal: number
  restoreAgenticDefaults: () => void
  restoreAgenticField: (field: keyof AgenticFormState) => void
  selectedChapter: Chapter | null
  setAgenticFieldValue: (field: keyof AgenticFormState, event: Event) => void
  setEditorRef: (editor: any) => void
  scrollToCritique: (comment: any) => void
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

function handlePovModeChange(beat: BeatPreviewItem) {
  if (beat.pov_mode === 'ensemble') {
    if (!beat.pov_characters || beat.pov_characters.length === 0) {
      beat.pov_characters = beat.pov_character ? [beat.pov_character] : []
    }
  } else {
    if (beat.pov_characters && beat.pov_characters.length > 0) {
      beat.pov_character = beat.pov_characters[0]
    }
  }
}

const emit = defineEmits<{
  (e: 'request-critique', content: string): void
  (e: 'intent-generate', payload: any): void
  (e: 'intent-save', payload: any): void
}>()

const editorRef = ref<any>(null)
const showAdvancedSettings = ref(false)
const showCharacterSelector = ref(false)
const characterSearchQuery = ref('')

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

const selectedCharacters = computed(() => {
  return props.characters.filter(c => props.isCharacterSelected(c.id))
})

const hasAdvancedContent = computed(() => {
  return (props.selectedChapter?.chapter_assets_schema || '').trim().length > 0
})

const filteredCharacters = computed(() => {
  if (!characterSearchQuery.value) return props.characters
  const query = characterSearchQuery.value.toLowerCase()
  return props.characters.filter(c => c.name.toLowerCase().includes(query))
})

const characterImportanceColor = (level: number) => {
  const colors: Record<number, string> = {
    1: 'bg-gray-100 text-gray-600 ring-gray-200',
    2: 'bg-blue-50 text-blue-600 ring-blue-200',
    3: 'bg-violet-50 text-violet-600 ring-violet-200',
    4: 'bg-amber-50 text-amber-600 ring-amber-200'
  }
  return colors[level] || colors[1]
}
</script>

<template>
  <div class="h-full flex flex-col overflow-hidden px-8 py-5">
    <div v-if="selectedChapter" class="max-w-[920px] w-full mx-auto flex flex-col h-full space-y-4">
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
          <svg v-else class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path v-if="selectedChapter.status === 'published'" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" />
            <path v-else stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8.684 13.342C8.886 12.938 9 12.482 9 12c0-.482-.114-.938-.316-1.342m0 2.684a3 3 0 110-2.684m0 2.684l6.632 3.316m-6.632-6l6.632-3.316m0 0a3 3 0 105.367-2.684 3 3 0 00-5.367 2.684zm0 9.316a3 3 0 105.368 2.684 3 3 0 00-5.368-2.684z" />
          </svg>
          {{ selectedChapter.status === 'published' ? '已发布' : '发布' }}
        </button>
      </div>

      <!-- 核心设置区 - 三层结构 -->
      <div class="rounded-xl bg-[var(--bg-panel)] flex-shrink-0 overflow-hidden">
        <!-- 第一层：核心输入 + 主要操作 -->
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
              :disabled="isGenerating || beatPreviewLoading || !selectedChapter.outline_text.trim() || (isAgenticMode && !canSubmitAgentic)"
              class="h-9 px-4 rounded-lg bg-[var(--accent-500)] text-white text-xs font-semibold shadow-sm shadow-accent-400/30 disabled:opacity-40 transition-all hover:bg-accent-600 hover:shadow-md flex items-center gap-1.5"
            >
              <svg v-if="beatPreviewLoading || isGenerating" class="animate-spin h-3.5 w-3.5" fill="none" viewBox="0 0 24 24">
                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
              </svg>
              <svg v-else class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z" />
              </svg>
              {{ beatPreviewLoading ? '规划中' : (isGenerating ? '生成中' : '智能生成') }}
            </button>
            
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

        <!-- 第二层：人物选择（新版展开式） -->
        <div class="px-3 pb-2.5 border-t border-[var(--border-color)]/50">
          <div class="mt-2">
            <!-- 已选人物展示 + 添加按钮 -->
            <div class="flex items-start gap-2">
              <div class="flex-1 min-w-0">
                <div v-if="selectedCharacters.length === 0" class="flex items-center gap-2">
                  <span class="text-[11px] text-[var(--text-muted)] italic">尚未选择本章人物</span>
                  <button
                    @click="showCharacterSelector = !showCharacterSelector"
                    class="text-[11px] text-[var(--accent-500)] hover:text-accent-600 font-medium flex items-center gap-0.5"
                  >
                    <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"/>
                    </svg>
                    添加人物
                  </button>
                </div>
                <div v-else class="flex flex-wrap items-center gap-1.5">
                  <span 
                    v-for="char in selectedCharacters" 
                    :key="char.id"
                    class="inline-flex items-center gap-1 px-2 py-1 text-[11px] rounded-full ring-1 transition-all"
                    :class="characterImportanceColor(char.importance_level)"
                  >
                    {{ char.name }}
                    <button
                      @click="toggleCharacter(char.id)"
                      class="hover:text-rose-500 hover:bg-rose-50 rounded-full p-0.5"
                    >
                      <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
                      </svg>
                    </button>
                  </span>
                  <button
                    @click="showCharacterSelector = !showCharacterSelector"
                    class="inline-flex items-center gap-0.5 px-2 py-1 text-[11px] rounded-full text-[var(--text-muted)] hover:text-[var(--accent-500)] hover:bg-accent-50 ring-1 ring-dashed ring-[var(--border-color)] hover:ring-accent-200 transition-all"
                  >
                    <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"/>
                    </svg>
                    添加
                  </button>
                </div>
              </div>
            </div>

            <!-- 人物选择展开面板 -->
            <div 
              v-if="showCharacterSelector" 
              class="mt-2 p-3 bg-[var(--bg-canvas)] rounded-lg border border-[var(--border-color)]"
            >
              <!-- 搜索框 -->
              <div class="relative mb-2">
                <svg class="w-4 h-4 absolute left-2.5 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"/>
                </svg>
                <input
                  v-model="characterSearchQuery"
                  type="text"
                  placeholder="搜索人物..."
                  class="w-full pl-9 pr-3 py-1.5 text-xs rounded-md bg-[var(--bg-primary)] border border-[var(--border-color)] focus:outline-none focus:border-[var(--accent-500)]"
                />
              </div>

              <!-- 人物网格 -->
              <div class="max-h-40 overflow-y-auto">
                <div v-if="filteredCharacters.length === 0" class="text-center py-3 text-[11px] text-[var(--text-muted)]">
                  未找到匹配的人物
                </div>
                <div v-else class="grid grid-cols-3 sm:grid-cols-4 gap-1.5">
                  <button
                    v-for="char in filteredCharacters"
                    :key="char.id"
                    @click="toggleCharacter(char.id)"
                    class="px-2 py-1.5 text-[11px] rounded-md text-left transition-all border"
                    :class="isCharacterSelected(char.id)
                      ? 'bg-accent-50 text-accent-700 border-accent-300 shadow-sm'
                      : 'bg-[var(--bg-primary)] text-[var(--text-secondary)] border-[var(--border-color)] hover:border-accent-200 hover:bg-accent-50/30'"
                  >
                    <div class="flex items-center gap-1">
                      <span v-if="isCharacterSelected(char.id)" class="text-accent-500">
                        <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/>
                        </svg>
                      </span>
                      <span class="truncate">{{ char.name }}</span>
                    </div>
                  </button>
                </div>
              </div>

              <!-- 底部操作 -->
              <div class="mt-2 pt-2 border-t border-[var(--border-color)]/50 flex items-center justify-between">
                <span class="text-[10px] text-[var(--text-muted)]">
                  已选 {{ selectedCharacters.length }} 人
                </span>
                <button
                  @click="showCharacterSelector = false"
                  class="text-[11px] text-[var(--accent-500)] hover:text-accent-600 font-medium"
                >
                  完成
                </button>
              </div>
            </div>
          </div>
        </div>

        <!-- 第三层：高级设置（折叠） -->
        <div 
          class="border-t border-[var(--border-color)]"
          :class="showAdvancedSettings ? 'bg-[var(--bg-canvas)]/50' : ''"
        >
          <button
            @click="showAdvancedSettings = !showAdvancedSettings"
            class="w-full px-3 py-2 flex items-center justify-between text-[11px] text-[var(--text-muted)] hover:text-[var(--text-secondary)] hover:bg-black/[0.02] transition-colors"
          >
            <span class="flex items-center gap-1.5">
              <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19.428 15.428a2 2 0 00-1.022-.547l-2.387-.477a6 6 0 00-3.86.517l-.318.158a6 6 0 01-3.86.517L6.05 15.21a2 2 0 00-1.806.547M8 4h8l-1 1v5.172a2 2 0 00.586 1.414l5 5c1.26 1.26.367 3.414-1.415 3.414H4.828c-1.782 0-2.674-2.154-1.414-3.414l5-5A2 2 0 009 10.172V5L8 4z"/>
              </svg>
              高级设置
              <span v-if="hasAdvancedContent" class="w-1.5 h-1.5 rounded-full bg-amber-400"></span>
            </span>
            <svg 
              class="w-4 h-4 transition-transform" 
              :class="showAdvancedSettings ? 'rotate-180' : ''"
              fill="none" 
              stroke="currentColor" 
              viewBox="0 0 24 24"
            >
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/>
            </svg>
          </button>
          
          <div v-if="showAdvancedSettings" class="px-3 pb-3 space-y-3">
            <div>
              <label class="text-[10px] font-medium text-[var(--text-secondary)] mb-1.5 block flex items-center gap-1">
                <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M20 7l-8-4-8 4m16 0l-8 4m8-4v10l-8 4m0-10L4 7m8 4v10M4 7v10l8 4"/>
                </svg>
                本章专属设定（Asset Schema）
              </label>
              <textarea
                :value="selectedChapter.chapter_assets_schema || ''"
                @input="handleAssetsSchemaInput"
                rows="3"
                class="w-full px-2.5 py-2 rounded-lg bg-[var(--bg-primary)] text-[var(--text-primary)] text-xs leading-relaxed focus:outline-none ring-1 ring-[var(--border-color)] focus:ring-[var(--accent-500)] resize-y"
                placeholder="定义本章特有的设定，如：&#10;【血噬】：2-3米高的重型实体机甲，采用外部驾驶舱包裹&#10;【虚空裂隙】：空间扭曲现象，会随机吞噬周围物体"
              />
              <p class="mt-1 text-[10px] text-[var(--text-muted)]">
                这些设定仅在当前章节有效，不会影响到其他章节的世界观
              </p>
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

  <!-- 智能生成设置模态框 - 沉浸式全屏 -->
  <Teleport to="body">
    <Transition name="modal-backdrop">
      <div
        v-if="showAgenticSettingsModal && isAgenticMode"
        class="fixed inset-0 z-50 flex items-center justify-center p-4 sm:p-6"
        @click.self="closeAgenticSettingsModal"
      >
        <!-- 背景遮罩 -->
        <div class="absolute inset-0 bg-slate-900/60 backdrop-blur-sm"></div>
        
        <!-- 模态框 -->
        <Transition name="modal-content">
          <div 
            v-if="showAgenticSettingsModal"
            class="relative w-full max-w-5xl max-h-[90vh] bg-[var(--bg-canvas)] rounded-2xl shadow-2xl overflow-hidden flex flex-col"
          >
            <!-- 关闭按钮 -->
            <button 
              @click="closeAgenticSettingsModal" 
              class="absolute top-4 right-4 z-10 w-8 h-8 flex items-center justify-center rounded-full bg-black/5 hover:bg-black/10 text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors"
            >
              <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
              </svg>
            </button>
            
            <!-- 内容 -->
            <div class="flex-1 overflow-auto">
              <IntentDrivenPanel
                :chapter-id="selectedChapter?.id || ''"
                :api-config="apiConfig"
                @save="(payload) => { closeAgenticSettingsModal(); emit('intent-save', payload); }"
                @generate="(payload) => { closeAgenticSettingsModal(); emit('intent-generate', payload); }"
              />
            </div>
          </div>
        </Transition>
      </div>
    </Transition>
  </Teleport>

  <!-- 剧情节拍预览模态框 -->
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
      <div class="p-4 overflow-y-auto max-h-[calc(85vh-56px)] space-y-3">
        <div v-if="previewBeats.length === 0" class="text-center text-[var(--text-muted)] text-sm py-8">
          暂无预览数据
        </div>
        <div
          v-for="beat in previewBeats"
          :key="beat.beat_id || beat.position"
          class="p-3 bg-[var(--bg-panel)] rounded-xl border border-[var(--border-color)]"
        >
          <div class="flex items-center justify-between mb-2">
            <span class="text-xs font-medium text-[var(--accent-500)]">Beat {{ beat.position }}</span>
            <span class="text-[10px] text-[var(--text-muted)]">{{ beat.word_count_target }}字</span>
          </div>
          <p class="text-sm text-[var(--text-primary)] mb-2">{{ beat.summary }}</p>
          <div class="flex flex-wrap items-center gap-2 text-[10px] text-[var(--text-muted)]">
            <span v-if="beat.location">📍 {{ beat.location }}</span>
            <span v-if="beat.pov_character">👤 {{ beat.pov_character }}</span>
          </div>
        </div>
        <div class="flex justify-end gap-2 pt-2">
          <button @click="closeBeatReviewModal" class="px-3 py-1.5 text-xs rounded-lg bg-[var(--bg-panel)] text-[var(--text-secondary)] hover:bg-parchment-100">
            取消
          </button>
          <button @click="confirmBeatsAndGenerate" class="px-3 py-1.5 text-xs rounded-lg bg-[var(--accent-500)] text-white hover:bg-accent-600">
            确认并生成
          </button>
        </div>
      </div>
    </div>
  </div>

  <!-- 完成模态框 -->
  <div
    v-if="showCompletionModal"
    class="fixed inset-0 z-50 flex items-center justify-center bg-black/45 p-3"
    @click.self="closeCompletionModal"
  >
    <div class="bg-[var(--bg-primary)] rounded-2xl shadow-2xl w-full max-w-md overflow-hidden">
      <div class="p-4 text-center">
        <div class="w-12 h-12 mx-auto mb-3 rounded-full bg-green-100 flex items-center justify-center">
          <svg class="w-6 h-6 text-green-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/>
          </svg>
        </div>
        <h3 class="text-base font-semibold text-[var(--text-primary)] mb-1">{{ completionTitle }}</h3>
        <p class="text-sm text-[var(--text-secondary)]">{{ completionMessage }}</p>
      </div>
      <div class="p-3 border-t border-[var(--border-color)] flex justify-center">
        <button @click="closeCompletionModal" class="px-4 py-1.5 text-xs rounded-lg bg-[var(--accent-500)] text-white hover:bg-accent-600">
          确定
        </button>
      </div>
    </div>
  </div>

  <!-- 发布模态框 -->
  <div
    v-if="showPublishModal"
    class="fixed inset-0 z-50 flex items-center justify-center bg-black/45 p-3"
    @click.self="closePublishModal"
  >
    <div class="bg-[var(--bg-primary)] rounded-2xl shadow-2xl w-full max-w-lg max-h-[85vh] overflow-hidden">
      <div class="p-3 border-b border-[var(--border-color)] flex items-center justify-between">
        <h3 class="text-sm font-semibold text-[var(--text-primary)]">发布章节</h3>
        <button @click="closePublishModal" class="p-1 text-[var(--text-muted)] hover:text-[var(--text-primary)]">
          <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
          </svg>
        </button>
      </div>
      <div class="p-4 overflow-y-auto max-h-[calc(85vh-120px)]">
        <div v-if="characterUpdates.length > 0" class="mb-4">
          <h4 class="text-xs font-medium text-[var(--text-secondary)] mb-2">角色状态变更</h4>
          <div class="space-y-2">
            <div
              v-for="update in characterUpdates"
              :key="update.character_id"
              class="p-2 bg-[var(--bg-panel)] rounded-lg text-xs"
            >
              <div class="font-medium text-[var(--text-primary)]">{{ update.character_name }}</div>
              <div class="text-[var(--text-muted)] mt-1">
                <span class="line-through">{{ update.old_state }}</span>
                <span class="mx-1">→</span>
                <span class="text-green-600">{{ update.new_state }}</span>
              </div>
            </div>
          </div>
        </div>
        <div v-else class="text-center text-sm text-[var(--text-muted)] py-4">
          暂无角色状态变更
        </div>
      </div>
      <div class="p-3 border-t border-[var(--border-color)] flex justify-end gap-2">
        <button @click="closePublishModal" class="px-3 py-1.5 text-xs rounded-lg bg-[var(--bg-panel)] text-[var(--text-secondary)] hover:bg-parchment-100">
          取消
        </button>
        <button @click="publishChapter" class="px-3 py-1.5 text-xs rounded-lg bg-[var(--accent-500)] text-white hover:bg-accent-600">
          确认发布
        </button>
      </div>
    </div>
  </div>
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
