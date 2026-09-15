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
  /** 多动作按钮组（学着闭嘴：幽灵蒸发理由条等；点击任一即执行并关闭） */
  actions?: ToastAction[]
}

const props = defineProps<{
  toasts: Toast[]
}>()

const emit = defineEmits<{
  'remove': [id: number]
}>()

/** P1 §8.6：弃实底语义色——float 表面 + 左侧 3px 语义色条 + 语义色图标/动作。
 *  每枚 toast 以 --toast-bar 注入本型语义色（ok/danger/warn/info token）。 */
const barColors: Record<ToastType, string> = {
  success: 'var(--ok)',
  error: 'var(--danger)',
  warning: 'var(--warn)',
  info: 'var(--info)'
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
  <div class="toast-region fixed top-4 right-4 flex flex-col gap-2" role="status" aria-live="polite">
    <TransitionGroup name="toast">
      <div
        v-for="toast in toasts"
        :key="toast.id"
        class="toast-card elev-3"
        :style="{ '--toast-bar': barColors[toast.type] }"
      >
        <div class="toast-row">
          <svg
            class="toast-icon"
            xmlns="http://www.w3.org/2000/svg"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            stroke-linecap="round"
            stroke-linejoin="round"
            aria-hidden="true"
          >
            <path :d="typeIcons[toast.type]" />
          </svg>
          <span class="toast-msg tnum">{{ toast.message }}</span>
          <div class="flex items-center gap-2">
            <button
              v-if="toast.action"
              class="toast-action"
              @click="runAction(toast.id, toast.action)"
            >{{ toast.action.label }}</button>
            <button
              class="toast-close"
              title="关闭"
              @click="removeToast(toast.id)"
            >
              <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" viewBox="0 0 20 20" fill="currentColor">
                <path fill-rule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clip-rule="evenodd" />
              </svg>
            </button>
          </div>
        </div>
        <!-- 多动作按钮组（学着闭嘴：理由条等；任一点击即执行并关闭） -->
        <div v-if="toast.actions?.length" class="flex flex-wrap gap-1.5 mt-2">
          <button
            v-for="a in toast.actions"
            :key="a.label"
            class="toast-chip"
            @click="runAction(toast.id, a)"
          >{{ a.label }}</button>
        </div>
      </div>
    </TransitionGroup>
  </div>
</template>

<style scoped>
/* toast 必须永远最上（--z-toast=120，00 期 §3.1） */
.toast-region {
  z-index: var(--z-toast);
}

/* P1 §8.6：float 表面 + 毛玻璃 + elev-3（暗档自动 chroma 影+顶部内高光），
   左侧 3px 语义色条 = 本型唯一强信号（弃整块实底） */
.toast-card {
  min-width: 200px;
  max-width: 400px;
  padding: 12px 16px;
  border-radius: var(--radius-lg);
  background: var(--surface-float);
  backdrop-filter: blur(8px);
  border-left: 3px solid var(--toast-bar);
  color: var(--text-primary);
  font-size: var(--text-sm);
}
.toast-row {
  display: flex;
  align-items: center;
  gap: 10px;
}
.toast-icon {
  flex-shrink: 0;
  width: 18px;
  height: 18px;
  color: var(--toast-bar);
}
.toast-msg {
  flex: 1;
  min-width: 0;
  font-weight: 500;
  line-height: var(--lh-normal);
}
.toast-action {
  flex-shrink: 0;
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--toast-bar);
  text-decoration: underline;
  text-underline-offset: 2px;
}
.toast-action:hover {
  filter: brightness(1.15);
}
.toast-close {
  flex-shrink: 0;
  display: inline-flex;
  color: var(--text-muted);
  transition: color var(--dur-1) var(--ease-out);
}
.toast-close:hover {
  color: var(--text-primary);
}
/* 多动作 chip：语义色浅底（color-mix，新透明度唯一通道） */
.toast-chip {
  font-size: var(--text-xs);
  font-weight: 600;
  padding: 2px 8px;
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--toast-bar) 12%, transparent);
  color: var(--text-primary);
  transition: background var(--dur-1) var(--ease-out);
}
.toast-chip:hover {
  background: color-mix(in srgb, var(--toast-bar) 24%, transparent);
}

/* P1 §8.6：入场上浮淡入 8px→0（dur-3 ease-out），退场 dur-2 ease-in */
.toast-enter-active {
  transition: opacity var(--dur-3) var(--ease-out), transform var(--dur-3) var(--ease-out);
}
.toast-leave-active {
  transition: opacity var(--dur-2) var(--ease-in), transform var(--dur-2) var(--ease-in);
}
.toast-enter-from {
  opacity: 0;
  transform: translateY(8px);
}
.toast-leave-to {
  opacity: 0;
  transform: translateY(8px);
}
</style>
