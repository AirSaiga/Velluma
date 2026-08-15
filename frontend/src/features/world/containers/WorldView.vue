<script setup lang="ts">
/**
 * 世界设定层主视图：地图画布 + 事实清单侧栏 + 时间轴回放。
 *
 * 设计对齐全局设计语言：CSS 变量暖纸质感 / Icon.vue / ModalShell 模态 /
 * useConfirmDialog 删除确认 / useToast 操作反馈；深色模式随变量自适应。
 */
import { ref, computed, onMounted, onBeforeUnmount, watch, nextTick } from 'vue'
import { useRoute } from 'vue-router'
import Icon from '../../../components/Icon.vue'
import { useToast } from '../../../composables/useToast'
import { useConfirmDialog } from '../../../composables/useConfirmDialog'
import { useWorld } from '../composables/useWorld'
import { worldApi } from '../../../services/api'
import { formatTime } from '../engine/timeFormat'
import { EVENT_TYPE_COLOR, getTemplate } from '../engine/eventTemplates'
import { eventPoint, stripPointFromNote } from '../engine/eventPoint'
import type { WorldEvent, WorldLocation, EventType, DrawMode, Point } from '../engine/types'
import WorldMap from './WorldMap.vue'
import WorldTimeline from './WorldTimeline.vue'
import WorldLensMindmap from './WorldLensMindmap.vue'
import QuickCapturePanel from '../presentation/QuickCapturePanel.vue'
import EntityDetailDrawer from '../presentation/EntityDetailDrawer.vue'
import EntityCard from '../presentation/EntityCard.vue'
import BulkImportDialog from '../presentation/BulkImportDialog.vue'
import ModalShell from '../presentation/ModalShell.vue'
import { useWorldHistory, useUndoShortcut } from '../composables/useWorldHistory'
import { useMapEdit, editUndo, editRedo } from '../composables/useMapEdit'

const route = useRoute()
const bookId = computed(() => route.params.bookId as string)

const {
  load,
  createLocation,
  renameLocation,
  renameEntity,
  deleteLocation,
  locations,
  events,
  deleteEvent,
  characters,
  factions,
  assets,
  createEntity,
  deleteEntity,
  locationsById,
  currentTime,
} = useWorld()

const { showToast } = useToast()
const { show: showConfirm } = useConfirmDialog()

// ===== 透镜切换（地图=空间投影 / 脑图=语义投影；v-show 保持两实例存活）=====
const lens = ref<'map' | 'mindmap'>('map')

// ===== 事件 =====
const showEventForm = ref(false)
const editingEvent = ref<WorldEvent | null>(null)
/** 新建事件的默认时刻（时间轴右键时刻或游标时刻——游标即输入焦点） */
const eventInitialTime = ref<number | null>(null)
/** 预设事件类型与角色（实体抽屉快捷动作带入） */
const eventInitialType = ref<EventType | null>(null)
const eventPresetCharacterId = ref<string | null>(null)
const sortedEvents = computed(() =>
  [...events.value].sort((a, b) => a.time_start - b.time_start),
)
const eventLabel = (type: string) => getTemplate(type as EventType)?.label || type
const eventNote = (note: string) => stripPointFromNote(note)

function openEventForm(t?: number) {
  eventInitialTime.value = t ?? currentTime.value
  eventInitialType.value = null
  eventPresetCharacterId.value = null
  showEventForm.value = true
}
function onNewEventAt(t: number) {
  openEventForm(t)
}
/** 实体抽屉快捷事态动作：预填类型与角色，时间默认游标时刻 */
function onQuickEvent(type: EventType, entityId: string) {
  eventInitialTime.value = currentTime.value
  eventInitialType.value = type
  eventPresetCharacterId.value = entityId
  showEventForm.value = true
}

// ===== 实体详情抽屉（M2：档案/编年史/快捷事态的家，三透镜共享选中态）=====
const selectedEntityId = ref<string | null>(null)

function openEditEvent(ev: WorldEvent) {
  editingEvent.value = ev
}
function closeEventForm(wasEdit: boolean, saved: boolean) {
  showEventForm.value = false
  editingEvent.value = null
  drawMode.value = null
  drawResult.value = null
  if (saved) showToast(wasEdit ? '事件已更新' : '事件已记录', 'success')
}

// ===== 地图绘制编排（疆域圈绘 / move 途经点）=====
// 面板发起 draw-start → 收起为悬浮条（保持挂载，表单状态不丢）；
// 完成 → drawResult 回灌面板字段；Esc/取消丢弃草稿。
const drawMode = ref<DrawMode>(null)
const drawResult = ref<{ kind: Exclude<DrawMode, null>; points: Point[] } | null>(null)

