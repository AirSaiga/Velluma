<script setup lang="ts">
/**
 * 世界观设定模态（M5：世界观文本在世界页的承载入口——顶栏「世界观」按钮触发）。
 *
 * 内容为 WorldviewPanel（自设定中心迁入，自动保存/导入导出功能不丢）。
 * 世界观文本经 settings_bundle 进 AI 生成上下文（system prompt 前缀）。
 */
import ModalShell from '../../../components/ModalShell.vue'
import WorldviewPanel from './WorldviewPanel.vue'

defineProps<{ bookId: string }>()

const emit = defineEmits<{ close: [] }>()
</script>

<template>
  <ModalShell
    title="世界观设定"
    subtitle="世界背景、规则、历史——写作时自动注入 AI 生成上下文"
    width="640px"
    @close="emit('close')"
  >
    <WorldviewPanel :book-id="bookId" />
  </ModalShell>
</template>
