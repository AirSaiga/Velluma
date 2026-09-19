<script setup lang="ts">
/**
 * 文风页 ②「笔迹指纹」——实测指纹可视化 + 高级画像折叠区。
 *
 * 职责：
 * - 语料聚合指纹的指标网格（句长起伏/句均/碎句率/对话占比/段落/标点/修辞）
 * - 句长分布五桶直方图（第一个「啊哈时刻」：原来我写字长这样）
 * - 高级面板（折叠）：正面画像五维文本框 / 对话占比目标 / 段落节奏 / 从样本提炼
 *
 * 数据经 props 直传；画像编辑就地改动 prop 对象字段后 emit('dirty')，
 * 由容器走 2s 防抖自动保存（沿用 StyleCardManager 既有契约）。
 * 旋钮档位制是 S4 范围，S1 先保留目标滑条并标注实测刻度。
 */
import { computed, ref } from 'vue'
import Icon from '../../../components/Icon.vue'
import type { StyleFingerprint, TextFingerprint } from '../../../types'

const props = defineProps<{
  fingerprint: StyleFingerprint | null
  positiveProfile: Record<string, string>
  paragraphRhythm: string
  isExtracting?: boolean
  /** 章级特例（S3）：章节列表 + 当前编辑对象（'' = 书级） */
  chapters?: Array<{ id: string; chapter_number: number; title: string | null }>
  scopeChapterId?: string
  hasOverride?: boolean
  /** 画像字段锁（补全批）：被锁字段不被「从样本提炼」覆盖 */
  lockedKeys?: string[]
}>()

const emit = defineEmits<{
  (e: 'dirty'): void
  (e: 'extract'): void
  (e: 'update:paragraphRhythm', value: string): void
  (e: 'edit-scope', chapterId: string): void
  (e: 'reset-override'): void
  (e: 'toggle-lock', key: string): void
  (e: 'lock-all'): void
}>()

const showAdvanced = ref(false)

// 段落节奏是原始字符串 prop，经可写 computed 中转双向绑定
const paragraphRhythmText = computed({
  get: () => props.paragraphRhythm,
  set: (v: string) => emit('update:paragraphRhythm', v),
})

const profileKeys = [
  { key: 'sentence_rhythm', label: '句长节奏' },
  { key: 'vocabulary', label: '词汇层级' },
  { key: 'register', label: '语域偏好' },
  { key: 'opening_habit', label: '开头习惯' },
  { key: 'ending_habit', label: '结尾习惯' },
]

const corpus = computed<TextFingerprint | null>(() => props.fingerprint?.corpus || null)
const hasCorpus = computed(() => (corpus.value?.word_count || 0) > 0)

// ---- 指标格（v4 实验室：hint 一律白话完整句；直方图已迁笔迹签名卡） ----
interface MetricRow {
  label: string
  value: string
  hint: string
}

