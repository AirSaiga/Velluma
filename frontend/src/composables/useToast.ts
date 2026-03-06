import { ref } from 'vue'
import type { Toast, ToastType } from '../components/Toast.vue'

const toasts = ref<Toast[]>([])
let nextId = 0

export function useToast() {
  const showToast = (message: string, type: ToastType = 'info') => {
    const id = nextId++
    toasts.value.push({ id, message, type })
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