function onDrawStart(kind: Exclude<DrawMode, null>) {
  pickingMode.value = null // 与点选建地点互斥
  exitMapEdit() // 与底图编辑互斥
  drawMode.value = kind
}
function onDrawComplete(points: Point[]) {
  if (!drawMode.value) return
  drawResult.value = { kind: drawMode.value, points }
  drawMode.value = null
}
function onDrawCancel() {
  drawMode.value = null // 草稿由 WorldMap watch drawing 时清掉
}
function onDrawFinish() {
  mapRef.value?.finishDraw() // 顶点不足时地图静默忽略，继续画
}

async function removeEvent(ev: WorldEvent) {
  const ok = await showConfirm({
    title: '删除事件',
    message: `确定删除「${eventLabel(ev.event_type)} · ${formatTime(ev.time_start)}」吗？`,
    warning: '时变状态由事件推演，删除后相关世界状态会随之改变（可用 Ctrl+Z 撤销）。',
    confirmText: '删除',
  })
  if (!ok) return
  await deleteEvent(bookId.value, ev.id)
  showToast('事件已删除', 'success')
}

// ===== 实体 =====
const showEntityForm = ref(false)
const newName = ref('')
const newType = ref<'character' | 'faction' | 'asset'>('character')
const newIntro = ref('')

// 连续创建：建立后保持模态打开、清空并聚焦名字（Esc / 完成 关闭）
const entityNameInputRef = ref<HTMLInputElement | null>(null)
async function submitEntity() {
  if (!newName.value.trim()) return
  const label = newType.value === 'character' ? '角色' : newType.value === 'faction' ? '势力' : '资产'
  await createEntity(bookId.value, {
    entity_type: newType.value,
    name: newName.value.trim(),
    intro: newIntro.value,
  })
  showToast(`${label}「${newName.value.trim()}」已建立`, 'success')
  newName.value = ''
  newIntro.value = ''
  // 类型保留（连续建同类常见）；焦点回名字输入，Enter 连续建
  await nextTick()
  entityNameInputRef.value?.focus()
}
function closeEntityForm() {
  showEntityForm.value = false
  newName.value = ''
  newIntro.value = ''
  newType.value = 'character'
}
function onEntityEnter(e: KeyboardEvent) {
  if ((e.target as HTMLElement).tagName === 'BUTTON') return
  submitEntity()
}

async function removeEntity(ent: { id: string; name: string }) {
  const ok = await showConfirm({
    title: '删除实体',
    message: `确定删除「${ent.name}」吗？`,
    warning: '引用该实体的事件不会被删除，但会失去关联（可用 Ctrl+Z 撤销）。',
    confirmText: '删除',
  })
  if (!ok) return
  await deleteEntity(bookId.value, ent.id)
  showToast('实体已删除', 'success')
}

// ===== undo/redo + 批量导入 =====
const { canUndo, canRedo, lastDesc, undo: undoAction, redo: redoAction } = useWorldHistory()
const showBulkImport = ref(false)
let removeShortcut: (() => void) | null = null

// ===== 旧设定中心迁移（幂等；详见后端 migrate_legacy_settings 注释）=====
async function migrateLegacy() {
  const ok = await showConfirm({
    title: '导入旧设定',
    message:
      '将设定中心的角色 / 关系 / 资产 / 地点迁入世界页，并给已有章节锚的旧伏笔补时间锚（出现在弧线带）。',
    warning:
      '旧档案全文会存为「旧档案」字段（不自动拆分）；角色的动态状态不迁（时变状态由事件推演）。可重复执行，已导入的自动跳过；旧表数据不会被修改或删除。',
    confirmText: '开始导入',
  })
  if (!ok) return
  try {
    const r = await worldApi.migrateLegacy(bookId.value)
    await load(bookId.value)
    showToast(
      `已导入 ${r.characters.migrated} 角色 · ${r.relations.migrated} 关系 · ${r.assets.migrated} 资产 · ${r.locations.migrated} 地点` +
        (r.foreshadows_anchored ? ` · 补锚 ${r.foreshadows_anchored} 条伏笔` : '') +
        (r.dynamic_states_skipped ? `（${r.dynamic_states_skipped} 条动态状态未迁，由事件推演）` : ''),
      'success',
    )
  } catch (e) {
    showToast('迁移失败：' + ((e as Error)?.message || '未知错误'), 'error')
  }
}

