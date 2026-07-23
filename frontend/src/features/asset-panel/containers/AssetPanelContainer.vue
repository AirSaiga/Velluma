<script setup lang="ts">
import AssetPanelView from '../presentation/AssetPanelView.vue'

withDefaults(defineProps<{
  bookId?: string
  closable?: boolean
}>(), {
  bookId: undefined,
  closable: true
})

const emit = defineEmits<{
  (e: 'close'): void
}>()
</script>

<template>
  <AssetPanelView
    :book-id="bookId"
    :closable="closable"
    @close="emit('close')"
  />
</template>
