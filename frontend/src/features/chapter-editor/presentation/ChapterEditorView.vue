<script setup lang="ts">
import { ref, watch, computed, onMounted, onBeforeUnmount } from 'vue'
import RichTextEditor from '../../../components/RichTextEditor.vue'
import PublishModal from './PublishModal.vue'
import Icon from '../../../components/Icon.vue'
import type { Chapter } from '../../../types'
import type { EntityFocusPayload } from '../../../shared/types'
import { assistEnabled } from '../../generation/composables/useAssistEnabled'

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
  publishChapter: () => void
  selectedChapter: Chapter | null
  setEditorRef: (editor: any) => void
  showPublishModal: boolean
  bookId?: string
  saveStatus?: 'idle' | 'saving' | 'saved' | 'error'
  lastSavedAt?: Date | null
  /** 当前章节字数（WorkspaceView 剥 HTML 计字符下传；底栏删除后由页头 meta 行继承） */
  wordCount?: number
  /** AI 状态短句（08 期 §4.2 N9：顶栏退役后住进页面头 meta 行；文案=07 期表 A1/A2 原句） */
  aiStateLabel?: string
  aiStateError?: boolean
}>()

// 占位引导双态（审计 §6-E 修复）：AI 辅助关闭时不再承诺 Space 续写；
// 开启态给三个高频入口（Tab 是卡片舱唯一入口，优先于 Alt+N——后者在速查表）
const editorPlaceholder = computed(() =>
  assistEnabled.value
    ? '从这里开始写——Space 让 AI 接着写 · Tab 找镜头 · Alt+O 插细纲'
    : '从这里开始写',
)

