<script setup lang="ts">
/**
 * 「AI 此刻读到的」主件（P5 B2 · 09 期重设计 docs/design/ux-redesign/09-ai-view-redesign.md）。
 *
 * 展示 stitch-ghost 实际注入的上下文块（与真实 system prompt 同源——后端
 * context-preview 与 stitch 路由共用同一装配函数）。09 期三改造：
 * 分区常开（无大按钮）；块默认折叠只留头行（头行即仪表盘：标题/字数/来源/
 * 预算条），展开即全量阅读（无嵌套滚动，滚动交给面板整体）；块正文保字排版
 * （contextBlockFormat 解析为排版结构，字不增不删，「原文」开关逐字核对）。
 * 块按注入序切三段（事实与设定/约束与记忆/文风与笔感），序可感知。
 * 空块单行虚线 +「去哪补录」引导——「什么值得录」的回报可见。
 * 纯展示组件：数据获取在容器（InspectorPanel）。
 */
import { computed, nextTick, ref, watch } from 'vue'
import Icon from '../../../components/Icon.vue'
import type { ContextPreview, ContextPreviewBlock } from '../../../services/api/domain/adaptive.api'
import { formatTime } from '../../world/engine/timeFormat'
import { budgetFillPercent, isBudgetHot } from './contextBudget'
import {
  SEGMENT_ORDER,
  SEGMENT_TITLES,
  friendlySource,
  inlineParse,
  markTone,
  parseBlockContent,
  segmentOfKey,
} from './contextBlockFormat'
import type { BlockNode, InlineSpan } from './contextBlockFormat'

type PreviewMode = 'stitch' | 'continue' | 'burst' | 'outline' | 'open'

const props = defineProps<{
  loading: boolean
  error: string
  preview: ContextPreview | null
  mode: PreviewMode
}>()

const emit = defineEmits<{
  refresh: []
  'update:mode': [mode: PreviewMode]
}>()

const MODES: Array<{ key: PreviewMode; label: string; title: string }> = [
  { key: 'continue', label: '顺写', title: '按光标前文顺句检索' },
  { key: 'stitch', label: '拼画面', title: '按卡舱零件锚定检索' },
  { key: 'burst', label: '连写', title: '多段连发，检索面更大' },
  { key: 'outline', label: '细纲', title: '按胶囊前后文双端锚定' },
  { key: 'open', label: '写开头', title: '按大纲整章检索' },
]

const TIME_SOURCE_LABELS: Record<string, string> = {
  chapter_anchor: '本章固定',
  prev_anchor: '上一章固定',
  max_event: '最新事件',
  zero: '空世界',
}

/** 空块的体检提示（一句话告诉作者去哪补录——「什么值得录」的回报可见） */
const EMPTY_HINTS: Record<string, string> = {
  style_positive: '文风页填画像或选预设后，AI 会照此校准语感',
  author_samples: '文风页收几段亲笔样本，是质量杠杆最大的注入',
  proper_nouns: '世界页建好角色（或在正文 @ 提及），AI 写作时称呼不乱叫',
  canon: '世界页「真相」账本记一条，AI 便知晓事实与秘密',
  secrets: '世界页把实体设为「私有」，AI 知晓其档案但绝不写出',
  echoes: '写过的章节会进记忆，后续章节自动呼应细节',
  spatial: '世界页设定地图比例尺后，距离与行程会带常识感',
}

// ===== 折叠态（组件内不持久化；切章数据置空时随 watch 复位回默认） =====

/** 默认只展开「场景身份」：恒居注入序首位且短，让保字排版第一眼可见 */
const expandedKeys = ref<Set<string>>(new Set(['scene']))
/** 「原文」对照开关：全部块正文回退等宽逐字直出（信任逃生舱，不持久化） */
const rawView = ref(false)
const blocksEl = ref<HTMLElement | null>(null)

watch(
  () => props.preview,
  (n) => {
    if (!n) expandedKeys.value = new Set(['scene'])
  },
)

function isOpen(b: ContextPreviewBlock): boolean {
  return expandedKeys.value.has(b.key)
}

