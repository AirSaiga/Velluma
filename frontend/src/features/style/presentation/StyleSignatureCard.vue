<script setup lang="ts">
/**
 * 笔迹签名卡（文风页 v4「笔迹谱」·实验室首屏）。
 * 把语料实测画成一张"签名"：句长直方图=墨迹柱，落在朱丝栏（字帖红栏线）
 * 纸面上；金线=对话占比；右侧三枚事实数；标题一句人话总结。
 * 纯展示——数据全部经 props 直传，与指纹区同一份 fingerprint。
 */
import { computed } from 'vue'
import type { StyleFingerprint } from '../../../types'

const props = defineProps<{
  fingerprint: StyleFingerprint | null
  /** 生效禁词条数（事实数之一；实验室视图允许数字） */
  negativeCount: number
}>()

const corpus = computed(() => props.fingerprint?.corpus || null)
const hasCorpus = computed(() => (corpus.value?.word_count || 0) > 0)
const sampleCount = computed(() => props.fingerprint?.sample_count ?? 0)

/** 标题一句人话：句长节奏 × 对话比重（判据同指纹参考，措辞作者语言） */
const headline = computed(() => {
  const fp = corpus.value
  if (!fp) return ''
  const [lo, hi] = props.fingerprint?.reference.cv_healthy || [0.35, 0.8]
  const cv = fp.sentence_len_cv
  const rhythm = cv < lo ? '句子长短很匀' : cv > hi ? '句子长短跳跃很大' : '句子长短相间'
  const d = fp.dialogue_ratio
  const voice = d < 0.2 ? '对话不多，多为叙述' : d > 0.6 ? '大半篇幅是人物开口' : '近一半留给了人物开口'
  return `${rhythm}，${voice}。`
})

// ---- 墨迹图几何（viewBox 420×150；绘图区 y∈[22,128]，基线 y=128，最高柱 106px） ----
interface InkBar {
  label: string
  count: number
  x: number
  y: number
  h: number
  opacity: number
}

const inkBars = computed<InkBar[]>(() => {
  const h = corpus.value?.sentence_len_histogram
  if (!h) return []
  const defs = [
    { key: 'lte5' as const, label: '≤5', x: 34 },
    { key: '6_10' as const, label: '6-10', x: 112 },
    { key: '11_20' as const, label: '11-20', x: 190 },
    { key: '21_30' as const, label: '21-30', x: 268 },
    { key: 'gt30' as const, label: '>30', x: 346 },
  ]
  // 每柱固定微差不透明度——墨迹的有机感（同设计稿）
  const opacities = [0.88, 0.78, 0.95, 0.82, 0.7]
  const max = Math.max(1, ...defs.map(d => h[d.key]))
  return defs.map((d, i) => {
    const hpx = Math.max(4, Math.round((h[d.key] / max) * 106))
    return { label: d.label, count: h[d.key], x: d.x, y: 128 - hpx, h: hpx, opacity: opacities[i] }
  })
})

/** 金线（对话占比）纵坐标：从基线向上按占比折算 */
const goldY = computed(() => {
  const d = corpus.value?.dialogue_ratio ?? 0
  return Math.round(128 - Math.min(1, Math.max(0, d)) * 106)
})
const dialoguePct = computed(() => Math.round((corpus.value?.dialogue_ratio ?? 0) * 100))
</script>

