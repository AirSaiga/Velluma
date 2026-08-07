<script setup lang="ts">
/**
 * 步进岔路门「顶部决策区」（节拍 tab UX 重设计新增）。
 *
 * 职责：当步进渲染挂起等作者决策（stage === 'beat_branch_choosing'）时，
 * 在节拍面板顶部独占焦点位，直接呈现决策交互——不再跳转分镜卡：
 * - DDE 走向岔路（node.source !== 'loop1_gap'）：radio 走向选项（默认走向预选并标注）
 *   +「我自己说一个走向」自由文本（复用 custom: 通道），主按钮确认后才开始渲染。
 * - Loop1 大纲缺口（node.source === 'loop1_gap'）：补充说明输入框，
 *   「提交补充并渲染本段」/「不补充，按原大纲渲染」两个出口。
 *
 * 历史背景：此前决策分散在四层（焦点条横幅指路 + 顶部通知 + 卡预告条 + 卡内选择块），
 * 一屏内同一信息重复 2~3 次且按钮行拥挤折行。本组件是唯一决策入口；
 * 接管态下分镜区塌缩为一行状态轨，卡的上下文（核心转折 + 必现画面）内嵌于标题区。
 *
 * 提交契约：emit('submit', choice) 直送 session.submitBranchChoice——
 *   optionId（DDE 选项）/ 'custom:'+文本（缺口补充或自定义走向）/ null（跳过=pass）。
 * Space 快捷键语义由 session._spaceKeyHandler 持有：DDE = 按默认走向渲染，
 * 缺口 = 跳过补充（均等价 submit(null)），本组件只展示提示。
 *
 * 纯 presentation 组件：不 import services，数据走 props，动作走 emits。
 */
import { computed, ref, watch } from 'vue'
import type { BeatSlot } from '../../../services/api/domain'
import Icon from '../../../components/Icon.vue'

interface DecisionNode {
  beat_id: string
  node_title: string
  options: { option_id: string; label: string; plot_impact: string }[]
  default_option: string
  /** dde=LLM 判出的真实岔路（缺省）；loop1_gap=大纲自检缺口提示（补充输入而非选择题） */
  source?: 'dde' | 'loop1_gap'
}

const props = defineProps<{
  /** 待决策岔路（session.branchChoicePending 原样传入） */
  pending: {
    beat_id: string
    segment_index: number
    node: DecisionNode
    card: BeatSlot | null
  }
  /** 全章总段数（标题「第 N/M 段」用） */
  segTotal?: number
}>()

const emit = defineEmits<{
  /** 提交决策：optionId / 'custom:'+文本 / null（跳过）。提交后 session 立即切态，本组件卸载 */
  (e: 'submit', choice: string | null): void
  /** 取消本次生成（岔路门挂起期间的逃生口；父级调 session.cancel） */
  (e: 'cancel'): void
}>()

// ---- 本地选择状态（换段时整体重置，防上一段的输入串到下一段） ----
const selectedOption = ref('')
const customText = ref('')
const gapText = ref('')

watch(
  () => props.pending.beat_id,
  () => {
    selectedOption.value = props.pending.node.default_option || props.pending.node.options[0]?.option_id || ''
    customText.value = ''
    gapText.value = ''
  },
  { immediate: true },
)

const isGap = computed(() => props.pending.node.source === 'loop1_gap')
/** 缺口提示语（单 option 的 label，如"建议补充：主角为何采取此行动"）作输入占位 */
const gapPlaceholder = computed(() => props.pending.node.options[0]?.label || '补充说明（可选）')

/** DDE 主按钮：自定义文本非空时改走 custom: 通道，文案同步切换（一个出口，不并列两个按钮） */
const primaryLabel = computed(() =>
  isGap.value
    ? '提交补充并渲染本段'
    : customText.value.trim()
      ? '用我写的走向渲染'
      : '确认走向，开始渲染本段',
)
const primaryDisabled = computed(() => isGap.value && !gapText.value.trim())

function onPrimary() {
  if (primaryDisabled.value) return
  if (isGap.value) {
    emit('submit', `custom:${gapText.value.trim()}`)
    return
  }
  const custom = customText.value.trim()
  emit('submit', custom ? `custom:${custom}` : selectedOption.value)
}

function onSkipGap() {
  emit('submit', null)
}
</script>