function toggleBlock(b: ContextPreviewBlock) {
  const next = new Set(expandedKeys.value)
  const opening = !next.has(b.key)
  if (opening) next.add(b.key)
  else next.delete(b.key)
  expandedKeys.value = next
  if (opening) {
    // 展开后若卡片底边超出可视区，只滚面板不滚页面
    nextTick(() => {
      blocksEl.value?.querySelector(`[data-blk="${b.key}"]`)?.scrollIntoView({ block: 'nearest' })
    })
  }
}

// ===== 汇总行 =====

const totalLabel = computed(() => (props.preview ? props.preview.total_chars.toLocaleString('zh-CN') : ''))

const worldTimeLabel = computed(() => {
  const p = props.preview
  if (!p) return ''
  const src = TIME_SOURCE_LABELS[p.world_time_source] || p.world_time_source
  return `${formatTime(p.world_time)} · 来自${src}`
})

/** 有旧数据时的重读（模式切换/刷新）：旧列表半透明冻结 + 扫描条，布局零跳动 */
const isReloading = computed(() => props.loading && !!props.preview)
const isFirstLoad = computed(() => props.loading && !props.preview)

// ===== 段分组（注入序切段；段是视觉切分，块才是折叠单元） =====

const segments = computed(() => {
  if (!props.preview) return []
  return SEGMENT_ORDER.map((id) => ({
    id,
    title: SEGMENT_TITLES[id],
    blocks: props.preview!.blocks.filter((b) => segmentOfKey(b.key) === id),
  })).filter((s) => s.blocks.length > 0)
})

// ===== 块正文保字排版 → 视图模型（preview 变更时算一次，渲染零重复解析） =====

type VM =
  | { kind: 'heading' | 'sample' | 'note' | 'plain'; text: string }
  | { kind: 'kv'; k: string; v: string; pin?: boolean }
  | { kind: 'item'; name?: string; spans: InlineSpan[] }
  | { kind: 'profile'; label?: string; arrow?: boolean; text: string }

/** 列表项名强调：短名后跟「：」（物件/秘密/伏笔条目），余文走行内切分 */
function itemVM(text: string): Extract<VM, { kind: 'item' }> {
  const m = text.match(/^([^：〔【]{1,16})：(.+)$/)
  if (m) return { kind: 'item', name: m[1], spans: inlineParse(m[2]) }
  return { kind: 'item', spans: inlineParse(text) }
}

function toVM(n: BlockNode): VM {
  if (n.type === 'kv') {
    return { kind: 'kv', k: n.k, v: n.v, pin: n.k.startsWith('【此刻·切记】') }
  }
  if (n.type === 'item') return itemVM(n.text)
  if (n.type === 'profile') {
    const m = n.text.match(/^(档案（[^）]*）：)([\s\S]*)$/)
    if (m) return { kind: 'profile', label: m[1], text: m[2] }
    return { kind: 'profile', arrow: n.text.startsWith('→'), text: n.text }
  }
  return { kind: n.type, text: n.text }
}

const vmByBlock = computed(() => {
  const map = new Map<ContextPreviewBlock, VM[]>()
  if (props.preview) {
    for (const b of props.preview.blocks) {
      map.set(b, parseBlockContent(b.content, b.key).map(toVM))
    }
  }
  return map
})

function vmsOf(b: ContextPreviewBlock): VM[] {
  return vmByBlock.value.get(b) ?? []
}

/** A3b 预算占用条 */
function fillWidth(b: ContextPreviewBlock): string {
  return `${budgetFillPercent(b.chars, b.budget_chars)}%`
}
function isHot(b: ContextPreviewBlock): boolean {
  return isBudgetHot(b.chars, b.budget_chars)
}
</script>

