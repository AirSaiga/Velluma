<script setup lang="ts">
/**
 * 纸左缘提醒轨（07 期 §2.4，取代 260px 常驻感知带）。
 *
 * 默认态=28px 透明轨：每条提醒一枚守行高的 8px 圆点（安全类 10px 朱点），
 * 打算进度一枚 ⚑ 在轨顶，找不到锚/滚出视口的条计进轨底「+N」。
 * 覆态=232px 读卡层：hover 轨 120ms / focus-within / 点击钉住 打开；
 * mouseleave / Esc（入 Esc 栈）/ 钉住态外点 关闭。覆于纸列之上不推挤——
 * 纸列从此零位移（07 期总纲 5）。
 *
 * 数据来自 session.adaptiveSuggestions（canon_watch 心跳产出）。锚定算法
 * （.canon-mark 视口 Y / stackAnchoredTops / rAF 节流）零改动——一份锚定，
 * 轨点与覆态卡两种渲染（bandEl 指根元素，与旧带体同几何原点）。
 */
import { ref, computed, watch, onMounted, onBeforeUnmount, nextTick } from 'vue'
import type { CanonHint, SpineProgress } from '../../../services/api/domain/adaptive.api'
import { usePerceptionAlignment, stackAnchoredTops } from '../composables/usePerceptionAlignment'
import { chapterEditorHandle } from '../../chapter-editor/editorHandle'
import { useEscStack } from '../../../composables/useEscStack'

/** 兜底区折叠阈值（覆态底部，空间有限） */
const COLLAPSE_AT = 4
/** 圆点纵向夹紧半径（轨高上下各留 8px） */
const DOT_MARGIN = 8

const props = defineProps<{
  suggestions: CanonHint[]
  /** 章级谋篇进度（P1.4 M2；无脉络不传 → 进度行静默缺席） */
  spineProgress?: SpineProgress | null
}>()

// 学着闭嘴（2026-08-25 战略定稿）：可静音类别的提醒卡带 × 收起——presentation 只抛事件，
// 埋点与本地摘除由容器（WorkspaceView）接线。白名单与后端 quiet_learning.HINT_MUTEABLE_KINDS
// 同步（改任一侧先对拍）；泄露/矛盾是安全类，永不出现 ×。
const MUTEABLE_KINDS = new Set(['appearance', 'callback', 'style_drift', 'world_inbox'])
function dismissable(kind: string) {
  return MUTEABLE_KINDS.has(kind)
}
/** 安全类（泄底/矛盾）：轨上朱点提权，永不静音 */
const SAFETY_KINDS = new Set(['leak', 'contradiction'])

const emit = defineEmits<{
  'dismiss-hint': [payload: { kind: string; label: string }]
}>()

// 谋篇进度行折叠（默认展开锚点清单；点击行头收起只留旗标）
const spineCollapsed = ref(false)

// 卡五族色种（07 期 §2.4.5 token 化，零新增 token）：卡/点共用一族，
// border/背景/tag 由 color-mix 从 --k 派生，深色自动正确。
function kindMeta(kind: string) {
  switch (kind) {
    case 'appearance':
      return { label: '角色', icon: '👤', cls: 'hint-card--character' }
    case 'callback':
      return { label: '伏笔', icon: '🔑', cls: 'hint-card--hook' }
    case 'leak':
      return { label: '泄密', icon: '⚠', cls: 'hint-card--leak' }
    case 'contradiction':
      return { label: '矛盾', icon: '⚡', cls: 'hint-card--leak' }
    case 'style_drift':
      // 文风漂移（S4 补全）：心跳纯 code 测量章尾指标 vs 目标/健康带
      return { label: '文风', icon: '✒', cls: 'hint-card--style' }
    case 'world_inbox':
      // 收件箱积压（A5c）：全书 pending 候选 >5——柔性提醒去裁决，不弹窗不抢焦点
      return { label: '收件箱', icon: '📥', cls: 'hint-card--inbox' }
    default:
      return { label: '设定', icon: '·', cls: 'hint-card--canon' }
  }
}

