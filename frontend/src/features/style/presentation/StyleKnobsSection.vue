<script setup lang="ts">
/**
 * 文风页「意图」区（S4 大旋钮）——四个维度五档 + 自动档 + 风格预设。
 *
 * 原则（设计稿 §6.4 拒绝假精确）：
 * - 档位制而非连续滑条（用户对 0.35 vs 0.40 无感知）
 * - 默认**自动档** = 不注入该维度，交给画像与 few-shot 样本（能测量的显示实测锚点）
 * - 拨离实测太远 → 轻提示「有意转型吗？」（防误触也防自欺，判断权留给作者）
 * - 对话旋钮直接落 dialogue_ratio_target（真实消费方：DialogueAuditor/ADF 契约）
 *
 * 纯展示：档位状态经 props/emits 与容器交互。
 */
import { computed } from 'vue'
import type { StyleKnobKey } from '../../../types'

/** 旋钮定义（语义与后端 services/style/knobs.py 同一套，档名此处为准渲染） */
const KNOBS: Array<{
  key: StyleKnobKey
  label: string
  tiers: string[]
}> = [
  { key: 'rhythm', label: '快慢', tiers: ['极快', '偏快', '适中', '偏慢', '极慢'] },
  { key: 'register', label: '文白', tiers: ['极白', '偏白', '适中', '偏文', '极文'] },
  { key: 'density', label: '浓淡', tiers: ['极淡', '偏淡', '适中', '偏浓', '极浓'] },
  { key: 'warmth', label: '冷热', tiers: ['极冷', '偏冷', '适中', '偏热', '极热'] },
]

/** 对话旋钮五档 → 目标值（落 dialogue_ratio_target；自动=不设目标） */
const DIALOGUE_TIERS: Array<{ label: string; value: number }> = [
  { label: '极少', value: 0.1 },
  { label: '偏少', value: 0.25 },
  { label: '适中', value: 0.4 },
  { label: '偏多', value: 0.6 },
  { label: '极多', value: 0.8 },
]

/** 风格预设：档位组合 + 画像模板补丁（描述自撰，只作起点不锁死） */
const PRESETS = [
  {
    id: 'austere',
    label: '冷峻短句',
    knobs: { rhythm: 1, register: 3, density: 1, warmth: 1 } as Record<StyleKnobKey, number>,
    profilePatch: { sentence_rhythm: '短句为主，收束干脆', register: '冷峻克制，少修饰' },
    dialogueTarget: 0.25,
  },
  {
    id: 'lush',
    label: '绵密抒情',
    knobs: { rhythm: 4, register: 4, density: 4, warmth: 4 } as Record<StyleKnobKey, number>,
    profilePatch: { sentence_rhythm: '中长句绵延，气韵连贯', register: '书面抒情，意象绵密' },
    dialogueTarget: 0.25,
  },
  {
    id: 'vernacular',
    label: '口语白描',
    knobs: { rhythm: 2, register: 1, density: 1, warmth: 3 } as Record<StyleKnobKey, number>,
    profilePatch: { sentence_rhythm: '短促口语，像说话一样写', register: '平白晓畅，少书面语' },
    dialogueTarget: 0.5,
  },
  {
    id: 'classical',
    label: '章回古雅',
    knobs: { rhythm: 3, register: 5, density: 3, warmth: 3 } as Record<StyleKnobKey, number>,
    profilePatch: { register: '雅正书面语，带古典章回气', opening_habit: '回目式起笔', ending_habit: '收束留钩，欲知后事' },
    dialogueTarget: 0.35,
  },
]

const props = defineProps<{
  knobs: Record<string, number>
  dialogueTarget: number | null
  /** 语料实测锚（可选：无样本时无锚） */
  corpusSentenceMean?: number | null
  corpusDialogue?: number | null
}>()

const emit = defineEmits<{
  (e: 'dirty'): void
  (e: 'update-knob', key: StyleKnobKey, tier: number | null): void
  (e: 'update-dialogue', value: number | null): void
  (e: 'apply-preset', preset: typeof PRESETS[number]): void
}>()

// ---- 实测锚（能测量的两个维度才有）----
const rhythmAnchorTier = computed<number | null>(() => {
  const mean = props.corpusSentenceMean
  if (!mean || mean <= 0) return null
  if (mean <= 12) return 1
  if (mean <= 16) return 2
  if (mean <= 22) return 3
  if (mean <= 30) return 4
  return 5
})

const rhythmAnchorLabel = computed(() => {
  const t = rhythmAnchorTier.value
  return t !== null ? KNOBS[0].tiers[t - 1] : null
})

const dialogueAnchorLabel = computed(() => {
  const d = props.corpusDialogue
  return d !== null && d !== undefined && d > 0 ? `${Math.round(d * 100)}%` : null
})

/** 偏差提示：手动档离实测锚 ≥2 档（节奏）或 >0.2（对话） */
const rhythmDeviation = computed(() => {
  const manual = props.knobs.rhythm
  const anchor = rhythmAnchorTier.value
  if (!manual || !anchor) return false
  return Math.abs(manual - anchor) >= 2
})

const dialogueDeviation = computed(() => {
  const t = props.dialogueTarget
  const measured = props.corpusDialogue
  if (t === null || t === undefined || !measured) return false
  return Math.abs(t - measured) > 0.2
})

