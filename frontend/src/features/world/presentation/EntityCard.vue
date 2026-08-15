<script setup lang="ts">
/**
 * 实体卡片（人物/势力/资产 固有属性，去表单化展示）。
 * 卡片式列表项：色点 + 名字（双击改名）+ 简介 + 类型徽章 + 删除（hover 浮现）。
 */
import { ref, nextTick } from 'vue'
import Icon from '../../../components/Icon.vue'
import type { WorldEntity } from '../engine/types'

const props = defineProps<{ entity: WorldEntity }>()
const emit = defineEmits<{ delete: []; 'update:name': [name: string]; click: [] }>()

const typeLabel: Record<string, string> = {
  character: '角色',
  faction: '势力',
  asset: '资产',
}
const typeColor: Record<string, string> = {
  character: '#f59e0b',
  faction: '#a855f7',
  asset: '#10b981',
}

// 双击改名
const editing = ref(false)
const draft = ref('')
const inputRef = ref<HTMLInputElement | null>(null)
function startEdit() {
  draft.value = props.entity.name
  editing.value = true
  nextTick(() => inputRef.value?.focus())
}
function save() {
  if (!editing.value) return
  editing.value = false
  const n = draft.value.trim()
  if (n && n !== props.entity.name) emit('update:name', n)
}
</script>

<template>
  <!-- 点卡片开详情抽屉；双击名字改名（重命名为名字元素自带） -->
  <div class="entity-card ec-clickable" title="点击查看档案与编年史" @click="emit('click')">
    <span
      class="ec-dot"
      :style="{ background: typeColor[entity.entity_type] || '#94a3b8' }"
    ></span>
    <div class="ec-body">
      <input
        v-if="editing"
        ref="inputRef"
        v-model="draft"
        class="ec-name-input"
        @keyup.enter="save"
        @keyup.esc="editing = false"
        @blur="save"
      />
      <div v-else class="ec-name" title="双击改名" @click.stop @dblclick="startEdit">{{ entity.name }}</div>
      <div v-if="entity.intro" class="ec-intro">{{ entity.intro }}</div>
    </div>
    <span class="ec-type">{{ typeLabel[entity.entity_type] || entity.entity_type }}</span>
    <button class="ec-del" title="删除" @click="emit('delete')">
      <Icon name="trash" :size="13" />
    </button>
  </div>
</template>

<style scoped>
.entity-card {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  background: var(--bg-canvas);
  border: 1px solid var(--border-color);
  border-radius: 10px;
  transition: all 0.15s ease-out;
}
.entity-card.ec-clickable {
  cursor: pointer;
}
.entity-card:hover {
  border-color: var(--accent-500);
  transform: translateY(-1px);
  box-shadow: 0 4px 14px rgba(120, 100, 70, 0.1);
}
.ec-dot {
  width: 8px;
  height: 8px;
  border-radius: 9999px;
  flex-shrink: 0;
  box-shadow: 0 0 0 3px rgba(0, 0, 0, 0.04);
}
.ec-body {
  flex: 1;
  min-width: 0;
}
.ec-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
  cursor: text;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.ec-name-input {
  width: 100%;
  padding: 1px 6px;
  border: 1px solid var(--accent-500);
  border-radius: 6px;
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
  background: var(--bg-canvas);
  font-family: inherit;
  outline: none;
}
.ec-intro {
  font-size: 12px;
  color: var(--text-secondary);
  margin-top: 1px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.ec-type {
  font-size: 10px;
  color: var(--text-muted);
  flex-shrink: 0;
  padding: 1px 7px;
  background: var(--bg-tertiary);
  border-radius: 9999px;
}
.ec-del {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  opacity: 0;
  transition: all 0.12s;
  flex-shrink: 0;
}
.entity-card:hover .ec-del {
  opacity: 1;
}
.ec-del:hover {
  background: rgba(220, 38, 38, 0.08);
  color: #dc2626;
}
</style>