// ============================================================
// 锚定（算法零改动，§2.4.4）：bandEl=根元素（轨与覆态同顶缘全高，
// 相对 Y 语义与旧带体逐像素一致）；topReserve 测量对象=覆态内打算进度行
// （dock 槽已迁光标层，无 spine 时 reserve=0）。
// ============================================================
const bandRoot = ref<HTMLElement | null>(null)
const overlayEl = ref<HTMLElement | null>(null)
const spineRowEl = ref<HTMLElement | null>(null)
const topReservePx = ref(0)
// 覆态开合态（提前声明：topReserve 补测 watch 引用它）
const bandOpenState = ref(false)
const pinnedByClick = ref(false)
let _reserveRO: ResizeObserver | null = null
function _measureTopReserve() {
  const el = spineRowEl.value
  if (!el) { topReservePx.value = 0; return }
  topReservePx.value = el.offsetTop + el.offsetHeight + 6
}
watch([spineRowEl, overlayEl], () => {
  _reserveRO?.disconnect()
  _reserveRO = null
  const el = spineRowEl.value
  if (el) {
    _reserveRO = new ResizeObserver(_measureTopReserve)
    _reserveRO.observe(el)
  }
  nextTick(_measureTopReserve)
}, { flush: 'post' })
// offsetTop 变化（谋篇行折叠/出现/覆态开合）不触发 RO，补测
watch([spineCollapsed, () => props.spineProgress, bandOpenState], () => { nextTick(_measureTopReserve) })
onBeforeUnmount(() => { _reserveRO?.disconnect(); _reserveRO = null })

const labels = computed(() => props.suggestions.map((h) => h.node_label))
const { anchors } = usePerceptionAlignment(labels, bandRoot, topReservePx)

// 锚定卡（找到正文位置）—— 覆态内 absolute 渲染到对应行。
// 碰撞避让：stackAnchoredTops 按 Y 排序逐张下推（卡高按内容估算）。
function cardHeight(h: CanonHint): number {
  const detail = h.detail || ''
  const lines = detail ? Math.min(6, Math.ceil(detail.length / 11)) : 0
  return 38 + (lines ? lines * 15 + 6 : 0) + 7
}
const stackedTops = computed(() =>
  stackAnchoredTops(anchors.value, props.suggestions.map(cardHeight)),
)
const located = computed(() => {
  const out: { hint: CanonHint; top: number }[] = []
  for (let i = 0; i < props.suggestions.length; i++) {
    const top = stackedTops.value[i]
    if (top !== null && top !== undefined) {
      out.push({ hint: props.suggestions[i], top })
    }
  }
  return out
})
// 兜底卡（找不到正文位置：orphan/leak 等）—— 覆态底部列表 + 折叠
const floating = computed(() =>
  props.suggestions.filter((_, i) => anchors.value[i] === null || anchors.value[i] === undefined),
)

const floatingExpanded = ref(false)
const visibleFloating = computed(() => {
  if (floatingExpanded.value || floating.value.length <= COLLAPSE_AT) return floating.value
  return floating.value.slice(0, COLLAPSE_AT)
})
const floatingHidden = computed(() =>
  floatingExpanded.value ? 0 : Math.max(0, floating.value.length - COLLAPSE_AT),
)

// ============================================================
// 提醒轨（默认态）：圆点守行高——锚点在视口内的条上点，位置取
// 堆叠后 Y 夹紧进轨；找不到锚/滚出视口的条计进轨底 +N。
// ============================================================
const hostHeight = ref(0)
let _hostRO: ResizeObserver | null = null
onMounted(() => {
  if (bandRoot.value) {
    hostHeight.value = bandRoot.value.offsetHeight
    _hostRO = new ResizeObserver(() => {
      hostHeight.value = bandRoot.value?.offsetHeight ?? 0
    })
    _hostRO.observe(bandRoot.value)
  }
})
onBeforeUnmount(() => { _hostRO?.disconnect(); _hostRO = null })

const railDots = computed(() => {
  const h = hostHeight.value
  const out: { key: string; top: number; cls: string; safety: boolean; title: string }[] = []
  if (!h) return out
  for (let i = 0; i < props.suggestions.length; i++) {
    const raw = anchors.value[i]
    if (raw === null || raw === undefined) continue
    if (raw < 0 || raw > h) continue // 锚点滚出视口 → +N
    const stacked = stackedTops.value[i] ?? raw
    const hint = props.suggestions[i]
    const meta = kindMeta(hint.kind)
    out.push({
      key: `dot${i}`,
      top: Math.max(DOT_MARGIN, Math.min(stacked, h - DOT_MARGIN)),
      cls: meta.cls,
      safety: SAFETY_KINDS.has(hint.kind),
      title: `${meta.label}：${hint.node_label}`,
    })
  }
  return out
})
const hiddenCount = computed(() => props.suggestions.length - railDots.value.length)
const isEmpty = computed(() => props.suggestions.length === 0 && !props.spineProgress)

