<script setup lang="ts">
/**
 * BS-ADF 单张槽位卡视图（V5 新建）。
 *
 * 职责：展示一张槽位卡的全部字段，支持作者编辑。
 * - 列表字段（anchor_actions / sensory_details / ban_words）：chip 样式，可增删
 * - 字符串字段（text_carrier / conflict_trigger / psych_subtext）：可编辑文本
 * - 只读字段（beat_type / target_word_count / sentence_rhythm 等）：标签展示
 *
 * 编辑方式：父组件传入的 slot 已是深拷贝（由 BeatSlotPanel 管理），
 * 本组件直接修改该对象，并 emit('edit', slot, field) 通知父级标记 edited。
 *
 * 视觉语言照搬 RefineryIssuesPanel 的 issue-card 风格。
 */
import { computed, ref } from 'vue'
import type { BeatSlot } from '../../../services/api/domain'

type ListField = 'anchor_actions' | 'sensory_details' | 'ban_words'
type StringField = 'text_carrier' | 'conflict_trigger' | 'psych_subtext'

const props = defineProps<{
  slot: BeatSlot
  /** 只读模式（SlotPreview 复用本组件时禁用编辑） */
  readonly?: boolean
}>()

const emit = defineEmits<{
  (e: 'edit', slot: BeatSlot, field: string): void
}>()

const FIELD_META: Record<ListField, { label: string; placeholder: string; chipClass: string }> = {
  anchor_actions: { label: '锚点动作', placeholder: '加一个动作', chipClass: 'chip-action' },
  sensory_details: { label: '感官细节', placeholder: '加一个细节', chipClass: 'chip-sensory' },
  ban_words: { label: '禁用词', placeholder: '加一个禁词', chipClass: 'chip-ban' },
}

const STRING_META: Record<StringField, { label: string; placeholder: string }> = {
  text_carrier: { label: '文本载体', placeholder: '本段如何承载锚点动作' },
  conflict_trigger: { label: '冲突触发', placeholder: '本段的冲突点' },
  psych_subtext: { label: '心理潜台词', placeholder: '角色内在动机' },
}

const newListValue = ref<Record<ListField, string>>({
  anchor_actions: '',
  sensory_details: '',
  ban_words: '',
})
const expanded = ref(true)

function addChip(field: ListField) {
  const v = newListValue.value[field].trim()
  if (!v) return
  props.slot[field].push(v)
  newListValue.value[field] = ''
  markEdited(field)
}

function removeChip(field: ListField, idx: number) {
  props.slot[field].splice(idx, 1)
  markEdited(field)
}

function onStringEdit(field: StringField) {
  markEdited(field)
}

function markEdited(field: string) {
  props.slot.edited = true
  props.slot.edit_count += 1
  emit('edit', props.slot, field)
}

const listFields: ListField[] = ['anchor_actions', 'sensory_details', 'ban_words']
const stringFields: StringField[] = ['text_carrier', 'conflict_trigger', 'psych_subtext']

const editedTag = computed(() => props.slot.edited ? '已编辑' : '')
</script>

<template>
  <div class="slot-card" :class="{ edited: slot.edited, 'read-only': readonly }">
    <header class="card-head" @click="expanded = !expanded">
      <div class="head-left">
        <span class="seg-num">段 {{ slot.segment_index + 1 }}</span>
        <span class="beat-type">{{ slot.beat_type }}</span>
        <span class="edited-tag" v-if="editedTag">{{ editedTag }}</span>
      </div>
      <div class="head-right">
        <span class="target-wc">{{ slot.target_word_count }} 字</span>
        <span class="expand-icon">{{ expanded ? '▾' : '▸' }}</span>
      </div>
    </header>

    <div v-if="expanded" class="card-body">
      <!-- 字符串字段 -->
      <div v-for="f in stringFields" :key="f" class="field-row">
        <label class="field-label">{{ STRING_META[f].label }}</label>
        <textarea
          v-if="!readonly"
          class="field-textarea"
          :value="slot[f]"
          :placeholder="STRING_META[f].placeholder"
          rows="2"
          @input="(e) => { slot[f] = (e.target as HTMLTextAreaElement).value; onStringEdit(f) }"
        ></textarea>
        <p v-else class="field-text">{{ slot[f] || '（无）' }}</p>
      </div>

      <!-- 列表字段（chip） -->
      <div v-for="f in listFields" :key="f" class="field-row">
        <label class="field-label">{{ FIELD_META[f].label }}</label>
        <div class="chip-row">
          <span v-for="(c, idx) in slot[f]" :key="idx" class="chip" :class="FIELD_META[f].chipClass">
            {{ c }}
            <button
              v-if="!readonly"
              class="chip-remove"
              title="删除"
              @click.stop="removeChip(f, idx)"
            >×</button>
          </span>
          <div v-if="!readonly" class="chip-add">
            <input
              class="chip-input"
              :placeholder="FIELD_META[f].placeholder"
              :value="newListValue[f]"
              @input="(e) => newListValue[f] = (e.target as HTMLInputElement).value"
              @keydown.enter.prevent="addChip(f)"
            />
            <button class="chip-add-btn" @click.stop="addChip(f)" title="添加">+</button>
          </div>
          <span v-if="readonly && slot[f].length === 0" class="chip-empty">（无）</span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.slot-card {
  padding: 0.625rem 0.75rem;
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
  font-size: 0.6875rem;
  color: var(--text-muted);
  font-variant-numeric: tabular-nums;
}
.beat-type {
  font-size: 0.75rem;
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
  font-size: 0.6875rem;
  color: var(--text-muted);
}
.expand-icon {
  font-size: 0.6875rem;
  color: var(--text-muted);
}

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
  font-size: 0.6875rem;
  font-weight: 600;
  color: var(--text-muted);
  letter-spacing: 0.03em;
}
.field-textarea {
  width: 100%;
  font-size: 0.75rem;
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
.field-text {
  font-size: 0.75rem;
  line-height: 1.5;
  color: var(--text-secondary);
  margin: 0;
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
  font-size: 0.6875rem;
  padding: 0.125rem 0.375rem;
  border-radius: 0.25rem;
  background: var(--hover-bg);
  color: var(--text-secondary);
}
.chip-action { background: rgba(124, 106, 173, 0.1); color: var(--accent-500); }
.chip-sensory { background: rgba(13, 148, 136, 0.1); color: #0f766e; }
.chip-ban { background: rgba(220, 38, 38, 0.1); color: #b91c1c; }
.chip-remove {
  background: none;
  border: none;
  color: inherit;
  cursor: pointer;
  font-size: 0.75rem;
  line-height: 1;
  padding: 0;
  opacity: 0.6;
}
.chip-remove:hover { opacity: 1; }
.chip-empty { font-size: 0.6875rem; color: var(--text-muted); font-style: italic; }

.chip-add {
  display: inline-flex;
  align-items: center;
  gap: 0.1875rem;
}
.chip-input {
  width: 6rem;
  font-size: 0.6875rem;
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
  font-size: 0.75rem;
  line-height: 1;
  padding: 0;
}
.chip-add-btn:hover {
  border-color: var(--accent-500);
  color: var(--accent-500);
}
</style>
