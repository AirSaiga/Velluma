<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import type { NodeViewProps } from '@tiptap/vue-3'
import { spine } from '../features/workspace/composables/useChapterSpine'

/**
 * 「细纲」胶囊的 NodeView（仓库首个 NodeView）。
 *
 * 单一根元素 = 节点在文档中的 DOM（TipTap NodeView 要求单根）；
 * 编辑浮层经 Teleport 挂到 body，避免 textarea 嵌在 contenteditable 里。
 *
 * 职责边界（NodeView 只管展示与编辑，不做编排）：
 * - 展示：展开态胶囊（⚑ + 速记摘要）/ 塌缩态小钉（hover 显示速记）
 * - 编辑：浮层 textarea 改速记（keydown.stop 阻断冒泡进 ProseMirror/全局键位）
 * - 触发：「落笔扩写」只派发 velluma:outline-expand 事件（带节点 id），
 *   扩写编排（定位/上下文提取/幽灵锚点）归 useAdaptiveAssist
 */
const props = defineProps<NodeViewProps>()

const open = ref(false)
const draft = ref('')
const chipEl = ref<HTMLElement | null>(null)
const popEl = ref<HTMLElement | null>(null)
const textareaEl = ref<HTMLTextAreaElement | null>(null)
const popStyle = ref<{ top: string; left: string }>({ top: '0px', left: '0px' })

const noteText = computed(() => String(props.node.attrs.note || ''))
const collapsed = computed(() => !!props.node.attrs.collapsed)
const anchorId = computed(() => String(props.node.attrs.anchorId || ''))

/** 可挂的谋篇锚点（P1.4 M3：pending/未划掉的；无脉络时空列表） */
const pendingAnchors = computed(() =>
  (spine.value?.anchors || []).filter((a) => a.status !== 'dropped'),
)
const anchorLabel = computed(
  () => pendingAnchors.value.find((a) => a.id === anchorId.value)?.text || '',
)

function setAnchor(id: string) {
  props.updateAttributes({ anchorId: id })
}

/** 从速记里解析目标字数提示（「约300字」→「300 字」），解析不出给默认 */
const targetHint = computed(() => {
  const m = /约?\s*(\d+)\s*字/.exec(noteText.value)
  return m ? `${m[1]} 字` : '默认 400 字'
})

function updatePopPos() {
  const rect = chipEl.value?.getBoundingClientRect()
  if (!rect) return
  popStyle.value = {
    top: `${rect.bottom + 6}px`,
    left: `${Math.max(12, Math.min(rect.left, window.innerWidth - 340))}px`,
  }
}

function openPopover() {
  draft.value = noteText.value
  open.value = true
  if (props.node.attrs.editing) props.updateAttributes({ editing: false })
  nextTick(() => {
    updatePopPos()
    textareaEl.value?.focus()
  })
}

function saveNote() {
  const text = draft.value.trim()
  if (text && text !== noteText.value) props.updateAttributes({ note: text })
}

function closePopover() {
  saveNote()
  open.value = false
}

function emitExpand() {
  const text = draft.value.trim() || noteText.value
  if (!text) {
    // 空速记不触发扩写，聚焦输入
    nextTick(() => textareaEl.value?.focus())
    return
  }
  if (text !== noteText.value) props.updateAttributes({ note: text })
  open.value = false
  window.dispatchEvent(
    new CustomEvent('velluma:outline-expand', { detail: { id: String(props.node.attrs.id || '') } }),
  )
}

function onKeydown(e: KeyboardEvent) {
  // 不冒泡：否则 ProseMirror / 全局写作键位会吃掉浮层输入
  e.stopPropagation()
  if (e.key === 'Escape') {
    e.preventDefault()
    closePopover()
  } else if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
    e.preventDefault()
    emitExpand()
  }
}

function onDocMouseDown(e: MouseEvent) {
  if (!open.value) return
  const target = e.target as Node
  if (chipEl.value?.contains(target) || popEl.value?.contains(target)) return
  closePopover()
}

// 新建/插入时（attrs.editing=true）自动打开浮层
watch(
  () => props.node.attrs.editing,
  (v) => {
    if (v) openPopover()
  },
  { immediate: true },
)
watch(open, (v) => {
  if (v) updatePopPos()
})

document.addEventListener('mousedown', onDocMouseDown)
window.addEventListener('resize', updatePopPos)
onBeforeUnmount(() => {
  document.removeEventListener('mousedown', onDocMouseDown)
  window.removeEventListener('resize', updatePopPos)
})
</script>

<template>
  <span
    ref="chipEl"
    class="outline-note"
    :class="{ 'outline-note--collapsed': collapsed }"
    :title="collapsed ? noteText : ''"
    contenteditable="false"
    @mousedown.prevent
    @click="openPopover"
  >
    <span class="outline-note__icon">⚑</span>
    <span v-if="!collapsed && noteText" class="outline-note__text">{{ noteText }}</span>
    <span v-else-if="!collapsed" class="outline-note__text outline-note__text--empty">写细纲…</span>
    <!-- 挂的谋篇锚点小签（P1.4 M3：这段速记服务于哪个锚点） -->
    <span v-if="anchorLabel" class="outline-note__anchor" title="这段服务于打算页列的情节">{{ anchorLabel }}</span>
    <Teleport to="body">
      <div v-if="open" ref="popEl" class="outline-note-pop" :style="popStyle" contenteditable="false">
        <textarea
          ref="textareaEl"
          v-model="draft"
          class="outline-note-pop__input"
          rows="3"
          placeholder="这段要发生什么？（例：打一架，她退缩，约300字）"
          @keydown="onKeydown"
        ></textarea>
        <div class="outline-note-pop__hint">扩写目标 {{ targetHint }} · Enter 落笔扩写 · Esc 收起</div>
        <!-- 锚点选择（P1.4 M3 三锚定：服务于谋篇锚点的胶囊，扩写时锚点文本注入意图） -->
        <div v-if="pendingAnchors.length" class="outline-note-pop__anchors">
          <span class="outline-note-pop__anchors-label">服务于哪条情节</span>
          <button
            class="outline-note-pop__anchor-opt"
            :class="{ 'is-on': !anchorId }"
            @click="setAnchor('')"
          >—</button>
          <button
            v-for="a in pendingAnchors"
            :key="a.id"
            class="outline-note-pop__anchor-opt"
            :class="{ 'is-on': a.id === anchorId }"
            :title="a.text"
            @click="setAnchor(a.id)"
          >{{ a.text }}</button>
        </div>
        <div class="outline-note-pop__actions">
          <button class="outline-note-pop__btn outline-note-pop__btn--danger" @click="props.deleteNode()">删除</button>
          <button class="outline-note-pop__btn outline-note-pop__btn--primary" @click="emitExpand()">落笔扩写</button>
        </div>
      </div>
    </Teleport>
  </span>
</template>
