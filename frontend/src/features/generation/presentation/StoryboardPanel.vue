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
 * 分支展示：Track B 暂停态可点选；Track A 自动应用后只读展示「AI 默认走向」。
 * 警示：后端 /confirm-beats 是先按 branch_choices 突变、再用 edited_slots 整卡覆盖
 * ——整卡覆盖会冲掉突变结果，故提交前本组件把所选走向镜像写入卡的 branch_directive
 * （格式与后端 slot_mutator 一致：label。plot_impact）。
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
import BeatSlotCardView from './BeatSlotCardView.vue'
import ChapterProgressStrip from './ChapterProgressStrip.vue'

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
  /** 风险5修复：步进岔路门走向选择（branch_choosing 态，单段提交） */
  (e: 'choose-branch', beatId: string, optionId: string): void
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
      const init: Record<string, string> = {}
      for (const node of props.decisionSet?.decision_nodes || []) {
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

function selectBranch(beatId: string, optionId: string) {
  branchChoices.value[beatId] = optionId
  // 风险5修复：步进岔路门态下，选走向直接提交（而非等 confirm 批量提交）
  if (props.branchChoicePendingBeatId === beatId) {
    emit('choose-branch', beatId, optionId)
  }
}

/** 只读展示：取该卡实际注入的走向文本（branch_directive 真非空才显示，
 *  否则返回空——步进模式下未选走向时不再回退默认选项）。 */
function appliedBranchLabel(slot: BeatSlot): string {
  return slot.branch_directive || ''
}

// ============================================================
// 状态灯 / 救援与降级匹配
// ============================================================
type CardStatus = 'ready' | 'rendering' | 'rendered' | 'rescue' | 'degraded' | 'branch_choosing'

const STATUS_META: Record<CardStatus, { label: string; icon: string }> = {
  ready: { label: '已就绪', icon: '○' },
  rendering: { label: '渲染中', icon: '⟳' },
  rendered: { label: '已渲染', icon: '✓' },
  rescue: { label: '需救援', icon: '⚠' },
  degraded: { label: '渲染降级', icon: '⚠' },
  branch_choosing: { label: '选走向中', icon: '⚡' },
}

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
  if (props.steppingReadyId === slot.beat_id) return 'ready'
  if (props.steppingRenderingId === slot.beat_id) return 'rendering'
  if (props.branchChoicePendingBeatId === slot.beat_id) return 'branch_choosing'
  if (rescueItemOf(slot)) return 'rescue'
  if (degradedItemOf(slot)) return 'degraded'
  const p = props.renderProgress.find(x => x.beat_id === slot.beat_id)
  if (p) {
    if (p.status === 'rendering') return 'rendering'
    if (p.status === 'rendered') return 'rendered'
    if (p.status === 'degraded') return 'degraded'
  }
  if (slot.status === 'rendered') return 'rendered'
  return 'ready'
}

const DEGRADED_REASON_LABEL: Record<string, string> = {
  ai_smell: 'AI 腔过重',
  coverage_fail: '必现画面覆盖不足',
  gate_fail: '质检未通过',
  llm_error: '模型调用错误',
}

/** 脉络条当前段：正在渲染的段，否则已渲染段数 */
const currentSegmentIndex = computed(() => {
  const rendering = props.renderProgress.find(p => p.status === 'rendering')
  if (rendering) return rendering.segment_index
  const renderedCount = props.renderProgress.filter(p => p.status === 'rendered').length
  return Math.min(renderedCount, Math.max(props.slots.length - 1, 0))
})

// ============================================================
// Track B 提交
// ============================================================
const editedCount = computed(() =>
  (props.editable ? draftSlots.value : []).filter(s => s.edited).length,
)

