<script setup lang="ts">
/**
 * 世界时间轴（自绘：刻度 + 事件密度直方图 + 事件标记点 + 章节锚刻度 + 指示线 + 拖动 + 播放）。
 *
 * 拖动轨道改 currentTime → worldState computed 自动重算 → 地图人物/疆域/事件回放。
 * 事件标记点：每条历史一个类型色圆点，点击跳到该时刻并聚焦地图——
 * 「哪段历史事多」看直方图，「具体什么事」点标记。
 * 章节锚刻度（M1）：narrative_time 已设的章节显示为「第N章」小片，点击游标跳到该章
 * 叙事时间——章节轴↔世界轴的桥（docs/world-unified-settings.md §2.4）。
 * 右键菜单：在此时刻记录事件 / 标记章节叙事时间 / 埋伏笔（M3）。
 */
import { ref, computed, onBeforeUnmount, onMounted, watch } from 'vue'
import Icon from '../../../components/Icon.vue'
import { useWorld } from '../composables/useWorld'
import { useToast } from '../../../composables/useToast'
import { useConfirmDialog } from '../../../composables/useConfirmDialog'
import ArcBand from '../presentation/ArcBand.vue'
import { yearOf, formatTime, fromYMD } from '../engine/timeFormat'
import { EVENT_TYPE_COLOR, getTemplate } from '../engine/eventTemplates'
import type { WorldEvent, ChapterAnchor, Foreshadow } from '../engine/types'

const emit = defineEmits<{ 'focus-event': [ev: WorldEvent]; 'new-event-at': [t: number] }>()

const { currentTime, events, setCurrentTime, chapterAnchors, setChapterAnchor, foreshadows, createForeshadow, updateForeshadowTimes, resolveForeshadow, dropForeshadow, deleteForeshadow, loadedBookId } =
  useWorld()

const { showToast } = useToast()
const { show: showConfirm } = useConfirmDialog()

const maxTime = computed(() =>
  Math.max(events.value.reduce((m, e) => Math.max(m, e.time_end), 0) + 365, 365 * 5),
)
const pct = computed(() =>
  Math.min(100, Math.max(0, (currentTime.value / maxTime.value) * 100)),
)

// 事件密度分桶
const BUCKETS = 64
const buckets = computed(() => {
  const arr = new Array(BUCKETS).fill(0)
  const span = maxTime.value
  for (const e of events.value) {
    const i = Math.min(BUCKETS - 1, Math.floor((e.time_start / span) * BUCKETS))
    arr[i] += 1
  }
  const mx = Math.max(1, ...arr)
  return arr.map((n) => (n / mx) * 100)
})

// 事件标记点（含横向位置与类型色）
const eventDots = computed(() =>
  events.value.map((e) => ({
    ev: e,
    left: Math.min(100, Math.max(0, (e.time_start / maxTime.value) * 100)),
    color: EVENT_TYPE_COLOR[e.event_type] || '#94a3b8',
    label: getTemplate(e.event_type)?.label || e.event_type,
  })),
)

function onDotClick(ev: WorldEvent) {
  setCurrentTime(ev.time_start)
  emit('focus-event', ev)
}

// 年份刻度（跨度自适应：≤20年→每年，≤200年→每10年，否则每50年）
const ticks = computed(() => {
  const maxY = yearOf(maxTime.value)
  const step = maxY <= 20 ? 1 : maxY <= 200 ? 10 : 50
  const out: { pct: number; label: string }[] = []
  for (let y = 1; y <= maxY; y += step) {
    out.push({ pct: (fromYMD(y, 1, 1) / maxTime.value) * 100, label: `${y}` })
  }
  return out
})

// 拖动（rAF 节流）
const trackRef = ref<HTMLDivElement | null>(null)
let dragging = false
let rafId: number | null = null

function posToTime(clientX: number): number {
  const el = trackRef.value
  if (!el) return 0
  const r = el.getBoundingClientRect()
  const p = Math.min(1, Math.max(0, (clientX - r.left) / r.width))
  return Math.round(p * maxTime.value)
}
function scheduleSet(t: number) {
  if (rafId !== null) return
  rafId = requestAnimationFrame(() => {
    rafId = null
    setCurrentTime(t)
  })
}
function onDown(e: PointerEvent) {
  dragging = true
  ;(e.currentTarget as HTMLElement).setPointerCapture?.(e.pointerId)
  scheduleSet(posToTime(e.clientX))
}
function onMove(e: PointerEvent) {
  if (dragging) scheduleSet(posToTime(e.clientX))
}
function onUp() {
  dragging = false
}

