<script setup lang="ts">
/**
 * 目录抽屉（08 期 §4.3，binder 的转世）——纯受控件：visible 与全部交互
 * 状态都在容器（WorkspaceView），本组件只渲染 + 抛事件。
 *
 * 内容 = 旧 binder 全量功能平移（零功能删除）：头部（返回书架 + 书名 + 多选）
 * → 多选全选栏 → 章节行列表（ChapterTocList）→ 多选批量栏 → 底部三钮
 * （新建章节 / 导入 .md / 提取设定）。
 *
 * 关闭路径：选中任一章（容器收）/ Esc（入 useEscStack）/ 外点（pointerdown
 * 落在抽屉、左缘书签与桌面区之外）/ 再点书签（容器收）。无 pin 模式。
 */
import { ref, watch, onBeforeUnmount } from 'vue'
import Icon from '../../../components/Icon.vue'
import ChapterTocList from './ChapterTocList.vue'
import { useEscStack } from '../../../composables/useEscStack'
import type { Chapter } from '../../../types'

const props = defineProps<{
  visible: boolean
  bookTitle: string
  chapters: Chapter[]
  selectedChapterId: string | null
  loading: boolean
  selectMode: boolean
  checkedIds: Set<string>
  allChecked: boolean
  batchDeleting: boolean
  /** 提取设定需有选中章（disabled 逻辑照抄旧 binder） */
  canExtract: boolean
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'back'): void
  (e: 'toggleSelectMode'): void
  (e: 'toggleCheckAll'): void
  (e: 'select', ch: Chapter, ev: MouseEvent | KeyboardEvent): void
  (e: 'delete', ch: Chapter): void
  (e: 'batchDelete'): void
  (e: 'exitSelectMode'): void
  (e: 'create'): void
  (e: 'import'): void
  (e: 'extract'): void
}>()

const rootEl = ref<HTMLElement | null>(null)

// Esc 入全局栈（一次 Esc 只关栈顶一层）；外点 = pointerdown 落在抽屉/书签之外。
// 落在桌面区（.workspace-view）之外的点击（模态/AppRail）不收——模态可能由抽屉按钮唤起。
const { push: pushEsc, remove: removeEsc } = useEscStack()
let _escId: symbol | null = null

function _onDocPointerDown(e: PointerEvent) {
  const t = e.target as HTMLElement | null
  if (!t) return
  if (rootEl.value && t instanceof Node && rootEl.value.contains(t)) return
  if (t.closest?.('.desk-spine')) return
  if (!t.closest?.('.workspace-view')) return
  emit('close')
}

watch(() => props.visible, (v) => {
  if (v) {
    if (!_escId) _escId = pushEsc(() => emit('close'), 'toc-drawer')
    document.addEventListener('pointerdown', _onDocPointerDown, true)
  } else {
    if (_escId) { removeEsc(_escId); _escId = null }
    document.removeEventListener('pointerdown', _onDocPointerDown, true)
  }
})

onBeforeUnmount(() => {
  if (_escId) { removeEsc(_escId); _escId = null }
  document.removeEventListener('pointerdown', _onDocPointerDown, true)
})
</script>

<template>
  <Transition name="toc-drawer">
    <aside v-if="visible" ref="rootEl" class="toc-drawer">
      <div class="toc-drawer__head">
        <button class="icon-btn-instrument" title="返回书架" @click="emit('back')">
          <Icon name="arrow-left" :size="15" />
        </button>
        <span class="toc-drawer__title" :title="bookTitle">{{ bookTitle || '未选择书籍' }}</span>
        <button
          class="icon-btn-instrument"
          :class="{ 'is-active': selectMode }"
          :title="selectMode ? '退出多选' : '多选删除'"
          @click="emit('toggleSelectMode')"
        >
          <Icon name="check-badge" :size="15" />
        </button>
        <button class="icon-btn-instrument" title="收起目录" @click="emit('close')">
          <Icon name="x-mark" :size="14" />
        </button>
      </div>

      <!-- 多选模式：全选栏 -->
      <div v-if="selectMode && !loading" class="select-all-bar" @click="emit('toggleCheckAll')">
        <span class="select-checkbox" :class="{ checked: allChecked }">
          <Icon v-if="allChecked" name="check" :size="12" />
        </span>
        <span class="select-all-label tnum">全选（{{ checkedIds.size }}/{{ chapters.length }}）</span>
      </div>

      <div v-if="loading" class="toc-drawer__loading">加载中…</div>
      <ChapterTocList
        v-else
        variant="drawer"
        :chapters="chapters"
        :selected-chapter-id="selectedChapterId"
        :select-mode="selectMode"
        :checked-ids="checkedIds"
        @select="(ch, ev) => emit('select', ch, ev)"
        @delete="(ch) => emit('delete', ch)"
      />

      <!-- 多选模式：批量操作栏（替换底部按钮区） -->
      <div v-if="selectMode" class="batch-actions">
        <span class="batch-count tnum">已选 {{ checkedIds.size }} 章</span>
        <div class="batch-btns">
          <button
            class="batch-delete-btn"
            :disabled="checkedIds.size === 0 || batchDeleting"
            @click="emit('batchDelete')"
          >            <Icon name="trash" :size="14" />
            <span>{{ batchDeleting ? '删除中…' : '删除选中' }}</span>
          </button>
          <button class="btn-ghost btn-ghost--sm" @click="emit('exitSelectMode')">
            <span>取消</span>
          </button>
        </div>
      </div>

      <div v-else class="toc-drawer__actions">
        <button class="toc-action-grow btn-primary-instrument" @click="emit('create')">
          <Icon name="plus" :size="14" />
          <span>新建章节</span>
        </button>
        <button class="toc-action-grow btn-ghost btn-ghost--sm" title="从 .md 文件批量导入章节" @click="emit('import')">
          <Icon name="arrow-up-tray" :size="14" />
          <span>导入 .md</span>
        </button>
        <button
          class="toc-action-grow btn-ghost btn-ghost--sm"
          title="从这一章的正文里认出角色、地点、伏笔，收进世界页"
          :disabled="!canExtract"
          @click="emit('extract')"
        >
          <Icon name="sparkles" :size="14" />
          <span>提取设定</span>
        </button>
      </div>
    </aside>
  </Transition>
