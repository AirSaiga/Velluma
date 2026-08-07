<script setup lang="ts">
/**
 * BS-ADF 单张分镜卡视图（DDE-BS 重构后重写）。
 *
 * 职责：展示一张分镜卡的物理硬契约，支持作者编辑。瘦身到 3+1 个 UI 字段：
 * - 🎯 本段核心转折（core_plot_event，可编辑文本框）
 * - 📌 画面必现硬焦点（key_anchors，chip 增删）
 * - 💬 特定台词（text_carrier，单行文本框）
 * - 大纲节拍（outline_beat，只读折叠展示）
 *
 * 编辑方式：父组件传入的 slot 已是深拷贝（由 StoryboardPanel 管理），
 * 本组件直接修改该对象，并 emit('edit', slot, field) 通知父级标记 edited。
 *
 * 视觉语言沿用原版（chip / field-row 样式），工程字段名不出现在界面。
 */
import { computed, ref, watch } from 'vue'
import type { BeatSlot } from '../../../services/api/domain'
import Icon from '../../../components/Icon.vue'

const props = defineProps<{
  slot: BeatSlot
  /** 只读模式（StoryboardPanel 只读态复用本组件时禁用编辑） */
  readonly?: boolean
  /** 状态灯图标名（对应 Icon.vue 的 icons key） */
  statusIcon?: string
  statusIconSpin?: boolean
  statusLabel?: string
  statusClass?: string
}>()

const emit = defineEmits<{
  (e: 'edit', slot: BeatSlot, field: string): void
}>()

const newAnchor = ref('')
// 渐进式展开：编辑态默认展开（作者要改），只读态默认折叠（浏览密度优先）；
// 进入编辑态（Track B / 极速微调）时自动展开该卡
const expanded = ref(!props.readonly)
watch(() => props.readonly, (ro) => {
  if (!ro) expanded.value = true
})
// 大纲节拍是只读参考信息，默认折叠（二级展开）
const outlineOpen = ref(false)

const BEAT_TYPE_LABEL: Record<string, string> = {
  ESTABLISH: '建立',
  CONFRONT: '冲突',
  CLIMACTIC: '高潮',
  RESOLVE: '收束',
}
const beatTypeLabel = computed(() => BEAT_TYPE_LABEL[props.slot.beat_type] || props.slot.beat_type)

/** 折叠态一行摘要：核心转折 + 元信息（N 个必现画面 / 有台词） */
const collapsedMeta = computed(() => {
  const parts: string[] = []
  if (props.slot.key_anchors.length) parts.push(`${props.slot.key_anchors.length} 个必现画面`)
  if (props.slot.text_carrier) parts.push('有特定台词')
  return parts.join(' · ')
})

function addAnchor() {
  const v = newAnchor.value.trim()
  if (!v) return
  props.slot.key_anchors.push(v)
  newAnchor.value = ''
  markEdited('key_anchors')
}

function removeAnchor(idx: number) {
  props.slot.key_anchors.splice(idx, 1)
  markEdited('key_anchors')
}

function markEdited(field: string) {
  props.slot.edited = true
  props.slot.edit_count += 1
  emit('edit', props.slot, field)
}

const editedTag = computed(() => props.slot.edited ? '已编辑' : '')
</script>