// 播放（~6s 播完全程，到尾循环）
const playing = ref(false)
let timer: ReturnType<typeof setInterval> | null = null
function togglePlay() {
  playing.value = !playing.value
  if (playing.value) {
    const step = Math.max(1, Math.ceil(maxTime.value / 360))
    timer = setInterval(() => {
      if (currentTime.value >= maxTime.value) setCurrentTime(0)
      else setCurrentTime(Math.min(maxTime.value, currentTime.value + step))
    }, 16)
  } else if (timer) {
    clearInterval(timer)
    timer = null
  }
}
onBeforeUnmount(() => {
  if (timer) clearInterval(timer)
  if (rafId !== null) cancelAnimationFrame(rafId)
  window.removeEventListener('mousedown', onGlobalMousedown)
})

// ===== 章节锚刻度层（M1：章节轴↔世界轴的桥）=====

const anchoredChapters = computed(() =>
  chapterAnchors.value.filter((c) => c.narrative_time != null && c.narrative_time <= maxTime.value),
)

function onChapterChipClick(c: ChapterAnchor) {
  if (c.narrative_time != null) setCurrentTime(c.narrative_time)
}

// ===== 演变动画：年份翻牌 + 章节闪现（仅游标前扫时触发）=====

const nowKey = ref(0) // 跨年递增 → :key 重挂触发翻牌动画
let lastYear = 0
const flash = ref<{ text: string; sub: string } | null>(null)
let flashTimer: ReturnType<typeof setTimeout> | null = null
let animPrevT: number | null = null

watch(currentTime, (t) => {
  const y = yearOf(t)
  if (lastYear && y !== lastYear) nowKey.value++
  lastYear = y

  // 前扫跨过章节锚 → 「第 N 章」闪现（回拖不闪）
  if (animPrevT != null && t > animPrevT) {
    for (const c of chapterAnchors.value) {
      if (
        c.narrative_time != null &&
        c.narrative_time > animPrevT &&
        c.narrative_time <= t
      ) {
        flash.value = {
          text: `第${c.chapter_number}章`,
          sub: c.chapter_name || '',
        }
        if (flashTimer) clearTimeout(flashTimer)
        flashTimer = setTimeout(() => (flash.value = null), 1500)
        break // 同刻多章只闪首个
      }
    }
  }
  animPrevT = t
})

onBeforeUnmount(() => {
  if (flashTimer) clearTimeout(flashTimer)
})

// ===== 右键菜单：在此时刻 记录事件 / 标记章节叙事时间 =====

const ctxMenu = ref<{ x: number; y: number; t: number } | null>(null)
const showAnchorPicker = ref(false)

function onTrackContext(e: MouseEvent) {
  e.preventDefault()
  ctxMenu.value = { x: e.clientX, y: e.clientY, t: posToTime(e.clientX) }
  showAnchorPicker.value = false
}

function onGlobalMousedown(e: MouseEvent) {
  // 点击菜单外部关闭（菜单/弹层自身 stop mousedown）
  if (!ctxMenu.value && !fsForm.value && !arcDetail.value) return
  const el = e.target as HTMLElement
  if (!el.closest('.wt-ctx') && !el.closest('.wt-fs') && !el.closest('.wt-arc')) {
    closeCtx()
    fsForm.value = null
    arcDetail.value = null
  }
}

function closeCtx() {
  ctxMenu.value = null
  showAnchorPicker.value = false
}

function ctxNewEvent() {
  if (!ctxMenu.value) return
  emit('new-event-at', ctxMenu.value.t)
  closeCtx()
}

function ctxForeshadow() {
  if (!ctxMenu.value) return
  const { x, y, t } = ctxMenu.value
  closeCtx()
  openForeshadowForm(t, x, y)
}

function ctxAnchor() {
  showAnchorPicker.value = true
}

