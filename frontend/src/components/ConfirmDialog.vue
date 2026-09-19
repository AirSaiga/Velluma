<script setup lang="ts">
/**
 * 全局确认框（02 §5 收编 ModalShell：Teleport/焦点陷阱/Esc 栈/遮罩点击统一托底）。
 * Esc/遮罩点击 = 取消；默认聚焦「取消」防 Enter 误触二次操作（ModalShell 首元素）。
 */
import { computed } from 'vue'
import ModalShell from './ModalShell.vue'

export interface ConfirmDialogOptions {
  title: string
  message: string
  warning?: string
  confirmText?: string
  cancelText?: string
}

const props = defineProps<{
  options: ConfirmDialogOptions | null
  visible: boolean
}>()

const emit = defineEmits<{
  'confirm': []
  'cancel': []
}>()

const title = computed(() => props.options?.title ?? '确认')
const message = computed(() => props.options?.message ?? '')
const warning = computed(() => props.options?.warning ?? '')
const confirmText = computed(() => props.options?.confirmText ?? '确认')
const cancelText = computed(() => props.options?.cancelText ?? '取消')
</script>

<template>
  <ModalShell
    v-if="visible && options"
    :title="title"
    width="28rem"
    @close="emit('cancel')"
  >
    <p class="cd-message">{{ message }}</p>
    <div v-if="warning" class="cd-warning">
      <svg xmlns="http://www.w3.org/2000/svg" class="cd-warning-icon" viewBox="0 0 20 20" fill="currentColor">
        <path fill-rule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clip-rule="evenodd" />
      </svg>
      <p class="cd-warning-text">{{ warning }}</p>
    </div>
    <template #footer>
      <button class="cd-btn" @click="emit('cancel')">{{ cancelText }}</button>
      <button class="cd-btn cd-btn--confirm" @click="emit('confirm')">{{ confirmText }}</button>
    </template>
  </ModalShell>
</template>

<style scoped>
.cd-message {
  font-size: var(--text-md);
  line-height: var(--lh-normal);
  color: var(--text-secondary);
  white-space: pre-wrap;
  margin-bottom: var(--space-4);
}

.cd-warning {
  display: flex;
  align-items: flex-start;
  gap: var(--space-2);
  padding: var(--space-3);
  background: color-mix(in srgb, var(--warn) 8%, transparent);
  border: 1px solid color-mix(in srgb, var(--warn) 35%, transparent);
  border-radius: var(--radius-md);
}

.cd-warning-icon {
  width: 20px;
  height: 20px;
  flex-shrink: 0;
  margin-top: 2px;
  color: var(--warn);
}

.cd-warning-text {
  font-size: var(--text-sm);
  line-height: var(--lh-normal);
  color: var(--warn);
}

.cd-btn {
  padding: 8px 16px;
  font-size: var(--text-base);
  font-weight: 500;
  color: var(--text-secondary);
  background: var(--bg-secondary);
  border: 1px solid var(--line-faint);
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: all var(--dur-2) var(--ease-out);
}

.cd-btn:hover {
  background: var(--state-hover);
  color: var(--text-primary);
}

.cd-btn--confirm {
  color: var(--bg-canvas);
  background: var(--danger);
  border-color: var(--danger);
}

.cd-btn--confirm:hover {
  filter: brightness(0.92);
  color: var(--bg-canvas);
}
</style>
