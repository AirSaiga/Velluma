<script setup lang="ts">
/**
 * 左缘感知带（写中常驻 180px 列）。
 *
 * 承载 Canon 感知提示（角色出场 / 伏笔回收 / private 泄露），数据来自
 * session.adaptiveSuggestions（useAdaptiveAssist 心跳接 canon_watch 产出）。
 *
 * 设计约束：任何内容都不许盖正文文字——本带是 editor-host 内的独立列，
 * 与正文区（editor-main）flex 并列，物理隔离。镜头碎片舱（SparkDock）经
 * #dock slot 注入。
 *
 * 按行对齐（批次 6.1/6.2）：感知卡锚定到正文里对应词的垂直位置（usePerceptionAlignment
 * 查 .canon-mark 标记元素视口 Y）。找到位置的卡在锚定层 absolute 渲染；
 * 找不到的（orphan/leak，label 不在当前段落）落底部兜底区 + 折叠。
 */
import { ref, computed, watch, onBeforeUnmount, nextTick } from 'vue'
import type { CanonHint, SpineProgress } from '../../../services/api/domain/adaptive.api'
import { usePerceptionAlignment, stackAnchoredTops } from '../composables/usePerceptionAlignment'

/** 兜底区折叠阈值（空间有限） */
const COLLAPSE_AT = 4

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

const emit = defineEmits<{
  'dismiss-hint': [payload: { kind: string; label: string }]
}>()

// 谋篇进度行折叠（默认展开锚点清单；点击行头收起只留旗标）
const spineCollapsed = ref(false)

function kindMeta(kind: string) {
  switch (kind) {
    case 'appearance':
      return { label: '角色', icon: '👤', cls: 'hint-card--character' }
    case 'callback':
      return { label: '伏笔', icon: '🔑', cls: 'hint-card--hook' }
    case 'leak':
      return { label: '泄露', icon: '⚠', cls: 'hint-card--leak' }
    case 'contradiction':
      return { label: '矛盾', icon: '⚡', cls: 'hint-card--leak' }
    case 'style_drift':
      // 文风漂移（S4 补全）：心跳纯 code 测量章尾指标 vs 目标/健康带
      return { label: '文风', icon: '✒', cls: 'hint-card--style' }
    case 'world_inbox':
      // 收件箱积压（A5c）：全书 pending 候选 >5——柔性提醒去裁决，不弹窗不抢焦点
      return { label: '收件箱', icon: '📥', cls: 'hint-card--inbox' }
    default:
      return { label: 'Canon', icon: '·', cls: 'hint-card--canon' }
  }
}

// 按行对齐：感知带元素 + labels → anchors（每个 label 的 top，null=找不到）
const bandEl = ref<HTMLElement | null>(null)
// 顶部固定区实高（header+谋篇行+镜头碎片舱）：锚定卡避让线，动态实测。
// 旧硬编码 92 只够 header+spine——4 挂件的舱体占 ~230px，卡位落进舱体
// 范围被 z-2 的舱盖住头部（2026-08-27 实测事故）。舱是临时面（打字/Esc
// 即收），收舱后 RO 触发重测，卡回到行位。
const dockSlotEl = ref<HTMLElement | null>(null)
const topReservePx = ref(0)
let _dockRO: ResizeObserver | null = null
function _measureTopReserve() {
  const el = dockSlotEl.value
  if (!el) { topReservePx.value = 0; return }
  topReservePx.value = el.offsetTop + el.offsetHeight + 6
}
watch(dockSlotEl, (el) => {
  _dockRO?.disconnect()
  _dockRO = null
  if (!el) return
  _dockRO = new ResizeObserver(_measureTopReserve)
  _dockRO.observe(el)
  _measureTopReserve()
}, { flush: 'post' })
// offsetTop 变化（谋篇行折叠/出现）不触发 RO，补测；dock 自身高度变化走 RO
watch([spineCollapsed, () => props.spineProgress], () => { nextTick(_measureTopReserve) })
onBeforeUnmount(() => { _dockRO?.disconnect(); _dockRO = null })
const labels = computed(() => props.suggestions.map((h) => h.node_label))
const { anchors } = usePerceptionAlignment(labels, bandEl, topReservePx)

