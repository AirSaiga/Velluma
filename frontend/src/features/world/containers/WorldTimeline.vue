<script setup lang="ts">
/**
 * 世界时间轴（自绘：刻度 + 事件密度直方图 + 事件标记点 + 章节锚刻度 + 指示线 + 拖动 + 播放）。
 *
 * 拖动轨道改 currentTime → worldState computed 自动重算 → 地图人物/疆域/事件回放。
 * 事件标记点：每条历史一个类型色圆点，点击跳到该时刻并聚焦地图——
 * 「哪段历史事多」看直方图，「具体什么事」点标记。
 * 主题豁免（01-theme-architecture §7）：鎏金游标/金墨柱/燕尾书签等装饰色跨主题恒定（灯下看地图）。
 * 章节锚刻度（M1）：narrative_time 已设的章节显示为「第N章」小片，点击游标跳到该章
 * 叙事时间——章节轴↔世界轴的桥（docs/world-unified-settings.md §2.4）。
 * 右键菜单：在此时刻记录事件 / 标记章节叙事时间 / 埋伏笔（M3）。
 */
import { ref, computed, onBeforeUnmount, onMounted, watch, nextTick } from 'vue'
import Icon from '../../../components/Icon.vue'
import { useWorld } from '../composables/useWorld'
import { useCanon } from '../composables/useCanon'
import { useToast } from '../../../composables/useToast'
import { useConfirmDialog } from '../../../composables/useConfirmDialog'
import { useFloatingLayer } from '../../../composables/useFloatingLayer'
import { useEscStack } from '../../../composables/useEscStack'
import ArcBand from '../presentation/ArcBand.vue'
import { yearOf, formatTime } from '../engine/timeFormat'
import { fitWindowToContent, buildScaleTicks, formatWindowLabel, assignRows } from '../engine/timelineLayout'
import type { TimelineRange } from '../engine/timelineView'
import { EVENT_TYPE_COLOR, eventDisplayName } from '../engine/eventTemplates'
import type { WorldEvent, ChapterAnchor, Foreshadow } from '../engine/types'

const emit = defineEmits<{
  'focus-event': [ev: WorldEvent]
  'new-event-at': [t: number]
  /** M5：弧线详情「编辑详情」→ WorldView 开伏笔详情抽屉 */
  'edit-foreshadow': [foreshadowId: string]
}>()

const { currentTime, events, setCurrentTime, chapterAnchors, setChapterAnchor, foreshadows, createForeshadow, updateForeshadowTimes, resolveForeshadow, dropForeshadow, deleteForeshadow, loadedBookId, timelineRange, setTimelineRange } =
  useWorld()

const { showToast } = useToast()
const { show: showConfirm } = useConfirmDialog()

/** 空书缺省窗口终点（下限 5 年） */
const maxTime = computed(() =>
  Math.max(events.value.reduce((m, e) => Math.max(m, e.time_end), 0) + 365, 365 * 5),
)

/** 内容时刻全集（事件起止 + 章节锚 + 伏笔埋/收）——自动视野贴合它们 */
const contentTimes = computed(() => {
  const ts: number[] = []
  for (const e of events.value) ts.push(e.time_start, e.time_end)
  for (const c of chapterAnchors.value) if (c.narrative_time != null) ts.push(c.narrative_time)
  for (const f of foreshadows.value) {
    if (f.world_time_planted != null) ts.push(f.world_time_planted)
    if (f.world_time_resolved != null) ts.push(f.world_time_resolved)
  }
  return ts
})

/** 自动视野：贴合内容 + 边距（旧行为=从创世 0 年铺满，稀疏史书大半是空白带） */
const autoWindow = computed(
  () => fitWindowToContent(contentTimes.value) ?? { start: 0, end: maxTime.value },
)

// ===== 视野窗口：可手动框定起止年份 / Ctrl+滚轮缩放（默认自动贴合内容；按书持久化到服务端 books.timeline_view）=====
// 状态在 useWorld 单例（timelineRange），随 load() 从服务端恢复；localStorage 旧键仅作一次性迁移来源。
/** 滚轮缩放的未落盘窗口（600ms 防抖写回；与 timelineRange 同形，浮点年=日精度） */
const pendingRange = ref<TimelineRange | null>(null)
const effRange = computed(() => pendingRange.value ?? timelineRange.value)
// range 年 → 窗口日计数：[round((start-1)*365), round(end*365))；整数年与旧语义逐日等价
const DAYS_PER_YEAR = 365
const viewStart = computed(() =>
  effRange.value ? Math.round((effRange.value.start - 1) * DAYS_PER_YEAR) : autoWindow.value.start,
)
const viewEnd = computed(() =>
  effRange.value ? Math.round(effRange.value.end * DAYS_PER_YEAR) : autoWindow.value.end,
)
const span = computed(() => Math.max(1, viewEnd.value - viewStart.value))
/** 时刻 → 轨道百分比（窗外夹到缘） */
const pctOf = (t: number) =>
  Math.min(100, Math.max(0, ((t - viewStart.value) / span.value) * 100))
const pct = computed(() => pctOf(currentTime.value))

const rangeForm = ref<{ x: number; y: number; start: string; end: string } | null>(null)

function openRangeForm(e: MouseEvent) {
  rangeForm.value = {
    // 02 期 §3.4：视口夹紧由 placeFloating 接管，这里只存原始锚点（表单是年粒度，
    // 日精度窗口向上取整到覆盖它的整年）
    x: e.clientX,
    y: e.clientY,
    start: String(yearOf(viewStart.value)),
    end: String(yearOf(Math.max(viewStart.value, viewEnd.value - 1))),
  }
}

function applyRange() {
  const f = rangeForm.value
  if (!f) return
  const s = parseInt(f.start, 10)
  const e = parseInt(f.end, 10)
  if (!Number.isFinite(s) || !Number.isFinite(e) || s < 1 || e <= s) {
    showToast('需为整数年份，且终止年大于起始年', 'error')
    return
  }
  pendingRange.value = null
  setTimelineRange({ start: s, end: e })
  // 游标夹进新窗口，防失落到视野外
  if (currentTime.value < viewStart.value || currentTime.value > viewEnd.value) {
    setCurrentTime(Math.min(viewEnd.value, Math.max(viewStart.value, currentTime.value)))
  }
  rangeForm.value = null
}

function resetRange() {
  pendingRange.value = null
  setTimelineRange(null)
  rangeForm.value = null
}

// 外部/落盘的窗口变更生效后，滚轮暂存即作废（同值切换无视觉跳变）
watch(timelineRange, () => {
  pendingRange.value = null
})

/** 手动窗口外的事件数（视野截断提醒，显示在头部） */
const hiddenCount = computed(() =>
  effRange.value
    ? events.value.filter(
        (e) => e.time_start < viewStart.value || e.time_start >= viewEnd.value,
      ).length
    : 0,
)

// 事件密度分桶（只计窗内事件）
const BUCKETS = 64
const buckets = computed(() => {
  const arr = new Array(BUCKETS).fill(0)
  for (const e of events.value) {
    if (e.time_start < viewStart.value || e.time_start >= viewEnd.value) continue
    const i = Math.min(
      BUCKETS - 1,
      Math.floor(((e.time_start - viewStart.value) / span.value) * BUCKETS),
    )
    arr[i] += 1
  }
  const mx = Math.max(1, ...arr)
  return arr.map((n) => (n / mx) * 100)
})