</template>

<style scoped>
.toc-drawer__head {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  padding: 0.5rem 0.625rem;
  border-bottom: 1px solid var(--border-color);
  flex-shrink: 0;
}

.toc-drawer__title {
  flex: 1;
  font-size: 0.8125rem;
  font-weight: 600;
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.toc-drawer__loading {
  padding: 1rem;
  font-size: 0.75rem;
  color: var(--text-muted);
  text-align: center;
}

/* N3：头部 icon 钮收编 .icon-btn-instrument（style.css 组件层）；
   仅保留多选激活态覆盖（激活=accent 文字+tint 底，优先级高于工具类默认 muted） */
.icon-btn-instrument.is-active {
  color: var(--accent-500);
  background: color-mix(in srgb, var(--accent-500) 10%, transparent);
}

/* 多选：全选栏 */
.select-all-bar {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.4375rem 0.625rem;
  border-bottom: 1px solid var(--border-color);
  font-size: 0.75rem;
  color: var(--text-secondary);
  cursor: pointer;
  flex-shrink: 0;
  transition: background var(--dur-2) var(--ease-out);
}
.select-all-bar:hover {
  background: var(--state-hover);
}
.select-all-label {
  user-select: none;
}
.select-checkbox {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 1rem;
  height: 1rem;
  border: 1.5px solid var(--border-color);
  border-radius: var(--radius-xs);
  background: var(--bg-canvas);
  color: var(--bg-canvas);
  flex-shrink: 0;
  transition: all var(--dur-2) var(--ease-out);
}
.select-checkbox.checked {
  border-color: var(--accent-500);
  background: var(--accent-500);
}

/* 多选：批量操作栏 */
.batch-actions {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  padding: 0.75rem;
  border-top: 1px solid var(--border-color);
  background: var(--bg-tertiary);
  flex-shrink: 0;
}
.batch-count {
  font-size: 0.75rem;
  color: var(--text-secondary);
  text-align: center;
}
.batch-btns {
  display: flex;
  gap: 0.375rem;
}
/* N3 §3.1 danger：实底散写收编为「透明底+danger 文字/描边，hover 叠 8% 底」
   （仪器语言：实底保留给主信号钮；删除是危险信号但非本栏主行动） */
.batch-delete-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0.375rem;
  flex: 1;
  min-height: var(--control-h-sm);
  padding: 0 var(--control-px);
  background: transparent;
  color: var(--danger);
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  font-size: var(--text-xs);
  font-weight: 500;
  cursor: pointer;
  transition: color var(--dur-1) var(--ease-out), border-color var(--dur-1) var(--ease-out), background var(--dur-1) var(--ease-out);
}
.batch-delete-btn:hover:not(:disabled) {
  color: var(--danger);
  border-color: var(--danger);
  background: color-mix(in srgb, var(--danger) 8%, transparent);
}
.batch-delete-btn:active:not(:disabled) {
  background: color-mix(in srgb, var(--danger) 14%, transparent);
}
.batch-delete-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

/* 底部三钮 */
.toc-drawer__actions {
  display: flex;
  gap: 0.25rem;
  margin: 0.375rem;
  flex-shrink: 0;
}
/* 底部三钮（N3：皮肤由 .btn-primary-instrument / .btn-ghost--sm 提供；
   本类只做布局——三钮等分抽屉宽） */
.toc-action-grow {
  flex: 1;
}
</style>
