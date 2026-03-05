<script setup lang="ts">
import { ref, computed } from 'vue'
import { useChapterGenerator } from '../composables/useChapterGenerator'
import { generateApi, chapterApi, publishPromptData } from '../composables/useApi'
import {
  AGENTIC_DEFAULTS,
  AGENTIC_FIELD_CONFIG,
  AGENTIC_GROUPS,
  buildAgenticPayload,
  getAgenticFieldFeedback,
  normalizeAgenticForm,
  validateAgenticForm
} from '../composables/useAgenticConfig'
import RichTextEditor from './RichTextEditor.vue'
import type { AgenticFormState, Chapter, Character } from '../types'

interface ApiConfig {
  api_key: string
  base_url: string
  model: string
}

const props = defineProps<{
  selectedChapter: Chapter | null
  characters: Character[]
  apiConfig: ApiConfig
  metaCollapsed?: boolean
}>()

const emit = defineEmits(['update-chapter', 'update-meta-collapsed', 'refresh-characters'])
const { isGenerating, generatedText, error, workflowState, startGeneration, startAgenticGeneration, reset } = useChapterGenerator()

const isPublishing = ref(false)
const publishError = ref<string | null>(null)
const showPublishModal = ref(false)
const showAgenticSettingsModal = ref(false)
const characterUpdates = ref<Array<{
  character_id: string
  character_name: string
  old_state: string
  new_state: string
}>>([])
const chapterSummary = ref<string | null>(null)

const agenticForm = ref<AgenticFormState>({ ...AGENTIC_DEFAULTS })
const wordCountMin = ref(500)
const wordCountMax = ref(10000)
const isStreamMode = ref(true)
const isAgenticMode = ref(true)
const formError = ref('')

const isEditorDisabled = computed(() => isGenerating.value || isPublishing.value)

const selectedChapter = computed(() => {
  return props.selectedChapter
})
const agenticValidation = computed(() => validateAgenticForm(agenticForm.value))
const agenticFieldFeedback = computed(() => getAgenticFieldFeedback(agenticForm.value))
const agenticGroupFields = computed(() => ({
  generation: ['word_count'] as Array<keyof AgenticFormState>,
  memory: ['rag_top_k', 'rag_alpha', 'rag_beta', 'rag_gamma', 'rag_lambda'] as Array<keyof AgenticFormState>,
  workflow: ['max_iterations'] as Array<keyof AgenticFormState>
}))
const hasFieldFeedback = computed(() => Object.values(agenticFieldFeedback.value).some(Boolean))
const firstFieldFeedback = computed(() => {
  return Object.values(agenticFieldFeedback.value).find(Boolean) || ''
})
const canSubmitAgentic = computed(() => {
  return agenticValidation.value.errors.length === 0 && !hasFieldFeedback.value
})
const ragWeightTotal = computed(() => {
  const sum = agenticForm.value.rag_alpha + agenticForm.value.rag_beta + agenticForm.value.rag_gamma
  return Math.round(sum * 1000) / 1000
})

function updateChapter(updates) {
  if (!selectedChapter.value) return
  emit('update-chapter', selectedChapter.value.id, updates)
}

function handleTitleInput(e: Event) {
  const target = e.target as HTMLInputElement
  scheduleMetaUpdate({ title: target.value })
}

function handleOutlineInput(e: Event) {
  const target = e.target as HTMLTextAreaElement
  scheduleMetaUpdate({ outline_text: target.value })
}

let metaUpdateTimeout: ReturnType<typeof setTimeout> | undefined
function scheduleMetaUpdate(updates) {
  clearTimeout(metaUpdateTimeout)
  metaUpdateTimeout = setTimeout(() => {
    updateChapter(updates)
  }, 500)
}

async function publishChapter() {
  if (!selectedChapter.value) return
  
  if (selectedChapter.value.status === 'published') {
    if (confirm('本章已发布，确定要取消发布吗？')) {
      try {
        isPublishing.value = true
        publishError.value = null
        await chapterApi.update(selectedChapter.value.id, { status: 'draft' })
        emit('update-chapter', selectedChapter.value.id, { status: 'draft' })
        alert('已取消发布')
      } catch (err: any) {
        publishError.value = err.message
        alert('取消发布失败: ' + err.message)
      } finally {
        isPublishing.value = false
      }
    }
    return
  }
  
  if (!props.apiConfig.api_key) {
    alert('请先在设置中配置 API Key 以启用角色动态状态更新功能')
  }
  
  if (confirm('确定要发布本章吗？发布后将会自动更新涉及角色的动态状态。')) {
    try {
      isPublishing.value = true
      publishError.value = null
      const result = await chapterApi.publish(selectedChapter.value.id, {
        api_key: props.apiConfig.api_key || undefined,
        base_url: props.apiConfig.base_url || undefined,
        model: props.apiConfig.model || 'gpt-4o-mini'
      })
      emit('update-chapter', selectedChapter.value.id, { status: 'published' })
      emit('refresh-characters')
      
      characterUpdates.value = result.character_updates || []
      
      // 直接从响应中获取摘要
      if (result.summary) {
        chapterSummary.value = result.summary
        emit('update-chapter', selectedChapter.value.id, { summary: result.summary })
      }
      
      showPublishModal.value = true
    } catch (err: any) {
      publishError.value = err.message
      alert('发布失败: ' + err.message)
    } finally {
      isPublishing.value = false
    }
  }
}

