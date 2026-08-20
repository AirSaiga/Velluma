import { ref, computed } from 'vue'
import { worldApi, plotLedgerApi, type PlotLedgerCreateInput } from '../../../services/api'
import { computeWorldState } from '../engine/computeWorldState'
import {
  normalizeTimelineCursor,
  normalizeTimelineRange,
  type TimelineRange,
  type TimelineViewState,
} from '../engine/timelineView'
import { pushCommand, clearHistory } from './useWorldHistory'
import { WORLD_REFRESH_EVENT } from './useWorldSlice'
import type {
  WorldLocation,
  WorldEvent,
  WorldEntity,
  WorldRelation,
  WorldState,
  WorldMapLayer,
  WorldMapStroke,
  ChapterAnchor,
  Foreshadow,
  MapLayerPatch,
  Point,
} from '../engine/types'

/**
 * World 设定层模块级单例状态（仿 useCanon）。
 *
 * 写动作（create/delete location/event/entity/relation）均包逆命令 push 到 history，
 * 支持 undo/redo（Ctrl+Z/Y）。**幂等恢复**：redo 重建时携带原 id（后端 create 支持指定
 * id），引用该对象的 relation/event payload 不会悬空——世界页 M1 起的引用完整性前提。
 *
 * 底图（mapLayers/strokes）不进全局 undo——编辑态内有 useMapEdit 的局部栈。
 */
const locations = ref<WorldLocation[]>([])
const events = ref<WorldEvent[]>([])
const entities = ref<WorldEntity[]>([])
const relations = ref<WorldRelation[]>([])
const chapterAnchors = ref<ChapterAnchor[]>([])
const foreshadows = ref<Foreshadow[]>([])
const mapLayers = ref<WorldMapLayer[]>([])
const mapStrokes = ref<WorldMapStroke[]>([])
const currentTime = ref<number>(0)
const loadedBookId = ref<string | null>(null)
/** 手动视野窗口（null=自动跟随事件延展）——与游标时刻一起按书持久化到服务端 */
const timelineRange = ref<TimelineRange | null>(null)

const locationsById = computed<Record<string, WorldLocation>>(() => {
  const m: Record<string, WorldLocation> = {}
  for (const loc of locations.value) m[loc.id] = loc
  return m
})

const worldState = computed<WorldState>(() =>
  computeWorldState(events.value, locationsById.value, currentTime.value, relations.value),
)

const characters = computed(() => entities.value.filter((e) => e.entity_type === 'character'))
const factions = computed(() => entities.value.filter((e) => e.entity_type === 'faction'))
const assets = computed(() => entities.value.filter((e) => e.entity_type === 'asset'))

// ===== 时间轴 UI 状态按书持久化（服务端 books.timeline_view：游标时刻 + 视野窗口）=====
// 恢复值只是「上次看到哪」：世界页 ?time= 深链在 load() 之后才 setCurrentTime，天然覆盖恢复值——深链优先。
// 历史 localStorage 方案（velluma:tl-time / velluma:tl-range）因启动脚本端口扫描换 origin 即漂移弃用；
// 旧键降级为一次性迁移来源（服务端缺键时读旧值顶上并写穿）+ 游标关窗竞态的同步兜底。
const LEGACY_TIME_KEY = (bookId: string) => `velluma:tl-time:${bookId}`
const LEGACY_RANGE_KEY = (bookId: string) => `velluma:tl-range:${bookId}`
let persistViewTimer: ReturnType<typeof setTimeout> | null = null
/** 服务端快照已应用的 bookId（加载竞态护栏：快照到达前的拖动不触发写库，防旧值覆盖新输入） */
let viewReadyBookId: string | null = null

