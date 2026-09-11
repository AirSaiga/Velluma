<script setup lang="ts">
/**
 * 写作台查找/替换条（Ctrl+F 唤起，2026-09-10）。
 *
 * 纸面右上浮出的单行条——「纸面常裸」纪律下不常驻：不搜时不存在，
 * Esc / × 即收，收后焦点回正文。
 *
 * Esc 不在这里处理：全局 Esc 栈统一剥皮（useEscStack，打开时由 RichTextEditor
 * 入栈），免得一次 Esc 被两处同时消费（关条 + 关助手面板）。
 *
 * 焦点：条是子组件、父级拿不到这里的 DOM，所以焦点由 `focusToken` 计数器下发
 * （每次唤起 +1）；挂载时 immediate 那一下负责首次聚焦。
 */
import { nextTick, ref, watch } from 'vue'
import Icon from '../../../components/Icon.vue'

const props = defineProps<{
  term: string
  replacement: string
  caseSensitive: boolean
  /** 「3/17」形态的命中位置；空词时为空串 */
  activeLabel: string
  matchCount: number
  /** 唤起计数器（+1 = 把焦点送回查找框并全选） */
  focusToken: number
}>()

const termInput = ref<HTMLInputElement | null>(null)

watch(
  () => props.focusToken,
  () => {
    nextTick(() => {
      termInput.value?.focus()
      termInput.value?.select()
    })
  },
  { immediate: true },
)

const emit = defineEmits<{
  'update:term': [value: string]
  'update:replacement': [value: string]
  toggleCase: []
  next: []
  prev: []
  replaceCurrent: []
  replaceAll: []
  close: []
}>()

function onTermInput(e: Event) {
  emit('update:term', (e.target as HTMLInputElement).value)
}
function onReplacementInput(e: Event) {
  emit('update:replacement', (e.target as HTMLInputElement).value)
}
/** 查找框里回车=下一条（Shift+回车=上一条）——不抢焦点、不动鼠标的标准手感 */
function onTermKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter') {
    e.preventDefault()
    if (e.shiftKey) emit('prev')
    else emit('next')
  }
}
function onReplacementKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter') {
    e.preventDefault()
    emit('replaceCurrent')
  }
}
</script>

<template>
  <div class="find-bar" role="search" aria-label="查找替换">
    <Icon name="magnifying-glass" :size="13" class="find-bar__glyph" />
    <input
      ref="termInput"
      :value="term"
      class="find-bar__input"
      type="text"
      placeholder="查找…"
      aria-label="查找内容"
      spellcheck="false"
      @input="onTermInput"
      @keydown="onTermKeydown"
    />
    <span class="find-bar__count" :class="{ 'find-bar__count--empty': term && !matchCount }" aria-live="polite">
      {{ activeLabel || '—' }}
    </span>
    <button class="find-bar__icon-btn" title="上一条（Shift+Enter）" :disabled="!matchCount" @click="emit('prev')">
      <Icon name="chevron-up" :size="13" />
    </button>
    <button class="find-bar__icon-btn" title="下一条（Enter）" :disabled="!matchCount" @click="emit('next')">
      <Icon name="chevron-down" :size="13" />
    </button>
    <button
      class="find-bar__icon-btn find-bar__case"
      :class="{ 'is-on': caseSensitive }"
      title="区分大小写"
      @click="emit('toggleCase')"
    >
      Aa
    </button>

    <span class="find-bar__divider" aria-hidden="true"></span>

    <input
      :value="replacement"
      class="find-bar__input"
      type="text"
      placeholder="替换为…"
      aria-label="替换内容"
      spellcheck="false"
      @input="onReplacementInput"
      @keydown="onReplacementKeydown"
    />
    <button class="find-bar__btn" :disabled="!matchCount" title="替换当前这一条（可 Ctrl+Z 反悔）" @click="emit('replaceCurrent')">
      替换
    </button>
    <button class="find-bar__btn" :disabled="!matchCount" title="替换全部（整批算一次撤销）" @click="emit('replaceAll')">
      全部
    </button>

    <button class="find-bar__icon-btn" title="收起（Esc）" @click="emit('close')">
      <Icon name="x-mark" :size="13" />
    </button>
  </div>
</template>

<style scoped>
.find-bar {
  position: absolute;
  top: var(--space-2);
  right: var(--space-3);
  z-index: var(--z-dock);
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--space-1);
  max-width: calc(100% - var(--space-6));
  padding: var(--space-1) var(--space-2);
  background: var(--bg-elevated);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  box-shadow: 0 8px 24px rgba(18, 38, 63, 0.1);
  font-size: var(--text-xs);
  color: var(--text-primary);
  line-height: var(--lh-compact);
}

.find-bar__glyph {
  color: var(--text-muted);
  flex-shrink: 0;
  margin-left: var(--space-1);
}

.find-bar__input {
  width: 11rem;
  padding: 0.1875rem var(--space-2);
  font-size: var(--text-xs);
  color: var(--text-primary);
  background: var(--bg-canvas);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-sm);
  outline: none;
}
.find-bar__input:focus {
  border-color: var(--accent-500);
}

.find-bar__count {
  min-width: 2.75rem;
  text-align: right;
  color: var(--text-muted);
  font-variant-numeric: tabular-nums;
}
.find-bar__count--empty {
  color: var(--danger);
}

.find-bar__icon-btn,
.find-bar__btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0.1875rem var(--space-2);
  font-size: var(--text-xs);
  color: var(--text-secondary);
  background: transparent;
  border: 1px solid transparent;
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: background 0.12s ease, color 0.12s ease;
}
.find-bar__icon-btn:hover:not(:disabled),
.find-bar__btn:hover:not(:disabled) {
  background: var(--hover-bg);
  color: var(--text-primary);
}
.find-bar__icon-btn:disabled,
.find-bar__btn:disabled {
  opacity: 0.35;
  cursor: not-allowed;
}
.find-bar__btn {
  border-color: var(--border-color);
}
.find-bar__case {
  font-weight: 600;
  letter-spacing: 0.02em;
}
.find-bar__case.is-on {
  color: var(--accent-600);
  border-color: var(--accent-400);
}

.find-bar__divider {
  width: 1px;
  height: 1rem;
  margin: 0 var(--space-1);
  background: var(--border-color);
}
</style>