function handleConfirm() {
  const slots = deepClone(draftSlots.value)
  // 警示：后端先按 branch_choices 突变、再用 edited_slots 整卡覆盖——
  // 整卡覆盖会冲掉突变，故把所选走向镜像写进卡的 branch_directive
  // （格式与后端 slot_mutator 一致：label。plot_impact）
  for (const node of props.decisionSet?.decision_nodes || []) {
    const chosenId = branchChoices.value[node.beat_id]
    if (!chosenId) continue
    const opt = node.options.find(o => o.option_id === chosenId)
    if (!opt) continue
    const card = slots.find(s => s.beat_id === node.beat_id)
    if (card) {
      card.branch_directive = opt.plot_impact ? `${opt.label}。${opt.plot_impact}` : opt.label
    }
  }
  emit('confirm', {
    edited_slots: slots,
    branch_choices: { ...branchChoices.value },
    skipped: false,
  })
}

function onSlotEdit(_slot: BeatSlot, _field: string) {
  // 编辑标记由 BeatSlotCardView 在卡对象上就地维护，此处无需额外操作
}
</script>

<template>
  <section class="storyboard">
    <!-- 顶部脉络条（全章段数 + 当前渲染位置） -->
    <ChapterProgressStrip
      v-if="slots.length > 0"
      :total-segments="slots.length"
      :current-index="currentSegmentIndex"
      :climax-summary="climaxSummary"
    />

    <header class="sb-header">
      <span class="sb-title">分镜卡（{{ slots.length }} 段 · 约 {{ slots.reduce((s, x) => s + (x.target_word_count || 0), 0) }} 字）</span>
      <span v-if="editable && editedCount" class="sb-edited">{{ editedCount }} 段已修改</span>
    </header>

    <p v-if="editable" class="sb-intro">
      每段的核心转折、必现画面、台词都可以直接改；有剧情岔路的段落内选择走向（已预选最顺大纲的一条）。
      确认后按段顺序渲染。
    </p>
    <!-- 岔路检查结论：两种模式下都可见（editable 时附在编辑说明下方） -->
    <p v-if="decisionSet && !decisionSet.has_story_branch" class="sb-intro muted">
      ⚡ 已检查剧情走向：本章无真正岔路，AI 按大纲顺势推进。
    </p>
    <p v-else-if="decisionSet && decisionSet.has_story_branch && !editable" class="sb-intro muted">
      ⚡ 本章有 {{ decisionSet.decision_nodes.length }} 处剧情岔路，将在对应段落渲染前让你选择走向。
    </p>

    <div class="sb-list">
      <div
        v-for="slot in slots"
        :key="slot.beat_id"
        class="sb-card"
        :class="`st-${statusOf(slot)}`"
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
            原因：{{ DEGRADED_REASON_LABEL[degradedItemOf(slot)!.reason] || degradedItemOf(slot)!.reason }}
            （已尝试 {{ degradedItemOf(slot)!.attempts }} 次）
          </div>
        </div>

        <!-- 卡体：3 字段编辑骨架（暂停态可编辑 / 极速微调展开时可编辑 / 其余只读）；
             卡头（段号/类型/字数/状态灯/展开）由 BeatSlotCardView 统一渲染 -->
        <BeatSlotCardView
          :slot="displaySlot(slot)"
          :readonly="!editable && !quickEdits[slot.beat_id]"
          :status-icon="STATUS_META[statusOf(slot)].icon"
          :status-label="STATUS_META[statusOf(slot)].label"
          :status-class="`st-${statusOf(slot)}`"
          @edit="onSlotEdit"
        />

        <!-- ⚡ 剧情走向分支 -->
        <div v-if="branchNodeOf(slot.beat_id)" class="branch-block">
          <div class="branch-title">⚡ 剧情走向：{{ branchNodeOf(slot.beat_id)!.node_title }}</div>
          <!-- 暂停态 / 步进岔路门：radio 点选 -->
          <div v-if="editable || statusOf(slot) === 'branch_choosing'" class="branch-options">
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
          <!-- 只读态：AI 默认走向 -->
          <p v-else-if="appliedBranchLabel(displaySlot(slot))" class="branch-readonly">
            ⚡ AI 默认走向：{{ appliedBranchLabel(displaySlot(slot)) }}
          </p>
        </div>

        <!-- 卡级动作（只读态）；重渲染中的卡禁用按钮防连点 -->
        <div v-if="!editable" class="card-actions">
          <template v-if="quickEdits[slot.beat_id]">
            <button class="sb-btn ghost" @click="cancelQuickEdit(slot)">收起微调</button>
            <button
              class="sb-btn primary"
              :disabled="busy || rerenderingBeatId === slot.beat_id"
              @click="handleRerender(slot)"
            >{{ statusOf(slot) === 'rescue' || statusOf(slot) === 'degraded' ? '拯救本段' : '🎲 定点渲染本段' }}</button>
          </template>
          <template v-else>
            <button class="sb-btn ghost" @click="startQuickEdit(slot)">极速微调</button>
            <button
              v-if="statusOf(slot) === 'rescue' || statusOf(slot) === 'degraded'"
              class="sb-btn warn"
              :disabled="busy || rerenderingBeatId === slot.beat_id"
              @click="handleRerender(slot)"
            >拯救本段</button>
            <button
              v-else
              class="sb-btn"
              :disabled="busy || rerenderingBeatId === slot.beat_id || statusOf(slot) === 'branch_choosing' || statusOf(slot) === 'ready' || statusOf(slot) === 'rendering'"
              title="按当前分镜卡重新渲染这一段"
              @click="handleRerender(slot)"
            >🎲 定点渲染本段</button>
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
  gap: 0.625rem;
  padding: 0.625rem 0.75rem;
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
  font-size: 0.8125rem;
  font-weight: 500;
  color: var(--text-primary);
}
.sb-edited {
  font-size: 0.6875rem;
  color: var(--accent-500);
}