<template>
  <section id="style-sec-signature" class="signature">
    <template v-if="hasCorpus">
      <div class="sig-left">
        <div class="sig-eyebrow">你 的 笔 迹</div>
        <h2 class="sig-headline">{{ headline }}</h2>
        <p class="sig-cap">由 <b class="tnum">{{ sampleCount }}</b> 条亲笔字实测得出——不是 AI 猜的。</p>
      </div>

      <div class="sig-plot" title="墨迹柱=各长度段的句子数量；金线=对话占比">
        <svg viewBox="0 0 420 150" role="img" aria-label="句长分布墨迹图">
          <g>
            <rect
              v-for="bar in inkBars"
              :key="bar.label"
              :x="bar.x" :y="bar.y" width="38" :height="bar.h" rx="2"
              fill="var(--text-primary)" :opacity="bar.opacity"
            />
          </g>
          <g class="tnum" text-anchor="middle">
            <text v-for="bar in inkBars" :key="bar.label" :x="bar.x + 19" :y="bar.y - 8">{{ bar.count }}</text>
          </g>
          <!-- 朱丝基线 -->
          <line x1="14" y1="128" x2="406" y2="128" stroke="var(--cinnabar-bright)" stroke-width="1.5" opacity=".55" />
          <!-- 金线：对话占比 -->
          <line x1="14" :y1="goldY" x2="380" :y2="goldY" stroke="var(--gold)" stroke-width="2" opacity=".75" />
          <path :d="`M380 ${goldY} l7 -3.5 v7 z`" fill="var(--gold)" opacity=".85" />
          <text :x="392" :y="goldY - 6" class="gold-label tnum">对话 {{ dialoguePct }}%</text>
          <!-- 桶标签 -->
          <g text-anchor="middle">
            <text v-for="bar in inkBars" :key="bar.label" :x="bar.x + 19" y="146">{{ bar.label }}</text>
          </g>
          <text x="14" y="146">字</text>
        </svg>
      </div>

      <div class="sig-right">
        <div class="sig-fact"><span class="k">亲笔字</span><span class="v tnum">{{ sampleCount }}<small>条</small></span></div>
        <div class="sig-fact"><span class="k">句长起伏</span><span class="v tnum">{{ corpus!.sentence_len_cv.toFixed(2) }}</span></div>
        <div class="sig-fact"><span class="k">拦下的词</span><span class="v tnum">{{ negativeCount }}<small>条</small></span></div>
      </div>
    </template>

    <div v-else class="empty-note">还没有可量的字——工坊贴入亲笔字后，这里会长出你的笔迹签名。</div>
  </section>
</template>

<style scoped>
/* 签名卡=纸面+朱丝栏（字帖红栏线，token 混配，五主题×明暗自动成立） */
.signature {
  position: relative;
  display: grid;
  grid-template-columns: minmax(220px, 300px) 1fr minmax(180px, 220px);
  gap: 0 var(--space-8);
  align-items: stretch;
  padding: var(--space-8);
  background-color: var(--paper-bg);
  background-image: repeating-linear-gradient(90deg,
    transparent 0 55px,
    color-mix(in srgb, var(--cinnabar-bright) 14%, transparent) 55px 56px);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-paper);
}
.signature::after {
  content: '筆跡';
  position: absolute;
  right: 18px;
  bottom: 14px;
  font-family: var(--font-heading);
  font-size: var(--text-xs);
  font-weight: 700;
  writing-mode: vertical-rl;
  letter-spacing: 0.3em;
  color: var(--cinnabar);
  opacity: 0.5;
  border: 1px solid color-mix(in srgb, var(--cinnabar) 45%, transparent);
  border-radius: 3px;
  padding: 6px 3px;
  pointer-events: none;
}
.sig-eyebrow {
  font-size: var(--text-xs);
  letter-spacing: 0.18em;
  color: var(--cinnabar);
  font-weight: 600;
}
.sig-headline {
  margin-top: var(--space-3);
  font-family: var(--font-heading);
  font-size: var(--text-3xl);
  font-weight: 600;
  line-height: 1.45;
  letter-spacing: 0.02em;
  color: var(--text-primary);
}
.sig-cap {
  margin-top: var(--space-4);
  font-size: var(--text-sm);
  line-height: 1.7;
  color: var(--text-muted);
}
.sig-plot {
  display: flex;
  flex-direction: column;
  justify-content: flex-end;
  min-width: 0;
}
.sig-plot svg {
  width: 100%;
  height: auto;
}
.sig-plot text {
  font-size: 12px;
  fill: var(--text-muted);
}
.sig-plot .gold-label {
  fill: var(--gold);
  font-family: var(--font-heading);
}
.sig-right {
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: var(--space-3);
}
.sig-fact {
  display: flex;
  align-items: baseline;
  gap: var(--space-3);
  padding: var(--space-2) var(--space-3);
  border-left: 2px solid color-mix(in srgb, var(--gold) 55%, transparent);
}
.sig-fact .k {
  flex: 1;
  font-size: var(--text-xs);
  color: var(--text-muted);
}
.sig-fact .v {
  font-family: var(--font-heading);
  font-size: var(--text-lg);
  font-weight: 600;
  color: var(--text-primary);
}
.sig-fact .v small {
  margin-left: 2px;
  font-size: var(--text-xs);
  font-weight: 400;
  color: var(--text-muted);
}
.empty-note {
  padding: var(--space-8);
  font-size: var(--text-sm);
  text-align: center;
  color: var(--text-muted);
}
@container stylepage (max-width: 60rem) {
  .signature {
    grid-template-columns: 1fr;
  }
}
</style>