// ============================================================
// 覆态开合三态：hover 120ms 驻留 / focus-within / 点击钉住；
// 关闭 = 指针离开圆点与覆态（无焦点未钉住）/ Esc（入栈，焦点回编辑器）/ 钉住态外点。
// 08 期 §4.7：根容器 pointer-events:none（不拦截正文选区与点击），
// pointerenter 不冒泡——hover 三态改挂圆点与覆态两件，双旗标跟踪接力。
// （bandOpenState / pinnedByClick 声明在上方锚定区，供 topReserve 补测引用）
// ============================================================
let _hoverTimer: ReturnType<typeof setTimeout> | null = null
const { push: pushEsc, remove: removeEsc } = useEscStack()
let _escId: symbol | null = null
let _dotHover = false
let _overlayHover = false

function openBand() {
  bandOpenState.value = true
}
function closeBand() {
  bandOpenState.value = false
  pinnedByClick.value = false
}
function escCloseBand() {
  closeBand()
  // Esc 关覆态后焦点回编辑器（07 期 §4 键盘列）
  try { chapterEditorHandle.value?.commands?.focus() } catch { /* 编辑器不在时静默 */ }
}
watch(bandOpenState, (open) => {
  if (open) {
    if (!_escId) _escId = pushEsc(escCloseBand, 'perception-overlay')
  } else if (_escId) {
    removeEsc(_escId)
    _escId = null
  }
})

function onHoverEnter() {
  if (_hoverTimer) clearTimeout(_hoverTimer)
  _hoverTimer = setTimeout(() => { openBand() }, 120)
}
function onDotEnter() {
  _dotHover = true
  onHoverEnter()
}
function onDotLeave() {
  _dotHover = false
  _scheduleHoverLeave()
}
function onOverlayEnter() {
  _overlayHover = true
  if (_hoverTimer) { clearTimeout(_hoverTimer); _hoverTimer = null }
}
function onOverlayLeave() {
  _overlayHover = false
  _scheduleHoverLeave()
}
/** 圆点→覆态的指针接力在下一拍落定（leave/enter 同拍连发），避免路过缝隙误收 */
function _scheduleHoverLeave() {
  setTimeout(() => {
    if (_dotHover || _overlayHover) return
    onHoverLeave()
  }, 0)
}
function onHoverLeave() {
  if (_hoverTimer) { clearTimeout(_hoverTimer); _hoverTimer = null }
  if (!bandOpenState.value) return
  if (pinnedByClick.value) return
  const root = bandRoot.value
  if (root && root.contains(document.activeElement)) return // 焦点在轨/卡内不收
  closeBand()
}
function onFocusIn() {
  openBand()
}
function onFocusOut(e: FocusEvent) {
  const root = bandRoot.value
  if (root && e.relatedTarget instanceof Node && root.contains(e.relatedTarget)) return
  if (pinnedByClick.value) return
  // 指针仍悬在轨上时不收（hover 语义优先）
  if (root?.matches(':hover')) return
  closeBand()
}
/** 点击轨体/圆点 = 钉住（覆态常驻至 Esc 或外点） */
function onRailActivate() {
  pinnedByClick.value = true
  openBand()
}
function onDocPointerDown(e: PointerEvent) {
  if (!pinnedByClick.value) return
  const root = bandRoot.value
  if (root && e.target instanceof Node && root.contains(e.target)) return
  closeBand()
}
watch(pinnedByClick, (pinned) => {
  document.removeEventListener('pointerdown', onDocPointerDown, true)
  if (pinned) document.addEventListener('pointerdown', onDocPointerDown, true)
})
onBeforeUnmount(() => {
  document.removeEventListener('pointerdown', onDocPointerDown, true)
  if (_hoverTimer) clearTimeout(_hoverTimer)
  if (_escId) { removeEsc(_escId); _escId = null }
})

/** 覆态/轨上滚轮转发编辑器滚动容器——读卡时滚轮不被截获 */
function forwardWheel(e: WheelEvent) {
  const editor = chapterEditorHandle.value
  const host = editor?.view?.dom?.closest('.overflow-y-auto') as HTMLElement | null
  if (!host) return
  e.preventDefault()
  host.scrollTop += e.deltaY
}
</script>

