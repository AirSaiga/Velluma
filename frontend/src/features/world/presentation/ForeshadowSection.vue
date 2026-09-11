<script setup lang="ts">
/**
 * 伏笔账本侧栏分组（M5：伏笔全量列表——弧线带只渲染有锚的，这里是整本账全览）。
 *
 * 状态筛选 chips（全部/埋设中/已回收/已废弃 + 计数，语义沿用旧伏笔账本面板）；
 * 点击行 → emit select 开详情抽屉。数据源 useWorld.foreshadows（与弧线带同源），
 * 本组件只读——写动作集中在详情抽屉与时间轴弧线带。
 */
import { computed, nextTick, ref } from 'vue'
import Icon from '../../../components/Icon.vue'
import { useWorld } from '../composables/useWorld'
import { formatTime } from '../engine/timeFormat'
import type { Foreshadow } from '../engine/types'

const props = defineProps<{ bookId: string }>()

const emit = defineEmits<{ select: [foreshadowId: string] }>()

const { foreshadows, currentTime, createForeshadow } = useWorld()

const filter = ref<'all' | 'open' | 'closed' | 'dropped'>('all')

// ===== 手动埋设（空账本也不该是死路：落游标时刻，建成即开详情抽屉继续补） =====
const adding = ref(false)
const addDraft = ref('')
const addInputRef = ref<HTMLInputElement | null>(null)

async function startAdd() {
  adding.value = true
  await nextTick()
  addInputRef.value?.focus()
}

async function submitAdd() {
  const c = addDraft.value.trim()
  if (!c) {
    adding.value = false
    return
  }
  const f = await createForeshadow(props.bookId, { content: c, planted: currentTime.value })
  addDraft.value = ''
  adding.value = false
  emit('select', f.id)
}

const FILTER_OPTS = [
  { k: 'all', l: '全部' },
  { k: 'open', l: '埋设中' },
  { k: 'closed', l: '已回收' },
  { k: 'dropped', l: '已废弃' },
] as const

const counts = computed(() => ({
  all: foreshadows.value.length,
  open: foreshadows.value.filter((f) => f.status === 'open').length,
  closed: foreshadows.value.filter((f) => f.status === 'closed').length,
  dropped: foreshadows.value.filter((f) => f.status === 'dropped').length,
}))

const STATUS_RANK: Record<string, number> = { open: 0, closed: 1, dropped: 2 }

const shown = computed(() => {
  const list =
    filter.value === 'all'
      ? foreshadows.value
      : foreshadows.value.filter((f) => f.status === filter.value)
  // 埋设中优先，同状态按埋设时刻升序（未锚定排最后）
  return [...list].sort(
    (a, b) =>
      (STATUS_RANK[a.status] ?? 9) - (STATUS_RANK[b.status] ?? 9) ||
      (a.world_time_planted ?? Number.MAX_SAFE_INTEGER) -
        (b.world_time_planted ?? Number.MAX_SAFE_INTEGER),
  )
})

const TYPE_LABEL: Record<string, string> = { foreshadow: '伏笔', callback: '呼应', twist: '反转' }

function isAuto(f: Foreshadow): boolean {
  return f.meta?.source === 'setup_graph_auto' || f.meta?.source === 'detonation_chain'
}

/** 锚状态摘要：有锚显时刻区间，无锚显章锚或「未锚定」（未锚定的不上弧线带，这里是唯一可见处） */
function anchorText(f: Foreshadow): string {
  if (f.world_time_planted != null) {
    return f.world_time_resolved != null
      ? `${formatTime(f.world_time_planted)} → ${formatTime(f.world_time_resolved)}`
      : `埋于 ${formatTime(f.world_time_planted)}`
  }
  if (f.created_at_chapter) return `第 ${f.created_at_chapter} 章埋设 · 未锚定`
  return '未锚定'
}
</script>

