<script setup lang="ts">
/**
 * 文风页 ④「对账」——每章实测指纹 vs 目标区间（反馈环的可视化入口）。
 *
 * 数据来自 GET /style-fingerprint?with_chapters=true（章指纹实时计算，
 * 与审计侧同一把尺子——句长 CV / 对话占比可直接与质量报告互相印证）。
 * 纯展示：两张带参考底色带的折线图（SVG 内联）+ 一句人话总结；
 * 判断权留给作者，页面只呈现事实（设计稿 §6.4 术语人性化）。
 */
import { computed } from 'vue'
import type { StyleFingerprint } from '../../../types'

const props = defineProps<{
  fingerprint: StyleFingerprint | null
}>()

const chapters = computed(() => props.fingerprint?.chapters || [])

// ============================================================
// 图表几何（viewBox 600x120，内边距 8）
// ============================================================
const W = 600
const H = 120
const PAD = 10

interface SeriesSpec {
  values: number[]
  /** 底色带 [lo, hi]，null 则不画带 */
  band: [number, number] | null
  /** y 轴上界 */
  yMax: number
}

function buildPolyline(spec: SeriesSpec): string {
  const n = spec.values.length
  if (n === 0) return ''
  const x = (i: number) => (n === 1 ? W / 2 : PAD + (i * (W - 2 * PAD)) / (n - 1))
  const y = (v: number) => H - PAD - (Math.min(v, spec.yMax) / spec.yMax) * (H - 2 * PAD)
  return spec.values.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(' ')
}

function bandRect(spec: SeriesSpec) {
  if (!spec.band) return null
  const y = (v: number) => H - PAD - (Math.min(v, spec.yMax) / spec.yMax) * (H - 2 * PAD)
  const top = y(spec.band[1])
  const bottom = y(spec.band[0])
  return { y: top, height: Math.max(2, bottom - top) }
}

function pointCoords(spec: SeriesSpec): Array<{ x: number; y: number; out: boolean }> {
  const n = spec.values.length
  if (n === 0) return []
  const x = (i: number) => (n === 1 ? W / 2 : PAD + (i * (W - 2 * PAD)) / (n - 1))
  const y = (v: number) => H - PAD - (Math.min(v, spec.yMax) / spec.yMax) * (H - 2 * PAD)
  return spec.values.map((v, i) => ({
    x: x(i),
    y: y(v),
    out: !!spec.band && (v < spec.band[0] || v > spec.band[1]),
  }))
}

// ---- 句长起伏（CV）----
const cvSeries = computed<SeriesSpec>(() => {
  const [lo, hi] = props.fingerprint?.reference.cv_healthy || [0.35, 0.8]
  return {
    values: chapters.value.map(c => c.fingerprint.sentence_len_cv),
    band: [lo, hi],
    yMax: 1.2,
  }
})

// ---- 对话占比（目标 ±0.2 容差，与 DialogueAuditor 同规则）----
const dialogueSeries = computed<SeriesSpec>(() => {
  const target = props.fingerprint?.reference.dialogue_target
  const band: [number, number] = target !== null && target !== undefined
    ? [Math.max(0, target - 0.2), Math.min(1, target + 0.2)]
    : [0.2, 0.5]
  return {
    values: chapters.value.map(c => c.fingerprint.dialogue_ratio),
    band,
    yMax: 1,
  }
})

// ============================================================
// 人话总结（只呈现事实，判断权留给作者）
// ============================================================
const summary = computed<string[]>(() => {
  const list = chapters.value
  if (list.length === 0) return []
  const notes: string[] = []
  const last = list.slice(-3)
  const avg = (arr: number[]) => arr.reduce((a, b) => a + b, 0) / (arr.length || 1)

  const [cvLo, cvHi] = props.fingerprint?.reference.cv_healthy || [0.35, 0.8]
  const avgCv = avg(last.map(c => c.fingerprint.sentence_len_cv))
  if (avgCv < cvLo) {
    notes.push(`最近三章句长起伏 ${avgCv.toFixed(2)}，低于健康下限 ${cvLo}——句子偏匀速，是 AI 腔的典型征兆。`)
  } else if (avgCv > cvHi) {
    notes.push(`最近三章句长起伏 ${avgCv.toFixed(2)}，节奏很跳（高于 ${cvHi}）——若非有意为之，检查短句连发。`)
  } else {
    notes.push(`句长起伏 ${avgCv.toFixed(2)}，在健康区间内。`)
  }

  const target = props.fingerprint?.reference.dialogue_target
  const [dLo, dHi] = dialogueSeries.value.band || [0.2, 0.5]
  const avgDlg = avg(last.map(c => c.fingerprint.dialogue_ratio))
  const targetLabel = target !== null && target !== undefined ? `目标 ${Math.round(target * 100)}%` : '默认目标'
  if (avgDlg < dLo) {
    notes.push(`对话占比 ${Math.round(avgDlg * 100)}%，低于${targetLabel}区间——叙事密度偏高。`)
  } else if (avgDlg > dHi) {
    notes.push(`对话占比 ${Math.round(avgDlg * 100)}%，高于${targetLabel}区间——环境与心理描写可能不足。`)
  } else {
    notes.push(`对话占比 ${Math.round(avgDlg * 100)}%，贴合${targetLabel}。`)
  }

  // 与语料实测对照：AI 腔在你不知觉时回归的探测器
  const corpusDlg = props.fingerprint?.corpus.dialogue_ratio
  if (corpusDlg !== undefined && Math.abs(avgDlg - corpusDlg) > 0.15) {
    notes.push(`与你的笔迹差距明显（语料实测对话 ${Math.round(corpusDlg * 100)}%）——值得回头看一眼这几章。`)
  }
  return notes
})

