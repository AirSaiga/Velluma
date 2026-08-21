<script setup lang="ts">
/**
 * 「AI 此刻所见」折叠区（P5 B2 · docs/foundation-hardening.md §2.1）。
 *
 * 展示 stitch-ghost 实际注入的七个上下文块（画像→样本→专名→canon→私有→回响→
 * 空间，与真实 system prompt 同源——后端 context-preview 与 stitch 路由共用同一
 * 装配函数）。空块显示「未配置」灰字：这是设定体检的入口流量，作者据此知道
 * 「什么值得录」。纯展示组件：数据获取在容器（InspectorPanel）。
 */
import { computed } from 'vue'
import Icon from '../../../components/Icon.vue'
import type { ContextPreview, ContextPreviewBlock } from '../../../services/api/domain/adaptive.api'
import { formatTime } from '../../world/engine/timeFormat'
import { budgetFillPercent, isBudgetHot } from './contextBudget'

type PreviewMode = 'stitch' | 'continue' | 'burst' | 'outline' | 'open'

const props = defineProps<{
  open: boolean
  loading: boolean
  error: string
  preview: ContextPreview | null
  mode: PreviewMode
}>()

const emit = defineEmits<{
  toggle: []
  refresh: []
  'update:mode': [mode: PreviewMode]
}>()

const MODES: Array<{ key: PreviewMode; label: string }> = [
  { key: 'continue', label: '顺写' },
  { key: 'stitch', label: '缝合' },
  { key: 'burst', label: '连写' },
  { key: 'outline', label: '细纲' },
  { key: 'open', label: '点火' },
]

const TIME_SOURCE_LABELS: Record<string, string> = {
  chapter_anchor: '本章锚定',
  prev_anchor: '前序章锚定',
  max_event: '事件最大时刻',
  zero: '空世界',
}

/** 空块的体检提示（一句话告诉作者去哪补录——「什么值得录」的回报可见） */
const EMPTY_HINTS: Record<string, string> = {
  style_positive: '文风页填画像或选预设后，AI 会照此校准语感',
  author_samples: '文风页收几段亲笔样本，是质量杠杆最大的注入',
  proper_nouns: '世界页建实体（或在正文 @ 提及），防缝合时称呼漂移',
  canon: '世界页「真相」账本记一条，AI 便知晓事实与秘密',
  secrets: '世界页把实体设为「私有」，AI 知晓其档案但绝不写出',
  echoes: '写过的章节会进记忆，后续章节自动呼应细节',
  spatial: '世界页设定地图比例尺后，距离与行程会带常识感',
}

const worldTimeLabel = computed(() => {
  const p = props.preview
  if (!p) return ''
  const src = TIME_SOURCE_LABELS[p.world_time_source] || p.world_time_source
  return `${formatTime(p.world_time)} · 来自${src}`
})

/** A3b 预算占用条：百分比宽度（配额缺失=0 不渲染） */
function fillWidth(b: ContextPreviewBlock): string {
  return `${budgetFillPercent(b.chars, b.budget_chars)}%`
}

/** A3b 预算占用条：>90% 变色（吃紧信号） */
function isHot(b: ContextPreviewBlock): boolean {
  return isBudgetHot(b.chars, b.budget_chars)
}
</script>

<template>
  <section class="ctx-preview">
    <button class="ctx-toggle" @click="emit('toggle')">
      <Icon name="light-bulb" :size="14" />
      <span>{{ open ? '收起 AI 此刻所见' : 'AI 此刻所见（预览）' }}</span>
      <Icon :name="open ? 'chevron-down' : 'chevron-up'" :size="12" class="ctx-chevron" />
    </button>
    <p class="ctx-hint">AI 续写时真的会读到这些——这里看到什么它就读到什么；空的块 = 这次用不上。</p>

    <template v-if="open">
      <!-- 模式五档：不同模式的检索锚不同（open 走大纲） -->
      <div class="ctx-modes">
        <button
          v-for="m in MODES"
          :key="m.key"
          class="ctx-mode-btn"
          :class="{ active: mode === m.key }"
          @click="emit('update:mode', m.key)"
        >{{ m.label }}</button>
      </div>

      <div v-if="loading" class="ctx-status">读取中…</div>
      <div v-else-if="error" class="ctx-status ctx-status--err">读取失败：{{ error }}</div>
      <template v-else-if="preview">
        <!-- 汇总行：总量 + 世界时刻来源（A4 来源可见） -->
        <div class="ctx-summary">
          <span>共 {{ preview.total_chars }} 字</span>
          <span class="ctx-dot">·</span>
          <span>{{ worldTimeLabel }}</span>
          <span class="ctx-dot">·</span>
          <span>{{ preview.world_sourced ? '设定来自世界页' : '设定来自章节' }}</span>
          <button class="ctx-refresh" title="按当前正文与设定重新读取" @click="emit('refresh')">刷新</button>
        </div>

        <!-- 各块（注入序）；空块原样返回 → 「未配置」灰字 -->
        <div
          v-for="b in preview.blocks"
          :key="b.key"
          class="ctx-block"
          :class="{ empty: !b.content }"
        >
          <div class="ctx-block-head">
            <span class="ctx-block-title">{{ b.title }}</span>
            <span class="ctx-block-chars">{{ b.chars }} 字</span>
            <span class="ctx-block-source">{{ b.source }}</span>
          </div>
          <!-- A3b 预算占用条：chars/budget_chars 比例，>90% 变色；被裁信息人话提示 -->
          <div v-if="b.budget_chars > 0" class="ctx-budget">
            <div
              class="ctx-budget-track"
              :title="`${b.chars} / ${b.budget_chars} 字（上限）`"
            >
              <div
                class="ctx-budget-fill"
                :class="{ hot: isHot(b) }"
                :style="{ width: fillWidth(b) }"
              />
            </div>
            <span v-if="b.trimmed" class="ctx-budget-trimmed">{{ b.trimmed }}</span>
          </div>
          <pre v-if="b.content" class="ctx-block-content">{{ b.content }}</pre>
          <div v-else class="ctx-block-empty">
            <span>未配置</span>
            <span class="ctx-block-empty-hint">{{ EMPTY_HINTS[b.key] || '' }}</span>
          </div>
        </div>
      </template>
    </template>
  </section>
