<script setup lang="ts">
import { ref, watch, computed } from 'vue'
import RichTextEditor from '../../../components/RichTextEditor.vue'
import WorkflowProgressGraph from '../../../components/WorkflowProgressGraph.vue'
import ClarificationModal from './ClarificationModal.vue'
import AgenticSettingsModal from './AgenticSettingsModal.vue'
import BeatReviewModal from './BeatReviewModal.vue'
import CompletionModal from './CompletionModal.vue'
import PublishModal from './PublishModal.vue'
import type { ApiConfig, Chapter, Character } from '../../../types'
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
  handlePartialOptimize: (payload: { selection: any, instruction: string }) => void
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
}>()

const emit = defineEmits<{
  (e: 'request-critique', content: string): void
  (e: 'intent-generate', payload: any): void
  (e: 'intent-save', payload: any): void
}>()

const editorRef = ref<any>(null)
const showAdvancedSettings = ref(false)
const showCharacterSelector = ref(false)
const showAssetSelector = ref(false)
const characterSearchQuery = ref('')
const assetSearchQuery = ref('')
const isConfigExpanded = ref(true)

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

const selectedAssets = computed(() => {
  return props.assets?.filter(a => props.isAssetSelected(a.id)) || []
})

const filteredAssets = computed(() => {
  if (!assetSearchQuery.value) return props.assets || []
  const query = assetSearchQuery.value.toLowerCase()
  return (props.assets || []).filter(a => a.name.toLowerCase().includes(query))
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
  <div class="h-full flex flex-col overflow-hidden px-6 py-4">
    <div v-if="selectedChapter" class="max-w-[920px] w-full mx-auto flex flex-col h-full space-y-3">
      <!-- 章节标题行 -->
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
      <div class="rounded-xl bg-[var(--bg-panel)] flex-shrink-0 overflow-hidden border border-[var(--border-color)]/50 transition-all duration-300">
        <!-- 折叠头部 -->
        <div 
          class="px-3 py-2 flex items-center justify-between cursor-pointer hover:bg-black/[0.02]"
          @click="isConfigExpanded = !isConfigExpanded"
        >
          <div class="flex items-center gap-2 min-w-0">
            <svg class="w-4 h-4 text-[var(--text-muted)] shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"></path>
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"></path>
            </svg>
            <span class="text-xs font-medium text-[var(--text-secondary)] shrink-0">生成配置</span>
            <span v-if="!isConfigExpanded && selectedChapter.outline_text" class="text-[10px] text-[var(--text-muted)] truncate mx-2">
              {{ selectedChapter.outline_text }}
            </span>
          </div>
          <div class="flex items-center gap-2 shrink-0">
            <!-- 快速生成按钮，在折叠时也可用 -->
            <button
              v-if="!isConfigExpanded"
              @click.stop="startGenerate"
              :disabled="isGenerating || beatPreviewLoading || isClarifyingOutline || !selectedChapter.outline_text.trim()"
              class="h-6 px-2.5 rounded text-[10px] font-medium bg-[var(--accent-500)] text-white shadow-sm disabled:opacity-40 transition-all hover:bg-accent-600 flex items-center gap-1"
            >
              <svg v-if="beatPreviewLoading || isGenerating || isClarifyingOutline" class="animate-spin h-3 w-3" fill="none" viewBox="0 0 24 24">
                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
              </svg>
              <svg v-else class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z" />
              </svg>
              {{ isClarifyingOutline ? '澄清中' : (beatPreviewLoading ? '规划中' : (isGenerating ? '生成中' : '智能生成')) }}
            </button>
            <svg 
              class="w-4 h-4 text-[var(--text-muted)] transition-transform" 
              :class="isConfigExpanded ? 'rotate-180' : ''"
              fill="none" stroke="currentColor" viewBox="0 0 24 24"
            >
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/>
            </svg>
          </div>
        </div>

        <!-- 展开内容区 -->
        <div v-show="isConfigExpanded" class="border-t border-[var(--border-color)]/50 bg-[var(--bg-panel)]">
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

        <!-- 第二层：上下文关联（人物与道具） -->
        <div class="px-3 pb-2.5 border-t border-[var(--border-color)]/50">
          <div class="mt-2 grid grid-cols-1 md:grid-cols-2 gap-4">
            <!-- 左列：人物选择 -->
            <div>
              <div class="flex items-center gap-2 mb-1.5">
                <label class="text-[10px] font-medium text-[var(--text-secondary)] flex items-center gap-1">
                  <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4.354a4 4 0 110 5.292M15 21H3v-1a6 6 0 0112 0v1zm0 0h6v-1a6 6 0 00-9-5.197M13 7a4 4 0 11-8 0 4 4 0 018 0z"/>
                  </svg>
                  本章出场人物
                </label>
              </div>
              
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
                <div class="max-h-40 overflow-y-auto">
                  <div v-if="filteredCharacters.length === 0" class="text-center py-3 text-[11px] text-[var(--text-muted)]">
                    未找到匹配的人物
                  </div>
                  <div v-else class="grid grid-cols-2 gap-1.5">
                    <button
                      v-for="char in filteredCharacters"
                      :key="char.id"
                      @click="toggleCharacter(char.id)"
                      class="px-2 py-1.5 text-[11px] rounded-md text-left transition-all border truncate"
                      :class="isCharacterSelected(char.id)
                        ? 'bg-accent-50 text-accent-700 border-accent-300 shadow-sm'
                        : 'bg-[var(--bg-primary)] text-[var(--text-secondary)] border-[var(--border-color)] hover:border-accent-200 hover:bg-accent-50/30'"
                    >
                      <div class="flex items-center gap-1">
                        <span v-if="isCharacterSelected(char.id)" class="text-accent-500 shrink-0">
                          <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/>
                          </svg>
                        </span>
                        <span class="truncate">{{ char.name }}</span>
                      </div>
                    </button>
                  </div>
                </div>
              </div>
            </div>

            <!-- 右列：道具资产选择 -->
            <div>
              <div class="flex items-center gap-2 mb-1.5">
                <label class="text-[10px] font-medium text-[var(--text-secondary)] flex items-center gap-1">
                  <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M20 7l-8-4-8 4m16 0l-8 4m8-4v10l-8 4m0-10L4 7m8 4v10M4 7v10l8 4"/>
                  </svg>
                  本章关键道具
                </label>
              </div>

              <div class="flex items-start gap-2">
                <div class="flex-1 min-w-0">
                  <div v-if="selectedAssets.length === 0" class="flex items-center gap-2">
                    <span class="text-[11px] text-[var(--text-muted)] italic">尚未选择关键道具</span>
                    <button
                      @click="showAssetSelector = !showAssetSelector"
                      class="text-[11px] text-[var(--accent-500)] hover:text-accent-600 font-medium flex items-center gap-0.5"
                    >
                      <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"/>
                      </svg>
                      添加道具
                    </button>
                  </div>
                  <div v-else class="flex flex-wrap items-center gap-1.5">
                    <span 
                      v-for="asset in selectedAssets" 
                      :key="asset.id"
                      class="inline-flex items-center gap-1 px-2 py-1 text-[11px] rounded-full ring-1 transition-all bg-emerald-50 text-emerald-600 ring-emerald-200"
                    >
                      {{ asset.name }}
                      <button
                        @click="toggleAsset(asset.id)"
                        class="hover:text-rose-500 hover:bg-rose-50 rounded-full p-0.5"
                      >
                        <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
                        </svg>
                      </button>
                    </span>
                    <button
                      @click="showAssetSelector = !showAssetSelector"
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

              <!-- 道具选择展开面板 -->
              <div 
                v-if="showAssetSelector" 
                class="mt-2 p-3 bg-[var(--bg-canvas)] rounded-lg border border-[var(--border-color)]"
              >
                <div class="relative mb-2">
                  <svg class="w-4 h-4 absolute left-2.5 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"/>
                  </svg>
                  <input
                    v-model="assetSearchQuery"
                    type="text"
                    placeholder="搜索道具..."
                    class="w-full pl-9 pr-3 py-1.5 text-xs rounded-md bg-[var(--bg-primary)] border border-[var(--border-color)] focus:outline-none focus:border-[var(--accent-500)]"
                  />
                </div>
                <div class="max-h-40 overflow-y-auto">
                  <div v-if="filteredAssets.length === 0" class="text-center py-3 text-[11px] text-[var(--text-muted)]">
                    未找到匹配的道具
                  </div>
                  <div v-else class="grid grid-cols-2 gap-1.5">
                    <button
                      v-for="asset in filteredAssets"
                      :key="asset.id"
                      @click="toggleAsset(asset.id)"
                      class="px-2 py-1.5 text-[11px] rounded-md text-left transition-all border truncate"
                      :class="isAssetSelected(asset.id)
                        ? 'bg-emerald-50 text-emerald-700 border-emerald-300 shadow-sm'
                        : 'bg-[var(--bg-primary)] text-[var(--text-secondary)] border-[var(--border-color)] hover:border-accent-200 hover:bg-accent-50/30'"
                    >
                      <div class="flex items-center gap-1">
                        <span v-if="isAssetSelected(asset.id)" class="text-emerald-500 shrink-0">
                          <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/>
                          </svg>
                        </span>
                        <span class="truncate">{{ asset.name }}</span>
                      </div>
                    </button>
                  </div>
                </div>
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

    <div v-else class="flex-1 flex flex-col items-center justify-center text-center">
      <div class="w-16 h-16 rounded-2xl bg-[var(--accent-100)]/30 flex items-center justify-center mb-4">
        <svg class="w-8 h-8 text-[var(--accent-700)]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253" />
        </svg>
      </div>
      <h3 class="text-base font-semibold text-[var(--text-primary)] mb-1">选择一个章节开始创作</h3>
      <p class="text-sm text-[var(--text-muted)] max-w-xs">在左侧章节列表中选择已有章节，或新建一章开始 AI 辅助写作</p>
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
    @close="closeBeatReviewModal"
    @confirm="confirmBeatsAndGenerate"
  />

  <ClarificationModal
    :show="showClarificationModal"
    :is-processing="isClarifyingOutline"
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