function applyTimelineView(bookId: string, view: TimelineViewState) {
  const cursor = normalizeTimelineCursor(view.cursor)
  const range = normalizeTimelineRange(view.range)
  currentTime.value = cursor ?? 0
  timelineRange.value = range

  // localStorage 旧键一次性迁移：仅当服务端缺该键时读旧值顶上，写穿成功后删本地键
  const legacy: Partial<TimelineViewState> = {}
  try {
    if (cursor === null) {
      const raw = localStorage.getItem(LEGACY_TIME_KEY(bookId))
      const v = raw === null ? null : normalizeTimelineCursor(Number(raw))
      if (v !== null) {
        currentTime.value = v
        legacy.cursor = v
      }
    }
    if (range === null) {
      const raw = localStorage.getItem(LEGACY_RANGE_KEY(bookId))
      const v = raw === null ? null : normalizeTimelineRange(JSON.parse(raw))
      if (v) {
        timelineRange.value = v
        legacy.range = v
      }
    }
  } catch {
    /* 隐私模式/坏数据静默忽略 */
  }

  if (Object.keys(legacy).length > 0) {
    worldApi
      .patchTimelineView(bookId, legacy)
      .then(() => {
        try {
          if (legacy.cursor !== undefined) localStorage.removeItem(LEGACY_TIME_KEY(bookId))
          if (legacy.range !== undefined) localStorage.removeItem(LEGACY_RANGE_KEY(bookId))
        } catch {
          /* 删不掉无碍——服务端值已优先 */
        }
      })
      .catch(() => {
        /* 写穿失败：本地键保留，下次加载重试迁移 */
      })
  }
}

function flushPersistView() {
  persistViewTimer = null
  const id = loadedBookId.value
  if (!id || viewReadyBookId !== id) return
  const cursor = Math.floor(currentTime.value)
  // localStorage 同步写仅作 pagehide 竞态兜底（日常读取以服务端为准）
  try {
    localStorage.setItem(LEGACY_TIME_KEY(id), String(cursor))
  } catch {
    /* 存不进就当会话级 */
  }
  worldApi.patchTimelineView(id, { cursor }).catch(() => {
    /* 离线/重启竞态：本地兜底键已留，下次加载迁移补写 */
  })
}

/** 拖动/播放是高频调用（rAF 帧/16ms 步进），尾部去抖合并成一次写 */
function schedulePersistView() {
  if (persistViewTimer) clearTimeout(persistViewTimer)
  persistViewTimer = setTimeout(flushPersistView, 300)
}

// 单例模块不随组件卸载，关窗/刷新时 pagehide 兜底冲刷，防去抖窗口内丢末次位置
window.addEventListener('pagehide', () => {
  if (!persistViewTimer) return
  clearTimeout(persistViewTimer)
  flushPersistView()
})

/** 框定/清除视野窗口（点击驱动低频，立即落库；null=回自动视野） */
function setTimelineRange(range: TimelineRange | null) {
  timelineRange.value = range
  const id = loadedBookId.value
  if (!id || viewReadyBookId !== id) return
  if (range === null) {
    // 清除动作必须同步抹掉本地旧键，防下次加载迁移复活已清除的窗口
    try {
      localStorage.removeItem(LEGACY_RANGE_KEY(id))
    } catch {
      /* 同上 */
    }
  }
  worldApi.patchTimelineView(id, { range }).catch(() => {
    /* 失败：本地 ref 已生效，本次会话内视野仍正确 */
  })
}

async function load(bookId: string) {
  loadedBookId.value = bookId
  viewReadyBookId = null
  // 默认值先落地（服务端快照到达前不渲染上一本书的旧状态）；?time= 深链在 load() 后覆盖——深链优先
  currentTime.value = 0
  timelineRange.value = null
  clearHistory() // 切书清空 undo 栈（避免指向被覆盖的旧数据）
  const [locs, evs, ents, rels, chapters, ledgers, layers, strokes, view] = await Promise.all([
    worldApi.listLocations(bookId),
    worldApi.listEvents(bookId),
    worldApi.listEntities(bookId),
    worldApi.listRelations(bookId),
    worldApi.listChapterAnchors(bookId),
    plotLedgerApi.listByBook(bookId).catch(() => [] as Awaited<ReturnType<typeof plotLedgerApi.listByBook>>),
    worldApi.listMapLayers(bookId),
    worldApi.listMapStrokes(bookId),
    worldApi.getTimelineView(bookId).catch(() => ({}) as TimelineViewState),
  ])
  locations.value = locs
  events.value = evs
  entities.value = ents
  relations.value = rels
  chapterAnchors.value = chapters.sort((a, b) => a.chapter_number - b.chapter_number)
  foreshadows.value = ledgers.map((l) => toForeshadow(l))
  mapLayers.value = layers
  mapStrokes.value = strokes
  applyTimelineView(bookId, view)
  viewReadyBookId = bookId
}