<template>
  <div class="decision" :class="{ 'is-gap': isGap }">
    <!-- 标题区：固定短标题（第 N/M 段 · 缺口/走向）+ 节点标题正文行 + 本段上下文。
         节点标题不进加粗标题行——loop1 缺口标题常含大段大纲引文，会把标题行
         撑到 5 行并从词中断开（真实显示事故）。接管态下分镜卡列表隐藏，
         卡的「必现画面」以 chips 内嵌于此，取代原「查看分镜卡」指路链接。 -->
    <div class="d-head">
      <Icon :name="isGap ? 'pencil-square' : 'bolt'" :size="18" class="d-icon" />
      <div class="d-titles">
        <div class="d-title">
          第 {{ pending.segment_index + 1 }}{{ segTotal ? '/' + segTotal : '' }} 段 · {{ isGap ? '大纲缺口' : '剧情走向' }}
        </div>
        <div class="d-node" :title="pending.node.node_title">{{ pending.node.node_title }}</div>
        <div v-if="pending.card?.core_plot_event" class="d-sub">
          这段原本写「{{ pending.card.core_plot_event }}」
        </div>
        <div v-if="pending.card?.key_anchors?.length" class="d-anchors">
          <span class="d-anchors-label">必现画面</span>
          <span
            v-for="(anchor, i) in pending.card.key_anchors.slice(0, 8)"
            :key="i"
            class="d-anchor"
            :title="anchor"
          >{{ anchor }}</span>
          <span v-if="pending.card.key_anchors.length > 8" class="d-anchor-more">
            +{{ pending.card.key_anchors.length - 8 }}
          </span>
        </div>
      </div>
    </div>

    <!-- DDE 走向选项（缺口节点无选项，只有补充输入） -->
    <div v-if="!isGap" class="d-options">
      <label
        v-for="opt in pending.node.options"
        :key="opt.option_id"
        class="d-option"
        :class="{ selected: selectedOption === opt.option_id }"
      >
        <input
          v-model="selectedOption"
          type="radio"
          name="branch-decision"
          :value="opt.option_id"
        />
        <span class="opt-body">
          <span class="opt-label">
            {{ opt.label }}
            <span v-if="opt.option_id === pending.node.default_option" class="opt-default">默认</span>
          </span>
          <span v-if="opt.plot_impact" class="opt-impact">{{ opt.plot_impact }}</span>
        </span>
      </label>
    </div>

    <!-- 输入区：缺口 = 补充说明（主输入）；DDE = 自定义走向（可选兜底）。
         缺口提示语完整显示为独立提示行——放 placeholder 会在两行输入框里
         被截成半句（真实显示事故："如白霆在"半截）。 -->
    <template v-if="isGap">
      <div v-if="gapPlaceholder" class="d-hint">{{ gapPlaceholder }}</div>
      <textarea
        v-model="gapText"
        class="d-input"
        rows="2"
        placeholder="用一两句话补充，AI 会按它渲染本段"
      ></textarea>
    </template>
    <textarea
      v-else
      v-model="customText"
      class="d-input"
      rows="2"
      placeholder="以上都不是，我自己说一个走向（可选）"
    ></textarea>

    <!-- 动作列：纵向堆叠全宽按钮（原横向 flex 在窄栏必折行） -->
    <div class="d-actions">
      <button class="d-btn primary" :disabled="primaryDisabled" @click="onPrimary">
        {{ primaryLabel }}
      </button>
      <button v-if="isGap" class="d-btn ghost" @click="onSkipGap">
        不补充，按原大纲渲染
      </button>
    </div>

    <!-- Space 快捷键提示（语义由 session._spaceKeyHandler 持有，此处只展示） -->
    <div class="d-kbd-row">
      <kbd class="d-kbd">Space</kbd>
      <span class="d-kbd-desc">{{ isGap ? '跳过补充，按原大纲渲染' : '按默认走向渲染' }}</span>
      <span class="d-kbd-spacer" />
      <button class="d-cancel" @click="emit('cancel')">✕ 取消生成</button>
    </div>
  </div>
</template>

<style scoped>
.decision {
  display: flex;
  flex-direction: column;
  gap: 0.625rem;
  margin: 0.75rem 0.875rem 0;
  padding: 0.75rem 0.875rem;
  background: var(--bg-canvas);
  border: 1px solid var(--accent-500);
  border-left-width: 3px;
  border-radius: 0.5rem;
  box-shadow: 0 0.25rem 0.875rem rgba(124, 106, 173, 0.08);
}
.decision.is-gap {
  border-color: #2563eb;
  box-shadow: 0 0.25rem 0.875rem rgba(37, 99, 235, 0.08);
}