function closePublishModal() {
  showPublishModal.value = false
  characterUpdates.value = []
  chapterSummary.value = null
}

function openAgenticSettingsModal() {
  if (!isAgenticMode.value || isGenerating.value) return
  showAgenticSettingsModal.value = true
}

function closeAgenticSettingsModal() {
  showAgenticSettingsModal.value = false
}

function toggleCharacter(charId) {
  if (!selectedChapter.value) return
  
  const currentIds = selectedChapter.value.character_ids || []
  const newCharacterIds = currentIds.includes(charId)
    ? currentIds.filter(id => id !== charId)
    : [...currentIds, charId]
  
  updateChapter({ character_ids: newCharacterIds })
  chapterApi.updateEntities(selectedChapter.value.id, newCharacterIds).catch(err => {
    console.error('更新章节角色关联失败:', err)
  })
}

const editorRef = ref<any>(null)

let generateStartTime = 0
function getDurationText() {
  const duration = (Date.now() - generateStartTime) / 1000
  return `耗时 ${duration.toFixed(1)} 秒`
}

async function startGenerate() {
  if (!selectedChapter.value) {
    alert('请先选择章节')
    return
  }
  if (!isAgenticMode.value && !props.apiConfig.api_key) {
    alert('请先配置 API Key')
    return
  }
  
  const editor = editorRef.value?.editor
  const editorContent = editor ? editor.getText().trim() : ''
  
  if (editorContent) {
    if (!confirm('当前章节已有内容，生成新内容将覆盖原有内容。是否继续？')) {
      return
    }
    if (editorRef.value) {
      editorRef.value.clearContent()
    }
  }
  
  reset()
  formError.value = ''
  generateStartTime = Date.now()

  const requestData = {
    chapter_id: selectedChapter.value.id,
    api_key: props.apiConfig.api_key,
    base_url: props.apiConfig.base_url || undefined,
    model: props.apiConfig.model,
    word_count: agenticForm.value.word_count
  }
  
  if (isAgenticMode.value) {
    const rawFeedback = getAgenticFieldFeedback(agenticForm.value)
    const firstFeedback = Object.values(rawFeedback).find(Boolean)
    if (firstFeedback) {
      formError.value = firstFeedback
      alert(formError.value)
      return
    }
    const { payload, errors } = buildAgenticPayload({
      chapterId: selectedChapter.value.id,
      apiConfig: props.apiConfig,
      form: agenticForm.value
    })
    agenticForm.value = normalizeAgenticForm(agenticForm.value)
    if (!payload) {
      formError.value = errors[0] || '表单参数不合法'
      alert(formError.value)
      return
    }
    startAgenticGeneration(payload, {
      onEvent: (event, data) => {
        console.log('[Workflow Event]', event, data)
      },
      onChunk: (chunk) => {
        if (editorRef.value) {
          editorRef.value.insertContent(chunk)
        }
      },
      onComplete: (result) => {
        if (editorRef.value) {
          editorRef.value.flushBuffer()
        }
        const durationText = getDurationText()
        const statusMsg = result.passed 
          ? `本章正文生成完成！审查通过，共重写 ${result.revision_count} 次 (${durationText})`
          : `本章正文生成完成！已达成最大迭代次数，共重写 ${result.revision_count} 次 (${durationText})`
        alert(statusMsg)
      }
    })
  } else if (isStreamMode.value) {
    startGeneration(requestData, (chunk) => {
      if (editorRef.value) {
        editorRef.value.insertContent(chunk)
      }
    }, () => {
      if (editorRef.value) {
        editorRef.value.flushBuffer()
      }
      alert(`本章正文生成完成！(${getDurationText()})`)
    })
  } else {
    isGenerating.value = true
    try {
      const result = await generateApi.generateSync(requestData)
      publishPromptData(result.prompt)
      if (editorRef.value && result.content) {
        editorRef.value.clearContent()
        editorRef.value.insertContent(result.content)
      }
      alert(`本章正文生成完成！(${getDurationText()})`)
    } catch (err) {
      alert('生成失败: ' + (err as Error).message)
    } finally {
      isGenerating.value = false
    }
  }
}

