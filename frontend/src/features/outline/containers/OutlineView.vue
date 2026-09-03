<script setup lang="ts">
/**
 * 大纲板路由页面（方案 A · 故事线俯视板，2026-09-03 重写）。
 *
 * 书级规划面：一根章号轴俯视全书（张力折线/伏笔弧线/真相揭示朱点），
 * 下方章卡纵列承载每章规划（打算/关键情节进度/伏笔埋收/大纲就地编辑）。
 * 编辑只碰规划层——正文永远回写作台写（画布即事实源不变）；
 * 与世界页时间轴正交：那边按世界时间排设定事实，这边按章号排叙事节奏。
 */
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import Icon from '../../../components/Icon.vue'
import { useAppStore } from '../../app/useAppStore'
import { useToast } from '../../../composables/useToast'
import { useStoryline } from '../composables/useStoryline'
import {
  alignTensionSamples,
  anchorProgress,
  buildStoryArcs,
  chapterMarks,
  spineIntentText,
} from '../engine/storyline'
import StorylineAxis from '../presentation/StorylineAxis.vue'
import ChapterCard, { type ChapterCardData } from '../presentation/ChapterCard.vue'

const route = useRoute()
const router = useRouter()
const store = useAppStore()
const { showToast } = useToast()

const currentBook = store.currentBook
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

// ===== 数据聚合（spine/伏笔/张力/真相 四路并行）=====

const chapterIds = computed(() => sortedChapters.value.map((c) => c.id))
const { spines, ledgers, tensionSamples, reveals } = useStoryline(bookIdFromRoute, chapterIds)

const numberById = computed(() => {
  const m = new Map<string, number>()
  sortedChapters.value.forEach((c) => m.set(c.id, c.chapter_number))
  return m
})
const validNumbers = computed(() => new Set(sortedChapters.value.map((c) => c.chapter_number)))

const arcs = computed(() => buildStoryArcs(ledgers.value, numberById.value, validNumbers.value))
const tensionAligned = computed(() => alignTensionSamples(tensionSamples.value, validNumbers.value))

const openArcCount = computed(() => arcs.value.filter((a) => !a.resolved).length)
const revealTotal = computed(() => {
  let n = 0
  for (const labels of reveals.value.values()) n += labels.length
  return n
})

const axisChapters = computed(() =>
  sortedChapters.value.map((c) => ({
    id: c.id,
    number: c.chapter_number,
    title: c.title || c.chapter_name || '',
  }))
)

const cards = computed<ChapterCardData[]>(() =>
  sortedChapters.value.map((c) => {
    const n = c.chapter_number
    const spine = spines.value[c.id] ?? null
    const prog = anchorProgress(spine)
    const marks = chapterMarks(arcs.value, n)
    return {
      id: c.id,
      number: n,
      title: c.title || c.chapter_name || '',
      status: c.status,
      wordCount: c.word_count ?? 0,
      outline: c.outline_text || '',
      intentText: spineIntentText(spine),
      anchorDone: prog.done,
      anchorTotal: prog.total,
      revealLabels: reveals.value.get(n) ?? [],
      planted: marks.planted,
      resolved: marks.resolved,
    }
  })
)

// ===== 大纲就地编辑（2s 防抖落盘；失焦/收起立即冲账）=====

const expandedId = ref<string | null>(null)
const draft = ref('')
const saveState = ref<'idle' | 'saving' | 'saved' | 'error'>('idle')
let saveTimer: ReturnType<typeof setTimeout> | null = null

function currentOutlineOf(chapterId: string): string {
  return sortedChapters.value.find((c) => c.id === chapterId)?.outline_text || ''
}

async function flushSave() {
  if (!expandedId.value) return
  if (draft.value === currentOutlineOf(expandedId.value)) return
  const id = expandedId.value
  const text = draft.value
  if (saveTimer) {
    clearTimeout(saveTimer)
    saveTimer = null
  }
  saveState.value = 'saving'
  try {
    await store.updateChapter(id, { outline_text: text })
    if (expandedId.value === id && draft.value === text) saveState.value = 'saved'
  } catch (e: any) {
    saveState.value = 'error'
    showToast('大纲保存失败：' + (e?.message || '未知错误'), 'error')
  }
}

function onDraftInput(text: string) {
  draft.value = text
  if (saveState.value !== 'idle') saveState.value = 'idle'
  if (saveTimer) clearTimeout(saveTimer)
  saveTimer = setTimeout(() => {
    saveTimer = null
    flushSave()
  }, 2000)
}

function toggleEdit(ch: ChapterCardData) {
  if (expandedId.value === ch.id) {
    flushSave()
    expandedId.value = null
    return
  }
  flushSave()
  expandedId.value = ch.id
  draft.value = ch.outline
  saveState.value = 'idle'
}

onBeforeUnmount(() => {
  if (saveTimer) clearTimeout(saveTimer)
  flushSave()
})

// ===== 导航 =====

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

function seekChapter(chapterId: string) {
  // 瞬时滚动：smooth 依赖 rAF，窗口被遮挡/节流时会被冻结成不滚动
  document.getElementById(`oc-${chapterId}`)?.scrollIntoView({ block: 'center' })
}

const creating = ref(false)

async function newChapter() {
  const bookId = bookIdFromRoute.value || store.currentBookId.value
  if (!bookId) {
    showToast('请先选择一本书', 'warning')
    return
  }
  if (creating.value) return
  creating.value = true
  try {
    const nextNumber =
      sortedChapters.value.reduce((max, c) => Math.max(max, c.chapter_number || 0), 0) + 1
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
            {{ currentBook?.title || '' }} · {{ sortedChapters.length }} 章
            <template v-if="openArcCount">· {{ openArcCount }} 条伏笔未收</template>
            <template v-if="revealTotal">· {{ revealTotal }} 处待揭真相</template>
          </p>
        </div>
      </div>
      <button class="btn-primary" :disabled="creating || !currentBook" @click="newChapter">
        <Icon name="plus" :size="16" />
        <span>{{ creating ? '创建中…' : '新建章节' }}</span>
      </button>
    </header>

    <div class="outline-body">
      <div v-if="sortedChapters.length === 0" class="empty-state">
        <div class="empty-icon"><Icon name="document" :size="48" /></div>
        <h2>暂无章节</h2>
        <p>新建第一个章节开始规划你的故事。</p>
        <button class="btn-primary" :disabled="creating || !currentBook" @click="newChapter">
          <Icon name="plus" :size="16" />
          <span>{{ creating ? '创建中…' : '新建章节' }}</span>
        </button>
      </div>

      <template v-else>
        <StorylineAxis
          :chapters="axisChapters"
          :arcs="arcs"
          :tension="tensionAligned"
          :reveals="reveals"
          @seek="seekChapter"
        />
        <div class="chapter-list">
          <ChapterCard
            v-for="card in cards"
            :key="card.id"
            :chapter="card"
            :editing="expandedId === card.id"
            :draft="expandedId === card.id ? draft : ''"
            :save-state="expandedId === card.id ? saveState : 'idle'"
            @open="openChapter(card.id)"
            @toggle-edit="toggleEdit(card)"
            @draft-input="onDraftInput"
            @draft-blur="flushSave"
          />
        </div>
      </template>
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
  margin-bottom: 1.25rem;
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

.chapter-list {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  max-width: 60rem;
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