// ===== Location =====
async function createLocation(
  bookId: string,
  data: {
    id?: string
    name: string
    kind?: string
    coord_x?: number | null
    coord_y?: number | null
    intro?: string
  },
) {
  const loc = await worldApi.createLocation(bookId, data)
  locations.value = [...locations.value, loc]
  pushCommand({
    description: `建立地点「${loc.name}」`,
    undo: async () => {
      await worldApi.deleteLocation(bookId, loc.id)
      locations.value = locations.value.filter((l) => l.id !== loc.id)
    },
    redo: async () => {
      const r = await worldApi.createLocation(bookId, {
        id: loc.id, // 幂等恢复：沿用原 id，保住 relation/事件对该地点的引用
        name: loc.name,
        kind: loc.kind,
        coord_x: loc.coord_x,
        coord_y: loc.coord_y,
        intro: loc.intro,
      })
      locations.value = [...locations.value, r]
    },
  })
  return loc
}

/** 改名（轻量，不进 undo） */
async function renameLocation(bookId: string, locationId: string, name: string) {
  await worldApi.updateLocation(bookId, locationId, { name })
  locations.value = locations.value.map((l) => (l.id === locationId ? { ...l, name } : l))
}

async function renameEntity(bookId: string, entityId: string, name: string) {
  await worldApi.updateEntity(bookId, entityId, { name })
  entities.value = entities.value.map((e) => (e.id === entityId ? { ...e, name } : e))
}

/** 地图拖拽微调地点坐标（不进 undo 栈——高频微调不值得占历史步） */
async function updateLocationCoords(
  bookId: string,
  locationId: string,
  x: number,
  y: number,
) {
  await worldApi.updateLocation(bookId, locationId, { coord_x: x, coord_y: y })
  locations.value = locations.value.map((l) =>
    l.id === locationId ? { ...l, coord_x: x, coord_y: y } : l,
  )
}

async function deleteLocation(bookId: string, locationId: string) {
  const snap = locations.value.find((l) => l.id === locationId)
  await worldApi.deleteLocation(bookId, locationId)
  locations.value = locations.value.filter((l) => l.id !== locationId)
  if (snap) {
    pushCommand({
      description: `删除地点「${snap.name}」`,
      undo: async () => {
        const r = await worldApi.createLocation(bookId, {
          id: snap.id, // 幂等恢复：沿用原 id
          name: snap.name,
          kind: snap.kind,
          coord_x: snap.coord_x,
          coord_y: snap.coord_y,
          intro: snap.intro,
        })
        locations.value = [...locations.value, r]
      },
      redo: async () => {
        await worldApi.deleteLocation(bookId, locationId)
        locations.value = locations.value.filter((l) => l.id !== locationId)
      },
    })
  }
}

// ===== Event =====
async function createEvent(
  bookId: string,
  data: {
    id?: string
    event_type: string
    time_start: number
    time_end?: number
    location_id?: string | null
    participant_ids?: string[]
    faction_ids?: string[]
    payload?: Record<string, unknown>
    chapter_ref?: string | null
    note?: string
    tags?: string[]
  },
) {
  const ev = await worldApi.createEvent(bookId, {
    ...data,
    time_end: data.time_end ?? data.time_start,
  })
  events.value = [...events.value, ev]
  pushCommand({
    description: `记录事件「${ev.event_type}」`,
    undo: async () => {
      await worldApi.deleteEvent(bookId, ev.id)
      events.value = events.value.filter((e) => e.id !== ev.id)
    },
    redo: async () => {
      const r = await worldApi.createEvent(bookId, {
        id: ev.id, // 幂等恢复：沿用原 id
        event_type: ev.event_type,
        time_start: ev.time_start,
        time_end: ev.time_end,
        location_id: ev.location_id,
        participant_ids: ev.participant_ids,
        faction_ids: ev.faction_ids,
        payload: ev.payload,
        chapter_ref: ev.chapter_ref,
        note: ev.note,
        tags: ev.tags,
      })
      events.value = [...events.value, r]
    },
  })
  return ev
}