// 轨道像素宽（刻度步长 / 标记分行都吃它；ArcBand 同款 ResizeObserver 模式）
const trackRef = ref<HTMLDivElement | null>(null)
const trackWidth = ref(0)
let resizeObs: ResizeObserver | null = null

// 事件标记（类型色信标 + 时长条；像素级重叠的纵向分行，保证每枚都可点）。
// 针脚（beacon stem）：信标底垂直虚线扎到基线，消灭「空中悬浮」——同像素列去重
// （同列多事件针脚本就完全共线，只画最靠上行=最长那根）+ 密度闸（事件过密时整体
// 收针，密度语义由金雾直方图承载）。纯视觉层：行位/位置与原实现逐字节一致。
const DOT_TOP0 = 2 // 与 CSS .wt-evt 行 0 top 对齐
const DOT_ROW_H = 9 // 与 CSS 行距对齐
const DOT_H = 8 // 与 CSS .wt-evt 尺寸对齐（命中区恒 8px）
const BASELINE_Y = 50 // 与 CSS .wt-baseline（bottom:14px @ 轨道高 64px）对齐
const STEM_DENSITY_MAX = 48
const STEM_MIN_GAP_PX = 6

const inWinDots = computed(() => {
  const inWin = events.value
    .filter((e) => e.time_start >= viewStart.value && e.time_start < viewEnd.value)
    .map((e) => ({
      ev: e,
      left: pctOf(e.time_start),
      right: pctOf(Math.max(e.time_end, e.time_start)),
      isSpan: e.time_end > e.time_start,
      color: EVENT_TYPE_COLOR[e.event_type] || 'var(--text-muted)',
      label: eventDisplayName(e),
    }))
  const w = trackWidth.value || 900
  const rows = assignRows(inWin.map((d) => (d.left / 100) * w), 8, 3)
  return inWin.map((d, i) => ({ ...d, row: rows[i] }))
})

/** 针脚密度闸：窗内事件过多或像素中位邻距过窄 → 收针（防「栅栏条形码」） */
const stemsOn = computed(() => {
  const dots = inWinDots.value
  if (dots.length > STEM_DENSITY_MAX) return false
  const pxs = dots
    .map((d) => (d.left / 100) * (trackWidth.value || 900))
    .sort((a, b) => a - b)
  const gaps: number[] = []
  for (let i = 1; i < pxs.length; i++) gaps.push(pxs[i] - pxs[i - 1])
  gaps.sort((a, b) => a - b)
  const med = gaps.length ? gaps[Math.floor(gaps.length / 2)] : Infinity
  return med >= STEM_MIN_GAP_PX
})

const eventDots = computed(() => {
  const w = trackWidth.value || 900
  const colMinRow = new Map<number, number>()
  if (stemsOn.value) {
    for (const d of inWinDots.value) {
      const col = Math.round(((d.left / 100) * w) / 3)
      const prev = colMinRow.get(col)
      if (prev === undefined || d.row < prev) colMinRow.set(col, d.row)
    }
  }
  return inWinDots.value.map((d) => {
    const col = Math.round(((d.left / 100) * w) / 3)
    const dotBottom = DOT_TOP0 + d.row * DOT_ROW_H + DOT_H
    return {
      ...d,
      stem: stemsOn.value && colMinRow.get(col) === d.row,
      stemTop: dotBottom,
      stemH: Math.max(0, BASELINE_Y - dotBottom),
      // 信标同色光晕（hex 色追加 alpha8；非 hex 兜底色不吃光晕）
      glow: /^#[0-9a-fA-F]{6}$/.test(d.color)
        ? `0 0 0 2.5px ${d.color}30, 0 0 9px 1px ${d.color}4d`
        : 'none',
    }
  })
})

function dotTitle(d: (typeof eventDots.value)[number]): string {
  const timePart = d.isSpan
    ? `${formatTime(d.ev.time_start)} → ${formatTime(d.ev.time_end)}`
    : formatTime(d.ev.time_start)
  const note = (d.ev.note || '').trim().slice(0, 40)
  return `${d.label} · ${timePart}${note ? '\n' + note : ''}`
}

function onDotClick(ev: WorldEvent) {
  setCurrentTime(ev.time_start)
  emit('focus-event', ev)
}

// ===== 上/下一事件步进（稀疏史书的主导航：事件聚簇间跳跃，不用扫空白带）=====
const eventTimesInView = computed(() => {
  const ts = new Set<number>()
  for (const e of events.value) {
    if (e.time_start >= viewStart.value && e.time_start < viewEnd.value) ts.add(e.time_start)
  }
  return [...ts].sort((a, b) => a - b)
})
const hasPrevEvent = computed(() => eventTimesInView.value.some((t) => t < currentTime.value - 1e-6))
const hasNextEvent = computed(() => eventTimesInView.value.some((t) => t > currentTime.value + 1e-6))

function stepEvent(dir: 1 | -1) {
  const cur = currentTime.value
  const ts = eventTimesInView.value
  let target: number | undefined
  if (dir === 1) {
    target = ts.find((t) => t > cur + 1e-6)
  } else {
    for (let i = ts.length - 1; i >= 0; i--) {
      if (ts[i] < cur - 1e-6) {
        target = ts[i]
        break
      }
    }
  }
  if (target != null) setCurrentTime(target)
}

// 刻度（年/月/日三档自动降档：>3年窗年档、>62天月档、否则日档；步长按像素宽自适应）
const ticks = computed(() =>
  buildScaleTicks(viewStart.value, viewEnd.value, trackWidth.value || 900).map((tk) => ({
    pct: pctOf(tk.t),
    label: tk.label,
    major: tk.major,
  })),
)

/** 头部视野文案（≥1年「第 X–Y 年」；亚年出月/日粒度） */
const windowLabel = computed(() => formatWindowLabel(viewStart.value, viewEnd.value))

// 拖动（rAF 节流）+ 悬停预览（不拖动时淡线 + 时刻气泡跟随）
// 手势分工（2026-09-02 平移轮）：轨道拖拽=平移视野窗口（>4px 阈值，未达阈值=点击定位游标）；
// 游标柄拖拽=拖动游标。缩放后窗口比内容窄时没有平移手段曾是死路（用户实测）。
const dragging = ref(false)
const panning = ref(false)
const hoverT = ref<number | null>(null)
let rafId: number | null = null
let panState: { id: number; x: number; start: number; end: number; moved: boolean } | null = null

