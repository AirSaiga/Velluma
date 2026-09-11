<script setup lang="ts">
/**
 * 故事线俯视条（大纲板方案 A）：章号轴上的全书一屏俯视。
 *
 * 一根横轴按章号等距分列，自上而下三段：
 *   张力折线（读者镜像 tension_curve，空心点=大释放章）
 *   伏笔弧线（PlotLedger 埋→收；虚线=还没收；分道堆叠防压线）
 *   章节刻（朱点=该章计划揭示的真相，与时间轴 C3 同语义色）
 * 点列 → emit seek 滚动到对应章卡。弧线视觉语言沿用世界页弧线带（ArcBand），
 * 但轴是章号（叙事节奏），与世界时间轴（设定事实）正交。
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { assignArcLanes, type StorylineArc, type StorylineTensionSample } from '../engine/storyline'

export interface AxisChapter {
  id: string
  number: number
  title: string
}

const props = defineProps<{
  chapters: AxisChapter[]
  arcs: StorylineArc[]
  tension: StorylineTensionSample[]
  /** 章号 → 该章计划揭示的真相标题 */
  reveals: Map<number, string[]>
}>()

const emit = defineEmits<{ seek: [chapterId: string] }>()

const bandRef = ref<HTMLDivElement | null>(null)
const width = ref(800)
let resizeObs: ResizeObserver | null = null

onMounted(() => {
  if (!bandRef.value) return
  resizeObs = new ResizeObserver((entries) => {
    width.value = entries[0].contentRect.width || 800
  })
  resizeObs.observe(bandRef.value)
})
onBeforeUnmount(() => resizeObs?.disconnect())

const hoverIdx = ref(-1)

// ===== 几何（纯 computed，随 width/chapters 重排）=====

const PAD = 12
const TICK_H = 20
const LANE_H = 13
const TENSION_H = 44

const indexOfNumber = computed(() => {
  const m = new Map<number, number>()
  props.chapters.forEach((c, i) => m.set(c.number, i))
  return m
})

const laned = computed(() =>
  assignArcLanes(props.arcs, indexOfNumber.value, props.chapters.length - 1),
)

const hasTension = computed(() => props.tension.length > 0)
const arcBandH = computed(() => (laned.value.length ? (Math.max(...laned.value.map((a) => a.lane)) + 1) * LANE_H + 6 : 8))
const height = computed(() => (hasTension.value ? TENSION_H : 0) + arcBandH.value + TICK_H)

function colX(i: number): number {
  const n = props.chapters.length
  return PAD + ((i + 0.5) * (width.value - 2 * PAD)) / n
}

const arcBaseY = computed(() => height.value - TICK_H + 4)

interface DrawnArc {
  key: string
  d: string
  x1: number
  x2: number
  dot: boolean
  lane: number
  dangling: boolean
  tooltip: string
}

const drawnArcs = computed<DrawnArc[]>(() =>
  laned.value.map((a) => {
    const x1 = colX(a.start)
    const x2 = colX(a.end)
    const base = arcBaseY.value
    const peak = base - LANE_H * (a.lane + 1) * 0.92
    const tooltip = a.resolved
      ? `第${a.fromN}章埋 → 第${a.toN}章收 · ${a.content}`
      : `第${a.fromN}章埋 · 还没收 · ${a.content}`
    return {
      key: a.id,
      d: `M ${x1} ${base} Q ${(x1 + x2) / 2} ${base - 2 * (base - peak)} ${x2} ${base}`,
      x1,
      x2,
      dot: Math.abs(x2 - x1) < 2,
      lane: a.lane,
      dangling: !a.resolved,
      tooltip,
    }
  }),
)

const tensionPoints = computed(() =>
  props.tension.map((t) => {
    const i = indexOfNumber.value.get(t.n)
    if (i == null) return null
    const x = colX(i)
    const top = 8
    const y = top + (1 - t.tension / 10) * (TENSION_H - 14)
    return { x, y, t }
  }).filter((p): p is { x: number; y: number; t: StorylineTensionSample } => p != null),
)