// 底图编辑（互斥编排：编辑态清拾取/绘制；undo 分流到局部栈）
const { mapEditMode, selectedLayerId, exitMapEdit, removeLayer } = useMapEdit()
watch(mapEditMode, (m) => {
  if (m) {
    pickingMode.value = null
    drawMode.value = null
    if (draftPoint.value) cancelDraft()
  }
})

async function handleUndo() {
  if (mapEditMode.value) {
    await editUndo()
    return
  }
  const d = lastDesc.value
  await undoAction()
  if (d) showToast(`已撤销：${d}`, 'info')
}
async function handleRedo() {
  if (mapEditMode.value) {
    await editRedo()
    return
  }
  await redoAction()
  const d = lastDesc.value
  if (d) showToast(`已重做：${d}`, 'info')
}

// ===== 地图联动 =====
const mapRef = ref<InstanceType<typeof WorldMap> | null>(null)
function focusEvent(ev: WorldEvent) {
  const pt = eventPoint(ev, locationsById.value)
  if (pt) mapRef.value?.focusAt(pt[0], pt[1], eventLabel(ev.event_type))
  else showToast('该事件没有可定位的坐标', 'info')
}
function focusLocation(loc: WorldLocation) {
  if (loc.coord_x == null || loc.coord_y == null) return
  mapRef.value?.focusAt(loc.coord_x, loc.coord_y, loc.name)
}

// ===== 地点双击改名 =====
const editingLocId = ref<string | null>(null)
const locEditName = ref('')
const locNameInputRef = ref<HTMLInputElement | null>(null)
function startEditLoc(loc: { id: string; name: string }) {
  editingLocId.value = loc.id
  locEditName.value = loc.name
  nextTick(() => locNameInputRef.value?.focus())
}
function saveLocName(loc: { id: string; name: string }) {
  if (editingLocId.value !== loc.id) return
  editingLocId.value = null
  const n = locEditName.value.trim()
  if (n && n !== loc.name) renameLocation(bookId.value, loc.id, n)
}

const LOC_KIND_LABEL: Record<string, string> = { point: '地点', region: '区域', route: '路径' }

// ===== 侧栏折叠 =====
const collapsedSections = ref(new Set<string>())
function toggleSection(key: string) {
  const s = collapsedSections.value
  if (s.has(key)) s.delete(key)
  else s.add(key)
  collapsedSections.value = new Set(s)
}
const isCollapsed = (key: string) => collapsedSections.value.has(key)

// ===== 事件过滤 =====
const evtFilter = ref('')
const filteredEvents = computed(() => {
  const q = evtFilter.value.trim().toLowerCase()
  if (!q) return sortedEvents.value
  return sortedEvents.value.filter(
    (ev) =>
      eventLabel(ev.event_type).toLowerCase().includes(q) ||
      ev.event_type.toLowerCase().includes(q) ||
      eventNote(ev.note).toLowerCase().includes(q),
  )
})

// ===== 点选建地点 =====
const pickingMode = ref<'location' | null>(null)
const draftPoint = ref<[number, number] | null>(null)
const draftName = ref('')
const draftKind = ref<'point' | 'region' | 'route'>('point')

function startPickLocation() {
  exitMapEdit() // 与底图编辑互斥
  pickingMode.value = 'location'
}
function onPick(point: [number, number]) {
  draftPoint.value = point
  pickingMode.value = null
}
async function saveDraft() {
  if (!draftPoint.value || !draftName.value.trim()) return
  await createLocation(bookId.value, {
    name: draftName.value.trim(),
    kind: draftKind.value,
    coord_x: draftPoint.value[0],
    coord_y: draftPoint.value[1],
  })
  showToast('已建立——继续点选下一个位置，Esc 结束', 'success')
  draftPoint.value = null
  draftName.value = ''
  draftKind.value = 'point'
  pickingMode.value = 'location' // 连续铺点：建立后直接回到拾取
}
function cancelDraft() {
  draftPoint.value = null
  draftName.value = ''
  pickingMode.value = null
}

async function removeLoc(loc: WorldLocation) {
  const ok = await showConfirm({
    title: '删除地点',
    message: `确定删除地点「${loc.name}」吗？`,
    warning: '关联事件的地点引用会被清空（可用 Ctrl+Z 撤销）。',
    confirmText: '删除',
  })
  if (!ok) return
  await deleteLocation(bookId.value, loc.id)
  showToast('地点已删除', 'success')
}

