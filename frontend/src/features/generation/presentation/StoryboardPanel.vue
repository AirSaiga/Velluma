<script setup lang="ts">
/**
 * BS-ADF 分镜工作台（DDE-BS 重构后新增，挂「节拍」tab，取代原双 Modal）。
 *
 * 职责：渐进式展开的分镜卡列表——每段一卡，覆盖三种状态：
 * - Track B 暂停态（editable）：卡片可编辑（核心转折/必现画面/台词）+
 *   剧情走向 radio 选择（default 预选），底部「开始渲染」提交 confirm-beats
 *   （含 edited_slots + branch_choices + skipped）。
 * - Track A / 渲染后（只读为主）：卡片展示 + 「极速微调」展开编辑 +
 *   「🎲 定点渲染本段」（/rerender-beat 携带 edited_slot）。
 * - 救援内联卡（路线 C）：命中 rescueNeeded 或 degraded 的卡高亮警示条
 *   「⚠ 第 N 段核心转折未落地」+ 内联编辑 + 「拯救本段」按钮。
 *
 * 分支展示：Track B 暂停态可点选；Track A 自动应用后只读展示「AI 默认走向」；
 * NLE-ADF 步进岔路门（选走向/补缺口）不在本组件——决策交互已上移
 * BranchDecisionPanel（顶部决策区），待决卡仅以 st-branch_choosing 高亮呼应。
 * 警示：后端 /confirm-beats 是先按 branch_choices 突变、再用 edited_slots 整卡覆盖
 * ——整卡覆盖会冲掉突变结果，故提交前本组件把所选走向镜像写入卡的 branch_directive
 * （格式与后端 slot_mutator 一致：label。plot_impact）。
 * P6 契约加固（2026-07-31）：
 * - confirm 唯一出口 = handleConfirm（焦点条不再提供「开始渲染」主按钮，双入口已收敛）；
 * - 镜像逻辑提取为 buildConfirmPayload，草稿/选择/镜像三者在一次调用内同源构建；
 * - 提交前守卫：草稿重复 beat_id 直接阻止提交；暂停态进入时校验卡集合内部一致性。
 *   任何一侧字段增删时，改 buildConfirmPayload 一处即可，勿在模板/其他函数里再写镜像。
 *
 * 纯 presentation 组件：不 import services，全部数据走 props，全部动作走 emits。
 */
import { computed, ref, watch } from 'vue'
import type {
  BeatSlot,
  ChapterDecisionSet,
  DegradedBeat,
  RenderProgress,
  RescueNeededItem,
  StoryBranch,
} from '../../../services/api/domain'
import { formatDegradedReason } from '../../../shared/constants/degradation'
import BeatSlotCardView from './BeatSlotCardView.vue'
import Icon from '../../../components/Icon.vue'

const props = withDefaults(defineProps<{
  slots: BeatSlot[]
  decisionSet?: ChapterDecisionSet | null
  rescueNeeded?: RescueNeededItem[]
  degraded?: DegradedBeat[]
  renderProgress?: RenderProgress[]
  /** 本章高潮一句话摘要（来自 ADF_ANCHOR_DESIGNED.climax_description） */
  climaxSummary?: string
  /** Track B 暂停态：卡片可编辑 + 底部「开始渲染」 */
  editable?: boolean
  /** 生成/渲染进行中（禁用重渲染按钮，防并发） */
  busy?: boolean
  /** 正在单卡重渲染的 beat_id（该卡亮「渲染中」灯 + 按钮禁用防连点） */
  rerenderingBeatId?: string | null
  // NLE-ADF 步进态（来自 session.lockedBeatIds / readyBeatId / renderingBeatId）
  /** 已锁死的 beat_id 集合 */
  steppingLockedIds?: Set<string> | null
  /** 当前已就绪等空格推进的 beat_id */
  steppingReadyId?: string | null
  /** 当前就绪段是否为降级就绪（渲染失败等作者手写/跳过；状态灯亮警告而非「已就绪」） */
  steppingReadyDegraded?: boolean
  /** 正在渲染的 beat_id（步进模式下逐段渲染） */
  steppingRenderingId?: string | null
  /** NLE-ADF 步进岔路门：当前待作者选走向的 beat_id（null = 无待决策岔路） */
  branchChoicePendingBeatId?: string | null
}>(), {
  decisionSet: null,
  rescueNeeded: () => [],
  degraded: () => [],
  renderProgress: () => [],
  climaxSummary: '',
  editable: false,
  busy: false,
  rerenderingBeatId: null,
  steppingLockedIds: null,
  steppingReadyId: null,
  steppingReadyDegraded: false,
  steppingRenderingId: null,
  branchChoicePendingBeatId: null,
})

