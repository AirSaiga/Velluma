<script setup lang="ts">
/**
 * V3.5 场景设定面板（独立二级 tab）。
 *
 * 职责：章级显式指定本章的出场角色、场景地点、关键资产。
 * 生成时由后端 SettingResolver 召回注入 prompt。
 *
 * 数据通道：
 * - 角色：ChapterEntity 关联表（经 store.updateChapter character_ids）
 * - 地点：ChapterMapLocation 关联表（mapApi）
 * - 资产：ChapterAsset 关联表（assetApi）
 */
import { ref, watch } from 'vue'
import { useAppStore } from '../../app/useAppStore'
import { mapApi, chapterApi } from '../../../services/api/domain'
import { assetApi } from '../../../services/api/domain/asset.api'

const props = defineProps<{
  chapterId: string | null
}>()

const store = useAppStore()
const characters = store.characters
const selectedChapter = store.selectedChapter
const currentBookId = store.currentBookId

const allLocations = ref<any[]>([])
const allAssets = ref<any[]>([])
const selectedLocationIds = ref<string[]>([])
const selectedAssetIds = ref<string[]>([])
const loading = ref(false)

// 加载书级地点/资产库 + 本章已关联项
async function loadSettings(chapterId: string) {
  if (!chapterId) return
  loading.value = true
  try {
    const bookId = currentBookId.value
    if (bookId) {
      const [locs, assets] = await Promise.all([
        mapApi.getLocations(bookId),
        assetApi.getAll(bookId),
      ])
      allLocations.value = locs || []
      allAssets.value = assets || []
    }
    const [chapterLocs, chapterAssets] = await Promise.all([
      mapApi.getChapterLocations(chapterId),
      assetApi.getChapterAssets(chapterId),
    ])
    selectedLocationIds.value = (chapterLocs || []).map((cl: any) => cl.location_id)
    selectedAssetIds.value = (chapterAssets || []).map((ca: any) => ca.asset_id)
  } catch (e) {
    console.warn('[SceneSettings] 加载失败', e)
  } finally {
    loading.value = false
  }
}

// 角色勾选（经 store.updateChapter character_ids 通道）
function toggleCharacter(charId: string) {
  if (!selectedChapter.value) return
  const ids = ((selectedChapter.value as any).character_ids || []).slice()
  const idx = ids.indexOf(charId)
  if (idx >= 0) {
    ids.splice(idx, 1)
  } else {
    ids.push(charId)
  }
  store.updateChapter(selectedChapter.value.id, { character_ids: ids })
}

function isCharacterSelected(charId: string): boolean {
  return ((selectedChapter.value as any)?.character_ids || []).includes(charId)
}

// 地点勾选
async function toggleLocation(locId: string) {
  if (!props.chapterId) return
  const idx = selectedLocationIds.value.indexOf(locId)
  if (idx >= 0) {
    selectedLocationIds.value.splice(idx, 1)
    await mapApi.removeLocationFromChapter(props.chapterId, locId)
  } else {
    selectedLocationIds.value.push(locId)
    await mapApi.addLocationToChapter(props.chapterId, locId)
  }
}

function isLocationSelected(locId: string): boolean {
  return selectedLocationIds.value.includes(locId)
}

// 资产勾选（整体覆盖式 PUT）
async function toggleAsset(assetId: string) {
  if (!props.chapterId) return
  const idx = selectedAssetIds.value.indexOf(assetId)
  if (idx >= 0) {
    selectedAssetIds.value.splice(idx, 1)
  } else {
    selectedAssetIds.value.push(assetId)
  }
  await assetApi.updateChapterAssets(props.chapterId, selectedAssetIds.value.slice())
}

function isAssetSelected(assetId: string): boolean {
  return selectedAssetIds.value.includes(assetId)
}

// 切章时重新加载
watch(() => props.chapterId, (newId) => {
  if (newId) loadSettings(newId)
}, { immediate: true })
</script>

