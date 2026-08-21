<script setup lang="ts">
/**
 * A5b 批量裁决模态（P5 §3.2）：「全部采纳」→ 逐条预览（可勾选剔除）→ 确认。
 *
 * 纯展示组件：勾选状态本组件自持（默认全选），确认时把选中 id 列表抛给宿主
 * （WorldSceneSlice 写作页收件箱 / WorldView 世界页待确认分区），执行与撤销
 * 逻辑在 features/world/composables/batchAccept.ts（两宿主共用同一份）。
 */
import { computed, ref } from 'vue'
import ModalShell from './ModalShell.vue'
import { getTemplate } from '../engine/eventTemplates'
import { formatTime } from '../engine/timeFormat'
import type { EventType } from '../engine/types'
import type { WorldEventCandidate } from '../../../services/api/domain/world.api'
import {
  initBatchSelection,
  toggleBatchSelection,
  selectedBatchIds,
  setAllBatchSelection,
} from '../composables/batchAccept'

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

function typeLabel(c: WorldEventCandidate): string {
  if (c.source === 'canon_extract') return '◉ 真相候选'
  return getTemplate((c.draft?.event_type || 'custom') as EventType)?.label || c.draft?.event_type || '事件'
}

function titleOf(c: WorldEventCandidate): string {
  if (c.source === 'canon_extract') return c.draft?.label || '未命名真相'
  return c.draft?.summary || c.draft?.note || '（无摘要）'
}

function metaOf(c: WorldEventCandidate): string {
  if (c.source === 'canon_extract') return '记入真相账本（草稿）'
  return formatTime(c.draft?.time_start || 0)
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

    <!-- 逐条预览（可剔除） -->
    <ul class="ba-list">
      <li
        v-for="c in candidates"
        :key="c.id"
        class="ba-row"
        :class="{ off: !selection[c.id] }"
        @click="toggle(c.id)"
      >
        <span class="ba-check" :class="{ checked: selection[c.id] }">{{ selection[c.id] ? '☑' : '☐' }}</span>
        <span class="ba-body">
          <span class="ba-title">{{ titleOf(c) }}</span>
          <span class="ba-meta">{{ typeLabel(c) }} · {{ metaOf(c) }}</span>
        </span>
      </li>
    </ul>

    <p class="ba-hint">✓ 后立即生效（真相候选进真相账本）；确认后 6 秒内可整批撤销。</p>

    <template #footer>
      <button class="ba-btn" :disabled="busy" @click="emit('close')">取消</button>
      <button class="ba-btn ba-btn--primary" :disabled="busy || selectedIds.length === 0" @click="confirmBatch">
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
  font-size: 12px;
  color: var(--text-muted);
  cursor: pointer;
  border-radius: 6px;
  user-select: none;
}
.ba-selectall:hover {
  background: var(--hover-bg);
}
.ba-count {
  margin-left: auto;
  font-variant-numeric: tabular-nums;
}
.ba-check {
  color: var(--text-muted);
  font-size: 14px;
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
}
.ba-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 7px 9px;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  cursor: pointer;
  user-select: none;
}
.ba-row:hover {
  border-color: var(--accent-400, #9685c2);
}
.ba-row.off {
  opacity: 0.5;
}
.ba-body {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.ba-title {
  font-size: 13px;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.ba-meta {
  font-size: 11px;
  color: var(--text-muted);
}
.ba-hint {
  margin: 8px 0 0;
  font-size: 11px;
  line-height: 1.6;
  color: var(--text-muted);
}
.ba-btn {
  padding: 7px 16px;
  border-radius: 8px;
  border: 1px solid var(--border-color);
  background: transparent;
  color: var(--text-secondary);
  font-size: 13px;
  cursor: pointer;
}
.ba-btn:hover:not(:disabled) {
  border-color: var(--accent-500);
  color: var(--accent-500);
}
.ba-btn--primary {
  background: var(--accent-500);
  border-color: var(--accent-500);
  color: #fff;
}
.ba-btn--primary:hover:not(:disabled) {
  color: #fff;
  opacity: 0.92;
}
.ba-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
</style>