function posToTime(clientX: number): number {
  const el = trackRef.value
  if (!el) return 0
  const r = el.getBoundingClientRect()
  const p = Math.min(1, Math.max(0, (clientX - r.left) / r.width))
  return Math.round(viewStart.value + p * span.value)
}
function scheduleSet(t: number) {
  if (rafId !== null) return
  rafId = requestAnimationFrame(() => {
    rafId = null
    setCurrentTime(t)
  })
}
function onDown(e: PointerEvent) {
  if (e.button !== 0) return
  ;(e.currentTarget as HTMLElement).setPointerCapture?.(e.pointerId)
  // 不立即动游标——先记下起点，等移动阈值判定「平移 vs 点击」
  panState = { id: e.pointerId, x: e.clientX, start: viewStart.value, end: viewEnd.value, moved: false }
}
// 游标柄按下：进入游标拖拽（stopPropagation 防被轨道判成平移）
function onCursorDown(e: PointerEvent) {
  if (e.button !== 0) return
  e.stopPropagation()
  dragging.value = true
  trackRef.value?.setPointerCapture?.(e.pointerId)
  scheduleSet(posToTime(e.clientX))
}
function onMove(e: PointerEvent) {
  if (dragging.value) {
    scheduleSet(posToTime(e.clientX))
    return
  }
  const ps = panState
  if (ps && e.pointerId === ps.id) {
    const dx = e.clientX - ps.x
    if (!ps.moved && Math.abs(dx) < 4) return // 阈值内=仍是点击候选
    ps.moved = true
    panning.value = true
    hoverT.value = null
    // 拖动内容跟随指针：右拖=窗口向过去移（映射惯例）
    const w = trackRef.value?.getBoundingClientRect().width || 1
    const spanD = ps.end - ps.start
    let ns = Math.round(ps.start - (dx / w) * spanD)
    let ne = ns + spanD
    if (ns < 0) {
      ns = 0
      ne = spanD // 触底保跨度（与 fitWindowToContent 同规约）
    }
    pendingRange.value = { start: 1 + ns / DAYS_PER_YEAR, end: ne / DAYS_PER_YEAR }
    return
  }
  hoverT.value = posToTime(e.clientX)
}
function onUp(e: PointerEvent) {
  if (dragging.value) {
    dragging.value = false
    return
  }
  const ps = panState
  if (!ps || e.pointerId !== ps.id) return
  panState = null
  if (ps.moved) {
    panning.value = false
    scheduleZoomCommit() // 复用防抖落盘 + 游标夹窗
  } else {
    setCurrentTime(posToTime(e.clientX)) // 未过阈值=点击定位游标
  }
}
function onLeave() {
  hoverT.value = null
}

// Ctrl/Cmd+滚轮缩放视野（以悬停点为锚，日精度；普通滚轮不劫持，留给页面滚动）
// 窗口以浮点年持久化（日计数 = [round((start-1)*365), round(end*365))），600ms 防抖落盘；
// 缩到比自动视野还宽 = 回自动。最小窗口 7 天（再窄日刻度也无信息增量）。
const MIN_SPAN_DAYS = 7
let zoomTimer: ReturnType<typeof setTimeout> | null = null

function onWheel(e: WheelEvent) {
  if (!e.ctrlKey && !e.metaKey) return
  e.preventDefault()
  const autoSpan = autoWindow.value.end - autoWindow.value.start
  const factor = e.deltaY > 0 ? 1.3 : 1 / 1.3
  const newSpan = span.value * factor
  if (newSpan >= autoSpan * 0.98 && e.deltaY > 0) {
    // 缩到比内容贴合窗还宽 → 「恢复自动」手势
    if (timelineRange.value || pendingRange.value) {
      pendingRange.value = null
      scheduleZoomCommit()
    }
    return
  }
  const clampedSpan = Math.max(MIN_SPAN_DAYS, newSpan)
  const anchor = posToTime(e.clientX)
  const frac = Math.min(1, Math.max(0, (anchor - viewStart.value) / span.value))
  const ns = Math.max(0, Math.round(anchor - frac * clampedSpan))
  const ne = Math.round(ns + clampedSpan)
  pendingRange.value = { start: 1 + ns / DAYS_PER_YEAR, end: ne / DAYS_PER_YEAR }
  scheduleZoomCommit()
}

function scheduleZoomCommit() {
  if (zoomTimer) clearTimeout(zoomTimer)
  zoomTimer = setTimeout(() => {
    zoomTimer = null
    const p = pendingRange.value
    if (!p && !timelineRange.value) return // 双 null 不发空写
    setTimelineRange(p)
    // 游标夹进落定后的窗口
    const t = currentTime.value
    if (t < viewStart.value || t > viewEnd.value) {
      setCurrentTime(Math.min(viewEnd.value, Math.max(viewStart.value, t)))
    }
  }, 600)
}

// ===== 快捷视界胶囊（以游标为中心展开；点击低频走 setTimelineRange 立即落盘——与「框定视野」表单同路径）=====
type ZoomPreset = 'd7' | 'd30' | 'y1' | 'all'
const PRESETS: { key: ZoomPreset; label: string; days: number | null }[] = [
  { key: 'd7', label: '7天', days: 7 },
  { key: 'd30', label: '30天', days: 30 },
  { key: 'y1', label: '1年', days: 365 },
  { key: 'all', label: '全局', days: null },
]
/** 预设切换的平滑过渡窗（380ms 后自动摘除；任何按压/滚轮经 capture 即时摘除，平移缩放手感零污染） */
const trackAnim = ref(false)
let animTimer: ReturnType<typeof setTimeout> | null = null
function killAnim() {
  if (!trackAnim.value && !animTimer) return
  trackAnim.value = false
  if (animTimer) {
    clearTimeout(animTimer)
    animTimer = null
  }
}
const activePreset = computed<ZoomPreset | null>(() => {
  if (!effRange.value) return 'all'
  const s = span.value
  if (Math.abs(s - 7) < 1) return 'd7'
  if (Math.abs(s - 30) < 2) return 'd30'
  if (Math.abs(s - 365) < 8) return 'y1'
  return null
})
function applyPreset(days: number | null) {
  if (days == null) {
    setTimelineRange(null) // 与「缩到最宽即回自动」滚轮手势同语义
  } else {
    // 以游标时刻为中心展开（游标=作者正在端详的时刻，居中不丢焦）；触 0 保跨度
    const ns = Math.max(0, Math.round(currentTime.value - days / 2))
    const ne = ns + days
    setTimelineRange({ start: 1 + ns / DAYS_PER_YEAR, end: ne / DAYS_PER_YEAR })
    // 游标夹窗（中心展开恒在窗内；防御性同 applyRange）
    if (currentTime.value < viewStart.value || currentTime.value > viewEnd.value) {
      setCurrentTime(Math.min(viewEnd.value, Math.max(viewStart.value, currentTime.value)))
    }
  }
  killAnim()
  trackAnim.value = true
  animTimer = setTimeout(killAnim, 380)
}
onBeforeUnmount(() => {
  if (animTimer) clearTimeout(animTimer)
})

// 播放（~6s 播完窗口全程，到尾循环回窗口起点；窄窗放慢到每天一帧，防日级窗口频闪）
const playing = ref(false)
let timer: ReturnType<typeof setInterval> | null = null
function togglePlay() {
  playing.value = !playing.value
  if (playing.value) {
    const step = Math.max(1, Math.ceil(span.value / 360))
    const interval = Math.max(16, Math.round(6000 / (span.value / step)))
    timer = setInterval(() => {
      if (currentTime.value >= viewEnd.value || currentTime.value < viewStart.value)
        setCurrentTime(viewStart.value)
      else setCurrentTime(Math.min(viewEnd.value, currentTime.value + step))
    }, interval)
  } else if (timer) {
    clearInterval(timer)
    timer = null
  }
}
onBeforeUnmount(() => {
  if (timer) clearInterval(timer)
  if (rafId !== null) cancelAnimationFrame(rafId)
  // 组件卸载体感：滚轮缩放暂存立即落盘，不丢最后一次手势
  if (zoomTimer) {
    clearTimeout(zoomTimer)
    zoomTimer = null
    if (pendingRange.value || timelineRange.value) setTimelineRange(pendingRange.value)
  }
  resizeObs?.disconnect()
  window.removeEventListener('mousedown', onGlobalMousedown)
})

