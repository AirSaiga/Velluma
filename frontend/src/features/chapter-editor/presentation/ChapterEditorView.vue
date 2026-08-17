<script setup lang="ts">
import { ref, watch, computed, onMounted, onBeforeUnmount } from 'vue'
import RichTextEditor from '../../../components/RichTextEditor.vue'
import PublishModal from './PublishModal.vue'
import Icon from '../../../components/Icon.vue'
import type { Chapter } from '../../../types'
import type { EntityFocusPayload } from '../../../shared/types'

// 纸面优先：标题/动作收敛进纸列页面头（大标题 + ⋯ 菜单），编辑器本体无常驻工具栏。
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
  handleEditorEntityFocus: (payload: EntityFocusPayload) => void
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
    case 'saving': return '保存中…'
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

// ===== 页面头 ⋯ 菜单（章节动作：发布 / 灵感 / 审阅 / 格式整理）=====
const actionMenuOpen = ref(false)
const actionMenuRef = ref<HTMLElement | null>(null)

function toggleActionMenu() {
  actionMenuOpen.value = !actionMenuOpen.value
}

function onActionMenuOutsidePress(e: MouseEvent) {
  if (!actionMenuOpen.value) return
  const el = actionMenuRef.value
  if (el && e.target instanceof Node && el.contains(e.target)) return
  actionMenuOpen.value = false
}
onMounted(() => document.addEventListener('mousedown', onActionMenuOutsidePress))
onBeforeUnmount(() => document.removeEventListener('mousedown', onActionMenuOutsidePress))

function menuPublish() {
  actionMenuOpen.value = false
  props.publishChapter()
}
function menuInspiration() {
  actionMenuOpen.value = false
  props.openInspirationModal()
}
function menuCritique() {
  actionMenuOpen.value = false
  props.openCritiqueModal()
}
function menuFormat() {
  actionMenuOpen.value = false
  editorRef.value?.formatWholeDocument?.()
}
</script>

<template>
  <div class="h-full flex flex-col overflow-hidden px-5 pt-2 pb-4 flex-1 min-h-0">
    <div v-if="selectedChapter" class="max-w-[var(--editor-max-width)] w-full mx-auto flex flex-col h-full flex-1 min-h-0">
      <!-- 纸列：页面头（章节名 + 大标题 + ⋯ 菜单）+ 正文画布 -->
      <div class="paper relative rounded-2xl bg-parchment-50 shadow-[0_8px_20px_rgba(18,38,63,0.06)] flex-1 min-h-0 flex flex-col overflow-hidden">
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

        <!-- 页面头：与正文同列宽（px-12），衬线大标题写在纸面上 -->
        <header class="page-head flex-shrink-0">
          <div class="page-head__meta">
            <span class="page-head__chapter">{{ selectedChapter.chapter_name || `第${selectedChapter.chapter_number}章` }}</span>
            <span v-if="selectedChapter.status === 'published'" class="page-head__published">已发布</span>
            <span v-if="saveStatusLabel" class="page-head__save">{{ saveStatusLabel }}</span>
            <div ref="actionMenuRef" class="page-head__actions">
              <button
                class="page-head__menu-btn"
                :class="{ 'page-head__menu-btn--open': actionMenuOpen }"
                title="章节动作"
                @click="toggleActionMenu"
              >
                <Icon name="ellipsis" :size="16" />
              </button>
              <transition name="action-menu">
                <div v-if="actionMenuOpen" class="action-menu" @mousedown.stop>
                  <button class="action-menu__item" @click="menuPublish">
                    <Icon name="arrow-up-tray" :size="13" />
                    <span>{{ selectedChapter.status === 'published' ? '撤回发布' : '发布本章' }}</span>
                  </button>
                  <button class="action-menu__item" @click="menuInspiration">
                    <Icon name="light-bulb" :size="13" />
                    <span>获取灵感</span>
                  </button>
                  <button class="action-menu__item" @click="menuCritique">
                    <Icon name="pencil-square" :size="13" />
                    <span>编辑审阅</span>
                  </button>
                  <div class="action-menu__divider"></div>
                  <button class="action-menu__item" :disabled="isFormatting" @click="menuFormat">
                    <Icon name="sparkles" :size="13" />
                    <span>{{ isFormatting ? '格式整理中…' : '智能格式整理' }}</span>
                  </button>
                </div>
              </transition>
            </div>
          </div>
          <input
            :value="selectedChapter.title"
            @input="handleTitleInput"
            class="page-head__title"
            placeholder="未命名章节"
          />
        </header>

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
          placeholder="从这里开始写——Space 续写 · Alt+O 细纲 · Alt+N 记世界"
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
/* ===== 纸面页面头：与正文同列（编辑器内容 px-12），标题写在纸面上 ===== */
.page-head {
  padding: 1.75rem 3rem 0;
}