const emit = defineEmits<{
  (e: 'confirm', payload: { edited_slots: BeatSlot[]; branch_choices: Record<string, string>; skipped: boolean }): void
  (e: 'cancel'): void
  /** 定点重渲染 / 拯救本段：携带作者编辑后的整卡 */
  (e: 'rerender', slot: BeatSlot): void
  /** 放弃某个降级段（保留占位） */
  (e: 'skip-degraded', beatId: string): void
  /** 忽略某条救援标记 */
  (e: 'dismiss-rescue', beatId: string): void
}>()

// ============================================================
// Track B 暂停态：编辑草稿 + 分支选择
// ============================================================
// 深拷贝槽位卡：作者编辑不直接污染 session（confirm 前可取消放弃）
function deepClone<T>(v: T): T {
  try {
    return structuredClone(v)
  } catch {
    return JSON.parse(JSON.stringify(v))
  }
}

const draftSlots = ref<BeatSlot[]>([])
/** 分支选择 { beat_id: option_id }，进入暂停态时用 default_option 预选 */
const branchChoices = ref<Record<string, string>>({})

watch(
  () => props.editable,
  (editable) => {
    if (editable) {
      draftSlots.value = deepClone(props.slots)
      // P6 守卫：暂停态卡集合不允许重复 beat_id（statusOf/渲染按 beat_id 索引，
      // 重复会让状态灯与分支选择错位）。克隆自同一数组本不会触发，但防御
      // 上游（session.loadForChapter 等）混入脏数据。
      const ids = props.slots.map(s => s.beat_id)
      if (new Set(ids).size !== ids.length) {
        console.warn('[StoryboardPanel] 槽位卡存在重复 beat_id，状态灯/分支选择将错位', ids)
      }
      const init: Record<string, string> = {}
      for (const node of props.decisionSet?.decision_nodes || []) {
        // 缺口提示节点不走 radio 预选（补充文本在 gapSupplements 里收集）
        if (node.source === 'loop1_gap') continue
        init[node.beat_id] = node.default_option || node.options[0]?.option_id || ''
      }
      branchChoices.value = init
    }
  },
  { immediate: true },
)

/** 展示用卡：暂停态用草稿，其余用 session 持有的卡 */
function displaySlot(slot: BeatSlot): BeatSlot {
  if (props.editable) {
    return draftSlots.value.find(s => s.beat_id === slot.beat_id) || slot
  }
  return quickEdits.value[slot.beat_id] || slot
}

// ============================================================
// 只读态：极速微调（按卡展开的编辑草稿）
// ============================================================
/** { beat_id: 编辑中的卡副本 }；存在即该卡处于「极速微调」展开态 */
const quickEdits = ref<Record<string, BeatSlot>>({})

function startQuickEdit(slot: BeatSlot) {
  quickEdits.value[slot.beat_id] = deepClone(slot)
}

function cancelQuickEdit(slot: BeatSlot) {
  delete quickEdits.value[slot.beat_id]
}

function handleRerender(slot: BeatSlot) {
  const card = quickEdits.value[slot.beat_id] || slot
  delete quickEdits.value[slot.beat_id]
  emit('rerender', card)
}

// ============================================================
// 分支（剧情走向）
// ============================================================
function branchNodeOf(beatId: string): StoryBranch | null {
  return props.decisionSet?.decision_nodes.find(n => n.beat_id === beatId) || null
}

/**
 * 状态轨 chip 的岔路标记：该段挂有走向节点且尚未轮到处置（渲染/锁定后自然消失）。
 * 状态轨取代了原 BeatProgress 统计行的「N 处剧情走向待选」——
 * 「哪一段有路口」直接标在对应 chip 上，比汇总计数更可定位。
 */
function hasPendingBranch(slot: BeatSlot): boolean {
  return !!branchNodeOf(slot.beat_id) && ['queued', 'rendering', 'branch_choosing'].includes(statusOf(slot))
}

function selectBranch(beatId: string, optionId: string) {
  // Track B 暂停态点选只记录、不提交（提交统一走底部「开始渲染」CTA）
  branchChoices.value[beatId] = optionId
}

// ============================================================
// Loop1 大纲缺口节点（source=loop1_gap）：Track B 暂停态的补充输入，
// 提交时由 buildConfirmPayload 收进 custom: 通道。
// 步进岔路门的缺口/走向决策已上移 BranchDecisionPanel（顶部决策区）。
// ============================================================
/** { beat_id: 作者输入的补充文本 }（Track B 暂停态用） */
const gapSupplements = ref<Record<string, string>>({})

function isGapNode(beatId: string): boolean {
  return branchNodeOf(beatId)?.source === 'loop1_gap'
}

