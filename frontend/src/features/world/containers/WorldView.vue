<script setup lang="ts">
/**
 * 世界设定层主视图：地图画布 + 事实清单侧栏 + 时间轴回放。
 *
 * 设计对齐全局设计语言：CSS 变量暖纸质感 / Icon.vue / ModalShell 模态 /
 * useConfirmDialog 删除确认 / useToast 操作反馈；深色模式随变量自适应。

 * 主题豁免（docs/design/theme-system/01-theme-architecture.md §7）：古地图永远是古地图——
 * 羊皮画布/鎏金/暖墨/烛光暗角等装饰色浅深与任何主题下恒定；深色下保持亮图=「灯下看地图」，
 * 由 2026-09-15 主题系统重设计正式追认为设计决定（此前是无意幸运）。
 */
import { ref, computed, onMounted, onBeforeUnmount, watch, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import Icon from '../../../components/Icon.vue'
import { useToast } from '../../../composables/useToast'
import { useConfirmDialog } from '../../../composables/useConfirmDialog'
import { useWorld } from '../composables/useWorld'
import { worldApi } from '../../../services/api'
import { bookApi } from '../../../services/api/domain'
import { useAppStore } from '../../app/useAppStore'
import { formatTime, displayCandidateTime } from '../engine/timeFormat'
import { getTemplate, eventDisplayName } from '../engine/eventTemplates'
import { eventPoint, stripPointFromNote } from '../engine/eventPoint'
import { childrenIndex, collectSubtree, topLevelLocations } from '../engine/locationTree'
import { groupEntities } from '../engine/entityGroups'
import { ensurePinyin, matchesQuery } from '../engine/pinyinMatch'
import type { WorldEvent, WorldLocation, EventType, DrawMode, Point } from '../engine/types'
import WorldMap from './WorldMap.vue'
import WorldTimeline from './WorldTimeline.vue'
import QuickCapturePanel from '../presentation/QuickCapturePanel.vue'
import QuickEventNote from '../presentation/QuickEventNote.vue'
import EntityDetailDrawer from '../presentation/EntityDetailDrawer.vue'
import LocationDetailDrawer from '../presentation/LocationDetailDrawer.vue'
import EntityCard from '../presentation/EntityCard.vue'
import DrawerShell from '../presentation/DrawerShell.vue'
import EventSpineList from '../presentation/EventSpineList.vue'
import BulkImportDialog from '../presentation/BulkImportDialog.vue'
import ModalShell from '../../../components/ModalShell.vue'
import ForeshadowSection from '../presentation/ForeshadowSection.vue'
import ForeshadowDetailDrawer from '../presentation/ForeshadowDetailDrawer.vue'
import ReaderMirrorModal from '../presentation/ReaderMirrorModal.vue'
import WorldviewModal from '../presentation/WorldviewModal.vue'
import CanonSection from '../presentation/CanonSection.vue'
import CanonTruthDetailDrawer from '../presentation/CanonTruthDetailDrawer.vue'
import BatchAcceptModal from '../presentation/BatchAcceptModal.vue'
import ReadBookModal from '../presentation/ReadBookModal.vue'
import {
  runBatchAccept,
  undoBatchAccept,
  summarizeBatch,
  type BatchAcceptOutcome,
} from '../composables/batchAccept'
import { useCanon } from '../composables/useCanon'
import { useReadBook } from '../composables/useReadBook'
import { inboxNavKey, moveInboxIndex, verdictFromKey } from '../composables/inboxKeyboard'
import { readerMirrorApi } from '../../../services/api/domain/reader-mirror.api'
import { useWorldHistory, useUndoShortcut } from '../composables/useWorldHistory'
import { useMapEdit, editUndo, editRedo } from '../composables/useMapEdit'

const route = useRoute()
const router = useRouter()
const bookId = computed(() => route.params.bookId as string)

// 书籍上下文：世界页跟随全局当前书（导航栏「世界」入口带 currentBookId 跳转）。
// 深链/旧地址直达时按路由参数同步当前书（与 BibleView 同模式）——否则页面数据
// 与导航栏高亮会指向两本不同的书。
const store = useAppStore()
const bookTitle = computed(() => store.currentBook.value?.title || '')
watch(
  bookId,
  (id) => {
    if (id && id !== store.currentBookId.value) store.selectBook(id)
  },
  { immediate: true }
)

function goLibrary() {
  router.push({ name: 'library' })
}

const {
  load,
  createLocation,
  renameLocation,
  updateLocationCoords,
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
  worldState,
  jumpToTime,
  foreshadows,
} = useWorld()

const { showToast } = useToast()
const { show: showConfirm } = useConfirmDialog()

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
const eventTypeLabel = (type: string) => getTemplate(type as EventType)?.label || type
const eventLabel = (ev: WorldEvent) => eventDisplayName(ev)
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

// ===== 世界速记（关联式录入 2026-09-05）=====
// 裸入口（胶囊条「记一笔历史」/事件抽屉「＋ 记一笔」/Alt+N）开速记——一句话把
// 事件与新人物/新地点一次带上；带预设上下文的路径（时间轴右键时刻/实体抽屉快捷
// 事态）仍直达模板表单——有预设时模板比句子快。速记内「按模板逐栏录 →」单向桥接回表单。
const quickNoteRef = ref<InstanceType<typeof QuickEventNote> | null>(null)
function openQuickNote() {
  quickNoteRef.value?.openWith()
}
/** 速记「放到地图」：进点选模式记行号，onPick 里按 quick-note 分流回灌 */
const quickNotePickIndex = ref<number | null>(null)
function onQuickNoteMapPick(index: number) {
  exitMapEdit() // 与底图编辑互斥
  quickNotePickIndex.value = index
  pickingMode.value = 'quick-note'
}
/** 速记标点取消（悬浮条取消 / Esc） */
function onQuickNotePickCancel() {
  quickNotePickIndex.value = null
  if (pickingMode.value === 'quick-note') pickingMode.value = null
}
/** 速记入账/撤销后全量刷新（速记不经 useWorld 的 pushCommand，主数据要手动拉） */
async function onQuickNoteCommitted() {
  if (bookId.value) await load(bookId.value)
}
/** 速记内「按模板逐栏录 →」：游标时刻为默认时刻，直达结构化表单 */
function onQuickNoteToTemplate() {
  openEventForm(currentTime.value)
}

// ===== 实体详情抽屉（M2：档案/编年史/快捷事态的家，三透镜共享选中态）=====
const selectedEntityId = ref<string | null>(null)

// ===== 地点详情抽屉（docs/location-interior.md：内部构造的二级面板）=====
const selectedLocId = ref<string | null>(null)
function openLocDetail(id: string) {
  selectedLocId.value = id
}

// ===== M5：伏笔详情抽屉 / 期待账本 / 世界观模态 =====
const selectedForeshadowId = ref<string | null>(null)
const showExpectations = ref(false)
const showWorldview = ref(false)

// ===== C1 真相层（Canon 融入）：真相详情抽屉（docs/canon-world-fusion.md）=====
// 2026-09-03：因果图谱模态退役（建边零入口——边恒为零，图谱永远是一屏孤立圆点；
// 后端边表/CRUD 保留零数据风险），设计稿 docs/design/truth-ux/
const selectedTruthId = ref<string | null>(null)
const { nodes: canonNodes, ensureLoaded: ensureCanonLoaded } = useCanon()

/** 期待摘要（侧栏「期待」分组：活跃 N · 该收了 M；账本本体在 ReaderMirrorModal） */
const mirrorSummary = ref<{ active: number; due: number } | null>(null)
async function loadMirrorSummary() {
  if (!bookId.value) return
  try {
    const data = await readerMirrorApi.get(bookId.value)
    const exps: any[] = data.expectations || []
    const active = exps.filter((e) => ['setup', 'accumulating'].includes(e.status))
    mirrorSummary.value = {
      active: active.length,
      due: active.filter((e) => e.current_tension >= 8).length,
    }
  } catch {
    mirrorSummary.value = null
  }
}

// ===== M6 活舆图：图标栏当前抽屉 / ⋯ 菜单 =====
type SidePanelKey = 'cand' | 'fs' | 'exp' | 'canon' | 'loc' | 'evt' | 'character' | 'faction' | 'asset'
const activePanel = ref<SidePanelKey | null>(null)
/** 详情抽屉的「上一级」：从图标栏抽屉钻进详情时由下方 watch 记下；返回=恢复来路，关闭=连来路丢弃 */
const detailReturnPanel = ref<SidePanelKey | null>(null)
// 详情抽屉（实体/地点/伏笔/真相）与图标栏抽屉双向互斥——同一时刻画布右缘只存在一层浮层
// （详情抽屉 right:58px 宽 340/360px 与账本抽屉 right:47px 宽 264px 物理重叠，同开必叠）
function closeDetailDrawers() {
  selectedEntityId.value = null
  selectedLocId.value = null
  selectedForeshadowId.value = null
  selectedTruthId.value = null
}
function togglePanel(key: SidePanelKey) {
  const opening = activePanel.value !== key
  activePanel.value = opening ? key : null
  if (opening) closeDetailDrawers()
  detailReturnPanel.value = null
}
const moreOpen = ref(false)

watch([selectedEntityId, selectedLocId, selectedForeshadowId, selectedTruthId], ([e, l, f, t]) => {
  if (e || l || f || t) {
    // 详情抽屉顶掉面板前记下它来路——「← 返回上一级」凭它恢复（只记第一重，防详情间横跳覆盖）
    if (activePanel.value && !detailReturnPanel.value) detailReturnPanel.value = activePanel.value
    activePanel.value = null
  }
})

function onDetailBack(clear: () => void) {
  const target = detailReturnPanel.value
  detailReturnPanel.value = null
  clear()
  if (target) activePanel.value = target
}
function onDetailClosed(clear: () => void) {
  detailReturnPanel.value = null
  clear()
}

/** 实体抽屉的当前列表（与图标栏选中类型联动，复用实体搜索过滤） */
const panelEntities = computed(() => {
  if (activePanel.value === 'character') return visibleCharacters.value
  if (activePanel.value === 'faction') return visibleFactions.value
  if (activePanel.value === 'asset') return visibleAssets.value
  return []
})
const entityEmptyText = computed(() => {
  const label =
    activePanel.value === 'character' ? '角色' : activePanel.value === 'faction' ? '势力' : '资产'
  const pool =
    activePanel.value === 'character'
      ? characters.value
      : activePanel.value === 'faction'
        ? factions.value
        : assets.value
  if (entityFilter.value && pool.length) return `没有匹配「${entityFilter.value}」的${label}`
  return `还没有${label}。点上方「＋ 新建」创建——它们只存固有属性，位置与生死由事件推演。`
})

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
    message: `确定删除「${eventLabel(ev)} · ${formatTime(ev.time_start)}」吗？`,
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
  const name = newName.value.trim()
  const ent = await createEntity(bookId.value, {
    entity_type: newType.value,
    name,
    intro: newIntro.value,
  })
  // 建完的桥：toast 带「补全档案」直达详情抽屉——深加工是选项不是强加（轻动作后不自动弹重表单）
  showToast(`${label}「${name}」已建立`, 'success', 6000, {
    label: '补全档案',
    onClick: () => {
      closeEntityForm()
      selectedEntityId.value = ent.id
    },
  })
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

// 侧栏实体抽屉「＋ 新建」：类型按当前抽屉预选（胶囊工具条「＋ 实体」入口不变，缺省角色）
function createFromEntityPanel() {
  newType.value =
    activePanel.value === 'faction' ? 'faction' : activePanel.value === 'asset' ? 'asset' : 'character'
  showEntityForm.value = true
}
// 侧栏地点抽屉「＋ 新建」：收起抽屉让出全图视野，走同一条点选流（Esc 取消）
function createFromLocPanel() {
  activePanel.value = null
  startPickLocation()
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
// ===== D4 比例尺标定（docs/map-scale-spatial.md §3：拉线→选档→完成，≤3 步）=====
const calibDialog = ref<{ points: [number, number][] } | null>(null)
const calibDays = ref('1')
const calibMode = ref<'foot' | 'horse' | 'boat' | 'custom'>('foot')
const calibPrefilled = ref(false)

function startCalibrate() {
  moreOpen.value = false
  window.dispatchEvent(new CustomEvent('velluma:map-calibrate-start'))
}

function onCalibLine(e: Event) {
  const d = (e as CustomEvent<{ points: [number, number][]; suggested_days?: number }>).detail
  if (d?.points?.length !== 2) return
  calibDialog.value = { points: d.points }
  // §2.2 空白舆图预填：选档卡默认 custom + 地球尺度折算值——作者可改可推翻
  if (d.suggested_days && d.suggested_days > 0) {
    calibMode.value = 'custom'
    calibDays.value = d.suggested_days < 10
      ? String(Math.round(d.suggested_days * 10) / 10)
      : String(Math.round(d.suggested_days))
    calibPrefilled.value = true
  } else {
    calibMode.value = 'foot'
    calibDays.value = '1'
    calibPrefilled.value = false
  }
}
onMounted(() => window.addEventListener('velluma:map-calibrate-line', onCalibLine))
onBeforeUnmount(() => window.removeEventListener('velluma:map-calibrate-line', onCalibLine))

/** 选档保存：模式换算为步行日（骑马 1 天 = 2.5 步行日等），refs ≤5 先进先出 */
async function saveCalibration() {
  const cal = calibDialog.value
  if (!cal || !bookId.value) return
  const MODE_TO_DAYS: Record<string, number> = { foot: 1, horse: 2.5, boat: 2 }
  let days = MODE_TO_DAYS[calibMode.value]
  if (calibMode.value === 'custom') days = Math.max(0.1, Number(calibDays.value) || 1)
  else days = Number(calibDays.value) > 0 ? Number(calibDays.value) * days : days
  const [a, b] = cal.points
  const book = store.currentBook.value as any
  const refs = [...((book?.map_scale as any)?.refs || []), {
    ax: a[0], ay: a[1], bx: b[0], by: b[1], days_foot: days,
    label: calibMode.value === 'foot' ? '步行' : calibMode.value === 'horse' ? '骑马' : calibMode.value === 'boat' ? '乘船' : '自定义',
  }].slice(-5)
  try {
    await bookApi.update(bookId.value, { map_scale: { refs, detour_factor: (book?.map_scale as any)?.detour_factor ?? 1.2, modes: (book?.map_scale as any)?.modes ?? { walk: 1, horse: 2.5, boat: 2, caravan: 0.7 } } })
    await store.selectBook(bookId.value)
    showToast('比例尺已标定——距离从此有了诚实的人话', 'success')
  } catch (e: any) {
    showToast('标定失败：' + (e?.message || ''), 'error')
  } finally {
    calibDialog.value = null
  }
}

async function migrateLegacy() {
  const ok = await showConfirm({
    title: '导入旧设定',
    message:
      '将设定中心的角色 / 关系 / 资产 / 地点迁入世界页，并给已有章节锚的旧伏笔补时间锚（出现在弧线带）。',
    warning:
      '角色档案全文会存为「背景」字段（不自动拆分，可随后在详情抽屉里整理）；角色的动态状态不迁（时变状态由事件推演）。可重复执行，已导入的自动跳过；旧表数据不会被修改或删除。',
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

// 罗盘针大摆归北动画的开关：class 摘下等一帧再挂回才能重播（连点重触发）
const compassHome = ref(false)
let compassHomeTimer: number | undefined

async function onCompassClick() {
  mapRef.value?.fitAll()
  compassHome.value = false
  await nextTick()
  requestAnimationFrame(() => {
    compassHome.value = true
    window.clearTimeout(compassHomeTimer)
    compassHomeTimer = window.setTimeout(() => (compassHome.value = false), 1500)
  })
}
function focusEvent(ev: WorldEvent) {
  const pt = eventPoint(ev, locationsById.value)
  if (pt) mapRef.value?.focusAt(pt[0], pt[1], eventLabel(ev))
  else showToast('该事件没有可定位的坐标', 'info')
}
/** 「去地图放置」的补坐标目标（2026-09-04 审计修复：无坐标地点此前点击零反应） */
const relocatingLoc = ref<WorldLocation | null>(null)

function focusLocation(loc: WorldLocation) {
  if (loc.coord_x != null && loc.coord_y != null) {
    mapRef.value?.focusAt(loc.coord_x, loc.coord_y, loc.name)
    pulseLocMarker(loc.id)
    return
  }
  // 无坐标（未上图/内部构造）→ 进拾取模式补坐标（原实现直接 return=死按钮）
  exitMapEdit()
  draftPoint.value = null
  draftName.value = ''
  draftKind.value = 'point'
  relocatingLoc.value = loc
  pickingMode.value = 'location'
}

/** 右缘任一浮层在场（图标栏抽屉或四个详情抽屉）→ 罗盘左移避让。
 *  全高 340px 抽屉（right:58px）与罗盘（right:64px, z:660）物理重叠——旧浮层时代
 *  详情抽屉盖罗盘已有先例，如今外壳统一全高，罗盘主动让位（避让位 58+340+16=414px）。 */
const rightDrawerOpen = computed(
  () =>
    !!(activePanel.value || selectedEntityId.value || selectedLocId.value ||
      selectedForeshadowId.value || selectedTruthId.value),
)

// ===== 地图双向联动（二期）=====
/** 面板 📍 → 地图：地标声呐脉冲（2.4s 自清；null→nextTick→id 分离两次变更，连点同目标也重播） */
const highlightedLocId = ref<string | null>(null)
let locPulseTimer: number | undefined
function pulseLocMarker(id: string) {
  highlightedLocId.value = null
  window.clearTimeout(locPulseTimer)
  void nextTick(() => {
    highlightedLocId.value = id
    locPulseTimer = window.setTimeout(() => (highlightedLocId.value = null), 2400)
  })
}

/** 地图标地点击 → 地点面板条目回指：行高亮 + 滚入视野 + 展开被折叠的祖先枝。
 *  仅地点面板开着时联动（面板关着时 popup 已承载信息展示，不硬开面板抢视野）。 */
const highlightedRowLocId = ref<string | null>(null)
let rowHlTimer: number | undefined
function expandLocAncestors(id: string) {
  const byId = locationsById.value
  let cur = byId[id]
  while (cur?.parent_id) {
    collapsedLocs.value.delete(cur.parent_id)
    cur = byId[cur.parent_id]
  }
}
function onMapLocationHighlight(id: string) {
  if (activePanel.value !== 'loc') return
  expandLocAncestors(id)
  highlightedRowLocId.value = null
  window.clearTimeout(rowHlTimer)
  void nextTick(() => {
    highlightedRowLocId.value = id
    rowHlTimer = window.setTimeout(() => (highlightedRowLocId.value = null), 2400)
    // 祖先展开后行才进 DOM——nextTick 后再滚；被搜索词滤掉的行静默跳过（不动用户的搜索词）
    document
      .querySelector(`.atlas-drawer li[data-loc-id="${id}"]`)
      ?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  })
}

// ===== W4 待确认候选（写作回流收件箱的跨章全貌）=====
const pendingCandidates = ref<import('../../../services/api/domain/world.api').WorldEventCandidate[]>([])
const busyCandidateId = ref<string | null>(null)

async function loadCandidates() {
  if (!bookId.value) return
  try {
    pendingCandidates.value = await worldApi.listCandidates(bookId.value, undefined, 'pending')
  } catch {
    pendingCandidates.value = []
  }
}
async function acceptCand(c: { id: string; source?: string; draft?: { summary?: string; event_type?: string; label?: string } }) {
  if (!bookId.value || busyCandidateId.value) return
  busyCandidateId.value = c.id
  const isCanon = c.source === 'canon_extract'
  try {
    await worldApi.acceptCandidate(bookId.value, c.id)
    if (isCanon) {
      // C3 分流：canon 候选转正建真相节点——刷新真相账本与候选列表，不动事件推演
      window.dispatchEvent(new CustomEvent('velluma:world-refresh'))
      showToast(`已记入真相：${c.draft?.label || '新条目'}（草稿——记得去真相抽屉核实）`, 'success')
    } else {
      await load(bookId.value) // 转正进入推演：事件/状态全量刷新
      showToast(`已入账：${c.draft?.summary || eventTypeLabel(c.draft?.event_type || 'custom')}`, 'success')
    }
  } catch (e: any) {
    showToast('入账失败：' + (e?.message || '未知错误'), 'error')
  } finally {
    busyCandidateId.value = null
    await loadCandidates()
  }
}
async function rejectCand(c: { id: string }) {
  if (!bookId.value || busyCandidateId.value) return
  busyCandidateId.value = c.id
  try {
    await worldApi.rejectCandidate(bookId.value, c.id)
  } finally {
    busyCandidateId.value = null
    await loadCandidates()
  }
}

// ===== 键盘裁决（02 候选回流修缮 M3）：待确认列表获焦后 ↑↓ 移动 / →·Enter ✓ / ←·Delete ✗ =====
const candCursor = ref(0)
watch(
  () => pendingCandidates.value.length,
  (len) => { if (candCursor.value >= len) candCursor.value = Math.max(0, len - 1) },
)
function onCandListKeydown(ev: KeyboardEvent) {
  if (!pendingCandidates.value.length) return
  const nav = inboxNavKey(ev.key)
  if (nav !== 0) {
    ev.preventDefault()
    ev.stopPropagation()
    candCursor.value = moveInboxIndex(candCursor.value, nav, pendingCandidates.value.length)
    return
  }
  const verdict = verdictFromKey(ev.key)
  if (!verdict) return
  ev.preventDefault()
  ev.stopPropagation()
  const c = pendingCandidates.value[candCursor.value]
  if (!c || busyCandidateId.value) return
  if (verdict === 'accept') void acceptCand(c)
  else void rejectCand(c)
}
/** 出处原句（02 修缮 M1）：悬停见正文原句（后端已校验逐字子串），canon 候选回落既有 title */
function candTitleOf(c: typeof pendingCandidates.value[number]): string {
  const ev = (c.draft as { evidence?: string } | undefined)?.evidence
  if (ev) return `原句：${ev}`
  return c.draft?.note || c.draft?.canon_text || ''
}

// ===== A5b 批量裁决：全部采纳 → 预览剔除 → 串行 accept → toast 6 秒整批撤销 =====
const batchOpen = ref(false)
const batchBusy = ref(false)
const batchProgress = ref<{ done: number; total: number } | null>(null)

// ===== 全书通读（2026-08-25「系统自己去读」存量首秀）：认人 → 过目 → 记事 =====
const readBookOpen = ref(false)
const readBook = useReadBook()

function openReadBook() {
  readBook.reset()
  readBookOpen.value = true
  if (bookId.value) void readBook.start(bookId.value)
}

async function onReadBookConfirmEntities() {
  if (!bookId.value) return
  await readBook.confirmEntities(bookId.value)
}

async function onReadBookConfirmDepictions() {
  if (!bookId.value) return
  await readBook.confirmDepictions(bookId.value)
}

async function onReadBookClose() {
  readBookOpen.value = false
  // 通读可能新建了实体/地点 + 填满了收件箱——全量刷新（实体进推演 + 候选重取）
  if (bookId.value && (readBook.createdEntities.value || readBook.createdCandidates.value)) {
    window.dispatchEvent(new CustomEvent('velluma:world-refresh'))
    await load(bookId.value)
    await loadCandidates()
  }
  readBook.reset()
}

async function onBatchConfirm(ids: string[]) {
  if (!bookId.value) return
  const picked = pendingCandidates.value.filter((c) => ids.includes(c.id))
  if (!picked.length) return
  batchBusy.value = true
  batchProgress.value = { done: 0, total: picked.length }
  let outcomes: BatchAcceptOutcome[] = []
  try {
    outcomes = await runBatchAccept(
      bookId.value,
      picked,
      (done, total) => { batchProgress.value = { done, total } },
    )
  } finally {
    batchBusy.value = false
    batchProgress.value = null
    batchOpen.value = false
    // 转正进入推演：事件/状态全量刷新 + 候选列表重取（canon 候选建节点亦经
    // world-refresh 广播让真相账本刷新）——与单条 acceptCand 的刷新面一致
    window.dispatchEvent(new CustomEvent('velluma:world-refresh'))
    await load(bookId.value)
    await loadCandidates()
  }
  const { ok, failed, dup } = summarizeBatch(outcomes)
  if (ok > 0) {
    showToast(
      `已批量入账 ${ok} 条世界变化` + (dup > 0 ? `（另 ${dup} 条与账本重复，已自动跳过）` : ''),
      'success', 6000, {
      label: '撤销',
      // 撤销闭包捕获本批 outcomes——连开两批时旧 toast 只撤旧批
      onClick: () => { void undoBatch(outcomes) },
    })
  } else if (dup > 0) {
    showToast(`${dup} 条与账本已有事件重复，已自动跳过`, 'info')
  }
  if (failed > 0) showToast(`${failed} 条采纳失败（可能已被处理），可稍后重试`, 'warning')
}

async function undoBatch(outcomes: BatchAcceptOutcome[]) {
  if (!bookId.value) return
  const undone = await undoBatchAccept(bookId.value, outcomes)
  showToast(
    undone > 0 ? `已撤销 ${undone} 条入账（候选回到待确认）` : '撤销未完全成功：可在待确认分区逐条处理',
    undone > 0 ? 'info' : 'warning',
  )
  window.dispatchEvent(new CustomEvent('velluma:world-refresh'))
  await load(bookId.value)
  await loadCandidates()
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

// ===== 事件过滤 =====
const evtFilter = ref('')
const filteredEvents = computed(() => {
  const q = evtFilter.value
  if (!q.trim()) return sortedEvents.value
  return sortedEvents.value.filter((ev) =>
    matchesQuery(q, eventLabel(ev), ev.event_type, eventNote(ev.note)),
  )
})

// ===== 点选建地点 =====
const pickingMode = ref<'location' | 'quick-note' | null>(null)
const draftPoint = ref<[number, number] | null>(null)
const draftName = ref('')
const draftKind = ref<'point' | 'region' | 'route'>('point')

function startPickLocation() {
  exitMapEdit() // 与底图编辑互斥
  pickingMode.value = 'location'
}
async function onPick(point: [number, number]) {
  // 速记新地点标位：坐标回灌速记草稿对应行（模态由 applyMapPoint 恢复显示）
  if (pickingMode.value === 'quick-note') {
    pickingMode.value = null
    const idx = quickNotePickIndex.value
    quickNotePickIndex.value = null
    if (idx !== null) quickNoteRef.value?.applyMapPoint(idx, point)
    return
  }
  // 补坐标拾取：更新既有地点坐标而非新建（来自详情抽屉「去地图放置」）
  if (relocatingLoc.value) {
    const loc = relocatingLoc.value
    relocatingLoc.value = null
    pickingMode.value = null
    try {
      await updateLocationCoords(bookId.value, loc.id, point[0], point[1])
      showToast(`「${loc.name}」已放置到地图`, 'success')
    } catch (e: any) {
      showToast('放置失败：' + (e?.message || ''), 'error')
    }
    return
  }
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
  relocatingLoc.value = null
}

// ===== 地点树（折叠分组 + 搜索 + 顶层计数口径）=====
/** 折叠的顶层节点集（整枝剪除，只折叠自身子树——房间级以下同规则递归） */
const collapsedLocs = ref(new Set<string>())
function toggleLocCollapse(id: string) {
  if (collapsedLocs.value.has(id)) collapsedLocs.value.delete(id)
  else collapsedLocs.value.add(id)
}
function isLocCollapsed(id: string) {
  return collapsedLocs.value.has(id)
}
const locFilter = ref('')
/** 树序展开：顶层在前、子级紧随父后带深度（列表缩进用）；折叠枝剪除；
 *  搜索时改「整枝保留」——自身或后代命中即入列（搜房间能带出父链），折叠态让位自动展开 */
const orderedLocations = computed(() => {
  const kids = locChildren.value
  const q = locFilter.value.trim().toLowerCase()
  const hasMatchIn = (l: WorldLocation): boolean => {
    if (matchesQuery(locFilter.value, l.name)) return true
    return (kids.get(l.id) || []).some(hasMatchIn)
  }
  const out: { loc: WorldLocation; depth: number }[] = []
  const walk = (list: WorldLocation[], depth: number) => {
    for (const l of list) {
      if (q) {
        if (!hasMatchIn(l)) continue
      } else if (collapsedLocs.value.has(l.id)) {
        out.push({ loc: l, depth })
        continue
      }
      out.push({ loc: l, depth })
      walk(kids.get(l.id) || [], depth + 1)
    }
  }
  walk(topLevelLocations(locations.value), 0)
  return out
})
/** 计数徽标只数顶层（内部构造不进「N 地点」——防房间把数字灌虚） */
const topLocationCount = computed(() => topLevelLocations(locations.value).length)
const locChildren = computed(() => childrenIndex(locations.value))

async function removeLoc(loc: WorldLocation) {
  const innerCount = Math.max(0, collectSubtree(locations.value, loc.id).length - 1)
  const ok = await showConfirm({
    title: '删除地点',
    message: `确定删除地点「${loc.name}」吗？`,
    warning:
      (innerCount ? `含 ${innerCount} 个内部构造，将一并删除。` : '') +
      '关联事件的地点引用会被清空（可用 Ctrl+Z 撤销）。',
    confirmText: '删除',
  })
  if (!ok) return
  await deleteLocation(bookId.value, loc.id)
  showToast('地点已删除', 'success')
}

// 键盘编排：底图编辑（Esc 退出 / Del 删选中图）→ 绘制（Esc/Enter/Backspace）→ 拾取 Esc
function onKeydown(e: KeyboardEvent) {
  // 02 期 §3.4：Esc 栈（window capture 先行）已消费的 Escape 事件让位——防「一次 Esc 同关弹层+退出绘制态」双关
  if (e.defaultPrevented) return
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
    const wasQuickNote = pickingMode.value === 'quick-note'
    pickingMode.value = null
    relocatingLoc.value = null
    if (wasQuickNote) {
      quickNotePickIndex.value = null
      quickNoteRef.value?.cancelMapPick() // 速记模态从悬浮条恢复
    }
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

/** world-refresh：候选列表 + 期待摘要一并静默重取（伏笔/期待/世界观编辑后由 useWorld/账本广播） */
function onWorldRefresh() {
  void loadCandidates()
  void loadMirrorSummary()
}

onMounted(() => {
  if (bookId.value) load(bookId.value)
  consumeRouteQuery()
  removeShortcut = useUndoShortcut(() => handleUndo(), () => handleRedo())
  window.addEventListener('keydown', onKeydown)
  window.addEventListener('velluma:world-refresh', onWorldRefresh)
  void loadCandidates()
  void loadMirrorSummary()
  if (bookId.value) void ensureCanonLoaded(bookId.value)
})
onBeforeUnmount(() => {
  removeShortcut?.()
  window.removeEventListener('keydown', onKeydown)
  window.removeEventListener('velluma:world-refresh', onWorldRefresh)
})
watch(bookId, (id) => {
  if (id) {
    load(id)
    consumeRouteQuery()
    void loadCandidates()
    void loadMirrorSummary()
    void ensureCanonLoaded(id)
  }
})

// ===== 深链支持：bible 跳转卡 + W2 写作页往返（?entity=&loc=&time=&from=chapter&chapter=）=====
// 实体选中是纯本地 ref，抽屉按 id 从 useWorld 响应式取——数据晚到也能正确打开。
function consumeRouteQuery() {
  const ent = route.query.entity
  if (typeof ent === 'string' && ent) selectedEntityId.value = ent
  // 游标跳到指定时刻（写作页「在世界页打开」带本章叙事时刻——回放观察与录入同焦点）。
  // 走 jumpToTime 而非 setCurrentTime：load() 未 await（挂载即消费 query），服务端恢复值
  // 在 await 之后才落——jumpToTime 登记 pendingDeepLinkTime 保证深链值后到后赢
  const time = route.query.time
  if (typeof time === 'string' && time !== '' && Number.isFinite(Number(time))) {
    jumpToTime(Math.max(0, Math.floor(Number(time))))
  }
  // 地点深链：数据可能仍在 load → 挂起，由下方 watch(locations) 兜底消费
  const loc = route.query.loc
  if (typeof loc === 'string' && loc) pendingLocId.value = loc
  // M5 伏笔深链（写作页「头顶的线」点击）：?fs=ledger_key 或 id，watch(foreshadows) 兜底
  const fs = route.query.fs
  if (typeof fs === 'string' && fs) pendingFsKey.value = fs
  // M5 面板深链：?panel=expectations|worldview → 直接开对应模态（账本族内容无独立图标，模态是唯一入口）。
  // 02 期 §9：?panel= 扩展接受图标栏全 8 键 → 走 togglePanel（与点击图标同一路径，开/关/互斥语义一致）；未映射值静默忽略
  const panel = route.query.panel
  if (panel === 'expectations') showExpectations.value = true
  else if (panel === 'worldview') showWorldview.value = true
  else if (typeof panel === 'string' && panel) {
    const panelKeys: SidePanelKey[] = ['cand', 'fs', 'exp', 'canon', 'loc', 'evt', 'character', 'faction', 'asset']
    if (panelKeys.includes(panel as SidePanelKey)) {
      if (activePanel.value !== panel) togglePanel(panel as SidePanelKey)
    }
  }
}

const pendingLocId = ref<string | null>(null)
watch(locations, (list) => {
  if (!pendingLocId.value || !list.length) return
  const loc = list.find((l) => l.id === pendingLocId.value)
  if (loc) {
    pendingLocId.value = null
    // 内部构造不上图——深链进它的唯一「面」是详情抽屉；顶层维持定位地图
    if (loc.parent_id) selectedLocId.value = loc.id
    else focusLocation(loc)
  }
})

// M5 伏笔深链兜底：数据晚到也能正确打开详情抽屉（按 id 或 ledger_key 双匹配）
const pendingFsKey = ref<string | null>(null)
watch(foreshadows, (list) => {
  if (!pendingFsKey.value || !list.length) return
  const hit = list.find((f) => f.id === pendingFsKey.value || f.ledger_key === pendingFsKey.value)
  if (hit) {
    pendingFsKey.value = null
    selectedForeshadowId.value = hit.id
  }
})

// W2 返程：from=chapter 深链携带来源章 → 页头「返回本章」一键回写作台
const returnChapterId = computed(() => {
  const ch = route.query.chapter
  return route.query.from === 'chapter' && typeof ch === 'string' && ch ? ch : null
})

// 临时在场角色建档深链（2026-09-09 涌现角色闭环）：?create_entity=明姐
// &from=chapter&chapter=… → 打开新建实体卡并预填名字（角色档），作者补档案
// 保存；「返回本章」走既有返程，写作台侧恢复光标。
void (() => {
  const name = route.query.create_entity
  if (typeof name === 'string' && name.trim()) {
    newType.value = 'character'
    newName.value = name.trim()
    newIntro.value = typeof route.query.create_intro === 'string' ? route.query.create_intro : ''
    showEntityForm.value = true
    void nextTick(() => entityNameInputRef.value?.focus())
  }
})()
function returnToChapter() {
  if (!returnChapterId.value) return
  router.push({
    name: 'workspace',
    params: { bookId: String(bookId.value), chapterId: returnChapterId.value },
  })
}

// ===== 侧栏实体搜索 + 重要度排序（承接设定页迁移后的查找需求）=====
const entityFilter = ref('')
interface SidebarEntity {
  name: string
  aliases?: any[]
  importance?: number
}
function filterAndSortEntities<T extends SidebarEntity>(list: T[]): T[] {
  const q = entityFilter.value
  const filtered = q.trim()
    ? list.filter((e) => matchesQuery(q, e.name, ...(e.aliases || []).map(String)))
    : [...list]
  filtered.sort(
    (a, b) => (b.importance || 1) - (a.importance || 1) || a.name.localeCompare(b.name, 'zh'),
  )
  return filtered
}
const visibleCharacters = computed(() => filterAndSortEntities(characters.value))
const visibleFactions = computed(() => filterAndSortEntities(factions.value))
const visibleAssets = computed(() => filterAndSortEntities(assets.value))

// ===== 拼音检索懒加载（二期）：任一抽屉搜索框有输入才拉 pinyin-pro（数百 KB，无搜索零成本） =====
watch([entityFilter, evtFilter, locFilter], ([a, b, c]) => {
  if (a.trim() || b.trim() || c.trim()) void ensurePinyin()
})

// ===== 角色存活状态点（worldState 按当前时刻推演；无事件的角色不标 = 默认活着） =====
const charAliveById = computed(() => {
  const m = new Map<string, boolean>()
  for (const cs of worldState.value.character_states) m.set(cs.entity_id, cs.alive)
  return m
})

// ===== 资产抽屉分组（单分组 2026-09-03）：组内保持重要度序，未分组恒居首 =====
const panelEntityGroups = computed(() =>
  activePanel.value === 'asset'
    ? groupEntities(visibleAssets.value)
    : [{ name: null as string | null, entities: panelEntities.value }],
)
/** 全部未分组（或角色/势力面板）→ 平铺渲染不出组头：存量书零视觉变化 */
const showGroupHeaders = computed(
  () => panelEntityGroups.value.length > 1 || panelEntityGroups.value[0]?.name != null,
)
const collapsedGroups = ref(new Set<string>())
function toggleGroup(name: string | null) {
  const key = name ?? ''
  if (collapsedGroups.value.has(key)) collapsedGroups.value.delete(key)
  else collapsedGroups.value.add(key)
}
function isGroupCollapsed(name: string | null) {
  return collapsedGroups.value.has(name ?? '')
}
</script>

<template>
  <div class="world-view">
    <div class="world-body">
      <div class="world-canvas">
        <!-- 水印题字（M6 活舆图：书名 + 世界统计，纸面水印质感） -->
        <div class="atlas-watermark">
          <div class="aw-title">{{ bookTitle ? `《${bookTitle}》` : '世界设定' }}</div>
          <div class="aw-sub">
            {{ topLocationCount }} 地点 · {{ events.length }} 事件 ·
            {{ characters.length + factions.length + assets.length }} 实体
          </div>
        </div>

        <!-- 罗盘（点击回到全图：视野收拢到底图+地点+实体；针平时轻摆、点击大摆归北）。
             02 期 §5.1：常驻「全图」caption 治「hover 才知用途」 -->
        <button
          class="atlas-compass"
          :class="{ 'is-home': compassHome, 'is-avoid': rightDrawerOpen }"
          title="回到全图"
          aria-label="回到全图视野"
          @click="onCompassClick"
        >
          <svg viewBox="0 0 80 92" aria-hidden="true">
            <g transform="translate(40,46)" stroke="rgba(110,85,45,.42)" fill="none">
              <circle r="30" stroke-width="1" />
              <circle r="23" stroke-width=".6" stroke-dasharray="2 3" />
              <g class="ac-needle">
                <path d="M0,-30 L5,0 L0,30 L-5,0 Z" fill="rgba(110,85,45,.35)" stroke="none" />
                <path d="M-30,0 L0,-5 L30,0 L0,5 Z" fill="rgba(110,85,45,.2)" stroke="none" />
              </g>
            </g>
            <text x="40" y="10" text-anchor="middle" font-size="10" fill="rgba(110,85,45,.55)" font-family="serif">北</text>
          </svg>
          <span class="ac-caption" aria-hidden="true">全图</span>
        </button>

        <!-- 单一画布：实体/关系/事件/疆域全部在地图（脑图已并入，M4 收敛） -->
        <div
          class="world-map-wrap"
          :class="{ 'is-picking': pickingMode !== null }"
          @drop.prevent="onDropMap"
          @dragover.prevent
        >
          <WorldMap
            ref="mapRef"
            :book-id="bookId"
            :picking-mode="pickingMode"
            :draw-mode="drawMode"
            :map-scale="(store.currentBook.value as any)?.map_scale ?? null"
            :highlight-location-id="highlightedLocId"
            @pick="onPick"
            @draw-complete="onDrawComplete"
            @entity-click="(id: string) => (selectedEntityId = id)"
            @location-detail="openLocDetail"
            @location-highlight="onMapLocationHighlight"
          />
        </div>

        <!-- 悬浮胶囊工具条（M6：取代旧顶栏——主动作唯一，低频收进 ⋯） -->
        <div class="atlas-pill">
          <button class="ap-btn ap-btn--icon" title="返回书架（可在此切换书籍）" @click="goLibrary">
            <Icon name="arrow-left" :size="14" />
          </button>
          <button
            v-if="returnChapterId"
            class="ap-btn"
            title="返回刚才写作的章节（写作台）"
            @click="returnToChapter"
          >
            ↩ 返回本章
          </button>
          <span class="ap-sep"></span>
          <button class="ap-btn ap-btn--primary" title="一句话记下刚发生的事——新提到的人名地名一并认出（Alt+N）" @click="openQuickNote">
            <Icon name="flag" :size="13" />
            记一笔历史
          </button>
          <button
            class="ap-btn"
            :class="{ 'ap-btn--on': pickingMode === 'location' }"
            :disabled="pickingMode !== null"
            @click="startPickLocation"
          >
            <Icon name="map-pin" :size="13" />
            {{ pickingMode === 'location' ? '点地图选位置…（Esc 取消）' : '地点' }}
          </button>
          <button class="ap-btn" @click="showEntityForm = true">
            <Icon name="plus" :size="13" />
            实体
          </button>
          <span class="ap-sep"></span>
          <button class="ap-btn" title="世界观文本（背景/规则/历史——进 AI 生成上下文）" @click="showWorldview = true">
            世界观
          </button>
          <div class="ap-more">
            <button class="ap-btn ap-btn--icon" title="更多（批量 / 导入 / 撤销重做）" aria-label="更多" @click.stop="moreOpen = !moreOpen">
              ⋯
            </button>
            <div v-if="moreOpen" class="ap-menu" @click.stop>
              <button class="ap-menu-item" title="拉一条你有感觉的距离，从此地图上的距离有了人话" @click="startCalibrate()">
                ⚖ 标定比例尺
              </button>
              <button class="ap-menu-item" @click="(showBulkImport = true), (moreOpen = false)">
                批量导入 TSV
              </button>
              <button class="ap-menu-item" @click="migrateLegacy(); moreOpen = false">
                导入旧设定
              </button>
              <div class="ap-menu-sep"></div>
              <button class="ap-menu-item" :disabled="!canUndo" @click="handleUndo(); moreOpen = false">
                撤销{{ lastDesc ? `：${lastDesc}` : '' }}
              </button>
              <button class="ap-menu-item" :disabled="!canRedo" @click="handleRedo(); moreOpen = false">
                重做
              </button>
            </div>
          </div>
        </div>
        <div v-if="moreOpen" class="ap-backdrop" @click="moreOpen = false"></div>

        <!-- 实体详情抽屉（点地图人物/脑图节点/侧栏卡片打开；从面板钻入时带「← 返回上一级」） -->
        <EntityDetailDrawer
          v-if="selectedEntityId"
          :book-id="bookId"
          :entity-id="selectedEntityId"
          :can-go-back="!!detailReturnPanel"
          @close="onDetailClosed(() => (selectedEntityId = null))"
          @back="onDetailBack(() => (selectedEntityId = null))"
          @quick-event="onQuickEvent"
          @focus-event="focusEvent"
        />

        <!-- 地点详情抽屉（地图 popup 详情/地点列表/深链打开——内部构造的家） -->
        <LocationDetailDrawer
          v-if="selectedLocId"
          :book-id="bookId"
          :location-id="selectedLocId"
          :can-go-back="!!detailReturnPanel"
          @close="onDetailClosed(() => (selectedLocId = null))"
          @back="onDetailBack(() => (selectedLocId = null))"
          @locate="(loc: WorldLocation) => focusLocation(loc)"
        />

        <!-- 伏笔详情抽屉（M5：侧栏账本行/写作页 ?fs= 深链/弧线带「编辑详情」打开） -->
        <ForeshadowDetailDrawer
          v-if="selectedForeshadowId"
          :book-id="bookId"
          :foreshadow-id="selectedForeshadowId"
          :can-go-back="!!detailReturnPanel"
          @close="onDetailClosed(() => (selectedForeshadowId = null))"
          @back="onDetailBack(() => (selectedForeshadowId = null))"
        />

        <!-- 真相详情抽屉（C1：账本行唤起——表里两面就地编辑） -->
        <CanonTruthDetailDrawer
          v-if="selectedTruthId"
          :book-id="bookId"
          :node-id="selectedTruthId"
          :can-go-back="!!detailReturnPanel"
          @close="onDetailClosed(() => (selectedTruthId = null))"
          @back="onDetailBack(() => (selectedTruthId = null))"
        />
      </div>

      <!-- M6 图标栏：原右侧栏收成右缘 46px 栏，点图标浮出抽屉（同一时间只开一格）。
           02 期 §2 分组：收件 / 账本 / 名册——按钮顺序逐位不变，仅分隔线易位 + 组首标签 -->
      <div class="atlas-rail">
        <!-- 待确认常驻（2026-08-25 修复冷启动自锁：抽屉承载「通读本书」入口，
             空箱时隐藏图标 = 填满收件箱的入口在收件箱为空时不可达） -->
        <span class="ar-group" aria-hidden="true">收件</span>
        <button
          class="ar-btn"
          :class="{ 'ar-btn--on': activePanel === 'cand', 'ar-btn--peek': detailReturnPanel === 'cand' }"
          :aria-pressed="activePanel === 'cand'"
          title="待确认 · 候选事件"
          @click="togglePanel('cand')"
        >
          <Icon name="clock" :size="15" />
          <span v-if="pendingCandidates.length" class="ar-n">{{ pendingCandidates.length }}</span>
        </button>
        <span class="ar-sep"></span>
        <span class="ar-group" aria-hidden="true">账本</span>
        <button
          class="ar-btn"
          :class="{ 'ar-btn--on': activePanel === 'fs', 'ar-btn--peek': detailReturnPanel === 'fs' }"
          :aria-pressed="activePanel === 'fs'"
          title="伏笔"
          @click="togglePanel('fs')"
        >
          <Icon name="link" :size="15" />
          <span class="ar-n">{{ foreshadows.length }}</span>
        </button>
        <button
          class="ar-btn"
          :class="{ 'ar-btn--on': activePanel === 'exp', 'ar-btn--peek': detailReturnPanel === 'exp' }"
          :aria-pressed="activePanel === 'exp'"
          title="期待"
          @click="togglePanel('exp')"
        >
          <Icon name="sparkles" :size="15" />
          <span class="ar-n">{{ mirrorSummary?.active ?? 0 }}</span>
        </button>
        <button
          class="ar-btn"
          :class="{ 'ar-btn--on': activePanel === 'canon', 'ar-btn--peek': detailReturnPanel === 'canon' }"
          :aria-pressed="activePanel === 'canon'"
          title="真相账本——读者知道与不知道的事，秘密 AI 替你守住"
          @click="togglePanel('canon')"
        >
          <Icon name="truth" :size="15" />
          <span class="ar-n">{{ canonNodes.length }}</span>
        </button>
        <span class="ar-sep"></span>
        <span class="ar-group" aria-hidden="true">名册</span>
        <button
          class="ar-btn"
          :class="{ 'ar-btn--on': activePanel === 'loc', 'ar-btn--peek': detailReturnPanel === 'loc' }"
          :aria-pressed="activePanel === 'loc'"
          title="地点"
          @click="togglePanel('loc')"
        >
          <Icon name="map-pin" :size="15" />
          <span class="ar-n">{{ topLocationCount }}</span>
        </button>
        <button
          class="ar-btn"
          :class="{ 'ar-btn--on': activePanel === 'evt', 'ar-btn--peek': detailReturnPanel === 'evt' }"
          :aria-pressed="activePanel === 'evt'"
          title="事件"
          @click="togglePanel('evt')"
        >
          <Icon name="flag" :size="15" />
          <span class="ar-n">{{ events.length }}</span>
        </button>
        <button
          class="ar-btn"
          :class="{ 'ar-btn--on': activePanel === 'character', 'ar-btn--peek': detailReturnPanel === 'character' }"
          :aria-pressed="activePanel === 'character'"
          title="角色"
          @click="togglePanel('character')"
        >
          <Icon name="user" :size="15" />
          <span class="ar-n">{{ characters.length }}</span>
        </button>
        <button
          class="ar-btn"
          :class="{ 'ar-btn--on': activePanel === 'faction', 'ar-btn--peek': detailReturnPanel === 'faction' }"
          :aria-pressed="activePanel === 'faction'"
          title="势力"
          @click="togglePanel('faction')"
        >
          <Icon name="users" :size="15" />
          <span class="ar-n">{{ factions.length }}</span>
        </button>
        <button
          class="ar-btn"
          :class="{ 'ar-btn--on': activePanel === 'asset', 'ar-btn--peek': detailReturnPanel === 'asset' }"
          :aria-pressed="activePanel === 'asset'"
          title="资产"
          @click="togglePanel('asset')"
        >
          <Icon name="star" :size="15" />
          <span class="ar-n">{{ assets.length }}</span>
        </button>
      </div>

      <!-- 图标栏抽屉（2026-09 外壳重构）：全高 340px 贴边浮层，与详情抽屉形态统一；
           统一骨架 DrawerShell（头部/搜索/滚动区），cand/exp/loc/evt/实体五类挂壳，
           伏笔/真相自带完整分区头直接平铺。互斥与「← 返回上一级」机制不变。 -->
      <Transition name="drawer">
      <aside v-if="activePanel" class="atlas-drawer">
        <!-- 待确认（W4 候选回流：写作沉淀/完稿抽出的候选事件，跨章全貌；A5b 批量裁决） -->
        <template v-if="activePanel === 'cand'">
        <DrawerShell icon="clock" title="待确认" :count="pendingCandidates.length" count-pending @close="activePanel = null">
          <template #actions>
            <button
              class="side-batch-btn"
              title="AI 自己通读全书正文：先认人（你过目后才建），再把发现的世界变化放进这里"
              @click="openReadBook"
            >通读本书</button>
            <button
              v-if="pendingCandidates.length"
              class="side-batch-btn"
              title="逐条预览后批量采纳（可剔除，确认后 6 秒内可整批撤销）"
              @click="batchOpen = true"
            >全部采纳</button>
          </template>
          <ul
            class="side-list cand-kb"
            tabindex="0"
            title="点一下这里就能用键盘批：↑↓ 选条，→ 或 Enter 采纳，← 或 Delete 丢弃"
            @keydown="onCandListKeydown"
          >
            <li
              v-for="(c, i) in pendingCandidates"
              :key="c.id"
              class="side-card"
              :class="{ 'cand-cursor': i === candCursor }"
              :title="candTitleOf(c)"
            >
              <div class="sc-body">
                <span class="sc-name">{{ c.source === 'canon_extract' ? (c.draft?.label || '真相候选') : (c.draft?.summary || eventTypeLabel(c.draft?.event_type || 'custom')) }}</span>
                <span class="sc-badge">
                  <template v-if="c.source === 'canon_extract'">◉ 真相候选 · 待核实</template>
                  <template v-else>{{ eventTypeLabel(c.draft?.event_type || 'custom') }} · {{ displayCandidateTime(c.draft?.time_start || 0, c.chapter_number) }}</template>
                </span>
              </div>
              <div class="sc-actions">
                <button class="sc-act" :title="c.source === 'canon_extract' ? '记入真相账本（草稿，去核实）' : '采纳入账（进入世界推算）'" :disabled="busyCandidateId === c.id" @click.stop="acceptCand(c)">✓</button>
                <button class="sc-act sc-act--danger" title="丢弃" :disabled="busyCandidateId === c.id" @click.stop="rejectCand(c)">✗</button>
              </div>
            </li>
          </ul>
          <!-- 冷启动空态（图标栏改为常驻后，空箱是第一印象场景）：引导通读首秀 -->
          <p v-if="!pendingCandidates.length" class="side-empty">
            还没有待确认的世界变化。点上方「通读本书」，让 AI 自己把已写的章节读一遍——它发现的都会放进这里等你过目。
          </p>
        </DrawerShell>
        </template>

        <!-- 伏笔账本（M5：全量列表——弧线带只渲染有锚的，未锚定的唯一可见处在此；
             自带完整分区头，直接平铺不套壳） -->
        <template v-if="activePanel === 'fs'">
        <div class="drawer-scroll">
          <ForeshadowSection :book-id="bookId" @select="(id: string) => (selectedForeshadowId = id)" />
        </div>
        </template>

        <!-- 期待（M5：摘要 + 打开账本模态；与写作页「头顶的线」同源） -->
        <template v-if="activePanel === 'exp'">
        <DrawerShell icon="sparkles" title="期待" :count="mirrorSummary?.active ?? 0" @close="activePanel = null">
          <div class="exp-summary">
            <p v-if="mirrorSummary?.active" class="exp-summary-text">
              活跃 {{ mirrorSummary.active }} 条<template v-if="mirrorSummary.due">
                · <span class="exp-due">{{ mirrorSummary.due }} 条该收了</span>
              </template>
            </p>
            <p v-else class="exp-summary-text">还没有期待。用一句话记下读者此刻最想知道的事。</p>
            <button class="exp-open" @click="showExpectations = true">打开账本</button>
          </div>
        </DrawerShell>
        </template>

        <!-- 真相账本（C1：Canon 融入——表里三态过滤 + 句子优先录入；详情在真相详情抽屉；
             自带完整分区头，直接平铺不套壳） -->
        <template v-if="activePanel === 'canon'">
        <div class="drawer-scroll">
          <CanonSection
            :book-id="bookId"
            @select="(id: string) => (selectedTruthId = id)"
            @select-entity="(id: string) => (selectedEntityId = id)"
          />
        </div>
        </template>

        <!-- 地点（折叠树：整条点击=开详情抽屉；📍=定位地图（顶层有坐标专属）；
             折叠按顶层整枝剪除，搜索命中时自动展开并整枝保留） -->
        <template v-if="activePanel === 'loc'">
        <DrawerShell icon="map-pin" title="地点" :count="topLocationCount" @close="activePanel = null">
          <template #actions>
            <button class="side-batch-btn" title="收起抽屉，在地图上点选新建" @click="createFromLocPanel">＋ 新建</button>
          </template>
          <template #search>
            <div class="evt-filter">
              <Icon name="magnifying-glass" :size="12" class="evt-filter-icon" />
              <input v-model="locFilter" class="evt-filter-input" placeholder="搜索地点（名字）…" />
            </div>
          </template>
          <ul v-if="orderedLocations.length" class="side-list">
            <li
              v-for="{ loc, depth } in orderedLocations"
              :key="loc.id"
              class="side-card side-card--click"
              :class="{ 'side-card--hl': highlightedRowLocId === loc.id }"
              :data-loc-id="loc.id"
              :style="depth ? { paddingLeft: `${8 + depth * 14}px` } : undefined"
              title="点击看详情与内部构造 · 双击名字改名"
              @click="openLocDetail(loc.id)"
            >
              <span class="loc-caret-slot">
                <button
                  v-if="(locChildren.get(loc.id) || []).length"
                  class="loc-caret"
                  :class="{ 'loc-caret--collapsed': isLocCollapsed(loc.id) }"
                  :title="isLocCollapsed(loc.id) ? `展开内部构造（${(locChildren.get(loc.id) || []).length}）` : '收起内部构造'"
                  aria-label="展开或收起内部构造"
                  @click.stop="toggleLocCollapse(loc.id)"
                >
                  <Icon name="chevron-down" :size="10" />
                </button>
              </span>
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
                <span v-if="depth > 0" class="sc-badge sc-badge--inner">内部</span>
                <span v-else class="sc-badge">{{ LOC_KIND_LABEL[loc.kind] || loc.kind }}</span>
              </div>
              <div class="sc-actions">
                <button
                  v-if="depth === 0 && loc.coord_x != null"
                  class="sc-act sc-act--locate"
                  title="在地图上定位（平移居中）"
                  @click.stop="focusLocation(loc)"
                >
                  <Icon name="map-pin" :size="13" />
                </button>
                <button class="sc-act" title="详情 / 内部构造" @click.stop="openLocDetail(loc.id)">
                  <Icon name="information-circle" :size="13" />
                </button>
                <button class="sc-act sc-act--danger" title="删除" @click.stop="removeLoc(loc)">
                  <Icon name="trash" :size="13" />
                </button>
              </div>
            </li>
          </ul>
          <div v-else class="side-empty">
            {{ locFilter ? `没有匹配「${locFilter}」的地点` : '还没有地点。点上方「＋ 新建」，在地图上点选第一个落脚点。' }}
          </div>
        </DrawerShell>
        </template>

        <!-- 事件（纵向编年脊柱：年份分组头承担年份、卡内短日期；整卡点击=定位地图） -->
        <template v-if="activePanel === 'evt'">
        <DrawerShell icon="flag" title="事件" :count="filteredEvents.length" @close="activePanel = null">
          <template #actions>
            <button class="side-batch-btn" title="一句话记一笔（AI 解析成草稿，你过目后入账）" @click="openQuickNote">＋ 记一笔</button>
          </template>
          <template #search>
            <div class="evt-filter">
              <Icon name="magnifying-glass" :size="12" class="evt-filter-icon" />
              <input v-model="evtFilter" class="evt-filter-input" placeholder="筛选事件（类型 / 备注）…" />
            </div>
          </template>
          <EventSpineList
            v-if="filteredEvents.length"
            :events="filteredEvents"
            @focus="focusEvent"
            @edit="openEditEvent"
            @delete="removeEvent"
          />
          <div v-else class="side-empty">
            {{ evtFilter ? '没有匹配的事件' : '还没有事件。事件是世界状态的唯一事实源——点上方「＋ 记一笔」记录第一条。' }}
          </div>
        </DrawerShell>
        </template>

        <!-- 实体（角色/势力/资产）：搜索 + 重要度排序 + 紧凑单行矩阵 -->
        <template v-if="activePanel === 'character' || activePanel === 'faction' || activePanel === 'asset'">
        <DrawerShell
          :icon="activePanel === 'character' ? 'user' : activePanel === 'faction' ? 'users' : 'star'"
          :title="activePanel === 'character' ? '角色' : activePanel === 'faction' ? '势力' : '资产'"
          :count="panelEntities.length"
          @close="activePanel = null"
        >
          <template #actions>
            <button class="side-batch-btn" title="新建实体（类型已按当前抽屉选好，弹窗里可改）" @click="createFromEntityPanel">＋ 新建</button>
          </template>
          <template #search>
            <div class="evt-filter">
              <Icon name="magnifying-glass" :size="12" class="evt-filter-icon" />
              <input v-model="entityFilter" class="evt-filter-input" placeholder="搜索实体（名字 / 别名）…" />
            </div>
          </template>
          <div v-if="panelEntities.length" class="side-list">
            <template v-for="group in panelEntityGroups" :key="group.name ?? '__ungrouped__'">
              <button
                v-if="showGroupHeaders"
                class="side-group-head"
                :title="isGroupCollapsed(group.name) ? '展开分组' : '收起分组'"
                @click="toggleGroup(group.name)"
              >
                <Icon
                  name="chevron-down"
                  :size="10"
                  class="side-group-chevron"
                  :class="{ 'side-group-chevron--collapsed': isGroupCollapsed(group.name) }"
                />
                <span>{{ group.name ?? '未分组' }}</span>
                <span class="side-group-count">{{ group.entities.length }}</span>
              </button>
              <template v-if="!isGroupCollapsed(group.name)">
                <EntityCard
                  v-for="ent in group.entities"
                  :key="ent.id"
                  :entity="ent"
                  :alive="activePanel === 'character' ? (charAliveById.get(ent.id) ?? null) : null"
                  @click="selectedEntityId = ent.id"
                  @update:name="(n: string) => renameEntity(bookId, ent.id, n)"
                  @delete="removeEntity(ent)"
                />
              </template>
            </template>
          </div>
          <div v-else class="side-empty">{{ entityEmptyText }}</div>
        </DrawerShell>
        </template>
      </aside>
      </Transition>
    </div>

    <!-- 时间轴（拖动改变 currentTime，地图人物位置/疆域随之回放；右键可记录事件/标记章节锚） -->
    <WorldTimeline
      @focus-event="focusEvent"
      @new-event-at="onNewEventAt"
      @edit-foreshadow="(id: string) => (selectedForeshadowId = id)"
    />

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

    <!-- 世界速记（关联式录入：一句话带出新人物/新地点；裸入口唤起，Alt+N 页面激活即可） -->
    <QuickEventNote
      ref="quickNoteRef"
      :book-id="bookId"
      :chapter-id="null"
      :enable-map-pick="true"
      @committed="onQuickNoteCommitted"
      @open-template-form="onQuickNoteToTemplate"
      @request-map-pick="onQuickNoteMapPick"
      @request-map-pick-cancel="onQuickNotePickCancel"
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

    <!-- 期待账本（M5：侧栏「打开账本」/ ?panel=expectations 深链） -->
    <ReaderMirrorModal
      v-if="showExpectations"
      :book-id="bookId"
      @close="showExpectations = false"
    />

    <!-- 世界观文本（M5：顶栏「世界观」/ ?panel=worldview 深链） -->
    <WorldviewModal
      v-if="showWorldview"
      :book-id="bookId"
      @close="showWorldview = false"
    />

    <!-- A5b 批量裁决模态（待确认分区「全部采纳」唤起） -->
    <BatchAcceptModal
      v-if="batchOpen"
      :candidates="pendingCandidates"
      :busy="batchBusy"
      :progress="batchProgress"
      @confirm="onBatchConfirm"
      @close="batchOpen = false"
    />

    <!-- 全书通读模态（2026-08-25「系统自己去读」存量首秀：认人→过目→记事） -->
    <ReadBookModal
      v-if="readBookOpen"
      :phase="readBook.phase.value"
      :progress="readBook.progress.value"
      :entity-candidates="readBook.entityCandidates.value"
      :location-candidates="readBook.locationCandidates.value"
      :created-entities="readBook.createdEntities.value"
      :created-candidates="readBook.createdCandidates.value"
      :skipped-count="readBook.skippedCount.value"
      :error-msg="readBook.errorMsg.value"
      :review-count="readBook.reviewCount.value"
      :creating="readBook.creating.value"
      :create-progress="readBook.createProgress.value"
      :depiction-candidates="readBook.depictionCandidates.value"
      :confirmed-depictions="readBook.confirmedDepictions.value"
      :depiction-review-count="readBook.depictionReviewCount.value"
      @cancel="readBook.cancel()"
      @confirm-entities="onReadBookConfirmEntities"
      @confirm-depictions="onReadBookConfirmDepictions"
      @close="onReadBookClose"
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
    <!-- D4 比例尺标定·选档卡（拉线完成弹出：这段路相当于？） -->
    <Teleport to="body">
      <div v-if="calibDialog" class="calib-backdrop" @click.self="calibDialog = null">
        <div class="calib-card">
          <div class="calib-title">这段路相当于？</div>
          <div class="calib-modes">
            <button v-for="m in [{k:'foot',l:'步行一天'},{k:'horse',l:'骑马一天'},{k:'boat',l:'乘船一天'},{k:'custom',l:'自定义'}]" :key="m.k"
              class="calib-mode" :class="{ 'is-on': calibMode === m.k }" @click="calibMode = m.k as any">{{ m.l }}</button>
          </div>
          <div class="calib-custom">
            <input v-model="calibDays" type="number" min="0.1" step="0.5" class="calib-input" />
            <span>{{ calibMode === 'custom' ? '天（步行）' : '× 天数（默认 1）' }}</span>
          </div>
          <div class="calib-actions">
            <button class="calib-btn" @click="calibDialog = null">取消</button>
            <button class="calib-btn calib-btn--primary" @click="saveCalibration">标定</button>
          </div>
          <p class="calib-hint">{{ calibPrefilled
            ? '已按空白舆图地球尺度预填（图宽≈赤道一圈 ≈1336 天步程）——可改可推翻。'
            : '可标多条取平均（≤5）；重标随时，全部距离即时重算。' }}</p>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.world-view {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--bg-primary);
  /* 页面级层叠隔离（00 期 §3.3）：页内野生 z 值（胶囊条/图标栏/时间轴弹层 640-1200）
     只在本上下文内竞争，必然低于全局模态(110)与 toast(120) */
  isolation: isolate;
}

/* ===== M6 活舆图：水印题字 / 装饰 / 罗盘 ===== */
.atlas-watermark {
  position: absolute;
  left: 40px;
  top: 64px;
  z-index: 640; /* Leaflet pane 内 marker 600 之上、vignette 645 之下——做纸面水印 */
  pointer-events: none;
  user-select: none;
  color: rgba(74, 68, 56, 0.28);
}
.aw-title {
  font-family: var(--font-atlas); /* 古地图字体恒定衬线（主题系统 01 §7 豁免） */
  font-size: 38px;
  font-weight: 700;
  letter-spacing: 0.22em;
}
.aw-sub {
  margin-top: 6px;
  font-size: var(--text-xs);
  letter-spacing: 0.34em;
  color: rgba(74, 68, 56, 0.48); /* 水印副行保持淡，但要读得出 */
}
.atlas-compass {
  position: absolute;
  right: 64px;
  bottom: 18px;
  width: 64px;
  height: 90px; /* 02 期 §5.1：svg 73.6 + caption 12 + 间距——加高容纳「全图」标签 */
  z-index: 660; /* 越过烛光暗角（645）——角落里的罗盘不该被压暗 */
  padding: 0;
  border: none;
  background: transparent;
  cursor: pointer;
  user-select: none;
  opacity: 0.75;
  /* right 过渡供抽屉避让（transform 军规：常驻位移会半像素位图模糊，只动 right） */
  transition: opacity 0.15s, transform 0.15s, right 0.2s ease;
}
/* 右缘抽屉在场时左移避让：避让位 = 抽屉 right 58 + 宽 340 + 间距 16 */
.atlas-compass.is-avoid {
  right: 414px;
}
.atlas-compass svg {
  display: block;
}
/* 02 期 §5.1 常驻 caption：功能自解释（点击回全图） */
.ac-caption {
  display: block;
  margin-top: 2px;
  font-size: var(--text-xs);
  line-height: 1;
  color: var(--text-muted);
  text-align: center;
}
.atlas-compass:hover {
  opacity: 1;
  transform: scale(1.06);
}
.atlas-compass:focus-visible {
  outline: 2px solid rgba(124, 106, 173, 0.55);
  outline-offset: 2px;
  border-radius: var(--radius-md);
}
/* 罗盘针：transform-box 让 SVG 内 rotate 绕自身中心（针形对称，盒中心即盘心） */
.ac-needle {
  transform-box: fill-box;
  transform-origin: center;
  animation: compass-sway 5.6s ease-in-out infinite;
}
.atlas-compass.is-home .ac-needle {
  animation: compass-home 1.45s ease-out 1;
}
/* 平时轻摆：荡—收—歇（末段停 0° 作间歇，循环不显机械） */
@keyframes compass-sway {
  0% { transform: rotate(0deg); }
  12% { transform: rotate(6deg); }
  30% { transform: rotate(-4.5deg); }
  48% { transform: rotate(3deg); }
  64% { transform: rotate(-1.5deg); }
  78%, 100% { transform: rotate(0deg); }
}
/* 点击「回到全图」：大摆过北再阻尼回稳（360°≡0°，恰好接回轻摆） */
@keyframes compass-home {
  0% { transform: rotate(0deg); }
  28% { transform: rotate(372deg); }
  48% { transform: rotate(342deg); }
  66% { transform: rotate(368deg); }
  82% { transform: rotate(355deg); }
  100% { transform: rotate(360deg); }
}
@media (prefers-reduced-motion: reduce) {
  .ac-needle { animation: none; }
}

/* ===== M6 悬浮胶囊工具条 ===== */
/* ⚠ 浮层禁用 transform 居中：translate(-50%) 落在半像素时整层位图化偏移，
   文字与边框一起发虚（曾致「真相」账本整格模糊）。一律 margin auto 居中。 */
.atlas-pill {
  position: absolute;
  top: 14px;
  left: 0;
  right: 0;
  margin-inline: auto;
  width: fit-content;
  z-index: 750;
  display: flex;
  align-items: center;
  gap: 3px;
  padding: 4px 6px;
  background: rgba(244, 238, 225, 0.92);
  backdrop-filter: blur(4px);
  border: 1px solid rgba(107, 90, 68, 0.3);
  border-radius: 9999px;
  box-shadow: var(--elev-3-shadow);
}
.ap-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 6px 13px;
  border: none;
  border-radius: 9999px;
  background: transparent;
  color: rgba(74, 68, 56, 0.88);
  font-size: var(--text-sm);
  font-family: inherit;
  cursor: pointer;
  white-space: nowrap;
  transition: background 0.12s ease;
}
.ap-btn:hover:not(:disabled) {
  background: rgba(120, 95, 50, 0.1);
}
.ap-btn:disabled {
  opacity: 0.55;
  cursor: default;
}
.ap-btn--icon {
  padding: 6px 9px;
}
.ap-btn--primary {
  background: var(--accent-500);
  color: #f8f5ee;
  font-weight: 500;
}
.ap-btn--primary:hover:not(:disabled) {
  background: var(--accent-600);
}
.ap-btn--on {
  background: rgba(245, 158, 11, 0.14);
  color: var(--warn);
}
.ap-sep {
  width: 1px;
  height: 16px;
  background: rgba(107, 90, 68, 0.25);
  margin: 0 3px;
}
.ap-more {
  position: relative;
}
.ap-menu {
  position: absolute;
  top: calc(100% + 8px);
  right: 0;
  min-width: 168px;
  background: rgba(249, 242, 226, 0.98);
  border: 1px solid rgba(107, 90, 68, 0.3);
  border-radius: var(--radius-lg);
  box-shadow: var(--elev-3-shadow);
  padding: 5px;
  z-index: 760;
}
.ap-menu-item {
  display: block;
  width: 100%;
  padding: 7px 10px;
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  color: rgba(74, 68, 56, 0.88);
  font-size: var(--text-base);
  font-family: inherit;
  text-align: left;
  cursor: pointer;
}
.ap-menu-item:hover:not(:disabled) {
  background: rgba(120, 95, 50, 0.1);
}
.ap-menu-item:disabled {
  opacity: 0.45;
  cursor: default;
}
.ap-menu-sep {
  height: 1px;
  background: rgba(107, 90, 68, 0.18);
  margin: 4px 6px;
}
.ap-backdrop {
  position: fixed;
  inset: 0;
  z-index: 745;
}

/* ===== M6 图标栏 + 浮出抽屉 ===== */
.atlas-rail {
  position: absolute;
  right: 0;
  top: 0;
  bottom: 0;
  margin-block: auto;
  height: fit-content;
  z-index: 750;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 3px;
  padding: 8px 6px;
  background: rgba(236, 228, 211, 0.92);
  backdrop-filter: blur(3px);
  border: 1px solid rgba(107, 90, 68, 0.28);
  border-right: none;
  border-radius: 12px 0 0 12px;
  box-shadow: var(--elev-3-shadow);
}
.ar-btn {
  position: relative;
  width: 34px;
  height: 34px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: none;
  border-radius: var(--radius-md);
  background: transparent;
  color: rgba(109, 90, 60, 0.75);
  cursor: pointer;
  transition: all 0.12s ease;
}
.ar-btn:hover {
  background: rgba(120, 95, 50, 0.1);
  color: rgba(74, 68, 56, 0.95);
}
.ar-btn:focus-visible,
.ap-btn:focus-visible {
  outline: 2px solid rgba(124, 106, 173, 0.55);
  outline-offset: 1px;
}
/* 02 期 §2.3 组首标签：纯信息元素（aria-hidden），分组语义由按钮自身承担 */
.ar-group {
  font-size: var(--text-xs);
  color: var(--text-muted);
  letter-spacing: 0.08em;
  line-height: 1;
  margin: var(--space-1) 0;
  user-select: none;
}
.ar-btn--on {
  background: color-mix(in srgb, var(--accent-500) 14%, transparent);
  color: var(--accent-500);
  position: relative;
}
/* 02 期 §2.4 当前态左缘指示条：扫视时可定位 */
.ar-btn--on::before {
  content: '';
  position: absolute;
  left: 0;
  top: 20%;
  bottom: 20%;
  width: 2px;
  border-radius: 1px;
  background: var(--accent-500);
}
/* 02 期 §2.4 来路半亮态：详情抽屉是从这个面板长出来的，关掉会回去 */
.ar-btn--peek {
  background: color-mix(in srgb, var(--accent-500) 7%, transparent);
  color: var(--accent-400);
}
.ar-n {
  position: absolute;
  top: 1px;
  right: 3px;
  font-size: var(--text-xs);
  font-weight: 700;
  color: #b08d3e;
  font-variant-numeric: tabular-nums;
}
.ar-sep {
  width: 18px;
  height: 1px;
  background: rgba(107, 90, 68, 0.22);
  margin: 4px 0;
}
/* ===== 图标栏抽屉（2026-09 外壳重构）：全高贴边浮层 =====
   与四个详情抽屉像素级对齐（top:48 / right:58 / bottom:12 / 宽 340 / 圆角 14）——
   开合之间无跳变。Overlay 路线（不参与 flex 布局）：地图容器宽度从不变化，
   Leaflet 无需 invalidateSize（WorldMap 侧零改动）。 */
.atlas-drawer {
  position: absolute;
  top: 48px;
  right: 58px;
  bottom: 12px;
  width: 340px;
  z-index: 740;
  display: flex;
  flex-direction: column;
  background: var(--bg-canvas);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  /* 04 §A2-3：纸叠边+主题大影（旧暖棕调字面影退役） */
  box-shadow: -4px 0 0 -1px var(--paper-edge), var(--shadow-lg);
  overflow: hidden;
}
/* 开合过渡：入场末态 transform 归零（浮层 transform 军规禁的是「居中悬浮态常驻」，
   进场动画终态无 transform，不会留下半像素常驻模糊） */
.drawer-enter-active,
.drawer-leave-active {
  transition: opacity 0.18s ease, transform 0.18s ease;
}
.drawer-enter-from,
.drawer-leave-to {
  opacity: 0;
  transform: translateX(14px);
}
/* 平铺分区（伏笔/真相自带完整分区头，不套 DrawerShell）的滚动容器 */
.drawer-scroll {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 12px;
}
/* 世界页滚动区统一：暖色细条（Chromium/WebKit） */
.drawer-scroll::-webkit-scrollbar {
  width: 8px;
}
.drawer-scroll::-webkit-scrollbar-thumb {
  background: rgba(120, 95, 50, 0.22);
  border-radius: var(--radius-xs);
}
.drawer-scroll::-webkit-scrollbar-thumb:hover {
  background: rgba(120, 95, 50, 0.38);
}
.drawer-scroll::-webkit-scrollbar-track {
  background: transparent;
}

/* ===== 布局 ===== */
.wbtn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 6px 12px;
  border: 1px solid var(--line-faint);
  border-radius: var(--radius-md);
  background: var(--bg-canvas);
  color: var(--text-secondary);
  font-size: var(--text-sm);
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
  box-shadow: var(--glow-accent);
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
  /* M6：图标栏/浮出抽屉是 body 的直接子级，绝对定位锚在此（漏了会锚到视口） */
  position: relative;
}
.world-canvas {
  flex: 1;
  position: relative;
  min-width: 0;
  display: flex;
}
.world-map-wrap {
  flex: 1;
  position: relative;
  min-width: 0;
}
.world-map-wrap.is-picking :deep(.leaflet-container) {
  cursor: crosshair;
}

/* ===== 抽屉内列表条目（沿用原侧栏条目语言；分区头已由 DrawerShell 承担） ===== */
/* 地点折叠箭头槽：固定占位保持名字列对齐（无子级的行不偏移） */
.loc-caret-slot {
  width: 14px;
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}
.loc-caret {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 16px;
  height: 16px;
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  transition: transform 0.15s ease, background 0.12s ease;
}
.loc-caret:hover {
  background: var(--hover-bg);
  color: var(--text-primary);
}
.loc-caret--collapsed {
  transform: rotate(-90deg);
}
.side-group-head {
  display: flex;
  align-items: center;
  gap: 5px;
  width: 100%;
  padding: 2px;
  margin-top: 5px;
  border: none;
  background: transparent;
  font-size: var(--text-xs);
  font-weight: 600;
  font-family: inherit;
  color: var(--text-muted);
  cursor: pointer;
}
.side-group-head:first-child {
  margin-top: 0;
}
.side-group-head:hover {
  color: var(--text-secondary);
}
.side-group-chevron {
  transition: transform 0.15s ease;
}
.side-group-chevron--collapsed {
  transform: rotate(-90deg);
}
.side-group-count {
  margin-left: auto;
  font-weight: 500;
}
/* A5b 待确认分区「全部采纳」——count 的 margin-left:auto 把右缘让给按钮组 */
.side-batch-btn {
  font-size: var(--text-xs);
  color: var(--accent-500);
  background: transparent;
  border: 1px solid var(--accent-500);
  border-radius: 9999px;
  padding: 1px 9px;
  cursor: pointer;
}
.side-batch-btn:hover {
  background: var(--accent-500);
  color: #fff;
}
/* 事件过滤 */
.evt-filter {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 8px;
  padding: 4px 8px;
  border: 1px solid var(--line-faint);
  border-radius: var(--radius-md);
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
  font-size: var(--text-sm);
  font-family: inherit;
  outline: none;
}
.evt-filter-input::placeholder {
  color: var(--text-muted);
}
/* M5 期待摘要分组 */
.exp-summary {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 2px 2px 8px;
}
.exp-summary-text {
  margin: 0;
  font-size: var(--text-xs);
  color: var(--text-muted);
  line-height: 1.6;
}
.exp-due {
  color: var(--danger);
  font-weight: 500;
}
.exp-open {
  align-self: flex-start;
  padding: 4px 12px;
  font-size: var(--text-xs);
  font-family: inherit;
  color: var(--text-secondary);
  background: var(--bg-canvas);
  border: 1px dashed var(--border-color);
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: all 0.12s ease;
}
.exp-open:hover {
  border-color: var(--accent-500);
  color: var(--accent-500);
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
  border: 1px solid var(--line-faint);
  border-radius: var(--radius-lg);
  transition: all 0.15s ease-out;
}
.side-card--click {
  cursor: pointer;
}
.side-card--click:hover {
  border-color: var(--accent-500);
  box-shadow: var(--elev-2-shadow);
}
/* 地图回指行高亮（地标点击 → 面板条目；2.4s 自清） */
.side-card--hl {
  border-color: var(--accent-500);
  background: rgba(124, 106, 173, 0.08);
}
/* 键盘裁决（02 候选回流修缮 M3）：待确认列表获焦态 + 光标行高亮 */
.cand-kb {
  outline: none;
}
.cand-kb:focus-visible {
  outline: 1px solid var(--accent-400);
  outline-offset: 2px;
  border-radius: var(--radius-lg);
}
.side-card.cand-cursor {
  border-color: var(--accent-400);
  background: color-mix(in srgb, var(--accent-400) 8%, transparent);
}
.sc-body {
  flex: 1;
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 8px;
}
.sc-name {
  font-size: var(--text-base);
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
  border-radius: var(--radius-sm);
  font-size: var(--text-base);
  font-weight: 600;
  color: var(--text-primary);
  background: var(--bg-canvas);
  font-family: inherit;
  outline: none;
}
.sc-badge {
  flex-shrink: 0;
  font-size: var(--text-xs);
  color: var(--text-muted);
  background: var(--bg-tertiary);
  border-radius: 9999px;
  padding: 1px 7px;
}
/* 内部构造徽标（缩进子级行 / 子数提示）：与地点类型徽标同形不同色 */
.sc-badge--inner {
  color: var(--accent-400);
  background: rgba(139, 109, 232, 0.1);
}
.sc-actions {
  display: flex;
  gap: 2px;
  flex-shrink: 0;
  opacity: 0;
  transition: opacity 0.15s;
}
/* 02 期 §8 H1：hover 显形补键盘对等（focus-within） */
.side-card:hover .sc-actions,
.side-card:focus-within .sc-actions {
  opacity: 1;
}
.sc-act {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  transition: all 0.12s;
}
.sc-act:hover {
  background: var(--hover-bg);
  color: var(--text-primary);
}
.sc-act--danger {
  opacity: 0.45; /* 02 期 §8 H1 规则三：破坏性操作常态低显 */
}
.sc-act--danger:hover,
.sc-act--danger:focus-visible {
  opacity: 1;
  background: rgba(220, 38, 38, 0.08);
  color: var(--danger);
}
/* 地点行定位按钮（📍 地图联动）：与详情按钮同形，accent 色示「地图动作」 */
.sc-act--locate {
  color: var(--accent-400);
}
.sc-act--locate:hover {
  background: rgba(139, 109, 232, 0.1);
  color: var(--accent-500);
}

/* 空状态 */
.side-empty {
  border: 1px dashed var(--border-color);
  border-radius: var(--radius-lg);
  padding: 14px 12px;
  font-size: var(--text-sm);
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
  font-size: var(--text-sm);
  color: var(--text-secondary);
  margin-bottom: 6px;
}
.form-input {
  width: 100%;
  box-sizing: border-box;
  padding: 8px 10px;
  border: 1px solid var(--line);
  border-radius: var(--radius-md);
  background: var(--bg-canvas);
  color: var(--text-primary);
  font-size: var(--text-sm);
  font-family: inherit;
  transition: border-color 0.15s;
}
.form-input:focus {
  outline: none;
  border-color: var(--accent-500);
  box-shadow: var(--ring-soft);
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
  border: 1px solid var(--line-faint);
  border-radius: var(--radius-md);
  background: var(--bg-canvas);
  color: var(--text-secondary);
  font-size: var(--text-sm);
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

/* D4 标定选档卡 */

.calib-backdrop { position: fixed; inset: 0; z-index: var(--z-modal); /* 标定卡 teleport 在 body，隔离罩不住——按模态语义归位（00 期 §3.1/F-02） */ background: rgba(20,18,16,.35); display: flex; align-items: center; justify-content: center; }
.calib-card { width: 300px; background: var(--bg-canvas); border: 1px solid var(--line-faint); border-radius: var(--radius-lg); padding: 16px 18px; box-shadow: 0 10px 32px rgba(0,0,0,.14); }
.calib-title { font-family: var(--font-heading); font-size: 14px; font-weight: 600; color: var(--text-primary); text-align: center; }
.calib-modes { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; justify-content: center; }
.calib-mode { border: 1px solid var(--line-faint); border-radius: 999px; background: none; font-size: var(--text-sm); color: var(--text-secondary); padding: 4px 12px; cursor: pointer; }
.calib-mode.is-on { border-color: #c2725a; color: #c2725a; }
.calib-custom { display: flex; align-items: center; gap: 6px; margin-top: 10px; font-size: var(--text-sm); color: var(--text-muted); justify-content: center; }
.calib-input { width: 70px; border: 1px solid var(--line); border-radius: var(--radius-sm); background: transparent; font-size: var(--text-sm); color: var(--text-primary); padding: 4px 6px; text-align: center; }
.calib-actions { display: flex; gap: 8px; margin-top: 12px; justify-content: center; }
.calib-btn { border: 1px solid var(--line-faint); border-radius: var(--radius-md); background: var(--bg-secondary); color: var(--text-secondary); font-size: var(--text-sm); padding: 6px 16px; cursor: pointer; }
.calib-btn--primary { background: #c2725a; border-color: #c2725a; color: #fff; }
.calib-hint { margin: 10px 0 0; font-size: var(--text-xs); color: var(--text-muted); text-align: center; }
</style>