// 键盘编排：底图编辑（Esc 退出 / Del 删选中图）→ 绘制（Esc/Enter/Backspace）→ 拾取 Esc
function onKeydown(e: KeyboardEvent) {
  const tag = (e.target as HTMLElement | null)?.tagName
  const inField = tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT'
  if (mapEditMode.value) {
    if (inField) return
    if (e.key === 'Escape') exitMapEdit()
    else if (
      mapEditMode.value === 'images' &&
      e.key === 'Delete' &&
      selectedLayerId.value
    ) {
      removeLayer(bookId.value, selectedLayerId.value)
    }
    return
  }
  if (drawMode.value) {
    if (inField) return
    if (e.key === 'Escape') onDrawCancel()
    else if (e.key === 'Enter') onDrawFinish()
    else if (e.key === 'Backspace') mapRef.value?.undoVertex()
    return
  }
  if (e.key === 'Escape' && pickingMode.value) {
    pickingMode.value = null
  }
}

// 拖文件进地图导入图片（images 编辑态）
async function onDropMap(e: DragEvent) {
  if (mapEditMode.value !== 'images') return
  const f = e.dataTransfer?.files?.[0]
  if (!f) return
  try {
    await mapRef.value?.importImageAtView(f)
    showToast('图片已导入——拖中心移动，拖角缩放', 'success')
  } catch (err) {
    showToast('导入失败：' + ((err as Error)?.message || '未知错误'), 'error')
  }
}

onMounted(() => {
  if (bookId.value) load(bookId.value)
  removeShortcut = useUndoShortcut(() => handleUndo(), () => handleRedo())
  window.addEventListener('keydown', onKeydown)
})
onBeforeUnmount(() => {
  removeShortcut?.()
  window.removeEventListener('keydown', onKeydown)
})
watch(bookId, (id) => {
  if (id) load(id)
})
</script>