</template>

<style scoped>
.ctx-preview {
  display: flex;
  flex-direction: column;
  gap: 0.375rem;
}

.ctx-toggle {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0.375rem;
  width: 100%;
  padding: 0.5rem;
  background: var(--bg-secondary);
  color: var(--accent-500);
  border: 1px solid var(--accent-500);
  border-radius: 0.5rem;
  font-size: 0.75rem;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s ease;
}
.ctx-toggle:hover {
  background: var(--accent-500);
  color: white;
}
.ctx-chevron {
  margin-left: auto;
  opacity: 0.7;
}

.ctx-hint {
  font-size: 0.6875rem;
  color: var(--text-muted);
  line-height: 1.5;
  margin: 0;
}

/* 模式五档 */
.ctx-modes {
  display: flex;
  gap: 0.25rem;
}
.ctx-mode-btn {
  flex: 1;
  padding: 0.25rem 0;
  font-size: 0.6875rem;
  color: var(--text-muted);
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 0.375rem;
  cursor: pointer;
  transition: all 0.15s ease;
}
.ctx-mode-btn:hover {
  color: var(--text-primary);
  border-color: var(--accent-400, #9685c2);
}
.ctx-mode-btn.active {
  color: var(--accent-500);
  border-color: var(--accent-500);
  font-weight: 600;
}

.ctx-status {
  font-size: 0.6875rem;
  color: var(--text-muted);
  padding: 0.375rem 0;
}
.ctx-status--err {
  color: var(--danger, #c66);
}

/* 汇总行 */
.ctx-summary {
  display: flex;
  align-items: center;
  gap: 0.3rem;
  font-size: 0.6875rem;
  color: var(--text-muted);
  font-variant-numeric: tabular-nums;
}
.ctx-dot {
  opacity: 0.5;
}
.ctx-refresh {
  margin-left: auto;
  padding: 0.0625rem 0.4375rem;
  font-size: 0.625rem;
  color: var(--text-muted);
  background: var(--bg-tertiary);
  border: none;
  border-radius: 0.375rem;
  cursor: pointer;
}
.ctx-refresh:hover {
  color: var(--accent-500);
}

/* 块卡片（hairline） */
.ctx-block {
  background: var(--bg-canvas);
  border: 1px solid var(--border-color);
  border-radius: 0.5rem;
  padding: 0.4375rem 0.5rem;
}
.ctx-block.empty {
  border-style: dashed;
  opacity: 0.85;
}
.ctx-block-head {
  display: flex;
  align-items: baseline;
  gap: 0.375rem;
}
.ctx-block-title {
  font-size: 0.75rem;
  font-weight: 600;
  color: var(--text-primary);
}
.ctx-block-chars {
  font-size: 0.625rem;
  color: var(--text-muted);
  font-variant-numeric: tabular-nums;
}
.ctx-block-source {
  margin-left: auto;
  flex-shrink: 0;
  font-size: 0.625rem;
  color: var(--accent-500);
  border: 1px solid var(--accent-400, #9685c2);
  border-radius: 999px;
  padding: 0.03125rem 0.4375rem;
}

/* A3b 预算占用条（细条 + 被裁提示） */
.ctx-budget {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  margin-top: 0.25rem;
}
.ctx-budget-track {
  flex: 1;
  height: 3px;
  background: var(--bg-tertiary);
  border-radius: 999px;
  overflow: hidden;
}
.ctx-budget-fill {
  height: 100%;
  background: var(--accent-400, #9685c2);
  border-radius: 999px;
  transition: width 0.2s ease;
}
.ctx-budget-fill.hot {
  background: var(--danger, #c66);
}
.ctx-budget-trimmed {
  flex-shrink: 0;
  font-size: 0.625rem;
  color: var(--danger, #c66);
}
.ctx-block-content {
  margin: 0.375rem 0 0;
  font-family: var(--font-mono, monospace);
  font-size: 0.6875rem;
  line-height: 1.6;
  color: var(--text-secondary);
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 10rem;
  overflow-y: auto;
}
.ctx-block-empty {
  display: flex;
  align-items: baseline;
  gap: 0.375rem;
  margin-top: 0.25rem;
  font-size: 0.6875rem;
  color: var(--text-muted);
  font-style: italic;
}
.ctx-block-empty-hint {
  font-style: normal;
  font-size: 0.625rem;
  opacity: 0.8;
}
</style>