<template>
  <div class="side-section">
    <div class="side-title">
      <Icon name="link" :size="13" />
      <span>伏笔</span>
      <span class="side-count">{{ counts.all }}</span>
    </div>

    <div v-if="counts.all" class="fs-filter">
      <button
        v-for="opt in FILTER_OPTS"
        :key="opt.k"
        class="fs-chip"
        :class="{ active: filter === opt.k }"
        @click="filter = opt.k"
      >
        {{ opt.l }} {{ counts[opt.k] }}
      </button>
    </div>

    <ul v-if="shown.length" class="side-list">
      <li
        v-for="f in shown"
        :key="f.id"
        class="side-card side-card--click fs-row"
        :class="`fs-row--${f.status}`"
        title="打开伏笔详情"
        @click="emit('select', f.id)"
      >
        <div class="sc-body">
          <div class="fs-head">
            <span class="fs-status" :class="f.status"></span>
            <span class="sc-name">{{ f.content }}</span>
            <span v-if="isAuto(f)" class="fs-auto" title="由 AI 自动登记">AI</span>
          </div>
          <div class="fs-meta">
            <span class="fs-type">{{ TYPE_LABEL[f.entry_type] || f.entry_type }}</span>
            <span class="fs-anchor" :class="{ 'fs-anchor--none': f.world_time_planted == null }">
              {{ anchorText(f) }}
            </span>
          </div>
        </div>
      </li>
    </ul>
    <div v-else-if="filter !== 'all'" class="side-empty">没有该状态的伏笔。</div>
    <div v-else class="side-empty">
      还没有伏笔——在下方埋第一条，或在时间轴上右键「埋伏笔」；写完章后 AI 也会登记。
    </div>

    <!-- 手动埋设：一句话 + Enter，落游标时刻（与旧面板「手动添加」同级能力） -->
    <div class="fs-add">
      <input
        v-if="adding"
        ref="addInputRef"
        v-model="addDraft"
        class="fs-add-input"
        placeholder="一句话写下这条伏笔（Enter 埋下 · Esc 取消）"
        @keydown.enter.prevent="submitAdd"
        @keydown.esc="((adding = false), (addDraft = ''))"
        @blur="submitAdd"
      />
      <button
        v-else
        class="fs-add-btn"
        :title="`在游标当前时刻（${formatTime(currentTime)}）埋下，建成后可继续编辑类型与锚`"
        @click="startAdd"
      >
        <Icon name="plus" :size="12" />
        埋一条伏笔
      </button>
    </div>
  </div>
</template>

<style scoped>
/* 与 WorldView 侧栏分组同语言（其样式 scoped 不可复用，这里复刻一份精简版） */
.side-section {
  padding: 0.375rem 0.625rem;
  border-bottom: 1px solid var(--border-color);
}

.side-title {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--text-secondary);
  padding: 0.25rem 0.125rem;
  user-select: none;
}

.side-count {
  margin-left: auto;
  font-size: var(--text-xs);
  color: var(--text-muted);
  font-family: ui-monospace, monospace;
}

.fs-filter {
  display: flex;
  flex-wrap: wrap;
  gap: 0.25rem;
  padding: 0.25rem 0 0.375rem;
}

.fs-chip {
  font-size: var(--text-xs);
  padding: 0.125rem 0.5rem;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 9999px;
  color: var(--text-muted);
  cursor: pointer;
  transition: all 0.12s ease;
}

.fs-chip:hover {
  color: var(--text-secondary);
}

.fs-chip.active {
  background: var(--accent-500);
  border-color: var(--accent-500);
  color: #fff;
}

.side-list {
  list-style: none;
  margin: 0;
  padding: 0.125rem 0 0.375rem;
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.side-card {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  padding: 0.375rem 0.5rem;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 0.375rem;
}

.side-card--click {
  cursor: pointer;
}

.side-card--click:hover {
  border-color: var(--accent-500);
}

.sc-body {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 0.125rem;
}

.fs-head {
  display: flex;
  align-items: center;
  gap: 0.375rem;
}

.fs-status {
  width: 0.4375rem;
  height: 0.4375rem;
  border-radius: 9999px;
  flex-shrink: 0;
}

.fs-status.open {
  background: #d97706;
}

.fs-status.closed {
  background: #16a34a;
}

.fs-status.dropped {
  background: var(--text-muted);
}

.fs-row--dropped .sc-name {
  text-decoration: line-through;
  color: var(--text-muted);
}

.sc-name {
  font-size: var(--text-base);
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.fs-auto {
  flex-shrink: 0;
  font-size: var(--text-xs);
  padding: 0.0625rem 0.3125rem;
  background: rgba(124, 106, 173, 0.12);
  color: var(--accent-500);
  border-radius: 0.1875rem;
}

.fs-meta {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  font-size: var(--text-xs);
  color: var(--text-muted);
}

.fs-type {
  flex-shrink: 0;
}

.fs-anchor {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-family: ui-monospace, monospace;
}

.fs-anchor--none {
  font-family: inherit;
  color: #d97706;
}

.side-empty {
  padding: 0.5rem 0.25rem 0.625rem;
  font-size: var(--text-xs);
  color: var(--text-muted);
  line-height: 1.6;
}

/* 手动埋设入口 */
.fs-add {
  padding: 0.125rem 0 0.375rem;
}

.fs-add-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 12px;
  font-size: var(--text-xs);
  font-family: inherit;
  color: var(--text-secondary);
  background: transparent;
  border: 1px dashed var(--border-color);
  border-radius: 7px;
  cursor: pointer;
  transition: all 0.12s ease;
}

.fs-add-btn:hover {
  border-color: var(--accent-500);
  color: var(--accent-500);
}

.fs-add-input {
  width: 100%;
  box-sizing: border-box;
  padding: 6px 9px;
  font-size: var(--text-sm);
  font-family: inherit;
  color: var(--text-primary);
  background: var(--bg-canvas);
  border: 1px solid var(--accent-500);
  border-radius: 7px;
  outline: none;
}
</style>
