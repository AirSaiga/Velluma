import { ref } from 'vue'
import type { Toast, ToastType } from '../components/Toast.vue'

const toasts = ref<Toast[]>([])
let nextId = 0

const typeDurations: Record<ToastType, number> = {
  success: 4000,
  error: 6000,
  warning: 5000,
  info: 4000
}

export interface ToastAction {
  label: string
  onClick: () => void
}

export function useToast() {
  /** 显示 toast；action（可选）渲染为可点按钮——点击即执行并关掉 toast（S4 撤销胶囊基础） */
  const showToast = (
    message: string,
    type: ToastType = 'info',
    duration?: number,
    action?: ToastAction,
  ) => {
    const id = nextId++
    toasts.value.push({ id, message, type, action })
    setTimeout(() => {
      removeToast(id)
    }, duration ?? typeDurations[type])
  }

  const removeToast = (id: number) => {
    const index = toasts.value.findIndex(t => t.id === id)
    if (index !== -1) {
      toasts.value.splice(index, 1)
    }
  }

  return {
    toasts,
    showToast,
    removeToast
  }
}
