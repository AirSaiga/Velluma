<script setup lang="ts">
import { ref, computed } from 'vue'
import { useFocusTrap } from '../../../composables/useFocusTrap'

const props = defineProps<{
  show: boolean
  characterUpdates: Array<{
    character_id: string
    character_name: string
    old_state: string
    new_state: string
  }>
  characterExtraction: any
}>()

const emit = defineEmits<{
  (e: 'close'): void
}>()

const modalRef = ref<HTMLElement | null>(null)
const showRef = computed(() => props.show)
useFocusTrap(modalRef, showRef, { onEscape: () => emit('close') })
</script>

<template>
  <Teleport to="body">
    <div
      v-if="show"
      ref="modalRef"
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/45 p-3"
      @click.self="emit('close')"
    >
      <div class="bg-[var(--bg-primary)] rounded-2xl shadow-2xl w-full max-w-lg max-h-[85vh] overflow-hidden flex flex-col">
        <div class="p-3 border-b border-[var(--border-color)] flex items-center justify-between">
          <h3 class="text-sm font-semibold text-[var(--text-primary)]">发布成功</h3>
          <button @click="emit('close')" class="p-1 text-[var(--text-muted)] hover:text-[var(--text-primary)]">
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
            </svg>
          </button>
        </div>
        <div class="p-4 overflow-y-auto max-h-[calc(85vh-120px)]">
          <div v-if="characterUpdates.length > 0" class="mb-4">
            <h4 class="text-xs font-medium text-[var(--text-secondary)] mb-2">本次角色状态变更记录</h4>
            <div class="space-y-2">
              <div
                v-for="update in characterUpdates"
                :key="update.character_id"
                class="p-2 bg-[var(--bg-panel)] rounded-lg text-xs"
              >
                <div class="font-medium text-[var(--text-primary)]">{{ update.character_name }}</div>
                <div class="text-[var(--text-muted)] mt-1">
                  <span class="line-through">{{ update.old_state }}</span>
                  <span class="mx-1">→</span>
                  <span class="text-green-600">{{ update.new_state }}</span>
                </div>
              </div>
            </div>
          </div>
          <div v-else class="text-center text-sm text-[var(--text-muted)] py-4">
            本次发布无角色状态变更记录
          </div>

          <div v-if="characterExtraction && characterExtraction.extracted_characters && characterExtraction.extracted_characters.length > 0" class="mt-6">
            <h4 class="text-xs font-medium text-[var(--text-secondary)] mb-2">新提取的角色信息</h4>
            <div class="space-y-3">
              <div
                v-for="character in characterExtraction.extracted_characters"
                :key="character.name"
                class="p-3 bg-[var(--bg-panel)] rounded-lg text-xs"
              >
                <div class="flex items-center justify-between mb-1">
                  <div class="font-medium text-[var(--text-primary)]">{{ character.name }}</div>
                  <span v-if="character.is_new" class="px-2 py-0.5 text-[10px] rounded-full bg-green-100 text-green-700">新角色</span>
                  <span v-else class="px-2 py-0.5 text-[10px] rounded-full bg-blue-100 text-blue-700">已有角色</span>
                </div>
                <div class="text-[var(--text-muted)] mt-1">
                  <div v-if="character.description" class="mb-1">{{ character.description }}</div>
                  <div class="flex items-center gap-2 mt-1">
                    <span>角色类型: {{ character.role_type }}</span>
                    <span>重要性: {{ character.importance_level }}</span>
                  </div>
                  <div v-if="character.aliases && character.aliases.length > 0" class="mt-1">
                    别名: {{ character.aliases.join(', ') }}
                  </div>
                </div>
              </div>
            </div>
            <div class="mt-3 text-xs text-[var(--text-muted)]">
              共提取 {{ characterExtraction.extracted_characters.length }} 个角色，其中新角色 {{ characterExtraction.new_characters_count }} 个
            </div>
          </div>
        </div>
        <div class="p-3 border-t border-[var(--border-color)] flex justify-end gap-2">
          <button @click="emit('close')" class="px-4 py-1.5 text-xs rounded-lg bg-[var(--accent-500)] text-white hover:bg-accent-600">
            完成
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>
