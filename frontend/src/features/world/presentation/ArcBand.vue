<script setup lang="ts">
/**
 * 伏笔弧线带（M3）：PlotLedger 世界时间锚的 SVG 弧线投影。
 *
 * 弧线从埋设时刻画到回收时刻；悬空（open 无回收锚）延伸到右缘渐隐 + 尾标「悬空」。
 * 交互：点弧线 → 详情（父级弹层）；拖端点圆点 → 改埋设/回收时刻（拖动本地预览，
 * 松手才 emit 持久化——高频微调不配 API 轰炸）。
 */
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import type { Foreshadow } from '../engine/types'

const props = withDefaults(
  defineProps<{
    foreshadows: Foreshadow[]
    /** 视野窗口终点（时间戳） */
    maxTime: number
    /** 视野窗口起点（默认 0 = 创世；手动框定视野时与时间轴同窗） */
    minTime?: number
    /** 只看悬空（隐藏已回收） */
    onlyOpen?: boolean
  }>(),
  { minTime: 0 },
)

const emit = defineEmits<{
  'arc-click': [f: Foreshadow, at: { x: number; y: number }]
  'update-times': [id: string, patch: { world_time_planted?: number; world_time_resolved?: number }]
}>()

const H = 30
const bandRef = ref<HTMLDivElement | null>(null)
const width = ref(600)
let resizeObs: ResizeObserver | null = null

onMounted(() => {
  if (!bandRef.value) return
  resizeObs = new ResizeObserver((entries) => {
    width.value = entries[0].contentRect.width || 600
  })
  resizeObs.observe(bandRef.value)
})
onBeforeUnmount(() => resizeObs?.disconnect())

/** 拖动中的本地时间覆盖（松手 emit 后清空） */
const dragOverride = ref<{ id: string; patch: Partial<Record<'planted' | 'resolved', number>> } | null>(null)

interface PlacedArc {
  f: Foreshadow
  x1: number
  x2: number
  dangling: boolean
}

const arcs = computed<PlacedArc[]>(() => {
  const span = Math.max(1, props.maxTime - props.minTime)
  const t2x = (t: number) =>
    Math.min(
      width.value - 4,
      Math.max(4, ((t - props.minTime) / span) * width.value),
    )
  const out: PlacedArc[] = []
  for (const f of props.foreshadows) {
    if (f.status === 'dropped') continue
    if (props.onlyOpen && f.status !== 'open') continue
    let p = f.world_time_planted
    let r = f.world_time_resolved
    const ov = dragOverride.value?.id === f.id ? dragOverride.value.patch : null
    if (ov?.planted != null) p = ov.planted
    if (ov?.resolved != null) r = ov.resolved
    if (p == null) continue // 无世界锚的伏笔不在弧线带显示（章锚换算后续补）
    const dangling = f.status === 'open'
    out.push({
      f,
      x1: t2x(p),
      x2: t2x(r != null ? r : props.maxTime),
      dangling,
    })
  }
  return out
})

function arcPath(a: PlacedArc): string {
  const mid = (a.x1 + a.x2) / 2
  const span = Math.abs(a.x2 - a.x1)
  const h = Math.max(6, Math.min(H - 6, 4 + span * 0.12))
  return `M ${a.x1} ${H - 3} Q ${mid} ${H - 3 - h * 2} ${a.x2} ${H - 3}`
}

function onArcClick(a: PlacedArc, e: MouseEvent) {
  emit('arc-click', a.f, { x: e.clientX, y: e.clientY })
}

// ===== 端点拖拽（planted / resolved 两个把手）=====

let dragging: { id: string; kind: 'planted' | 'resolved' } | null = null

function x2t(x: number): number {
  const min = props.minTime
  const max = props.maxTime
  return Math.round(Math.min(max, Math.max(min, min + (x / width.value) * (max - min))))
}

function onHandleDown(e: PointerEvent, f: Foreshadow, kind: 'planted' | 'resolved') {
  e.stopPropagation()
  ;(e.target as SVGElement).setPointerCapture?.(e.pointerId)
  dragging = { id: f.id, kind }
  dragOverride.value = { id: f.id, patch: {} }
}

function onHandleMove(e: PointerEvent) {
  if (!dragging || !bandRef.value) return
  const rect = bandRef.value.getBoundingClientRect()
  const t = x2t(e.clientX - rect.left)
  dragOverride.value = {
    id: dragging.id,
    patch: { ...dragOverride.value?.patch, [dragging.kind]: t },
  }
}

