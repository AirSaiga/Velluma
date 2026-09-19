<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { placeFloating } from '../shared/utils/floatGeometry'
import type { NodeViewProps } from '@tiptap/vue-3'

/**
 * 「问书」胶囊的 NodeView（04 下一阶段，镜像 OutlineNoteChip 家族）。
 *
 * 职责边界（NodeView 只管展示，不做编排）：
 * - 输入态：浮层单行输入问题，Enter 派发 velluma:ask-book（带节点 id），
 *   Esc 蒸发整颗胶囊；
 * - 答案态：监听 velluma:ask-book-answer（按 id 认领）——幽灵式浅字只读卡：
 *   答案 + 逐条出处（点击派发 velluma:ask-source 由容器导航），Esc 蒸发；
 *   永不可采纳、永不进正文（图书管理员不是合著者）。
 */
const props = defineProps<NodeViewProps>()

const open = ref(false)
const question = ref('')
const chipEl = ref<HTMLElement | null>(null)
const popEl = ref<HTMLElement | null>(null)
const inputEl = ref<HTMLInputElement | null>(null)
const popStyle = ref<{ top: string; left: string }>({ top: '0px', left: '0px' })
const state = ref<'editing' | 'loading' | 'answered'>('editing')
const answer = ref<{ kind: string; text: string; sources: Array<Record<string, unknown>> } | null>(null)

const noteId = () => String(props.node.attrs.id || '')

function updatePopPos() {
  const rect = chipEl.value?.getBoundingClientRect()
  if (!rect) return
  const result = placeFloating(
    { top: rect.top, left: rect.left, bottom: rect.bottom, right: rect.right },
    {
      width: popEl.value?.offsetWidth || 360,
      height: popEl.value?.offsetHeight || 160,
      gap: 6,
      margin: 12,
    },
    { width: window.innerWidth, height: window.innerHeight },
  )
  popStyle.value = { top: `${result.top}px`, left: `${result.left}px` }
}

function openPopover() {
  open.value = true
  if (props.node.attrs.editing) props.updateAttributes({ editing: false })
  nextTick(() => {
    updatePopPos()
    inputEl.value?.focus()
  })
}

function ask() {
  const q = question.value.trim()
  if (!q) {
    nextTick(() => inputEl.value?.focus())
    return
  }
  state.value = 'loading'
  window.dispatchEvent(new CustomEvent('velluma:ask-book', {
    detail: { question: q, noteId: noteId() },
  }))
  nextTick(updatePopPos)
}

function vaporize() {
  open.value = false
  props.deleteNode()
}

function onKeydown(e: KeyboardEvent) {
  e.stopPropagation()
  if (e.key === 'Escape') {
    e.preventDefault()
    vaporize()
  } else if (e.key === 'Enter' && !e.shiftKey && !e.isComposing && state.value === 'editing') {
    e.preventDefault()
    ask()
  }
}

function onAnswer(ev: Event) {
  const detail = (ev as CustomEvent<{ noteId: string; answer: typeof answer.value }>).detail
  if (!detail || detail.noteId !== noteId()) return
  answer.value = detail.answer || { kind: 'not_found', text: '没查到。', sources: [] }
  state.value = 'answered'
  nextTick(updatePopPos)
}

function goSource(source: Record<string, unknown>) {
  window.dispatchEvent(new CustomEvent('velluma:ask-source', { detail: { source } }))
}

function onDocMouseDown(e: MouseEvent) {
  if (!open.value) return
  const target = e.target as Node
  if (chipEl.value?.contains(target) || popEl.value?.contains(target)) return
  vaporize()
}

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

window.addEventListener('velluma:ask-book-answer', onAnswer as EventListener)
document.addEventListener('mousedown', onDocMouseDown)
window.addEventListener('resize', updatePopPos)
onBeforeUnmount(() => {
  window.removeEventListener('velluma:ask-book-answer', onAnswer as EventListener)
  document.removeEventListener('mousedown', onDocMouseDown)
  window.removeEventListener('resize', updatePopPos)
})
</script>

<template>
  <span
    ref="chipEl"
    class="ask-note"
    title="问书：查一个事实（Esc 蒸发，不进正文）"
    contenteditable="false"
    @mousedown.prevent
    @click="openPopover"
  >
    <span class="ask-note__icon">?</span>
    <span class="ask-note__text">{{ state === 'answered' ? '已答' : state === 'loading' ? '查书中…' : '问书' }}</span>
    <Teleport to="body">
      <div v-if="open" ref="popEl" class="ask-note-pop" :style="popStyle" contenteditable="false">
        <template v-if="state === 'editing'">
          <input
            ref="inputEl"
            v-model="question"
            class="ask-note-pop__input"
            maxlength="200"
            placeholder="问一个事实（例：明姐上次出场是什么时候？）"
            @keydown="onKeydown"
          />
          <div class="ask-note-pop__hint">只答书里的事实，不出主意 · Enter 问 · Esc 蒸发</div>
        </template>
        <template v-else-if="state === 'loading'">
          <div class="ask-note-pop__loading">查书中…</div>
        </template>
        <template v-else>
          <!-- 幽灵式浅字只读答案：不可采纳、不进正文；出处可点验（唯一跳走动作） -->
          <div class="ask-note-pop__answer">{{ answer?.text }}</div>
          <div v-if="answer?.sources?.length" class="ask-note-pop__sources">
            <button
              v-for="(s, i) in answer.sources.slice(0, 6)"
              :key="i"
              class="ask-note-pop__source"
              :title="`点验：${s.label}`"
              @click="goSource(s)"
            >{{ s.label }}</button>
          </div>
          <div class="ask-note-pop__hint">Esc 蒸发 · 答案不进正文</div>
        </template>
      </div>
    </Teleport>
  </span>
</template>