async function pickChapter(ch: ChapterAnchor) {
  if (!ctxMenu.value) return
  await setChapterAnchor(ch.id, ctxMenu.value.t)
  closeCtx()
}

// ===== 伏笔弧线带（M3）=====

const onlyOpen = ref(false)
const openCount = computed(
  () => foreshadows.value.filter((f) => f.status === 'open' && f.world_time_planted != null).length,
)
const hasPlaced = computed(
  () => foreshadows.value.some((f) => f.status !== 'dropped' && f.world_time_planted != null),
)

async function onUpdateTimes(
  id: string,
  patch: { world_time_planted?: number; world_time_resolved?: number },
) {
  if (!loadedBookId.value) return
  await updateForeshadowTimes(loadedBookId.value, id, patch)
}

// 埋伏笔内联表单（时间轴右键 → 落右键时刻）
const fsForm = ref<{ x: number; y: number; t: number; content: string; entryType: string } | null>(null)

function openForeshadowForm(t: number, x: number, y: number) {
  fsForm.value = { x, y, t, content: '', entryType: 'foreshadow' }
}

async function submitForeshadow() {
  const f = fsForm.value
  if (!f || !f.content.trim() || !loadedBookId.value) return
  await createForeshadow(loadedBookId.value, {
    content: f.content.trim(),
    entryType: f.entryType,
    planted: f.t,
  })
  fsForm.value = null
  showToast('伏笔已埋——回收时机可后补（拖弧线端点）', 'success')
}

// 弧线详情弹层
const arcDetail = ref<{ f: Foreshadow; x: number; y: number } | null>(null)

async function onArcResolve() {
  const d = arcDetail.value
  if (!d || !loadedBookId.value) return
  await resolveForeshadow(loadedBookId.value, d.f.id, currentTime.value)
  showToast(`已在 ${formatTime(currentTime.value)} 回收`, 'success')
  arcDetail.value = null
}

async function onArcDrop() {
  const d = arcDetail.value
  if (!d || !loadedBookId.value) return
  await dropForeshadow(loadedBookId.value, d.f.id)
  arcDetail.value = null
}

async function onArcDelete() {
  const d = arcDetail.value
  if (!d || !loadedBookId.value) return
  const ok = await showConfirm({
    title: '删除伏笔',
    message: `确定删除「${d.f.content.slice(0, 24)}」吗？（Ctrl+Z 可撤销）`,
    confirmText: '删除',
  })
  if (!ok) return
  await deleteForeshadow(loadedBookId.value, d.f.id)
  arcDetail.value = null
}

onMounted(() => {
  window.addEventListener('mousedown', onGlobalMousedown)
})
</script>

