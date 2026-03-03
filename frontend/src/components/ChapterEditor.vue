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
  chapters: Chapter[]
  characters: Character[]
  apiConfig: ApiConfig
  metaCollapsed?: boolean
}>()

const emit = defineEmits(['create-chapter', 'update-chapter', 'delete-chapter', 'save-generated', 'update-meta-collapsed', 'refresh-characters'])

const selectedChapterId = ref<string | null>(null)
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
  return props.chapters.find(c => c.id === selectedChapterId.value)
})

const sortedChapters = computed(() => {
  return [...props.chapters].sort((a, b) => a.chapter_number - b.chapter_number)
})

function selectChapter(chapter: Chapter) {
  selectedChapterId.value = chapter.id
}

function handleTitleInput(e: Event) {
  const target = e.target as HTMLInputElement
  scheduleMetaUpdate({ title: target.value })
}

function handleOutlineInput(e: Event) {
  const target = e.target as HTMLTextAreaElement
  scheduleMetaUpdate({ outline_text: target.value })
}

function addChapter() {
  const maxNumber = props.chapters.length > 0 
    ? Math.max(...props.chapters.map(c => c.chapter_number)) 
    : 0
  emit('create-chapter', {
    chapter_number: maxNumber + 1,
    title: `第${maxNumber + 1}章`,
    outline_text: '',
    content_text: '',
    status: 'draft'
  })
}

function updateChapter(updates) {
  if (!selectedChapter.value) return
  emit('update-chapter', selectedChapter.value.id, updates)
}

let metaUpdateTimeout: ReturnType<typeof setTimeout> | undefined
function scheduleMetaUpdate(updates) {
  clearTimeout(metaUpdateTimeout)
  metaUpdateTimeout = setTimeout(() => {
    updateChapter(updates)
  }, 500)
}

function deleteChapter(chapter) {
  if (confirm(`确定要删除"${chapter.title}"吗？`)) {
    emit('delete-chapter', chapter.id)
    if (selectedChapterId.value === chapter.id) {
      selectedChapterId.value = null
    }
  }
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

const editorRef = ref()

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
        const statusMsg = result.passed 
          ? `本章正文生成完成！审查通过，共重写 ${result.revision_count} 次`
          : `本章正文生成完成！已达成最大迭代次数，共重写 ${result.revision_count} 次`
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
      alert('本章正文生成完成！')
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
      alert('本章正文生成完成！')
    } catch (err) {
      alert('生成失败: ' + err.message)
    } finally {
      isGenerating.value = false
    }
  }
}