<template>
  <!-- 根：纸列对齐覆层（08 期 §4.7 纸左页边批注；不占布局宽——纸列零位移的物理保证） -->
  <aside
    ref="bandRoot"
    class="hint-rail-host"
    :aria-hidden="isEmpty ? 'true' : undefined"
    @focusin="onFocusIn"
    @focusout="onFocusOut"
  >
    <div class="hint-rail" @wheel="forwardWheel">
      <!-- 打算小旗（详情在覆态读） -->
      <div v-if="spineProgress" class="hint-rail__flag" :title="spineProgress.hint || '打算进度'">⚑</div>
      <button
        v-for="d in railDots"
        :key="d.key"
        class="hint-dot"
        :class="[d.cls, { 'hint-dot--safety': d.safety }]"
        :style="{ top: d.top + 'px' }"
        :title="d.title"
        @pointerenter="onDotEnter"
        @pointerleave="onDotLeave"
        @click.stop="onRailActivate"
      />
      <div v-if="hiddenCount > 0" class="hint-rail__more" :title="`还有 ${hiddenCount} 条提醒`">+{{ hiddenCount }}</div>
    </div>

    <!-- 覆态（读卡态）：232px 纯色层自纸左缘向右开（覆于正文上），peek 语义同 07 -->
    <Transition name="hint-overlay">
      <div
        v-if="bandOpenState"
        ref="overlayEl"
        class="hint-overlay"
        @pointerenter="onOverlayEnter"
        @pointerleave="onOverlayLeave"
        @wheel="forwardWheel"
      >
        <!-- 打算进度行（锚定卡避让测量对象；行内容沿用旧感知带原样） -->
        <div v-if="spineProgress" ref="spineRowEl" class="spine-progress">
          <button class="spine-progress__head" :title="spineProgress.hint" @click="spineCollapsed = !spineCollapsed">
            <span class="spine-progress__intent">{{ spineProgress.intent || '打算' }}</span>
            <span class="spine-progress__flags">
              <span
                v-for="a in spineProgress.anchors"
                :key="a.id"
                class="spine-flag"
                :class="'spine-flag--' + a.status"
              >{{ a.status === 'hit' ? '⚑' : a.status === 'dropped' ? '⊘' : '⚐' }}</span>
            </span>
          </button>
          <div v-if="!spineCollapsed" class="spine-progress__list">
            <div
              v-for="a in spineProgress.anchors"
              :key="a.id"
              class="spine-progress__item"
              :class="'is-' + a.status"
            >{{ a.status === 'hit' ? '✓ ' : a.status === 'dropped' ? '⊘ ' : '○ ' }}{{ a.text }}</div>
            <div class="spine-progress__hint">{{ spineProgress.hint }}</div>
          </div>
        </div>

        <div v-if="suggestions.length === 0" class="hint-overlay__empty">
          写到相关角色 / 伏笔时，这里会浮现提醒
        </div>

        <!-- 锚定层：感知卡按正文行 Y 对齐（absolute，pointer-events 放行） -->
        <div class="hint-anchor-layer">
          <div
            v-for="(item, i) in located"
            :key="'loc' + i"
            class="hint-card hint-card--anchor"
            :class="kindMeta(item.hint.kind).cls"
            :style="{ top: item.top + 'px' }"
          >
            <div class="hint-card__head">
              <span class="hint-card__icon">{{ kindMeta(item.hint.kind).icon }}</span>
              <span class="hint-card__label" :title="item.hint.node_label">{{ item.hint.node_label }}</span>
              <span class="hint-card__tag">{{ kindMeta(item.hint.kind).label }}</span>
              <button
                v-if="dismissable(item.hint.kind)"
                class="hint-card__dismiss"
                title="收起这类提醒（多收几次就不再提，可在写作助手里恢复）"
                @click.stop="emit('dismiss-hint', { kind: item.hint.kind, label: item.hint.node_label })"
              >×</button>
            </div>
            <div v-if="item.hint.detail" class="hint-card__detail">{{ item.hint.detail }}</div>
          </div>
        </div>

        <!-- 兜底区：找不到正文位置的提醒（底部固定，流式列表 + 折叠） -->
        <div v-if="floating.length" class="hint-floating">
          <div class="hint-sub">其他提醒</div>
          <div
            v-for="(hint, i) in visibleFloating"
            :key="'flt' + i"
            class="hint-card"
            :class="kindMeta(hint.kind).cls"
          >
            <div class="hint-card__head">
              <span class="hint-card__icon">{{ kindMeta(hint.kind).icon }}</span>
              <span class="hint-card__label" :title="hint.node_label">{{ hint.node_label }}</span>
              <span class="hint-card__tag">{{ kindMeta(hint.kind).label }}</span>
              <button
                v-if="dismissable(hint.kind)"
                class="hint-card__dismiss"
                title="收起这类提醒（多收几次就不再提，可在写作助手里恢复）"
                @click.stop="emit('dismiss-hint', { kind: hint.kind, label: hint.node_label })"
              >×</button>
            </div>
            <div v-if="hint.detail" class="hint-card__detail">{{ hint.detail }}</div>
          </div>
          <button v-if="floatingHidden > 0" class="hint-more" @click="floatingExpanded = true">
            +{{ floatingHidden }} 更多
          </button>
        </div>
      </div>
    </Transition>
  </aside>
