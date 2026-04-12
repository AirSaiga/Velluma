/**
 * Toast 和 Confirm Dialog 工具模块
 * 提供全局 toast 和确认对话框的便捷调用接口
 */

import { getCurrentInstance, onUnmounted, ref } from 'vue'
import type { ConfirmDialogOptions } from '../../components/ConfirmDialog.vue'
import type { Toast, ToastType } from '../../components/Toast.vue'

// Toast 状态
const toasts = ref<Toast[]>([])
let nextToastId = 0

// Confirm Dialog 状态
const dialogVisible = ref(false)
const dialogOptions = ref<ConfirmDialogOptions | null>(null)
let resolvePromise: ((value: boolean) => void) | null = null

function cleanupPromise() {
  if (resolvePromise) {
    resolvePromise(false)
    resolvePromise = null
    dialogVisible.value = false
    dialogOptions.value = null
  }
}

/**
 * 显示 Toast 消息
 */
export function showToast(message: string, type: ToastType = 'info') {
  const id = nextToastId++
  toasts.value.push({ id, message, type })
}

/**
 * 移除 Toast 消息
 */
export function removeToast(id: number) {
  const index = toasts.value.findIndex(t => t.id === id)
  if (index !== -1) {
    toasts.value.splice(index, 1)
  }
}

/**
 * 显示确认对话框
 */
export function showConfirm(opts: ConfirmDialogOptions): Promise<boolean> {
  const instance = getCurrentInstance()
  if (instance) {
    onUnmounted(cleanupPromise)
  }

  dialogOptions.value = opts
  dialogVisible.value = true

  return new Promise((resolve) => {
    resolvePromise = resolve
  })
}

/**
 * 确认对话框 - 内部使用
 */
export function handleConfirm() {
  dialogVisible.value = false
  if (resolvePromise) {
    resolvePromise(true)
    resolvePromise = null
  }
  dialogOptions.value = null
}

/**
 * 取消对话框 - 内部使用
 */
export function handleCancel() {
  dialogVisible.value = false
  if (resolvePromise) {
    resolvePromise(false)
    resolvePromise = null
  }
  dialogOptions.value = null
}

export { toasts, dialogVisible, dialogOptions }