<template>
  <section class="ctx-preview">
    <div class="ctx-title">AI 此刻读到的</div>
    <p class="ctx-hint">AI 续写时读到的，就是下面这些字。空着的块 = 这次用不上。</p>

    <template v-if="preview">
      <div class="ctx-summary">
        <div class="sum-line1">
          <span class="sum-total"><b>{{ totalLabel }}</b> 字</span>
          <span class="sum-actions">
            <button
              class="sum-raw"
              :class="{ on: rawView }"
              title="显示 AI 实际读到的原始文本（逐字等宽）"
              @click="rawView = !rawView"
            >原文</button>
            <button
              class="sum-refresh"
              title="按当前正文与设定重新读取"
              :disabled="loading"
              @click="emit('refresh')"
            ><Icon name="arrow-path" :size="13" :class="{ spin: loading }" /></button>
          </span>
        </div>
        <div class="sum-line2">
          <span>{{ worldTimeLabel }}</span>
          <span class="dot">·</span>
          <span>{{ preview.world_sourced ? '设定来自世界页' : '设定来自章节' }}</span>
        </div>
      </div>
    </template>

    <!-- 模式五档：不同模式的检索锚不同（open 走大纲） -->
    <div class="ctx-modes">
      <button
        v-for="m in MODES"
        :key="m.key"
        class="mode-btn"
        :class="{ active: mode === m.key }"
        :title="m.title"
        @click="emit('update:mode', m.key)"
      >{{ m.label }}</button>
    </div>

    <!-- 首次加载骨架 -->
    <div v-if="isFirstLoad" class="ctx-loading">
      <div class="ctx-loading-text">正在按当前正文装配…</div>
      <div class="skel-label">事实与设定</div>
      <div class="skel-row"></div>
      <div class="skel-row"></div>
      <div class="skel-label">约束与记忆</div>
      <div class="skel-row"></div>
      <div class="skel-label">文风与笔感</div>
      <div class="skel-row"></div>
    </div>

    <div v-else-if="error" class="ctx-error">
      <div class="ctx-error-text">读取失败：{{ error }}</div>
      <button class="ctx-error-retry" @click="emit('refresh')">重试</button>
    </div>

    <template v-else-if="preview">
      <!-- 重读指示：旧列表冻结半透明，数据到达即替换 -->
      <div v-if="isReloading" class="ctx-reloading">
        <div class="scanbar"></div>
        <span>重新读取中…</span>
      </div>

      <div ref="blocksEl" class="ctx-blocks" :class="{ 'is-reloading': isReloading }">
        <section v-for="seg in segments" :key="seg.id" class="ctx-seg">
          <div class="seg-label">{{ seg.title }}</div>
          <template v-for="b in seg.blocks" :key="b.key">
            <!-- 空块：单行虚线 + 补录引导 -->
            <div v-if="!b.content" class="blk-empty">
              <span class="blk-empty-title">{{ b.title }}</span>
              <span class="blk-empty-tag">还没录</span>
              <span class="blk-empty-hint">{{ EMPTY_HINTS[b.key] || '' }}</span>
            </div>
            <!-- 满块：折叠头行（仪表盘）+ 展开全量正文 -->
            <div v-else class="blk" :class="{ 'is-open': isOpen(b) }" :data-blk="b.key">
              <button class="blk-head" @click="toggleBlock(b)">
                <Icon name="chevron-right" :size="12" class="blk-chev" />
                <span class="blk-title">{{ b.title }}</span>
                <span class="blk-meta">{{ b.chars.toLocaleString('zh-CN') }} 字<template v-if="b.source"> · {{ friendlySource(b.source) }}</template></span>
              </button>
              <div v-if="b.budget_chars > 0" class="blk-meter">
                <div class="blk-meter-track" :title="`${b.chars} / ${b.budget_chars} 字（上限）`">
                  <div class="blk-meter-fill" :class="{ hot: isHot(b) }" :style="{ width: fillWidth(b) }" />
                </div>
                <span v-if="b.trimmed" class="blk-meter-trim">{{ b.trimmed }}</span>
              </div>
              <div class="blk-body">
                <div class="blk-clip">
                  <div class="blk-inner">
                    <pre v-if="rawView" class="blk-raw">{{ b.content }}</pre>
                    <template v-else>
                      <template v-for="(vm, i) in vmsOf(b)" :key="i">
                        <div v-if="vm.kind === 'heading'" class="nd nd-heading">{{ vm.text }}</div>
                        <div v-else-if="vm.kind === 'sample'" class="nd nd-sample">{{ vm.text }}</div>
                        <div v-else-if="vm.kind === 'note'" class="nd nd-note">{{ vm.text }}</div>
                        <div v-else-if="vm.kind === 'plain'" class="nd nd-plain">{{ vm.text }}</div>
                        <div v-else-if="vm.kind === 'kv'" class="nd nd-kv">
                          <span class="k" :class="{ 'is-pin': vm.pin }">{{ vm.k }}</span>
                          <span class="v">{{ vm.v }}</span>
                        </div>
                        <div v-else-if="vm.kind === 'item'" class="nd nd-item">
                          <span v-if="vm.name" class="it-name">{{ vm.name }}：</span>
                          <span
                            v-for="(sp, si) in vm.spans"
                            :key="si"
                            :class="sp.mark ? ['it-mark', `tone-${markTone(sp.text)}`] : 'it-text'"
                          >{{ sp.text }}</span>
                        </div>
                        <div v-else-if="vm.kind === 'profile'" class="nd nd-profile" :class="{ 'is-arrow': vm.arrow }">
                          <span v-if="vm.label" class="pf-label">{{ vm.label }}</span>{{ vm.text }}
                        </div>
                      </template>
                    </template>
                  </div>
                </div>
              </div>
            </div>
          </template>
        </section>
      </div>
    </template>
  </section>