<template>
  <div class="wt">
    <div class="wt-head">
      <button class="wt-play" :title="playing ? '暂停' : '播放世界演变'" @click="togglePlay">
        <Icon :name="playing ? 'pause' : 'play'" :size="13" />
      </button>
      <div :key="nowKey" class="wt-now">{{ formatTime(currentTime) }}</div>
      <button
        v-if="openCount"
        class="wt-open-badge"
        :class="{ active: onlyOpen }"
        :title="onlyOpen ? '显示全部弧线' : '只看悬空伏笔'"
        @click="onlyOpen = !onlyOpen"
      >
        悬空伏笔 {{ openCount }}
      </button>
      <div class="wt-meta">{{ events.length }} 事件 · 至第 {{ yearOf(maxTime) }} 年</div>
    </div>

    <!-- 伏笔弧线带（M3：plant→payoff 弧线，悬空渐隐；拖端点改锚） -->
    <ArcBand
      v-if="hasPlaced"
      :foreshadows="foreshadows"
      :max-time="maxTime"
      :only-open="onlyOpen"
      @arc-click="(f, at) => (arcDetail = { f, x: at.x, y: at.y })"
      @update-times="onUpdateTimes"
    />
    <!-- 章节锚刻度层（第N章 ↔ 世界时间，点击跳该章叙事时间） -->
    <div v-if="anchoredChapters.length" class="wt-chapters">
      <button
        v-for="c in anchoredChapters"
        :key="c.id"
        class="wt-chap"
        :style="{ left: ((c.narrative_time! / maxTime) * 100) + '%' }"
        :title="`${c.chapter_name || '第' + c.chapter_number + '章'} · ${formatTime(c.narrative_time!)}`"
        @click="onChapterChipClick(c)"
      >
        {{ c.chapter_number }}章
      </button>
    </div>
    <div
      ref="trackRef"
      class="wt-track"
      @pointerdown="onDown"
      @pointermove="onMove"
      @pointerup="onUp"
      @pointercancel="onUp"
      @contextmenu="onTrackContext"
    >
      <div class="wt-bars">
        <div v-for="(h, i) in buckets" :key="i" class="wt-bar" :style="{ height: h + '%' }"></div>
      </div>
      <div
        v-for="d in eventDots"
        :key="d.ev.id"
        class="wt-evt"
        :style="{ left: d.left + '%', background: d.color }"
        :title="`${d.label} · ${formatTime(d.ev.time_start)}`"
        @pointerdown.stop
        @click.stop="onDotClick(d.ev)"
      ></div>
      <div class="wt-cursor" :style="{ left: pct + '%' }"></div>
      <div class="wt-ticks">
        <span
          v-for="(t, i) in ticks"
          :key="i"
          class="wt-tick"
          :style="{ left: t.pct + '%' }"
        >{{ t.label }}</span>
      </div>
    </div>

    <!-- 章节闪现：游标前扫跨过章节锚（演变仪式感） -->
    <Transition name="wt-flash">
      <div v-if="flash" class="wt-flash" aria-hidden="true">
        <span class="wt-flash-ch">{{ flash.text }}</span>
        <span v-if="flash.sub" class="wt-flash-name">{{ flash.sub }}</span>
      </div>
    </Transition>

    <!-- 右键菜单：在此时刻…… -->
    <div
      v-if="ctxMenu"
      class="wt-ctx"
      :style="{ left: ctxMenu.x + 'px', top: ctxMenu.y + 'px' }"
      @mousedown.stop
      @contextmenu.prevent
    >
      <div class="wt-ctx-time">在此时刻（{{ formatTime(ctxMenu.t) }}）</div>
      <template v-if="!showAnchorPicker">
        <button class="wt-ctx-item" @click="ctxNewEvent">
          <Icon name="flag" :size="13" />
          记录事件
        </button>
        <button class="wt-ctx-item" @click="ctxAnchor">
          <Icon name="book-open" :size="13" />
          标记章节叙事时间…
        </button>
        <button class="wt-ctx-item" @click="ctxForeshadow">
          <Icon name="link" :size="13" />
          埋伏笔…
        </button>
      </template>
      <template v-else>
        <div class="wt-ctx-title">哪一章发生在此时刻？</div>
        <div class="wt-ctx-list">
          <button
            v-for="ch in chapterAnchors"
            :key="ch.id"
            class="wt-ctx-item wt-ctx-chap"
            @click="pickChapter(ch)"
          >
            <span class="wt-ctx-chapname">{{ ch.chapter_name || `第${ch.chapter_number}章` }}</span>
            <span v-if="ch.narrative_time != null" class="wt-ctx-chaptime">
              已锚 {{ formatTime(ch.narrative_time) }}
            </span>
          </button>
        </div>
      </template>
    </div>

    <!-- 埋伏笔内联表单（右键时刻落锚） -->
    <div
      v-if="fsForm"
      class="wt-fs"
      :style="{ left: fsForm.x + 'px', top: fsForm.y + 'px' }"
      @mousedown.stop
      @contextmenu.prevent
      @keydown.esc="fsForm = null"
    >
      <div class="wt-fs-title">在 {{ formatTime(fsForm.t) }} 埋伏笔</div>
      <textarea
        v-model="fsForm.content"
        rows="2"
        class="wt-fs-input"
        placeholder="一句话：草蛇灰线，伏脉千里…"
        @keydown.enter.prevent="submitForeshadow"
      ></textarea>
      <div class="wt-fs-row">
        <select v-model="fsForm.entryType" class="wt-fs-select">
          <option value="foreshadow">伏笔</option>
          <option value="callback">回响</option>
          <option value="twist">反转</option>
        </select>
        <button class="wt-fs-cancel" @click="fsForm = null">取消</button>
        <button class="wt-fs-ok" :disabled="!fsForm.content.trim()" @click="submitForeshadow">
          埋下（Enter）
        </button>
      </div>
      <div class="wt-fs-hint">回收时机可后补：拖弧线端点，或在详情里「在此回收」</div>
    </div>

    <!-- 伏笔弧线详情 -->
    <div
      v-if="arcDetail"
      class="wt-arc"
      :style="{ left: arcDetail.x + 'px', top: arcDetail.y + 'px' }"
      @mousedown.stop
      @contextmenu.prevent
      @keydown.esc="arcDetail = null"
    >
      <div class="wt-arc-status">
        <span class="wt-arc-dot" :class="arcDetail.f.status"></span>
        {{ arcDetail.f.status === 'open' ? '悬空中' : arcDetail.f.status === 'closed' ? '已回收' : '已废弃' }}
      </div>
      <div class="wt-arc-content">{{ arcDetail.f.content }}</div>
      <div class="wt-arc-times">
        埋 {{ formatTime(arcDetail.f.world_time_planted ?? 0) }}
        <template v-if="arcDetail.f.world_time_resolved != null">
          · 收 {{ formatTime(arcDetail.f.world_time_resolved) }}
        </template>
      </div>
      <div class="wt-arc-acts">
        <button
          v-if="arcDetail.f.status === 'open'"
          class="wt-arc-act wt-arc-act--primary"
          :title="`在游标时刻（${formatTime(currentTime)}）闭合`"
          @click="onArcResolve"
        >
          在此回收
        </button>
        <button v-if="arcDetail.f.status === 'open'" class="wt-arc-act" @click="onArcDrop">
          废弃
        </button>
        <button class="wt-arc-act wt-arc-act--danger" @click="onArcDelete">删除</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.wt {
  position: relative;
  border-top: 1px solid var(--border-color);
  background: var(--bg-secondary);
  padding: 10px 20px 6px;
  user-select: none;
}
.wt-head {
  display: flex;
  align-items: baseline;
  gap: 12px;
  margin-bottom: 6px;
}
.wt-play {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border: 1px solid var(--border-color);
  background: var(--bg-canvas);
  border-radius: 8px;
  cursor: pointer;
  color: var(--accent-500);
  align-self: center;
  transition: all 0.15s;
}
.wt-play:hover {
  border-color: var(--accent-500);
  background: rgba(124, 106, 173, 0.08);
  transform: translateY(-1px);
}
.wt-now {
  font-size: 15px;
  font-weight: 700;
  color: var(--accent-500);
  font-family: ui-monospace, monospace;
  min-width: 150px;
  animation: wt-flip 0.38s ease-out;
  transform-origin: 50% 60%;
}
@keyframes wt-flip {
  from {
    transform: rotateX(84deg);
    opacity: 0;
    filter: blur(2px);
  }
  to {
    transform: rotateX(0);
    opacity: 1;
    filter: blur(0);
  }
}
.wt-meta {
  font-size: 11px;
  color: var(--text-muted);
  font-family: ui-monospace, monospace;
  margin-left: auto;
}
.wt-track {
  position: relative;
  height: 52px;
  cursor: pointer;
  touch-action: none;
}
.wt-bars {
  position: absolute;
  left: 0;
  right: 0;
  top: 14px;
  bottom: 14px;
  display: flex;
  align-items: flex-end;
  gap: 1px;
}
.wt-bar {
  flex: 1;
  background: linear-gradient(to top, rgba(90, 70, 40, 0.5), rgba(90, 70, 40, 0.16));
  border-radius: 1px 1px 0 0;
  min-height: 0;
}
/* 事件标记点：类型色圆点，悬浮加亮放大 */
.wt-evt {
  position: absolute;
  top: 5px;
  width: 8px;
  height: 8px;
  margin-left: -4px;
  border-radius: 9999px;
  border: 1.5px solid var(--bg-canvas);
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.25);
  cursor: pointer;
  transition: transform 0.12s ease-out;
  z-index: 2;
}
.wt-evt:hover {
  transform: scale(1.5);
  z-index: 3;
}
.wt-cursor {
  position: absolute;
  top: 0;
  bottom: 12px;
  width: 2px;
  margin-left: -1px;
  background: #b32424;
  box-shadow:
    0 0 6px rgba(179, 36, 36, 0.55),
    0 0 14px rgba(179, 36, 36, 0.25);
  pointer-events: none;
  z-index: 4;
}
.wt-ticks {
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  height: 10px;
  font-size: 9px;
  color: var(--text-muted);
  font-family: ui-monospace, monospace;
}
.wt-tick {
  position: absolute;
  transform: translateX(-50%);
  white-space: nowrap;
}