/** 缺口提示语（单 option 的 label，如"建议补充：主角为何采取此行动"）作输入占位 */
function gapPlaceholder(beatId: string): string {
  return branchNodeOf(beatId)?.options[0]?.label || '补充说明（可选）'
}

/** 只读展示：取该卡实际注入的走向文本（branch_directive 真非空才显示，
 *  否则返回空——步进模式下未选走向时不再回退默认选项）。 */
function appliedBranchLabel(slot: BeatSlot): string {
  return slot.branch_directive || ''
}

// ============================================================
// 状态灯 / 救援与降级匹配
// ============================================================
type CardStatus = 'ready' | 'rendering' | 'rendered' | 'skipped' | 'rescue' | 'degraded' | 'branch_choosing' | 'queued'

const STATUS_META: Record<CardStatus, { label: string; icon: string; spin?: boolean }> = {
  ready: { label: '已就绪', icon: 'clock' },
  rendering: { label: '渲染中', icon: 'loader', spin: true },
  rendered: { label: '已定稿', icon: 'check-circle' },
  skipped: { label: '已跳过', icon: 'no-symbol' },
  rescue: { label: '需救援', icon: 'exclamation-circle' },
  degraded: { label: '渲染降级', icon: 'exclamation-circle' },
  branch_choosing: { label: '选走向中', icon: 'bolt' },
  queued: { label: '待渲染', icon: 'ellipsis' },
}

/** 步进模式进行中（有待裁决段/正在步进渲染/岔路门挂起）：此时只允许操作当前待裁决段。
 *  ⚠ 必须含岔路门态——岔路门期间 session 清空了 ready/rendering id，不含它会让
 *  未轮到段误标「已就绪」（queued 守卫失效）、待决卡误出现「重写本段」（点它会
 *  走与 SteppingRun 脱节的 /rerender-beat 旧路径）。 */
const steppingActive = computed(() => !!(props.steppingReadyId || props.steppingRenderingId || props.branchChoicePendingBeatId))

function rescueItemOf(slot: BeatSlot): RescueNeededItem | null {
  return props.rescueNeeded.find(r =>
    (r.beat_id && r.beat_id === slot.beat_id) ||
    (r.segment_index >= 0 && r.segment_index === slot.segment_index),
  ) || null
}

function degradedItemOf(slot: BeatSlot): DegradedBeat | null {
  return props.degraded.find(d => d.beat_id === slot.beat_id) || null
}

function statusOf(slot: BeatSlot): CardStatus {
  // 单卡重渲染进行中：亮「渲染中」灯（优先于救援/降级，按钮同时被禁用）
  if (props.rerenderingBeatId && props.rerenderingBeatId === slot.beat_id) return 'rendering'
  // NLE-ADF 步进态：已锁死→rendered，就绪等推进→ready，渲染中→rendering
  if (props.steppingLockedIds?.has(slot.beat_id)) return 'rendered'
  // 降级就绪：亮警告灯而非「已就绪」绿灯（与正文预览「⚠ 渲染失败 · 待处理」口径一致）
  if (props.steppingReadyId === slot.beat_id) return props.steppingReadyDegraded ? 'degraded' : 'ready'
  if (props.steppingRenderingId === slot.beat_id) return 'rendering'
  if (props.branchChoicePendingBeatId === slot.beat_id) return 'branch_choosing'
  if (rescueItemOf(slot)) return 'rescue'
  if (degradedItemOf(slot)) return 'degraded'
  // 渲染进度兜底：skipped/ready 等状态在步进进行中也必须优先于 queued 显示
  // （否则跳过段被误标「待渲染」，与 BeatProgress 的「已跳过」矛盾）
  const p = props.renderProgress.find(x => x.beat_id === slot.beat_id)
  if (p) {
    if (p.status === 'rendering') return 'rendering'
    if (p.status === 'ready') return 'ready'
    if (p.status === 'rendered') return 'rendered'
    if (p.status === 'skipped') return 'skipped'
    if (p.status === 'degraded') return 'degraded'
  }
  // 步进模式：未轮到的段不再冒充「已就绪」（否则状态灯失去区分度，
  // 且未来段与待裁决段看起来一模一样——真实误导事故）
  if (steppingActive.value) return 'queued'
  if (slot.status === 'rendered') return 'rendered'
  return 'ready'
}

// 降级 reason 字典已抽到 shared/constants/degradation.ts，三处共用

// ============================================================
// 状态轨 + 单卡展开（节拍 tab UX 重构：卡列表收成一行状态轨，
// 点击段 chip 就地展开该卡详情；Track B editable 态仍用全量列表）
// ============================================================
/** 当前展开的分镜卡 beat_id（null = 全部收起，只显示状态轨） */
const expandedBeatId = ref<string | null>(null)