</template>

<style scoped>
/* 提醒轨宿主：与纸列同轴同宽的对齐覆层（08 期 §4.7 纸左页边批注——圆点落进纸列
   左页边，批注贴着它所指的段落；纸列零位移的物理保证=不占布局宽）。
   宽度复算纸列：min(880px, 100% − 编辑器内边距 40px)。pointer-events:none
   不拦截正文选区与点击——交互件（圆点/覆态）各自回收 pointer-events:auto。 */
.hint-rail-host {
  position: absolute;
  left: 50%;
  transform: translateX(-50%);
  top: 0;
  bottom: 0;
  width: min(var(--editor-max-width), calc(100% - 40px));
  z-index: var(--z-page-chrome);
  pointer-events: none;
}

/* 轨道本体透明且惰性（宿主 pointer-events:none 下不拦截；点击/悬停交互在圆点上） */
.hint-rail {
  position: absolute;
  inset: 0;
}
.hint-rail__flag {
  position: absolute;
  top: 6px;
  left: 18px;
  transform: translateX(-50%);
  font-size: var(--text-xs);
  line-height: 1;
  color: var(--accent-500);
}
.hint-dot {
  position: absolute;
  left: 14px;
  transform: translateY(-50%);
  width: 8px;
  height: 8px;
  border: none;
  border-radius: 999px;
  padding: 0;
  cursor: pointer;
  pointer-events: auto;
  /* 色种由卡族类给出（color-mix 双主题自动正确） */
  background: var(--k, var(--text-muted));
  opacity: 0.85;
  transition: transform var(--dur-1) var(--ease-out), opacity var(--dur-1) var(--ease-out);
}
.hint-dot:hover,
.hint-dot:focus-visible {
  opacity: 1;
  transform: translateY(-50%) scale(1.35);
  outline: none;
}
/* 安全类提权（继承旧折叠徽章语义）：10px 朱点 */
.hint-dot--safety {
  width: 10px;
  height: 10px;
  background: var(--danger);
  box-shadow: 0 0 0 2px color-mix(in srgb, var(--danger) 25%, transparent);
}
.hint-rail__more {
  position: absolute;
  bottom: 6px;
  left: 0;
  width: 36px;
  text-align: center;
  font-size: var(--text-xs);
  color: var(--text-muted);
  pointer-events: none;
}

/* 覆态：232px 读卡层自纸左缘向右开（覆于正文上），投影值镜像 .inspector-drawer（方向相反） */
.hint-overlay {
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 232px;
  background: var(--bg-secondary);
  border-right: 1px solid var(--line-faint);
  box-shadow: 12px 0 0 -1px var(--paper-edge), var(--shadow-lg); /* 04 §A2-3 覆态读卡同款纸叠影 */
  overflow: hidden;
  cursor: default;
  pointer-events: auto;
}
.hint-overlay-enter-active {
  transition: transform var(--dur-2) var(--ease-out), opacity var(--dur-2) var(--ease-out);
}
.hint-overlay-leave-active {
  transition: transform var(--dur-1) var(--ease-in), opacity var(--dur-1) var(--ease-in);
}
.hint-overlay-enter-from,
.hint-overlay-leave-to {
  transform: translateX(-8px);
  opacity: 0;
}
.hint-overlay__empty {
  padding: 12px 10px;
  font-size: var(--text-sm);
  color: var(--text-muted);
  line-height: 1.6;
}

