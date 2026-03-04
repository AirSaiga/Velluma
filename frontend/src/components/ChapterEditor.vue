<script setup lang="ts">
import { ref, computed } from 'vue'
import { useChapterGenerator } from '../composables/useChapterGenerator'
import { generateApi, chapterApi, publishPromptData } from '../composables/useApi'
import RichTextEditor from './RichTextEditor.vue'
import type { Chapter, Character } from '../types'

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
const characterUpdates = ref<Array<{
  character_id: string
  character_name: string
  old_state: string
  new_state: string
}>>([])

const wordCount = ref(2000)
const wordCountMin = ref(500)
const wordCountMax = ref(10000)
const isStreamMode = ref(true)
const isAgenticMode = ref(true)

const isEditorDisabled = computed(() => isGenerating.value)

const selectedChapter = computed(() => {
  return props.selectedChapter
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
      if (characterUpdates.value.length > 0) {
        showPublishModal.value = true
      } else {
        alert('本章已发布！')
      }
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
  if (!selectedChapter.value || !props.apiConfig.api_key) {
    alert('请先选择章节并配置 API Key')
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
  generateStartTime = Date.now()
  
  const requestData = {
    chapter_id: selectedChapter.value.id,
    api_key: props.apiConfig.api_key,
    base_url: props.apiConfig.base_url || undefined,
    model: props.apiConfig.model,
    word_count: wordCount.value,
    max_iterations: 2
  }
  
  if (isAgenticMode.value) {
    startAgenticGeneration(requestData, {
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

let updateTimeout: ReturnType<typeof setTimeout> | undefined
function handleContentUpdate(content: string) {
  clearTimeout(updateTimeout)
  updateTimeout = setTimeout(() => {
    updateChapter({ content_text: content })
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
              v-model="wordCount"
              :min="wordCountMin"
              :max="wordCountMax"
              step="100"
              class="w-24 h-1.5 rounded-full appearance-none cursor-pointer accent-[var(--accent-500)]"
            />
            <span class="text-[10px] font-medium text-[var(--accent-600)]">{{ wordCount }}</span>
          </div>
          <div class="flex items-center gap-1">
            <div
              v-if="isGenerating && isAgenticMode"
              class="mr-1 inline-flex items-center gap-1 px-2 py-0.5 rounded-lg bg-indigo-50 text-indigo-700 ring-1 ring-indigo-200"
            >
              <span class="text-[10px] font-medium">{{ getWorkflowStageLabel() }}</span>
              <span v-if="workflowState.iteration > 0" class="text-[10px]">#{{ workflowState.iteration }}</span>
              <span v-if="workflowState.message" class="text-[10px] text-indigo-600/90 max-w-[130px] truncate">
                {{ workflowState.message }}
              </span>
            </div>
            <button
              @click="isAgenticMode = !isAgenticMode"
              :disabled="isGenerating"
              class="px-2 py-0.5 text-[10px] rounded-lg transition-colors"
              :class="isAgenticMode
                ? 'bg-[var(--accent-500)]/15 text-[var(--accent-600)]'
                : 'bg-white text-[var(--text-secondary)]'"
            >
              {{ isAgenticMode ? 'Agentic' : '传统' }}
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
              :disabled="isGenerating || !selectedChapter.outline_text.trim()"
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

      <div class="rounded-2xl bg-white shadow-[0_8px_20px_rgba(18,38,63,0.06)] min-h-[60vh] flex flex-col">
        <RichTextEditor
          ref="editorRef"
          :model-value="selectedChapter.content_text"
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

  <div v-if="showPublishModal" class="fixed inset-0 z-50 flex items-center justify-center bg-black/50" @click.self="closePublishModal">
    <div class="bg-[var(--bg-primary)] rounded-2xl shadow-2xl w-full max-w-2xl max-h-[80vh] overflow-hidden">
      <div class="p-4 border-b border-white/60 flex items-center justify-between">
        <h3 class="text-lg font-semibold text-[var(--text-primary)]">本章已发布，角色动态状态更新</h3>
        <button @click="closePublishModal" class="p-1 text-[var(--text-muted)] hover:text-[var(--text-primary)]">
          <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
          </svg>
        </button>
      </div>
      <div class="p-4 overflow-y-auto max-h-[60vh]">
        <div v-for="update in characterUpdates" :key="update.character_id" class="mb-4 p-3 bg-[var(--bg-panel)] rounded-2xl">
          <div class="flex items-center gap-2 mb-2">
            <span class="font-medium text-primary-400">{{ update.character_name }}</span>
          </div>
          <div class="space-y-2 text-sm">
            <div>
              <span class="text-[var(--text-muted)]">旧状态：</span>
              <p class="text-[var(--text-secondary)] mt-1">{{ update.old_state || '暂无' }}</p>
            </div>
            <div>
              <span class="text-[var(--text-muted)]">新状态：</span>
              <p class="text-[var(--text-primary)] mt-1">{{ update.new_state || '暂无' }}</p>
            </div>
          </div>
        </div>
      </div>
      <div class="p-4 border-t border-white/60 flex justify-end">
        <button @click="closePublishModal" class="px-4 py-2 bg-[var(--accent-500)] text-white rounded-full transition-colors">
          确定
        </button>
      </div>
    </div>
  </div>
</template>
