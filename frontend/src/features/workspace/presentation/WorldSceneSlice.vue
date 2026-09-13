<script setup lang="ts">
import { computed, ref, watch, onMounted, onBeforeUnmount } from 'vue'
import { useRouter } from 'vue-router'
import { useAppStore } from '../../app/useAppStore'
import { useWorldSlice, WORLD_REFRESH_EVENT } from '../../world/composables/useWorldSlice'
import { formatTime, breakdownTime, fromYMD, displayCandidateTime } from '../../world/engine/timeFormat'
import { getTemplate } from '../../world/engine/eventTemplates'
import { narrativeSourceText } from '../../world/engine/narrativeTimeSource'
import { locationPath } from '../../world/engine/locationTree'
import type { EventType, WorldLocation } from '../../world/engine/types'
import { worldApi } from '../../../services/api/domain/world.api'
import type { WorldEventCandidate } from '../../../services/api/domain/world.api'
import { getAssistMutes, forgiveAssistMute, type AssistMute } from '../../../services/api/domain/assist.api'
import BatchAcceptModal from '../../world/presentation/BatchAcceptModal.vue'
import {
  runBatchAccept,
  undoBatchAccept,
  summarizeBatch,
  OPEN_INBOX_EVENT,
  inboxAutoOpen,
} from '../../world/composables/batchAccept'
import type { BatchAcceptOutcome } from '../../world/composables/batchAccept'
import { useToast } from '../../../composables/useToast'
import { loadUiPrefs, saveUiPrefs } from '../../../composables/useUiPrefs'
import { dispatchCollabEvent } from '../../../composables/collabEventBus'

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
  scoutSkipped,
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
  dispatchCollabEvent('slice_mode', { mode: readerView.value ? 'reader' : 'author' })
}
const presenceView = computed(() =>
  readerView.value ? (slice.value?.presence || []).filter((p) => p.visibility === 'public') : slice.value?.presence || []
)

// 相遇口径（遗留修）：读者视角显示全公开参与者的相遇；作者视角全显示
// （encounters 的 names 来自 presence.name——匹配用同名键）
const visibleEncounters = computed(() => {
  const encs = slice.value?.encounters || []
  if (!readerView.value) return encs
  const publicNames = new Set(presenceView.value.map((p) => p.name))
  return encs.filter((e) => (e.names || []).every((n: string) => publicNames.has(n)))
})

// ---- 时刻来源小字（人话行，见 world/engine/narrativeTimeSource.ts）----

// ---- A4 时刻来源小字：来自本章锚 / 来自第N章锚 / 来自事件『……』 / 未锚定 ----
const sourceText = computed(() =>
  slice.value
    ? narrativeSourceText({
        source: slice.value.t_source,
        chapter: slice.value.t_source_chapter,
        note: slice.value.t_source_note,
      })
    : '',
)

/** A4 一键锚定：把本章叙事锚钉在当前推演时刻（setNarrativeTime 与世界页时间轴
 *  右键锚定共用 worldApi.setChapterAnchor 同一通路，不另造路径） */
async function anchorHere() {
  if (!props.chapterId || !currentBookId.value || slice.value == null) return
  await setNarrativeTime(currentBookId.value, props.chapterId, slice.value.t)
}

// ---- 本章时刻编辑（叙事锚 = 切片内容的螺丝）----
// 内部存连续日数（Timestamp），编辑面按架空历法拆 年/月/日——作者不认日数
const editingTime = ref(false)
const draftYear = ref(1)
const draftMonth = ref(1)
const draftDay = ref(1)
const draftT = computed(() => fromYMD(draftYear.value || 1, draftMonth.value || 1, draftDay.value || 1))
const timePreview = computed(() => formatTime(draftT.value))
function openTimeEditor() {
  const ymd = breakdownTime(slice.value?.t ?? 0)
  draftYear.value = ymd.year
  draftMonth.value = ymd.month
  draftDay.value = ymd.day
  editingTime.value = true
}
async function applyTime() {
  if (!props.chapterId || !currentBookId.value) return
  editingTime.value = false
  await setNarrativeTime(currentBookId.value, props.chapterId, draftT.value)
}
async function clearAnchor() {
  if (!props.chapterId || !currentBookId.value) return
  editingTime.value = false
  await setNarrativeTime(currentBookId.value, props.chapterId, null)
}