<template>
  <div class="world-view">
    <header class="world-header">
      <div class="wh-left">
        <h1>世界设定</h1>
        <div class="wh-sub">
          {{ locations.length }} 地点 · {{ events.length }} 事件 ·
          {{ characters.length + factions.length + assets.length }} 实体
        </div>
      </div>
      <div class="header-actions">
        <button
          class="wbtn wbtn--icon"
          :disabled="!canUndo"
          :title="lastDesc ? `撤销：${lastDesc}（Ctrl+Z）` : '撤销（Ctrl+Z）'"
          @click="handleUndo"
        >
          <Icon name="arrow-uturn-left" :size="15" />
        </button>
        <button
          class="wbtn wbtn--icon"
          :disabled="!canRedo"
          title="重做（Ctrl+Y）"
          @click="handleRedo"
        >
          <Icon name="arrow-uturn-right" :size="15" />
        </button>
        <span class="hdr-sep"></span>
        <button
          class="wbtn"
          :class="{ 'wbtn--picking': pickingMode === 'location' }"
          :disabled="pickingMode === 'location'"
          @click="startPickLocation"
        >
          <Icon name="map-pin" :size="14" />
          {{ pickingMode === 'location' ? '点地图选位置…（Esc 取消）' : '地点' }}
        </button>
        <button class="wbtn wbtn--primary" @click="openEventForm()">
          <Icon name="flag" :size="14" />
          事件
        </button>
        <button class="wbtn" @click="showEntityForm = true">
          <Icon name="plus" :size="14" />
          实体
        </button>
        <button class="wbtn" title="TSV 批量导入事件" @click="showBulkImport = true">
          <Icon name="arrow-up-tray" :size="14" />
          批量
        </button>
        <button class="wbtn" title="从设定中心导入角色/关系/资产/地点，并给旧伏笔补时间锚" @click="migrateLegacy">
          <Icon name="arrow-path" :size="14" />
          导入旧设定
        </button>
      </div>
    </header>

    <div class="world-body">
      <div class="world-canvas">
        <!-- 透镜切换：地图（空间投影）/ 脑图（语义投影） -->
        <div class="lens-tabs">
          <button
            class="lens-tab"
            :class="{ active: lens === 'map' }"
            title="地理空间投影"
            @click="lens = 'map'"
          >
            <Icon name="map" :size="13" />
            地图
          </button>
          <button
            class="lens-tab"
            :class="{ active: lens === 'mindmap' }"
            title="关系语义投影"
            @click="lens = 'mindmap'"
          >
            <Icon name="link" :size="13" />
            脑图
          </button>
        </div>

        <div
          v-show="lens === 'map'"
          class="world-map-wrap"
          :class="{ 'is-picking': pickingMode === 'location' }"
          @drop.prevent="onDropMap"
          @dragover.prevent
        >
          <WorldMap
            ref="mapRef"
            :book-id="bookId"
            :picking-mode="pickingMode"
            :draw-mode="drawMode"
            @pick="onPick"
            @draw-complete="onDrawComplete"
            @entity-click="(id: string) => (selectedEntityId = id)"
          />
        </div>

        <div v-show="lens === 'mindmap'" class="world-mm-wrap">
          <WorldLensMindmap :book-id="bookId" @entity-click="(id: string) => (selectedEntityId = id)" />
        </div>

        <!-- 实体详情抽屉（点地图人物/脑图节点/侧栏卡片打开） -->
        <EntityDetailDrawer
          v-if="selectedEntityId"
          :book-id="bookId"
          :entity-id="selectedEntityId"
          @close="selectedEntityId = null"
          @quick-event="onQuickEvent"
          @focus-event="focusEvent"
        />
      </div>

      <aside class="world-side">
        <!-- 地点 -->
        <div class="side-section">
          <div class="side-title side-title--toggle" title="点击折叠/展开" @click="toggleSection('loc')">
            <Icon name="map-pin" :size="13" />
            <span>地点</span>
            <span class="side-count">{{ locations.length }}</span>
            <span class="side-chev" :class="{ closed: isCollapsed('loc') }">▾</span>
          </div>
          <ul v-show="!isCollapsed('loc') && locations.length" class="side-list">
            <li
              v-for="loc in locations"
              :key="loc.id"
              class="side-card"
              :class="{ 'side-card--click': loc.coord_x != null }"
              title="点击定位 · 双击名字改名"
              @click="focusLocation(loc)"
            >
              <div class="sc-body">
                <input
                  v-if="editingLocId === loc.id"
                  ref="locNameInputRef"
                  v-model="locEditName"
                  class="sc-name-input"
                  @keyup.enter="saveLocName(loc)"
                  @keyup.esc="editingLocId = null"
                  @blur="saveLocName(loc)"
                  @click.stop
                />
                <span v-else class="sc-name" @dblclick.stop="startEditLoc(loc)">{{ loc.name }}</span>
                <span class="sc-badge">{{ LOC_KIND_LABEL[loc.kind] || loc.kind }}</span>
              </div>
              <div class="sc-actions">
                <button class="sc-act sc-act--danger" title="删除" @click.stop="removeLoc(loc)">
                  <Icon name="trash" :size="13" />
                </button>
              </div>
            </li>
          </ul>
          <div v-show="!isCollapsed('loc') && !locations.length" class="side-empty">
            还没有地点。点上方「地点」按钮，在地图上点选第一个落脚点。
          </div>
        </div>

        <!-- 事件 -->
        <div class="side-section">
          <div class="side-title side-title--toggle" title="点击折叠/展开" @click="toggleSection('evt')">
            <Icon name="flag" :size="13" />
            <span>事件</span>
            <span class="side-count">{{ filteredEvents.length }}</span>
            <span class="side-chev" :class="{ closed: isCollapsed('evt') }">▾</span>
          </div>
          <div v-show="!isCollapsed('evt')" class="evt-filter">
            <Icon name="magnifying-glass" :size="12" class="evt-filter-icon" />
            <input v-model="evtFilter" class="evt-filter-input" placeholder="筛选事件（类型 / 备注）…" />
          </div>
          <ul v-if="filteredEvents.length" v-show="!isCollapsed('evt')" class="side-list">
            <li
              v-for="ev in filteredEvents"
              :key="ev.id"
              class="side-card side-card--click"
              title="定位到地图"
              @click="focusEvent(ev)"
            >
              <span
                class="evt-dot"
                :style="{ background: EVENT_TYPE_COLOR[ev.event_type] || '#94a3b8' }"
              ></span>
              <div class="sc-body">
                <div class="evt-head">
                  <span class="sc-name">{{ eventLabel(ev.event_type) }}</span>
                  <span class="evt-time">{{ formatTime(ev.time_start) }}</span>
                </div>
                <div v-if="eventNote(ev.note)" class="evt-note">{{ eventNote(ev.note) }}</div>
              </div>
              <div class="sc-actions">
                <button class="sc-act" title="编辑" @click.stop="openEditEvent(ev)">
                  <Icon name="pencil" :size="13" />
                </button>
                <button class="sc-act sc-act--danger" title="删除" @click.stop="removeEvent(ev)">
                  <Icon name="trash" :size="13" />
                </button>
              </div>
            </li>
          </ul>
          <div v-show="!isCollapsed('evt') && !filteredEvents.length" class="side-empty">
            {{ evtFilter ? '没有匹配的事件' : '还没有事件。事件是世界状态的唯一事实源——点「事件」记录第一条历史。' }}
          </div>
        </div>

        <!-- 实体（角色/势力/资产） -->
        <div v-for="group in [
          { key: 'character', title: '角色', icon: 'user', list: characters },
          { key: 'faction', title: '势力', icon: 'users', list: factions },
          { key: 'asset', title: '资产', icon: 'star', list: assets },
        ]" :key="group.key" class="side-section">
          <template v-if="group.list.length">
            <div
              class="side-title side-title--toggle"
              title="点击折叠/展开"
              @click="toggleSection(group.key)"
            >
              <Icon :name="group.icon" :size="13" />
              <span>{{ group.title }}</span>
              <span class="side-count">{{ group.list.length }}</span>
              <span class="side-chev" :class="{ closed: isCollapsed(group.key) }">▾</span>
            </div>
            <div v-show="!isCollapsed(group.key)" class="side-list">
              <EntityCard
                v-for="ent in group.list"
                :key="ent.id"
                :entity="ent"
                @click="selectedEntityId = ent.id"
                @update:name="(n: string) => renameEntity(bookId, ent.id, n)"
                @delete="removeEntity(ent)"
              />
            </div>
          </template>
        </div>
        <div v-if="!characters.length && !factions.length && !assets.length" class="side-empty">
          还没有实体。点「实体」创建角色 / 势力 / 资产——它们只存固有属性，位置与生死由事件推演。
        </div>
      </aside>
    </div>

    <!-- 时间轴（拖动改变 currentTime，地图人物位置/疆域随之回放；右键可记录事件/标记章节锚） -->
    <WorldTimeline @focus-event="focusEvent" @new-event-at="onNewEventAt" />

    <!-- 事件录入/编辑（绘制期间保持挂载、收起为悬浮条，表单状态不丢） -->
    <QuickCapturePanel
      v-if="showEventForm || editingEvent"
      :book-id="bookId"
      :existing="editingEvent"
      :drawing="!!drawMode"
      :draw-result="drawResult"
      :initial-time="eventInitialTime"
      :initial-type="eventInitialType"
      :preset-character-id="eventPresetCharacterId"
      @saved="closeEventForm(!!editingEvent, true)"
      @cancel="closeEventForm(!!editingEvent, false)"
      @draw-start="onDrawStart"
      @draw-finish="onDrawFinish"
      @draw-cancel="onDrawCancel"
    />

    <!-- 实体创建（连续创建：建立后不关，Esc / 完成 关闭） -->
    <ModalShell
      v-if="showEntityForm"
      title="新建实体"
      subtitle="Enter 建立并继续 · Esc 完成"
      width="360px"
      @close="closeEntityForm"
    >
      <div @keydown.enter="onEntityEnter">
      <div class="form-row">
        <label class="form-label">类型</label>
        <div class="type-seg">
          <button
            v-for="t in [
              { v: 'character', label: '角色', icon: 'user' },
              { v: 'faction', label: '势力', icon: 'users' },
              { v: 'asset', label: '资产', icon: 'star' },
            ]"
            :key="t.v"
            class="type-seg-btn"
            :class="{ active: newType === t.v }"
            @click="newType = t.v as typeof newType"
          >
            <Icon :name="t.icon" :size="13" />
            {{ t.label }}
          </button>
        </div>
      </div>
      <div class="form-row">
        <label class="form-label">名字</label>
        <input
          ref="entityNameInputRef"
          v-model="newName"
          class="form-input"
          placeholder="如：莱安娜 / 北境同盟"
        />
      </div>
      <div class="form-row">
        <label class="form-label">简介（可选）</label>
        <input v-model="newIntro" class="form-input" placeholder="一句话说明" />
      </div>
      </div>
      <template #footer>
        <button class="wbtn" @click="closeEntityForm">完成</button>
        <button class="wbtn wbtn--primary" :disabled="!newName.trim()" @click="submitEntity">
          建立（继续）
        </button>
      </template>
    </ModalShell>

    <!-- 批量导入 TSV -->
    <BulkImportDialog
      v-if="showBulkImport"
      :book-id="bookId"
      @done="showBulkImport = false"
      @cancel="showBulkImport = false"
    />

    <!-- 新地点（点选坐标后） -->
    <ModalShell
      v-if="draftPoint"
      title="新地点"
      :subtitle="`坐标 (${draftPoint[0].toFixed(0)}, ${draftPoint[1].toFixed(0)})`"
      width="360px"
      @close="cancelDraft"
    >
      <div class="form-row">
        <label class="form-label">地点名</label>
        <input v-model="draftName" class="form-input" placeholder="如：北境关" />
      </div>
      <div class="form-row">
        <label class="form-label">类型</label>
        <select v-model="draftKind" class="form-input">
          <option value="point">点（城市 / 关隘 / 遗迹）</option>
          <option value="region">区域（国家 / 森林 / 海域）</option>
          <option value="route">路径（道路 / 河流）</option>
        </select>
      </div>
      <template #footer>
        <button class="wbtn" @click="cancelDraft">取消</button>
        <button class="wbtn wbtn--primary" :disabled="!draftName.trim()" @click="saveDraft">
          建立
        </button>
      </template>
    </ModalShell>
  </div>
