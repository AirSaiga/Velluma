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

export function useToast() {
  const showToast = (message: string, type: ToastType = 'info', duration?: number) => {
    const id = nextId++
    toasts.value.push({ id, message, type })
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