<template>
  <div class="scene-settings-panel">
    <div v-if="!chapterId" class="empty">
      <p>从左侧选择一个章节。</p>
    </div>
    <template v-else>
      <!-- 概要统计 -->
      <div class="summary-bar">
        <span class="summary-item">
          <strong>{{ ((selectedChapter as any)?.character_ids || []).length }}</strong> 角色
        </span>
        <span class="summary-item">
          <strong>{{ selectedLocationIds.length }}</strong> 地点
        </span>
        <span class="summary-item">
          <strong>{{ selectedAssetIds.length }}</strong> 资产
        </span>
        <span v-if="loading" class="loading-hint">加载中…</span>
      </div>

      <!-- 出场角色 -->
      <section class="setting-group">
        <div class="setting-group-label">
          出场角色
          <span class="muted">生成时注入角色的永恒设定与此刻状态</span>
        </div>
        <div v-if="characters.length === 0" class="empty-hint">暂无角色，请在圣经面板创建</div>
        <div class="chip-list">
          <button
            v-for="char in characters"
            :key="char.id"
            class="chip"
            :class="{ selected: isCharacterSelected(char.id) }"
            @click="toggleCharacter(char.id)"
          >
            {{ char.name }}
          </button>
        </div>
      </section>

      <!-- 场景地点 -->
      <section class="setting-group">
        <div class="setting-group-label">
          场景地点
          <span class="muted">本章发生的地理空间，影响环境描写</span>
        </div>
        <div v-if="allLocations.length === 0" class="empty-hint">暂无地点，请在圣经面板创建</div>
        <div class="chip-list">
          <button
            v-for="loc in allLocations"
            :key="loc.id"
            class="chip"
            :class="{ selected: isLocationSelected(loc.id) }"
            :disabled="loading"
            @click="toggleLocation(loc.id)"
          >
            {{ loc.name }}
          </button>
        </div>
      </section>

      <!-- 关键资产 -->
      <section class="setting-group">
        <div class="setting-group-label">
          关键资产
          <span class="muted">本章可用的道具/装备，影响情节逻辑</span>
        </div>
        <div v-if="allAssets.length === 0" class="empty-hint">暂无资产，请在圣经面板创建</div>
        <div class="chip-list">
          <button
            v-for="asset in allAssets"
            :key="asset.id"
            class="chip"
            :class="{ selected: isAssetSelected(asset.id) }"
            :disabled="loading"
            @click="toggleAsset(asset.id)"
          >
            {{ asset.name }}
          </button>
        </div>
      </section>

      <!-- 使用说明 -->
      <div class="usage-hint">
        <p>勾选的设定会在生成时通过 SettingResolver 注入 prompt，作为角色行为选择与环境描写的背景知识。</p>
        <p class="muted small">设定影响生成，但不会被直接复述进正文（设定倾倒防御）。</p>
      </div>
    </template>
  </div>
</template>

<style scoped>
.scene-settings-panel {
  display: flex;
  flex-direction: column;
  gap: 1rem;
  height: 100%;
  overflow-y: auto;
}

.empty {
  padding: 2rem 1rem;
  text-align: center;
  color: var(--text-muted);
}

.summary-bar {
  display: flex;
  gap: 1rem;
  padding: 0.5rem 0;
  border-bottom: 1px solid var(--border-color);
  font-size: 0.8rem;
  color: var(--text-muted);
}
.summary-item strong {
  color: var(--text-primary);
  font-size: 0.95rem;
}
.loading-hint {
  margin-left: auto;
  font-style: italic;
}

.setting-group {
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
}
.setting-group-label {
  font-size: 0.8rem;
  font-weight: 600;
  color: var(--text-primary);
  display: flex;
  align-items: baseline;
  gap: 0.5rem;
}
.setting-group-label .muted {
  font-size: 0.7rem;
  font-weight: normal;
  color: var(--text-muted);
}

.empty-hint {
  font-size: 0.75rem;
  color: var(--text-muted);
  font-style: italic;
  padding: 0.25rem 0;
}

.chip-list {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem;
}
.chip {
  padding: 0.25rem 0.7rem;
  font-size: 0.78rem;
  border: 1px solid var(--border-color);
  border-radius: 9999px;
  background: var(--bg-canvas);
  color: var(--text-muted);
  cursor: pointer;
  transition: all 0.15s;
}
.chip:hover:not(:disabled) {
  border-color: var(--accent-500);
  color: var(--text-primary);
}
.chip.selected {
  background: var(--accent-500);
  border-color: var(--accent-600);
  color: white;
  font-weight: 500;
}
.chip:disabled {
  opacity: 0.5;
  cursor: default;
}

.usage-hint {
  margin-top: auto;
  padding: 0.75rem;
  background: var(--bg-canvas);
  border: 1px dashed var(--border-color);
  border-radius: 0.25rem;
  font-size: 0.72rem;
  color: var(--text-muted);
  line-height: 1.5;
}
.usage-hint p {
  margin: 0;
}
.muted.small {
  font-size: 0.68rem;
}
</style>
