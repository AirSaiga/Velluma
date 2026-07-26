<script setup lang="ts">
/**
 * 大纲板路由页面（V3.1 F1 占位 / F5 实现）。
 *
 * 规格 §3 + §8：卷/弧 → 章节卡的看板视图（卡片列=弧，卡=章节卡）。
 * F1 阶段：占位，仅展示章节列表（平铺，无看板列）。
 * F5 阶段：实现完整的看板拖拽 + 弧管理 + 章节卡编辑。
 */
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import Icon from '../../../components/Icon.vue'
import { useAppStore } from '../../app/useAppStore'
import { useToast } from '../../../composables/useToast'

const route = useRoute()
const router = useRouter()
const store = useAppStore()
const { showToast } = useToast()

// 解构 ref 供模板使用
const currentBook = store.currentBook
const chapters = store.chapters
const sortedChapters = store.sortedChapters

const bookIdFromRoute = computed(() => (route.params.bookId as string) || null)
watch(
  bookIdFromRoute,
  (newBookId) => {
    if (newBookId && newBookId !== store.currentBookId.value) {
      store.selectBook(newBookId)
    }
  },
  { immediate: true }
)

function backToLibrary() {
  router.push({ name: 'library' })
}

function openChapter(chapterId: string) {
  if (bookIdFromRoute.value) {
    router.push({
      name: 'workspace',
      params: { bookId: bookIdFromRoute.value, chapterId },
    })
  }
}

const creating = ref(false)

async function newChapter() {
  // 真正创建章节（store.createChapter 内部走 POST /api/books/{id}/chapters），
  // 成功后跳转写作台并选中新章节
  const bookId = bookIdFromRoute.value || store.currentBookId.value
  if (!bookId) {
    showToast('请先选择一本书', 'warning')
    return
  }
  if (creating.value) return
  creating.value = true
  try {
    const nextNumber =
      chapters.value.reduce((max, c) => Math.max(max, c.chapter_number || 0), 0) + 1
    const chapter = await store.createChapter({
      chapter_number: nextNumber,
      title: `第 ${nextNumber} 章`,
    })
    if (chapter) {
      router.push({
        name: 'workspace',
        params: { bookId, chapterId: chapter.id },
      })
    }
  } catch (e: any) {
    showToast('创建章节失败：' + (e?.message || '未知错误'), 'error')
  } finally {
    creating.value = false
  }
}
</script>

<template>
  <div class="outline-view">
    <header class="outline-header">
      <div class="header-left">
        <button class="icon-btn" @click="backToLibrary" title="返回书架">
          <Icon name="arrow-left" :size="16" />
        </button>
        <div>
          <h1 class="page-title">大纲板</h1>
          <p class="page-subtitle">
            {{ currentBook?.title || '' }} ·
            {{ chapters.length }} 章
          </p>
        </div>
      </div>
      <button class="btn-primary" :disabled="creating || !currentBook" @click="newChapter">
        <Icon name="plus" :size="16" />
        <span>{{ creating ? '创建中…' : '新建章节' }}</span>
      </button>
    </header>

    <div class="outline-body">
      <div v-if="chapters.length === 0" class="empty-state">
        <div class="empty-icon"><Icon name="document" :size="48" /></div>
        <h2>暂无章节</h2>
        <p>新建第一个章节开始规划你的故事。</p>
        <button class="btn-primary" :disabled="creating || !currentBook" @click="newChapter">
          <Icon name="plus" :size="16" />
          <span>{{ creating ? '创建中…' : '新建章节' }}</span>
        </button>
      </div>

      <div v-else class="chapter-cards">
        <p class="hint">
          大纲板看板视图（卷/弧分列 + 拖拽排序）将在 F5 阶段实现。当前为平铺章节列表。
        </p>
        <article
          v-for="ch in sortedChapters"
          :key="ch.id"
          class="chapter-card"
          @click="openChapter(ch.id)"
        >
          <div class="card-header">
            <span class="card-num">第 {{ ch.chapter_number }} 章</span>
            <span v-if="ch.status" class="card-status">{{ ch.status }}</span>
          </div>
          <h3 class="card-title">{{ ch.title || ch.chapter_name || '(未命名)' }}</h3>
          <p v-if="ch.outline_text" class="card-outline">{{ ch.outline_text.slice(0, 120) }}</p>
          <p v-else class="card-outline muted">暂无大纲</p>
        </article>
      </div>
    </div>
  </div>
</template>

<style scoped>
.outline-view {
  height: 100%;
  overflow-y: auto;
  background: var(--bg-primary);
  padding: 1.5rem 2rem;
}

.outline-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 1.5rem;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 0.625rem;
}

.page-title {
  font-family: var(--font-heading);
  font-size: 1.25rem;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0;
}

.page-subtitle {
  font-size: 0.75rem;
  color: var(--text-muted);
  margin: 0.125rem 0 0;
}

.icon-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 1.75rem;
  height: 1.75rem;
  background: transparent;
  border: 1px solid var(--border-color);
  border-radius: 0.25rem;
  color: var(--text-secondary);
  cursor: pointer;
}
.icon-btn:hover {
  background: var(--hover-bg);
}

.btn-primary {
  display: inline-flex;
  align-items: center;
  gap: 0.375rem;
  padding: 0.4375rem 0.875rem;
  font-size: 0.8125rem;
  font-weight: 500;
  background: var(--accent-500);
  color: white;
  border: none;
  border-radius: 0.375rem;
  cursor: pointer;
  transition: background 0.15s ease;
}
.btn-primary:hover {
  background: var(--accent-600);
}
.btn-primary:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.outline-body {
  min-height: 400px;
}

.hint {
  font-size: 0.75rem;
  color: var(--text-muted);
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 0.25rem;
  padding: 0.5rem 0.75rem;
  margin: 0 0 1rem;
}

.chapter-cards {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 0.75rem;
}

.chapter-card {
  background: var(--bg-canvas);
  border: 1px solid var(--border-color);
  border-radius: 0.375rem;
  padding: 0.875rem;
  cursor: pointer;
  transition: all 0.15s ease;
}

.chapter-card:hover {
  border-color: var(--accent-500);
  transform: translateY(-1px);
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 0.375rem;
}

.card-num {
  font-size: 0.6875rem;
  color: var(--text-muted);
  font-variant-numeric: tabular-nums;
}

.card-status {
  font-size: 0.625rem;
  padding: 0.0625rem 0.375rem;
  background: var(--bg-tertiary);
  color: var(--text-secondary);
  border-radius: 0.1875rem;
}

.card-title {
  font-family: var(--font-heading);
  font-size: 0.9375rem;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0 0 0.375rem;
}

.card-outline {
  font-size: 0.75rem;
  color: var(--text-secondary);
  line-height: 1.5;
  margin: 0;
}

.card-outline.muted {
  color: var(--text-muted);
  font-style: italic;
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 3rem 2rem;
  text-align: center;
  color: var(--text-muted);
}

.empty-icon {
  margin-bottom: 1rem;
}

.empty-state h2 {
  font-family: var(--font-heading);
  font-size: 1.125rem;
  font-weight: 500;
  color: var(--text-secondary);
  margin: 0 0 0.375rem;
}

.empty-state p {
  font-size: 0.8125rem;
  margin: 0 0 1.25rem;
}
</style>