// Debounce update to avoid spamming API
let updateTimeout
function handleContentUpdate(content) {
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


function isCharacterSelected(charId) {
  return selectedChapter.value?.character_ids?.includes(charId) || false
}
</script>

<template>
  <div class="h-full flex flex-col bg-[var(--bg-primary)]">
    <div class="p-4 border-b border-[var(--border-color)] flex items-center justify-between">
      <h2 class="text-lg font-semibold text-[var(--text-primary)]">章节编辑器</h2>
      <button
        @click="addChapter"
        class="px-3 py-1.5 bg-primary-600 hover:bg-primary-500 text-white text-sm rounded-lg transition-colors flex items-center gap-1"
      >
        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"/>
        </svg>
        新建章节
      </button>
    </div>
    
    <div class="flex-1 flex min-h-0">
      <div class="w-48 flex-shrink-0 border-r border-[var(--border-color)] overflow-y-auto bg-[var(--bg-secondary)]">
        <div class="p-2 space-y-1">
          <div
            v-for="chapter in sortedChapters"
            :key="chapter.id"
            @click="selectChapter(chapter)"
            class="group p-2 rounded-lg cursor-pointer transition-all"
            :class="selectedChapterId === chapter.id 
              ? 'bg-primary-600/20 border border-primary-500' 
              : 'hover:bg-[var(--bg-tertiary)]'"
          >
            <div class="flex items-center justify-between">
              <span class="text-sm font-medium text-[var(--text-primary)]">
                {{ chapter.title }}
              </span>
              <button
                @click.stop="deleteChapter(chapter)"
                class="opacity-0 group-hover:opacity-100 p-1 text-[var(--text-muted)] hover:text-rose-400 transition-all"
              >
                <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
                </svg>
              </button>
            </div>
            <span class="text-xs text-[var(--text-muted)]">Chapter {{ chapter.chapter_number }}</span>
          </div>
          
          <div v-if="sortedChapters.length === 0" class="text-center py-8 text-[var(--text-muted)] text-sm">
            暂无章节
          </div>
        </div>
      </div>
      
      <div class="flex-1 min-h-0 flex flex-col">
        <div v-if="selectedChapter" class="flex flex-col min-h-0">
          <div class="p-4 border-b border-[var(--border-color)] bg-[var(--bg-primary)] flex items-center gap-3">
            <input
              :value="selectedChapter.title"
              @input="handleTitleInput"
              class="flex-1 px-3 py-2 bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-lg text-[var(--text-primary)] font-medium focus:outline-none focus:border-primary-500"
              placeholder="章节标题"
            />
            <button
              class="px-3 py-2 text-sm bg-[var(--bg-tertiary)] hover:bg-[var(--hover-bg)] text-[var(--text-muted)] hover:text-[var(--text-primary)] rounded-lg transition-colors"
              @click="toggleMetaCollapsed"
            >
              {{ getMetaCollapsedLabel() }}
            </button>
          </div>

          <div v-show="!localMetaCollapsed" class="px-4 py-3 border-b border-[var(--border-color)] bg-[var(--bg-primary)] space-y-3">
            <div>
              <label class="block text-xs text-[var(--text-muted)] mb-2">出场人物</label>
              <div class="flex flex-wrap gap-2 p-3 bg-[var(--bg-tertiary)] rounded-lg border border-[var(--border-color)] max-h-28 overflow-y-auto">
                <button
                  v-for="char in characters"
                  :key="char.id"
                  @click="toggleCharacter(char.id)"
                  class="px-2.5 py-1 text-xs rounded-full border transition-all"
                  :class="isCharacterSelected(char.id) 
                    ? 'bg-primary-600/20 border-primary-500 text-primary-400' 
                    : 'bg-[var(--bg-secondary)] border-[var(--border-color)] text-[var(--text-muted)] hover:border-[var(--text-muted)]'"
                >
                  {{ char.name }}
                </button>
                <span v-if="characters.length === 0" class="text-xs text-[var(--text-muted)]">
                  暂无角色，请在左侧添加
                </span>
              </div>
            </div>

            <div>
              <label class="block text-xs text-[var(--text-muted)] mb-2">剧情指令</label>
              <textarea
                :value="selectedChapter.outline_text"
                @input="handleOutlineInput"
                rows="3"
                class="w-full px-3 py-2 bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-lg text-[var(--text-primary)] text-sm focus:outline-none focus:border-primary-500 resize-none"
                placeholder="本章要发生的情节..."
              />
            </div>

            <div>
              <div class="flex items-center justify-between mb-2">
                <label class="text-xs text-[var(--text-muted)]">期望字数</label>
                <span class="text-xs font-medium text-primary-400">{{ wordCount }} 字</span>
              </div>
              <div class="flex items-center gap-3">
                <input
                  type="range"
                  v-model="wordCount"
                  :min="wordCountMin"
                  :max="wordCountMax"
                  step="100"
                  class="flex-1 h-2 bg-[var(--bg-tertiary)] rounded-lg appearance-none cursor-pointer accent-primary-500"
                />
                <input
                  type="number"
                  v-model="wordCountMin"
                  class="w-16 px-2 py-1 text-xs bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded text-[var(--text-primary)] focus:outline-none focus:border-primary-500"
                  placeholder="最小"
                />
                <span class="text-xs text-[var(--text-muted)]">-</span>
                <input
                  type="number"
                  v-model="wordCountMax"
                  class="w-16 px-2 py-1 text-xs bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded text-[var(--text-primary)] focus:outline-none focus:border-primary-500"
                  placeholder="最大"
                />
              </div>
            </div>

            <div class="flex items-center justify-between gap-3">
              <div v-if="error" class="text-sm text-rose-400 truncate">{{ error }}</div>
              <div v-else-if="isGenerating && isAgenticMode && workflowState.currentEvent" class="flex items-center gap-2">
                <span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium"
                  :class="{
                    'bg-blue-100 text-blue-800': workflowState.currentEvent === 'ASSEMBLING_CONTEXT',
                    'bg-purple-100 text-purple-800': workflowState.currentEvent === 'DRAFTING',
                    'bg-yellow-100 text-yellow-800': workflowState.currentEvent === 'REVIEWING',
                    'bg-orange-100 text-orange-800': workflowState.currentEvent === 'REFINING',
                    'bg-green-100 text-green-800': workflowState.currentEvent === 'FINAL_TEXT_STREAM' || workflowState.currentEvent === 'TEXT_CHUNK',
                    'bg-gray-100 text-gray-800': workflowState.currentEvent === 'DONE'
                  }"
                >
                  <svg v-if="workflowState.currentEvent === 'ASSEMBLING_CONTEXT'" class="w-3 h-3 mr-1 animate-pulse" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4"/>
                  </svg>
                  <svg v-else-if="workflowState.currentEvent === 'DRAFTING'" class="w-3 h-3 mr-1 animate-pulse" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z"/>
                  </svg>
                  <svg v-else-if="workflowState.currentEvent === 'REVIEWING'" class="w-3 h-3 mr-1 animate-pulse" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"/>
                  </svg>
                  <svg v-else-if="workflowState.currentEvent === 'REFINING'" class="w-3 h-3 mr-1 animate-pulse" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/>
                  </svg>
                  <svg v-else-if="workflowState.currentEvent === 'FINAL_TEXT_STREAM' || workflowState.currentEvent === 'TEXT_CHUNK'" class="w-3 h-3 mr-1 animate-pulse" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z"/>
                  </svg>
                  {{ workflowState.message }}
                </span>
                <span v-if="workflowState.iteration > 0" class="text-xs text-[var(--text-muted)]">
                  轮次: {{ workflowState.iteration }}
                </span>
              </div>
              <div v-else class="flex-1"></div>
              <button
                @click="isAgenticMode = !isAgenticMode"
                :disabled="isGenerating"
                class="px-3 py-2 text-sm rounded-lg transition-colors border"
                :class="isAgenticMode 
                  ? 'bg-indigo-100 border-indigo-300 text-indigo-700' 
                  : 'bg-[var(--bg-tertiary)] border-[var(--border-color)] text-[var(--text-muted)] hover:text-[var(--text-primary)]'"
                :title="isAgenticMode ? 'Actor-Critic 模式：三阶段审评流水线' : '传统模式：单次生成'"
              >
                {{ isAgenticMode ? '🎭 Agentic' : '📝 传统' }}
              </button>
              <button
                v-if="isAgenticMode"
                @click="isStreamMode = !isStreamMode"
                :disabled="isGenerating"
                class="px-3 py-2 text-sm bg-[var(--bg-tertiary)] hover:bg-[var(--hover-bg)] text-[var(--text-muted)] hover:text-[var(--text-primary)] rounded-lg transition-colors border border-[var(--border-color)]"
                :title="isStreamMode ? '当前：流式输出' : '当前：一次性输出'"
              >
                {{ isStreamMode ? '🔄 流式' : '📦 一次性' }}
              </button>
              <button
                @click="startGenerate"
                :disabled="isGenerating || !selectedChapter.outline_text.trim()"
                class="px-5 py-2 bg-emerald-600 hover:bg-emerald-500 disabled:bg-[var(--bg-tertiary)] disabled:text-[var(--text-muted)] text-white font-medium rounded-lg transition-colors flex items-center gap-2"
              >
                <svg v-if="isGenerating" class="w-5 h-5 animate-spin" fill="none" viewBox="0 0 24 24">
                  <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                  <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                </svg>
                <svg v-else class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z"/>
                </svg>
                {{ isGenerating ? '生成中...' : '生成本章正文' }}
              </button>
              <button
                @click="publishChapter"
                :disabled="isPublishing"
                class="px-5 py-2 bg-blue-600 hover:bg-blue-500 disabled:bg-[var(--bg-tertiary)] disabled:text-[var(--text-muted)] text-white font-medium rounded-lg transition-colors flex items-center gap-2"
              >
                <svg v-if="isPublishing" class="w-5 h-5 animate-spin" fill="none" viewBox="0 0 24 24">
                  <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                  <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                </svg>
                <svg v-else class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path v-if="selectedChapter.status !== 'published'" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12"/>
                  <path v-else stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"/>
                </svg>
                {{ isPublishing ? '发布中...' : (selectedChapter.status === 'published' ? '已发布' : '发布本章') }}
              </button>
            </div>
          </div>

          <div class="flex-1 min-h-0 p-4">
            <RichTextEditor
              ref="editorRef"
              :model-value="selectedChapter.content_text"
              @update:model-value="handleContentUpdate"
              :disabled="isEditorDisabled"
              placeholder="在此处开始写作或生成内容..."
            />
          </div>
        </div>
        
        <div v-else class="flex items-center justify-center h-full">
          <div class="text-center">
            <div class="w-16 h-16 mx-auto mb-4 rounded-full bg-[var(--bg-secondary)] flex items-center justify-center">
              <svg class="w-8 h-8 text-[var(--text-muted)]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/>
              </svg>
            </div>
            <p class="text-[var(--text-muted)] text-sm">选择一个章节或新建章节开始编辑</p>
          </div>
        </div>
      </div>
    </div>
  </div>

  <div v-if="showPublishModal" class="fixed inset-0 z-50 flex items-center justify-center bg-black/50" @click.self="closePublishModal">
    <div class="bg-[var(--bg-primary)] rounded-xl shadow-2xl w-full max-w-2xl max-h-[80vh] overflow-hidden border border-[var(--border-color)]">
      <div class="p-4 border-b border-[var(--border-color)] flex items-center justify-between">
        <h3 class="text-lg font-semibold text-[var(--text-primary)]">本章已发布，角色动态状态更新</h3>
        <button @click="closePublishModal" class="p-1 text-[var(--text-muted)] hover:text-[var(--text-primary)]">
          <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
          </svg>
        </button>
      </div>
      <div class="p-4 overflow-y-auto max-h-[60vh]">
        <div v-for="update in characterUpdates" :key="update.character_id" class="mb-4 p-3 bg-[var(--bg-secondary)] rounded-lg border border-[var(--border-color)]">
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
      <div class="p-4 border-t border-[var(--border-color)] flex justify-end">
        <button @click="closePublishModal" class="px-4 py-2 bg-primary-600 hover:bg-primary-500 text-white rounded-lg transition-colors">
          确定
        </button>
      </div>
    </div>
  </div>
</template>
