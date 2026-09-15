<script setup lang="ts">
/**
 * 「AI 此刻读到的」主件（P5 B2 · 09 期重设计 docs/design/ux-redesign/09-ai-view-redesign.md
 * · 2026-09-15 轻量化重构 docs/ai-view-briefing-feasibility.md）。
 *
 * 展示 stitch-ghost 实际注入的上下文块（与真实 system prompt 同源——后端
 * context-preview 与 stitch 路由共用同一装配函数）。轻量化三改造：
 * ①顶层「战局态势」简报卡（后端 briefing 增量字段，零 LLM）——4~5 行高密
 *   态势一眼可辨，行空整行不渲染（简报层不做催收）；
 * ②底层原始块收进默认折叠手风琴（逃生舱），展开完整继承 09 期宪法级资产
 *   （保字排版/原文逐字核对/注入序三段）；
 * ③空块全量静音（未配置块不渲染，EMPTY_HINTS 催收框退役——09 稿批注 #4）。
 * 数据获取在容器（InspectorPanel，光标窗口随请求上行=中插态真切片）。
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

/** 简报·引力行来源人话（对齐世界模型卡 INTENT_SOURCE_LABELS 口径——AI 猜的必须亮身份） */
const BRIEF_INTENT_LABELS: Record<string, string> = {
  request: '本次请求',
  outline: '大纲',
  inferred: 'AI 猜的',
  baton: '上一章接力',
  spine: '你的打算',
}

// ===== 折叠态（组件内不持久化；切章数据置空时随 watch 复位回默认） =====

/** 块级展开：默认只展开「场景身份」（恒居注入序首位且短，保字排版第一眼可见） */
const expandedKeys = ref<Set<string>>(new Set(['scene']))
/** 底层手风琴（逃生舱）：默认折叠——模式切换/刷新不重置（旧数据冻结流不置空
 * preview），只有切章复位（watch preview→null）收回，保持整洁折叠态 */
const rawOpen = ref(false)
/** 「原文」对照开关：全部块正文回退等宽逐字直出（信任逃生舱，不持久化） */
const rawView = ref(false)
const blocksEl = ref<HTMLElement | null>(null)

