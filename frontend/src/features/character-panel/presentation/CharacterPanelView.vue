<script setup lang="ts">
import { ref, onMounted } from 'vue'

const props = defineProps<{
  bookId?: string
}>()

const emit = defineEmits<{
  (e: 'close'): void
}>()

// TODO: 实现角色面板逻辑
const isLoading = ref(false)
</script>

<template>
  <div class="h-full flex flex-col bg-[var(--bg-primary)] overflow-hidden">
    <!-- 头部区域 -->
    <div class="p-4 border-b border-[var(--border-color)] flex-shrink-0 bg-[var(--bg-canvas)]">
      <div class="flex items-center justify-between mb-4">
        <h2 class="text-lg font-heading font-semibold text-[var(--text-primary)] flex items-center gap-2">
          <svg class="w-5 h-5 text-[var(--accent-500)]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"/>
          </svg>
          角色管理
        </h2>
        <button @click="emit('close')" class="p-1.5 text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-panel)] rounded-md transition-colors">
          <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
          </svg>
        </button>
      </div>
    </div>

    <!-- 列表区域 -->
    <div class="flex-1 overflow-y-auto p-4">
      <div v-if="isLoading" class="flex justify-center items-center py-8">
        <svg class="animate-spin h-6 w-6 text-[var(--accent-500)]" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
        </svg>
      </div>
      
      <div v-else class="text-center py-12">
        <div class="w-16 h-16 mx-auto mb-4 rounded-full bg-[var(--bg-canvas)] flex items-center justify-center">
          <svg class="w-8 h-8 text-[var(--text-muted)]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"/>
          </svg>
        </div>
        <p class="text-[var(--text-secondary)] font-medium mb-1">角色管理面板</p>
        <p class="text-sm text-[var(--text-muted)]">该面板正在开发中...</p>
      </div>
    </div>
  </div>
</template>