// ===== 章节锚刻度层（M1：章节轴↔世界轴的桥）=====

const anchoredChapters = computed(() =>
  chapterAnchors.value.filter(
    (c) =>
      c.narrative_time != null &&
      c.narrative_time >= viewStart.value &&
      c.narrative_time < viewEnd.value,
  ),
)

// ===== C3 揭示投影：真相条目的 expected_reveal_chapter 挂到章节锚刻度（朱点） =====
const { nodes: canonNodes, ensureLoaded: ensureCanon } = useCanon()
watch(
  loadedBookId,
  (id) => { if (id) void ensureCanon(id) },
  { immediate: true },
)
const revealMarksByChapter = computed(() => {
  const by: Record<number, { id: string; label: string; plan: string }[]> = {}
  for (const n of canonNodes.value || []) {
    const ch = n.expected_reveal_chapter
    if (ch && ch > 0) {
      ;(by[ch] ||= []).push({ id: n.id, label: n.label, plan: (n.reveal_plan || '').slice(0, 60) })
    }
  }
  return by
})

function onChapterChipClick(c: ChapterAnchor) {
  if (c.narrative_time != null) setCurrentTime(c.narrative_time)
}

// 章节片横向重叠时纵向分行（按标签长度估算片宽，最多 3 行；密集叙事不再糊成一坨）
const chapterChips = computed(() => {
  const list = anchoredChapters.value.map((c) => ({
    c,
    left: pctOf(c.narrative_time!),
    reveals: revealMarksByChapter.value[c.chapter_number] || [],
  }))
  const w = trackWidth.value || 900
  const widths = list.map(
    (d) => String(d.c.chapter_number).length * 7 + 24 + d.reveals.length * 8,
  )
  const rows = assignRows(
    list.map((d) => (d.left / 100) * w),
    widths,
    3,
  )
  return list.map((d, i) => ({ ...d, row: rows[i] }))
})
const chapterRows = computed(() => chapterChips.value.reduce((m, d) => Math.max(m, d.row + 1), 1))

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
  if (!ctxMenu.value && !fsForm.value && !arcDetail.value && !rangeForm.value) return
  const el = e.target as HTMLElement
  if (
    !el.closest('.wt-ctx') &&
    !el.closest('.wt-fs') &&
    !el.closest('.wt-arc') &&
    !el.closest('.wt-range')
  ) {
    closeCtx()
    fsForm.value = null
    arcDetail.value = null
    rangeForm.value = null
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

// ===== 02 期 §3.4：四弹层统一接 placeFloating（点锚、向上优先+翻转+视口夹紧）+ Esc 栈 =====
// 归位决定（§3.2）：弹层保持页内 DOM、不 teleport、z:800 保留——隔离上下文内层级序正确。
const escStack = useEscStack()

const ctxEl = ref<HTMLElement | null>(null)
const fsEl = ref<HTMLElement | null>(null)
const arcEl = ref<HTMLElement | null>(null)
const rangeEl = ref<HTMLElement | null>(null)

/** 实测尺寸优先（内容行数影响高度），未挂载时用设计兜底包围盒（§3.4） */
function measuredSize(el: HTMLElement | null, fallback: { width: number; height: number }) {
  if (el && el.offsetWidth > 0 && el.offsetHeight > 0) return { width: el.offsetWidth, height: el.offsetHeight }
  return fallback
}
const ctxSize = computed(() => measuredSize(ctxEl.value, { width: 240, height: 320 }))
const fsSize = computed(() => measuredSize(fsEl.value, { width: 280, height: 230 }))
const arcSize = computed(() => measuredSize(arcEl.value, { width: 260, height: 240 }))
const rangeSize = computed(() => measuredSize(rangeEl.value, { width: 236, height: 210 }))

// 时间轴贴视口底缘，向上展开是自然方向；flip 保险朝上空间不足时落下方
const WT_FLOAT_PLACEMENT = { gap: 8, margin: 8, prefer: 'above' as const, flip: true, align: 'start' as const }

const ctxLayer = useFloatingLayer({
  anchor: () => (ctxMenu.value ? { x: ctxMenu.value.x, y: ctxMenu.value.y } : null),
  size: ctxSize,
  placement: WT_FLOAT_PLACEMENT,
  open: computed(() => !!ctxMenu.value),
})
const fsLayer = useFloatingLayer({
  anchor: () => (fsForm.value ? { x: fsForm.value.x, y: fsForm.value.y } : null),
  size: fsSize,
  placement: WT_FLOAT_PLACEMENT,
  open: computed(() => !!fsForm.value),
})
const arcLayer = useFloatingLayer({
  anchor: () => (arcDetail.value ? { x: arcDetail.value.x, y: arcDetail.value.y } : null),
  size: arcSize,
  placement: WT_FLOAT_PLACEMENT,
  open: computed(() => !!arcDetail.value),
})
const rangeLayer = useFloatingLayer({
  anchor: () => (rangeForm.value ? { x: rangeForm.value.x, y: rangeForm.value.y } : null),
  size: rangeSize,
  placement: WT_FLOAT_PLACEMENT,
  open: computed(() => !!rangeForm.value),
})
const { pos: ctxPos, maxHeight: ctxMaxH } = ctxLayer
const { pos: fsPos, maxHeight: fsMaxH } = fsLayer
const { pos: arcPos, maxHeight: arcMaxH } = arcLayer
const { pos: rangePos, maxHeight: rangeMaxH } = rangeLayer

// Esc 栈：打开时入栈（一次 Esc 只关栈顶一层），关闭时摘除（幂等）。wt-ctx 首次获得 Esc 关闭能力
let ctxEscId: symbol | undefined
watch(ctxMenu, (v) => {
  if (v && !ctxEscId) ctxEscId = escStack.push(closeCtx, 'wt-ctx')
  else if (!v && ctxEscId) {
    escStack.remove(ctxEscId)
    ctxEscId = undefined
  }
})
let fsEscId: symbol | undefined
watch(fsForm, (v) => {
  if (v && !fsEscId) fsEscId = escStack.push(() => (fsForm.value = null), 'wt-fs')
  else if (!v && fsEscId) {
    escStack.remove(fsEscId)
    fsEscId = undefined
  }
})
let arcEscId: symbol | undefined
watch(arcDetail, (v) => {
  if (v && !arcEscId) arcEscId = escStack.push(() => (arcDetail.value = null), 'wt-arc')
  else if (!v && arcEscId) {
    escStack.remove(arcEscId)
    arcEscId = undefined
  }
})
let rangeEscId: symbol | undefined
watch(rangeForm, (v) => {
  if (v && !rangeEscId) rangeEscId = escStack.push(() => (rangeForm.value = null), 'wt-range')
  else if (!v && rangeEscId) {
    escStack.remove(rangeEscId)
    rangeEscId = undefined
  }
})

// v-if 挂载后用实测尺寸重算一次（首帧用兜底包围盒）；同层内换锚（再右键他处）也经此重算
watch([ctxMenu, fsForm, arcDetail, rangeForm], () => {
  nextTick(() => {
    if (ctxMenu.value) ctxLayer.recalc()
    if (fsForm.value) fsLayer.recalc()
    if (arcDetail.value) arcLayer.recalc()
    if (rangeForm.value) rangeLayer.recalc()
  })
})

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
  if (trackRef.value) {
    resizeObs = new ResizeObserver((entries) => {
      trackWidth.value = entries[0].contentRect.width
    })
    resizeObs.observe(trackRef.value)
  }
})
</script>