async function deleteEvent(bookId: string, eventId: string) {
  const snap = events.value.find((l) => l.id === eventId)
  await worldApi.deleteEvent(bookId, eventId)
  events.value = events.value.filter((e) => e.id !== eventId)
  if (snap) {
    pushCommand({
      description: `删除事件「${snap.event_type}」`,
      undo: async () => {
        const r = await worldApi.createEvent(bookId, {
          id: snap.id, // 幂等恢复：沿用原 id
          event_type: snap.event_type,
          time_start: snap.time_start,
          time_end: snap.time_end,
          location_id: snap.location_id,
          participant_ids: snap.participant_ids,
          faction_ids: snap.faction_ids,
          payload: snap.payload,
          chapter_ref: snap.chapter_ref,
          note: snap.note,
          tags: snap.tags,
        })
        events.value = [...events.value, r]
      },
      redo: async () => {
        await worldApi.deleteEvent(bookId, eventId)
        events.value = events.value.filter((e) => e.id !== eventId)
      },
    })
  }
}

/** 编辑事件（轻量：快照旧值进 undo，id 不变引用不断） */
async function updateEvent(
  bookId: string,
  eventId: string,
  data: {
    time_start?: number
    time_end?: number
    location_id?: string | null
    participant_ids?: string[]
    faction_ids?: string[]
    payload?: Record<string, unknown>
    note?: string
    tags?: string[]
  },
) {
  const snap = events.value.find((e) => e.id === eventId)
  const updated = await worldApi.updateEvent(bookId, eventId, data)
  events.value = events.value.map((e) => (e.id === eventId ? updated : e))
  if (snap) {
    pushCommand({
      description: `编辑事件「${snap.event_type}」`,
      undo: async () => {
        const r = await worldApi.updateEvent(bookId, eventId, {
          time_start: snap.time_start,
          time_end: snap.time_end,
          location_id: snap.location_id,
          participant_ids: snap.participant_ids,
          faction_ids: snap.faction_ids,
          payload: snap.payload,
          note: snap.note,
          tags: snap.tags,
        })
        events.value = events.value.map((e) => (e.id === eventId ? r : e))
      },
      redo: async () => {
        const r = await worldApi.updateEvent(bookId, eventId, data)
        events.value = events.value.map((e) => (e.id === eventId ? r : e))
      },
    })
  }
  return updated
}

// ===== Entity =====
async function createEntity(
  bookId: string,
  data: {
    id?: string
    entity_type: 'character' | 'faction' | 'asset'
    name: string
    intro?: string
    props?: Record<string, unknown>
    canvas_x?: number | null
    canvas_y?: number | null
  },
) {
  const ent = await worldApi.createEntity(bookId, data)
  entities.value = [...entities.value, ent]
  pushCommand({
    description: `建立${ent.entity_type === 'character' ? '角色' : ent.entity_type === 'faction' ? '势力' : '资产'}「${ent.name}」`,
    undo: async () => {
      await worldApi.deleteEntity(bookId, ent.id)
      entities.value = entities.value.filter((e) => e.id !== ent.id)
    },
    redo: async () => {
      const r = await worldApi.createEntity(bookId, {
        id: ent.id, // 幂等恢复：沿用原 id，保住关系边引用
        entity_type: ent.entity_type,
        name: ent.name,
        intro: ent.intro,
        props: ent.props,
      })
      entities.value = [...entities.value, r]
    },
  })
  return ent
}

async function deleteEntity(bookId: string, entityId: string) {
  const snap = entities.value.find((e) => e.id === entityId)
  await worldApi.deleteEntity(bookId, entityId)
  entities.value = entities.value.filter((e) => e.id !== entityId)
  if (snap) {
    pushCommand({
      description: `删除${snap.entity_type === 'character' ? '角色' : snap.entity_type === 'faction' ? '势力' : '资产'}「${snap.name}」`,
      undo: async () => {
        const r = await worldApi.createEntity(bookId, {
          id: snap.id, // 幂等恢复：沿用原 id
          entity_type: snap.entity_type,
          name: snap.name,
          intro: snap.intro,
          props: snap.props,
        })
        entities.value = [...entities.value, r]
      },
      redo: async () => {
        await worldApi.deleteEntity(bookId, entityId)
        entities.value = entities.value.filter((e) => e.id !== entityId)
      },
    })
  }
}

// ===== Relation（脑图透镜的边）=====