const metrics = computed<MetricRow[]>(() => {
  const fp = corpus.value
  if (!fp) return []
  const pct = (v: number) => `${Math.round((v || 0) * 100)}%`
  const rows: MetricRow[] = [
    {
      label: '句长起伏',
      value: fp.sentence_len_cv.toFixed(2),
      hint: `参考范围 ${props.fingerprint?.reference.cv_healthy[0]}~${props.fingerprint?.reference.cv_healthy[1]}`,
    },
    { label: '句均字数', value: `${fp.sentence_len_mean}`, hint: `一半句子比 ${fp.sentence_len_median} 字长、一半比它短` },
    { label: '碎句率', value: pct(fp.short_sentence_ratio), hint: '不超过五个字的短句占比，一般不超过 10%' },
    { label: '对话占比', value: pct(fp.dialogue_ratio), hint: '以你自己写的字为准' },
    { label: '段均字数', value: `${fp.paragraph_len_mean}`, hint: `短段（不超过 15 字）占 ${pct(fp.short_paragraph_ratio)}` },
    {
      label: '标点习惯',
      value: `${fp.punctuation.dash_per_1k}/${fp.punctuation.ellipsis_per_1k}`,
      hint: `每千字破折号 / 省略号；叹号 ${fp.punctuation.exclaim_per_1k}、问号 ${fp.punctuation.question_per_1k}`,
    },
  ]
  if (fp.rhetoric) {
    rows.push({
      label: '修辞密度',
      value: `${fp.rhetoric.metaphor_per_500}`,
      hint: `每 500 字的比喻数量；微动作 ${fp.rhetoric.micro_action_per_500}；AI 味综合 ${fp.rhetoric.ai_taste_score}`,
    })
  }
  // 词汇丰富度 / 重复度：旧指纹无此键或数据不足（null）则整格不渲染
  if (fp.lexical?.mattr != null) {
    rows.push({
      label: '词汇丰富度',
      value: fp.lexical.mattr.toFixed(2),
      hint: '用词的多样程度，越高越丰富',
    })
  }
  if (fp.repetition?.bigram_repeat_ratio != null) {
    rows.push({
      label: '重复度',
      value: pct(fp.repetition.bigram_repeat_ratio),
      hint: '前后相邻的重复词组占比，偏高说明表达套路化（人名等正常重复也算）',
    })
  }
  return rows
})

const sampleCount = computed(() => props.fingerprint?.sample_count ?? 0)
</script>

<template>
  <section id="style-sec-fingerprint" class="style-section">
    <header class="sec-head">
      <h2 class="sec-title">笔迹指标</h2>
      <p class="sec-sub">
        从你的字实测得出（纯算法，不是 AI 猜的）。
        <span v-if="fingerprint?.low_confidence" class="warn-inline">亲笔字还少（{{ sampleCount }} 条），仅供参考。</span>
      </p>
    </header>

    <div v-if="!hasCorpus" class="empty-note">还没有可量的字——工坊贴入亲笔字后，这里会长出指标。</div>

    <template v-else>
      <!-- 指标格：每格一句白话解释（句长分布墨迹图见上方笔迹签名卡） -->
      <div class="metric-grid">
        <div v-for="m in metrics" :key="m.label" class="metric-cell card-well" :title="m.hint">
          <span class="metric-label">{{ m.label }}</span>
          <span class="metric-value tnum">{{ m.value }}</span>
          <span class="metric-hint">{{ m.hint }}</span>
        </div>
      </div>

      <!-- 高级面板：画像/目标/提炼（S4 旋钮化前保留原编辑形态） -->
      <div class="advanced">
        <button class="advanced-toggle" @click="showAdvanced = !showAdvanced">
          <Icon :name="showAdvanced ? 'chevron-down' : 'chevron-right'" :size="12" />
          画像与按章设文风{{ showAdvanced ? '' : '（点开编辑）' }}
        </button>

        <div v-if="showAdvanced" class="advanced-body">
          <!-- 按章单独设文风（选一章=只改那一章） -->
          <div v-if="chapters && chapters.length > 0" class="scope-block">
            <label class="field-label">正在改哪一层的文风（选一章=只改那一章）</label>
            <div class="scope-row">
              <select
                class="scope-select"
                :value="scopeChapterId || ''"
                @change="emit('edit-scope', ($event.target as HTMLSelectElement).value)"
              >
                <option value="">全书默认</option>
                <option v-for="c in chapters" :key="c.id" :value="c.id">
                  第{{ c.chapter_number }}章{{ c.title ? ` · ${c.title.slice(0, 10)}` : '' }}{{ }}
                </option>
              </select>
              <button
                v-if="scopeChapterId && hasOverride"
                class="btn-scope-reset"
                @click="emit('reset-override')"
              >恢复用全书默认</button>
            </div>
            <p class="scope-hint">
              {{ scopeChapterId ? '现在改的是这一章自己的文风——保存只影响它。' : '想让某一章换腔调？选一章，为它单独设文风。' }}
            </p>
          </div>

          <div class="advanced-toolbar">
            <p class="advanced-note">
              画像由「开始提炼」从你的字里生成；上了锁的条目不会被覆盖（保护亲笔描述/特殊文体）。
              没有手填——画像只信从你的字里提出来的。
            </p>
            <span class="advanced-actions">
              <button
                class="btn-lock-all"
                title="全部上锁——特殊文体（诗歌/剧本）或亲笔描述的保护"
                @click="emit('lock-all')"
              >{{ profileKeys.every(pk => lockedKeys?.includes(pk.key)) ? '全部解锁' : '全部锁定' }}</button>
              <button class="btn-primary" :disabled="isExtracting" @click="emit('extract')">
                <Icon name="bolt" :size="12" class="mr-0.5" />
                {{ isExtracting ? '提炼中…' : '开始提炼' }}
              </button>
            </span>
          </div>

          <div v-for="pk in profileKeys" :key="pk.key" class="profile-field">
            <label class="field-label">
              {{ pk.label }}
              <button
                class="lock-btn"
                :class="{ active: lockedKeys?.includes(pk.key) }"
                :title="lockedKeys?.includes(pk.key) ? '已上锁：提炼不会覆盖这一条' : '未上锁：提炼结果可以覆盖这一条'"
                @click="emit('toggle-lock', pk.key)"
              ><Icon :name="lockedKeys?.includes(pk.key) ? 'lock-closed' : 'lock-open'" :size="14" /></button>
            </label>
            <!-- 手填已下线：只读展示提炼产物（空=未提炼；改内容走「开始提炼」或上锁保护亲笔值） -->
            <p v-if="(positiveProfile[pk.key] || '').trim()" class="field-readonly">{{ positiveProfile[pk.key] }}</p>
            <p v-else class="field-readonly field-readonly--empty">还没提炼——点上方「开始提炼」生成</p>
          </div>

          <div class="profile-field">
            <label class="field-label">段落节奏</label>
            <textarea
              v-model="paragraphRhythmText"
              rows="3"
              class="field-textarea"
              placeholder="例：段落短促，常 2-3 句一段"
              @input="emit('dirty')"
            ></textarea>
          </div>
        </div>
      </div>
    </template>
  </section>