<template>
  <div class="slot-card" :class="{ edited: slot.edited, 'read-only': readonly }">
    <header class="card-head" @click="expanded = !expanded">
      <div class="head-left">
        <span class="seg-num">第 {{ slot.segment_index + 1 }} 段</span>
        <span class="beat-type">{{ beatTypeLabel }}</span>
        <span class="edited-tag" v-if="editedTag">{{ editedTag }}</span>
      </div>
      <div class="head-right">
        <span v-if="statusLabel" class="status-light" :class="statusClass">
          <Icon v-if="statusIcon" :name="statusIcon" :size="14" :class="{ 'status-icon': true, spin: !!statusIconSpin }" />
          {{ statusLabel }}
        </span>
        <span class="target-wc">约 {{ slot.target_word_count }} 字</span>
        <span class="expand-icon">{{ expanded ? '▾' : '▸' }}</span>
      </div>
    </header>

    <!-- 折叠态：一行摘要（核心转折截断 + 元信息） -->
    <div v-if="!expanded" class="card-summary" @click="expanded = true">
      <p class="summary-text">{{ slot.core_plot_event || '（未填核心转折）' }}</p>
      <p v-if="collapsedMeta" class="summary-meta">{{ collapsedMeta }}</p>
    </div>

    <div v-if="expanded" class="card-body">
      <!-- 🎯 本段核心转折 -->
      <div class="field-row">
        <label class="field-label">🎯 本段核心转折</label>
        <textarea
          v-if="!readonly"
          class="field-textarea"
          :value="slot.core_plot_event"
          placeholder="这一段必须发生的剧情转折（如：林尘当众拒绝下跪）"
          rows="2"
          @input="(e) => { slot.core_plot_event = (e.target as HTMLTextAreaElement).value; markEdited('core_plot_event') }"
        ></textarea>
        <p v-else class="field-text">{{ slot.core_plot_event || '（无）' }}</p>
      </div>

      <!-- 📌 画面必现硬焦点 -->
      <div class="field-row">
        <label class="field-label">📌 画面必现硬焦点</label>
        <div class="chip-row">
          <span v-for="(c, idx) in slot.key_anchors" :key="idx" class="chip chip-anchor">
            {{ c }}
            <button
              v-if="!readonly"
              class="chip-remove"
              title="删除"
              @click.stop="removeAnchor(idx)"
            >×</button>
          </span>
          <div v-if="!readonly" class="chip-add">
            <input
              class="chip-input"
              placeholder="加一个必现画面"
              :value="newAnchor"
              @input="(e) => newAnchor = (e.target as HTMLInputElement).value"
              @keydown.enter.prevent="addAnchor"
            />
            <button class="chip-add-btn" @click.stop="addAnchor" title="添加">+</button>
          </div>
          <span v-if="readonly && slot.key_anchors.length === 0" class="chip-empty">（无）</span>
        </div>
      </div>

      <!-- 💬 特定台词 -->
      <div class="field-row">
        <label class="field-label">💬 特定台词</label>
        <input
          v-if="!readonly"
          class="field-input"
          :value="slot.text_carrier"
          placeholder="本段必须出现的一句台词（可留空）"
          @input="(e) => { slot.text_carrier = (e.target as HTMLInputElement).value; markEdited('text_carrier') }"
        />
        <p v-else class="field-text">{{ slot.text_carrier || '（无）' }}</p>
      </div>

      <!-- 大纲节拍（只读，二级折叠：默认收起，点击展开） -->
      <div v-if="slot.outline_beat" class="field-row outline-row">
        <button type="button" class="outline-toggle" @click.stop="outlineOpen = !outlineOpen">
          📖 大纲节拍 {{ outlineOpen ? '▾' : '▸' }}
        </button>
        <p v-if="outlineOpen" class="field-text outline-text">{{ slot.outline_beat }}</p>
      </div>
    </div>
  </div>
</template>

<style scoped>
.slot-card {
  padding: 0.75rem 0.875rem;
  border-radius: 0.5rem;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-left: 3px solid var(--text-muted);
  transition: border-color 0.15s ease;
}
.slot-card.edited { border-left-color: var(--accent-500); }
.slot-card.read-only { border-left-color: var(--text-muted); }
.slot-card:hover { border-color: rgba(124, 106, 173, 0.45); }

