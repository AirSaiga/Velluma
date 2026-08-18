<script setup lang="ts">
/**
 * 应用栏（App Rail，V3.1 F1 新建，规格 §3）。
 *
 * 左侧窄应用栏，图标 + 文字导航五个顶层目的地。
 * - 规格要求 chrome 界面零 emoji，统一用 Icon.vue 一套图标。
 * - 当前活跃目的地高亮（accent 色）。
 * - 无书时进入书架；选了书后其余目的地才可用。
 */
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import Icon from '../../../components/Icon.vue'
import { useAppStore } from '../useAppStore'
import { useAppSettings } from '../../../composables/useAppSettings'

const route = useRoute()
const router = useRouter()
const store = useAppStore()
const { open: openSettings } = useAppSettings()

interface RailItem {
  key: string
  label: string
  icon: string
  /** 无书时禁用 */
  requiresBook: boolean
}

const railItems: RailItem[] = [
  { key: 'library', label: '书架', icon: 'book', requiresBook: false },
  { key: 'workspace', label: '写作台', icon: 'pencil-square', requiresBook: true },
  { key: 'outline', label: '大纲', icon: 'document', requiresBook: true },
  { key: 'bible', label: '设定', icon: 'book-open', requiresBook: true },
  { key: 'world', label: '世界', icon: 'map', requiresBook: true },
  { key: 'style', label: '文风', icon: 'paint-brush', requiresBook: true },
  { key: 'insights', label: '数据', icon: 'sparkles', requiresBook: true },
]

const activeKey = computed(() => (route.meta.railKey as string) || null)
const hasBook = computed(() => !!store.currentBookId.value)

function navigate(item: RailItem) {
  if (item.requiresBook && !hasBook.value) return
  if (item.key === 'library') {
    router.push({ name: 'library' })
    return
  }
  if (!store.currentBookId.value) return
  if (item.key === 'workspace') {
    router.push({
      name: 'workspace',
      params: {
        bookId: store.currentBookId.value,
        chapterId: store.selectedChapterId.value || undefined,
      },
    })
  } else {
    router.push({ name: item.key, params: { bookId: store.currentBookId.value } })
  }
}
</script>

<template>
  <nav class="app-rail" aria-label="主导航">
    <button
      v-for="item in railItems"
      :key="item.key"
      class="rail-item"
      :class="{
        'active': activeKey === item.key,
        'disabled': item.requiresBook && !hasBook,
      }"
      :title="item.requiresBook && !hasBook ? `${item.label}（需先选择书籍）` : item.label"
      :aria-current="activeKey === item.key ? 'page' : undefined"
      :disabled="item.requiresBook && !hasBook"
      @click="navigate(item)"
    >
      <Icon :name="item.icon" :size="20" class="rail-icon" />
      <span class="rail-label">{{ item.label }}</span>
    </button>

    <div class="rail-spacer"></div>

    <!-- 全局设置（应用级配置，非导航目的地，无书亦可达） -->
    <button class="rail-item" title="设置" @click="openSettings">
      <Icon name="settings" :size="20" class="rail-icon" />
      <span class="rail-label">设置</span>
    </button>
  </nav>
</template>

<style scoped>
.app-rail {
  display: flex;
  flex-direction: column;
  gap: 0.125rem;
  width: 3.5rem;
  flex-shrink: 0;
  padding: 0.5rem 0.25rem;
  background: var(--bg-tertiary);
  border-right: 1px solid var(--border-color);
  overflow: hidden;
}

.rail-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.125rem;
  padding: 0.5rem 0.25rem;
  border: none;
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  border-radius: 0.375rem;
  transition: background-color 0.15s ease, color 0.15s ease;
  position: relative;
}

.rail-item:hover:not(.disabled) {
  background: var(--hover-bg);
  color: var(--text-primary);
}

.rail-item.active {
  color: var(--accent-500);
  background: var(--hover-bg);
}

.rail-item.active::before {
  content: '';
  position: absolute;
  left: -0.25rem;
  top: 25%;
  bottom: 25%;
  width: 2px;
  background: var(--accent-500);
  border-radius: 0 1px 1px 0;
}

.rail-item.disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.rail-icon {
  flex-shrink: 0;
}

.rail-spacer {
  flex: 1;
}

.rail-label {
  font-size: 9px;
  line-height: 1;
  letter-spacing: 0.02em;
  white-space: nowrap;
}
</style>
