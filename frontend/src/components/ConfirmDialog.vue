<script setup lang="ts">
import { ref, watch, computed } from 'vue'
import { useFocusTrap } from '../composables/useFocusTrap'

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

function handleConfirm() {
  emit('confirm')
}

function handleCancel() {
  emit('cancel')
}

// 键盘可用（UX 修复）：Esc=取消、Tab 焦点捕获、关闭后焦点还原。
// 默认聚焦第一个可焦点元素 = 「取消」按钮（DOM 顺序在前）——危险确认场景
// 防止焦点停留在背后页面的删除按钮上，Enter 误触发二次操作。
const dialogRef = ref<HTMLElement | null>(null)
const dialogActive = computed(() => props.visible && !!props.options)
useFocusTrap(dialogRef, dialogActive, { onEscape: handleCancel })
</script>

<template>
  <Teleport to="body">
    <Transition name="modal">
      <div
        v-if="visible && options"
        class="fixed inset-0 z-[110] flex items-center justify-center"
      >
        <div class="fixed inset-0 bg-black/40 backdrop-blur-sm" @click="handleCancel"></div>
        <div
          ref="dialogRef"
          class="modal-content relative bg-parchment-50 dark:bg-gray-800 rounded-2xl shadow-xl w-full max-w-md mx-4 overflow-hidden"
          role="dialog"
          aria-modal="true"
          aria-labelledby="confirm-dialog-title"
        >
          <div class="p-6">
            <h3 id="confirm-dialog-title" class="text-lg font-heading font-semibold text-gray-900 dark:text-gray-100 mb-3">
              {{ title }}
            </h3>
            <p class="text-gray-600 dark:text-gray-300 mb-4 whitespace-pre-wrap">
              {{ message }}
            </p>
            <div
              v-if="warning"
              class="flex items-start gap-2 p-3 bg-amber-50 dark:bg-amber-900/30 border border-amber-200 dark:border-amber-700 rounded-xl ring-1 ring-[var(--border-color)]/60"
            >
              <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5 text-amber-500 flex-shrink-0 mt-0.5" viewBox="0 0 20 20" fill="currentColor">
                <path fill-rule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clip-rule="evenodd" />
              </svg>
              <p class="text-sm text-amber-700 dark:text-amber-300">{{ warning }}</p>
            </div>
          </div>
          <div class="flex justify-end gap-3 px-6 py-4 bg-ink-50 dark:bg-gray-700/50 border-t border-ink-100 dark:border-gray-700">
            <button
              @click="handleCancel"
              class="px-4 py-2 text-sm font-medium text-ink-700 dark:text-gray-300 bg-parchment-50 dark:bg-gray-600 border border-ink-200 dark:border-gray-500 rounded-xl hover:bg-ink-50 dark:hover:bg-gray-500 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-ink-500 transition-colors"
            >
              {{ cancelText }}
            </button>
            <button
              @click="handleConfirm"
              class="px-4 py-2 text-sm font-medium text-white bg-red-600 hover:bg-red-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-red-500 rounded-xl transition-colors"
            >
              {{ confirmText }}
            </button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>


