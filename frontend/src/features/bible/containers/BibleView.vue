<script setup lang="ts">
/**
 * 设定中心路由页面（V3.1 F1 新建，规格 §7）。
 *
 * 职责：把旧 AppContainer 右栏的 9 个悬浮 tab 原样迁入此处的二级导航。
 * 左侧二级导航 + 右侧内容区。
 *
 * 二级分区（规格 §7）：
 * - 角色（CharacterPanel）
 * - 伏笔账本（F4 新建，F1 占位"开发中"）
 * - 世界观（WorldviewSettings）
 * - 文风（StyleCardManager）
 * - 资产（AssetPanel）
 * - 地图（MapSettings）
 * - 笔记（NotesPanel）
 * - 设置（SettingsPanel）
 *
 * F1 阶段：各面板原样复用旧组件（分层违规留待 F5 清零），保证功能不丢。
 */
import { ref, computed, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import Icon from '../../../components/Icon.vue'
import CharacterPanel from '../../../components/CharacterPanel.vue'
import WorldviewSettings from '../../../components/WorldviewSettings.vue'
import StyleCardManager from '../../../components/StyleCardManager.vue'
import MapSettings from '../../../components/MapSettings.vue'
import NotesPanel from '../../../components/NotesPanel.vue'
import SettingsPanel from '../../../components/SettingsPanel.vue'
import ForeshadowingPanel from './ForeshadowingPanel.vue'
import ReaderMirrorPanel from './ReaderMirrorPanel.vue'
import { AssetPanel } from '../../asset-panel'
import { useAppStore } from '../../app/useAppStore'
import { characterApi, relationshipApi } from '../../../services/api'
import { useToast } from '../../../composables/useToast'

const route = useRoute()
const router = useRouter()
const store = useAppStore()
const { showToast } = useToast()

// 解构出 ref 供模板自动解包
const characters = store.characters
const relationships = store.relationships
const currentBook = store.currentBook
const currentBookId = store.currentBookId
const selectedChapter = store.selectedChapter
const selectedChapterId = store.selectedChapterId

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

async function refreshCharacters() {
  try {
    await store.refreshCharacters()
  } catch (e: any) {
    showToast('加载角色失败：' + (e?.message || '未知错误'), 'error')
  }
}

// 角色管理回调：CharacterPanel 只负责收集表单并上抛事件，真实 API 调用在这里完成。
// 副作用：成功后刷新列表；onDone 回调是 CharacterPanel 关闭抽屉的唯一触发点，必须调用。
async function onCreateCharacter(data: any, onDone?: (ok: boolean) => void) {
  if (!currentBookId.value) {
    showToast('请先选择一本书籍', 'warning')
    onDone?.(false)
    return
  }
  try {
    await characterApi.create({ ...data, book_id: currentBookId.value })
    await refreshCharacters()
    onDone?.(true)
  } catch (e: any) {
    showToast('创建角色失败: ' + (e?.message || '未知错误'), 'error')
    onDone?.(false)
  }
}
async function onUpdateCharacter(id: string, data: any, onDone?: (ok: boolean) => void) {
  try {
    await characterApi.update(id, data)
    await refreshCharacters()
    onDone?.(true)
  } catch (e: any) {
    showToast('更新角色失败: ' + (e?.message || '未知错误'), 'error')
    onDone?.(false)
  }
}
async function onDeleteCharacter(id: string) {
  try {
    await characterApi.delete(id)
    await refreshCharacters()
  } catch (e: any) {
    showToast('删除角色失败: ' + (e?.message || '未知错误'), 'error')
  }
}
// 注意：store.refreshCharacters 只刷新角色不刷新关系，这里直接本地更新 relationships 列表。
async function onCreateRelationship(data: any) {
  if (!currentBookId.value) {
    showToast('请先选择一本书籍', 'warning')
    return
  }
  try {
    const newRel = await relationshipApi.create({ ...data, book_id: currentBookId.value })
    relationships.value.push(newRel)
  } catch (e: any) {
    showToast('创建关系失败: ' + (e?.message || '未知错误'), 'error')
  }
}
async function onUpdateRelationship(id: string, data: any) {
  try {
    const updated = await relationshipApi.update(id, data)
    const index = relationships.value.findIndex((r: any) => r.id === id)
    if (index !== -1) relationships.value[index] = updated
  } catch (e: any) {
    showToast('更新关系失败: ' + (e?.message || '未知错误'), 'error')
  }
}
async function onDeleteRelationship(id: string) {
  try {
    await relationshipApi.delete(id)
    relationships.value = relationships.value.filter((r: any) => r.id !== id)
  } catch (e: any) {
    showToast('删除关系失败: ' + (e?.message || '未知错误'), 'error')
  }
}

// MapSettings 的活动范围保存（emit update-chapter）
async function onUpdateChapter(id: string, data: any) {
  try {
    await store.updateChapter(id, data)
  } catch (e) {
    console.error('[Bible] 更新章节失败', e)
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
      <!-- 角色 -->
      <div v-if="activeSection === 'characters'" class="panel-host">
        <CharacterPanel
          :characters="characters"
          :relationships="relationships"
          :selected-chapter-id="selectedChapterId"
          :closable="false"
          @create-character="onCreateCharacter"
          @update-character="onUpdateCharacter"
          @delete-character="onDeleteCharacter"
          @create-relationship="onCreateRelationship"
          @update-relationship="onUpdateRelationship"
          @delete-relationship="onDeleteRelationship"
        />
      </div>

      <!-- 伏笔账本 -->
      <div v-else-if="activeSection === 'foreshadowing'" class="panel-host">
        <ForeshadowingPanel :book-id="bookIdFromRoute || ''" />
      </div>

      <!-- V4.2 期待账本（Reader Mirror） -->
      <div v-else-if="activeSection === 'readerMirror'" class="panel-host">
        <ReaderMirrorPanel :book-id="bookIdFromRoute || ''" />
      </div>

      <!-- 世界观 -->
      <div v-else-if="activeSection === 'worldview'" class="panel-host">
        <WorldviewSettings :book-id="bookIdFromRoute" :closable="false" />
      </div>

      <!-- 文风 -->
      <div v-else-if="activeSection === 'style'" class="panel-host">
        <StyleCardManager :book-id="bookIdFromRoute" :genre="currentBook?.genre" :closable="false" />
      </div>

      <!-- 资产 -->
      <div v-else-if="activeSection === 'assets'" class="panel-host">
        <AssetPanel :book-id="bookIdFromRoute || ''" :closable="false" />
      </div>

      <!-- 地图 -->
      <div v-else-if="activeSection === 'map'" class="panel-host">
        <MapSettings :chapter="selectedChapter" :closable="false" @update-chapter="onUpdateChapter" />
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