.card-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  cursor: pointer;
  user-select: none;
}
.head-left, .head-right {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}
.seg-num {
  font-size: 0.8125rem;
  color: var(--text-muted);
  font-variant-numeric: tabular-nums;
}
.beat-type {
  font-size: 0.8125rem;
  font-weight: 500;
  color: var(--text-primary);
}
.edited-tag {
  font-size: 0.625rem;
  padding: 0.0625rem 0.375rem;
  border-radius: 0.25rem;
  background: rgba(124, 106, 173, 0.12);
  color: var(--accent-500);
}
.target-wc {
  font-size: 0.8125rem;
  color: var(--text-muted);
}
.expand-icon {
  font-size: 0.8125rem;
  color: var(--text-muted);
}
.status-light {
  font-size: 0.8125rem;
  font-weight: 500;
}
.status-light.st-ready { color: var(--text-muted); }
.status-light.st-queued { color: var(--text-muted); }
.status-light.st-skipped { color: #6b7280; }
.status-light.st-rendering { color: var(--accent-500); }
.status-light.st-branch_choosing { color: var(--accent-500); }
.status-light.st-rendered { color: #16a34a; }
.status-light.st-rescue,
.status-light.st-degraded { color: #d97706; }
.status-light .status-icon {
  display: inline-block;
  vertical-align: -0.125em;
  margin-right: 0.25rem;
}
.status-light .status-icon.spin {
  animation: card-spin 1s linear infinite;
}
@keyframes card-spin {
  to { transform: rotate(360deg); }
}

.card-summary {
  margin-top: 0.375rem;
  cursor: pointer;
}
.summary-text {
  font-size: 0.8125rem;
  line-height: 1.5;
  color: var(--text-secondary);
  margin: 0;
  overflow: hidden;
  display: -webkit-box;
  -webkit-line-clamp: 1;
  -webkit-box-orient: vertical;
}
.summary-meta {
  font-size: 0.8125rem;
  color: var(--text-muted);
  margin: 0.125rem 0 0;
}

.outline-toggle {
  align-self: flex-start;
  background: none;
  border: none;
  padding: 0;
  font-size: 0.8125rem;
  font-weight: 600;
  color: var(--text-muted);
  letter-spacing: 0.03em;
  cursor: pointer;
}
.outline-toggle:hover { color: var(--accent-500); }

.card-body {
  margin-top: 0.5rem;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.field-row {
  display: flex;
  flex-direction: column;
  gap: 0.1875rem;
}
.field-label {
  font-size: 0.8125rem;
  font-weight: 600;
  color: var(--text-muted);
  letter-spacing: 0.03em;
}
.field-textarea {
  width: 100%;
  font-size: 0.8125rem;
  line-height: 1.5;
  padding: 0.375rem;
  border: 1px solid var(--border-color);
  border-radius: 0.25rem;
  background: var(--bg-primary);
  color: var(--text-primary);
  font-family: inherit;
  resize: vertical;
}
.field-textarea:focus {
  outline: none;
  border-color: var(--accent-500);
  box-shadow: 0 0 0 3px rgba(124, 106, 173, 0.12);
}
.field-input {
  width: 100%;
  font-size: 0.8125rem;
  line-height: 1.5;
  padding: 0.375rem;
  border: 1px solid var(--border-color);
  border-radius: 0.25rem;
  background: var(--bg-primary);
  color: var(--text-primary);
  font-family: inherit;
}
.field-input:focus {
  outline: none;
  border-color: var(--accent-500);
  box-shadow: 0 0 0 3px rgba(124, 106, 173, 0.12);
}
.field-text {
  font-size: 0.8125rem;
  line-height: 1.5;
  color: var(--text-secondary);
  margin: 0;
}
.outline-row {
  padding-top: 0.25rem;
  border-top: 1px dashed var(--border-color);
}
.outline-text {
  font-style: italic;
}

.chip-row {
  display: flex;
  flex-wrap: wrap;
  gap: 0.25rem;
  align-items: center;
}
.chip {
  display: inline-flex;
  align-items: center;
  gap: 0.1875rem;
  font-size: 0.8125rem;
  padding: 0.125rem 0.375rem;
  border-radius: 0.25rem;
  background: var(--hover-bg);
  color: var(--text-secondary);
}
.chip-anchor { background: rgba(124, 106, 173, 0.1); color: var(--accent-500); }
.chip-remove {
  background: none;
  border: none;
  color: inherit;
  cursor: pointer;
  font-size: 0.8125rem;
  line-height: 1;
  padding: 0;
  opacity: 0.6;
}
.chip-remove:hover { opacity: 1; }
.chip-empty { font-size: 0.8125rem; color: var(--text-muted); font-style: italic; }

.chip-add {
  display: inline-flex;
  align-items: center;
  gap: 0.1875rem;
}
.chip-input {
  width: 6rem;
  font-size: 0.8125rem;
  padding: 0.125rem 0.375rem;
  border: 1px dashed var(--border-color);
  border-radius: 0.25rem;
  background: transparent;
  color: var(--text-primary);
  font-family: inherit;
}
.chip-input::placeholder { color: var(--text-muted); }
.chip-input:focus {
  outline: none;
  border-style: solid;
  border-color: var(--accent-500);
}
.chip-add-btn {
  width: 1.125rem;
  height: 1.125rem;
  border: 1px solid var(--border-color);
  border-radius: 0.25rem;
  background: var(--bg-canvas);
  color: var(--text-secondary);
  cursor: pointer;
  font-size: 0.8125rem;
  line-height: 1;
  padding: 0;
}
.chip-add-btn:hover {
  border-color: var(--accent-500);
  color: var(--accent-500);
}
</style>
