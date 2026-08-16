<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useAppStore } from '../../app/useAppStore'
import { useWorldSlice } from '../../world/composables/useWorldSlice'
import { formatTime, breakdownTime, fromYMD } from '../../world/engine/timeFormat'
import { getTemplate } from '../../world/engine/eventTemplates'
import type { EventType } from '../../world/engine/types'
import type { WorldEventCandidate } from '../../../services/api/domain/world.api'
import { loadUiPrefs, saveUiPrefs } from '../../../composables/useUiPrefs'

/**
 * 「此刻此地」世界切片条（docs/world-writing-bridge.md W1/W4/W5-lite，替换 SceneSettingsPanel）。
 *
 * 数据源 GET /world/scene-slice——与生成辅助（settings_bundle 世界优先桥接）共用
 * 同一份叙事时间解析与事件推演。被动呈现为主（在场/脚下/头顶的线/相遇提示），
 * 主动动作：改本章叙事锚、钉场景、确认候选回流（✓/✗ + 撤销胶囊）、跳世界页。
 * 空间编辑永远在世界页（深链带时刻与往返参数）。
 */
const props = defineProps<{
  chapterId: string | null
}>()

const store = useAppStore()
const router = useRouter()
const currentBookId = store.currentBookId
const {
  slice,
  candidates,
  loading,
  updated,
  load,
  setNarrativeTime,
  setScenePin,
  acceptCandidate,
  rejectCandidate,
  undoAccept,
  acknowledgeUpdate,
} = useWorldSlice()

watch(
  () => props.chapterId,
  (newId) => {
    if (newId && currentBookId.value) load(currentBookId.value, newId)
  },
  { immediate: true },
)

// ---- 折叠（UiPrefs 记忆）----
const collapsed = ref(loadUiPrefs().worldSliceCollapsed)
function toggleCollapsed() {
  collapsed.value = !collapsed.value
  saveUiPrefs({ ...loadUiPrefs(), worldSliceCollapsed: collapsed.value })
}

// ---- 读者视角滤镜（W5-lite：隐藏 private 实体与作者层伏笔——自检揭示节奏）----
const readerView = ref(loadUiPrefs().worldReaderView)
function toggleReaderView() {
  readerView.value = !readerView.value
  saveUiPrefs({ ...loadUiPrefs(), worldReaderView: readerView.value })
}
const presenceView = computed(() =>
  readerView.value ? (slice.value?.presence || []).filter((p) => p.visibility === 'public') : slice.value?.presence || []
)

// ---- 时刻来源徽标 ----
const SOURCE_LABELS: Record<string, { label: string; hint: string }> = {
  chapter_anchor: { label: '本章锚', hint: '本章已锚定叙事时间（时间轴右键或此处「改」）' },
  prev_anchor: { label: '承前章', hint: '沿用前序最近已锚章节的叙事时间' },
  max_event: { label: '事件最远', hint: '未锚定，按世界事件流最大时刻推演' },
  zero: { label: '世界起点', hint: '世界尚无事件记录，从起点推演' },
}
const sourceInfo = computed(() => SOURCE_LABELS[slice.value?.t_source || 'zero'] || SOURCE_LABELS.zero)

// ---- 本章时刻编辑（叙事锚 = 切片内容的螺丝）----
const editingTime = ref(false)
const timeDraft = ref('0')
const draftYmd = computed(() => {
  const n = Math.max(0, Math.floor(Number(timeDraft.value) || 0))
  return breakdownTime(n)
})
const timePreview = computed(() => {
  const ymd = draftYmd.value
  return formatTime(fromYMD(ymd.year, ymd.month, ymd.day))
})
function openTimeEditor() {
  timeDraft.value = String(slice.value?.t ?? 0)
  editingTime.value = true
}
async function applyTime() {
  if (!props.chapterId || !currentBookId.value) return
  const t = Math.max(0, Math.floor(Number(timeDraft.value) || 0))
  editingTime.value = false
  await setNarrativeTime(currentBookId.value, props.chapterId, t)
}
async function clearAnchor() {
  if (!props.chapterId || !currentBookId.value) return
  editingTime.value = false
  await setNarrativeTime(currentBookId.value, props.chapterId, null)
}