async function createRelation(
  bookId: string,
  data: {
    source_entity_id: string
    target_entity_id: string
    relation_type?: string
    label?: string
    affinity?: number | null
    note?: string
    static?: boolean
    event_ref?: string | null
  },
) {
  const rel = await worldApi.createRelation(bookId, data)
  relations.value = [...relations.value, rel]
  pushCommand({
    description: `建立关系「${rel.label || rel.relation_type}」`,
    undo: async () => {
      await worldApi.deleteRelation(bookId, rel.id)
      relations.value = relations.value.filter((r) => r.id !== rel.id)
    },
    redo: async () => {
      const r = await worldApi.createRelation(bookId, {
        id: rel.id, // 幂等恢复：沿用原 id
        source_entity_id: rel.source_entity_id,
        target_entity_id: rel.target_entity_id,
        relation_type: rel.relation_type,
        label: rel.label,
        affinity: rel.affinity,
        note: rel.note,
        static: rel.static,
        event_ref: rel.event_ref,
      })
      relations.value = [...relations.value, r]
    },
  })
  return rel
}

/** 编辑关系（快照旧值进 undo，id 不变引用不断） */
async function updateRelation(
  bookId: string,
  relationId: string,
  data: {
    relation_type?: string
    label?: string
    affinity?: number | null
    note?: string
    static?: boolean
    event_ref?: string | null
  },
) {
  const snap = relations.value.find((r) => r.id === relationId)
  const updated = await worldApi.updateRelation(bookId, relationId, data)
  relations.value = relations.value.map((r) => (r.id === relationId ? updated : r))
  if (snap) {
    pushCommand({
      description: `编辑关系「${snap.label || snap.relation_type}」`,
      undo: async () => {
        const r = await worldApi.updateRelation(bookId, relationId, {
          relation_type: snap.relation_type,
          label: snap.label,
          affinity: snap.affinity,
          note: snap.note,
          static: snap.static,
          event_ref: snap.event_ref,
        })
        relations.value = relations.value.map((x) => (x.id === relationId ? r : x))
      },
      redo: async () => {
        const r = await worldApi.updateRelation(bookId, relationId, data)
        relations.value = relations.value.map((x) => (x.id === relationId ? r : x))
      },
    })
  }
  return updated
}

async function deleteRelation(bookId: string, relationId: string) {
  const snap = relations.value.find((r) => r.id === relationId)
  await worldApi.deleteRelation(bookId, relationId)
  relations.value = relations.value.filter((r) => r.id !== relationId)
  if (snap) {
    pushCommand({
      description: `删除关系「${snap.label || snap.relation_type}」`,
      undo: async () => {
        const r = await worldApi.createRelation(bookId, {
          id: snap.id, // 幂等恢复：沿用原 id
          source_entity_id: snap.source_entity_id,
          target_entity_id: snap.target_entity_id,
          relation_type: snap.relation_type,
          label: snap.label,
          affinity: snap.affinity,
          note: snap.note,
          static: snap.static,
          event_ref: snap.event_ref,
        })
        relations.value = [...relations.value, r]
      },
      redo: async () => {
        await worldApi.deleteRelation(bookId, relationId)
        relations.value = relations.value.filter((r) => r.id !== relationId)
      },
    })
  }
}

// ===== 实体档案（M2：轻量就地编辑，不进 undo——高频微调不值得占历史步）=====

async function updateEntityArchive(
  bookId: string,
  entityId: string,
  patch: {
    name?: string
    aliases?: string[]
    importance?: number
    visibility?: string
    intro?: string
    tags?: string[]
    props?: Record<string, unknown>
    canvas_x?: number | null
    canvas_y?: number | null
  },
) {
  const updated = await worldApi.updateEntity(bookId, entityId, patch)
  entities.value = entities.value.map((e) => (e.id === entityId ? updated : e))
  return updated
}

// ===== 伏笔（M3：PlotLedger 的世界页投影，弧线带数据源；M5：侧栏账本+详情抽屉）=====

/** M5：伏笔/期待/世界观变更后广播——写作页「此刻此地」切片（头顶的线）静默重取 */
function notifyWorldChanged() {
  window.dispatchEvent(new CustomEvent(WORLD_REFRESH_EVENT))
}