<template>
  <div class="wt">
    <div class="wt-head">
      <div class="wt-nav">
        <button
          class="wt-step"
          title="上一事件"
          :disabled="!hasPrevEvent"
          @click="stepEvent(-1)"
        >
          <Icon name="chevron-left" :size="12" />
        </button>
        <button
          class="wt-play"
          :class="{ playing }"
          :title="playing ? '暂停' : '播放世界演变'"
          @click="togglePlay"
        >
          <Icon :name="playing ? 'pause' : 'play'" :size="13" />
        </button>
        <button
          class="wt-step"
          title="下一事件"
          :disabled="!hasNextEvent"
          @click="stepEvent(1)"
        >
          <Icon name="chevron-right" :size="12" />
        </button>
      </div>
      <div :key="nowKey" class="wt-now">{{ formatTime(currentTime) }}</div>
      <!-- 快捷视界：以游标为中心的跨度预设（全局=回自动视野） -->
      <div class="wt-zooms" role="group" aria-label="快捷视界">
        <button
          v-for="p in PRESETS"
          :key="p.key"
          class="wt-zoom"
          :class="{ active: activePreset === p.key }"
          :title="p.days == null ? '回到自动全局视野' : `以游标时刻为中心展开到${p.label}`"
          @click="applyPreset(p.days)"
        >{{ p.label }}</button>
      </div>
      <button
        v-if="openCount"
        class="wt-open-badge"
        :class="{ active: onlyOpen }"
        :title="onlyOpen ? '显示全部弧线' : '只看悬空伏笔'"
        @click="onlyOpen = !onlyOpen"
      >
        悬空伏笔 {{ openCount }}
      </button>
      <button
        class="wt-meta"
        :class="{ manual: effRange }"
        title="视野窗口：点击框定起止年份；拖拽轨道平移；Ctrl+滚轮缩放（可精确到日）；缩到最宽即回自动"
        @click="openRangeForm"
      >
        {{ events.length }} 事件 · {{ windowLabel }}
        <template v-if="effRange && hiddenCount"> · 窗外 {{ hiddenCount }}</template>
      </button>
    </div>

    <!-- 伏笔弧线带（M3：plant→payoff 弧线，悬空渐隐；拖端点改锚） -->
    <ArcBand
      v-if="hasPlaced"
      :foreshadows="foreshadows"
      :min-time="viewStart"
      :max-time="viewEnd"
      :only-open="onlyOpen"
      @arc-click="(f, at) => (arcDetail = { f, x: at.x, y: at.y })"
      @update-times="onUpdateTimes"
    />
    <!-- 章节锚刻度层（第N章 ↔ 世界时间，点击跳该章叙事时间；书签燕尾指向轨道，底行垂尾接地） -->
    <div
      v-if="chapterChips.length"
      class="wt-chapters"
      :style="{ height: chapterRows * 15 + 1 + 'px' }"
    >
      <div
        v-for="d in chapterChips"
        :key="d.c.id"
        class="wt-chap-wrap"
        :class="{ base: d.row === chapterRows - 1 }"
        :style="{ left: d.left + '%', top: d.row * 15 + 'px' }"
      >
        <button
          class="wt-chap"
          :title="`${d.c.chapter_name || '第' + d.c.chapter_number + '章'} · ${formatTime(d.c.narrative_time!)}`"
          @click="onChapterChipClick(d.c)"
        >
          {{ d.c.chapter_number }}章
          <!-- C3 揭示投影：该章预期揭示的真相（朱点，悬停看条目与计划） -->
          <span
            v-for="r in d.reveals"
            :key="r.id"
            class="wt-reveal"
            :title="`◉ 揭示：${r.label}${r.plan ? ' · ' + r.plan : ''}`"
          >◉</span>
        </button>
      </div>
    </div>
    <div
      ref="trackRef"
      class="wt-track"
      :class="{ panning, anim: trackAnim }"
      @pointerdown="onDown"
      @pointerdown.capture="killAnim"
      @pointermove="onMove"
      @pointerup="onUp"
      @pointercancel="onUp"
      @pointerleave="onLeave"
      @contextmenu="onTrackContext"
      @wheel="onWheel"
      @wheel.capture="killAnim"
    >
      <div class="wt-baseline"></div>
      <div class="wt-bars">
        <div
          v-for="(h, i) in buckets"
          :key="i"
          class="wt-bar"
          :class="{ on: h > 0 }"
          :style="{ height: h + '%' }"
        ></div>
      </div>
      <template v-for="d in eventDots" :key="d.ev.id">
        <div
          v-if="d.isSpan"
          class="wt-span"
          :style="{
            left: d.left + '%',
            width: Math.max(0.5, d.right - d.left) + '%',
            top: 4 + d.row * 9 + 'px',
            background: d.color,
          }"
        ></div>
        <div
          class="wt-evt"
          :style="{ left: d.left + '%', top: 2 + d.row * 9 + 'px', background: d.color, boxShadow: d.glow }"
          :title="dotTitle(d)"
          @pointerdown.stop
          @click.stop="onDotClick(d.ev)"
        ></div>
        <!-- 针脚：信标底虚线垂到基线（悬停由相邻选择器联动点亮为金线；密度闸控制渲染） -->
        <div
          v-if="d.stem"
          class="wt-stem"
          :style="{ left: d.left + '%', top: d.stemTop + 'px', height: d.stemH + 'px' }"
        ></div>
      </template>
      <div v-if="!events.length" class="wt-empty">
        还没有事件——右键在任意时刻记录第一笔，拖动移动「此刻」
      </div>
      <div
        v-if="hoverT != null && !dragging"
        class="wt-hoverline"
        :style="{ left: pctOf(hoverT) + '%' }"
      ></div>
      <div
        v-if="hoverT != null && !dragging"
        class="wt-hovertip"
        :class="{ edgeL: pctOf(hoverT) < 6, edgeR: pctOf(hoverT) > 94 }"
        :style="{ left: pctOf(hoverT) + '%' }"
      >{{ formatTime(hoverT) }}</div>
      <div
        v-if="dragging"
        class="wt-hovertip dragging"
        :class="{ edgeL: pct < 6, edgeR: pct > 94 }"
        :style="{ left: pct + '%' }"
      >{{ formatTime(currentTime) }}</div>
      <div
        class="wt-cursor"
        :style="{ left: pct + '%' }"
        title="拖动移动此刻"
        @pointerdown="onCursorDown"
      ></div>
      <div class="wt-ticks">
        <span
          v-for="(t, i) in ticks"
          :key="i"
          class="wt-tick"
          :class="{ edgeL: t.pct < 4, edgeR: t.pct > 96, major: t.major }"
          :style="{ left: t.pct + '%' }"
        ><i class="wt-tick-mark"></i>{{ t.label }}</span>
      </div>
    </div>

    <!-- 章节闪现：游标前扫跨过章节锚（演变仪式感） -->
    <Transition name="wt-flash">
      <div v-if="flash" class="wt-flash" aria-hidden="true">
        <span class="wt-flash-ch">{{ flash.text }}</span>
        <span v-if="flash.sub" class="wt-flash-name">{{ flash.sub }}</span>
      </div>
    </Transition>

    <!-- 右键菜单：在此时刻……（02 期 §3.4：定位/钳位由 placeFloating 接管） -->
    <div
      v-if="ctxMenu"
      ref="ctxEl"
      class="wt-ctx"
      :style="{ left: ctxPos.left + 'px', top: ctxPos.top + 'px', maxHeight: ctxMaxH != null ? ctxMaxH + 'px' : undefined }"
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
      ref="fsEl"
      class="wt-fs"
      :style="{ left: fsPos.left + 'px', top: fsPos.top + 'px', maxHeight: fsMaxH != null ? fsMaxH + 'px' : undefined }"
      @mousedown.stop
      @contextmenu.prevent
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
      ref="arcEl"
      class="wt-arc"
      :style="{ left: arcPos.left + 'px', top: arcPos.top + 'px', maxHeight: arcMaxH != null ? arcMaxH + 'px' : undefined }"
      @mousedown.stop
      @contextmenu.prevent
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
        <button
          class="wt-arc-act"
          title="编辑内容 / 类型 / 锚（详情抽屉）"
          @click="emit('edit-foreshadow', arcDetail.f.id); arcDetail = null"
        >
          编辑详情
        </button>
        <button v-if="arcDetail.f.status === 'open'" class="wt-arc-act" @click="onArcDrop">
          废弃
        </button>
        <button class="wt-arc-act wt-arc-act--danger" @click="onArcDelete">删除</button>
      </div>
    </div>

    <!-- 视野窗口设置：手动起止年份（头部「N 事件 · …」按钮唤起） -->
    <div
      v-if="rangeForm"
      ref="rangeEl"
      class="wt-range"
      :style="{ left: rangePos.left + 'px', top: rangePos.top + 'px', maxHeight: rangeMaxH != null ? rangeMaxH + 'px' : undefined }"
      @mousedown.stop
      @contextmenu.prevent
    >
      <div class="wt-range-title">时间轴视野</div>
      <div class="wt-range-row">
        第
        <input
          v-model="rangeForm.start"
          class="wt-range-input"
          inputmode="numeric"
          @keydown.enter.prevent="applyRange"
        />
        年 —
        第
        <input
          v-model="rangeForm.end"
          class="wt-range-input"
          inputmode="numeric"
          @keydown.enter.prevent="applyRange"
        />
        年
      </div>
      <div class="wt-range-actions">
        <button v-if="timelineRange" class="wt-range-reset" @click="resetRange">恢复自动</button>
        <button class="wt-range-ok" @click="applyRange">框定视野</button>
      </div>
      <div class="wt-range-hint">窗口只收拢视野、不动史实；窗外事件数会标注在上方。</div>
    </div>
  </div>
