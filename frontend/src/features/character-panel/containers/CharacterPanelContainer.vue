<script setup lang="ts">
import CharacterPanelView from '../presentation/CharacterPanelView.vue'

defineProps<{
  bookId?: string
}>()

const emit = defineEmits<{
  (e: 'close'): void
}>()
</script>

<template>
  <CharacterPanelView
    :book-id="bookId"
    @close="emit('close')"
  />
</template>
