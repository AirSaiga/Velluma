import { getCurrentInstance, onUnmounted, ref } from 'vue'
import type { ConfirmDialogOptions } from '../components/ConfirmDialog.vue'

const visible = ref(false)
const options = ref<ConfirmDialogOptions | null>(null)
let resolvePromise: ((value: boolean) => void) | null = null

function cleanupPromise() {
  if (resolvePromise) {
    resolvePromise(false)
    resolvePromise = null
    visible.value = false
    options.value = null
  }
}

export function useConfirmDialog() {
  const instance = getCurrentInstance()
  if (instance) {
    onUnmounted(cleanupPromise)
  }

  const show = (opts: ConfirmDialogOptions): Promise<boolean> => {
    options.value = opts
    visible.value = true
    
    return new Promise((resolve) => {
      resolvePromise = resolve
    })
  }

  const handleConfirm = () => {
    visible.value = false
    if (resolvePromise) {
      resolvePromise(true)
      resolvePromise = null
    }
    options.value = null
  }

  const handleCancel = () => {
    visible.value = false
    if (resolvePromise) {
      resolvePromise(false)
      resolvePromise = null
    }
    options.value = null
  }

  return {
    visible,
    options,
    show,
    handleConfirm,
    handleCancel
  }
}
