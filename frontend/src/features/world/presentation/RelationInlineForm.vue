<script setup lang="ts">
/**
 * 关系边内联表单（脑图透镜拖线/点边后浮现于连线中点，非模态弹窗）。
 *
 * 新建：source/target 固定（拖线结果），只填类型/标签/态度/时间性；
 * 编辑：可改全部字段 + 删除。
 * 时间性二分（设计 §2.2）：一直成立（static）或锚定某事件（static=false + event_ref，
 * 锚事件回放前边不生效——"关系随事态演变"）。
 */
import { ref, computed, onMounted, onUnmounted } from 'vue'
import Icon from '../../../components/Icon.vue'
import { useWorld } from '../composables/useWorld'
import { useConfirmDialog } from '../../../composables/useConfirmDialog'
import { useEscStack } from '../../../composables/useEscStack'
import { RELATION_TYPES } from '../engine/relationTypes'
import { formatTime } from '../engine/timeFormat'
import { eventDisplayName } from '../engine/eventTemplates'
import type { WorldRelation } from '../engine/types'

const props = defineProps<{
  bookId: string
  sourceId: string
  targetId: string
  existing?: WorldRelation | null
}>()

const emit = defineEmits<{ saved: []; cancel: [] }>()

// Esc 分层关闭栈（00 期 §4.2）：挂载即入栈，卸载即出栈（焦点不在表单内也生效）
const escStack = useEscStack()
let escId: symbol | null = null
onMounted(() => { escId = escStack.push(() => emit('cancel'), 'relation-inline-form') })
onUnmounted(() => { if (escId) escStack.remove(escId) })

const { entities, events, createRelation, updateRelation, deleteRelation } = useWorld()
const { show: showConfirm } = useConfirmDialog()

const entName = (id: string) => entities.value.find((e) => e.id === id)?.name || '？'

const ex = props.existing
const relationType = ref(ex?.relation_type || 'ally')
const label = ref(ex?.label || '')
const affinity = ref<number>(ex?.affinity ?? 0)
const hasAffinity = ref(ex?.affinity != null)
const isStatic = ref(ex?.static ?? true)
const eventRef = ref<string | null>(ex?.event_ref || null)

/** 可锚定的事件类型（影响关系走向的叙事事件） */
const ANCHORABLE = ['alliance', 'war_declare', 'battle', 'custom', 'coronation']
const anchorCandidates = computed(() =>
  events.value
    .filter((e) => ANCHORABLE.includes(e.event_type))
    .sort((a, b) => a.time_start - b.time_start)
    .map((e) => ({
      id: e.id,
      desc: `${eventDisplayName(e)} · ${formatTime(e.time_start)}`,
    })),
)

const invalid = computed(() => !isStatic.value && !eventRef.value)

async function submit() {
  if (invalid.value) return
  const data = {
    relation_type: relationType.value,
    label: label.value.trim(),
    affinity: hasAffinity.value ? affinity.value : null,
    static: isStatic.value,
    event_ref: isStatic.value ? null : eventRef.value,
  }
  if (ex) await updateRelation(ex.book_id, ex.id, data)
  else
    await createRelation(props.bookId, {
      source_entity_id: props.sourceId,
      target_entity_id: props.targetId,
      ...data,
    })
  emit('saved')
}

async function remove() {
  if (!ex) return
  const ok = await showConfirm({
    title: '删除关系',
    message: `确定删除「${entName(props.sourceId)} → ${entName(props.targetId)}」的关系吗？`,
    confirmText: '删除',
  })
  if (!ok) return
  await deleteRelation(ex.book_id, ex.id)
  emit('saved')
}
</script>