function onHandleUp() {
  if (!dragging || !dragOverride.value) return
  const { id, kind } = dragging
  const t = dragOverride.value.patch[kind]
  dragging = null
  dragOverride.value = null
  if (t != null) {
    emit('update-times', id, {
      [`world_time_${kind}`]: t,
    } as { world_time_planted?: number; world_time_resolved?: number })
  }
}

watch(
  () => props.foreshadows,
  () => {
    // 外部数据变化（如持久化完成）时丢弃残留拖动态
    dragging = null
    dragOverride.value = null
  },
)

// ===== 回收瞬间金光：检测 world_time_resolved null→值（回收闭合仪式感）=====
const flashIds = ref(new Set<string>())
watch(
  () => props.foreshadows,
  (list, old) => {
    if (!old) return
    const prevResolved = new Map(old.map((f) => [f.id, f.world_time_resolved]))
    for (const f of list) {
      const before = prevResolved.get(f.id)
      if (f.world_time_resolved != null && before == null) {
        flashIds.value = new Set(flashIds.value).add(f.id)
        setTimeout(() => {
          const s = new Set(flashIds.value)
          s.delete(f.id)
          flashIds.value = s
        }, 1300)
      }
    }
  },
)
</script>

<template>
  <div ref="bandRef" class="wab" @pointermove="onHandleMove" @pointerup="onHandleUp" @pointercancel="onHandleUp">
    <svg :width="width" :height="H" class="wab-svg">
      <g v-for="a in arcs" :key="a.f.id">
        <path
          :d="arcPath(a)"
          class="wab-arc"
          :class="{ 'wab-arc--open': a.dangling, 'wab-arc--closed': !a.dangling, 'wab-arc--flash': flashIds.has(a.f.id) }"
          @click="onArcClick(a, $event)"
        />
        <!-- 尾标：悬空 -->
        <text
          v-if="a.dangling"
          :x="a.x2 - 2"
          :y="H - 6"
          class="wab-tail"
          text-anchor="end"
          @click="onArcClick(a, $event)"
        >悬空</text>
        <!-- 端点把手（可拖改时刻） -->
        <circle
          :cx="a.x1"
          :cy="H - 3"
          r="4"
          class="wab-handle"
          @pointerdown="onHandleDown($event, a.f, 'planted')"
        >
          <title>拖动改埋设时刻</title>
        </circle>
        <circle
          v-if="a.f.world_time_resolved != null"
          :cx="a.x2"
          :cy="H - 3"
          r="4"
          class="wab-handle wab-handle--resolved"
          @pointerdown="onHandleDown($event, a.f, 'resolved')"
        >
          <title>拖动改回收时刻</title>
        </circle>
      </g>
    </svg>
  </div>
</template>

<style scoped>
.wab {
  position: relative;
  height: 30px;
  user-select: none;
}
.wab-svg {
  display: block;
}
.wab-arc {
  fill: none;
  stroke-width: 2;
  cursor: pointer;
  transition: stroke-width 0.12s;
}
.wab-arc:hover {
  stroke-width: 3.5;
}
.wab-arc--open {
  stroke: #a855f7;
  opacity: 0.85;
  stroke-dasharray: 5 3;
}
.wab-arc--closed {
  stroke: #64748b;
  opacity: 0.45;
}
.wab-tail {
  font-size: 9px;
  fill: #a855f7;
  opacity: 0.8;
  cursor: pointer;
  animation: wab-tail-pulse 2s ease-in-out infinite;
}
@keyframes wab-tail-pulse {
  50% {
    opacity: 0.35;
  }
}
/* 回收瞬间金光（一次性） */
.wab-arc--flash {
  stroke: #c9a227;
  stroke-width: 3.5;
  stroke-dasharray: none;
  animation: wab-flash 1.2s ease-out forwards;
}
@keyframes wab-flash {
  0% {
    filter: drop-shadow(0 0 0 rgba(201, 162, 39, 0));
  }
  25% {
    filter: drop-shadow(0 0 6px rgba(201, 162, 39, 0.9));
  }
  100% {
    filter: drop-shadow(0 0 0 rgba(201, 162, 39, 0));
  }
}
.wab-handle {
  fill: #a855f7;
  stroke: var(--bg-canvas, #fff);
  stroke-width: 1.5;
  cursor: ew-resize;
}
.wab-handle:hover {
  r: 5.5;
}
.wab-handle--resolved {
  fill: #64748b;
}
</style>