// ---- 场景钉（W5-lite）----
async function pinScene() {
  if (!props.chapterId || !currentBookId.value || !slice.value?.scene) return
  await setScenePin(currentBookId.value, props.chapterId, slice.value.scene.location_id)
}
async function unpinScene() {
  if (!props.chapterId || !currentBookId.value) return
  await setScenePin(currentBookId.value, props.chapterId, null)
}

// ---- 展示截断（每块 ≤2，超出计数跳世界页）----
const foreshadowsShown = computed(() => (slice.value?.foreshadows || []).slice(0, 2))
const expectationsShown = computed(() => (slice.value?.expectations || []).slice(0, 2))

// ---- W4 候选回流收件箱（本章 pending 池）----
const inboxOpen = ref(false)
const busyCandidateId = ref<string | null>(null)
const undoCapsule = ref<{ candidateId: string; eventId: string; label: string } | null>(null)
let capsuleTimer: number | null = null

async function onAccept(c: WorldEventCandidate) {
  if (!currentBookId.value || busyCandidateId.value) return
  busyCandidateId.value = c.id
  try {
    const r = await acceptCandidate(currentBookId.value, c.id)
    if (r) {
      undoCapsule.value = { candidateId: c.id, eventId: r.eventId, label: r.label }
      if (capsuleTimer) window.clearTimeout(capsuleTimer)
      capsuleTimer = window.setTimeout(() => (undoCapsule.value = null), 6000)
    }
  } finally {
    busyCandidateId.value = null
  }
}
async function onReject(c: WorldEventCandidate) {
  if (!currentBookId.value || busyCandidateId.value) return
  busyCandidateId.value = c.id
  try {
    await rejectCandidate(currentBookId.value, c.id)
  } finally {
    busyCandidateId.value = null
  }
}
async function undoLastAccept() {
  if (!undoCapsule.value || !currentBookId.value) return
  const { candidateId, eventId } = undoCapsule.value
  undoCapsule.value = null
  if (capsuleTimer) window.clearTimeout(capsuleTimer)
  await undoAccept(currentBookId.value, candidateId, eventId)
}

function eventLabelOf(type: string) {
  return getTemplate(type as EventType)?.label || type
}

function ack() {
  acknowledgeUpdate()
}

/** 跳世界页（W2 深链：游标停本章时刻 + from=chapter 支持一键返回；带实体 id 时飞到该对象；
 *  M5：extra 支持 ?fs= 伏笔详情 / ?panel=expectations 期待账本） */
function goWorld(entityId?: string, extra?: Record<string, string>) {
  if (!currentBookId.value) return
  const query: Record<string, string> = {}
  if (slice.value) {
    query.time = String(slice.value.t)
    query.from = 'chapter'
    if (props.chapterId) query.chapter = props.chapterId
  }
  if (entityId) query.entity = entityId
  Object.assign(query, extra || {})
  router.push({ path: `/world/${currentBookId.value}`, query })
}
</script>

