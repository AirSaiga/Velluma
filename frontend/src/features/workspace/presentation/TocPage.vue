<script setup lang="ts">
/**
 * 目录页（08 期 §4.4，无选中章时的纸面本体，取代旧 empty-editor 空态）。
 *
 * 纸面几何与章页完全同构（880 居中、同 pt/pb）——翻页不换桌子。
 * 纸上内容全部衬线居中轴：书名大标题 + 「目录」副行 + 章节条目（page 变体）
 * + 「＋ 新起一章」+ 纸底导入入口。多选删除在目录页不提供（管理动作归目录抽屉）。
 */
import Icon from '../../../components/Icon.vue'
import ChapterTocList from './ChapterTocList.vue'
import type { Chapter } from '../../../types'

defineProps<{
  bookTitle: string
  chapters: Chapter[]
  loading: boolean
}>()

const emit = defineEmits<{
  (e: 'select', ch: Chapter): void
  (e: 'create'): void
  (e: 'import'): void
}>()
</script>

<template>
  <div class="toc-host">
    <div class="toc-page">
      <header class="toc-page__head">
        <h1 class="toc-page__title">{{ bookTitle || '未选择书籍' }}</h1>
        <div class="toc-page__sub">目录</div>
      </header>

      <div v-if="loading" class="toc-page__loading">加载中…</div>

      <template v-else>
        <!-- 零章节书 -->
        <div v-if="chapters.length === 0" class="toc-page__empty">
          <p class="toc-page__empty-text">这本书还没有章节</p>
          <button class="toc-page__primary" @click="emit('create')">
            <Icon name="plus" :size="15" />
            <span>新起第一章</span>
          </button>
        </div>

        <template v-else>
          <div class="toc-page__list">
            <ChapterTocList
              variant="page"
              :chapters="chapters"
              @select="(ch) => emit('select', ch)"
            />
          </div>
          <div class="toc-page__new-row">
            <button class="toc-page__new" @click="emit('create')">＋ 新起一章</button>
          </div>
        </template>

        <div class="toc-page__foot">
          <button class="toc-page__import" @click="emit('import')">从 .md 文件批量导入章节</button>
        </div>
      </template>
    </div>
  </div>
</template>

<style scoped>
/* 与章页纸列同构的外壳（ChapterEditorView 根同款内边距） */
.toc-host {
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  padding: 1.25rem 1.25rem;
  flex: 1;
  min-height: 0;
}

.toc-page__head {
  flex-shrink: 0;
  text-align: center;
  padding: var(--space-8) var(--space-6) var(--space-4);
}

.toc-page__title {
  font-family: var(--font-heading);
  font-size: var(--text-3xl);
  font-weight: 600;
  color: var(--text-primary);
  letter-spacing: 0.04em;
  margin: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.toc-page__sub {
  margin-top: var(--space-2);
  font-size: var(--text-sm);
  color: var(--text-muted);
  letter-spacing: 0.3em;
}

.toc-page__loading {
  padding: var(--space-6);
  text-align: center;
  font-size: var(--text-sm);
  color: var(--text-muted);
}

.toc-page__list {
  flex: 1;
  min-height: 0;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.toc-page__new-row {
  flex-shrink: 0;
  padding: 0 var(--space-6);
}

.toc-page__new {
  width: 100%;
  padding: 0.5rem;
  background: transparent;
  border: 1px dashed var(--border-color);
  border-radius: var(--radius-sm);
  font-size: var(--text-base);
  color: var(--text-secondary);
  cursor: pointer;
  transition: all 0.15s ease;
}
.toc-page__new:hover {
  border-color: var(--accent-500);
  color: var(--accent-500);
}

.toc-page__empty {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--space-4);
  padding: var(--space-6);
}

.toc-page__empty-text {
  font-family: var(--font-heading);
  font-size: var(--text-lg);
  color: var(--text-secondary);
  margin: 0;
}

.toc-page__primary {
  display: inline-flex;
  align-items: center;
  gap: 0.375rem;
  padding: 0.5rem 1.25rem;
  font-size: var(--text-base);
  font-weight: 500;
  background: var(--accent-500);
  color: #fff;
  border: none;
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: background 0.15s ease;
}
.toc-page__primary:hover {
  background: var(--accent-600);
}

.toc-page__foot {
  flex-shrink: 0;
  padding: var(--space-4) 0 var(--space-2);
  text-align: center;
}

.toc-page__import {
  background: none;
  border: none;
  padding: 0.25rem 0.5rem;
  font-size: var(--text-xs);
  color: var(--text-faint);
  cursor: pointer;
  transition: color 0.15s ease;
}
.toc-page__import:hover {
  color: var(--text-secondary);
}
</style>