const toForeshadow = (l: {
  id: string
  ledger_key: string
  entry_type: string
  content: string
  status: 'open' | 'closed' | 'dropped'
  world_time_planted?: number | null
  world_time_resolved?: number | null
  created_at_chapter?: number | null
  hook_id?: string | null
  meta?: Record<string, any> | null
}): Foreshadow => ({
  id: l.id,
  ledger_key: l.ledger_key,
  entry_type: l.entry_type,
  content: l.content,
  status: l.status,
  world_time_planted: l.world_time_planted ?? null,
  world_time_resolved: l.world_time_resolved ?? null,
  created_at_chapter: l.created_at_chapter ?? null,
  hook_id: l.hook_id ?? null,
  meta: l.meta ?? null,
})

/**
 * 快照 → create payload：undo/redo 重建伏笔用，全字段透传（漏字段=撤销静默丢数据）。
 * 幂等恢复：沿用原 ledger_key（book 内唯一约束）。
 * 后端校验约束：meta 非 Optional（缺省须省键，传 null 会 422）；hook_id min_length=1、
 * created_at_chapter ge=1——旧数据里的空串/越值在此归一为 null，防重建被 422 打断。
 */
function foreshadowRestorePayload(f: Foreshadow): PlotLedgerCreateInput {
  return {
    ledger_key: f.ledger_key,
    content: f.content,
    entry_type: f.entry_type,
    status: f.status,
    hook_id: f.hook_id || null,
    created_at_chapter: f.created_at_chapter != null && f.created_at_chapter > 0 ? f.created_at_chapter : null,
    world_time_planted: f.world_time_planted,
    world_time_resolved: f.world_time_resolved,
    ...(f.meta ? { meta: f.meta } : {}),
  }
}

async function createForeshadow(
  bookId: string,
  data: { content: string; entryType?: string; planted: number; resolved?: number | null },
) {
  const entry = await plotLedgerApi.create(bookId, {
    ledger_key: `world-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`,
    content: data.content,
    entry_type: data.entryType || 'foreshadow',
    world_time_planted: data.planted,
    world_time_resolved: data.resolved ?? null,
  })
  const f = toForeshadow(entry)
  foreshadows.value = [...foreshadows.value, f]
  pushCommand({
    description: `埋伏笔「${data.content.slice(0, 12)}」`,
    undo: async () => {
      await plotLedgerApi.remove(f.id)
      foreshadows.value = foreshadows.value.filter((x) => x.id !== f.id)
    },
    redo: async () => {
      const r = await plotLedgerApi.create(bookId, foreshadowRestorePayload(f))
      foreshadows.value = [...foreshadows.value, toForeshadow(r)]
    },
  })
  notifyWorldChanged()
  return f
}

/** 拖弧线端点改锚（轻量，不进 undo） */
async function updateForeshadowTimes(
  bookId: string,
  foreshadowId: string,
  patch: { world_time_planted?: number | null; world_time_resolved?: number | null },
) {
  await plotLedgerApi.update(foreshadowId, patch)
  foreshadows.value = foreshadows.value.map((f) => (f.id === foreshadowId ? { ...f, ...patch } : f))
  notifyWorldChanged()
}

/**
 * M5：详情抽屉就地编辑（内容/类型/状态/章锚/hook_id）。
 * 轻量编辑不进 undo（照 updateEntityArchive 先例）；时间锚走 updateForeshadowTimes。
 */
async function updateForeshadow(
  bookId: string,
  foreshadowId: string,
  patch: {
    content?: string
    entry_type?: string
    status?: 'open' | 'closed' | 'dropped'
    created_at_chapter?: number | null
    hook_id?: string | null
  },
) {
  await plotLedgerApi.update(foreshadowId, patch)
  foreshadows.value = foreshadows.value.map((f) => (f.id === foreshadowId ? { ...f, ...patch } : f))
  notifyWorldChanged()
}

/** 在时刻 t 回收（闭合） */
async function resolveForeshadow(bookId: string, foreshadowId: string, t: number) {
  await updateForeshadowTimes(bookId, foreshadowId, { world_time_resolved: t })
  await plotLedgerApi.update(foreshadowId, { status: 'closed' })
  foreshadows.value = foreshadows.value.map((f) =>
    f.id === foreshadowId ? { ...f, status: 'closed' as const, world_time_resolved: t } : f,
  )
}