<template>
  <div class="world-scene-slice">
    <div v-if="!chapterId" class="empty">
      <p>从左侧选择一个章节。</p>
    </div>
    <template v-else>
      <!-- 世界页无实体（旧表兜底书）：迁移引导（继承旧面板） -->
      <div v-if="slice?.world_empty && !loading" class="usage-hint">
        <p>本书尚未在世界页建立设定。「此刻此地」由世界页的事件按叙事时间推演，与 AI 生成吃同一份数据。</p>
        <button class="go-world-btn" @click="goWorld()">前往世界页</button>
      </div>

      <template v-else-if="slice">
        <header class="slice-header" @click="toggleCollapsed">
          <span class="slice-title">此刻此地</span>
          <span class="slice-time">{{ formatTime(slice.t) }}</span>
          <span class="source-badge" :title="sourceInfo.hint">{{ sourceInfo.label }}</span>
          <button
            class="reader-toggle"
            :class="{ on: readerView }"
            title="读者视角：隐藏作者已知（private）的实体与伏笔——自检揭示节奏"
            @click.stop="toggleReaderView"
          >
            读者视角
          </button>
          <button v-if="updated" class="update-dot" title="世界页数据已变化，切片已刷新" @click.stop="ack">
            世界有更新
          </button>
          <span class="chevron" :class="{ open: !collapsed }">▾</span>
        </header>

        <!-- 本章时刻编辑（叙事锚） -->
        <div v-if="editingTime" class="time-editor" @click.stop>
          <label>
            世界日数
            <input v-model="timeDraft" type="number" min="0" step="1" />
          </label>
          <span class="time-preview">{{ timePreview }}</span>
          <div class="time-actions">
            <button class="mini-btn primary" @click="applyTime">锚定</button>
            <button
              v-if="slice.t_source === 'chapter_anchor'"
              class="mini-btn"
              title="清除本章叙事锚，回落到前序章/事件推演"
              @click="clearAnchor"
            >
              清除锚
            </button>
            <button class="mini-btn" @click="editingTime = false">取消</button>
          </div>
        </div>
        <div v-else class="time-edit-row">
          <button class="link-btn" title="锚定本章发生的世界时刻（切片内容随之变化）" @click="openTimeEditor">
            改
          </button>
        </div>

        <div v-show="!collapsed" class="slice-body">
          <!-- 在场 -->
          <section class="setting-group">
            <div class="setting-group-label">在场<span class="muted">事件推演 · 与生成同源</span></div>
            <div v-if="!presenceView.length" class="empty-hint">
              世界页还没有本章时刻的事态——去录移动/出生等事件，或先锚定本章叙事时间。
            </div>
            <ul v-else class="presence-list">
              <li
                v-for="row in presenceView"
                :key="row.entity_id"
                class="presence-row clickable"
                :class="{ dead: !row.alive }"
                title="在世界页打开（游标停在本章时刻）"
                @click="goWorld(row.entity_id)"
              >
                <span class="presence-name">{{ row.name }}</span>
                <span class="presence-where">
                  <template v-if="!row.alive">已死亡</template>
                  <template v-else-if="row.location_name">位于{{ row.location_name }}</template>
                  <template v-else>位置未知</template>
                  <template v-if="row.label && row.alive"> · {{ row.label }}</template>
                </span>
              </li>
            </ul>
          </section>

          <!-- 脚下 -->
          <section v-if="slice.scene" class="setting-group">
            <div class="setting-group-label">
              脚下
              <button
                class="pin-btn"
                :title="slice.scene.pinned ? '取消钉定，回落事件/在场推演' : '钉定本章地点（优先于推演）'"
                @click="slice.scene.pinned ? unpinScene() : pinScene()"
              >
                {{ slice.scene.pinned ? '📌 已钉 · 取消' : '钉住' }}
              </button>
            </div>
            <div class="scene-row">
              {{ slice.scene.name }}
              <span v-if="slice.scene.controlling_faction" class="faction-tag">
                {{ slice.scene.controlling_faction }} 控制区
              </span>
            </div>
          </section>

          <!-- 相遇提示（W5-lite：同地角色的戏剧机会） -->
          <section v-if="!readerView && slice.encounters?.length" class="setting-group">
            <div class="setting-group-label">相遇</div>
            <div v-for="(enc, i) in slice.encounters" :key="i" class="encounter-row">
              {{ enc.names.join(' × ') }}<span class="encounter-loc"> · {{ enc.location_name }}</span>
            </div>
          </section>

          <!-- 头顶的线（读者视角下伏笔=作者层，隐藏） -->
          <section
            v-if="!readerView && (slice.foreshadows.length || slice.expectations.length)"
            class="setting-group"
          >
            <div class="setting-group-label">头顶的线</div>
            <ul class="thread-list">
              <li
                v-for="f in foreshadowsShown"
                :key="f.ledger_key"
                class="thread-row foreshadow clickable"
                title="在世界页打开这条伏笔（详情抽屉）"
                @click="goWorld(undefined, { fs: f.ledger_key })"
              >
                <span class="thread-tag">伏笔</span>
                <span class="thread-text">{{ f.content }}</span>
                <span v-if="f.chapters_open != null" class="thread-meta">悬空 {{ f.chapters_open }} 章</span>
              </li>
              <li
                v-for="(e, i) in expectationsShown"
                :key="i"
                class="thread-row expectation clickable"
                title="在世界页打开期待账本"
                @click="goWorld(undefined, { panel: 'expectations' })"
              >
                <span class="thread-tag">期待</span>
                <span class="thread-text">{{ e.description }}</span>
                <span class="thread-meta">张力 {{ e.tension }}</span>
              </li>
            </ul>
            <div
              v-if="slice.foreshadows.length > 2 || slice.expectations.length > 2"
              class="more-hint"
              @click="goWorld()"
            >
              更多线索在世界页 »
            </div>
          </section>

          <!-- W4 候选回流收件箱（本章变化） -->
          <section v-if="candidates.length" class="setting-group inbox">
            <div class="setting-group-label inbox-head" @click="inboxOpen = !inboxOpen">
              <span class="inbox-badge">{{ candidates.length }}</span>
              本章带来的世界变化
              <span class="chevron small" :class="{ open: inboxOpen }">▾</span>
            </div>
            <ul v-show="inboxOpen" class="inbox-list">
              <li v-for="c in candidates" :key="c.id" class="inbox-row">
                <span class="inbox-type">{{ eventLabelOf(c.draft?.event_type || 'custom') }}</span>
                <span class="inbox-text">{{ c.draft?.summary || c.draft?.note || '（无摘要）' }}</span>
                <span class="inbox-meta">{{ formatTime(c.draft?.time_start || 0) }}</span>
                <span class="inbox-actions">
                  <button
                    class="inbox-btn ok"
                    :disabled="busyCandidateId === c.id"
                    title="转正入账（进入事件推演）"
                    @click="onAccept(c)"
                  >
                    ✓
                  </button>
                  <button
                    class="inbox-btn no"
                    :disabled="busyCandidateId === c.id"
                    title="丢弃（留痕，不进视图）"
                    @click="onReject(c)"
                  >
                    ✗
                  </button>
                </span>
              </li>
            </ul>
            <div v-show="!inboxOpen" class="inbox-hint" @click="inboxOpen = true">
              来自沉淀/完稿的抽取，✓ 后进入世界推演
            </div>
          </section>

          <div class="usage-hint">
            <p>在场与位置由世界页事件推演；想改变此刻，去世界页录事件、Alt+N 速记一句话，或拖动时间轴。</p>
            <button class="go-world-btn subtle" @click="goWorld()">打开世界页</button>
          </div>
        </div>
      </template>

      <div v-else-if="loading" class="empty">
        <p>推演中…</p>
      </div>
    </template>

    <!-- 撤销胶囊（✓ 转正后 6 秒可撤：删事件 + 候选回 pending） -->
    <Teleport to="body">
      <div v-if="undoCapsule" class="undo-capsule">
        <span>已入账：{{ undoCapsule.label }}</span>
        <button class="undo-btn" @click="undoLastAccept">撤销</button>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.world-scene-slice {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  height: 100%;
  overflow-y: auto;
}