.page-head__meta {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  min-height: 1.5rem;
}

.page-head__chapter {
  font-size: 0.6875rem;
  font-weight: 600;
  letter-spacing: 0.08em;
  color: var(--text-muted);
}

.page-head__published {
  font-size: 0.625rem;
  padding: 0 0.375rem;
  border-radius: 999px;
  background: rgba(16, 185, 129, 0.12);
  color: #059669;
  line-height: 1.4;
}

.page-head__save {
  font-size: 0.6875rem;
  color: var(--text-muted);
  opacity: 0.85;
}

.page-head__actions {
  position: relative;
  margin-left: auto;
}

.page-head__menu-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 1.625rem;
  height: 1.625rem;
  background: transparent;
  border: none;
  border-radius: 0.375rem;
  color: var(--text-muted);
  cursor: pointer;
  opacity: 0;
  transition: all 0.15s ease;
}
/* 平时收起，悬停纸面/焦点时浮现（画布安静优先） */
.paper:hover .page-head__menu-btn,
.page-head__menu-btn--open,
.page-head__menu-btn:focus-visible {
  opacity: 1;
}
.page-head__menu-btn:hover {
  background: var(--hover-bg);
  color: var(--text-primary);
}

.action-menu {
  position: absolute;
  top: calc(100% + 4px);
  right: 0;
  z-index: 30;
  min-width: 10rem;
  padding: 0.25rem;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 0.625rem;
  box-shadow: 0 10px 30px rgba(15, 23, 42, 0.14);
  display: flex;
  flex-direction: column;
}

.action-menu__item {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  width: 100%;
  padding: 0.4375rem 0.625rem;
  background: transparent;
  border: none;
  border-radius: 0.375rem;
  font-size: 0.75rem;
  color: var(--text-primary);
  cursor: pointer;
  text-align: left;
  transition: background 0.12s ease;
}
.action-menu__item:hover:not(:disabled) {
  background: var(--hover-bg);
}
.action-menu__item:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.action-menu__item :deep(svg) {
  color: var(--text-muted);
  flex-shrink: 0;
}

.action-menu__divider {
  height: 1px;
  margin: 0.25rem 0.375rem;
  background: var(--border-color);
}

.action-menu-enter-active,
.action-menu-leave-active {
  transition: opacity 0.14s ease, transform 0.14s ease;
}
.action-menu-enter-from,
.action-menu-leave-to {
  opacity: 0;
  transform: translateY(-4px) scale(0.98);
}

/* 衬线大标题：写在纸面上，无边框，hover/focus 才显可编辑轮廓 */
.page-head__title {
  width: 100%;
  margin-top: 0.375rem;
  padding: 0.125rem 0;
  font-family: var(--font-heading);
  font-size: 1.75rem;
  font-weight: 700;
  line-height: 1.35;
  letter-spacing: 0.01em;
  color: var(--text-primary);
  background: transparent;
  border: none;
  border-bottom: 1px solid transparent;
  transition: border-color 0.15s ease;
}
.page-head__title::placeholder {
  color: var(--text-muted);
  opacity: 0.55;
  font-weight: 400;
}
.page-head__title:hover {
  border-bottom-color: var(--border-color);
}
.page-head__title:focus {
  outline: none;
  border-bottom-color: var(--accent-500);
}
</style>
