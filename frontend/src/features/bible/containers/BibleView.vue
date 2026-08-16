<script setup lang="ts">
/**
 * 设定中心路由页面（V3.1 F1 新建，规格 §7）。
 *
 * 职责：把旧 AppContainer 右栏的 9 个悬浮 tab 原样迁入此处的二级导航。
 * 左侧二级导航 + 右侧内容区。
 *
 * 编辑入口收敛现状（M4/M5）：
 * - 角色/资产/地图（M4）+ 伏笔账本/期待账本/世界观（M5）已迁往世界页，
 *   对应分区退役为 WorldRedirectCard 跳转卡
 * - 保留分区：文风（StyleCardManager）/ 笔记（NotesPanel）/ 设置（SettingsPanel）
 */
import { ref, computed, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import Icon from '../../../components/Icon.vue'
import StyleCardManager from '../../../components/StyleCardManager.vue'
import NotesPanel from '../../../components/NotesPanel.vue'
import SettingsPanel from '../../../components/SettingsPanel.vue'
import WorldRedirectCard from '../presentation/WorldRedirectCard.vue'
import { useAppStore } from '../../app/useAppStore'

const route = useRoute()
const router = useRouter()
const store = useAppStore()

// 解构出 ref 供模板自动解包
const currentBook = store.currentBook
const currentBookId = store.currentBookId

type SectionKey = 'characters' | 'foreshadowing' | 'readerMirror' | 'worldview' | 'style' | 'assets' | 'map' | 'notes' | 'settings'

interface Section {
  key: SectionKey
  label: string
  icon: string
  ready: boolean
}

const sections: Section[] = [
  { key: 'characters', label: '角色', icon: 'users', ready: true },
  { key: 'foreshadowing', label: '伏笔账本', icon: 'link', ready: true },
  { key: 'readerMirror', label: '期待账本', icon: 'star', ready: true },
  { key: 'worldview', label: '世界观', icon: 'book-open', ready: true },
  { key: 'style', label: '文风', icon: 'sparkles', ready: true },
  { key: 'assets', label: '资产', icon: 'archive', ready: true },
  { key: 'map', label: '地图', icon: 'map-pin', ready: true },
  { key: 'notes', label: '笔记', icon: 'pencil-square', ready: true },
  { key: 'settings', label: '设置', icon: 'settings', ready: true },
]

const activeSection = ref<SectionKey>('characters')

const bookIdFromRoute = computed(() => (route.params.bookId as string) || null)
watch(
  bookIdFromRoute,
  (newBookId) => {
    if (newBookId && newBookId !== currentBookId.value) {
      store.selectBook(newBookId)
    }
  },
  { immediate: true }
)

function backToLibrary() {
  router.push({ name: 'library' })
}

function goWorkspace() {
  if (bookIdFromRoute.value) {
    router.push({ name: 'workspace', params: { bookId: bookIdFromRoute.value } })
  }
}

// NotesPanel 的 saveNotes 回调
// 警示：失败必须向上抛出，否则 NotesPanel 会误显示"已保存"
async function saveBookNotes(notes: string) {
  if (!currentBookId.value) return
  await store.updateBook(currentBookId.value, { global_sys_prompt: notes } as any)
}
</script>

<template>
  <div class="bible-view">
    <aside class="bible-nav">
      <div class="nav-header">
        <button class="icon-btn" @click="backToLibrary" title="返回书架">
          <Icon name="arrow-left" :size="16" />
        </button>
        <span class="nav-title">{{ currentBook?.title || '设定中心' }}</span>
      </div>
      <nav class="nav-list">
        <button
          v-for="s in sections"
          :key="s.key"
          class="nav-item"
          :class="{ active: activeSection === s.key }"
          @click="activeSection = s.key"
        >
          <Icon :name="s.icon" :size="16" class="nav-icon" />
          <span>{{ s.label }}</span>
          <span v-if="!s.ready" class="badge-soon">F4</span>
        </button>
      </nav>
      <button class="nav-footer" @click="goWorkspace">
        <Icon name="pencil-square" :size="16" />
        <span>去写作台</span>
      </button>
    </aside>

    <main class="bible-content">
      <!-- 角色（M4：编辑迁往世界页，分区保留为引导入口） -->
      <div v-if="activeSection === 'characters'" class="panel-host">
        <WorldRedirectCard
          :book-id="bookIdFromRoute || ''"
          icon="users"
          title="角色设定已迁往世界页"
          description="角色档案、关系网络、位置与生死——在世界页的地图与时间轴里编辑；位置与『此刻状态』由事件自动推演，写作辅助直接使用。"
        />
      </div>

      <!-- 伏笔账本（M5：迁往世界页侧栏 + 时间轴弧线带） -->
      <div v-else-if="activeSection === 'foreshadowing'" class="panel-host">
        <WorldRedirectCard
          :book-id="bookIdFromRoute || ''"
          icon="link"
          title="伏笔账本已迁往世界页"
          description="伏笔的埋设与回收在时间轴弧线带上可视化（拖端点改锚）；侧栏「伏笔」分组是全量账本，点击条目开详情编辑。写作页「头顶的线」与 AI 生成自动使用。"
        />
      </div>

      <!-- 期待账本（M5：迁往世界页侧栏「期待」分组） -->
      <div v-else-if="activeSection === 'readerMirror'" class="panel-host">
        <WorldRedirectCard
          :book-id="bookIdFromRoute || ''"
          icon="star"
          title="期待账本已迁往世界页"
          description="读者期待与张力曲线在世界页侧栏「期待」分组里——火候看板/加一把火/收线功能原样保留；写作页「头顶的线」与其同源。"
          :query="{ panel: 'expectations' }"
        />
      </div>

      <!-- 世界观（M5：迁往世界页顶栏「世界观」） -->
      <div v-else-if="activeSection === 'worldview'" class="panel-host">
        <WorldRedirectCard
          :book-id="bookIdFromRoute || ''"
          icon="book-open"
          title="世界观已迁往世界页"
          description="世界背景、规则、历史——在世界页顶栏「世界观」里编辑（自动保存 + 导入导出），写作时自动注入 AI 生成上下文。"
          :query="{ panel: 'worldview' }"
        />
      </div>

      <!-- 文风 -->
      <div v-else-if="activeSection === 'style'" class="panel-host">
        <StyleCardManager :book-id="bookIdFromRoute" :genre="currentBook?.genre" :closable="false" />
      </div>

      <!-- 资产（M4：编辑迁往世界页） -->
      <div v-else-if="activeSection === 'assets'" class="panel-host">
        <WorldRedirectCard
          :book-id="bookIdFromRoute || ''"
          icon="star"
          title="资产设定已迁往世界页"
          description="资产的固有属性在世界页的实体档案里编辑；持有与转移由事件记录，写作辅助自动使用。"
        />
      </div>

      <!-- 地图（M4：编辑迁往世界页） -->
      <div v-else-if="activeSection === 'map'" class="panel-host">
        <WorldRedirectCard
          :book-id="bookIdFromRoute || ''"
          icon="map-pin"
          title="地图已迁往世界页"
          description="地点、疆域、移动路径与底图拼贴——在世界页的地图画布里绘制；章节叙事时刻的世界状态自动推演。"
        />
      </div>

      <!-- 笔记 -->
      <div v-else-if="activeSection === 'notes'" class="panel-host">
        <NotesPanel :book="currentBook" :save-notes="saveBookNotes" :closable="false" />
      </div>

      <!-- 设置 -->
      <div v-else-if="activeSection === 'settings'" class="panel-host">
        <SettingsPanel />
      </div>
    </main>
  </div>
</template>

<style scoped>
.bible-view {
  display: flex;
  width: 100%;
  height: 100%;
  overflow: hidden;
  background: var(--bg-primary);
}

.bible-nav {
  display: flex;
  flex-direction: column;
  width: 200px;
  flex-shrink: 0;
  background: var(--bg-secondary);
  border-right: 1px solid var(--border-color);
}

.nav-header {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  padding: 0.625rem 0.75rem;
  border-bottom: 1px solid var(--border-color);
}

.nav-title {
  flex: 1;
  font-size: 0.8125rem;
  font-weight: 600;
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.icon-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 1.75rem;
  height: 1.75rem;
  background: transparent;
  border: none;
  border-radius: 0.25rem;
  color: var(--text-secondary);
  cursor: pointer;
  transition: all 0.15s ease;
}
.icon-btn:hover {
  background: var(--hover-bg);
  color: var(--text-primary);
}

.nav-list {
  flex: 1;
  overflow-y: auto;
  padding: 0.5rem 0.375rem;
  display: flex;
  flex-direction: column;
  gap: 0.125rem;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  width: 100%;
  padding: 0.4375rem 0.625rem;
  background: transparent;
  border: none;
  border-radius: 0.25rem;
  font-size: 0.8125rem;
  color: var(--text-secondary);
  text-align: left;
  cursor: pointer;
  transition: all 0.15s ease;
}

.nav-item:hover {
  background: var(--hover-bg);
  color: var(--text-primary);
}

.nav-item.active {
  background: var(--hover-bg);
  color: var(--accent-500);
  font-weight: 500;
}

.nav-icon {
  flex-shrink: 0;
  opacity: 0.8;
}

.badge-soon {
  margin-left: auto;
  font-size: 0.625rem;
  padding: 0.0625rem 0.3125rem;
  background: var(--bg-tertiary);
  color: var(--text-muted);
  border-radius: 0.1875rem;
  letter-spacing: 0.02em;
}

.nav-footer {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0.375rem;
  margin: 0.5rem;
  padding: 0.5rem;
  background: var(--accent-500);
  color: white;
  border: none;
  border-radius: 0.25rem;
  font-size: 0.75rem;
  font-weight: 500;
  cursor: pointer;
  transition: background 0.15s ease;
}

.nav-footer:hover {
  background: var(--accent-600);
}

.bible-content {
  flex: 1;
  min-width: 0;
  height: 100%;
  overflow: auto;
  background: var(--bg-canvas);
}

.panel-host {
  height: 100%;
  overflow: auto;
}

.empty-section {
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  color: var(--text-muted);
  padding: 2rem;
}

.empty-icon {
  margin-bottom: 1rem;
}

.empty-section h2 {
  font-family: var(--font-heading);
  font-size: 1.125rem;
  font-weight: 500;
  color: var(--text-secondary);
  margin: 0 0 0.5rem;
}

.empty-section p {
  font-size: 0.8125rem;
  line-height: 1.7;
  margin: 0;
}
</style>