.sb-intro {
  font-size: 0.75rem;
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

.sb-list {
  display: flex;
  flex-direction: column;
  gap: 0.625rem;
}

.sb-card {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  padding: 0.5rem;
  border-radius: 0.5rem;
  border: 1px solid transparent;
}
.sb-card.st-rescue,
.sb-card.st-degraded {
  border-color: rgba(217, 119, 6, 0.45);
  background: rgba(217, 119, 6, 0.04);
}

.alert-bar {
  padding: 0.4375rem 0.625rem;
  border-radius: 0.375rem;
  border-left: 3px solid #d97706;
  background: rgba(217, 119, 6, 0.08);
}
.alert-title {
  font-size: 0.75rem;
  font-weight: 600;
  color: #92400e;
}
.alert-detail {
  font-size: 0.6875rem;
  color: var(--text-secondary);
  margin-top: 0.125rem;
  line-height: 1.5;
}

.branch-block {
  padding: 0.5rem 0.625rem;
  background: var(--bg-secondary);
  border-radius: 0.375rem;
  border-left: 3px solid #c75450;
}
.branch-title {
  font-size: 0.75rem;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 0.375rem;
}
.branch-options {
  display: flex;
  flex-direction: column;
  gap: 0.375rem;
}
.branch-option {
  display: flex;
  align-items: flex-start;
  gap: 0.5rem;
  padding: 0.4375rem 0.625rem;
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
  font-size: 0.8125rem;
  color: var(--text-primary);
  line-height: 1.5;
}
.opt-impact {
  font-size: 0.6875rem;
  color: var(--text-muted);
  line-height: 1.4;
}
.branch-readonly {
  font-size: 0.75rem;
  color: var(--text-secondary);
  margin: 0;
  line-height: 1.5;
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
  padding: 0.375rem 0.75rem;
  font-size: 0.75rem;
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
.sb-btn.warn {
  background: #d97706;
  color: white;
  border-color: #d97706;
}
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