</template>

<style scoped>
.world-view {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--bg-primary);
}

/* ===== Header ===== */
.world-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 20px;
  border-bottom: 1px solid var(--border-color);
  background: var(--bg-secondary);
}
.wh-left {
  display: flex;
  align-items: baseline;
  gap: 12px;
  min-width: 0;
}
.world-header h1 {
  font-size: 16px;
  font-weight: 600;
  margin: 0;
  color: var(--text-primary);
}
.wh-sub {
  font-size: 12px;
  color: var(--text-muted);
  white-space: nowrap;
}
.header-actions {
  display: flex;
  align-items: center;
  gap: 6px;
}
.hdr-sep {
  width: 1px;
  height: 18px;
  background: var(--border-color);
  margin: 0 4px;
}

/* ===== 按钮体系（本模块统一） ===== */
.wbtn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 6px 12px;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  background: var(--bg-canvas);
  color: var(--text-secondary);
  font-size: 13px;
  font-family: inherit;
  cursor: pointer;
  transition: all 0.15s ease-out;
}
.wbtn:hover:not(:disabled) {
  border-color: var(--accent-500);
  color: var(--accent-500);
  background: rgba(124, 106, 173, 0.06);
}
.wbtn:disabled {
  opacity: 0.45;
  cursor: default;
}
.wbtn--icon {
  width: 30px;
  height: 30px;
  padding: 0;
  justify-content: center;
}
.wbtn--primary {
  background: var(--accent-500);
  border-color: var(--accent-500);
  color: #fff;
}
.wbtn--primary:hover:not(:disabled) {
  background: var(--accent-600);
  border-color: var(--accent-600);
  color: #fff;
  box-shadow: 0 4px 12px rgba(124, 106, 173, 0.25);
  transform: translateY(-1px);
}
.wbtn--picking {
  border-color: #d97706;
  color: #d97706;
  background: rgba(245, 158, 11, 0.08);
  animation: pulse-pick 1.4s ease-in-out infinite;
}
@keyframes pulse-pick {
  50% {
    box-shadow: 0 0 0 5px rgba(245, 158, 11, 0.14);
  }
}

