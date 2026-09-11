<script setup lang="ts">
/**
 * 左缘书签（08 期 §4.2，docs/design/ux-redesign/08-writing-desk-total-redesign.md）。
 *
 * 章节系统的写中入口：整签一钮，点击开目录抽屉。仅在有选中章时由容器挂载
 * （无选中章时纸面就是目录，书签缺席）。打字沉浸时随 .workspace-view--typing
 * 淡至 35%（样式在 style.css 全局段，与右缘栏同律）。无 hover 展开——点击制。
 */
import { computed } from 'vue'
import Icon from '../../../components/Icon.vue'

const props = defineProps<{
  /** 当前章标识（如「第3章 · 雨夜来客」；超过 10 字本组件截断） */
  chapterLabel: string
}>()

const emit = defineEmits<{
  (e: 'open'): void
}>()

const truncated = computed(() =>
  props.chapterLabel.length > 10 ? props.chapterLabel.slice(0, 10) + '…' : props.chapterLabel,
)
</script>

<template>
  <button type="button" class="desk-spine" title="章节列表" @click="emit('open')">
    <Icon name="book-open" :size="15" />
    <span v-if="truncated" class="desk-spine__label">{{ truncated }}</span>
  </button>
</template>