function toggleExpand(beatId: string) {
  expandedBeatId.value = expandedBeatId.value === beatId ? null : beatId
}

/** 可见卡集合：editable 全量（Track B 批量编辑）；否则仅展开的那张（或空） */
const visibleSlots = computed(() => {
  if (props.editable) return props.slots
  const id = expandedBeatId.value
  if (!id) return []
  const found = props.slots.find(s => s.beat_id === id)
  return found ? [found] : []
})

/** 状态轨右侧统计（沿用原 sb-header 文案） */
const totalWords = computed(() =>
  props.slots.reduce((s, x) => s + (x.target_word_count || 0), 0),
)

/** 完成后有降级/救援段时自动展开第一张问题卡（引导复查，无需作者在状态轨上找） */
watch(
  () => [props.rescueNeeded.length, props.degraded.length],
  () => {
    if (expandedBeatId.value) return
    const first = props.slots.find(s => rescueItemOf(s) || degradedItemOf(s))
    if (first) expandedBeatId.value = first.beat_id
  },
  { immediate: true },
)

/** 换章/新会话（卡集合整体替换）时收起展开态，避免展开着上一章的卡 */
watch(
  () => props.slots,
  (slots) => {
    if (expandedBeatId.value && !slots.some(s => s.beat_id === expandedBeatId.value)) {
      expandedBeatId.value = null
    }
  },
)

// ============================================================
// Track B 提交
// ============================================================
const editedCount = computed(() =>
  (props.editable ? draftSlots.value : []).filter(s => s.edited).length,
)

/**
 * 构建 confirm 载荷并镜像分支走向（P6 提取，契约见文件头注释）。
 *
 * 契约：后端 /confirm-beats 先按 branch_choices 突变、再用 edited_slots 整卡覆盖——
 * 整卡覆盖会冲掉突变结果，故此处把所选走向写入卡的 branch_directive
 * （格式与后端 slot_mutator 一致：label。plot_impact）；
 * Loop1 缺口节点只认 custom: 通道（作者补充文本），未补充的节点从 choices 剔除
 * （双保险防提示语注入）。
 *
 * 草稿/选择/补充三者在一次调用内同源构建——字段增删只改这里。
 */
function buildConfirmPayload(
  drafts: BeatSlot[],
  branchChoices: Record<string, string>,
  gapSupplements: Record<string, string>,
  decisionSet: ChapterDecisionSet | null,
): { slots: BeatSlot[]; choices: Record<string, string> } {
  const slots = deepClone(drafts)
  const choices = { ...branchChoices }
  for (const node of decisionSet?.decision_nodes || []) {
    const card = slots.find(s => s.beat_id === node.beat_id)
    if (node.source === 'loop1_gap') {
      const text = (gapSupplements[node.beat_id] || '').trim()
      if (text) {
        choices[node.beat_id] = `custom:${text}`
        if (card) card.branch_directive = text
      } else {
        delete choices[node.beat_id]
      }
      continue
    }
    const chosenId = choices[node.beat_id]
    if (!chosenId) continue
    const opt = node.options.find(o => o.option_id === chosenId)
    if (!opt) continue
    if (card) {
      card.branch_directive = opt.plot_impact ? `${opt.label}。${opt.plot_impact}` : opt.label
    }
  }
  return { slots, choices }
}

function handleConfirm() {
  // P6 守卫：草稿集合内部一致性——重复 beat_id 会让后端按卡覆盖时丢段
  const seen = new Set<string>()
  for (const s of draftSlots.value) {
    if (seen.has(s.beat_id)) {
      console.warn('[StoryboardPanel] 草稿存在重复 beat_id，已阻止提交：', s.beat_id)
      return
    }
    seen.add(s.beat_id)
  }
  const { slots, choices } = buildConfirmPayload(
    draftSlots.value,
    branchChoices.value,
    gapSupplements.value,
    props.decisionSet,
  )
  emit('confirm', {
    edited_slots: slots,
    branch_choices: choices,
    skipped: false,
  })
}

function onSlotEdit(_slot: BeatSlot, _field: string) {
  // 编辑标记由 BeatSlotCardView 在卡对象上就地维护，此处无需额外操作
}
</script>

