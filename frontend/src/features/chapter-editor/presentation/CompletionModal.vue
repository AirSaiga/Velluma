<script setup lang="ts">
defineProps<{
  show: boolean
  title: string
  message: string
}>()

const emit = defineEmits<{
  (e: 'close'): void
}>()
</script>

<template>
  <div
    v-if="show"
    class="fixed inset-0 z-50 flex items-center justify-center bg-black/45 p-3"
    @click.self="emit('close')"
  >
    <div class="bg-[var(--bg-primary)] rounded-2xl shadow-2xl w-full max-w-md overflow-hidden">
      <div class="p-4 text-center">
        <div class="w-12 h-12 mx-auto mb-3 rounded-full bg-[var(--accent-100)] flex items-center justify-center">
          <svg class="w-6 h-6 text-[var(--accent-700)]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/>
          </svg>
        </div>
        <h3 class="text-base font-semibold text-[var(--text-primary)] mb-1">{{ title }}</h3>
        <p class="text-sm text-[var(--text-secondary)]">{{ message }}</p>
      </div>
      <div class="p-3 border-t border-[var(--border-color)] flex justify-center">
        <button @click="emit('close')" class="px-4 py-1.5 text-xs rounded-lg bg-[var(--accent-500)] text-white hover:bg-accent-600">
          确定
        </button>
      </div>
    </div>
  </div>
</template>
