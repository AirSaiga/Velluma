<script setup lang="ts">
/**
 * BS-ADF 槽位卡只读折叠预览（V5 新建）。
 *
 * 职责：Track A 自动模式生成完成后，折叠展示本次生成使用的槽位卡
 * （只读），供作者回看本次的写作契约。
 *
 * 默认折叠，状态持久化在 localStorage 键 `velluma:bsadf:slotPreviewExpanded`。
 */
import { ref } from 'vue'
import type { BeatSlot } from '../../../services/api/domain'
import BeatSlotCardView from './BeatSlotCardView.vue'

const STORAGE_KEY = 'velluma:bsadf:slotPreviewExpanded'

const props = defineProps<{
  slots: BeatSlot[]
}>()

const expanded = ref<boolean>((() => {
  try {
    const v = localStorage.getItem(STORAGE_KEY)
    // 默认折叠（无存储值时为 false）
    return v === 'true'
  } catch {
    return false
  }
})())

function toggle() {
  expanded.value = !expanded.value
  try {
    localStorage.setItem(STORAGE_KEY, String(expanded.value))
  } catch {
    // 忽略 localStorage 异常
  }
}

const totalSegments = props.slots.length
const totalWords = props.slots.reduce((sum, s) => sum + (s.target_word_count || 0), 0)
</script>

<template>
  <section class="slot-preview">
    <header class="sp-header" @click="toggle">
      <div class="sp-title">
        <span class="sp-icon">📄</span>
        <span>槽位卡（{{ totalSegments }} 段 · 约 {{ totalWords }} 字）</span>
      </div>
      <span class="sp-toggle" :class="{ open: expanded }">{{ expanded ? '▾' : '▸' }}</span>
    </header>
    <p class="sp-hint">Track A 自动生成使用的写作契约。点开查看每段的锚点/感官/冲突设定。</p>

    <div v-if="expanded" class="sp-body">
      <BeatSlotCardView
        v-for="slot in slots"
        :key="slot.beat_id"
        :slot="slot"
        :readonly="true"
      />
    </div>
  </section>
</template>

<style scoped>
.slot-preview {
  padding: 0.625rem 0.75rem;
  background: var(--bg-canvas);
  border: 1px solid var(--border-color);
  border-radius: 0.5rem;
}
.sp-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  cursor: pointer;
  user-select: none;
}
.sp-title {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  font-size: 0.8125rem;
  font-weight: 500;
  color: var(--text-primary);
}
.sp-icon { font-size: 0.875rem; }
.sp-toggle {
  font-size: 0.6875rem;
  color: var(--text-muted);
  transition: transform 0.15s ease;
}
.sp-hint {
  font-size: 0.6875rem;
  color: var(--text-muted);
  margin: 0.375rem 0 0;
  line-height: 1.5;
}
.sp-body {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  margin-top: 0.625rem;
}
</style>