<template>
  <section class="storyboard">
    <!-- 状态轨：每段一个可点击 chip（合并原脉络条——末段红色底纹 = 高潮段），
         点击就地展开该卡详情，再点收起。Track B editable 态用全量列表，不显示轨。 -->
    <div v-if="!editable && slots.length > 0" class="sb-rail">
      <button
        v-for="slot in slots"
        :key="slot.beat_id"
        class="rail-seg"
        :class="[`st-${statusOf(slot)}`, { active: expandedBeatId === slot.beat_id, climax: slot.segment_index === slots.length - 1 }]"
        :title="`第 ${slot.segment_index + 1} 段 · ${STATUS_META[statusOf(slot)].label}${slot.segment_index === slots.length - 1 ? ' · 高潮段' : ''}${hasPendingBranch(slot) ? ' · 有剧情走向待选' : ''}（点击查看分镜卡）`"
        @click="toggleExpand(slot.beat_id)"
      >
        <Icon
          :name="STATUS_META[statusOf(slot)].icon"
          :size="12"
          :class="{ 'rail-icon': true, spin: !!STATUS_META[statusOf(slot)].spin }"
        />
        <span class="rail-num">{{ slot.segment_index + 1 }}</span>
        <Icon v-if="hasPendingBranch(slot)" name="bolt" :size="10" class="rail-branch" />
      </button>
      <span class="rail-climax-tag">→高潮</span>
      <span class="rail-total">{{ slots.length }} 段 · 约 {{ totalWords }} 字</span>
    </div>
    <!-- 高潮一句话摘要（原脉络条第二行，保留） -->
    <p v-if="!editable && climaxSummary" class="sb-climax" :title="climaxSummary">
      高潮：{{ climaxSummary }}
    </p>

    <header v-if="editable" class="sb-header">
      <span class="sb-title">分镜卡（{{ slots.length }} 段 · 约 {{ totalWords }} 字）</span>
      <span v-if="editedCount" class="sb-edited">{{ editedCount }} 段已修改</span>
    </header>

    <p v-if="editable" class="sb-intro">
      每段的核心转折、必现画面、台词都可以直接改；有剧情岔路的段落内选择走向（已预选最顺大纲的一条）。
      确认后按段顺序渲染。
    </p>
    <!-- 岔路检查结论：两种模式下都可见（editable 时附在编辑说明下方）。
         「有走向待选」通知已删除——待选段落由卡上 branch-preview 标注，
         轮到决策时由顶部 BranchDecisionPanel 直接呈现，此处不再重复。 -->
    <p v-if="decisionSet && !decisionSet.has_story_branch" class="sb-intro muted">
      ⚡ 已检查剧情走向：本章无真正岔路，AI 按大纲顺势推进。
    </p>

    <div class="sb-list">
      <div
        v-for="slot in visibleSlots"
        :key="slot.beat_id"
        class="sb-card"
        :class="`st-${statusOf(slot)}`"
        :data-beat-id="slot.beat_id"
      >
        <!-- 救援警示条（路线 C：审计判核心转折未落地） -->
        <div v-if="rescueItemOf(slot)" class="alert-bar rescue">
          <div class="alert-title">⚠ 第 {{ slot.segment_index + 1 }} 段核心转折未落地</div>
          <div class="alert-detail">
            应有的转折：{{ rescueItemOf(slot)!.core_plot_event || rescueItemOf(slot)!.outline_beat }}
          </div>
        </div>
        <!-- 降级警示条（渲染多次失败降级） -->
        <div v-else-if="degradedItemOf(slot)" class="alert-bar degraded">
          <div class="alert-title">⚠ 第 {{ slot.segment_index + 1 }} 段渲染降级</div>
          <div class="alert-detail">
            原因：{{ formatDegradedReason(degradedItemOf(slot)!.reason) }}
            （已尝试 {{ degradedItemOf(slot)!.attempts }} 次）
          </div>
        </div>

        <!-- 卡体：3 字段编辑骨架（暂停态可编辑 / 极速微调展开时可编辑 / 其余只读）；
             卡头（段号/类型/字数/状态灯/展开）由 BeatSlotCardView 统一渲染 -->
        <BeatSlotCardView
          :slot="displaySlot(slot)"
          :readonly="!editable && !quickEdits[slot.beat_id]"
          :status-icon="STATUS_META[statusOf(slot)].icon"
          :status-icon-spin="STATUS_META[statusOf(slot)].spin"
          :status-label="STATUS_META[statusOf(slot)].label"
          :status-class="`st-${statusOf(slot)}`"
          @edit="onSlotEdit"
        />

        <!-- ⚡ 岔路预告条：本段有走向要选，但还没轮到（queued）时，提前告知作者。
             解决"知道有 N 个路口、不知道在第几段"的定位焦虑。
             轮到时（branch_choosing）走下方 branch-block 的完整选择 UI。 -->
        <div
          v-if="branchNodeOf(slot.beat_id) && !editable && statusOf(slot) === 'queued'"
          class="branch-preview"
          :class="{ 'gap-preview': isGapNode(slot.beat_id) }"
        >
          <Icon :name="isGapNode(slot.beat_id) ? 'pencil-square' : 'bolt'" :size="16" :class="{ 'bp-icon': true, 'gap-icon': isGapNode(slot.beat_id) }" />
          <span class="bp-text">
            <span class="bp-tag" :class="{ 'gap-tag': isGapNode(slot.beat_id) }">{{ isGapNode(slot.beat_id) ? '大纲缺口待补' : '剧情走向待选' }}</span>
            <span class="bp-title">{{ branchNodeOf(slot.beat_id)!.node_title }}</span>
          </span>
          <span class="bp-hint">渲染到本段时会让你选</span>
        </div>

        <!-- ⚡ 剧情走向分支 / 📝 大纲缺口：视觉上用不同颜色区分两类节点。
             步进岔路门（branch_choosing）时本块整体隐藏——决策交互在顶部
             BranchDecisionPanel，卡只用 st-branch_choosing 高亮描边呼应。 -->
        <div v-if="branchNodeOf(slot.beat_id) && statusOf(slot) !== 'branch_choosing'" class="branch-block" :class="{ 'gap-block': isGapNode(slot.beat_id) }">
          <!-- Loop1 大纲缺口：补充输入（不是走向选择题，无 radio） -->
          <template v-if="isGapNode(slot.beat_id)">
            <div class="branch-title gap-title">
              <Icon name="pencil-square" :size="14" /> 大纲缺口：{{ branchNodeOf(slot.beat_id)!.node_title }}
            </div>
            <div v-if="editable" class="gap-supplement">
              <textarea
                v-model="gapSupplements[slot.beat_id]"
                class="gap-input"
                rows="2"
                :placeholder="gapPlaceholder(slot.beat_id)"
              ></textarea>
            </div>
            <!-- 只读态：已注入的作者补充 -->
            <p v-else-if="appliedBranchLabel(displaySlot(slot))" class="branch-readonly">
              ⚡ 作者补充：{{ appliedBranchLabel(displaySlot(slot)) }}
            </p>
          </template>
          <!-- 普通 DDE 走向题 -->
          <template v-else>
            <div class="branch-title">⚡ 剧情走向：{{ branchNodeOf(slot.beat_id)!.node_title }}</div>
            <!-- Track B 暂停态：radio 点选（仅预选，提交走底部「开始渲染」CTA） -->
            <div v-if="editable" class="branch-options">
              <label
                v-for="opt in branchNodeOf(slot.beat_id)!.options"
                :key="opt.option_id"
                class="branch-option"
                :class="{ selected: branchChoices[slot.beat_id] === opt.option_id }"
              >
                <input
                  type="radio"
                  :name="`branch-${slot.beat_id}`"
                  :value="opt.option_id"
                  :checked="branchChoices[slot.beat_id] === opt.option_id"
                  @change="selectBranch(slot.beat_id, opt.option_id)"
                />
                <span class="opt-body">
                  <span class="opt-label">{{ opt.label }}</span>
                  <span v-if="opt.plot_impact" class="opt-impact">{{ opt.plot_impact }}</span>
                </span>
              </label>
            </div>
            <!-- 只读态：已注入的走向 -->
            <p v-else-if="appliedBranchLabel(displaySlot(slot))" class="branch-readonly">
              ⚡ AI 默认走向：{{ appliedBranchLabel(displaySlot(slot)) }}
            </p>
          </template>
        </div>

        <!-- 卡级动作（只读态）。
             分工：焦点条（CurrentTaskBar）管段级裁决（接受/重写/回退/跳过；改正文直接在主编辑器进行），
             StoryboardPanel 卡内只保留【降级/救援的跳过·忽略】和【完成后的逐段重写】。
             - 步进进行中（steppingActive）：隐藏「重写本段」（归焦点条②），仅降级/救援段保留跳过/忽略。
             - 完成后浏览（!steppingActive）：保留「重写本段」供事后逐段重渲。 -->
        <div v-if="!editable && (!steppingActive || degradedItemOf(slot) || rescueItemOf(slot) || quickEdits[slot.beat_id])" class="card-actions">
          <template v-if="quickEdits[slot.beat_id]">
            <button class="sb-btn ghost" @click="cancelQuickEdit(slot)">收起</button>
            <button
              class="sb-btn primary"
              :disabled="busy || rerenderingBeatId === slot.beat_id"
              @click="handleRerender(slot)"
            >重生成</button>
          </template>
          <template v-else>
            <button
              v-if="!steppingActive"
              class="sb-btn"
              :disabled="busy || rerenderingBeatId === slot.beat_id"
              :title="'改分镜卡（核心转折 / 必现画面 / 台词）后重新生成本段'"
              @click="startQuickEdit(slot)"
            >重写本段</button>
            <button
              v-if="degradedItemOf(slot)"
              class="sb-btn ghost"
              @click="emit('skip-degraded', slot.beat_id)"
            >跳过</button>
            <button
              v-if="rescueItemOf(slot)"
              class="sb-btn ghost"
              @click="emit('dismiss-rescue', slot.beat_id)"
            >忽略</button>
          </template>
        </div>
      </div>
    </div>

    <!-- Track B 暂停态底部 CTA -->
    <footer v-if="editable" class="sb-footer">
      <button class="sb-btn" @click="emit('cancel')">取消（回滚）</button>
      <button class="sb-btn primary" @click="handleConfirm">
        开始渲染（{{ slots.length }} 段<span v-if="editedCount"> · {{ editedCount }} 处修改</span>）
      </button>
    </footer>
  </section>
