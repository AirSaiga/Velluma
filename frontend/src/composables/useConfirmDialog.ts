import { getCurrentInstance, onUnmounted, ref } from 'vue'
import type { ConfirmDialogOptions } from '../components/ConfirmDialog.vue'

interface DialogRequest {
  id: number
  options: ConfirmDialogOptions
  resolve: (value: boolean) => void
}

const visible = ref(false)
const options = ref<ConfirmDialogOptions | null>(null)
const queue = ref<DialogRequest[]>([])
let nextId = 0
let currentRequest: DialogRequest | null = null

function processQueue() {
  if (visible.value || queue.value.length === 0) return
  currentRequest = queue.value.shift() || null
  if (currentRequest) {
    options.value = currentRequest.options
    visible.value = true
  }
}

function cleanupAll() {
  while (queue.value.length > 0) {
    const req = queue.value.shift()
    if (req) req.resolve(false)
  }
  if (currentRequest) {
    currentRequest.resolve(false)
    currentRequest = null
  }
  visible.value = false
  options.value = null
}

export function useConfirmDialog() {
  const instance = getCurrentInstance()
  if (instance) {
    onUnmounted(cleanupAll)
  }

  const show = (opts: ConfirmDialogOptions): Promise<boolean> => {
    return new Promise((resolve) => {
      const id = nextId++
      queue.value.push({ id, options: opts, resolve })
      processQueue()
    })
  }

  const handleConfirm = () => {
    visible.value = false
    if (currentRequest) {
      currentRequest.resolve(true)
      currentRequest = null
    }
    options.value = null
    setTimeout(processQueue, 50)
  }

  const handleCancel = () => {
    visible.value = false
    if (currentRequest) {
      currentRequest.resolve(false)
      currentRequest = null
    }
    options.value = null
    setTimeout(processQueue, 50)
  }

  return {
    visible,
    options,
    show,
    handleConfirm,
    handleCancel
  }
}
