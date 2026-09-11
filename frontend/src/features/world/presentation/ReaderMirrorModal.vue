<script setup lang="ts">
/**
 * 期待账本模态（M5：期待账本在世界页的承载入口——侧栏摘要分组/深链 ?panel=expectations 触发）。
 *
 * 内容为 ReaderMirrorBoard（火候看板 + 张力曲线，自设定中心整面板迁入，功能不丢）。
 */
import ModalShell from '../../../components/ModalShell.vue'
import ReaderMirrorBoard from './ReaderMirrorBoard.vue'

defineProps<{ bookId: string }>()

const emit = defineEmits<{ close: [] }>()
</script>

<template>
  <ModalShell
    title="期待账本"
    subtitle="读者此刻在等什么、火候如何——写作页「头顶的线」与本账本同源"
    width="640px"
    @close="emit('close')"
  >
    <ReaderMirrorBoard :book-id="bookId" />
  </ModalShell>
</template>