/* ===== 布局 ===== */
.world-body {
  flex: 1;
  display: flex;
  min-height: 0;
}
.world-canvas {
  flex: 1;
  position: relative;
  min-width: 0;
  display: flex;
}
.world-map-wrap,
.world-mm-wrap {
  flex: 1;
  position: relative;
  min-width: 0;
}
.world-map-wrap.is-picking :deep(.leaflet-container) {
  cursor: crosshair;
}
/* 透镜切换 pill（顶部居中：避开 Leaflet 左上缩放控件与地图右上工具条） */
.lens-tabs {
  position: absolute;
  top: 10px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 600;
  display: flex;
  gap: 3px;
  padding: 3px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 9999px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
}
.lens-tab {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 4px 14px;
  border: none;
  border-radius: 9999px;
  background: transparent;
  color: var(--text-muted);
  font-size: 12px;
  font-family: inherit;
  cursor: pointer;
  transition: all 0.15s ease-out;
}
.lens-tab.active {
  background: var(--accent-500);
  color: #fff;
  font-weight: 500;
}
.lens-tab:not(.active):hover {
  color: var(--text-primary);
  background: var(--hover-bg);
}

/* ===== 侧栏 ===== */
.world-side {
  width: 300px;
  flex-shrink: 0;
  border-left: 1px solid var(--border-color);
  background: var(--bg-secondary);
  overflow-y: auto;
  padding: 14px;
}
.side-section {
  margin-bottom: 18px;
}
.side-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary);
  margin-bottom: 8px;
}
.side-count {
  margin-left: auto;
  font-size: 11px;
  font-weight: 500;
  color: var(--text-muted);
  background: var(--bg-tertiary);
  border-radius: 9999px;
  padding: 1px 8px;
}
.side-title--toggle {
  cursor: pointer;
  user-select: none;
  border-radius: 6px;
  padding: 2px 4px;
  margin-left: -4px;
  transition: background 0.12s;
}
.side-title--toggle:hover {
  background: var(--hover-bg);
}
.side-chev {
  font-size: 9px;
  color: var(--text-muted);
  transition: transform 0.15s ease-out;
}
.side-chev.closed {
  transform: rotate(-90deg);
}
/* 事件过滤 */
.evt-filter {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 8px;
  padding: 4px 8px;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  background: var(--bg-canvas);
}
.evt-filter-icon {
  color: var(--text-muted);
  flex-shrink: 0;
}
.evt-filter-input {
  flex: 1;
  min-width: 0;
  border: none;
  background: transparent;
  color: var(--text-primary);
  font-size: 12px;
  font-family: inherit;
  outline: none;
}
.evt-filter-input::placeholder {
  color: var(--text-muted);
}
.side-list {
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.side-card {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  background: var(--bg-canvas);
  border: 1px solid var(--border-color);
  border-radius: 10px;
  transition: all 0.15s ease-out;
}
.side-card--click {
  cursor: pointer;
}
.side-card--click:hover {
  border-color: var(--accent-500);
  transform: translateY(-1px);
  box-shadow: 0 4px 14px rgba(120, 100, 70, 0.1);
}
.sc-body {
  flex: 1;
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 8px;
}
.sc-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.sc-name-input {
  flex: 1;
  min-width: 0;
  padding: 2px 6px;
  border: 1px solid var(--accent-500);
  border-radius: 6px;
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
  background: var(--bg-canvas);
  font-family: inherit;
  outline: none;
}
.sc-badge {
  flex-shrink: 0;
  font-size: 10px;
  color: var(--text-muted);
  background: var(--bg-tertiary);
  border-radius: 9999px;
  padding: 1px 7px;
}
.sc-actions {
  display: flex;
  gap: 2px;
  flex-shrink: 0;
  opacity: 0;
  transition: opacity 0.15s;
}
.side-card:hover .sc-actions {
  opacity: 1;
}
.sc-act {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  transition: all 0.12s;
}
.sc-act:hover {
  background: var(--hover-bg);
  color: var(--text-primary);
}
.sc-act--danger:hover {
  background: rgba(220, 38, 38, 0.08);
  color: #dc2626;
}

/* 事件条目 */
.evt-dot {
  width: 8px;
  height: 8px;
  border-radius: 9999px;
  flex-shrink: 0;
  box-shadow: 0 0 0 3px rgba(0, 0, 0, 0.04);
}
.evt-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
  min-width: 0;
}
.evt-time {
  flex-shrink: 0;
  font-size: 11px;
  color: var(--text-muted);
  font-family: ui-monospace, monospace;
}
.evt-note {
  margin-top: 2px;
  font-size: 12px;
  color: var(--text-secondary);
  overflow: hidden;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}

