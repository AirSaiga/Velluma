<script setup lang="ts">
/**
 * A5b 批量裁决模态（P5 §3.2）：「全部采纳」→ 逐条预览（可勾选剔除）→ 确认。
 *
 * 纯展示组件：勾选状态本组件自持（默认全选），确认时把选中 id 列表抛给宿主
 * （WorldSceneSlice 写作页收件箱 / WorldView 世界页待确认分区），执行与撤销
 * 逻辑在 features/world/composables/batchAccept.ts（两宿主共用同一份）。
 */
import { computed, ref, watch } from 'vue'
import ModalShell from '../../../components/ModalShell.vue'
import { getTemplate } from '../engine/eventTemplates'
import { displayCandidateTime } from '../engine/timeFormat'
import type { EventType } from '../engine/types'
import type { WorldEventCandidate } from '../../../services/api/domain/world.api'
import {
  initBatchSelection,
  toggleBatchSelection,
  selectedBatchIds,
  setAllBatchSelection,
} from '../composables/batchAccept'
import { inboxNavKey, moveInboxIndex, isToggleKey } from '../composables/inboxKeyboard'

const props = defineProps<{
  candidates: WorldEventCandidate[]
  /** 批次执行中（确认/取消禁用，按钮显示进度） */
  busy?: boolean
  /** 执行进度（done/total） */
  progress?: { done: number; total: number } | null
}>()

const emit = defineEmits<{
  /** 确认：抛剔除后的采纳名单（id 列表，保持展示顺序） */
  confirm: [ids: string[]]
  close: []
}>()

// 打开即全选（「全部采纳」语义），作者逐条剔除
const selection = ref(initBatchSelection(props.candidates))

const selectedIds = computed(() => selectedBatchIds(props.candidates, selection.value))
const allSelected = computed(
  () => props.candidates.length > 0 && selectedIds.value.length === props.candidates.length,
)

function toggle(id: string) {
  if (props.busy) return
  selection.value = toggleBatchSelection(selection.value, id)
}

function toggleAll() {
  if (props.busy) return
  selection.value = setAllBatchSelection(props.candidates, !allSelected.value)
}

function confirmBatch() {
  if (props.busy || selectedIds.value.length === 0) return
  emit('confirm', selectedIds.value)
}

// ---- 键盘批阅（02 候选回流修缮 M3）：↑↓ 移动 / Space 勾选剔除 / Enter 确认 ----
// 列表元素挂载后聚焦，模态内键盘动线即刻可用；Esc 仍走 ModalShell 既有路径
const listEl = ref<HTMLUListElement | null>(null)
const cursor = ref(0)
watch(
  () => props.candidates.length,
  (len) => { if (cursor.value >= len) cursor.value = Math.max(0, len - 1) },
)
watch(listEl, (el) => el?.focus())
function onListKeydown(ev: KeyboardEvent) {
  if (!props.candidates.length) return
  const nav = inboxNavKey(ev.key)
  if (nav !== 0) {
    ev.preventDefault()
    cursor.value = moveInboxIndex(cursor.value, nav, props.candidates.length)
    return
  }
  const c = props.candidates[cursor.value]
  if (isToggleKey(ev.key) && c) {
    ev.preventDefault()
    toggle(c.id)
    return
  }
  if (ev.key === 'Enter') {
    ev.preventDefault()
    confirmBatch()
  }
}

function typeLabel(c: WorldEventCandidate): string {
  if (c.source === 'canon_extract') return '◉ 真相候选'
  return getTemplate((c.draft?.event_type || 'custom') as EventType)?.label || c.draft?.event_type || '事件'
}

function titleOf(c: WorldEventCandidate): string {
  if (c.source === 'canon_extract') return c.draft?.label || '未命名真相'
  return c.draft?.summary || c.draft?.note || '（无摘要）'
}

function evidenceOf(c: WorldEventCandidate): string {
  return (c.draft as { evidence?: string } | undefined)?.evidence || ''
}

function metaOf(c: WorldEventCandidate): string {
  if (c.source === 'canon_extract') return '记入真相账本（草稿）'
  // t=0 = 无叙事锚无法推断——显示章节序（真实信息），不伪造「第1年1月1日」
  return displayCandidateTime(c.draft?.time_start || 0, c.chapter_number)
}
</script>