</template>

<style scoped>
/* M6 编年史带：纸面渐层 + 衬线日期 + 鎏金游标 */
.wt {
  position: relative;
  border-top: 1px solid rgba(107, 90, 68, 0.3);
  background: linear-gradient(to top, rgba(236, 228, 211, 0.98), rgba(244, 238, 225, 0.92));
  padding: 10px 22px 8px;
  user-select: none;
}
.wt-head {
  display: flex;
  align-items: baseline;
  gap: 14px;
  margin-bottom: 6px;
}
.wt-nav {
  display: flex;
  align-items: center;
  gap: 5px;
  align-self: center;
}
.wt-step {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border: 1px solid rgba(74, 68, 56, 0.35);
  background: rgba(255, 252, 245, 0.55);
  border-radius: 9999px;
  cursor: pointer;
  color: rgba(74, 68, 56, 0.85);
  transition: all 0.12s;
}
.wt-step:hover:not(:disabled) {
  border-color: rgba(74, 68, 56, 0.7);
  background: rgba(255, 252, 245, 0.9);
}
.wt-step:disabled {
  opacity: 0.35;
  cursor: default;
}
.wt-play {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 29px;
  height: 29px;
  border: 1px solid rgba(74, 68, 56, 0.7);
  background: rgba(74, 68, 56, 0.92);
  border-radius: 9999px;
  cursor: pointer;
  color: #f4eee1;
  align-self: center;
  transition: all 0.15s;
}
.wt-play:hover {
  background: rgba(74, 68, 56, 1);
  box-shadow: 0 3px 10px rgba(96, 72, 36, 0.3);
}
.wt-play.playing {
  background: #b08d3e;
  border-color: #b08d3e;
  box-shadow: 0 0 0 3px rgba(176, 141, 62, 0.18);
}
.wt-now {
  /* 蓝图 §5：衬线纪年放大 15% */
  font-size: calc(var(--text-lg) * 1.15);
  font-weight: 600;
  letter-spacing: 0.05em;
  color: rgba(51, 48, 42, 0.92);
  font-family: var(--font-atlas); /* 古地图字体恒定衬线（主题系统 01 §7 豁免） */
  min-width: 190px;
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
/* 头部「N 事件 · …」兼作视野窗口入口（点击框定起止年份）；右距权已移交快捷视界组 */
.wt-meta {
  font-size: var(--text-xs);
  letter-spacing: 0.18em;
  color: var(--text-muted);
  padding: 2px 7px;
  border: 1px solid transparent;
  border-radius: 6px;
  background: transparent;
  font-family: inherit;
  cursor: pointer;
  transition: all 0.12s;
}
.wt-meta:hover {
  color: var(--text-secondary);
  border-color: var(--border-color);
  background: rgba(90, 70, 40, 0.07);
}
/* 手动态：鎏金点出「这不是全程」 */
.wt-meta.manual {
  color: #8a6d2f;
  border-color: rgba(176, 141, 62, 0.4);
  background: rgba(176, 141, 62, 0.08);
}

/* ===== 快捷视界胶囊（以游标为中心展开；active 金态与游标同色系） ===== */
.wt-zooms {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-left: auto;
  align-self: center;
}
.wt-zoom {
  padding: 2px 9px;
  border: 1px solid rgba(107, 90, 68, 0.3);
  border-radius: 9999px;
  background: rgba(255, 252, 245, 0.55);
  color: rgba(74, 68, 56, 0.8);
  font-size: var(--text-xs);
  font-family: var(--font-mono);
  letter-spacing: 0.05em;
  cursor: pointer;
  transition: all 0.12s;
}
.wt-zoom:hover {
  border-color: rgba(176, 141, 62, 0.6);
  color: #8a6d2f;
  background: rgba(255, 252, 245, 0.92);
}
.wt-zoom.active {
  border-color: rgba(176, 141, 62, 0.75);
  background: rgba(176, 141, 62, 0.14);
  color: #8a6d2f;
  box-shadow: 0 0 0 3px rgba(176, 141, 62, 0.08);
}
/* 轨道带：内框带底，与头部区分（编年史「带」的实体感） */
.wt-track {
  position: relative;
  height: 64px;
  cursor: grab; /* 拖拽=平移窗口；游标柄上另为 ew-resize */
  touch-action: none;
  user-select: none;
  border: 1px solid rgba(107, 90, 68, 0.18);
  border-radius: 10px;
  background: rgba(255, 252, 245, 0.42);
  box-shadow: inset 0 1px 3px rgba(96, 72, 36, 0.06);
}
.wt-track.panning {
  cursor: grabbing;
}
/* 基线：刻度尺脊线——针脚的扎线目标，微加重（蓝图 §4） */
.wt-baseline {
  position: absolute;
  left: 0;
  right: 0;
  bottom: 14px;
  height: 1px;
  background: rgba(107, 90, 68, 0.4);
  pointer-events: none;
}
.wt-bars {
  position: absolute;
  left: 0;
  right: 0;
  top: 32px;
  bottom: 16px;
  display: flex;
  align-items: flex-end;
  gap: 2px;
  pointer-events: none;
}
/* 金墨微波（蓝图 §2）：古铜金垂直渐变自日期基底蒸腾而起，顶端 2px 柔圆角 */
.wt-bar {
  flex: 1;
  background: linear-gradient(to top, rgba(176, 141, 62, 0.28) 0%, rgba(176, 141, 62, 0) 100%);
  border-radius: 2px 2px 0 0;
  min-height: 0;
}
/* 非零柱保底可见（单事件不再隐形） */
.wt-bar.on {
  min-height: 8%;
}
/* 信标（蓝图 §1）：1px 衬边让出视觉芯（8px 命中区=6px 芯+2px 衬），同色光晕经内联
   boxShadow 注入；8px 元素尺寸恒为命中区，命中手感与旧圆点逐像素一致 */
.wt-evt {
  position: absolute;
  width: 8px;
  height: 8px;
  margin-left: -4px;
  border-radius: 9999px;
  border: 1px solid rgba(255, 252, 245, 0.85);
  box-sizing: border-box;
  cursor: pointer;
  transition: transform 0.12s ease-out, box-shadow 0.12s ease-out;
  z-index: 2;
}
.wt-evt:hover {
  transform: scale(1.6);
  z-index: 3;
}
/* 针脚：信标底虚线垂到基线——消灭「空中悬浮」；不接事件（纯视觉连接） */
.wt-stem {
  position: absolute;
  width: 0;
  border-left: 1px dashed rgba(107, 90, 68, 0.35);
  pointer-events: none;
  z-index: 1;
}
/* 悬停联动：针脚点亮为实体金线（相邻兄弟选择器，DOM 序=span→信标→针脚） */
.wt-evt:hover + .wt-stem {
  border-left-style: solid;
  border-left-color: rgba(176, 141, 62, 0.9);
}
/* 时长条：time_end > time_start 的事件画起讫横段（类型色半透） */
.wt-span {
  position: absolute;
  height: 4px;
  border-radius: 2px;
  opacity: 0.4;
  pointer-events: none;
  z-index: 1;
}
/* 悬停预览线（不拖动时跟随鼠标的淡竖线） */
.wt-hoverline {
  position: absolute;
  top: 2px;
  bottom: 14px;
  width: 1px;
  background: rgba(74, 68, 56, 0.35);
  pointer-events: none;
  z-index: 3;
}
/* 悬停/拖动时刻气泡（轨道上方跟随） */
.wt-hovertip {
  position: absolute;
  top: -24px;
  transform: translateX(-50%);
  padding: 2px 8px;
  border-radius: 6px;
  background: rgba(74, 68, 56, 0.88);
  color: #f4eee1;
  font-size: var(--text-xs);
  font-family: ui-monospace, monospace;
  white-space: nowrap;
  pointer-events: none;
  z-index: 6;
}
.wt-hovertip.edgeL {
  transform: translateX(0);
}
.wt-hovertip.edgeR {
  transform: translateX(-100%);
}
.wt-hovertip.dragging {
  background: #b08d3e;
  box-shadow: 0 2px 8px rgba(176, 141, 62, 0.4);
}
/* 空态引导（无事件书的轨道上屏提示） */
.wt-empty {
  position: absolute;
  left: 0;
  right: 0;
  top: 8px;
  text-align: center;
  font-size: var(--text-xs);
  letter-spacing: 0.08em;
  color: rgba(109, 90, 60, 0.55);
  pointer-events: none;
}
/* 鎏金游标（M6：朱红 → 鎏金，压三角旗标 + 顶部圆珠抓手；可拖拽移动此刻） */
.wt-cursor {
  position: absolute;
  top: 0;
  bottom: 14px;
  width: 2px;
  margin-left: -1px;
  background: #b08d3e;
  box-shadow:
    0 0 6px rgba(176, 141, 62, 0.55),
    0 0 14px rgba(176, 141, 62, 0.25);
  cursor: ew-resize;
  z-index: 4;
}
/* 隐形加宽抓取带（2px 细线太难捏，左右各扩 6px） */
.wt-cursor::after {
  content: '';
  position: absolute;
  top: 0;
  bottom: 0;
  left: -6px;
  right: -6px;
}
/* 菱形黄铜指针对齐器（蓝图 §4）：渐变铜面+金晕；包络与旧圆珠同量级，命中面增量≈0 */
.wt-cursor::before {
  content: '';
  position: absolute;
  top: -2px;
  left: 50%;
  width: 7px;
  height: 7px;
  box-sizing: border-box;
  transform: translateX(-50%) rotate(45deg);
  background: linear-gradient(135deg, #e6c87e 0%, #b08d3e 55%, #8a6d2f 100%);
  border: 1px solid rgba(255, 252, 245, 0.92);
  box-shadow:
    0 0 8px rgba(176, 141, 62, 0.65),
    0 1px 2px rgba(96, 72, 36, 0.4);
}
.wt-ticks {
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  height: 14px;
  font-size: var(--text-xs);
  color: var(--text-secondary); /* 02 期 §4：主刻度数字归 token（原墨色 rgba 0.75 过淡） */
  font-family: var(--font-mono);
  pointer-events: none;
}
.wt-tick {
  position: absolute;
  bottom: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 1px;
  transform: translateX(-50%);
  white-space: nowrap;
}
.wt-tick-mark {
  display: block;
  width: 1px;
  height: 4px;
  background: rgba(107, 90, 68, 0.45);
}
/* 刻度分档（蓝图 §4 精工层次）：major（年界/月界）松烟墨加重线，minor（日网格）淡一度 */
.wt-tick.major {
  font-weight: 600;
  color: #5c4a32;
}
.wt-tick.major .wt-tick-mark {
  height: 7px;
  width: 1.5px;
  background: rgba(92, 74, 50, 0.75);
}
.wt-tick:not(.major) {
  font-size: var(--text-xs);
  color: var(--text-muted); /* 02 期 §4：次刻度数字归 token */
}
/* 缘标签防裁切（首末枚贴缘对齐而非居中出界） */
.wt-tick.edgeL {
  transform: translateX(0);
  align-items: flex-start;
}
.wt-tick.edgeR {
  transform: translateX(-100%);
  align-items: flex-end;
}

/* ===== 章节书签（蓝图 §3：燕尾缎带，轴线经 wrap 居中精确对齐章始时刻） ===== */
.wt-chapters {
  position: relative;
  margin-bottom: 3px;
}
/* wrap 承绝对定位与居中（原 .wt-chap 的 left/translateX 职责），z 序随之迁移 */
.wt-chap-wrap {
  position: absolute;
  transform: translateX(-50%);
  z-index: 2;
}
.wt-chap-wrap:hover {
  z-index: 3;
}
/* 底行书签垂尾：桥接章节区与轨道顶缘（区高冗余 2px + 区距 3px，净增高度为零） */
.wt-chap-wrap.base::after {
  content: '';
  position: absolute;
  top: 100%;
  left: 50%;
  width: 1px;
  height: 7px;
  background: linear-gradient(to bottom, rgba(126, 87, 194, 0.6), rgba(126, 87, 194, 0.08));
}
.wt-chap {
  position: relative;
  display: flex;
  align-items: center;
  height: 14px;
  box-sizing: border-box;
  padding: 0 7px;
  border: none;
  /* 燕尾：底缘中央内凹 4px 指向章始时刻；filter 阴影沿裁剪后形状描边（border 会被 clip 吃掉） */
  clip-path: polygon(0 0, 100% 0, 100% 100%, 50% calc(100% - 4px), 0 100%);
  background: linear-gradient(to bottom, rgba(126, 87, 194, 0.2), rgba(126, 87, 194, 0.36));
  filter: drop-shadow(0 1px 1.5px rgba(80, 60, 140, 0.22));
  color: #6b4fa8;
  font-size: var(--text-xs);
  font-family: ui-monospace, monospace;
  cursor: pointer;
  transition: background 0.12s ease-out, filter 0.12s ease-out;
  white-space: nowrap;
}
.wt-chap:hover {
  background: linear-gradient(to bottom, rgba(126, 87, 194, 0.32), rgba(126, 87, 194, 0.5));
  filter: drop-shadow(0 1px 3px rgba(80, 60, 140, 0.35));
}

/* ===== 右键菜单 ===== */
/* 弹层层级：世界页浮层内部刻度到 760（罗盘 660/图标栏 750），瞬态菜单须压过全部 */
.wt-ctx {
  position: fixed;
  z-index: 800;
  min-width: 200px;
  max-height: 320px;
  overflow-y: auto;
  background: var(--bg-canvas);
  border: 1px solid var(--line-faint);
  border-radius: 10px;
  box-shadow: 0 12px 32px rgba(0, 0, 0, 0.18);
  padding: 6px;
}
.wt-ctx-time {
  padding: 4px 8px 6px;
  font-size: var(--text-xs);
  color: var(--text-muted);
  border-bottom: 1px solid var(--line-faint);
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
  font-size: var(--text-xs);
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
  font-size: var(--text-xs);
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
  font-size: var(--text-3xl);
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
  font-size: var(--text-xs);
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
  z-index: 800;
  width: 280px;
  background: var(--bg-canvas);
  border: 1px solid var(--line-faint);
  border-radius: 12px;
  box-shadow: 0 12px 32px rgba(0, 0, 0, 0.18);
  padding: 12px;
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
  border: 1px solid var(--line);
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
  border: 1px solid var(--line);
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
  border: 1px solid var(--line-faint);
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
  font-size: var(--text-xs);
  color: var(--text-muted);
  line-height: 1.5;
}

/* ===== 弧线详情弹层 ===== */
.wt-arc {
  position: fixed;
  z-index: 800;
  width: 260px;
  background: var(--bg-canvas);
  border: 1px solid var(--line-faint);
  border-radius: 12px;
  box-shadow: 0 12px 32px rgba(0, 0, 0, 0.18);
  padding: 12px;
}
.wt-arc-status {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: var(--text-xs);
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
  background: var(--text-secondary);
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
  font-size: var(--text-xs);
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
  border: 1px solid var(--line-faint);
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
  border-color: var(--danger);
  color: var(--danger);
}

/* ===== 视野窗口设置弹层（鎏金，与时间轴游标同色系） ===== */
.wt-range {
  position: fixed;
  z-index: 800;
  width: 236px;
  background: var(--bg-canvas);
  border: 1px solid var(--line-faint);
  border-radius: 12px;
  box-shadow: 0 12px 32px rgba(0, 0, 0, 0.18);
  padding: 12px;
}
.wt-range-title {
  font-size: 12px;
  font-weight: 600;
  color: #8a6d2f;
  margin-bottom: 8px;
}
.wt-range-row {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 12px;
  color: var(--text-secondary);
  white-space: nowrap;
}
.wt-range-input {
  width: 58px;
  padding: 5px 6px;
  border: 1px solid var(--line);
  border-radius: 7px;
  background: var(--bg-canvas);
  color: var(--text-primary);
  font-size: 13px;
  font-family: ui-monospace, monospace;
  text-align: center;
  outline: none;
}
.wt-range-input:focus {
  border-color: #b08d3e;
  box-shadow: 0 0 0 3px rgba(176, 141, 62, 0.12);
}
.wt-range-actions {
  display: flex;
  gap: 6px;
  margin-top: 10px;
}
.wt-range-reset {
  flex: 1;
  padding: 6px 0;
  border: 1px solid var(--line-faint);
  border-radius: 8px;
  background: transparent;
  color: var(--text-muted);
  font-size: 12px;
  font-family: inherit;
  cursor: pointer;
  transition: all 0.12s;
}
.wt-range-reset:hover {
  color: var(--text-secondary);
  border-color: var(--text-muted);
}
.wt-range-ok {
  flex: 1;
  padding: 6px 0;
  border: none;
  border-radius: 8px;
  background: #b08d3e;
  color: #fff;
  font-size: 12px;
  font-family: inherit;
  cursor: pointer;
}
.wt-range-hint {
  margin-top: 8px;
  font-size: var(--text-xs);
  color: var(--text-muted);
  line-height: 1.5;
}

/* C3 揭示投影：书签上的朱点（预期揭示的真相条目），朱晕反衬 */
.wt-reveal {
  color: #c25a4a;
  font-size: var(--text-xs);
  margin-left: 1px;
  pointer-events: auto;
  text-shadow: 0 0 5px rgba(194, 90, 74, 0.5);
}

/* ===== 预设切换平滑过渡（仅预设点击后 380ms 内挂载；任何按压/滚轮 capture 即摘除，平移/缩放手感零污染） ===== */
.wt-track.anim .wt-evt {
  transition:
    left 0.32s ease-out,
    top 0.32s ease-out,
    transform 0.12s ease-out,
    box-shadow 0.12s ease-out;
}
.wt-track.anim .wt-stem {
  transition:
    left 0.32s ease-out,
    top 0.32s ease-out,
    height 0.32s ease-out;
}
.wt-track.anim .wt-span,
.wt-track.anim .wt-cursor,
.wt-track.anim .wt-chap-wrap {
  transition:
    left 0.32s ease-out,
    top 0.32s ease-out;
}
.wt-track.anim .wt-tick {
  transition: left 0.32s ease-out;
}
.wt-track.anim .wt-bar {
  transition: height 0.32s ease-out;
}
</style>