<template>
  <div class="rif" @keydown.enter.prevent="submit">
    <div class="rif-head">
      <Icon name="link" :size="13" />
      <span class="rif-title">{{ entName(sourceId) }} → {{ entName(targetId) }}</span>
      <button class="rif-x" title="关闭 (Esc)" @click="emit('cancel')">
        <Icon name="x-mark" :size="13" />
      </button>
    </div>

    <div class="rif-row">
      <label class="rif-label">类型</label>
      <div class="rif-types">
        <button
          v-for="t in RELATION_TYPES"
          :key="t.value"
          class="rif-type"
          :class="{ active: relationType === t.value }"
          :style="relationType === t.value ? { borderColor: t.color, color: t.color } : {}"
          @click="relationType = t.value"
        >
          {{ t.label }}
        </button>
      </div>
    </div>

    <div class="rif-row">
      <label class="rif-label">标签</label>
      <input v-model="label" class="rif-input" placeholder="如：义兄弟 / 杀父仇人（可选）" />
    </div>

    <div class="rif-row">
      <label class="rif-label">态度</label>
      <label class="rif-check">
        <input v-model="hasAffinity" type="checkbox" />
        记录态度值
      </label>
      <input
        v-if="hasAffinity"
        v-model.number="affinity"
        type="range"
        min="-100"
        max="100"
        class="rif-range"
      />
      <span v-if="hasAffinity" class="rif-aff">{{ affinity > 0 ? '+' : '' }}{{ affinity }}</span>
    </div>

    <div class="rif-row">
      <label class="rif-label">时间性</label>
      <div class="rif-seg">
        <button class="rif-seg-btn" :class="{ active: isStatic }" @click="isStatic = true">一直成立</button>
        <button class="rif-seg-btn" :class="{ active: !isStatic }" @click="isStatic = false">
          从某事件起
        </button>
      </div>
    </div>

    <div v-if="!isStatic" class="rif-row">
      <label class="rif-label">锚事件</label>
      <select v-model="eventRef" class="rif-input">
        <option :value="null" disabled>选择锚事件…</option>
        <option v-for="c in anchorCandidates" :key="c.id" :value="c.id">{{ c.desc }}</option>
      </select>
    </div>
    <div v-if="invalid" class="rif-warn">事件锚定关系必须选择锚事件</div>

    <div class="rif-foot">
      <button v-if="existing" class="rif-btn rif-btn--danger" @click="remove">
        <Icon name="trash" :size="13" />
        删除
      </button>
      <span class="rif-spacer"></span>
      <button class="rif-btn" @click="emit('cancel')">取消</button>
      <button class="rif-btn rif-btn--primary btn-primary-instrument" :disabled="invalid" @click="submit">
        {{ existing ? '保存' : '建立' }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.rif {
  width: 300px;
  background: var(--bg-canvas);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-lg);
  padding: 12px;
  font-size: var(--text-sm);
  z-index: 30;
}
.rif-head {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 10px;
  color: var(--accent-500);
}
.rif-title {
  flex: 1;
  font-weight: 600;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.rif-x {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
}
.rif-x:hover {
  background: var(--state-hover);
  color: var(--text-primary);
}
.rif-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
}
.rif-label {
  flex-shrink: 0;
  width: 44px;
  font-size: var(--text-xs);
  color: var(--text-secondary);
}
.rif-types {
  flex: 1;
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}
.rif-type {
  padding: 3px 8px;
  border: 1px solid var(--border-color);
  border-radius: 9999px;
  background: var(--bg-canvas);
  color: var(--text-secondary);
  font-size: var(--text-xs);
  font-family: inherit;
  cursor: pointer;
  transition: all var(--dur-1) var(--ease-out);
}
.rif-type:hover {
  border-color: var(--accent-500);
}
.rif-type.active {
  font-weight: 600;
  background: var(--bg-tertiary);
}
.rif-input {
  flex: 1;
  min-width: 0;
  padding: 6px 8px;
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  background: var(--bg-canvas);
  color: var(--text-primary);
  font-size: var(--text-sm);
  font-family: inherit;
  outline: none;
}
.rif-input:focus {
  border-color: var(--accent-500);
}
.rif-check {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: var(--text-xs);
  color: var(--text-secondary);
  cursor: pointer;
  white-space: nowrap;
}
.rif-range {
  flex: 1;
  accent-color: var(--accent-500);
}
.rif-aff {
  font-size: var(--text-xs);
  color: var(--text-secondary);
  font-family: ui-monospace, monospace;
  min-width: 36px;
  text-align: right;
}
.rif-seg {
  flex: 1;
  display: flex;
  gap: 6px;
}
.rif-seg-btn {
  flex: 1;
  padding: 5px 0;
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  background: var(--bg-canvas);
  color: var(--text-secondary);
  font-size: var(--text-xs);
  font-family: inherit;
  cursor: pointer;
  transition: all var(--dur-1) var(--ease-out);
}
.rif-seg-btn.active {
  border-color: var(--accent-500);
  color: var(--accent-500);
  background: color-mix(in srgb, var(--accent-500) 8%, transparent);
  font-weight: 600;
}
.rif-warn {
  margin: -2px 0 8px;
  font-size: var(--text-xs);
  color: var(--danger);
}
.rif-foot {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 4px;
}
.rif-spacer {
  flex: 1;
}
.rif-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 5px 12px;
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  background: var(--bg-canvas);
  color: var(--text-secondary);
  font-size: var(--text-xs);
  font-family: inherit;
  cursor: pointer;
  transition: all var(--dur-1) var(--ease-out);
}
.rif-btn:hover:not(:disabled) {
  border-color: var(--accent-500);
  color: var(--accent-500);
}
.rif-btn:disabled {
  opacity: 0.45;
  cursor: default;
}
.rif-btn--primary {
}
.rif-btn--primary:hover:not(:disabled) {
  background: var(--accent-600);
  color: var(--bg-canvas);
}
.rif-btn--danger:hover {
  border-color: var(--danger);
  color: var(--danger);
}
</style>