<template>
  <ModalShell
    title="批量采纳"
    :subtitle="`共 ${candidates.length} 条候选，已选 ${selectedIds.length} 条——取消勾选可剔除`"
    width="480px"
    @close="!busy && emit('close')"
  >
    <!-- 全选条 -->
    <div class="ba-selectall" @click="toggleAll">
      <span class="ba-check" :class="{ checked: allSelected }">{{ allSelected ? '☑' : '☐' }}</span>
      <span>{{ allSelected ? '全不选' : '全选' }}</span>
      <span class="ba-count">{{ selectedIds.length }}/{{ candidates.length }}</span>
    </div>

    <!-- 逐条预览（可剔除；↑↓ 选条 / 空格剔除 / 回车确认——键盘批阅动线） -->
    <ul ref="listEl" class="ba-list" tabindex="0" @keydown="onListKeydown">
      <li
        v-for="(c, i) in candidates"
        :key="c.id"
        class="ba-row"
        :class="{ off: !selection[c.id], cursor: i === cursor }"
        :title="evidenceOf(c) ? `原句：${evidenceOf(c)}` : undefined"
        @click="toggle(c.id)"
      >
        <span class="ba-check" :class="{ checked: selection[c.id] }">{{ selection[c.id] ? '☑' : '☐' }}</span>
        <span class="ba-body">
          <span class="ba-title">{{ titleOf(c) }}</span>
          <!-- 出处原句（02 修缮 M1）：后端已校验为正文逐字子串——逐条过目时的裁决依据 -->
          <span v-if="evidenceOf(c)" class="ba-evidence">「{{ evidenceOf(c) }}」</span>
          <span class="ba-meta">{{ typeLabel(c) }} · {{ metaOf(c) }}</span>
        </span>
      </li>
    </ul>

    <p class="ba-hint">每条下面的引文是正文原句（AI 依据的原话）；确认后 6 秒内可整批撤销。</p>

    <template #footer>
      <button class="ba-btn btn-ghost" :disabled="busy" @click="emit('close')">取消</button>
      <button class="ba-btn ba-btn--primary btn-primary-instrument" :disabled="busy || selectedIds.length === 0" @click="confirmBatch">
        <template v-if="busy">
          采纳中 {{ progress ? `${progress.done}/${progress.total}` : '…' }}
        </template>
        <template v-else>采纳选中（{{ selectedIds.length }}）</template>
      </button>
    </template>
  </ModalShell>
</template>

<style scoped>
.ba-selectall {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 8px;
  margin-bottom: 6px;
  font-size: var(--text-xs);
  color: var(--text-muted);
  cursor: pointer;
  border-radius: var(--radius-sm);
  user-select: none;
}
.ba-selectall:hover {
  background: var(--state-hover);
}
.ba-count {
  margin-left: auto;
  font-variant-numeric: tabular-nums;
}
.ba-check {
  color: var(--text-muted);
  font-size: var(--text-base);
  line-height: 1;
}
.ba-check.checked {
  color: var(--accent-500);
}
.ba-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
  max-height: 46vh;
  overflow-y: auto;
  outline: none;
}
.ba-list:focus-visible {
  outline: 1px solid var(--accent-400);
  outline-offset: 2px;
  border-radius: var(--radius-md);
}
.ba-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 7px 9px;
  border: 1px solid var(--line-faint);
  border-radius: var(--radius-md);
  cursor: pointer;
  user-select: none;
}
.ba-row:hover {
  border-color: var(--accent-400);
}
.ba-row.off {
  opacity: 0.5;
}
.ba-row.cursor {
  border-color: var(--accent-400);
  background: color-mix(in srgb, var(--accent-400) 8%, transparent);
}
.ba-evidence {
  font-size: var(--text-xs);
  color: var(--text-muted);
  line-height: 1.5;
  /* 原句最多两行——过目要快，超过两行的长句截断（完整句悬停 title 可见） */
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.ba-body {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.ba-title {
  font-size: var(--text-sm);
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.ba-meta {
  font-size: var(--text-xs);
  color: var(--text-muted);
}
.ba-hint {
  margin: 8px 0 0;
  font-size: var(--text-xs);
  line-height: 1.6;
  color: var(--text-muted);
}
.ba-btn {
  padding: 7px 16px;
  border-radius: var(--radius-md);
  color: var(--text-secondary);
  font-size: var(--text-sm);
  cursor: pointer;
}
.ba-btn:hover:not(:disabled) {
  border-color: var(--accent-500);
  color: var(--accent-500);
}
.ba-btn--primary {
}
.ba-btn--primary:hover:not(:disabled) {
  color: var(--bg-canvas);
  opacity: 0.92;
}
.ba-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
</style>
