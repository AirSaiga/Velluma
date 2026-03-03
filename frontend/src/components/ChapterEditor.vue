<script setup lang="ts">
import { ref, computed } from 'vue'
import { useChapterGenerator } from '../composables/useChapterGenerator'
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

const emit = defineEmits(['create-chapter', 'update-chapter', 'delete-chapter', 'save-generated', 'update-meta-collapsed'])

const selectedChapterId = ref<string | null>(null)
const { isGenerating, generatedText, error, startGeneration, reset } = useChapterGenerator()

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

function toggleCharacter(charId) {
  if (!selectedChapter.value) return
  
  const currentIds = selectedChapter.value.character_ids || []
  const newCharacterIds = currentIds.includes(charId)
    ? currentIds.filter(id => id !== charId)
    : [...currentIds, charId]
  
  updateChapter({ character_ids: newCharacterIds })
}

const editorRef = ref()

function startGenerate() {
  if (!selectedChapter.value || !props.apiConfig.api_key) {
    alert('请先选择章节并配置 API Key')
    return
  }
  
  if (selectedChapter.value.content_text && selectedChapter.value.content_text.trim()) {
    if (!confirm('当前章节已有内容，生成新内容将覆盖原有内容。是否继续？')) {
      return
    }
    if (editorRef.value) {
      editorRef.value.clearContent()
    }
  }
  
  reset()
  
  startGeneration({
    chapter_id: selectedChapter.value.id,
    api_key: props.apiConfig.api_key,
    base_url: props.apiConfig.base_url || undefined,
    model: props.apiConfig.model
  }, (chunk) => {
    if (editorRef.value) {
      editorRef.value.insertContent(chunk)
    }
  })
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

            <div class="flex items-center justify-between gap-3">
              <div v-if="error" class="text-sm text-rose-400 truncate">{{ error }}</div>
              <div class="flex-1"></div>
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
            </div>
          </div>

          <div class="flex-1 min-h-0 p-4">
            <RichTextEditor
              ref="editorRef"
              :model-value="selectedChapter.content_text"
              @update:model-value="handleContentUpdate"
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
</template>