const tensionPath = computed(() =>
  tensionPoints.value.map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x} ${p.y}`).join(' '),
)

interface RevealDot {
  x: number
  y: number
  tooltip: string
}

const revealDots = computed<RevealDot[]>(() => {
  const out: RevealDot[] = []
  props.chapters.forEach((c, i) => {
    const labels = props.reveals.get(c.number)
    if (!labels?.length) return
    out.push({
      x: colX(i),
      y: height.value - 13,
      tooltip: `第${c.number}章计划揭示：${labels.join('；')}`,
    })
  })
  return out
})

function tooltipFor(ch: AxisChapter): string {
  return ch.title ? `第${ch.number}章 · ${ch.title}` : `第${ch.number}章`
}
</script>

<template>
  <div v-if="chapters.length" ref="bandRef" class="axis-wrap">
    <svg :width="width" :height="height" :viewBox="`0 0 ${width} ${height}`" class="axis-svg" aria-label="故事线俯视条">
      <!-- 章列：悬停高亮 + 点击滚到章卡 -->
      <g v-for="(ch, i) in chapters" :key="ch.id">
        <rect
          v-if="hoverIdx === i"
          class="axis-col-hl"
          :x="colX(i) - (width - 2 * PAD) / chapters.length / 2"
          y="0"
          :width="(width - 2 * PAD) / chapters.length"
          :height="height"
        />
        <rect
          class="axis-col-hit"
          :x="colX(i) - (width - 2 * PAD) / chapters.length / 2"
          y="0"
          :width="(width - 2 * PAD) / chapters.length"
          :height="height"
          @mouseenter="hoverIdx = i"
          @mouseleave="hoverIdx = -1"
          @click="emit('seek', ch.id)"
        >
          <title>{{ tooltipFor(ch) }}</title>
        </rect>
        <text
          class="axis-tick"
          :class="{ active: hoverIdx === i }"
          :x="colX(i)"
          :y="height - 3"
          text-anchor="middle"
        >{{ ch.number }}</text>
      </g>

      <!-- 张力折线 -->
      <g v-if="hasTension">
        <path :d="tensionPath" class="axis-tension-line" />
        <g v-for="(p, i) in tensionPoints" :key="`t${i}`">
          <circle
            :cx="p.x"
            :cy="p.y"
            :r="p.t.payoff ? 3 : 2"
            :class="['axis-tension-dot', { payoff: p.t.payoff }]"
          >
            <title>第{{ p.t.n }}章 张力 {{ p.t.tension }}{{ p.t.payoff ? ' · 大释放章' : '' }}</title>
          </circle>
        </g>
      </g>

      <!-- 伏笔弧线（悬空=虚线；同拍重合画点） -->
      <g>
        <template v-for="a in drawnArcs" :key="a.key">
          <circle v-if="a.dot" :cx="a.x1" :cy="arcBaseY - LANE_H * (a.lane + 1) * 0.6" :r="2.5" :class="['axis-arc-dot', { dangling: a.dangling }]">
            <title>{{ a.tooltip }}</title>
          </circle>
          <path v-else :d="a.d" :class="['axis-arc', { dangling: a.dangling }]">
            <title>{{ a.tooltip }}</title>
          </path>
        </template>
      </g>

      <!-- 真相揭示朱点（与时间轴 C3 同语义色 #c25a4a） -->
      <g v-for="(d, i) in revealDots" :key="`r${i}`">
        <circle :cx="d.x" :cy="d.y" r="3" class="axis-reveal">
          <title>{{ d.tooltip }}</title>
        </circle>
      </g>
    </svg>
    <p class="axis-legend">弧线 = 伏笔（虚线 = 还没收）· 朱点 = 该章计划揭的真相 · 折线 = 张力（空心点 = 大释放章）</p>
  </div>
</template>

<style scoped>
.axis-wrap {
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 0.375rem;
  padding: 0.5rem 0.75rem 0.25rem;
  margin-bottom: 1rem;
}

.axis-svg {
  display: block;
}

.axis-col-hl {
  fill: var(--hover-bg);
}

.axis-col-hit {
  fill: transparent;
  cursor: pointer;
}

.axis-tick {
  fill: var(--text-muted);
  font-size: var(--text-xs);
  font-variant-numeric: tabular-nums;
}

.axis-tick.active {
  fill: var(--text-primary);
  font-weight: 600;
}

.axis-tension-line {
  fill: none;
  stroke: var(--accent-600);
  stroke-width: 1.25;
  pointer-events: none;
}

.axis-tension-dot {
  fill: var(--accent-500);
  pointer-events: none;
}

.axis-tension-dot.payoff {
  fill: var(--bg-panel);
  stroke: var(--accent-600);
  stroke-width: 1.5;
}

.axis-arc {
  fill: none;
  stroke: var(--accent-500);
  stroke-width: 1.25;
  pointer-events: none;
}

.axis-arc.dangling {
  stroke: var(--accent-400);
  stroke-dasharray: 3 3;
  opacity: 0.75;
}

.axis-arc-dot {
  fill: var(--accent-500);
  pointer-events: none;
}

.axis-arc-dot.dangling {
  fill: var(--accent-400);
  opacity: 0.75;
}

.axis-reveal {
  fill: #c25a4a; /* 朱砂语义色（真相层视觉签名，与 WorldTimeline 揭示朱点同值） */
}

.axis-legend {
  font-size: var(--text-xs);
  color: var(--text-muted);
  margin: 0.125rem 0 0.25rem;
}
</style>