/* 谋篇进度行：意图短语 + 旗标，点击行头收起清单（内容沿用旧带原样） */
.spine-progress {
  position: relative;
  z-index: 2;
  padding: 8px 10px 6px;
  margin-bottom: 6px;
  border-bottom: 1px dashed var(--border-color);
  background: var(--bg-secondary);
}
.spine-progress__head {
  display: flex;
  align-items: center;
  gap: 6px;
  width: 100%;
  border: none;
  background: none;
  cursor: pointer;
  padding: 2px 0;
  text-align: left;
  font-family: inherit;
}
.spine-progress__intent {
  flex: 1;
  font-size: var(--text-xs);
  font-family: var(--font-heading);
  color: var(--text-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.spine-progress__flags {
  display: inline-flex;
  gap: 1px;
  flex-shrink: 0;
}
.spine-flag {
  font-size: var(--text-xs);
  color: var(--text-muted);
}
.spine-flag--hit {
  color: var(--accent-500);
}
.spine-flag--dropped {
  opacity: 0.4;
}
.spine-progress__list {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 2px 0 4px;
}
.spine-progress__item {
  font-size: var(--text-xs);
  color: var(--text-secondary);
}
.spine-progress__item.is-hit {
  color: var(--accent-500);
}
.spine-progress__item.is-dropped {
  opacity: 0.5;
  text-decoration: line-through;
}
.spine-progress__hint {
  font-size: var(--text-xs);
  color: var(--text-muted);
}

/* 锚定层：覆盖覆态全高，pointer-events 放行（不挡进度行交互）；卡片自身回收事件 */
.hint-anchor-layer {
  position: absolute;
  inset: 0;
  pointer-events: none;
}
.hint-card--anchor {
  position: absolute;
  left: 8px;
  right: 8px;
  pointer-events: auto;
}

/* 兜底区：底部固定，顶部渐变避免和锚定卡硬碰（渐变底色 token 化） */
.hint-floating {
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  max-height: 55%;
  overflow-y: auto;
  padding: 14px 8px 8px;
  background: linear-gradient(
    to top,
    color-mix(in srgb, var(--bg-secondary) 98%, transparent) 72%,
    transparent
  );
  z-index: 3;
}
.hint-sub {
  font-size: var(--text-xs);
  color: var(--text-muted);
  margin-bottom: 5px;
}
.hint-more {
  margin-top: 4px;
  padding: 4px;
  width: 100%;
  border: 1px dashed var(--border-color);
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text-muted);
  font-size: var(--text-xs);
  cursor: pointer;
}
.hint-more:hover {
  background: var(--state-hover);
}

/* 卡五族（07 期 §2.4.5）：色种 --k 由族类给出，border/背景/tag 全部 color-mix 派生 */
.hint-card--character { --k: var(--info); }
.hint-card--hook { --k: var(--warn); }
.hint-card--leak { --k: var(--danger); }
.hint-card--style { --k: var(--accent-500); }
.hint-card--inbox { --k: var(--ok); }
.hint-card--canon { --k: var(--text-muted); }

.hint-card {
  background: color-mix(in srgb, var(--k, var(--text-muted)) 8%, var(--bg-canvas));
  border: 1px solid color-mix(in srgb, var(--k, var(--border-color)) 35%, transparent);
  border-radius: var(--radius-md);
  padding: 7px 9px;
  box-shadow: var(--elev-1-shadow);
  margin-bottom: 6px;
}
.hint-card__head {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-bottom: 3px;
}
.hint-card__icon {
  font-size: var(--text-xs);
  line-height: 1;
}
.hint-card__label {
  font-size: var(--text-xs);
  font-weight: 600;
  color: var(--text-primary);
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.hint-card--leak .hint-card__label {
  color: var(--danger);
}
.hint-card__tag {
  font-size: var(--text-xs);
  padding: 1px 5px;
  border-radius: 9999px;
  background: color-mix(in srgb, var(--k, var(--text-muted)) 14%, var(--bg-canvas));
  color: var(--k, var(--text-muted));
  flex-shrink: 0;
}
/* 学着闭嘴：× 默认隐身，卡 hover/focus-within 双触发显形；24px 命中（padding 4px 6px） */
.hint-card__dismiss {
  flex-shrink: 0;
  border: none;
  background: none;
  padding: 4px 6px;
  margin: -4px -6px;
  font-size: var(--text-sm);
  line-height: 1;
  color: var(--text-muted);
  cursor: pointer;
  opacity: 0;
  transition: opacity var(--dur-2) var(--ease-out);
}
.hint-card:hover .hint-card__dismiss,
.hint-card:focus-within .hint-card__dismiss {
  opacity: 0.85;
}
.hint-card__dismiss:hover {
  color: var(--text-primary);
}
.hint-card__detail {
  font-size: var(--text-xs);
  color: var(--text-secondary);
  line-height: 1.5;
}
</style>