.empty {
  padding: 2rem 1rem;
  text-align: center;
  color: var(--text-muted);
}

.slice-header {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  cursor: pointer;
  user-select: none;
  padding: 0.35rem 0.25rem;
  border-bottom: 1px solid var(--border-color);
}
.slice-title {
  font-weight: 600;
  color: var(--text-primary);
  font-size: 0.85rem;
}
.slice-time {
  color: var(--accent-500);
  font-size: 0.8rem;
}
.source-badge {
  font-size: 0.65rem;
  color: var(--text-muted);
  border: 1px solid var(--border-color);
  border-radius: 999px;
  padding: 0.05rem 0.4rem;
  cursor: help;
}
.reader-toggle {
  font-size: 0.62rem;
  color: var(--text-muted);
  background: transparent;
  border: 1px solid var(--border-color);
  border-radius: 999px;
  padding: 0.05rem 0.4rem;
  cursor: pointer;
}
.reader-toggle.on {
  color: var(--accent-500);
  border-color: var(--accent-500);
}
.update-dot {
  margin-left: auto;
  font-size: 0.65rem;
  color: var(--accent-500);
  background: transparent;
  border: 1px solid var(--accent-500);
  border-radius: 999px;
  padding: 0.05rem 0.45rem;
  cursor: pointer;
  animation: pulse 2s ease-in-out infinite;
}
.chevron {
  color: var(--text-muted);
  font-size: 0.7rem;
  transition: transform 0.15s ease;
}
.chevron.open {
  transform: rotate(0deg);
}
.chevron:not(.open) {
  transform: rotate(-90deg);
}
.chevron.small {
  font-size: 0.6rem;
}
@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.55; }
}