</template>

<style scoped>
.style-section {
  padding: 1.25rem 0 1.5rem;
  scroll-margin-top: 4.5rem;
}
/* .sec-head/.sec-title 吃 style.css 全局工具类（00 期 §3.1）；
   sec-sub 按 §6 归 token（原 muted 过淡） */
.sec-sub {
  margin: 0.25rem 0 0;
  font-size: var(--text-sm);
  line-height: var(--lh-normal);
  color: var(--text-secondary);
}
.warn-inline {
  color: var(--warn);
}
.empty-note {
  padding: 1rem;
  font-size: 0.75rem;
  text-align: center;
  color: var(--text-muted);
}

.metric-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(168px, 1fr));
  gap: 0.5rem;
  margin-bottom: 0.75rem;
}
/* N2 §3.7：指标格试点 .card-well（凹槽卡；皮肤由工具类提供） */
.metric-cell {
  display: flex;
  flex-direction: column;
  gap: 0.125rem;
  cursor: help;
}
.metric-label {
  font-size: var(--text-xs);
  color: var(--text-muted);
}
.metric-value {
  /* 04 §B4 页码感：展示大数字=衬线等宽（20px ≥16px 阈值） */
  font-family: var(--font-heading);
  font-variant-numeric: tabular-nums;
  font-size: 1.25rem;
  font-weight: 600;
  color: var(--text-primary);
}
.metric-hint {
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 3;
  overflow: hidden;
  font-size: var(--text-xs);
  line-height: 1.45;
  color: var(--text-muted);
}