// ---- 场景钉（脚下：直接选一个地方即钉住；取消钉住回到按事件推算）----
const locPickerOpen = ref(false)

// ---- 光标派生取景框（第三弹）：心跳带 active_scene → 微标 + 一键钉定 ----
const activeScene = ref<{ loc_id: string; loc_name: string; derived: boolean; via?: string } | null>(null)
function _onActiveScene(e: Event) {
  const d = (e as CustomEvent).detail as { chapterId?: string; scene?: typeof activeScene.value }
  // 章号守卫：切章后旧章心跳的取景不落新章（与章节纪元守卫同哲学）
  if (!d?.scene || (d.chapterId && d.chapterId !== props.chapterId)) return
  activeScene.value = d.scene
}
async function pinActiveScene() {
  const s = activeScene.value
  if (!s?.loc_id || !props.chapterId || !currentBookId.value) return
  await setScenePin(currentBookId.value, props.chapterId, s.loc_id)
}
onMounted(() => window.addEventListener('velluma:active-scene', _onActiveScene))
onBeforeUnmount(() => window.removeEventListener('velluma:active-scene', _onActiveScene))
watch(() => props.chapterId, () => { activeScene.value = null })
const locationOptions = ref<WorldLocation[]>([])
/** 内部构造（有父级）带全路径显示——钉到房间级时无歧义，且能看出进路 */
const locOptionLabels = computed(() => {
  const byId = new Map(locationOptions.value.map((l) => [l.id, l]))
  return new Map(locationOptions.value.map((l) => [l.id, l.parent_id ? locationPath(l, byId) : l.name]))
})
async function toggleLocPicker() {
  locPickerOpen.value = !locPickerOpen.value
  if (locPickerOpen.value && !locationOptions.value.length && currentBookId.value) {
    try {
      locationOptions.value = (await worldApi.listLocations(currentBookId.value)) || []
    } catch {
      locationOptions.value = []
    }
  }
}
async function chooseLocation(loc: WorldLocation) {
  if (!props.chapterId || !currentBookId.value) return
  locPickerOpen.value = false
  await setScenePin(currentBookId.value, props.chapterId, loc.id)
}
async function unpinScene() {
  if (!props.chapterId || !currentBookId.value) return
  await setScenePin(currentBookId.value, props.chapterId, null)
}