watch(
  () => props.preview,
  (n) => {
    if (!n) {
      expandedKeys.value = new Set(['scene'])
      rawOpen.value = false
      rawView.value = false
    }
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

/** 原文开关（驻手风琴头行）：打开时顺带展开手风琴——逐字核对需要看得见正文 */
function toggleRawView() {
  rawView.value = !rawView.value
  if (rawView.value) rawOpen.value = true
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

// ===== 战局态势简报（顶层高密卡：行空整行不渲染；全空单行状态陈述非催收） =====

type BriefRow =
  | { kind: 'scene'; label: string; name: string; derived: boolean; bridge: boolean }
  | { kind: 'items'; label: string; items: string[]; sourceLabel?: string }

const briefingRows = computed<BriefRow[]>(() => {
  const b = props.preview?.briefing
  if (!b) return []
  const rows: BriefRow[] = []
  if (b.scene?.name) {
    rows.push({
      kind: 'scene', label: '场景',
      name: b.scene.name,
      derived: !!b.scene.derived,
      bridge: !!b.scene.bridge,
    })
  }
  if (b.onstage?.length) rows.push({ kind: 'items', label: '在场', items: b.onstage })
  if (b.props?.length) rows.push({ kind: 'items', label: '焦点物件', items: b.props })
  if (b.secrets?.length) rows.push({ kind: 'items', label: '守死秘密', items: b.secrets })
  if (b.intent) {
    rows.push({
      kind: 'items', label: '引力', items: [b.intent],
      sourceLabel: b.intent_source ? BRIEF_INTENT_LABELS[b.intent_source] || b.intent_source : undefined,
    })
  }
  return rows
})

// ===== 段分组（注入序切段；段是视觉切分，块才是折叠单元） =====

// 空块静音（2026-09-15）：未配置块不渲染，整段皆空的段自动消失——不造催收框
const segments = computed(() => {
  if (!props.preview) return []
  return SEGMENT_ORDER.map((id) => ({
    id,
    title: SEGMENT_TITLES[id],
    blocks: props.preview!.blocks.filter((b) => b.content && segmentOfKey(b.key) === id),
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
    <p class="ctx-hint">AI 续写时将参考以下事实与约束；态势一眼可辨，逐字细节收在底层。</p>

    <template v-if="preview">
      <div class="ctx-summary">
        <span>{{ worldTimeLabel }}</span>
        <span class="dot">·</span>
        <span>{{ preview.world_sourced ? '设定来自世界页' : '设定来自章节' }}</span>
        <button
          class="sum-refresh"
          title="按当前正文与设定重新读取"
          :disabled="loading"
          @click="emit('refresh')"
        ><Icon name="arrow-path" :size="13" :class="{ spin: loading }" /></button>
      </div>

      <!-- 战局态势简报（顶层高密卡；行空整行不渲染，全空单行状态陈述） -->
      <div class="ctx-briefing" :class="{ 'is-reloading': isReloading }">
        <div class="bf-head">战局态势</div>
        <template v-if="briefingRows.length">
          <div v-for="row in briefingRows" :key="row.label" class="bf-row">
            <span class="bf-k">{{ row.label }}</span>
            <span class="bf-v">
              <template v-if="row.kind === 'scene'">
                <span class="bf-scene">{{ row.name }}</span>
                <span class="bf-tag" :class="{ 'is-derived': row.derived }">{{ row.derived ? '正文推导' : '本章钉' }}</span>
                <span v-if="row.bridge" class="bf-tag is-bridge">中插</span>
              </template>
              <template v-else>
                <span v-for="(item, i) in row.items" :key="i" class="bf-item" :title="item">{{ item }}</span>
                <span v-if="row.sourceLabel" class="bf-src">{{ row.sourceLabel }}</span>
              </template>
            </span>
          </div>
        </template>
        <div v-else class="bf-none">暂无态势</div>
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

      <!-- 底层逃生舱：原始提示词块手风琴（默认折叠；展开继承 09 期全部资产） -->
      <div class="ctx-raw" :class="{ 'is-open': rawOpen }">
        <div class="raw-head">
          <button class="raw-toggle" @click="rawOpen = !rawOpen">
            <Icon name="chevron-right" :size="12" class="raw-chev" />
            <span class="raw-title">查看底层原始提示词细节<template v-if="totalLabel">（共 {{ totalLabel }} 字）</template></span>
          </button>
          <button
            class="sum-raw"
            :class="{ on: rawView }"
            title="显示 AI 实际读到的原始文本（逐字等宽）"
            @click="toggleRawView"
          >原文</button>
        </div>
        <div class="raw-body">
          <div class="raw-clip">
            <div ref="blocksEl" class="ctx-blocks" :class="{ 'is-reloading': isReloading }">
              <section v-for="seg in segments" :key="seg.id" class="ctx-seg">
                <div class="seg-label">{{ seg.title }}</div>
                <template v-for="b in seg.blocks" :key="b.key">
                  <div class="blk" :class="{ 'is-open': isOpen(b) }" :data-blk="b.key">
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
          </div>
        </div>
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
  font-size: var(--text-xs);
  color: var(--text-muted);
  line-height: 1.5;
  margin: 0;
}

/* ===== 汇总行（时刻/来源一行 + 刷新；总字数移驻手风琴头行） ===== */
.ctx-summary {
  display: flex;
  align-items: center;
  gap: 0.3rem;
  font-size: var(--text-xs);
  color: var(--text-muted);
  font-variant-numeric: tabular-nums;
}
.ctx-summary .dot {
  opacity: 0.5;
}
.sum-raw {
  padding: 0.0625rem 0.4375rem;
  font-size: var(--text-xs);
  color: var(--text-muted);
  background: transparent;
  border: 1px solid var(--border-color);
  border-radius: 999px;
  cursor: pointer;
  transition: all var(--dur-2) var(--ease-out);
}
.sum-raw:hover {
  color: var(--accent-500);
  border-color: var(--accent-400);
}
.sum-raw.on {
  color: var(--accent-500);
  border-color: var(--accent-400);
  background: color-mix(in srgb, var(--accent-400) 14%, transparent);
}
.sum-refresh {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  margin-left: auto;
  color: var(--text-muted);
  background: transparent;
  border: none;
  border-radius: var(--radius-sm);
  cursor: pointer;
}
.sum-refresh:hover {
  color: var(--accent-500);
  background: var(--state-hover);
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

/* ===== 战局态势简报（顶层高密卡；行空不渲染） ===== */
.ctx-briefing {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  padding: 0.5rem 0.625rem;
  background: var(--bg-canvas);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-sm);
}
.ctx-briefing.is-reloading {
  opacity: 0.5;
  transition: opacity var(--dur-2) var(--ease-out);
}
.bf-head {
  font-size: var(--text-xs);
  font-weight: 600;
  color: var(--text-secondary);
  letter-spacing: 0.05em;
}
.bf-row {
  display: flex;
  align-items: baseline;
  gap: 0.5rem;
  font-size: 0.75rem;
  line-height: 1.6;
}
.bf-k {
  flex: 0 0 auto;
  min-width: 3.5em;
  font-size: var(--text-xs);
  font-weight: 600;
  color: var(--text-muted);
}
.bf-v {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 0.25rem 0.375rem;
  color: var(--text-primary);
}
.bf-scene {
  font-weight: 600;
}
.bf-tag {
  display: inline-block;
  padding: 0.03125rem 0.3125rem;
  font-size: var(--text-xs);
  line-height: 1.4;
  border-radius: 999px;
  vertical-align: 0.0625rem;
  color: var(--text-muted);
  background: var(--bg-tertiary);
}
.bf-tag.is-derived {
  color: var(--ok);
  background: color-mix(in srgb, var(--ok) 12%, transparent);
}
.bf-tag.is-bridge {
  color: var(--accent-500);
  background: color-mix(in srgb, var(--accent-400) 14%, transparent);
}
.bf-item {
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--text-secondary);
}
.bf-src {
  font-size: var(--text-xs);
  font-style: italic;
  color: var(--text-muted);
}
.bf-none {
  font-size: var(--text-xs);
  color: var(--text-muted);
}

/* ===== 底层逃生舱（原始块手风琴，默认折叠） ===== */
.ctx-raw {
  margin-top: 0.25rem;
  padding-top: 0.375rem;
  border-top: 1px solid var(--border-color);
}
.raw-head {
  display: flex;
  align-items: center;
  gap: 0.375rem;
}
.raw-toggle {
  flex: 1;
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 0.375rem;
  min-height: 1.75rem;
  padding: 0;
  background: none;
  border: none;
  text-align: left;
  cursor: pointer;
  color: var(--text-secondary);
  font-size: var(--text-xs);
  font-weight: 600;
}
.raw-toggle:hover {
  color: var(--text-primary);
}
.raw-chev {
  flex-shrink: 0;
  color: var(--text-muted);
  transition: transform var(--dur-3) var(--ease-out);
}
.ctx-raw.is-open .raw-chev {
  transform: rotate(90deg);
  color: var(--accent-500);
}
.raw-title {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
}
.raw-body {
  display: grid;
  grid-template-rows: 0fr;
  transition: grid-template-rows var(--dur-3) var(--ease-out);
}
.ctx-raw.is-open .raw-body {
  grid-template-rows: 1fr;
}
.raw-clip {
  overflow: hidden;
  min-height: 0;
}

/* ===== 模式五档 ===== */
.ctx-modes {
  display: flex;
  gap: 0.25rem;
}
.mode-btn {
  flex: 1;
  padding: 0.25rem 0;
  font-size: var(--text-xs);
  color: var(--text-muted);
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: all var(--dur-2) var(--ease-out);
}
.mode-btn:hover {
  color: var(--text-primary);
  border-color: var(--accent-400);
}
.mode-btn.active {
  color: var(--accent-500);
  border-color: var(--accent-400);
  background: color-mix(in srgb, var(--accent-400) 14%, transparent);
  font-weight: 600;
}

/* ===== 首次加载骨架 ===== */
.ctx-loading {
  display: flex;
  flex-direction: column;
  gap: 0.375rem;
}
.ctx-loading-text {
  font-size: var(--text-xs);
  color: var(--text-muted);
}
.skel-label {
  font-size: var(--text-xs);
  font-weight: 600;
  color: var(--text-muted);
  letter-spacing: 0.05em;
  margin-top: 0.375rem;
}
.skel-row {
  height: 1.75rem;
  border-radius: var(--radius-sm);
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
  border: 1px solid var(--danger);
  border-radius: var(--radius-md);
  background: color-mix(in srgb, var(--danger) 6%, transparent);
}
.ctx-error-text {
  flex: 1;
  font-size: var(--text-xs);
  color: var(--danger);
  word-break: break-all;
}
.ctx-error-retry {
  flex-shrink: 0;
  padding: 0.1875rem 0.625rem;
  font-size: var(--text-xs);
  color: var(--danger);
  background: transparent;
  border: 1px solid var(--danger);
  border-radius: var(--radius-sm);
  cursor: pointer;
}
.ctx-error-retry:hover {
  color: var(--bg-canvas);
  background: var(--danger);
}

/* ===== 重读指示（扫描条 + 列表冻结） ===== */
.ctx-reloading {
  display: flex;
  align-items: center;
  gap: 0.375rem;
}
.ctx-reloading span {
  flex-shrink: 0;
  font-size: var(--text-xs);
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
  background: var(--accent-400);
  animation: ctx-scan 1.1s ease-in-out infinite;
}
@keyframes ctx-scan {
  0% { left: -30%; }
  100% { left: 100%; }
}
.ctx-blocks.is-reloading {
  opacity: 0.5;
  pointer-events: none;
  transition: opacity var(--dur-2) var(--ease-out);
}

/* ===== 段分组 ===== */
.ctx-seg + .ctx-seg {
  margin-top: 0.25rem;
}
.seg-label {
  font-size: var(--text-xs);
  font-weight: 600;
  color: var(--text-muted);
  letter-spacing: 0.05em;
  margin: 0.5rem 0 0.375rem;
}
.ctx-seg:first-child .seg-label {
  margin-top: 0.25rem;
}

/* ===== 满块折叠卡 ===== */
.blk {
  background: var(--bg-canvas);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-sm);
  padding: 0.375rem 0.625rem;
}
.blk + .blk {
  margin-top: 0.375rem;
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
  transition: transform var(--dur-3) var(--ease-out);
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
  font-size: var(--text-xs);
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
  background: var(--accent-400);
  transition: width var(--dur-3) var(--ease-out);
}
.blk-meter-fill.hot {
  background: var(--danger);
}
.blk-meter-trim {
  flex-shrink: 0;
  font-size: var(--text-xs);
  color: var(--danger);
}

/* 展开动画（grid 0fr→1fr，无依赖）；展开即全量，滚动交给面板 */
.blk-body {
  display: grid;
  grid-template-rows: 0fr;
  transition: grid-template-rows var(--dur-3) var(--ease-out);
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
  font-family: var(--font-mono);
  font-size: var(--text-xs);
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
  font-size: var(--text-xs);
  font-weight: 600;
  color: var(--text-secondary);
  margin: 0.25rem 0;
}
.nd-sample {
  font-size: var(--text-xs);
  font-weight: 600;
  color: var(--text-muted);
  margin: 0.5rem 0 0.125rem;
}
.nd-sample:first-child {
  margin-top: 0;
}
.nd-note {
  font-size: var(--text-xs);
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
  font-size: var(--text-xs);
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
  font-size: var(--text-xs);
  line-height: 1.4;
  border-radius: 999px;
  vertical-align: 0.0625rem;
}
.it-mark.tone-present {
  color: var(--ok);
  background: color-mix(in srgb, var(--ok) 12%, transparent);
}
.it-mark.tone-dead {
  color: var(--danger);
  font-weight: 600;
  background: color-mix(in srgb, var(--danger) 10%, transparent);
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
  font-size: var(--text-xs);
  color: var(--text-muted);
}
.pf-label {
  display: block;
  font-size: var(--text-xs);
  font-weight: 600;
  color: var(--text-muted);
}
</style>
