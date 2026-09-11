<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { worldApi } from '../../../services/api/domain/world.api'
import type { ContextCard } from '../../../services/api/domain/world.api'
import { formatTime } from '../../world/engine/timeFormat'
import { getTemplate } from '../../world/engine/eventTemplates'
import type { EventType } from '../../world/engine/types'
import { dispatchCollabEvent } from '../../../composables/collabEventBus'

/**
 * 情境浮卡（docs/world-writing-bridge.md W2 查询闭环）。
 *
 * 触发：选中文本（1-12 字，按名/别名解析）或点击 @/# 提及（实体 id 直取）。
 * 三秒动作：看一眼此刻状态 + 最近编年史（≤ 叙事时刻，防剧透），或深链跳世界页。
 * 解析不到（选中的不是已知实体/地点）→ 静默缺席（直接关闭，不打扰）。
 * 「记一笔」速记入口留给 W3。
 */
const props = defineProps<{
  bookId: string
  chapterId: string
  x: number
  y: number
  keyword: string
  entityId?: string | null
  entityKind?: 'character' | 'asset' | null
}>()

const emit = defineEmits<{ close: [] }>()

const router = useRouter()
const card = ref<ContextCard | null>(null)
const rootRef = ref<HTMLElement | null>(null)

onMounted(async () => {
  document.addEventListener('pointerdown', onOutsidePress, true)
  dispatchCollabEvent('context_card', { keyword: props.keyword })
  try {
    card.value = await worldApi.getContextCard(props.bookId, props.chapterId, {
      name: props.keyword,
      entity_id: props.entityId || undefined,
    })
  } catch {
    // 未解析到（404）或网络失败：静默缺席
    emit('close')
  }
})
onBeforeUnmount(() => {
  document.removeEventListener('pointerdown', onOutsidePress, true)
})

function onOutsidePress(e: PointerEvent) {
  if (rootRef.value && e.target instanceof Node && !rootRef.value.contains(e.target)) {
    emit('close')
  }
}

/** 视口内钳位（宽 ~280，高估 260） */
const pos = computed(() => {
  const left = Math.min(Math.max(8, props.x), Math.max(8, window.innerWidth - 292))
  const top = Math.min(Math.max(8, props.y), Math.max(8, window.innerHeight - 268))
  return { left, top }
})

const KIND_BADGES: Record<string, string> = {
  character: '角色',
  faction: '势力',
  asset: '资产',
  location: '地点',
}
const kindBadge = computed(() => KIND_BADGES[card.value?.entity_type || ''] || '实体')

const stateLine = computed(() => {
  if (!card.value) return ''
  const c = card.value
  if (c.kind === 'location') {
    return c.controlling_faction ? `${c.controlling_faction} 控制区` : ''
  }
  if (c.alive === null) return ''
  if (!c.alive) return '已死亡'
  const parts = [c.location_name ? `位于${c.location_name}` : '', c.label || '']
  return parts.filter(Boolean).join(' · ') || '有事态记录'
})

const chronicle = computed(() => {
  if (!card.value) return []
  return card.value.kind === 'entity' ? card.value.chronicle : card.value.recent_events
})

function eventLabel(type: string) {
  return getTemplate(type as EventType)?.label || type
}

function openInWorld() {
  if (!card.value) return
  const query: Record<string, string> = {
    time: String(card.value.t),
    from: 'chapter',
    chapter: props.chapterId,
  }
  if (card.value.kind === 'entity') query.entity = card.value.id
  else query.loc = card.value.id
  router.push({ path: `/world/${props.bookId}`, query })
  emit('close')
}

/** W3「记一笔」：唤起速记框并预填该实体名（velluma:quick-note 事件解耦） */
function quickNote() {
  if (!card.value) return
  window.dispatchEvent(
    new CustomEvent('velluma:quick-note', { detail: { keyword: card.value.name } }),
  )
  emit('close')
}
</script>

