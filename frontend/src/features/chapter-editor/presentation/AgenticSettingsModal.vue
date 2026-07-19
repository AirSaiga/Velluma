<script setup lang="ts">
import { IntentDrivenPanel } from '../../intent-driven'
import Icon from '@/components/Icon.vue'
import type { ApiConfig, Chapter } from '../../../types'

defineProps<{
  show: boolean
  selectedChapter: Chapter | null
  apiConfig: ApiConfig
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'save', payload: any): void
  (e: 'generate', payload: any): void
}>()
</script>

<template>
  <Teleport to="body">
    <Transition name="modal-backdrop">
      <div
        v-if="show"
        class="fixed inset-0 z-50 flex items-center justify-center p-4 sm:p-6"
        @click.self="emit('close')"
      >
        <div class="absolute inset-0 bg-black/40 backdrop-blur-sm"></div>
        <Transition name="modal-content">
          <div
            v-if="show"
            class="relative w-full max-w-5xl bg-[var(--bg-canvas)] rounded-2xl shadow-xl overflow-hidden flex flex-col"
            :style="{ height: '90vh' }"
          >
            <button
              @click="emit('close')"
              class="absolute top-3 right-3 z-10 w-7 h-7 flex items-center justify-center rounded-full bg-black/5 hover:bg-black/10 text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors"
            >
              <Icon name="x-mark" :size="16" />
            </button>
            <div class="flex-1 overflow-hidden min-h-0 flex flex-col">
              <IntentDrivenPanel
                :chapter-id="selectedChapter?.id || ''"
                :api-config="apiConfig"
                @save="(payload) => { emit('close'); emit('save', payload); }"
                @generate="(payload) => { emit('close'); emit('generate', payload); }"
              />
            </div>
          </div>
        </Transition>
      </div>
    </Transition>
  </Teleport>
</template>