async function dropForeshadow(bookId: string, foreshadowId: string) {
  await plotLedgerApi.update(foreshadowId, { status: 'dropped' })
  foreshadows.value = foreshadows.value.map((f) =>
    f.id === foreshadowId ? { ...f, status: 'dropped' as const } : f,
  )
  notifyWorldChanged()
}

async function deleteForeshadow(bookId: string, foreshadowId: string) {
  const snap = foreshadows.value.find((f) => f.id === foreshadowId)
  await plotLedgerApi.remove(foreshadowId)
  foreshadows.value = foreshadows.value.filter((f) => f.id !== foreshadowId)
  if (snap) {
    pushCommand({
      description: `删除伏笔「${snap.content.slice(0, 12)}」`,
      undo: async () => {
        const r = await plotLedgerApi.create(bookId, foreshadowRestorePayload(snap))
        foreshadows.value = [...foreshadows.value, toForeshadow(r)]
      },
      redo: async () => {
        await plotLedgerApi.remove(foreshadowId)
        foreshadows.value = foreshadows.value.filter((f) => f.id !== foreshadowId)
      },
    })
  }
  notifyWorldChanged()
}

// ===== 章节叙事时间锚（轻量，不进 undo——改锚是低风险高频微调）=====

async function setChapterAnchor(chapterId: string, narrativeTime: number) {
  await worldApi.setChapterAnchor(chapterId, narrativeTime)
  chapterAnchors.value = chapterAnchors.value
    .map((c) => (c.id === chapterId ? { ...c, narrative_time: narrativeTime } : c))
    .sort((a, b) => a.chapter_number - b.chapter_number)
}

function setCurrentTime(t: number) {
  currentTime.value = t
  schedulePersistView()
}

// ===== 底图（图片层 + 笔迹；不进全局 undo——编辑态用 useMapEdit 局部栈）=====

async function createMapLayer(
  bookId: string,
  data: { image_url: string; x: number; y: number; w: number; h: number },
) {
  const layer = await worldApi.createMapLayer(bookId, data)
  mapLayers.value = [...mapLayers.value, layer]
  return layer
}

/** 图片变换（拖/缩放后落库）。直接改本地数组由调用方做（编辑期高频），这里只落库。 */
async function patchMapLayer(bookId: string, layerId: string, patch: MapLayerPatch) {
  await worldApi.updateMapLayer(bookId, layerId, patch)
}

async function deleteMapLayerData(bookId: string, layerId: string) {
  await worldApi.deleteMapLayer(bookId, layerId)
  mapLayers.value = mapLayers.value.filter((l) => l.id !== layerId)
}

async function createMapStroke(bookId: string, color: string, width: number, points: Point[]) {
  const stroke = await worldApi.createMapStroke(bookId, { color, width, points })
  mapStrokes.value = [...mapStrokes.value, stroke]
  return stroke
}

async function deleteMapStrokeData(bookId: string, strokeId: string) {
  await worldApi.deleteMapStroke(bookId, strokeId)
  mapStrokes.value = mapStrokes.value.filter((s) => s.id !== strokeId)
}

function setMapLayers(layers: WorldMapLayer[]) {
  mapLayers.value = layers
}

function setMapStrokes(strokes: WorldMapStroke[]) {
  mapStrokes.value = strokes
}

export function useWorld() {
  return {
    locations,
    events,
    entities,
    relations,
    chapterAnchors,
    foreshadows,
    characters,
    factions,
    assets,
    currentTime,
    timelineRange,
    worldState,
    locationsById,
    loadedBookId,
    mapLayers,
    mapStrokes,
    load,
    createLocation,
    updateLocationCoords,
    renameLocation,
    renameEntity,
    deleteLocation,
    createEvent,
    updateEvent,
    deleteEvent,
    createEntity,
    deleteEntity,
    createRelation,
    updateRelation,
    deleteRelation,
    updateEntityArchive,
    createForeshadow,
    updateForeshadowTimes,
    updateForeshadow,
    resolveForeshadow,
    dropForeshadow,
    deleteForeshadow,
    setChapterAnchor,
    setCurrentTime,
    setTimelineRange,
    createMapLayer,
    patchMapLayer,
    deleteMapLayerData,
    createMapStroke,
    deleteMapStrokeData,
    setMapLayers,
    setMapStrokes,
  }
}