function normalizeAgenticField() {
  const before = getAgenticFieldFeedback(agenticForm.value)
  agenticForm.value = normalizeAgenticForm(agenticForm.value)
  if (Object.keys(before).length > 0) {
    formError.value = '检测到无效输入，已自动恢复为有效值'
  } else if (!hasFieldFeedback.value) {
    formError.value = ''
  }
}

function restoreAgenticDefaults() {
  agenticForm.value = { ...AGENTIC_DEFAULTS }
  formError.value = ''
}

function restoreAgenticField(field: keyof AgenticFormState) {
  agenticForm.value = {
    ...agenticForm.value,
    [field]: AGENTIC_DEFAULTS[field]
  }
  formError.value = ''
}

function getAgenticFieldValue(field: keyof AgenticFormState) {
  return agenticForm.value[field]
}

function setAgenticFieldValue(field: keyof AgenticFormState, event: Event) {
  const target = event.target as HTMLInputElement
  const nextValue = Number(target.value)
  agenticForm.value = {
    ...agenticForm.value,
    [field]: nextValue
  }
}

function getAgenticFieldInputType(field: keyof AgenticFormState) {
  if (field === 'word_count' || field === 'max_iterations' || field === 'rag_top_k') {
    return 'number'
  }
  return 'number'
}

function getAgenticFieldStep(field: keyof AgenticFormState) {
  if (field === 'word_count') return 100
  if (field === 'max_iterations' || field === 'rag_top_k') return 1
  return 0.01
}

function getAgenticFieldMin(field: keyof AgenticFormState) {
  if (field === 'word_count') return 500
  if (field === 'max_iterations' || field === 'rag_top_k') return 1
  return 0
}

function getAgenticFieldMax(field: keyof AgenticFormState) {
  if (field === 'word_count') return 10000
  if (field === 'max_iterations') return 5
  if (field === 'rag_top_k') return 20
  if (field === 'rag_alpha' || field === 'rag_beta' || field === 'rag_gamma') return 1
  return undefined
}

function getAgenticFieldFeedbackText(field: keyof AgenticFormState) {
  return agenticFieldFeedback.value[field] || ''
}

let updateTimeout: ReturnType<typeof setTimeout> | undefined
function handleContentUpdate(content: string) {
  clearTimeout(updateTimeout)
  updateTimeout = setTimeout(() => {
    // 同时更新 draft_text 和 content_text
    updateChapter({ content_text: content, draft_text: content })
  }, 1000)
}

const localMetaCollapsed = ref(props.metaCollapsed ?? false)

function toggleMetaCollapsed() {
  localMetaCollapsed.value = !localMetaCollapsed.value
  emit('update-meta-collapsed', localMetaCollapsed.value)
}

function getMetaCollapsedLabel() {
  return localMetaCollapsed.value ? '展开信息' : '收起信息'
}

function getWorkflowStageLabel() {
  switch (workflowState.value.currentEvent) {
    case 'ASSEMBLING_CONTEXT':
      return '组装上下文'
    case 'DRAFTING':
      return '起草'
    case 'REVIEWING':
      return '审阅'
    case 'REFINING':
      return '重写优化'
    case 'FINAL_TEXT_STREAM':
      return '输出正文'
    case 'TEXT_CHUNK':
      return '写入中'
    case 'DONE':
      return '完成'
    default:
      return '处理中'
  }
}


function isCharacterSelected(charId: string) {
  return selectedChapter.value?.character_ids?.includes(charId) || false
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
              v-model.number="agenticForm.word_count"
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
              @click="isAgenticMode = !isAgenticMode"
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
              @click="isStreamMode = !isStreamMode"
              :disabled="isGenerating"
              class="px-2 py-0.5 text-[10px] rounded-lg bg-white text-[var(--text-secondary)]"
            >
              {{ isStreamMode ? '流' : '一次' }}
            </button>
            <button
              @click="startGenerate"
              :disabled="isGenerating || !selectedChapter.outline_text.trim() || (isAgenticMode && !canSubmitAgentic)"
              class="px-3 py-1 rounded-lg bg-[var(--accent-500)] text-white text-xs font-medium disabled:opacity-40 transition-colors"
            >
              {{ isGenerating ? '生成中' : '生成' }}
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
        <!-- 摘要部分 -->
        <div v-if="chapterSummary" class="bg-[var(--bg-panel)] rounded-xl p-4 border border-[var(--border-color)]">
          <h4 class="text-sm font-semibold text-[var(--text-primary)] mb-2 flex items-center gap-2">
            <svg class="w-4 h-4 text-indigo-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
            </svg>
            本章摘要 (自动生成)
          </h4>
          <p class="text-sm text-[var(--text-secondary)] leading-relaxed">{{ chapterSummary }}</p>
        </div>

        <!-- 角色状态变更部分 -->
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