/* 标题区 */
.d-head {
  display: flex;
  align-items: flex-start;
  gap: 0.5rem;
}
.d-icon {
  flex: 0 0 auto;
  margin-top: 0.125rem;
  color: var(--accent-500);
}
.is-gap .d-icon { color: #2563eb; }
.d-titles {
  flex: 1;
  min-width: 0;
}
.d-title {
  font-size: 0.9375rem;
  font-weight: 600;
  color: var(--text-primary);
  line-height: 1.5;
}
.d-node {
  margin-top: 0.125rem;
  font-size: 0.875rem;
  color: var(--text-secondary);
  line-height: 1.6;
  overflow: hidden;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
}
.d-sub {
  margin-top: 0.125rem;
  font-size: 0.8125rem;
  color: var(--text-muted);
  line-height: 1.5;
  overflow: hidden;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}
/* 必现画面 chips：接管态下列表隐藏，卡的硬焦点内嵌于此供决策参考 */
.d-anchors {
  margin-top: 0.375rem;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.25rem;
}
.d-anchors-label {
  font-size: 0.6875rem;
  color: var(--text-muted);
  margin-right: 0.125rem;
  white-space: nowrap;
}
.d-anchor {
  padding: 0.0625rem 0.4375rem;
  font-size: 0.6875rem;
  color: var(--text-secondary);
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 9999px;
  white-space: nowrap;
  max-width: 10rem;
  overflow: hidden;
  text-overflow: ellipsis;
}
.d-anchor-more {
  font-size: 0.6875rem;
  color: var(--text-muted);
}

/* 走向选项 */
.d-options {
  display: flex;
  flex-direction: column;
  gap: 0.375rem;
}
.d-option {
  display: flex;
  align-items: flex-start;
  gap: 0.5rem;
  padding: 0.5rem 0.625rem;
  border-radius: 0.375rem;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  cursor: pointer;
  transition: all 0.15s;
}
.d-option:hover { background: var(--hover-bg); }
.d-option.selected {
  border-color: var(--accent-500);
  background: rgba(124, 106, 173, 0.08);
}
.d-option input[type="radio"] {
  margin: 0.125rem 0 0;
  cursor: pointer;
  accent-color: var(--accent-500);
}
.opt-body {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 0.125rem;
}
.opt-label {
  font-size: 0.875rem;
  color: var(--text-primary);
  line-height: 1.5;
}
.opt-default {
  margin-left: 0.375rem;
  padding: 0 0.375rem;
  font-size: 0.75rem;
  color: var(--accent-600);
  background: rgba(124, 106, 173, 0.12);
  border-radius: 9999px;
}
.opt-impact {
  font-size: 0.8125rem;
  color: var(--text-muted);
  line-height: 1.4;
}

/* 输入框 */
.d-hint {
  font-size: 0.8125rem;
  color: var(--text-muted);
  line-height: 1.5;
}
.d-input {
  width: 100%;
  padding: 0.4375rem 0.625rem;
  border-radius: 0.375rem;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  font-size: 0.875rem;
  color: var(--text-primary);
  line-height: 1.5;
  resize: vertical;
  font-family: inherit;
}
.d-input:focus {
  outline: none;
  border-color: var(--accent-500);
}
.d-input::placeholder {
  color: var(--text-muted);
}

/* 动作列：纵向全宽，窄栏不折行 */
.d-actions {
  display: flex;
  flex-direction: column;
  gap: 0.375rem;
}
.d-btn {
  width: 100%;
  padding: 0.5rem 0.875rem;
  font-size: 0.875rem;
  font-weight: 500;
  border: 1px solid transparent;
  border-radius: 0.375rem;
  cursor: pointer;
  transition: all 0.15s;
}
.d-btn.primary {
  background: var(--accent-500);
  color: #fff;
}
.d-btn.primary:hover:not(:disabled) { background: var(--accent-600); }
.d-btn.primary:disabled { opacity: 0.5; cursor: not-allowed; }
.d-btn.ghost {
  background: transparent;
  color: var(--text-secondary);
  border-color: var(--border-color);
}
.d-btn.ghost:hover:not(:disabled) {
  background: var(--hover-bg);
  color: var(--text-primary);
}

/* Space 提示 */
.d-kbd-row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}
.d-kbd {
  padding: 0.125rem 0.5rem;
  font-size: 0.75rem;
  font-weight: 600;
  font-family: inherit;
  color: var(--text-secondary);
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 0.25rem;
  box-shadow: 0 1px 0 rgba(0, 0, 0, 0.06);
}
.d-kbd-desc {
  font-size: 0.8125rem;
  color: var(--text-muted);
}
.d-kbd-spacer {
  flex: 1;
}
.d-cancel {
  font-size: 0.8125rem;
  color: var(--text-muted);
  padding: 0.125rem 0.375rem;
  border-radius: 0.25rem;
}
.d-cancel:hover {
  color: var(--danger-500, #c4533c);
  background: var(--danger-50, #fdf0ec);
}
</style>