</template>

<style scoped>
.ctx-preview {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.ctx-title {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  font-size: 0.75rem;
  font-weight: 600;
  color: var(--text-primary);
}
.ctx-title::before {
  content: '';
  width: 3px;
  height: 0.75rem;
  border-radius: 2px;
  background: var(--accent-500);
  opacity: 0.55;
  flex-shrink: 0;
}

.ctx-hint {
  font-size: 0.6875rem;
  color: var(--text-muted);
  line-height: 1.5;
  margin: 0;
}

/* ===== 汇总两行 ===== */
.ctx-summary {
  display: flex;
  flex-direction: column;
  gap: 0.125rem;
}
.sum-line1 {
  display: flex;
  align-items: center;
}
.sum-total {
  font-size: 0.6875rem;
  color: var(--text-muted);
  font-variant-numeric: tabular-nums;
}
.sum-total b {
  font-size: 0.875rem;
  font-weight: 700;
  color: var(--text-primary);
  font-family: var(--font-heading);
}
.sum-actions {
  margin-left: auto;
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
}
.sum-raw {
  padding: 0.0625rem 0.4375rem;
  font-size: 0.625rem;
  color: var(--text-muted);
  background: transparent;
  border: 1px solid var(--border-color);
  border-radius: 999px;
  cursor: pointer;
  transition: all 0.15s ease;
}
.sum-raw:hover {
  color: var(--accent-500);
  border-color: var(--accent-400, #9685c2);
}
.sum-raw.on {
  color: var(--accent-500);
  border-color: var(--accent-400, #9685c2);
  background: color-mix(in srgb, var(--accent-400, #9685c2) 14%, transparent);
}
.sum-refresh {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  color: var(--text-muted);
  background: transparent;
  border: none;
  border-radius: var(--radius-sm, 4px);
  cursor: pointer;
}
.sum-refresh:hover {
  color: var(--accent-500);
  background: var(--hover-bg);
}
.sum-refresh:disabled {
  cursor: default;
}
.spin {
  animation: ctx-spin 1s linear infinite;
}
@keyframes ctx-spin {
  to { transform: rotate(360deg); }
}
.sum-line2 {
  display: flex;
  align-items: baseline;
  gap: 0.3rem;
  font-size: 0.6875rem;
  color: var(--text-muted);
  font-variant-numeric: tabular-nums;
}
.sum-line2 .dot {
  opacity: 0.5;
}

/* ===== 模式五档 ===== */
.ctx-modes {
  display: flex;
  gap: 0.25rem;
}
.mode-btn {
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
.mode-btn:hover {
  color: var(--text-primary);
  border-color: var(--accent-400, #9685c2);
}
.mode-btn.active {
  color: var(--accent-500);
  border-color: var(--accent-400, #9685c2);
  background: color-mix(in srgb, var(--accent-400, #9685c2) 14%, transparent);
  font-weight: 600;
}

/* ===== 首次加载骨架 ===== */
.ctx-loading {
  display: flex;
  flex-direction: column;
  gap: 0.375rem;
}
.ctx-loading-text {
  font-size: 0.6875rem;
  color: var(--text-muted);
}
.skel-label {
  font-size: 0.6875rem;
  font-weight: 600;
  color: var(--text-muted);
  letter-spacing: 0.05em;
  margin-top: 0.375rem;
}
.skel-row {
  height: 1.75rem;
  border-radius: var(--radius-sm, 4px);
  background: var(--bg-tertiary);
  animation: ctx-pulse 1.4s ease-in-out infinite;
}
@keyframes ctx-pulse {
  0%, 100% { opacity: 0.55; }
  50% { opacity: 1; }
}

/* ===== 错误态 ===== */
.ctx-error {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.5rem 0.625rem;
  border: 1px solid var(--danger, #c66);
  border-radius: 0.5rem;
  background: color-mix(in srgb, var(--danger, #c66) 6%, transparent);
}
.ctx-error-text {
  flex: 1;
  font-size: 0.6875rem;
  color: var(--danger, #c66);
  word-break: break-all;
}
.ctx-error-retry {
  flex-shrink: 0;
  padding: 0.1875rem 0.625rem;
  font-size: 0.625rem;
  color: var(--danger, #c66);
  background: transparent;
  border: 1px solid var(--danger, #c66);
  border-radius: 0.375rem;
  cursor: pointer;
}
.ctx-error-retry:hover {
  color: #fff;
  background: var(--danger, #c66);
}

/* ===== 重读指示（扫描条 + 列表冻结） ===== */
.ctx-reloading {
  display: flex;
  align-items: center;
  gap: 0.375rem;
}
.ctx-reloading span {
  flex-shrink: 0;
  font-size: 0.625rem;
  color: var(--text-muted);
}
.scanbar {
  flex: 1;
  height: 2px;
  border-radius: 999px;
  background: var(--bg-tertiary);
  position: relative;
  overflow: hidden;
}
.scanbar::after {
  content: '';
  position: absolute;
  top: 0;
  width: 30%;
  height: 100%;
  border-radius: inherit;
  background: var(--accent-400, #9685c2);
  animation: ctx-scan 1.1s ease-in-out infinite;
}
@keyframes ctx-scan {
  0% { left: -30%; }
  100% { left: 100%; }
}
.ctx-blocks.is-reloading {
  opacity: 0.5;
  pointer-events: none;
  transition: opacity 0.15s ease;
}

/* ===== 段分组 ===== */
.ctx-seg + .ctx-seg {
  margin-top: 0.25rem;
}
.seg-label {
  font-size: 0.6875rem;
  font-weight: 600;
  color: var(--text-muted);
  letter-spacing: 0.05em;
  margin: 0.5rem 0 0.375rem;
}
.ctx-seg:first-child .seg-label {
  margin-top: 0.25rem;
}

/* ===== 空块单行 ===== */
.blk-empty {
  display: flex;
  align-items: baseline;
  gap: 0.375rem;
  padding: 0.3125rem 0.625rem;
  border: 1px dashed var(--border-color);
  border-radius: var(--radius-sm, 4px);
  opacity: 0.85;
}
.blk + .blk,
.blk + .blk-empty,
.blk-empty + .blk,
.blk-empty + .blk-empty {
  margin-top: 0.375rem;
}
.blk-empty-title {
  flex-shrink: 0;
  font-size: 0.6875rem;
  font-weight: 600;
  color: var(--text-secondary);
}
.blk-empty-tag {
  flex-shrink: 0;
  font-size: 0.6875rem;
  color: var(--text-muted);
  font-style: italic;
}
.blk-empty-hint {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 0.6875rem;
  color: var(--text-muted);
}

/* ===== 满块折叠卡 ===== */
.blk {
  background: var(--bg-canvas);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-sm, 4px);
  padding: 0.375rem 0.625rem;
}
.blk-head {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  width: 100%;
  min-height: 1.75rem;
  padding: 0;
  background: none;
  border: none;
  text-align: left;
  cursor: pointer;
}
.blk-chev {
  flex-shrink: 0;
  color: var(--text-muted);
  transition: transform 0.2s ease;
}
.blk.is-open .blk-chev {
  transform: rotate(90deg);
  color: var(--accent-500);
}
.blk-title {
  flex: 0 1 auto;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 0.75rem;
  font-weight: 600;
  color: var(--text-primary);
}
.blk-meta {
  margin-left: auto;
  flex-shrink: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 0.6875rem;
  color: var(--text-muted);
  font-variant-numeric: tabular-nums;
  text-align: right;
}

/* 预算占用条（头行下全宽轨道；hot 变红 + 被裁红字） */
.blk-meter {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  margin-top: 0.125rem;
}
.blk-meter-track {
  flex: 1;
  height: 2px;
  border-radius: 999px;
  background: var(--bg-tertiary);
  overflow: hidden;
}
.blk-meter-fill {
  height: 100%;
  border-radius: 999px;
  background: var(--accent-400, #9685c2);
  transition: width 0.2s ease;
}
.blk-meter-fill.hot {
  background: var(--danger, #c66);
}
.blk-meter-trim {
  flex-shrink: 0;
  font-size: 0.625rem;
  color: var(--danger, #c66);
}

/* 展开动画（grid 0fr→1fr，无依赖）；展开即全量，滚动交给面板 */
.blk-body {
  display: grid;
  grid-template-rows: 0fr;
  transition: grid-template-rows 0.2s ease;
}
.blk.is-open .blk-body {
  grid-template-rows: 1fr;
}
.blk-clip {
  overflow: hidden;
  min-height: 0;
}
.blk-inner {
  padding-top: 0.375rem;
}

/* 原文对照视图（等宽逐字） */
.blk-raw {
  margin: 0;
  font-family: var(--font-mono, monospace);
  font-size: 0.6875rem;
  line-height: 1.6;
  color: var(--text-secondary);
  white-space: pre-wrap;
  word-break: break-all;
}

/* ===== 保字排版节点 ===== */
/* 散文行（plain 兜底 + 档案体）用衬线：块正文是作者录入的中文叙述文，
   等宽/无衬线是给代码与坐标的（09 期 §5.3 字体裁决） */
.nd {
  font-size: 0.75rem;
  line-height: 1.7;
  color: var(--text-secondary);
  word-break: break-word;
}
.nd-plain,
.nd-profile {
  font-family: var(--font-heading);
}
.nd-heading {
  font-size: 0.6875rem;
  font-weight: 600;
  color: var(--text-secondary);
  margin: 0.25rem 0;
}
.nd-sample {
  font-size: 0.6875rem;
  font-weight: 600;
  color: var(--text-muted);
  margin: 0.5rem 0 0.125rem;
}
.nd-sample:first-child {
  margin-top: 0;
}
.nd-note {
  font-size: 0.6875rem;
  color: var(--text-muted);
  font-style: italic;
  margin-top: 0.375rem;
}
.nd-kv {
  display: flex;
  gap: 0.5rem;
  align-items: baseline;
}
.nd-kv .k {
  flex: 0 0 auto;
  min-width: 3.5em;
  font-size: 0.6875rem;
  font-weight: 600;
  color: var(--text-muted);
}
.nd-kv .k.is-pin {
  color: var(--accent-500);
  min-width: 0;
}
.nd-kv .v {
  flex: 1;
  min-width: 0;
  color: var(--text-primary);
}

/* 列表项：圆点 + 名强调 + 行内标记 chip */
.nd-item {
  position: relative;
  padding-left: 0.75rem;
  margin: 0.25rem 0;
}
.nd-item::before {
  content: '';
  position: absolute;
  left: 0.2rem;
  top: 0.62em;
  width: 4px;
  height: 4px;
  border-radius: 999px;
  background: var(--text-muted);
  opacity: 0.6;
}
.it-name {
  font-weight: 600;
  color: var(--text-primary);
}
.it-mark {
  display: inline-block;
  margin: 0 0.0625rem;
  padding: 0.03125rem 0.3125rem;
  font-size: 0.625rem;
  line-height: 1.4;
  border-radius: 999px;
  vertical-align: 0.0625rem;
}
.it-mark.tone-present {
  color: var(--ok, #4a9);
  background: color-mix(in srgb, var(--ok, #4a9) 12%, transparent);
}
.it-mark.tone-dead {
  color: var(--danger, #c66);
  font-weight: 600;
  background: color-mix(in srgb, var(--danger, #c66) 10%, transparent);
}
.it-mark.tone-moment {
  color: var(--text-secondary);
  background: var(--bg-tertiary);
  font-variant-numeric: tabular-nums;
}
.it-mark.tone-neutral {
  color: var(--text-muted);
  background: var(--bg-tertiary);
}

/* 档案体（衬线 + 左竖线；连续行竖线视觉连续） */
.nd-profile {
  margin: 0.125rem 0 0.125rem 0.75rem;
  padding-left: 0.5rem;
  border-left: 2px solid var(--border-color);
}
.nd-profile.is-arrow {
  font-size: 0.6875rem;
  color: var(--text-muted);
}
.pf-label {
  display: block;
  font-size: 0.6875rem;
  font-weight: 600;
  color: var(--text-muted);
}
</style>
