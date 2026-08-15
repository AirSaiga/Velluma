<script setup lang="ts">
/**
 * 场景设定面板（M4 世界页收敛后：只读「本章在场」展示）。
 *
 * 原章级勾选绑定（角色 ChapterEntity / 地点 ChapterMapLocation / 资产 ChapterAsset）
 * 已退役——「本章在场」改由世界页事件推演自动得出（docs/world-unified-settings.md §8）：
 * 后端 world_bridge.resolve_narrative_time 解析章节叙事时间，compute_world_state
 * 折叠出该时刻谁在场/在哪/生死，生成流（settings_bundle 世界优先）吃同一份数据。
 *
 * 本面板只做呈现与引导：想改变在场，去世界页录事件（move/birth/death…）或锚定章节时间。
 */
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useAppStore } from '../../app/useAppStore'
import { worldApi } from '../../../services/api/domain/world.api'
import type { WorldEntity, WorldLocation } from '../../../features/world/engine/types'

const props = defineProps<{
  chapterId: string | null
}>()

const store = useAppStore()
const router = useRouter()
const currentBookId = store.currentBookId

const loading = ref(false)
const entities = ref<WorldEntity[]>([])
const locations = ref<WorldLocation[]>([])
const charStates = ref<any[]>([])

async function loadPresence(chapterId: string) {
  const bookId = currentBookId.value
  if (!chapterId || !bookId) return
  loading.value = true
  try {
    const [ents, locs, state] = await Promise.all([
      worldApi.listEntities(bookId),
      worldApi.listLocations(bookId),
      worldApi.getStateForChapter(bookId, chapterId),
    ])
    entities.value = ents || []
    locations.value = locs || []
    charStates.value = (state as any)?.character_states || []
  } catch (e) {
    console.warn('[SceneSettings] 加载在场推演失败', e)
    charStates.value = []
  } finally {
    loading.value = false
  }
}

watch(() => props.chapterId, (newId) => {
  if (newId) loadPresence(newId)
}, { immediate: true })

const usingWorld = computed(() => entities.value.length > 0)
const entityById = computed(() => {
  const map: Record<string, WorldEntity> = {}
  for (const e of entities.value) map[e.id] = e
  return map
})
const locationById = computed(() => {
  const map: Record<string, WorldLocation> = {}
  for (const l of locations.value) map[l.id] = l
  return map
})

interface PresenceRow {
  id: string
  name: string
  alive: boolean
  where: string
  label: string
}
/** 本章时刻在场的角色（推演）：活着或有事态记录的排前，死亡排后灰显 */
const presenceRows = computed<PresenceRow[]>(() => {
  const rows: PresenceRow[] = []
  for (const cs of charStates.value) {
    const ent = entityById.value[String(cs.entity_id)]
    if (!ent) continue
    const loc = locationById.value[String(cs.location_id || '')]
    rows.push({
      id: ent.id,
      name: ent.name,
      alive: !!cs.alive,
      where: loc?.name || '',
      label: cs.label || '',
    })
  }
  rows.sort((a, b) => Number(b.alive) - Number(a.alive) || a.name.localeCompare(b.name, 'zh'))
  return rows
})

function goWorld() {
  if (currentBookId.value) {
    router.push({ path: `/world/${currentBookId.value}`, query: { lens: 'map' } })
  }
}
</script>

<template>
  <div class="scene-settings-panel">
    <div v-if="!chapterId" class="empty">
      <p>从左侧选择一个章节。</p>
    </div>
    <template v-else>
      <!-- 未使用世界页：引导迁移 -->
      <div v-if="!usingWorld && !loading" class="usage-hint">
        <p>本书尚未在世界页建立设定。「本章在场」由世界页的事件推演自动得出。</p>
        <button class="go-world-btn" @click="goWorld">前往世界页</button>
      </div>

      <template v-else>
        <div class="summary-bar">
          <span class="summary-item"><strong>{{ presenceRows.length }}</strong> 在场角色（推演）</span>
          <span v-if="loading" class="loading-hint">推演中…</span>
        </div>

        <section class="setting-group">
          <div class="setting-group-label">
            本章在场
            <span class="muted">由世界页事件按章节叙事时刻自动推演，随事件录入实时变化</span>
          </div>
          <div v-if="!presenceRows.length" class="empty-hint">
            世界页还没有本章时刻的事态记录——去世界页录入移动/出生等事件，或为章节锚定叙事时间。
          </div>
          <ul v-else class="presence-list">
            <li v-for="row in presenceRows" :key="row.id" class="presence-row" :class="{ dead: !row.alive }">
              <span class="presence-name">{{ row.name }}</span>
              <span class="presence-where">
                <template v-if="!row.alive">已死亡</template>
                <template v-else-if="row.where">位于{{ row.where }}</template>
                <template v-else>位置未知</template>
                <template v-if="row.label && row.alive"> · {{ row.label }}</template>
              </span>
            </li>
          </ul>
        </section>

        <div class="usage-hint">
          <p>在场与位置由世界页事件推演（生成辅助使用同一份数据）；想改变在场，去世界页录事件或调整章节叙事锚。</p>
          <button class="go-world-btn subtle" @click="goWorld">打开世界页</button>
        </div>
      </template>
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
  line-height: 1.6;
}

.presence-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}
.presence-row {
  display: flex;
  align-items: baseline;
  gap: 0.75rem;
  padding: 0.3rem 0.5rem;
  border: 1px solid var(--border-color);
  border-radius: 0.25rem;
  font-size: 0.78rem;
}
.presence-row.dead {
  opacity: 0.55;
}
.presence-name {
  color: var(--text-primary);
  font-weight: 500;
}
.presence-where {
  color: var(--text-muted);
  font-size: 0.72rem;
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
  margin: 0 0 0.5rem;
}
.go-world-btn {
  padding: 0.3rem 0.9rem;
  background: var(--accent-500);
  color: #fff;
  border: none;
  border-radius: 0.25rem;
  font-size: 0.72rem;
  cursor: pointer;
}
.go-world-btn.subtle {
  background: transparent;
  color: var(--accent-500);
  border: 1px solid var(--accent-500);
}
</style>
