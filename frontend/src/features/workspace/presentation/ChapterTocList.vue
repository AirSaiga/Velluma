<script setup lang="ts">
/**
 * 章节行列表（08 期 §4.3 共享行组件）——目录抽屉与目录页共用一份行结构，
 * 杜绝双份漂移。行 = 序号 + 标题 + ChapterBadges + hover 删除钮（page 变体无删除/无多选）。
 * 行结构照抄旧 binder 行；样式自 WorkspaceView scoped 迁入（binder 全家已退役）。
 */
import Icon from '../../../components/Icon.vue'
import ChapterBadges from './ChapterBadges.vue'
import type { Chapter } from '../../../types'

withDefaults(defineProps<{
  chapters: Chapter[]
  selectedChapterId?: string | null
  selectMode?: boolean
  checkedIds?: Set<string>
  /** page=目录页（行高放宽、无管理动作）；drawer=目录抽屉（全量行交互） */
  variant?: 'page' | 'drawer'
}>(), {
  selectedChapterId: null,
  selectMode: false,
  checkedIds: () => new Set<string>(),
  variant: 'drawer',
})

const emit = defineEmits<{
  (e: 'select', ch: Chapter, ev: MouseEvent | KeyboardEvent): void
  (e: 'delete', ch: Chapter): void
}>()
</script>

<template>
  <div class="toc-list" :class="`toc-list--${variant}`">
    <div
      v-for="ch in chapters"
      :key="ch.id"
      class="chapter-item"
      :class="{ active: !selectMode && ch.id === selectedChapterId, checked: selectMode && checkedIds.has(ch.id) }"
      role="button"
      tabindex="0"
      @click="emit('select', ch, $event)"
      @keydown.enter="emit('select', ch, $event)"
    >
      <!-- 多选模式：复选框 -->
      <span v-if="selectMode" class="select-checkbox" :class="{ checked: checkedIds.has(ch.id) }">
        <Icon v-if="checkedIds.has(ch.id)" name="check" :size="12" />
      </span>
      <span class="ch-num">{{ ch.chapter_number }}</span>
      <span class="ch-name">{{ ch.title || ch.chapter_name || '(未命名)' }}</span>
      <ChapterBadges v-if="!selectMode" :chapter="ch" />
      <button
        v-if="!selectMode && variant === 'drawer'"
        class="ch-delete"
        title="删除章节"
        @click.stop="emit('delete', ch)"
      >
        <Icon name="trash" :size="12" />
      </button>
    </div>
  </div>
</template>

<style scoped>
.toc-list {
  flex: 1;
  overflow-y: auto;
  padding: 0.375rem;
  display: flex;
  flex-direction: column;
  gap: 0.125rem;
}

.chapter-item {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  width: 100%;
  padding: 0.4375rem 0.5rem;
  background: transparent;
  border: none;
  border-radius: var(--radius-xs);
  text-align: left;
  cursor: pointer;
  transition: background var(--dur-2) var(--ease-out);
}

.chapter-item:hover {
  background: var(--state-hover);
}

.chapter-item.active {
  background: var(--state-hover);
}

.chapter-item.checked {
  background: color-mix(in srgb, var(--accent-500) 8%, transparent);
}

/* 复选框（与目录抽屉全选栏同款） */
.select-checkbox {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 1rem;
  height: 1rem;
  border: 1.5px solid var(--border-color);
  border-radius: var(--radius-xs);
  background: var(--bg-canvas);
  color: var(--bg-canvas);
  flex-shrink: 0;
  transition: all var(--dur-2) var(--ease-out);
}

.select-checkbox.checked {
  border-color: var(--accent-500);
  background: var(--accent-500);
}

.ch-num {
  font-size: var(--text-xs);
  color: var(--text-muted);
  font-variant-numeric: tabular-nums;
  flex-shrink: 0;
  min-width: 1.25rem;
}

.chapter-item.active .ch-num {
  color: var(--accent-500);
  font-weight: 600;
}

.ch-name {
  flex: 1;
  font-size: 0.75rem;
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.chapter-item.active .ch-name {
  color: var(--accent-500);
  font-weight: 500;
}

.ch-delete {
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 1.25rem;
  height: 1.25rem;
  padding: 0;
  background: transparent;
  border: none;
  border-radius: var(--radius-xs);
  color: var(--text-muted);
  cursor: pointer;
  opacity: 0;
  transition: opacity var(--dur-2) var(--ease-out), color var(--dur-2) var(--ease-out), background var(--dur-2) var(--ease-out);
}

.chapter-item:hover .ch-delete,
.chapter-item:focus-within .ch-delete {
  opacity: 1;
}

.ch-delete:hover {
  color: var(--danger);
  background: var(--danger-bg);
}

/* ---- page 变体（目录页 §4.4）：行高放宽至 2.4rem，标题左对齐，徽标同行 ---- */
.toc-list--page {
  padding: 0 var(--space-6);
}
/* 04 §A3-3 目录页章号=页码感衬线（仅 page 变体；抽屉变体保持紧凑无衬线） */
.toc-list--page .ch-num {
  font-family: var(--font-heading);
  color: var(--text-faint);
}

.toc-list--page .chapter-item {
  min-height: 2.4rem;
  padding: 0.375rem 0.5rem;
}

.toc-list--page .ch-name {
  font-size: var(--text-md);
}
</style>
