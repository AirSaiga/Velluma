<script setup lang="ts">
/**
 * 「从样本提炼」弹窗（Match My Style）——迁移自 StyleCardManager 内嵌 modal。
 *
 * 红线保持：提炼不落库，结果回填编辑区由作者过目（容器确认后才随自动保存入库）。
 * 打开时容器会把样本库中最长的 3 条预填进来（零状态坡道第三幕的承接）。
 */
import { ref, watch } from 'vue'

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
  <Teleport to="body">
    <div
      v-if="open"
      class="modal-mask"
      @click.self="emit('close')"
    >
      <div class="modal-card">
        <header class="modal-head">
          <h3 class="modal-title">从样本提炼文风画像</h3>
          <button class="modal-close" @click="emit('close')">✕</button>
        </header>
        <div class="modal-body">
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
        </div>
        <footer class="modal-foot">
          <button class="btn-ghost" @click="emit('close')">取消</button>
          <button class="btn-primary" :disabled="isExtracting" @click="run">
            {{ isExtracting ? '提炼中（5-15s）…' : '开始提炼' }}
          </button>
        </footer>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.modal-mask {
  position: fixed;
  inset: 0;
  z-index: 50;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 0.75rem;
  background: rgb(0 0 0 / 45%);
}
.modal-card {
  display: flex;
  flex-direction: column;
  width: 100%;
  max-width: 40rem;
  max-height: 80vh;
  overflow: hidden;
  background: var(--bg-primary);
  border-radius: 1rem;
  box-shadow: 0 25px 50px -12px rgb(0 0 0 / 25%);
}
.modal-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.75rem 1rem;
  border-bottom: 1px solid var(--border-color);
}
.modal-title {
  margin: 0;
  font-size: 0.875rem;
  font-weight: 600;
  color: var(--text-primary);
}
.modal-close {
  padding: 0.25rem 0.5rem;
  font-size: 0.75rem;
  color: var(--text-muted);
  background: transparent;
  border: none;
  cursor: pointer;
}
.modal-close:hover {
  color: var(--text-primary);
}
.modal-body {
  flex: 1;
  padding: 1rem;
  overflow-y: auto;
}
.modal-note {
  margin: 0 0 0.75rem;
  font-size: 0.6875rem;
  line-height: 1.7;
  color: var(--text-muted);
}
.extract-field {
  margin-bottom: 0.75rem;
}
.field-label {
  display: block;
  margin-bottom: 0.25rem;
  font-size: 0.6875rem;
  color: var(--text-muted);
}
.field-textarea {
  width: 100%;
  padding: 0.375rem 0.5rem;
  font-size: 0.75rem;
  background: var(--bg-panel);
  border: 1px solid var(--border-color);
  border-radius: 0.375rem;
  resize: vertical;
}
.field-textarea:focus {
  outline: none;
  border-color: var(--accent-400);
}
.modal-foot {
  display: flex;
  justify-content: flex-end;
  gap: 0.5rem;
  padding: 0.75rem 1rem;
  border-top: 1px solid var(--border-color);
}
.btn-ghost {
  padding: 0.375rem 0.75rem;
  font-size: 0.75rem;
  color: var(--text-secondary);
  background: var(--bg-panel);
  border: none;
  border-radius: 0.375rem;
  cursor: pointer;
}
.btn-primary {
  padding: 0.375rem 0.875rem;
  font-size: 0.75rem;
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