.time-edit-row {
  display: flex;
  justify-content: flex-end;
  margin-top: -0.4rem;
}
.link-btn {
  background: none;
  border: none;
  color: var(--accent-500);
  font-size: 0.7rem;
  cursor: pointer;
  padding: 0.1rem 0.3rem;
}
.time-editor {
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
  padding: 0.5rem 0.6rem;
  border: 1px dashed var(--border-color);
  border-radius: 0.25rem;
  font-size: 0.75rem;
  color: var(--text-muted);
}
.time-editor label {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}
.time-editor input {
  width: 6rem;
  padding: 0.2rem 0.4rem;
  background: var(--bg-canvas);
  border: 1px solid var(--border-color);
  border-radius: 0.25rem;
  color: var(--text-primary);
  font-size: 0.78rem;
}
.time-preview {
  color: var(--text-primary);
}
.time-actions {
  display: flex;
  gap: 0.4rem;
}
.mini-btn {
  padding: 0.2rem 0.7rem;
  background: transparent;
  border: 1px solid var(--border-color);
  border-radius: 0.25rem;
  color: var(--text-muted);
  font-size: 0.72rem;
  cursor: pointer;
}
.mini-btn.primary {
  background: var(--accent-500);
  border-color: var(--accent-500);
  color: #fff;
}

.slice-body {
  display: flex;
  flex-direction: column;
  gap: 0.9rem;
  padding-top: 0.25rem;
}

.setting-group {
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
}
.setting-group-label {
  font-size: 0.8rem;
  font-weight: 600;
  color: var(--text-primary);
  display: flex;
  align-items: baseline;
  gap: 0.5rem;
}
.setting-group-label .muted {
  font-size: 0.7rem;
  font-weight: normal;
  color: var(--text-muted);
}

.empty-hint {
  font-size: 0.75rem;
  color: var(--text-muted);
  font-style: italic;
  padding: 0.25rem 0;
  line-height: 1.6;
}

.presence-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}
.presence-row {
  display: flex;
  align-items: baseline;
  gap: 0.75rem;
  padding: 0.3rem 0.5rem;
  border: 1px solid var(--border-color);
  border-radius: 0.25rem;
  font-size: 0.78rem;
}
.presence-row.dead {
  opacity: 0.55;
}
.presence-row.clickable {
  cursor: pointer;
}
.presence-row.clickable:hover {
  border-color: var(--accent-500);
}
.presence-name {
  color: var(--text-primary);
  font-weight: 500;
}
.presence-where {
  color: var(--text-muted);
  font-size: 0.72rem;
}

.scene-row {
  font-size: 0.8rem;
  color: var(--text-primary);
  padding: 0.3rem 0.5rem;
  border: 1px solid var(--border-color);
  border-radius: 0.25rem;
  display: flex;
  align-items: center;
  gap: 0.5rem;
}
.faction-tag {
  font-size: 0.68rem;
  color: var(--text-muted);
  border: 1px dashed var(--border-color);
  border-radius: 999px;
  padding: 0.05rem 0.45rem;
}
.pin-btn {
  margin-left: auto;
  font-size: 0.62rem;
  color: var(--text-muted);
  background: transparent;
  border: 1px dashed var(--border-color);
  border-radius: 999px;
  padding: 0.08rem 0.5rem;
  cursor: pointer;
}
.pin-btn:hover {
  color: var(--accent-500);
  border-color: var(--accent-500);
}

.encounter-row {
  font-size: 0.74rem;
  color: var(--text-primary);
  padding: 0.22rem 0.45rem;
  background: color-mix(in srgb, var(--accent-500) 5%, transparent);
  border-radius: 0.25rem;
}
.encounter-loc {
  color: var(--text-muted);
  font-size: 0.68rem;
}