<template>
  <Teleport to="body">
    <!-- @pointerdown.prevent：阻止点击卡片引发编辑器选区塌缩（否则选区事件会
         在按钮 click 派发前把卡片关闭——「记一笔/在世界页打开」全部失效）；
         与既有选区菜单的 @mousedown.prevent 同一惯用法 -->
    <div
      ref="rootRef"
      class="wctx-card"
      :style="{ left: pos.left + 'px', top: pos.top + 'px' }"
      @pointerdown.prevent
    >
      <template v-if="card">
        <div class="wctx-head">
          <span class="wctx-badge" :class="{ loc: card.kind === 'location' }">{{ kindBadge }}</span>
          <span class="wctx-name">{{ card.name }}</span>
          <button class="wctx-close" title="关闭" @click="emit('close')">×</button>
        </div>
        <div v-if="stateLine" class="wctx-state">{{ stateLine }}</div>
        <div v-if="card.intro" class="wctx-intro">{{ card.intro }}</div>
        <div v-if="chronicle.length" class="wctx-chronicle">
          <div class="wctx-chronicle-title">{{ card.kind === 'entity' ? '编年史' : '此地事件' }}</div>
          <div v-for="(ev, i) in chronicle" :key="i" class="wctx-chronicle-row">
            <span class="wctx-chronicle-type">{{ eventLabel(ev.event_type) }}</span>
            <span class="wctx-chronicle-note">{{ ev.note || '—' }}</span>
            <span class="wctx-chronicle-time">{{ formatTime(ev.time_start) }}</span>
          </div>
        </div>
        <div v-else class="wctx-chronicle-empty">这个时间之前，还没有事情被记下</div>
        <div class="wctx-actions">
          <button class="wctx-link" @click="quickNote">记一笔</button>
          <button class="wctx-link" @click="openInWorld">在世界页打开 →</button>
        </div>
      </template>
      <div v-else class="wctx-loading">查询中…</div>
    </div>
  </Teleport>
</template>

<style scoped>
.wctx-card {
  position: fixed;
  z-index: 90;
  width: 280px;
  max-width: calc(100vw - 16px);
  background: var(--bg-panel, #fff);
  border: 1px solid var(--border-color);
  border-radius: 0.5rem;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.18);
  padding: 0.6rem 0.7rem;
  font-size: 0.78rem;
  color: var(--text-primary);
}
.wctx-head {
  display: flex;
  align-items: center;
  gap: 0.45rem;
}
.wctx-badge {
  flex-shrink: 0;
  font-size: 0.62rem;
  color: var(--accent-500);
  border: 1px solid var(--accent-500);
  border-radius: 999px;
  padding: 0.05rem 0.4rem;
}
.wctx-badge.loc {
  color: var(--text-muted);
  border-color: var(--border-color);
}
.wctx-name {
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.wctx-close {
  margin-left: auto;
  background: none;
  border: none;
  color: var(--text-muted);
  font-size: 1rem;
  cursor: pointer;
  line-height: 1;
  padding: 0 0.15rem;
}
.wctx-state {
  margin-top: 0.4rem;
  color: var(--accent-500);
  font-size: 0.72rem;
}
.wctx-intro {
  margin-top: 0.35rem;
  color: var(--text-muted);
  font-size: 0.72rem;
  line-height: 1.5;
}
.wctx-chronicle {
  margin-top: 0.5rem;
  border-top: 1px dashed var(--border-color);
  padding-top: 0.4rem;
}
.wctx-chronicle-title {
  font-size: 0.68rem;
  color: var(--text-muted);
  margin-bottom: 0.25rem;
}
.wctx-chronicle-row {
  display: flex;
  align-items: baseline;
  gap: 0.4rem;
  font-size: 0.7rem;
  padding: 0.12rem 0;
}
.wctx-chronicle-type {
  flex-shrink: 0;
  color: var(--accent-500);
}
.wctx-chronicle-note {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--text-primary);
}
.wctx-chronicle-time {
  flex-shrink: 0;
  color: var(--text-muted);
  font-size: 0.62rem;
}
.wctx-chronicle-empty {
  margin-top: 0.5rem;
  border-top: 1px dashed var(--border-color);
  padding-top: 0.4rem;
  font-size: 0.68rem;
  color: var(--text-muted);
  font-style: italic;
}
.wctx-actions {
  margin-top: 0.5rem;
  display: flex;
  justify-content: flex-end;
  gap: 0.3rem;
}
.wctx-link {
  background: none;
  border: none;
  color: var(--accent-500);
  font-size: 0.72rem;
  cursor: pointer;
  padding: 0.15rem 0.2rem;
}
.wctx-loading {
  color: var(--text-muted);
  font-size: 0.72rem;
  padding: 0.2rem 0;
}
</style>
