<script setup lang="ts">
import { ref, watch, computed } from 'vue'
import RichTextEditor from '../../../components/RichTextEditor.vue'
import PublishModal from './PublishModal.vue'
import type { Chapter } from '../../../types'

// V3.1 清理：旧双轨生成 UI（智能生成按钮/生成参数弹窗/节拍预览弹窗/澄清与完成弹窗/
// 生成进度遮罩）已移除。生成统一由 Inspector「本章」tab 的 useGenerationSession 驱动。
const props = defineProps<{
  characterUpdates: Array<{
    character_id: string
    character_name: string
    old_state: string
    new_state: string
  }>
  characterExtraction: any
  closePublishModal: () => void
  handleContentUpdate: (content: string) => void
  handleEditorEntityFocus: (keyword: string) => void
  handleFormatText: (text: string) => void
  handlePartialOptimize: (payload: { selection: any, instruction: string, mode?: string, tone?: string | null }) => void
  handleTitleInput: (event: Event) => void
  isEditorDisabled: boolean
  isFormatting: boolean
  isPublishing: boolean
  openInspirationModal: () => void
  openCritiqueModal: () => void
  publishChapter: () => void
  selectedChapter: Chapter | null
  setEditorRef: (editor: any) => void
  showPublishModal: boolean
  bookId?: string
  saveStatus?: 'idle' | 'saving' | 'saved' | 'error'
  lastSavedAt?: Date | null
}>()

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
</script>

<template>
  <div class="h-full flex flex-col overflow-hidden px-6 py-4 flex-1 min-h-0">
    <div v-if="selectedChapter" class="max-w-[920px] w-full mx-auto flex flex-col h-full flex-1 min-h-0 space-y-3">
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
        <div class="flex items-center gap-1 flex-shrink-0">
          <button
            @click="openInspirationModal"
            title="获取灵感"
            class="h-7 w-8 flex items-center justify-center rounded-md text-[var(--text-muted)] hover:text-[var(--accent-500)] hover:bg-accent-50 transition-colors"
          >
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
            </svg>
          </button>
          <button
            @click="openCritiqueModal"
            title="编辑审阅：毒舌编辑视角点评本章"
            class="h-7 w-8 flex items-center justify-center rounded-md text-[var(--text-muted)] hover:text-[var(--accent-500)] hover:bg-accent-50 transition-colors"
          >
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
            </svg>
          </button>
        </div>
        <button
          @click="publishChapter"
          :disabled="isPublishing"
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

      <!-- 章节大纲（编辑入口在上方章节卡横条）+ 编辑器区域 -->
      <div class="relative rounded-2xl bg-parchment-50 shadow-[0_8px_20px_rgba(18,38,63,0.06)] flex-1 min-h-0 flex flex-col overflow-hidden">
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
