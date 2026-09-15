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
const {
  open: openSettings,
  openApi: openApiSettings,
  toggleAppearance,
  appearanceVisible,
} = useAppSettings()

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
      <Icon :name="item.icon" :size="18" class="rail-icon" />
      <span class="rail-label">{{ item.label }}</span>
    </button>

    <div class="rail-spacer"></div>

    <!-- 底部工具簇（2026-09-15 设置拆分：外观抽屉 + 模型与 API 弹窗 + 通用设置；
         均为应用级配置，非导航目的地，无书亦可达） -->
    <button
      class="rail-item"
      :class="{ active: appearanceVisible }"
      title="外观（主题/明暗/背景/排版，即时生效）"
      @click="toggleAppearance"
    >
      <Icon name="sun" :size="18" class="rail-icon" />
      <span class="rail-label">外观</span>
    </button>
    <button class="rail-item" title="模型与 API（Key/厂商/预设/向量/代理）" @click="openApiSettings">
      <Icon name="bolt" :size="18" class="rail-icon" />
      <span class="rail-label">API</span>
    </button>
    <button class="rail-item" title="设置（通知偏好）" @click="openSettings">
      <Icon name="settings" :size="18" class="rail-icon" />
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

/* N1 §3.9：仪器密度——项高 40（4+18+2+12+4=40）、icon 18（模板）、label 12/500 */
.rail-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.125rem;
  padding: 0.25rem 0.25rem;
  border: none;
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  border-radius: var(--radius-sm);
  transition: background-color var(--dur-2) var(--ease-out), color var(--dur-2) var(--ease-out);
  position: relative;
}

.rail-item:hover:not(.disabled) {
  background: var(--state-hover);
  color: var(--text-primary);
}

/* P1 §8.7：激活态= pill（--state-selected 底 + accent 文字/图标），
   不再是实底色块；左缘 accent 小条保留（rail 既有记号） */
.rail-item.active {
  color: var(--accent-500);
  background: var(--state-selected);
  border-radius: var(--radius-md);
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
  font-size: var(--text-xs);
  font-weight: 500;
  line-height: 1;
  letter-spacing: var(--tracking-label);
  white-space: nowrap;
}
</style>