// 锚定卡（找到正文位置）—— absolute 渲染到对应行。
// 碰撞避让（2026-08-28 重叠修复）：各卡锚 Y 独立而来，相邻行/同 label 多条
// 提醒会叠在一起——stackAnchoredTops 按 Y 排序逐张下推（卡高按内容估算：
// 卡体 ~38px + detail 行数 × 15px + 间距）。
function cardHeight(h: CanonHint): number {
  const detail = h.detail || ''
  const lines = detail ? Math.min(6, Math.ceil(detail.length / 11)) : 0
  return 38 + (lines ? lines * 15 + 6 : 0) + 7
}
const located = computed(() => {
  const tops = anchors.value.map((t) => (t === null || t === undefined ? null : t))
  const stacked = stackAnchoredTops(tops, props.suggestions.map(cardHeight))
  const out: { hint: CanonHint; top: number }[] = []
  for (let i = 0; i < props.suggestions.length; i++) {
    const top = stacked[i]
    if (top !== null && top !== undefined) {
      out.push({ hint: props.suggestions[i], top })
    }
  }
  return out
})
// 兜底卡（找不到正文位置：orphan/leak 等）—— 底部列表 + 折叠
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
</script>

<template>
  <aside ref="bandEl" class="perception-band">
    <!-- 顶部固定区：header + 谋篇进度行 + 镜头碎片舱（slot） -->
    <div class="band-header">Canon 感知</div>
    <!-- 谋篇进度行（P1.4 M2 §3.2）：意图短语 + ⚑ 旗标；hit 判定后旗标实心（划 todo 的满足感） -->
    <div v-if="spineProgress" class="spine-progress">
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
    <div ref="dockSlotEl" class="band-dock-slot">
      <slot name="dock" />
    </div>
    <div v-if="suggestions.length === 0" class="band-empty">
      写到相关角色 / 伏笔时，<br />这里会浮现提醒
    </div>

    <!-- 锚定层：感知卡按正文行 Y 对齐（absolute，pointer-events 放行顶部区交互） -->
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
            title="收起此类提醒（同类多次收起后将少提，可在收件箱恢复）"
            @click.stop="emit('dismiss-hint', { kind: item.hint.kind, label: item.hint.node_label })"
          >×</button>
        </div>
        <div v-if="item.hint.detail" class="hint-card__detail">{{ item.hint.detail }}</div>
      </div>
    </div>

    <!-- 兜底区：找不到正文位置的提醒（底部固定，流式列表 + 折叠） -->
    <div v-if="floating.length" class="hint-floating">
      <div class="band-sub">其他提醒</div>
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
            title="收起此类提醒（同类多次收起后将少提，可在收件箱恢复）"
            @click.stop="emit('dismiss-hint', { kind: hint.kind, label: hint.node_label })"
          >×</button>
        </div>
        <div v-if="hint.detail" class="hint-card__detail">{{ hint.detail }}</div>
      </div>
      <button v-if="floatingHidden > 0" class="band-more" @click="floatingExpanded = true">
        +{{ floatingHidden }} 更多
      </button>
    </div>
  </aside>
</template>

<style scoped>
.perception-band {
  width: 260px;
  flex-shrink: 0;
  position: relative;
  overflow: hidden;
  height: 100%;
  order: -1;  /* 放正文左侧，避开右边 InspectorPanel 抽屉遮挡 */
  border-right: 1px solid #e2e8f0;
  background: rgba(248, 250, 252, 0.6);
}
.band-header {
  position: relative;
  z-index: 2;
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: #94a3b8;
  margin-bottom: 8px;
  padding: 8px 8px 0;
  font-family: ui-monospace, monospace;
}