const dialogueActiveTier = computed<number | null>(() => {
  const t = props.dialogueTarget
  if (t === null || t === undefined) return null
  let best = 0
  let bestDist = Infinity
  DIALOGUE_TIERS.forEach((d, i) => {
    const dist = Math.abs(d.value - t)
    if (dist < bestDist) {
      bestDist = dist
      best = i
    }
  })
  return best
})
</script>

<template>
  <section id="style-sec-knobs" class="style-section">
    <header class="sec-head">
      <h2 class="sec-title">意图</h2>
      <p class="sec-sub">
        大方向旋钮——默认<b>自动</b>（跟随你的样本与画像，不额外强加）；
        拨动即覆盖，生成时作为意图行注入。爱精确的进「笔迹指纹 → 高级画像」。
      </p>
    </header>

    <!-- 风格预设：只作起点 -->
    <div class="preset-row">
      <span class="preset-label">预设起点：</span>
      <button
        v-for="p in PRESETS"
        :key="p.id"
        class="preset-chip"
        :title="`把旋钮与画像模板填为「${p.label}」风格（可继续手调）`"
        @click="emit('apply-preset', p)"
      >{{ p.label }}</button>
    </div>

    <!-- 四个维度旋钮 -->
    <div v-for="knob in KNOBS" :key="knob.key" class="knob-row">
      <span class="knob-label">{{ knob.label }}</span>
      <button
        class="tier-btn tier-auto"
        :class="{ active: knobs[knob.key] === undefined }"
        title="自动：不注入该维度，交给画像与样本"
        @click="emit('update-knob', knob.key, null); emit('dirty')"
      >自动</button>
      <button
        v-for="(tierLabel, i) in knob.tiers"
        :key="tierLabel"
        class="tier-btn"
        :class="{
          active: knobs[knob.key] === i + 1,
          anchor: knob.key === 'rhythm' && rhythmAnchorTier === i + 1 && knobs[knob.key] === undefined,
        }"
        :title="rhythmAnchorTier === i + 1 && knob.key === 'rhythm' ? '你的笔迹实测在这里' : tierLabel"
        @click="emit('update-knob', knob.key, i + 1); emit('dirty')"
      >{{ tierLabel }}</button>
      <span v-if="knob.key === 'rhythm' && rhythmAnchorLabel && knobs.rhythm === undefined" class="anchor-note">
        你的字实测 ≈ {{ rhythmAnchorLabel }}
      </span>
    </div>
    <p v-if="rhythmDeviation" class="deviation-note">
      快慢拨得和你最近的字差得有点远（实测 ≈ {{ rhythmAnchorLabel }}）——是有意转型吗？
    </p>

    <!-- 对话旋钮（落目标值） -->
    <div class="knob-row">
      <span class="knob-label">对话</span>
      <button
        class="tier-btn tier-auto"
        :class="{ active: dialogueTarget === null || dialogueTarget === undefined }"
        title="自动：不设目标，审计用默认区间"
        @click="emit('update-dialogue', null); emit('dirty')"
      >自动</button>
      <button
        v-for="(t, i) in DIALOGUE_TIERS"
        :key="t.label"
        class="tier-btn"
        :class="{ active: dialogueActiveTier === i }"
        @click="emit('update-dialogue', t.value); emit('dirty')"
      >{{ t.label }}</button>
      <span v-if="dialogueAnchorLabel && dialogueTarget === null" class="anchor-note">
        你的字实测 {{ dialogueAnchorLabel }}
      </span>
    </div>
    <p v-if="dialogueDeviation" class="deviation-note">
      对话目标和你最近的字（实测 {{ dialogueAnchorLabel }}）差得有点远——是有意转型吗？
    </p>
  </section>
</template>

<style scoped>
.style-section {
  padding: 1.25rem 0 1.5rem;
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
.preset-row {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  flex-wrap: wrap;
  margin-bottom: 0.75rem;
}
.preset-label {
  font-size: 0.6875rem;
  color: var(--text-muted);
}
.preset-chip {
  padding: 0.25rem 0.625rem;
  font-size: 0.6875rem;
  color: var(--text-secondary);
  background: var(--bg-panel);
  border: 1px solid var(--border-color);
  border-radius: 999px;
  cursor: pointer;
}
.preset-chip:hover {
  color: var(--accent-500);
  border-color: var(--accent-400);
}
.knob-row {
  display: flex;
  align-items: center;
  gap: 0.25rem;
  flex-wrap: wrap;
  margin-bottom: 0.5rem;
}
.knob-label {
  width: 2.5rem;
  flex-shrink: 0;
  font-size: 0.75rem;
  color: var(--text-secondary);
}
.tier-btn {
  padding: 0.25rem 0.5rem;
  font-size: 0.6875rem;
  color: var(--text-muted);
  background: var(--bg-panel);
  border: 1px solid var(--border-color);
  border-radius: 0.375rem;
  cursor: pointer;
  transition: all 0.12s ease;
}
.tier-btn:hover {
  color: var(--text-secondary);
  border-color: var(--accent-400);
}
.tier-btn.active {
  color: white;
  background: var(--accent-500);
  border-color: var(--accent-500);
}
.tier-btn.anchor {
  border-color: var(--accent-400);
  border-style: dashed;
}
.tier-auto {
  font-weight: 500;
}
.anchor-note {
  margin-left: 0.375rem;
  font-size: 0.625rem;
  color: var(--accent-500);
}
.deviation-note {
  margin: 0.25rem 0 0.5rem;
  font-size: 0.6875rem;
  color: #b45309;
}
</style>