.thread-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}
.thread-row {
  display: flex;
  align-items: baseline;
  gap: 0.5rem;
  font-size: 0.75rem;
  padding: 0.25rem 0.4rem;
  border-radius: 0.25rem;
}
.thread-row.foreshadow {
  background: color-mix(in srgb, var(--accent-500) 6%, transparent);
}
.thread-row.expectation {
  background: color-mix(in srgb, #d4a017 6%, transparent);
}
.thread-row.clickable {
  cursor: pointer;
}
.thread-row.clickable:hover {
  filter: brightness(0.96);
  box-shadow: inset 0 0 0 1px var(--border-color);
}
.thread-tag {
  flex-shrink: 0;
  font-size: 0.65rem;
  color: var(--text-muted);
}
.thread-text {
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.thread-meta {
  margin-left: auto;
  flex-shrink: 0;
  font-size: 0.65rem;
  color: var(--text-muted);
}
.more-hint {
  font-size: 0.7rem;
  color: var(--accent-500);
  cursor: pointer;
  padding-left: 0.4rem;
}

/* ---- 收件箱 ---- */
.inbox-head {
  cursor: pointer;
  user-select: none;
}
.inbox-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 1.1rem;
  height: 1.1rem;
  padding: 0 0.25rem;
  border-radius: 999px;
  background: var(--accent-500);
  color: #fff;
  font-size: 0.65rem;
  font-weight: 600;
  align-self: center;
}
.inbox-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}
.inbox-row {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.28rem 0.45rem;
  border: 1px dashed var(--border-color);
  border-radius: 0.25rem;
  font-size: 0.73rem;
}
.inbox-type {
  flex-shrink: 0;
  color: var(--accent-500);
  font-size: 0.66rem;
}
.inbox-text {
  flex: 1;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.inbox-meta {
  flex-shrink: 0;
  color: var(--text-muted);
  font-size: 0.63rem;
}
.inbox-actions {
  flex-shrink: 0;
  display: flex;
  gap: 0.25rem;
}
.inbox-btn {
  width: 1.4rem;
  height: 1.4rem;
  border-radius: 0.25rem;
  border: 1px solid var(--border-color);
  background: transparent;
  color: var(--text-muted);
  font-size: 0.75rem;
  cursor: pointer;
  line-height: 1;
}
.inbox-btn.ok:hover {
  color: var(--accent-500);
  border-color: var(--accent-500);
}
.inbox-btn.no:hover {
  color: #d45454;
  border-color: #d45454;
}
.inbox-btn:disabled {
  opacity: 0.5;
  cursor: default;
}
.inbox-hint {
  font-size: 0.68rem;
  color: var(--text-muted);
  font-style: italic;
  cursor: pointer;
}

.usage-hint {
  margin-top: auto;
  padding: 0.75rem;
  background: var(--bg-canvas);
  border: 1px dashed var(--border-color);
  border-radius: 0.25rem;
  font-size: 0.72rem;
  color: var(--text-muted);
  line-height: 1.5;
}
.usage-hint p {
  margin: 0 0 0.5rem;
}
.go-world-btn {
  padding: 0.3rem 0.9rem;
  background: var(--accent-500);
  color: #fff;
  border: none;
  border-radius: 0.25rem;
  font-size: 0.72rem;
  cursor: pointer;
}
.go-world-btn.subtle {
  background: transparent;
  color: var(--accent-500);
  border: 1px solid var(--accent-500);
}

/* ---- 撤销胶囊 ---- */
.undo-capsule {
  position: fixed;
  bottom: 28px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 96;
  display: flex;
  align-items: center;
  gap: 0.7rem;
  padding: 0.45rem 0.8rem;
  background: var(--bg-panel, #2a2a33);
  border: 1px solid var(--border-color);
  border-radius: 999px;
  box-shadow: 0 6px 18px rgba(0, 0, 0, 0.25);
  font-size: 0.75rem;
  color: var(--text-primary);
}
.undo-btn {
  background: none;
  border: 1px solid var(--accent-500);
  border-radius: 999px;
  color: var(--accent-500);
  font-size: 0.7rem;
  padding: 0.12rem 0.6rem;
  cursor: pointer;
}
</style>