// ---- 在场补记（「少了谁？补一句」走 Alt+N 同一条速记通路：解析 → 过目 → 入账）----
function openQuickNote() {
  window.dispatchEvent(new CustomEvent('velluma:quick-note'))
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
    loadAssistMutes() // 学着闭嘴：✗ 可能触发静音阈值，顺手刷新静音清单（异步不阻塞）
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

// ---- 学着闭嘴（2026-08-25 战略定稿）：静音清单可见 + 一键恢复 ----
// 静音由后端从拒绝行为派生（quiet_learning）；此处是唯一可见面——尤其覆盖
// 「收件箱为什么空了」的困惑场景（空箱 + 有静音 → 作者知道是自己在掌舵）。
const assistMutes = ref<AssistMute[]>([])
async function loadAssistMutes() {
  if (!currentBookId.value) return
  assistMutes.value = await getAssistMutes(currentBookId.value)
}
async function restoreMute(key: string) {
  if (!currentBookId.value) return
  try {
    assistMutes.value = await forgiveAssistMute(currentBookId.value, key)
    showToast('已恢复，这类还会再提', 'success')
  } catch {
    showToast('恢复失败，请重试', 'error')
  }
}
onMounted(loadAssistMutes)

// ---- A5b 批量裁决：全部采纳 → 预览剔除 → 串行 accept → toast 6 秒整批撤销 ----
const { showToast } = useToast()
const batchOpen = ref(false)
const batchBusy = ref(false)
const batchProgress = ref<{ done: number; total: number } | null>(null)

function openBatchAccept() {
  if (!candidates.value.length) return
  batchOpen.value = true
}

async function onBatchConfirm(ids: string[]) {
  if (!currentBookId.value) return
  const picked = candidates.value.filter((c) => ids.includes(c.id))
  if (!picked.length) return
  batchBusy.value = true
  batchProgress.value = { done: 0, total: picked.length }
  let outcomes: BatchAcceptOutcome[] = []
  try {
    outcomes = await runBatchAccept(
      currentBookId.value,
      picked,
      (done, total) => { batchProgress.value = { done, total } },
    )
  } finally {
    batchBusy.value = false
    batchProgress.value = null
    batchOpen.value = false
    // 收件箱/切片随 useWorldSlice 的 world-refresh 监听静默重取
    window.dispatchEvent(new CustomEvent(WORLD_REFRESH_EVENT))
  }
  const { ok, failed, dup } = summarizeBatch(outcomes)
  if (ok > 0) {
    showToast(
      `已把 ${ok} 条世界变化记入世界` + (dup > 0 ? `（另 ${dup} 条与账本重复，已自动跳过）` : ''),
      'success', 6000, {
      label: '撤销',
      // 撤销闭包捕获本批 outcomes——连开两批时旧 toast 只撤旧批
      onClick: () => { void undoBatch(outcomes) },
    })
  } else if (dup > 0) {
    showToast(`${dup} 条与账本已有事件重复，已自动跳过`, 'info')
  }
  if (failed > 0) showToast(`${failed} 条采纳失败（可能已被处理），可稍后重试`, 'warning')
}

async function undoBatch(outcomes: BatchAcceptOutcome[]) {
  if (!currentBookId.value) return
  const undone = await undoBatchAccept(currentBookId.value, outcomes)
  showToast(
    undone > 0 ? `已撤销 ${undone} 条记入（候选回到待确认）` : '撤销未完全成功：可到收件箱逐条处理',
    undone > 0 ? 'info' : 'warning',
  )
  window.dispatchEvent(new CustomEvent(WORLD_REFRESH_EVENT))
}

// ---- A5d 沉淀直达：toast「去确认」→ 抽屉滑出 + 「此刻」tab + 收件箱展开 ----
// 抽屉关闭时本组件是卸载态（v-if），事件发出瞬间监听器未挂——挂载后消费旗标补位
if (inboxAutoOpen.value) {
  inboxOpen.value = true
  inboxAutoOpen.value = false
}
function _onOpenInbox() {
  inboxOpen.value = true
  inboxAutoOpen.value = false
}
onMounted(() => window.addEventListener(OPEN_INBOX_EVENT, _onOpenInbox))
onBeforeUnmount(() => window.removeEventListener(OPEN_INBOX_EVENT, _onOpenInbox))

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
        <p>这里显示故事里此刻的状态：什么时间、谁在哪。它由世界页记录的事件自动算出，AI 写作时看到的也是这份——先去世界页记几笔设定吧。</p>
        <button class="go-world-btn" @click="goWorld()">前往世界页</button>
      </div>

      <template v-else-if="slice">
        <header class="slice-header" @click="toggleCollapsed">
          <span class="slice-title">此刻此地</span>
          <span class="slice-time">故事时间 {{ formatTime(slice.t) }}</span>
          <button
            class="reader-toggle"
            :class="{ on: readerView }"
            title="看看读者眼里的世界：藏起他们还不知道的秘密，检查有没有提前泄底"
            @click.stop="toggleReaderView"
          >
            读者视角
          </button>
          <button v-if="updated" class="update-dot" title="世界页有新记录，这里已经跟着更新了" @click.stop="ack">
            世界有更新
          </button>
          <span class="chevron" :class="{ open: !collapsed }">▾</span>
        </header>

        <!-- 本章故事时间编辑 -->
        <div v-if="editingTime" class="time-editor" @click.stop>
          <div class="ymd-row">
            第
            <input v-model.number="draftYear" class="ymd-year" type="number" min="1" step="1" />
            年
            <input v-model.number="draftMonth" type="number" min="1" max="12" step="1" />
            月
            <input v-model.number="draftDay" type="number" min="1" max="30" step="1" />
            日
          </div>
          <span class="time-preview">{{ timePreview }}</span>
          <div class="time-actions">
            <button class="mini-btn primary" title="把本章固定在输入的时间" @click="applyTime">确定</button>
            <button
              v-if="slice.t_source === 'chapter_anchor'"
              class="mini-btn"
              title="取消固定，回到跟着前一章/最新事件走"
              @click="clearAnchor"
            >
              取消固定
            </button>
            <button class="mini-btn" @click="editingTime = false">取消</button>
          </div>
        </div>
        <div v-else class="time-edit-row">
          <span class="source-note">{{ sourceText }}</span>
          <span class="time-row-actions">
            <button
              v-if="slice.t_source !== 'chapter_anchor'"
              class="link-btn"
              title="本章就固定在这个时间——以后记新事件不会再拉动它"
              @click="anchorHere"
            >
              定在这个时间
            </button>
            <button class="link-btn" title="手动定本章的故事时间（在场、脚下会跟着变）" @click="openTimeEditor">
              改时间
            </button>
          </span>
        </div>

        <div v-show="!collapsed" class="slice-body">
          <!-- 在场 -->
          <section class="setting-group">
            <div class="setting-group-label">在场<span class="muted">谁在哪、谁还活着</span></div>
            <div v-if="!presenceView.length" class="empty-hint">
              世界页还没有这个时间的事态——先给本章定个时间，或
              <button class="link-btn" @click="openQuickNote">补一句</button>（如「老王也到了上海」）。
            </div>
            <ul v-else class="presence-list">
              <li
                v-for="row in presenceView"
                :key="row.entity_id"
                class="presence-row clickable"
                :class="{ dead: !row.alive }"
                :title="row.label ? `依据事件「${row.label}」· 点击去世界页看详情` : '点击去世界页看详情'"
                @click="goWorld(row.entity_id)"
              >
                <span class="presence-name">{{ row.name }}</span>
                <span class="presence-where">
                  <template v-if="!row.alive">已死亡</template>
                  <template v-else-if="row.location_name">在{{ row.location_name }}</template>
                  <template v-else>位置未知</template>
                </span>
                <!-- 词法兜底 badge（2026-09-02）：位置从事件记录的文字推断，非结构化链接
                     ——兼作补录建议：点了「补一句」把这个人正式记进事件 -->
                <span
                  v-if="row.presence_source === 'lexical'"
                  class="presence-inferred"
                  title="这个位置是从事件记录的文字里推断的——世界页补一条正式事件会更准"
                >据正文推断</span>
              </li>
            </ul>
            <button
              v-if="presenceView.length"
              class="link-btn quick-add"
              title="用一句话记进世界页（同 Alt+N），你过目确认后这里自动更新"
              @click="openQuickNote"
            >少了谁？补一句</button>
          </section>

          <!-- 脚下（直接选地点即钉住；不选则按事件推算） -->
          <section class="setting-group">
            <div class="setting-group-label">脚下<span class="muted">本章故事发生的地点</span></div>
            <!-- 第三弹：光标派生取景框微标——正文最近转场命中随笔尖流转，
                 与钉不同时显示并出一键钉定（钉=作者主权覆盖派生） -->
            <div v-if="activeScene && activeScene.loc_id" class="active-scene-row">
              <span class="active-scene-tag" :class="{ 'active-scene-tag--derived': activeScene.derived }">
                此刻取景：{{ activeScene.loc_name || '未命名地点' }}
                <template v-if="activeScene.derived">（正文推导）</template>
              </span>
              <button
                v-if="activeScene.derived && activeScene.loc_id !== slice?.scene?.location_id"
                class="link-btn"
                title="把本章场景钉定到这里——派生是推断，钉定是作者拍板"
                @click="pinActiveScene"
              >钉定</button>
            </div>
            <div v-if="slice.scene" class="scene-row">
              {{ slice.scene.path || slice.scene.name }}
              <span v-if="slice.scene.controlling_faction" class="faction-tag">
                {{ slice.scene.controlling_faction }} 控制区
              </span>
              <span v-if="slice.scene.pinned" class="pinned-tag" title="已固定，不随新事件变动">📌 已定</span>
            </div>
            <div v-else class="empty-hint">还没定——不选就按事件推算。</div>
            <div class="scene-actions">
              <button class="link-btn" @click="toggleLocPicker">
                {{ locPickerOpen ? '收起' : slice.scene?.pinned ? '换地方' : '选一个地方' }}
              </button>
              <button
                v-if="slice.scene?.pinned"
                class="link-btn"
                title="取消固定，回到按事件自动算"
                @click="unpinScene"
              >取消固定</button>
            </div>
            <ul v-if="locPickerOpen" class="loc-picker">
              <li
                v-for="loc in locationOptions"
                :key="loc.id"
                class="loc-option"
                :class="{
                  current: slice.scene?.pinned && slice.scene.location_id === loc.id,
                  'loc-option--inner': !!loc.parent_id,
                }"
                @click="chooseLocation(loc)"
              >{{ locOptionLabels.get(loc.id) || loc.name }}</li>
              <li v-if="!locationOptions.length" class="loc-option loc-option--empty">
                世界页还没有地点——先去世界页建一个
              </li>
            </ul>
          </section>

          <!-- 相遇提示（W5-lite：同地角色的戏剧机会；读者视角只显示全公开参与者的相遇——
               口径定夺：含 private 参与者的相遇是作者层信息，读者不该看到谁在场） -->
          <section v-if="visibleEncounters.length" class="setting-group">
            <div class="setting-group-label">相遇<span class="muted">同在一处的角色，可能撞出戏</span></div>
            <div v-for="(enc, i) in visibleEncounters" :key="i" class="encounter-row">
              {{ enc.names.join(' × ') }}<span class="encounter-loc"> · {{ enc.location_name }}</span>
            </div>
          </section>

          <!-- D4-2 比例尺距离（未标定整段缺席——零变化契约；作者视角信息，读者档隐藏） -->
          <section v-if="!readerView && (slice.proximities?.length || slice.nearest_anchor)" class="setting-group">
            <div class="setting-group-label">距离（按地图粗估）</div>
            <div v-if="slice.nearest_anchor" class="encounter-row">
              最近地标 {{ slice.nearest_anchor.name }}<span class="encounter-loc"> · {{ slice.nearest_anchor.text }}</span>
            </div>
            <div v-for="(p, i) in slice.proximities || []" :key="'px' + i" class="encounter-row">
              {{ p.text }}
            </div>
          </section>

          <!-- 头顶的线（读者视角下伏笔=作者层，隐藏） -->
          <section
            v-if="!readerView && (slice.foreshadows.length || slice.expectations.length)"
            class="setting-group"
          >
            <div class="setting-group-label">伏笔与期待<span class="muted">悬着的线，点击看详情</span></div>
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

          <!-- W4 候选回流收件箱（本章变化）+ A5b 批量裁决 -->
          <section v-if="candidates.length" class="setting-group inbox">
            <div class="setting-group-label inbox-head" @click="inboxOpen = !inboxOpen">
              <span class="inbox-badge">{{ candidates.length }}</span>
              本章带来的世界变化
              <button
                class="mini-btn"
                title="逐条预览后批量采纳（可剔除，确认后 6 秒内可整批撤销）"
                @click.stop="openBatchAccept"
              >
                全部采纳
              </button>
              <span class="chevron small" :class="{ open: inboxOpen }">▾</span>
            </div>
            <ul v-show="inboxOpen" class="inbox-list">
              <li v-for="c in candidates" :key="c.id" class="inbox-row">
                <span class="inbox-type">{{ eventLabelOf(c.draft?.event_type || 'custom') }}</span>
                <span class="inbox-text">{{ c.draft?.summary || c.draft?.note || '（无摘要）' }}</span>
                <span class="inbox-meta">{{ displayCandidateTime(c.draft?.time_start || 0, c.chapter_number) }}</span>
                <span class="inbox-actions">
                  <button
                    class="inbox-btn ok"
                    :disabled="busyCandidateId === c.id"
                    title="采纳，记入世界"
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
              AI 从正文里发现的世界变化，✓ 后记入世界
            </div>
          </section>

          <!-- P3-4（C6）：「世界发现」跳过原因——收件箱空态一句作者语言提示
               （settle/finish 带回；无原因字段时整块缺席，维持现状） -->
          <div v-if="!candidates.length && scoutSkipped" class="empty-hint scout-skipped">
            {{ scoutSkipped }}
          </div>

          <!-- 学着闭嘴：静音清单（有静音才显示——覆盖「收件箱怎么空了」的困惑场景） -->
          <div v-if="assistMutes.length" class="mute-line">
            <span class="mute-line__label">已按你的拒绝少提：</span>
            <span v-for="m in assistMutes" :key="m.key" class="mute-chip">
              {{ m.label }}
              <button class="mute-chip__restore" title="恢复此类（此前的拒绝记录一笔勾销）" @click="restoreMute(m.key)">恢复</button>
            </span>
          </div>

          <div class="usage-hint">
            <p>都按世界页的事件推算——想改就去世界页记一笔（或按 Alt+N）。</p>
            <button class="go-world-btn subtle" @click="goWorld()">打开世界页</button>
          </div>
        </div>
      </template>

      <div v-else-if="loading" class="empty">
        <p>推算中…</p>
      </div>
    </template>

    <!-- 撤销胶囊（✓ 转正后 6 秒可撤：删事件 + 候选回 pending） -->
    <Teleport to="body">
      <div v-if="undoCapsule" class="undo-capsule">
        <span>已记入世界：{{ undoCapsule.label }}</span>
        <button class="undo-btn" @click="undoLastAccept">撤销</button>
      </div>
    </Teleport>

    <!-- A5b 批量裁决模态（全部采纳 → 逐条预览剔除 → 确认） -->
    <BatchAcceptModal
      v-if="batchOpen"
      :candidates="candidates"
      :busy="batchBusy"
      :progress="batchProgress"
      @confirm="onBatchConfirm"
      @close="batchOpen = false"
    />
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
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
  margin-top: -0.4rem;
}
/* A4 来源小字：时刻行左缘（事件摘要可长，单行省略） */
.source-note {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 0.68rem;
  color: var(--text-muted);
}
.time-row-actions {
  display: flex;
  flex-shrink: 0;
  gap: 0.35rem;
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
.ymd-row {
  display: flex;
  align-items: center;
  gap: 0.3rem;
}
.time-editor input {
  width: 3rem;
  padding: 0.2rem 0.3rem;
  text-align: center;
  background: var(--bg-canvas);
  border: 1px solid var(--border-color);
  border-radius: 0.25rem;
  color: var(--text-primary);
  font-size: 0.78rem;
}
.time-editor input.ymd-year {
  width: 3.8rem;
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

/* P3-4（C6）：收件箱空态的「世界发现」跳过提示（复用 empty-hint 排版） */
.scout-skipped {
  margin: 0 0 0.25rem;
}

/* 学着闭嘴：静音清单行（低存在感——作者需要时才看见；chip 带恢复阀） */
.mute-line {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.375rem;
  margin-top: 0.375rem;
  font-size: 0.6875rem;
  color: var(--text-muted);
}
.mute-chip {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  padding: 0.0625rem 0.375rem;
  border: 1px dashed var(--border-color, #d6d3d1);
  border-radius: 9999px;
}
.mute-chip__restore {
  border: none;
  background: none;
  padding: 0;
  font-size: 0.6875rem;
  color: var(--accent-500, #7c6aad);
  cursor: pointer;
}
.mute-chip__restore:hover {
  text-decoration: underline;
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
  padding: 0.3rem 0.25rem;
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
  background: var(--hover-bg);
}
.presence-name {
  color: var(--text-primary);
  font-weight: 500;
}
.presence-where {
  color: var(--text-muted);
  font-size: 0.72rem;
}

.presence-inferred {
  color: var(--accent-400, #9685c2);
  font-size: 0.66rem;
  border: 1px solid currentColor;
  border-radius: 999px;
  padding: 0 0.35rem;
  line-height: 1.3;
  opacity: 0.85;
}

.quick-add {
  margin-top: 0.25rem;
}

/* 第三弹：光标派生取景框微标行 */
.active-scene-row {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  font-size: 0.72rem;
}
.active-scene-tag {
  color: var(--accent-500);
}
.active-scene-tag--derived {
  border-bottom: 1px dashed var(--accent-400, #9685c2);
}

.scene-row {
  font-size: 0.8rem;
  color: var(--text-primary);
  padding: 0.3rem 0.25rem;
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
.pinned-tag {
  font-size: 0.68rem;
  color: var(--text-muted);
}
.scene-actions {
  display: flex;
  gap: 0.75rem;
  padding-left: 0.25rem;
}
.loc-picker {
  list-style: none;
  margin: 0.25rem 0 0;
  padding: 0.25rem;
  border: 1px solid var(--border-color);
  border-radius: 0.375rem;
  background: var(--bg-canvas);
  max-height: 10rem;
  overflow-y: auto;
}
.loc-option {
  padding: 0.3rem 0.5rem;
  font-size: 0.78rem;
  color: var(--text-primary);
  border-radius: 0.25rem;
  cursor: pointer;
}
/* 内部构造选项：全路径 + 缩进，一眼分清大地点与房间 */
.loc-option--inner {
  padding-left: 1.1rem;
  color: var(--text-secondary, var(--text-primary));
}
.loc-option:hover {
  background: var(--hover-bg);
}
.loc-option.current {
  color: var(--accent-500);
}
.loc-option--empty {
  color: var(--text-muted);
  cursor: default;
}
.loc-option--empty:hover {
  background: transparent;
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
.inbox-head .mini-btn {
  margin-left: auto;
  font-size: 0.62rem;
  padding: 0.08rem 0.5rem;
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
