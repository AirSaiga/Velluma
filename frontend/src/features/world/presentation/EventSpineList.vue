<script setup lang="ts">
/**
 * 事件纵向时间轴（2026-09 外壳重构：外部抽屉特化排布）。
 *
 * 按年份分组的极简编年脊柱：sticky「第N年」分组头承担年份（卡内只显月日短格式，
 * 治旧 264px 浮层「类型名 + 全格式时刻 + 备注」挤成一团的截断），左侧竖线 + 事件
 * 圆点串珠。纯展示组件——排序/过滤在调用方（WorldView filteredEvents），交互
 * focus/edit/delete 原样上抛（全是既有 handler）。
 *
 * 韧性：time_start 恒为数值日计数（后端 nullable=False），同刻并列用 sequence_num
 * 稳定次级排序；time_end > time_start 的时长事件显示起讫区间。
 */
import { computed } from 'vue'
import Icon from '../../../components/Icon.vue'
import { EVENT_TYPE_COLOR, eventDisplayName } from '../engine/eventTemplates'
import { stripPointFromNote } from '../engine/eventPoint'
import { breakdownTime, formatDateShort, formatTime } from '../engine/timeFormat'
import type { WorldEvent } from '../engine/types'

const props = defineProps<{ events: WorldEvent[] }>()

const emit = defineEmits<{
  /** 整卡点击：定位到地图（与旧列表语义一致，地图联动不被备注展开牺牲） */
  focus: [ev: WorldEvent]
  edit: [ev: WorldEvent]
  delete: [ev: WorldEvent]
}>()

const eventLabel = (ev: WorldEvent) => eventDisplayName(ev)
const eventNote = (note: string) => stripPointFromNote(note)

interface SpineGroup {
  year: number
  items: WorldEvent[]
}
const groups = computed<SpineGroup[]>(() => {
  const sorted = [...props.events].sort(
    (a, b) => a.time_start - b.time_start || a.sequence_num - b.sequence_num,
  )
  const out: SpineGroup[] = []
  for (const ev of sorted) {
    const y = breakdownTime(ev.time_start).year
    const last = out[out.length - 1]
    if (last && last.year === y) last.items.push(ev)
    else out.push({ year: y, items: [ev] })
  }
  return out
})
</script>

<template>
  <div class="esp">
    <section v-for="g in groups" :key="g.year" class="esp-group">
      <header class="esp-year">
        <span class="esp-year-label">第{{ g.year }}年</span>
        <span class="esp-year-count">{{ g.items.length }}</span>
      </header>
      <ul class="esp-list">
        <li
          v-for="ev in g.items"
          :key="ev.id"
          class="esp-item"
          :title="`定位到地图 · ${formatTime(ev.time_start)}`"
          @click="emit('focus', ev)"
        >
          <span
            class="esp-dot"
            :style="{ background: EVENT_TYPE_COLOR[ev.event_type] || 'var(--text-muted)' }"
          ></span>
          <div class="esp-body">
            <div class="esp-head">
              <span class="esp-name">{{ eventLabel(ev) }}</span>
              <span class="esp-time">
                {{ formatDateShort(ev.time_start) }}<template v-if="ev.time_end > ev.time_start"> – {{ formatDateShort(ev.time_end) }}</template>
              </span>
            </div>
            <div v-if="eventNote(ev.note)" class="esp-note">{{ eventNote(ev.note) }}</div>
          </div>
          <div class="esp-actions">
            <button class="esp-act" title="编辑" @click.stop="emit('edit', ev)">
              <Icon name="pencil" :size="13" />
            </button>
            <button class="esp-act esp-act--danger" title="删除" @click.stop="emit('delete', ev)">
              <Icon name="trash" :size="13" />
            </button>
          </div>
        </li>
      </ul>
    </section>
  </div>
</template>

<style scoped>
.esp-group {
  margin-bottom: 4px;
}
/* sticky 年份头：滚动时钉在外壳滚动区顶（.ds-body），不随事件流滚走 */
.esp-year {
  position: sticky;
  top: 0;
  z-index: 2;
  display: flex;
  align-items: baseline;
  gap: 6px;
  padding: 6px 2px 5px;
  background: var(--bg-canvas);
  border-bottom: 1px solid var(--border-color);
}
.esp-year-label {
  font-size: var(--text-xs);
  font-weight: 700;
  letter-spacing: 0.08em;
  color: var(--text-muted);
  font-variant-numeric: tabular-nums;
}
.esp-year-count {
  font-size: var(--text-xs);
  color: var(--text-muted);
  opacity: 0.7;
}
.esp-list {
  list-style: none;
  display: flex;
  flex-direction: column;
}
/* 编年脊柱竖线：过圆点中心 */
.esp-list {
  position: relative;
}
.esp-list::before {
  content: '';
  position: absolute;
  left: 13px;
  top: 4px;
  bottom: 4px;
  width: 1px;
  background: var(--border-color);
}
.esp-item {
  position: relative;
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 7px 2px 7px 0;
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: background var(--dur-1) var(--ease-out);
}
.esp-item:hover {
  background: var(--state-hover);
}
.esp-dot {
  width: 8px;
  height: 8px;
  border-radius: 9999px;
  flex-shrink: 0;
  margin-top: 5px;
  margin-left: 10px;
  box-shadow: 0 0 0 3px var(--bg-canvas); /* 点压住竖线，留白与底同色断线 */
  z-index: 1;
}
.esp-body {
  flex: 1;
  min-width: 0;
}
.esp-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
  min-width: 0;
}
.esp-name {
  font-size: var(--text-base);
  font-weight: 600;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.esp-time {
  flex-shrink: 0;
  font-size: var(--text-xs);
  color: var(--text-muted);
  font-family: ui-monospace, monospace;
  font-variant-numeric: tabular-nums;
}
/* 备注：340px 全高抽屉下放宽到 3 行；全文走卡片 title 悬停 + 编辑表单 */
.esp-note {
  margin-top: 2px;
  font-size: var(--text-sm);
  color: var(--text-secondary);
  overflow: hidden;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
}
.esp-actions {
  display: flex;
  gap: 2px;
  flex-shrink: 0;
  opacity: 0;
  transition: opacity 0.15s;
}
.esp-item:hover .esp-actions,
.esp-item:focus-within .esp-actions {
  opacity: 1;
}
.esp-act {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  transition: all var(--dur-1) var(--ease-out);
}
.esp-act:hover {
  background: var(--state-hover);
  color: var(--text-primary);
}
.esp-act--danger {
  opacity: 0.45; /* 破坏性操作常态低显（02 期 §8 H1 规则三） */
}
.esp-act--danger:hover,
.esp-act--danger:focus-visible {
  opacity: 1;
  background: rgba(220, 38, 38, 0.08);
  color: var(--danger);
}
</style>