/* 空状态 */
.side-empty {
  border: 1px dashed var(--border-color);
  border-radius: 10px;
  padding: 14px 12px;
  font-size: 12px;
  line-height: 1.6;
  color: var(--text-muted);
  text-align: center;
}

/* ===== 表单（模态内） ===== */
.form-row {
  margin-bottom: 14px;
}
.form-row:last-child {
  margin-bottom: 0;
}
.form-label {
  display: block;
  font-size: 12px;
  color: var(--text-secondary);
  margin-bottom: 6px;
}
.form-input {
  width: 100%;
  box-sizing: border-box;
  padding: 8px 10px;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  background: var(--bg-canvas);
  color: var(--text-primary);
  font-size: 13px;
  font-family: inherit;
  transition: border-color 0.15s;
}
.form-input:focus {
  outline: none;
  border-color: var(--accent-500);
  box-shadow: 0 0 0 3px rgba(124, 106, 173, 0.12);
}
.type-seg {
  display: flex;
  gap: 6px;
}
.type-seg-btn {
  flex: 1;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 5px;
  padding: 7px 0;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  background: var(--bg-canvas);
  color: var(--text-secondary);
  font-size: 13px;
  font-family: inherit;
  cursor: pointer;
  transition: all 0.15s;
}
.type-seg-btn.active {
  border-color: var(--accent-500);
  background: rgba(124, 106, 173, 0.08);
  color: var(--accent-500);
  font-weight: 600;
}
</style>