/* ===== 章节锚刻度层 ===== */
.wt-chapters {
  position: relative;
  height: 16px;
  margin-bottom: 2px;
}
.wt-chap {
  position: absolute;
  top: 0;
  transform: translateX(-50%);
  padding: 1px 7px;
  border: 1px solid rgba(124, 106, 173, 0.45);
  border-radius: 9999px;
  background: rgba(124, 106, 173, 0.12);
  color: var(--accent-500);
  font-size: 10px;
  font-family: ui-monospace, monospace;
  cursor: pointer;
  transition: all 0.12s ease-out;
  white-space: nowrap;
}
.wt-chap:hover {
  background: rgba(124, 106, 173, 0.25);
  border-color: var(--accent-500);
}

/* ===== 右键菜单 ===== */
.wt-ctx {
  position: fixed;
  z-index: 60;
  min-width: 200px;
  max-height: 320px;
  overflow-y: auto;
  background: var(--bg-canvas);
  border: 1px solid var(--border-color);
  border-radius: 10px;
  box-shadow: 0 12px 32px rgba(0, 0, 0, 0.18);
  padding: 6px;
  transform: translate(-8px, -8px);
}
.wt-ctx-time {
  padding: 4px 8px 6px;
  font-size: 11px;
  color: var(--text-muted);
  border-bottom: 1px solid var(--border-color);
  margin-bottom: 4px;
}
.wt-ctx-title {
  padding: 2px 8px 6px;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary);
}
.wt-ctx-item {
  display: flex;
  align-items: center;
  gap: 7px;
  width: 100%;
  padding: 6px 8px;
  border: none;
  border-radius: 7px;
  background: transparent;
  color: var(--text-secondary);
  font-size: 13px;
  font-family: inherit;
  text-align: left;
  cursor: pointer;
  transition: background 0.1s;
}
.wt-ctx-item:hover:not(:disabled) {
  background: var(--hover-bg);
  color: var(--text-primary);
}
.wt-ctx-item:disabled {
  opacity: 0.45;
  cursor: default;
}
.wt-ctx-soon {
  margin-left: auto;
  font-size: 10px;
  padding: 0 5px;
  border-radius: 4px;
  background: var(--bg-tertiary);
  color: var(--text-muted);
}
.wt-ctx-list {
  display: flex;
  flex-direction: column;
}
.wt-ctx-chap {
  justify-content: flex-start;
}
.wt-ctx-chapname {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.wt-ctx-chaptime {
  flex-shrink: 0;
  font-size: 10px;
  color: var(--text-muted);
  font-family: ui-monospace, monospace;
}

/* ===== 章节闪现（演变仪式感；仅前扫跨锚触发）===== */
.wt-flash {
  position: absolute;
  left: 0;
  right: 0;
  top: -46px;
  display: flex;
  align-items: baseline;
  justify-content: center;
  gap: 10px;
  pointer-events: none;
  z-index: 50;
}
.wt-flash-ch {
  font-size: 26px;
  font-weight: 800;
  letter-spacing: 0.12em;
  color: #6d5a3c;
  text-shadow: 0 1px 0 rgba(255, 248, 230, 0.8);
}
.wt-flash-name {
  font-size: 14px;
  color: rgba(109, 90, 60, 0.78);
}
.wt-flash-enter-active {
  animation: wt-flash-in 1.5s ease-out;
}
.wt-flash-leave-active {
  transition: opacity 0.2s;
}
.wt-flash-enter-from,
.wt-flash-leave-to {
  opacity: 0;
}
@keyframes wt-flash-in {
  0% {
    opacity: 0;
    transform: translateY(8px);
    filter: blur(3px);
  }
  18% {
    opacity: 1;
    transform: translateY(0);
    filter: blur(0);
  }
  78% {
    opacity: 1;
  }
  100% {
    opacity: 0;
  }
}

/* ===== 悬空伏笔徽标 ===== */
.wt-open-badge {
  padding: 2px 10px;
  border: 1px solid rgba(168, 85, 247, 0.5);
  border-radius: 9999px;
  background: rgba(168, 85, 247, 0.1);
  color: #a855f7;
  font-size: 11px;
  font-family: ui-monospace, monospace;
  cursor: pointer;
  transition: all 0.12s;
  align-self: center;
}
.wt-open-badge:hover,
.wt-open-badge.active {
  background: rgba(168, 85, 247, 0.22);
  border-color: #a855f7;
}

/* ===== 埋伏笔内联表单 ===== */
.wt-fs {
  position: fixed;
  z-index: 62;
  width: 280px;
  background: var(--bg-canvas);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  box-shadow: 0 12px 32px rgba(0, 0, 0, 0.18);
  padding: 12px;
  transform: translate(-8px, -8px);
}
.wt-fs-title {
  font-size: 12px;
  font-weight: 600;
  color: #a855f7;
  margin-bottom: 8px;
}
.wt-fs-input {
  width: 100%;
  box-sizing: border-box;
  padding: 7px 9px;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  background: var(--bg-canvas);
  color: var(--text-primary);
  font-size: 13px;
  font-family: inherit;
  outline: none;
  resize: none;
}
.wt-fs-input:focus {
  border-color: #a855f7;
}
.wt-fs-row {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 8px;
}
.wt-fs-select {
  padding: 5px 6px;
  border: 1px solid var(--border-color);
  border-radius: 7px;
  background: var(--bg-canvas);
  color: var(--text-secondary);
  font-size: 12px;
  font-family: inherit;
  outline: none;
}
.wt-fs-cancel {
  margin-left: auto;
  padding: 5px 10px;
  border: 1px solid var(--border-color);
  border-radius: 7px;
  background: transparent;
  color: var(--text-muted);
  font-size: 12px;
  font-family: inherit;
  cursor: pointer;
}
.wt-fs-ok {
  padding: 5px 10px;
  border: none;
  border-radius: 7px;
  background: #a855f7;
  color: #fff;
  font-size: 12px;
  font-family: inherit;
  cursor: pointer;
}
.wt-fs-ok:disabled {
  opacity: 0.45;
  cursor: default;
}
.wt-fs-hint {
  margin-top: 8px;
  font-size: 10px;
  color: var(--text-muted);
  line-height: 1.5;
}

/* ===== 弧线详情弹层 ===== */
.wt-arc {
  position: fixed;
  z-index: 62;
  width: 260px;
  background: var(--bg-canvas);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  box-shadow: 0 12px 32px rgba(0, 0, 0, 0.18);
  padding: 12px;
  transform: translate(-8px, -8px);
}
.wt-arc-status {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  color: var(--text-muted);
  margin-bottom: 6px;
}
.wt-arc-dot {
  width: 8px;
  height: 8px;
  border-radius: 9999px;
}
.wt-arc-dot.open {
  background: #a855f7;
}
.wt-arc-dot.closed {
  background: #64748b;
}
.wt-arc-dot.dropped {
  background: #9ca3af;
}
.wt-arc-content {
  font-size: 13px;
  color: var(--text-primary);
  line-height: 1.6;
  margin-bottom: 6px;
}
.wt-arc-times {
  font-size: 10px;
  color: var(--text-muted);
  font-family: ui-monospace, monospace;
  margin-bottom: 10px;
}
.wt-arc-acts {
  display: flex;
  gap: 6px;
}
.wt-arc-act {
  flex: 1;
  padding: 6px 0;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  background: transparent;
  color: var(--text-secondary);
  font-size: 12px;
  font-family: inherit;
  cursor: pointer;
  transition: all 0.12s;
}
.wt-arc-act:hover {
  border-color: var(--accent-500);
  color: var(--accent-500);
}
.wt-arc-act--primary {
  border-color: #a855f7;
  color: #a855f7;
}
.wt-arc-act--primary:hover {
  background: rgba(168, 85, 247, 0.12);
}
.wt-arc-act--danger:hover {
  border-color: #dc2626;
  color: #dc2626;
}
</style>
