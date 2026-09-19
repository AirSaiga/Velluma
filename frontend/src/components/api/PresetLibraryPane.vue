<script setup lang="ts">
/**
 * 预设库分区（ApiSettingsModal 2026-09 UX 重构子件）。
 *
 * 纯展示 + 抛事件，不直接调 API：应用/删除结果由父组件处理（刷新预设池、toast）。
 * 删除二次确认语义同旧版下拉旁删除钮：首点变红进入待确认态 3.5s，复点才真删，
 * armed 态按预设 id 在本组件内管理（旧版按槽位管理——预设库无槽位选择态，此处简化）。
 */
import { ref } from 'vue'
import Icon from '../Icon.vue'
import type { ModelPresetItem } from '../../services/api'
import type { ProfileRole } from './ModelSlotPane.vue'

const props = defineProps<{
  presets: ModelPresetItem[]
  /** 正在应用中的目标槽（任一槽在飞则全部操作钮禁用） */
  applying: ProfileRole | null
}>()

const emit = defineEmits<{
  apply: [id: string, role: ProfileRole]
  remove: [id: string]
}>()

const armedId = ref<string | null>(null)
let armTimer: ReturnType<typeof setTimeout> | undefined

function onDelete(id: string) {
  if (armedId.value !== id) {
    armedId.value = id
    clearTimeout(armTimer)
    armTimer = setTimeout(() => { armedId.value = null }, 3500)
    return
  }
  armedId.value = null
  clearTimeout(armTimer)
  emit('remove', id)
}
</script>

<template>
  <div class="preset-pane">
    <div class="pane-title">预设库</div>
    <div class="pane-hint">
      写作/分析两槽共用一个池；「应用」即整卡切换（含 Key），旧配置由服务端自动存档兜底，切换无损。
    </div>

    <div v-for="p in presets" :key="p.id" class="preset-card">
      <div class="preset-info">
        <div class="preset-name">
          <span class="preset-name-text">{{ p.name }}</span>
          <span v-if="p.source === 'auto'" class="preset-badge">自动存档</span>
        </div>
        <div class="preset-sub">{{ p.model || '未命名模型' }} · {{ p.base_url || '默认端点' }}</div>
      </div>
      <div class="preset-ops">
        <button
          type="button"
          class="op-btn"
          :disabled="applying !== null"
          @click="emit('apply', p.id, 'creative')"
        >
          <Icon v-if="applying === 'creative'" name="loader" :size="12" class="spin spin-reduced" />
          应用到写作
        </button>
        <button
          type="button"
          class="op-btn"
          :disabled="applying !== null"
          @click="emit('apply', p.id, 'reasoning')"
        >
          <Icon v-if="applying === 'reasoning'" name="loader" :size="12" class="spin spin-reduced" />
          应用到分析
        </button>
        <button
          type="button"
          class="op-btn op-del"
          :class="{ armed: armedId === p.id }"
          :disabled="applying !== null"
          @click="onDelete(p.id)"
        >{{ armedId === p.id ? '确认删除？' : '删除' }}</button>
      </div>
    </div>

    <div v-if="!presets.length" class="preset-empty">
      <Icon name="inbox" :size="22" class="preset-empty-icon" />
      <span>暂无已存配置——在写作/分析模型分区点「存为预设」即可收进这里。</span>
    </div>
  </div>
</template>

<style scoped>
.pane-title {
  font-size: var(--text-md);
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 4px;
}

.pane-hint {
  font-size: var(--text-xs);
  line-height: 1.5;
  color: var(--text-muted);
  margin-bottom: 12px;
}

.preset-card {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  margin-bottom: 8px;
  background: var(--bg-secondary);
  border: 1px solid var(--line-faint);
  border-radius: var(--radius-md);
}

.preset-info {
  flex: 1;
  min-width: 0;
}

.preset-name {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 2px;
}

.preset-name-text {
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.preset-badge {
  flex-shrink: 0;
  padding: 1px 6px;
  font-size: var(--text-xs);
  color: var(--text-muted);
  border: 1px solid var(--line);
  border-radius: var(--radius-pill);
}

.preset-sub {
  font-size: var(--text-xs);
  color: var(--text-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.preset-ops {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}

.op-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 5px 9px;
  font-size: var(--text-xs);
  white-space: nowrap;
  color: var(--accent-500);
  background: transparent;
  border: 1px solid var(--accent-500);
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: all var(--dur-2) var(--ease-out);
}

.op-btn:hover:not(:disabled) {
  background: var(--accent-500);
  color: var(--bg-canvas);
}

.op-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.op-del {
  color: var(--text-muted);
  border-color: var(--line);
}

.op-del:hover:not(:disabled) {
  background: transparent;
  color: var(--text-secondary);
  border-color: var(--text-muted);
}

.op-del.armed {
  color: var(--danger);
  border-color: var(--danger);
}

.op-del.armed:hover:not(:disabled) {
  background: var(--danger);
  border-color: var(--danger);
  color: var(--bg-canvas);
}

.preset-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 28px 12px;
  font-size: var(--text-xs);
  line-height: 1.6;
  color: var(--text-muted);
  text-align: center;
  border: 1px dashed var(--border-color);
  border-radius: var(--radius-md);
}

.preset-empty-icon {
  opacity: 0.6;
}

.spin {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from {
    transform: rotate(0deg);
  }

  to {
    transform: rotate(360deg);
  }
}
</style>