/* 谋篇进度行（P1.4 M2）：意图短语 + 旗标，点击行头收起清单 */
.spine-progress {
  position: relative;
  z-index: 2;
  padding: 0 8px 6px;
  margin-bottom: 6px;
  border-bottom: 1px dashed rgba(148, 163, 184, 0.35);
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
  font-size: 11px;
  font-family: var(--font-heading, inherit);
  color: var(--text-secondary, #6b6560);
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
  font-size: 12px;
  color: #94a3b8;
}
.spine-flag--hit {
  color: var(--accent-500, #7c6aad);
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
  font-size: 11px;
  color: var(--text-secondary, #6b6560);
}
.spine-progress__item.is-hit {
  color: var(--accent-500, #7c6aad);
}
.spine-progress__item.is-dropped {
  opacity: 0.5;
  text-decoration: line-through;
}
.spine-progress__hint {
  font-size: 10px;
  color: #94a3b8;
}
/* 顶部固定区 slot（SparkDock）wrapper：实高供锚定卡避让（topReservePx），z-2 盖在锚定层之上 */
.band-dock-slot {
  position: relative;
  z-index: 2;
}
.band-empty {
  font-size: 11px;
  color: #cbd5e1;
  line-height: 1.6;
  padding: 12px 8px;
}

/* 锚定层：覆盖整个带，pointer-events 放行（不挡顶部区交互）；卡片自身回收事件 */
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

/* 兜底区：底部固定，顶部渐变避免和锚定卡硬碰 */
.hint-floating {
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  max-height: 55%;
  overflow-y: auto;
  padding: 14px 8px 8px;
  background: linear-gradient(to top, rgba(248, 250, 252, 0.98) 72%, rgba(248, 250, 252, 0));
  z-index: 3;
}
.band-sub {
  font-size: 9px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: #94a3b8;
  margin-bottom: 5px;
  font-family: ui-monospace, monospace;
}
.band-more {
  margin-top: 4px;
  padding: 4px;
  width: 100%;
  border: 1px dashed #cbd5e1;
  border-radius: 6px;
  background: transparent;
  color: #64748b;
  font-size: 11px;
  cursor: pointer;
}
.band-more:hover {
  background: #f1f5f9;
  border-color: #94a3b8;
}

.hint-list,
.hint-card {
  /* 卡片基类（锚定 + 兜底共用） */
}
.hint-card {
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 7px 9px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
  margin-bottom: 6px;
}
.hint-card__head {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-bottom: 3px;
}
.hint-card__icon {
  font-size: 12px;
  line-height: 1;
}
.hint-card__label {
  font-size: 12px;
  font-weight: 600;
  color: #334155;
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.hint-card__tag {
  font-size: 9px;
  padding: 1px 5px;
  border-radius: 9999px;
  background: #f1f5f9;
  color: #64748b;
  flex-shrink: 0;
}
/* 学着闭嘴：× 收起按钮默认隐身、悬停卡片浮现（常驻 × 是视觉噪声——学着闭嘴先从自己做起） */
.hint-card__dismiss {
  flex-shrink: 0;
  border: none;
  background: none;
  padding: 0 2px;
  font-size: 13px;
  line-height: 1;
  color: #94a3b8;
  cursor: pointer;
  opacity: 0;
  transition: opacity 0.15s ease;
}
.hint-card:hover .hint-card__dismiss {
  opacity: 0.85;
}
.hint-card__dismiss:hover {
  color: #475569;
}
.hint-card__detail {
  font-size: 11px;
  color: #64748b;
  line-height: 1.5;
}
/* 角色出场 —— indigo */
.hint-card--character {
  border-color: #c7d2fe;
  background: #eef2ff;
}
.hint-card--character .hint-card__tag {
  background: #e0e7ff;
  color: #4f46e5;
}
/* 伏笔回收 —— amber */
.hint-card--hook {
  border-color: #fcd34d;
  background: #fffbeb;
}
.hint-card--hook .hint-card__tag {
  background: #fef3c7;
  color: #b45309;
}
/* private 泄露 —— rose（高优先级） */
.hint-card--leak {
  border-color: #fca5a5;
  background: #fef2f2;
}
.hint-card--leak .hint-card__label {
  color: #b91c1c;
}
.hint-card--leak .hint-card__tag {
  background: #fee2e2;
  color: #b91c1c;
}
/* 文风漂移 —— violet（S4 补全） */
.hint-card--style {
  border-color: #c4b5fd;
  background: #f5f3ff;
}
.hint-card--style .hint-card__tag {
  background: #ede9fe;
  color: #7c3aed;
}
/* 收件箱积压 —— teal（A5c，参照 style_drift 先例的柔性提醒色档） */
.hint-card--inbox {
  border-color: #5eead4;
  background: #f0fdfa;
}
.hint-card--inbox .hint-card__tag {
  background: #ccfbf1;
  color: #0f766e;
}
</style>