const rangeLabel = computed(() => {
  if (chapters.value.length < 2) return ''
  const first = chapters.value[0]
  const last = chapters.value[chapters.value.length - 1]
  return `第${first.chapter_number}章 → 第${last.chapter_number}章（${chapters.value.length} 章正文）`
})
</script>

<template>
  <section id="style-sec-recon" class="style-section">
    <header class="sec-head">
      <h2 class="sec-title">对账</h2>
      <p class="sec-sub">每章实测 vs 目标区间——同一把尺子量你的样本和 AI 的章节，数字可直接互相印证。</p>
    </header>

    <div v-if="chapters.length === 0" class="empty-note">本书还没有章节正文——开始写作后，这里会长出趋势线。</div>
    <div v-else-if="chapters.length === 1" class="empty-note">已有第 {{ chapters[0].chapter_number }} 章指纹——第 2 章之后可看趋势。</div>

    <template v-else>
      <p class="range-label">{{ rangeLabel }}</p>

      <!-- 句长起伏 -->
      <div class="chart-card">
        <div class="chart-head">
          <span class="chart-title">句长起伏（健康带 {{ cvSeries.band?.[0] }}~{{ cvSeries.band?.[1] }}）</span>
        </div>
        <svg :viewBox="`0 0 ${W} ${H}`" class="chart" preserveAspectRatio="none" role="img" aria-label="句长起伏趋势">
          <rect
            v-if="bandRect(cvSeries)"
            :x="PAD" :y="bandRect(cvSeries)!.y" :width="W - 2 * PAD" :height="bandRect(cvSeries)!.height"
            class="band"
          />
          <polyline :points="buildPolyline(cvSeries)" class="line" />
          <circle
            v-for="(p, i) in pointCoords(cvSeries)" :key="i"
            :cx="p.x" :cy="p.y" r="2.5" :class="p.out ? 'dot-out' : 'dot'"
          />
        </svg>
      </div>

      <!-- 对话占比 -->
      <div class="chart-card">
        <div class="chart-head">
          <span class="chart-title">
            对话占比（目标带 {{ Math.round((dialogueSeries.band?.[0] || 0) * 100) }}%~{{ Math.round((dialogueSeries.band?.[1] || 1) * 100) }}%）
          </span>
        </div>
        <svg :viewBox="`0 0 ${W} ${H}`" class="chart" preserveAspectRatio="none" role="img" aria-label="对话占比趋势">
          <rect
            v-if="bandRect(dialogueSeries)"
            :x="PAD" :y="bandRect(dialogueSeries)!.y" :width="W - 2 * PAD" :height="bandRect(dialogueSeries)!.height"
            class="band"
          />
          <polyline :points="buildPolyline(dialogueSeries)" class="line" />
          <circle
            v-for="(p, i) in pointCoords(dialogueSeries)" :key="i"
            :cx="p.x" :cy="p.y" r="2.5" :class="p.out ? 'dot-out' : 'dot'"
          />
        </svg>
      </div>

      <!-- 人话总结 -->
      <ul class="summary-list">
        <li v-for="(note, i) in summary" :key="i">{{ note }}</li>
      </ul>
    </template>
  </section>
</template>

<style scoped>
.style-section {
  padding: 1.25rem 0 2rem;
  scroll-margin-top: 4.5rem;
}
.sec-head {
  margin-bottom: 0.75rem;
}
.sec-title {
  margin: 0;
  font-family: var(--font-heading);
  font-size: 1rem;
  font-weight: 600;
  color: var(--text-primary);
}
.sec-sub {
  margin: 0.25rem 0 0;
  font-size: 0.75rem;
  line-height: 1.6;
  color: var(--text-muted);
}
.empty-note {
  padding: 1rem;
  font-size: 0.75rem;
  text-align: center;
  color: var(--text-muted);
}
.range-label {
  margin: 0 0 0.5rem;
  font-size: 0.6875rem;
  color: var(--text-muted);
}
.chart-card {
  padding: 0.625rem 0.75rem 0.375rem;
  margin-bottom: 0.5rem;
  background: var(--bg-panel);
  border: 1px solid var(--border-color);
  border-radius: 0.5rem;
}
.chart-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 0.25rem;
}
.chart-title {
  font-size: 0.6875rem;
  color: var(--text-muted);
}
.chart {
  display: block;
  width: 100%;
  height: 96px;
}
.band {
  fill: color-mix(in srgb, #10b981 12%, transparent);
}
.line {
  fill: none;
  stroke: var(--accent-500);
  stroke-width: 1.5;
  vector-effect: non-scaling-stroke;
}
.dot {
  fill: var(--accent-500);
}
.dot-out {
  fill: #ef4444;
}
.summary-list {
  margin: 0.5rem 0 0;
  padding-left: 1.125rem;
}
.summary-list li {
  margin-bottom: 0.25rem;
  font-size: 0.75rem;
  line-height: 1.7;
  color: var(--text-secondary);
}
</style>