.advanced {
  margin-top: 0.25rem;
}
.advanced-toggle {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  padding: 0.25rem 0.375rem;
  font-size: 0.75rem;
  color: var(--text-muted);
  background: transparent;
  border: none;
  border-radius: var(--radius-xs);
  cursor: pointer;
}
.advanced-toggle:hover {
  color: var(--text-secondary);
  background: var(--state-hover);
}
.advanced-body {
  padding: 0.75rem;
  margin-top: 0.25rem;
  background: var(--surface-overlay);
  border: 1px dashed var(--border-color);
  border-radius: var(--radius-md);
}
.scope-block {
  padding-bottom: 0.75rem;
  margin-bottom: 0.75rem;
  border-bottom: 1px dashed var(--border-color);
}
.scope-row {
  display: flex;
  gap: 0.5rem;
  align-items: center;
}
.scope-select {
  flex: 1;
  min-width: 0;
  padding: 0.3rem 0.5rem;
  font-size: 0.75rem;
  background: transparent;
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
}
.btn-scope-reset {
  flex-shrink: 0;
  padding: 0.3rem 0.625rem;
  font-size: var(--text-xs);
  color: var(--warn);
  background: var(--warn-bg);
  border: none;
  border-radius: var(--radius-sm);
  cursor: pointer;
}
.btn-scope-reset:hover {
  background: var(--warn-bg);
}
.scope-hint {
  margin: 0.375rem 0 0;
  font-size: var(--text-xs);
  color: var(--text-muted);
}
.advanced-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  margin-bottom: 0.75rem;
}
.advanced-actions {
  display: flex;
  align-items: center;
  flex-shrink: 0;
  gap: 0.5rem;
}
.btn-lock-all {
  padding: 0.375rem 0.625rem;
  font-size: var(--text-xs);
  color: var(--accent-600);
  background: color-mix(in srgb, var(--accent-500) 15%, transparent);
  border: none;
  border-radius: var(--radius-sm);
  cursor: pointer;
}
.btn-lock-all:hover {
  background: color-mix(in srgb, var(--accent-500) 25%, transparent);
}
.lock-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  margin-left: 0.375rem;
  background: transparent;
  border: none;
  border-radius: var(--radius-xs);
  cursor: pointer;
  color: var(--text-muted);
}
.lock-btn.active {
  color: var(--accent-500);
  opacity: 1;
}
.advanced-note {
  margin: 0;
  font-size: var(--text-xs);
  line-height: 1.6;
  color: var(--text-muted);
}
.btn-primary {
  display: inline-flex;
  align-items: center;
  flex-shrink: 0;
  padding: 0.375rem 0.75rem;
  font-size: 0.75rem;
  color: var(--bg-canvas);
  background: var(--accent-500);
  border: none;
  border-radius: var(--radius-sm);
  cursor: pointer;
}
.btn-primary:hover:not(:disabled) {
  background: var(--accent-600);
}
.btn-primary:disabled {
  opacity: 0.5;
}
.profile-field {
  margin-bottom: 0.625rem;
}
.field-label {
  display: block;
  margin-bottom: 0.25rem;
  font-size: var(--text-xs);
  color: var(--text-muted);
}
.measured-mark {
  margin-left: 0.5rem;
  color: var(--accent-500);
}
.field-textarea {
  width: 100%;
  padding: 0.375rem 0.5rem;
  font-size: 0.75rem;
  background: transparent;
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  resize: vertical;
}
.field-textarea:focus {
  border-color: var(--accent-400);
}
/* 画像只读展示（手填下线 2026-09-14）——与 field-textarea 同排版基因，无焦点态 */
.field-readonly {
  margin: 0;
  padding: 0.375rem 0.5rem;
  font-size: 0.75rem;
  line-height: 1.6;
  color: var(--text-primary);
  background: var(--bg-secondary);
  border: 1px dashed var(--border-color);
  border-radius: var(--radius-sm);
  white-space: pre-wrap;
}
.field-readonly--empty {
  color: var(--text-muted);
}
.field-range {
  width: 100%;
  margin-top: 0.25rem;
}
</style>
