<script setup lang="ts">
import { ref } from 'vue'

export type ToastType = 'success' | 'error' | 'warning' | 'info'

export interface ToastAction {
  label: string
  onClick: () => void
}

export interface Toast {
  id: number
  message: string
  type: ToastType
  /** 可选动作按钮（S4：撤销胶囊等；点击即执行并关闭） */
  action?: ToastAction
}

const props = defineProps<{
  toasts: Toast[]
}>()

const emit = defineEmits<{
  'remove': [id: number]
}>()

const typeStyles: Record<ToastType, string> = {
  success: 'bg-[var(--accent-500)] text-white',
  error: 'bg-rose-500 text-white',
  warning: 'bg-amber-500 text-white',
  info: 'bg-blue-500 text-white'
}

const typeIcons: Record<ToastType, string> = {
  success: 'M5 13l4 4L19 7',
  error: 'M6 18L18 6M6 6l12 12',
  warning: 'M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z',
  info: 'M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z'
}

function removeToast(id: number) {
  emit('remove', id)
}

function runAction(id: number, action: ToastAction) {
  action.onClick()
  removeToast(id)
}
</script>

<template>
  <!-- z-index 分层：drawer(85) < modal/confirm(110) < toast(120)——toast 必须永远可见，
       此前 z-50 会被副驾抽屉（z-85）整个挡住 -->
  <div class="fixed top-4 right-4 z-[120] flex flex-col gap-2" role="status" aria-live="polite">
    <TransitionGroup name="toast">
      <div
        v-for="toast in toasts"
        :key="toast.id"
        :class="[
          'px-4 py-3 rounded-lg shadow-lg min-w-[200px] max-w-[400px]',
          typeStyles[toast.type]
        ]"
      >
        <div class="flex items-center justify-between gap-3">
          <span class="text-sm font-medium">{{ toast.message }}</span>
          <div class="flex items-center gap-2">
            <button
              v-if="toast.action"
              @click="runAction(toast.id, toast.action)"
              class="text-sm font-semibold underline underline-offset-2 opacity-90 hover:opacity-100 transition-opacity"
            >{{ toast.action.label }}</button>
            <button
              @click="removeToast(toast.id)"
              class="opacity-70 hover:opacity-100 transition-opacity"
            >
              <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" viewBox="0 0 20 20" fill="currentColor">
                <path fill-rule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clip-rule="evenodd" />
              </svg>
            </button>
          </div>
        </div>
      </div>
    </TransitionGroup>
  </div>
</template>

<style scoped>
.toast-enter-active,
.toast-leave-active {
  transition: all 0.3s ease;
}

.toast-enter-from {
  opacity: 0;
  transform: translateX(100%);
}

.toast-leave-to {
  opacity: 0;
  transform: translateX(100%);
}
</style>
