<script setup lang="ts">
/**
 * BS-ADF Track B 槽位卡编辑面板（V5 新建）。
 *
 * 职责：Track B 暂停态下（stage='beat_pending'）的作者介入点。
 * - 展示本次生成的全部槽位卡（深拷贝，作者编辑不直接污染 session）
 * - 作者逐张编辑字段（由 BeatSlotCardView 处理）
 * - 底部 CTA：确认 → 渲染 / 取消 → 回滚 idle
 *
 * 照搬 RefineryIssuesPanel 的结构（header + 列表 + footer CTA）。
 */
import { ref, computed } from 'vue'
import type { BeatSlot } from '../../../services/api/domain'
import BeatSlotCardView from './BeatSlotCardView.vue'

const props = defineProps<{
  slots: BeatSlot[]
  runId: string
}>()

const emit = defineEmits<{
  (e: 'confirm', payload: { run_id: string; edited_slots: BeatSlot[] }): void
  (e: 'cancel'): void
}>()

// 深拷贝槽位卡：作者编辑不直接污染 session.beatSlots（confirm 前可放弃）
// structuredClone 处理嵌套数组；回退到 JSON 方案以兼容旧浏览器
function deepClone(slots: BeatSlot[]): BeatSlot[] {
  try {
    return structuredClone(slots)
  } catch {
    return JSON.parse(JSON.stringify(slots))
  }
}
const editedSlots = ref<BeatSlot[]>(deepClone(props.slots))

const editedCount = computed(() => editedSlots.value.filter(s => s.edited).length)
const totalWords = computed(() =>
  editedSlots.value.reduce((sum, s) => sum + (s.target_word_count || 0), 0),
)

function onSlotEdit(_slot: BeatSlot, _field: string) {
  // 编辑标记由 BeatSlotCardView 在 slot 对象上就地维护，此处无需额外操作
}

function handleConfirm() {
  emit('confirm', {
    run_id: props.runId,
    edited_slots: editedSlots.value,
  })
}
</script>

<template>
  <div class="beat-slot-panel">
    <header class="header">
      <h3>槽位卡（Track B 介入）</h3>
      <p class="stats">
        共 {{ editedSlots.length }} 段 · 约 {{ totalWords }} 字 · 已编辑 {{ editedCount }} 段
      </p>
    </header>

    <p class="intro">
      系统已为每段生成写作契约（锚点动作 / 感官细节 / 文本载体 / 冲突触发 / 心理潜台词 / 禁用词）。
      你可以直接修改，确认后按段顺序渲染。不改也可以直接确认。
    </p>

    <div class="slot-list">
      <BeatSlotCardView
        v-for="slot in editedSlots"
        :key="slot.beat_id"
        :slot="slot"
        @edit="onSlotEdit"
      />
    </div>

    <footer class="footer">
      <button class="btn-secondary" @click="emit('cancel')">取消（回滚）</button>
      <button class="btn-primary" @click="handleConfirm">
        确认并渲染（{{ editedSlots.length }} 段<span v-if="editedCount"> · {{ editedCount }} 处修改</span>）
      </button>
    </footer>
  </div>
</template>

<style scoped>
.beat-slot-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--bg-primary);
  padding: 1rem;
  overflow: hidden;
}
.header {
  margin-bottom: 0.5rem;
}
.header h3 {
  font-size: 1rem;
  margin: 0 0 0.25rem;
}
.stats {
  font-size: 0.75rem;
  color: var(--text-muted);
  margin: 0;
}
.intro {
  font-size: 0.75rem;
  color: var(--text-secondary);
  line-height: 1.6;
  margin: 0 0 0.75rem;
  padding: 0.5rem 0.625rem;
  background: var(--bg-secondary);
  border-radius: 0.375rem;
  border-left: 3px solid var(--accent-500);
}

.slot-list {
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 0.625rem;
  padding-right: 0.25rem;
}

.footer {
  display: flex;
  justify-content: flex-end;
  gap: 0.5rem;
  padding-top: 0.75rem;
  border-top: 1px solid var(--border-color);
  margin-top: 0.75rem;
}
.btn-primary, .btn-secondary {
  padding: 0.5rem 1rem;
  border-radius: 0.375rem;
  font-size: 0.8125rem;
  cursor: pointer;
  border: 1px solid var(--border-color);
}
.btn-primary {
  background: var(--accent-500);
  color: white;
  border-color: var(--accent-500);
  box-shadow: 0 2px 8px rgba(124, 106, 173, 0.25);
}
.btn-primary:hover {
  background: var(--accent-600);
}
.btn-secondary {
  background: var(--bg-primary);
  color: var(--text-primary);
}
.btn-secondary:hover {
  background: var(--hover-bg);
}
</style>
