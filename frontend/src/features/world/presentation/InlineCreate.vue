<script setup lang="ts">
/**
 * 内联快速创建（select 旁的 ＋ 按钮）——解决「录事件时发现没角色/地点，
 * 要关模态去侧栏建再回来重填」的流程断裂。
 *
 * 点 ＋ → 展开输入框 → Enter 提交 → created 回传（父组件把 select 值设为新项）。
 * 地点内联创建：坐标取地图中心附近随机落点（建后出现 marker，拖拽调整位置）。
 * Esc 收起；Enter 已 stop（不会触发外层表单提交）。
 */
import { ref, computed, nextTick } from 'vue'
import Icon from '../../../components/Icon.vue'
import { useWorld } from '../composables/useWorld'

const props = defineProps<{
  bookId: string
  kind: 'character' | 'faction' | 'asset' | 'location'
  title?: string
}>()
const emit = defineEmits<{ created: [item: { id: string; name: string }] }>()

const { createEntity, createLocation } = useWorld()

const open = ref(false)
const name = ref('')
const busy = ref(false)
const inputRef = ref<HTMLInputElement | null>(null)

const kindLabel = computed(() =>
  props.kind === 'location'
    ? '地点'
    : props.kind === 'faction'
      ? '势力'
      : props.kind === 'asset'
        ? '资产'
        : '角色',
)

function start() {
  name.value = ''
  open.value = true
  nextTick(() => inputRef.value?.focus())
}
function cancel() {
  open.value = false
}

async function submit() {
  const n = name.value.trim()
  if (!n || busy.value) return
  busy.value = true
  try {
    let item: { id: string; name: string }
    if (props.kind === 'location') {
      const loc = await createLocation(props.bookId, {
        name: n,
        coord_x: 420 + Math.random() * 160,
        coord_y: 420 + Math.random() * 160,
      })
      item = loc
    } else {
      const ent = await createEntity(props.bookId, { entity_type: props.kind, name: n })
      item = ent
    }
    emit('created', item)
    open.value = false
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <span class="ic">
    <button
      v-if="!open"
      class="ic-btn"
      :title="title || `快速新建${kindLabel}`"
      type="button"
      @click="start"
    >
      <Icon name="plus" :size="12" />
    </button>
    <span v-else class="ic-row">
      <input
        ref="inputRef"
        v-model="name"
        class="ic-input"
        :placeholder="`${kindLabel}名`"
        @keydown.enter.stop.prevent="submit"
        @keydown.esc.stop="cancel"
        @blur="() => { if (!name) cancel() }"
      />
      <button
        class="ic-btn ic-btn--go"
        type="button"
        :disabled="!name.trim() || busy"
        title="确认建立（Enter）"
        @click="submit"
      >
        <Icon name="check-circle" :size="13" />
      </button>
    </span>
  </span>
</template>

<style scoped>
.ic {
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
}
.ic-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  border: 1px dashed var(--accent-500);
  border-radius: 7px;
  background: rgba(124, 106, 173, 0.05);
  color: var(--accent-500);
  cursor: pointer;
  transition: all 0.13s;
}
.ic-btn:hover {
  background: rgba(124, 106, 173, 0.14);
}
.ic-btn:disabled {
  opacity: 0.4;
  cursor: default;
}
.ic-btn--go {
  border-style: solid;
  background: var(--accent-500);
  color: #fff;
}
.ic-row {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.ic-input {
  width: 120px;
  padding: 4px 8px;
  border: 1px solid var(--accent-500);
  border-radius: 7px;
  background: var(--bg-canvas);
  color: var(--text-primary);
  font-size: 12px;
  font-family: inherit;
  outline: none;
  box-shadow: 0 0 0 3px rgba(124, 106, 173, 0.12);
}
</style>