</template>

<style scoped>
.storyboard {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  padding: 0.75rem 0.875rem;
  background: var(--bg-canvas);
  border: 1px solid var(--border-color);
  border-radius: 0.5rem;
}

.sb-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.sb-title {
  font-size: 0.9375rem;
  font-weight: 500;
  color: var(--text-primary);
}
.sb-edited {
  font-size: 0.875rem;
  color: var(--accent-500);
}

.sb-intro {
  font-size: 0.875rem;
  color: var(--text-secondary);
  line-height: 1.6;
  margin: 0;
  padding: 0.5rem 0.625rem;
  background: var(--bg-secondary);
  border-radius: 0.375rem;
  border-left: 3px solid var(--accent-500);
}
.sb-intro.muted {
  border-left-color: var(--text-muted);
  color: var(--text-muted);
}

/* 状态轨：一行段 chip，点击展开对应分镜卡（原脉络条并入——末段红色底纹 = 高潮段）。
   flex-wrap：窄栏下「→高潮 / 字数统计」折到第二行，不被裁断（真实事故：
   6 段章在检查器窄栏里 rail-total 只剩"6 段 · 约"半截）。 */
.sb-rail {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.25rem;
  padding: 0.375rem 0.5rem;
  background: var(--bg-secondary);
  border-radius: 0.375rem;
}
.rail-seg {
  display: inline-flex;
  align-items: center;
  gap: 0.1875rem;
  padding: 0.25rem 0.4375rem;
  border-radius: 0.3125rem;
  border: 1px solid transparent;
  font-size: 0.75rem;
  font-weight: 500;
  color: var(--text-muted);
  cursor: pointer;
  transition: all 0.15s;
}
.rail-seg:hover { background: var(--hover-bg); }
.rail-seg.active {
  border-color: var(--accent-500);
  background: rgba(124, 106, 173, 0.08);
}
.rail-seg.st-rendered { color: #16a34a; }
.rail-seg.st-rendering { color: var(--accent-500); }
.rail-seg.st-branch_choosing {
  color: var(--accent-500);
  border-color: var(--accent-500);
}
.rail-seg.st-rescue,
.rail-seg.st-degraded { color: #d97706; }
.rail-seg.st-skipped { color: #6b7280; opacity: 0.7; }
/* 高潮段（末段）红色底纹，沿用原脉络条语义 */
.rail-seg.climax:not(.active) {
  background: rgba(199, 84, 80, 0.12);
}
.rail-icon.spin {
  display: inline-block;
  animation: rail-spin 1s linear infinite;
}
@keyframes rail-spin {
  to { transform: rotate(360deg); }
}
/* 岔路标记：该段有走向待选（取代原 BeatProgress 行的「N 处剧情走向待选」汇总） */
.rail-branch {
  color: var(--accent-500);
  margin-left: -0.0625rem;
}
.rail-climax-tag {
  font-size: 0.625rem;
  color: #c75450;
  margin-left: 0.125rem;
  white-space: nowrap;
}
.rail-total {
  margin-left: auto;
  font-size: 0.75rem;
  color: var(--text-muted);
  white-space: nowrap;
}
.sb-climax {
  margin: 0;
  font-size: 0.6875rem;
  color: var(--text-secondary);
  line-height: 1.4;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sb-list {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.sb-card {
  display: flex;
  flex-direction: column;
  gap: 0.625rem;
  padding: 0.625rem 0.75rem;
  border-radius: 0.5rem;
  border: 1px solid transparent;
}
.sb-card.st-rescue,
.sb-card.st-degraded {
  border-color: rgba(217, 119, 6, 0.45);
  background: rgba(217, 119, 6, 0.04);
}
/* 岔路门待决卡高亮：与顶部 BranchDecisionPanel 决策区呼应 */
.sb-card.st-branch_choosing {
  border-color: var(--accent-500);
  background: rgba(124, 106, 173, 0.05);
}
.sb-card.st-skipped {
  opacity: 0.6;
}

.alert-bar {
  padding: 0.4375rem 0.625rem;
  border-radius: 0.375rem;
  border-left: 3px solid #d97706;
  background: rgba(217, 119, 6, 0.08);
}
.alert-title {
  font-size: 0.875rem;
  font-weight: 600;
  color: #92400e;
}
.alert-detail {
  font-size: 0.875rem;
  color: var(--text-secondary);
  margin-top: 0.125rem;
  line-height: 1.5;
}

/* ⚡ 岔路预告条：未轮到的段提前标注有走向待选 */
.branch-preview {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-top: 0.5rem;
  padding: 0.5rem 0.625rem;
  background: rgba(124, 106, 173, 0.06);
  border: 1px dashed var(--accent-500, #7c6aad);
  border-radius: 0.375rem;
  font-size: 0.875rem;
}
.branch-preview.gap-preview {
  background: rgba(37, 99, 235, 0.06);
  border-color: #2563eb;
}
.bp-icon {
  flex: 0 0 auto;
  color: var(--accent-500, #7c6aad);
}
.bp-icon.gap-icon { color: #2563eb; }
.bp-text {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 1px;
}
.bp-tag {
  font-size: 0.875rem;
  font-weight: 600;
  color: var(--accent-600, #6d5dab);
}
.bp-tag.gap-tag { color: #2563eb; }
.bp-title {
  font-size: 0.875rem;
  color: var(--text-secondary, #6b6560);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.bp-hint {
  flex: 0 0 auto;
  font-size: 0.875rem;
  color: var(--text-muted, #a89e90);
}

.branch-block {
  padding: 0.625rem 0.75rem;
  background: var(--bg-secondary);
  border-radius: 0.375rem;
  border-left: 3px solid #c75450;
}
.branch-block.gap-block {
  border-left-color: #2563eb;
  background: rgba(37, 99, 235, 0.04);
}
.branch-title {
  font-size: 0.875rem;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 0.375rem;
  display: flex;
  align-items: center;
  gap: 0.375rem;
}
.branch-title.gap-title { color: #2563eb; }
.branch-options {
  display: flex;
  flex-direction: column;
  gap: 0.375rem;
}
.branch-option {
  display: flex;
  align-items: flex-start;
  gap: 0.5rem;
  padding: 0.5rem 0.625rem;
  border-radius: 0.3125rem;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  cursor: pointer;
  transition: all 0.15s;
}
.branch-option:hover { background: var(--hover-bg); }
.branch-option.selected {
  border-color: var(--accent-500);
  background: rgba(124, 106, 173, 0.08);
}
.branch-option input[type="radio"] {
  margin: 0.125rem 0 0;
  cursor: pointer;
  accent-color: var(--accent-500);
}
.opt-body {
  display: flex;
  flex-direction: column;
  gap: 0.125rem;
  flex: 1;
}
.opt-label {
  font-size: 0.875rem;
  color: var(--text-primary);
  line-height: 1.5;
}
.opt-impact {
  font-size: 0.875rem;
  color: var(--text-muted);
  line-height: 1.4;
}
.branch-readonly {
  font-size: 0.875rem;
  color: var(--text-secondary);
  margin: 0;
  line-height: 1.5;
}

/* Loop1 大纲缺口补充输入框 */
.gap-supplement {
  display: flex;
  flex-direction: column;
  gap: 0.375rem;
}
.gap-input {
  width: 100%;
  padding: 0.4375rem 0.625rem;
  border-radius: 0.3125rem;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  font-size: 0.875rem;
  color: var(--text-primary);
  line-height: 1.5;
  resize: vertical;
  font-family: inherit;
}
.gap-input:focus {
  outline: none;
  border-color: var(--accent-500);
}
.gap-input::placeholder {
  color: var(--text-muted);
}

.card-actions {
  display: flex;
  justify-content: flex-end;
  gap: 0.375rem;
}

.sb-footer {
  display: flex;
  justify-content: flex-end;
  gap: 0.5rem;
  padding-top: 0.5rem;
  border-top: 1px solid var(--border-color);
}

.sb-btn {
  padding: 0.4375rem 0.875rem;
  font-size: 0.875rem;
  border: 1px solid var(--border-color);
  background: var(--bg-secondary);
  color: var(--text-primary);
  border-radius: 0.25rem;
  cursor: pointer;
  transition: all 0.15s;
}
.sb-btn:hover:not(:disabled) { opacity: 0.85; }
.sb-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.sb-btn.primary {
  background: var(--accent-500);
  color: white;
  border-color: var(--accent-500);
}
.sb-btn.primary:hover:not(:disabled) { background: var(--accent-600); }
.sb-btn.ghost {
  background: transparent;
  border-color: transparent;
  color: var(--text-secondary);
}
.sb-btn.ghost:hover:not(:disabled) {
  background: var(--hover-bg);
  color: var(--text-primary);
}
</style>
