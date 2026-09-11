<script setup lang="ts">
/**
 * 「从样本提炼」弹窗（Match My Style）——迁移自 StyleCardManager 内嵌 modal。
 *
 * 红线保持：提炼不落库，结果回填编辑区由作者过目（容器确认后才随自动保存入库）。
 * 打开时容器会把样本库中最长的 3 条预填进来（零状态坡道第三幕的承接）。
 * 壳走全局 ModalShell（00 期 §4.8：焦点陷阱/Esc 栈/遮罩点击统一托底）。
 */
import { ref, watch } from 'vue'
import ModalShell from '../../../components/ModalShell.vue'

const props = defineProps<{
  open: boolean
  prefill: string[]
  isExtracting?: boolean
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'run', samples: string[]): void
}>()

const extractSamples = ref<string[]>(['', '', ''])

watch(
  () => props.open,
  (open) => {
    if (open) {
      extractSamples.value = [0, 1, 2].map(i => props.prefill[i] || '')
    }
  },
)

function run() {
  const valid = extractSamples.value.filter(s => s.trim().length > 20)
  if (valid.length < 1) return
  emit('run', valid)
}
</script>

<template>
  <ModalShell v-if="open" title="从样本提炼文风画像" width="40rem" @close="emit('close')">
    <p class="modal-note">
      粘贴 2-3 段你写的文字（已预填样本库里最长的几条），AI 提炼句长节奏、词汇层级与负面清单建议。
      约 5-15 秒 · 1 次调用；结果只回填编辑区，你过目后才保存。
    </p>
    <div v-for="(_, idx) in extractSamples" :key="idx" class="extract-field">
      <label class="field-label">样本 {{ idx + 1 }}</label>
      <textarea
        v-model="extractSamples[idx]"
        rows="5"
        class="field-textarea"
        placeholder="粘贴你写的原文（建议 200-2000 字）"
      ></textarea>
    </div>
    <template #footer>
      <button class="btn-ghost" @click="emit('close')">取消</button>
      <button class="btn-primary" :disabled="isExtracting" @click="run">
        {{ isExtracting ? '提炼中（5-15s）…' : '开始提炼' }}
      </button>
    </template>
  </ModalShell>
</template>

<style scoped>
.modal-note {
  margin: 0 0 0.75rem;
  font-size: var(--text-sm);
  line-height: 1.7;
  color: var(--text-muted);
}
.extract-field {
  margin-bottom: 0.75rem;
}
.field-label {
  display: block;
  margin-bottom: 0.25rem;
  font-size: var(--text-sm);
  color: var(--text-secondary);
}
.field-textarea {
  width: 100%;
  padding: 0.375rem 0.5rem;
  font-size: var(--text-base);
  line-height: var(--lh-normal);
  background: var(--bg-panel);
  border: 1px solid var(--border-color);
  border-radius: 0.375rem;
  resize: vertical;
}
.field-textarea:focus {
  border-color: var(--accent-400);
}
.btn-ghost {
  min-height: 28px;
  padding: 0.375rem 0.75rem;
  font-size: var(--text-base);
  color: var(--text-secondary);
  background: var(--bg-panel);
  border: none;
  border-radius: 0.375rem;
  cursor: pointer;
}
.btn-primary {
  min-height: 28px;
  padding: 0.375rem 0.875rem;
  font-size: var(--text-base);
  color: white;
  background: var(--accent-500);
  border: none;
  border-radius: 0.375rem;
  cursor: pointer;
}
.btn-primary:hover:not(:disabled) {
  background: var(--accent-600);
}
.btn-primary:disabled {
  opacity: 0.5;
}
</style>