const saveStatusLabel = computed(() => {
  switch (props.saveStatus) {
    case 'saving': return '保存中…'
    case 'saved': return props.lastSavedAt ? `已保存 ${formatTime(props.lastSavedAt)}` : '已保存'
    case 'error': return '保存失败（已存本地草稿）'
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
function menuFormat() {
  actionMenuOpen.value = false
  editorRef.value?.formatWholeDocument?.()
}
// 2026-09-10 编辑器优化：三个本机命令（零 LLM）。Ctrl+F 之外的可发现入口——
// 键位藏起来的功能等于不存在（快捷键速查表也只覆盖到愿意去看的人）。
function menuFind() {
  actionMenuOpen.value = false
  editorRef.value?.openFind?.()
}
function menuNormalizePunctuation() {
  actionMenuOpen.value = false
  editorRef.value?.normalizePunctuation?.()
}
function menuClearForeignStyles() {
  actionMenuOpen.value = false
  editorRef.value?.clearForeignStyles?.()
}
</script>

<template>
  <div class="h-full flex flex-col overflow-hidden px-5 pt-5 pb-5 flex-1 min-h-0">
    <div v-if="selectedChapter" class="max-w-[var(--editor-max-width)] w-full mx-auto flex flex-col h-full flex-1 min-h-0">
      <!-- 纸列：页面头（章节名 + 大标题 + ⋯ 菜单）+ 正文画布 -->
      <div class="paper relative rounded-2xl shadow-[var(--shadow-paper)] flex-1 min-h-0 flex flex-col overflow-hidden">
        <div
          v-if="isPublishing"
          class="publish-veil absolute inset-0 z-10 flex flex-col items-center justify-center backdrop-blur-[2px] rounded-2xl transition-all duration-300"
        >
          <div class="relative flex items-center justify-center w-24 h-24 mb-8">
            <div class="absolute inset-0 rounded-full border-[6px] border-accent-100"></div>
            <div class="absolute inset-0 rounded-full border-[6px] border-accent-500 border-t-transparent animate-spin"></div>
          </div>

          <div class="flex flex-col items-center gap-3">
            <h3 class="text-3xl font-heading font-bold text-accent-900 tracking-tight">
              正在发布…
            </h3>
            <p class="text-lg text-accent-600 font-medium max-w-xl text-center px-6 leading-relaxed">
              正在更新角色近况…
            </p>
          </div>
        </div>

        <!-- 页面头：与正文同列宽（px-12），衬线大标题写在纸面上 -->
        <header class="page-head flex-shrink-0">
          <div class="page-head__meta">
            <span class="page-head__chapter">{{ selectedChapter.chapter_name || `第${selectedChapter.chapter_number}章` }}</span>
            <span v-if="selectedChapter.status === 'published'" class="page-head__published">已发布</span>
            <span v-if="typeof wordCount === 'number'" class="page-head__words tnum">{{ wordCount }} 字</span>
            <span v-if="saveStatusLabel" class="page-head__save" :class="{ 'page-head__save--error': saveStatus === 'error' }">{{ saveStatusLabel }}</span>
            <span v-if="aiStateLabel" class="page-head__ai" :class="{ 'page-head__ai--error': aiStateError }" aria-live="polite"><span class="page-head__ai-dot"></span>{{ aiStateLabel }}</span>
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
                <div v-if="actionMenuOpen" class="action-menu menu-shell" @mousedown.stop>
                  <button class="action-menu__item menu-item" @click="menuPublish">
                    <Icon name="arrow-up-tray" :size="13" />
                    <span>{{ selectedChapter.status === 'published' ? '撤回发布' : '发布本章' }}</span>
                  </button>
                  <button class="action-menu__item menu-item" @click="menuInspiration">
                    <Icon name="light-bulb" :size="13" />
                    <span>找找灵感</span>
                  </button>
                  <div class="action-menu__divider menu-sep"></div>
                  <button class="action-menu__item menu-item" @click="menuFind">
                    <Icon name="magnifying-glass" :size="13" />
                    <span>查找替换<kbd class="action-menu__kbd menu-kbd">Ctrl+F</kbd></span>
                  </button>
                  <button class="action-menu__item menu-item" title="把 ASCII 省略号、半角逗号句号、直引号统一成中文标点（本机即时完成，不改剧情）" @click="menuNormalizePunctuation">
                    <Icon name="bolt" :size="13" />
                    <span>整理标点</span>
                  </button>
                  <button class="action-menu__item menu-item" title="清掉从别处粘贴带进来的颜色与字体（深色主题下它们会让字看不见）" @click="menuClearForeignStyles">
                    <Icon name="no-symbol" :size="13" />
                    <span>清除外来样式</span>
                  </button>
                  <div class="action-menu__divider menu-sep"></div>
                  <button class="action-menu__item menu-item" :disabled="isFormatting" @click="menuFormat">
                    <Icon name="sparkles" :size="13" />
                    <span>{{ isFormatting ? '正在整理格式…' : '整理全文格式' }}</span>
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
          <div class="page-head__ornament" aria-hidden="true">❦</div>
        </header>

        <!-- 页首块槽（08 期 §4.3：点火卡从悬浮封面改为纸内页首块，随文流走） -->
        <slot name="page-top" />

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
          :placeholder="editorPlaceholder"
        />
      </div>
    </div>

    <div v-else class="h-full flex items-center justify-center">
      <!-- 04 §D3 空态统一规格：❦ + 衬线主句 + 灰副句 -->
      <div class="empty-state">
        <p class="empty-state__title">这本书还空着</p>
        <p class="empty-state__sub">从左缘书签打开目录，选一章或新起一章开始写</p>
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
/* 纸面 token 化（08 期 §4.1：--paper-bg 双主题，根治深色「白纸白字」P0）。
   04 §A1/A2：拆 background 简写接 --paper-texture（选「纸纹」背景时纸面得纹，
   ⚠ 简写会把 background-image 重置回 none）；边框升纸缘色 --paper-edge。 */
.paper {
  background-color: var(--paper-bg);
  background-image: var(--paper-texture);
  border: 1px solid var(--paper-edge);
}

/* 发布遮罩：跟随纸面 token（原 bg-parchment-50/80 深色下又是白纱罩） */
.publish-veil {
  background: color-mix(in srgb, var(--paper-bg) 82%, transparent);
}

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
  /* 04 §A3-1 章号眉标化：小而疏的灰眉标——「第N章」从标签升格为书页眉 */
  font-size: var(--text-xs);
  font-weight: 500;
  letter-spacing: 0.22em;
  color: var(--text-muted);
}

.page-head__ornament {
  /* 04 §A3-2 章饰：左 ❦ + 右延细线（左对齐随标题；编辑器画布安静优先，符走纯装饰档） */
  display: flex;
  align-items: center;
  gap: var(--space-3);
  margin-top: var(--space-3);
  font-size: var(--text-xs);
  line-height: 1;
  color: var(--text-faint);
}
.page-head__ornament::after {
  content: '';
  flex: 1;
  height: 1px;
  background: var(--border-color);
}

.page-head__published {
  font-size: var(--text-xs);
  padding: 0 0.375rem;
  border-radius: 999px;
  background: color-mix(in srgb, var(--mint) 12%, transparent);
  color: var(--mint-ink);
  line-height: 1.4;
}

.page-head__words {
  font-size: var(--text-xs);
  color: var(--text-muted);
  font-variant-numeric: tabular-nums;
}

.page-head__save {
  font-size: var(--text-xs);
  color: var(--text-muted);
  opacity: 0.85;
}

.page-head__save--error {
  color: var(--danger);
  opacity: 1;
}

/* AI 状态件（08 期 §4.2 N9）：薄荷呼吸点 + 短句；脉冲 keyframes 全局既有（state-pill-pulse） */
.page-head__ai {
  display: inline-flex;
  align-items: center;
  gap: 0.375rem;
  font-size: var(--text-xs);
  color: var(--text-muted);
  white-space: nowrap;
}
.page-head__ai-dot {
  width: 6px;
  height: 6px;
  border-radius: 999px;
  background: var(--mint);
  animation: state-pill-pulse 1.6s ease-in-out infinite;
  flex-shrink: 0;
}
.page-head__ai--error {
  color: var(--danger);
}
.page-head__ai--error .page-head__ai-dot {
  background: var(--danger);
  animation: none;
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
  border-radius: var(--radius-sm);
  color: var(--text-muted);
  cursor: pointer;
  opacity: 0;
  transition: all var(--dur-2) var(--ease-out);
}
/* 平时收起，悬停纸面/焦点时浮现（画布安静优先） */
.paper:hover .page-head__menu-btn,
.page-head__menu-btn--open,
.page-head__menu-btn:focus-visible {
  opacity: 1;
}
.page-head__menu-btn:hover {
  background: var(--state-hover);
  color: var(--text-primary);
}

/* N2 §3.5：⋯菜单收编 .menu-shell/.menu-item 族——壳只留定位，项/分隔线/kbd 皮肤全交工具类 */
.action-menu {
  position: absolute;
  top: calc(100% + 4px);
  right: 0;
  z-index: var(--z-page-chrome); /* 归表：页内菜单带（原 30 表外值） */
  min-width: 10rem;
  display: flex;
  flex-direction: column;
}
.action-menu__item {
  /* 挂点：皮肤由 .menu-item 提供 */
}
.action-menu__item :deep(svg) {
  color: var(--text-muted);
  flex-shrink: 0;
}

.action-menu__divider {
  /* 挂点：皮肤由 .menu-sep 提供 */
}

/* 菜单里的键位提示（可发现性：点得到，也看得见 Ctrl+F） */
.action-menu__kbd {
  margin-left: auto;
  padding: 0 0.25rem;
  font-family: inherit;
  font-size: var(--text-xs);
  color: var(--text-muted);
}

.action-menu-enter-active {
  transition: opacity var(--dur-1) var(--ease-out), transform var(--dur-1) var(--ease-out);
}
.action-menu-leave-active {
  transition: opacity var(--dur-1) var(--ease-in), transform var(--dur-1) var(--ease-in);
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
  transition: border-color var(--dur-2) var(--ease-out);
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
