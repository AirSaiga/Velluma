<script setup lang="ts">
import AssetPanelView from '../presentation/AssetPanelView.vue'

defineProps<{
  bookId?: string
}>()

const emit = defineEmits<{
  (e: 'close'): void
}>()
</script>

<template>
  <AssetPanelView
    :book-id="bookId"
    @close="emit('close')"
  />
</template>
