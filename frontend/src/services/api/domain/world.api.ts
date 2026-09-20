/**
 * World 设定层 API 客户端（独立于 canonApi）。
 * 端点 /books/{bookId}/world/...，经 transport 自动加 /api 前缀。
 *
 * 类型复用 engine/types（前后端同构）。
 */
import { requestJson } from '../transport'
import type { TimelineViewState } from '../../../features/world/engine/timelineView'
import type {
  WorldEntity,
  WorldEvent,
  WorldLocation,
  WorldState,
  WorldMapLayer,
  WorldMapStroke,
  WorldRelation,
  ChapterAnchor,
  Point,
} from '../../../features/world/engine/types'

export interface WorldLocationCreate {
  id?: string // 幂等重建（undo/redo 恢复路径）
  name: string
  kind?: string
  parent_id?: string | null // 非空 = 内部构造（上图权 = parent_id IS NULL，docs/reports/location-interior.md）
  coord_x?: number | null
  coord_y?: number | null
  intro?: string
  tags?: string[]
}

export interface WorldEntityCreate {
  id?: string // 幂等重建（undo/redo 恢复路径）
  entity_type: 'character' | 'faction' | 'asset'
  name: string
  intro?: string
  /** 别名（RAG 检索 / 速记名单匹配用）；速记建档时口述原词自动回填 */
  aliases?: string[]
  tags?: string[]
  /** 单分组（2026-09-03 资产抽屉分组）：更新时显式传 null = 移出分组 */
  group_name?: string | null
  props?: Record<string, unknown>
  /** 字段级真相分层（2026-09-03）：{ field_key: { level: private|partial, public_text?, reveal_chapter? } } */
  field_layers?: Record<string, { level: string; public_text?: string; reveal_chapter?: number | null }>
  canvas_x?: number | null
  canvas_y?: number | null
}

export interface WorldRelationCreate {
  id?: string // 幂等重建（undo/redo 恢复路径）
  source_entity_id: string
  target_entity_id: string
  relation_type?: string
  label?: string
  affinity?: number | null
  note?: string
  static?: boolean
  event_ref?: string | null
}

export interface WorldEventCreate {
  id?: string // 幂等重建（undo/redo 恢复路径）
  event_type: string
  time_start: number
  time_end: number
  location_id?: string | null
  participant_ids?: string[]
  faction_ids?: string[]
  payload?: Record<string, unknown>
  causes?: string[]
  chapter_ref?: string | null
  tags?: string[]
  title?: string
  note?: string
}

const JSON_HEADERS = { 'Content-Type': 'application/json' }

// ===== 世界切片（写作页「此刻此地」，docs/world-writing-bridge.md W1）=====

export interface WorldVersion {
  /** 事件计数（兜底「删除不 bump updated_at」的盲区） */
  events: number
  /** 四表聚合 max(updated_at)（ISO 字符串；空世界为 null） */
  updated_at: string | null
}

/** C2 canon 迁移预览行（label 匹配世界对象的建议，作者逐条 ✓/✗） */
export interface CanonMigrateRow {
  node_id: string
  label: string
  type: string
  action: 'link' | 'to_ledger' | 'create_ledger' | 'skip'
  ref_type: 'entity' | 'location' | 'ledger' | null
  target_id: string | null
  target_name: string | null
}

export interface ScenePresence {
  entity_id: string
  name: string
  alive: boolean
  location_name: string
  /** 结构化位置 id（双层分立）：空=位置未知——取景/章范围子树闭包过滤的依据 */
  location_id: string
  label: string
  /** 词法兜底标记：lexical=位置从事件 note 推断（据正文推断 badge） */
  presence_source: string | null
  importance: number
  visibility: string
}

export interface SceneBlock {
  location_id: string
  name: string
  /** 全路径「父·子」（内部构造脚下无歧义显示；顶层=裸名，docs/reports/location-interior.md） */
  path?: string
  controlling_faction: string | null
  /** True=作者显式钉定（chapters.scene_location_id） */
  pinned: boolean
}

export interface SceneEncounter {
  /** t 时刻同地点的存活角色名（戏剧机会线索） */
  names: string[]
  location_name: string
}

export interface SceneForeshadow {
  ledger_key: string
  content: string
  chapters_open: number | null
}

export interface SceneExpectation {
  type: string
  description: string
  tension: number
}

export interface SceneChapterActor {
  /** 全章正文活跃名册条目（方向 B）：正文有戏份的角色（含零事件者） */
  name: string
  /** 判定证据：对白/交互/动作/在场/未建档 */
  via: string
  /** guest（未建档）无档案故空 */
  entity_id: string
  /** registered=已建档 | guest=未建档高频人名 */
  source: 'registered' | 'guest'
}

export interface SceneSlice {
  t: number
  /** chapter_anchor | prev_anchor | max_event | zero（四级降级来源） */
  t_source: string
  /** A4 来源可见：max_event 时附最大时刻事件摘要（截 30 字；缺席 = 未取到） */
  t_source_note?: string | null
  /** A4 来源可见：prev_anchor 时来源章号（「来自第N章锚」；缺席 = 未取到） */
  t_source_chapter?: number | null
  presence: ScenePresence[]
  scene: SceneBlock | null
  /** 全章正文活跃名册（2026-09-17 方向 B）：与 presence 并集渲染出场名册 */
  chapter_actors: SceneChapterActor[]
  encounters: SceneEncounter[]
  foreshadows: SceneForeshadow[]
  expectations: SceneExpectation[]
  version: WorldVersion
  /** 世界页无实体（旧表兜底书）→ 前端显示迁移引导 */
  world_empty: boolean
  /** D4-2 比例尺距离（docs/reports/map-scale-spatial.md §5）：未标定整段缺席 */
  proximities?: { a: string; b: string; text: string }[]
  nearest_anchor?: { name: string; text: string } | null
  /** D4-3 空间常识块（settings_bundle 消费；切片 API 顺带携带） */
  spatial_brief?: string | null
}

// ===== 情境浮卡（W2 查询闭环）=====

export interface ContextChronicleItem {
  event_type: string
  title?: string
  note: string
  time_start: number
}

export interface ContextCard {
  kind: 'entity' | 'location'
  id: string
  entity_type: string
  name: string
  intro: string
  t: number
  alive: boolean | null
  location_name: string
  label: string
  chronicle: ContextChronicleItem[]
  controlling_faction: string | null
  recent_events: ContextChronicleItem[]
}

// ===== 速记解析（W3）+ 候选事件（W4）=====

export interface EventDraft {
  event_type: string
  summary: string
  time_start: number
  time_end: number
  participant_ids: string[]
  participant_names: string[]
  /** 名单没匹配上的名字（提示作者手选） */
  unresolved_names: string[]
  location_id: string | null
  location_name: string
  note: string
  /** 出处原句（02 修缮 M1）：后端已校验为正文逐字子串；旧候选无此字段（可缺席） */
  evidence?: string
  /** 转正产物 id（02 修缮 P2b，accept 时后端写入 draft）——单事务撤销据此删产物 */
  accepted_event_id?: string
  accepted_canon_node_id?: string
}

export interface ParseEventResult {
  draft: EventDraft
  confidence: 'high' | 'low' | 'none'
  /** 速记里名单外的新实体/新地点草拟（关联式录入 2026-09-05）：名字+类型猜测+依据原文 */
  new_entities: NewEntityDraft[]
  new_locations: NewLocationDraft[]
}

export interface NewEntityDraft {
  name: string
  kind: 'character' | 'faction' | 'asset' | string
  /** 速记原文的逐字子串（后端硬闸校验过），展示给作者核对 */
  evidence: string
}

export interface NewLocationDraft {
  name: string
  evidence: string
}

export interface WorldEventCandidate {
  id: string
  book_id: string
  chapter_id: string | null
  /** 归属章号（后端联表补；无时间锚时显示「第 N 章」替代默认日期） */
  chapter_number?: number | null
  /** C3 起 canon_extract 候选的 draft 是真相候选形状（label/type/canon_text/public_text） */
  draft: EventDraft & { label?: string; type?: string; canon_text?: string; public_text?: string }
  source: 'settle' | 'finish' | 'canon_extract' | string
  status: 'pending' | 'accepted' | 'rejected' | string
  created_at: string
}

export const worldApi = {
  // ===== 时间轴 UI 状态（游标时刻 + 视野窗口，服务端按书持久化——替代随端口扫描漂移的 localStorage）=====
  getTimelineView: (bookId: string): Promise<TimelineViewState> =>
    requestJson<{ timeline_view: TimelineViewState }>(`/books/${bookId}/timeline-view`).then(
      (r) => r.timeline_view || {},
    ),

  /** 键级合并补丁；值传 null 删除该键（如 range: null 回自动视野） */
  patchTimelineView: (bookId: string, patch: Partial<TimelineViewState>) =>
    requestJson<{ timeline_view: TimelineViewState }>(`/books/${bookId}/timeline-view`, {
      method: 'PATCH',
      headers: JSON_HEADERS,
      body: JSON.stringify(patch),
    }),

  // ===== 地点 =====
  listLocations: (bookId: string) =>
    requestJson<WorldLocation[]>(`/books/${bookId}/world/locations`),

  createLocation: (bookId: string, data: WorldLocationCreate) =>
    requestJson<WorldLocation>(`/books/${bookId}/world/locations`, {
      method: 'POST',
      headers: JSON_HEADERS,
      body: JSON.stringify({ ...data, book_id: bookId }),
    }),

  updateLocation: (bookId: string, locationId: string, data: Partial<WorldLocationCreate>) =>
    requestJson<WorldLocation>(`/books/${bookId}/world/locations/${locationId}`, {
      method: 'PUT',
      headers: JSON_HEADERS,
      body: JSON.stringify(data),
    }),

  deleteLocation: (bookId: string, locationId: string) =>
    requestJson<{ deleted: boolean }>(`/books/${bookId}/world/locations/${locationId}`, {
      method: 'DELETE',
    }),

  // ===== 事件 =====
  listEvents: (bookId: string) => requestJson<WorldEvent[]>(`/books/${bookId}/world/events`),

  createEvent: (bookId: string, data: WorldEventCreate) =>
    requestJson<WorldEvent>(`/books/${bookId}/world/events`, {
      method: 'POST',
      headers: JSON_HEADERS,
      body: JSON.stringify({ ...data, book_id: bookId }),
    }),

  updateEvent: (bookId: string, eventId: string, data: Partial<WorldEventCreate>) =>
    requestJson<WorldEvent>(`/books/${bookId}/world/events/${eventId}`, {
      method: 'PUT',
      headers: JSON_HEADERS,
      body: JSON.stringify(data),
    }),

  deleteEvent: (bookId: string, eventId: string) =>
    requestJson<{ deleted: boolean }>(`/books/${bookId}/world/events/${eventId}`, {
      method: 'DELETE',
    }),

  // ===== 实体 =====
  listEntities: (bookId: string, entityType?: 'character' | 'faction' | 'asset') => {
    const qs = entityType ? `?entity_type=${entityType}` : ''
    return requestJson<WorldEntity[]>(`/books/${bookId}/world/entities${qs}`)
  },

  createEntity: (bookId: string, data: WorldEntityCreate) =>
    requestJson<WorldEntity>(`/books/${bookId}/world/entities`, {
      method: 'POST',
      headers: JSON_HEADERS,
      body: JSON.stringify({ ...data, book_id: bookId }),
    }),

  updateEntity: (bookId: string, entityId: string, data: Partial<WorldEntityCreate>) =>
    requestJson<WorldEntity>(`/books/${bookId}/world/entities/${entityId}`, {
      method: 'PUT',
      headers: JSON_HEADERS,
      body: JSON.stringify(data),
    }),

  deleteEntity: (bookId: string, entityId: string) =>
    requestJson<{ deleted: boolean }>(`/books/${bookId}/world/entities/${entityId}`, {
      method: 'DELETE',
    }),

  // ===== 关系（脑图透镜的边）=====
  listRelations: (bookId: string) =>
    requestJson<WorldRelation[]>(`/books/${bookId}/world/relations`),

  createRelation: (bookId: string, data: WorldRelationCreate) =>
    requestJson<WorldRelation>(`/books/${bookId}/world/relations`, {
      method: 'POST',
      headers: JSON_HEADERS,
      body: JSON.stringify({ ...data, book_id: bookId }),
    }),

  updateRelation: (
    bookId: string,
    relationId: string,
    data: Partial<Omit<WorldRelationCreate, 'id' | 'source_entity_id' | 'target_entity_id'>>,
  ) =>
    requestJson<WorldRelation>(`/books/${bookId}/world/relations/${relationId}`, {
      method: 'PUT',
      headers: JSON_HEADERS,
      body: JSON.stringify(data),
    }),

  deleteRelation: (bookId: string, relationId: string) =>
    requestJson<{ deleted: boolean }>(`/books/${bookId}/world/relations/${relationId}`, {
      method: 'DELETE',
    }),

  // ===== 章节叙事时间锚（章节轴↔世界轴的桥）=====
  /** 只取世界页所需字段的轻量投影（后端返回完整 ChapterResponse，多余字段忽略） */
  listChapterAnchors: async (bookId: string): Promise<ChapterAnchor[]> => {
    const raw = await requestJson<
      Array<{
        id: string
        chapter_number: number
        chapter_name?: string | null
        narrative_time?: number | null
      }>
    >(`/books/${bookId}/chapters`)
    return raw.map((c) => ({
      id: c.id,
      chapter_number: c.chapter_number,
      chapter_name: c.chapter_name ?? null,
      narrative_time: c.narrative_time ?? null,
    }))
  },

  setChapterAnchor: (chapterId: string, narrativeTime: number | null) =>
    requestJson<unknown>(`/chapters/${chapterId}`, {
      method: 'PUT',
      headers: JSON_HEADERS,
      body: JSON.stringify({ narrative_time: narrativeTime }),
    }),

  /** 本章场景钉（W5-lite）：显式钉定本章地点（null=取消钉，回落推演） */
  setScenePin: (chapterId: string, locationId: string | null) =>
    requestJson<unknown>(`/chapters/${chapterId}`, {
      method: 'PUT',
      headers: JSON_HEADERS,
      body: JSON.stringify({ scene_location_id: locationId }),
    }),

  // ===== 旧设定中心一次性迁移（幂等）=====
  migrateLegacy: (bookId: string) =>
    requestJson<{
      characters: { migrated: number; skipped_existing: number }
      assets: { migrated: number; skipped_existing: number }
      locations: { migrated: number; skipped_existing: number }
      relations: { migrated: number; skipped_missing_endpoint: number; skipped_existing: number }
      foreshadows_anchored: number
      dynamic_states_skipped: number
    }>(`/books/${bookId}/world/migrate-legacy`, { method: 'POST' }),

  // ===== C2：canon 信息面挂接迁移（预览→作者确认→幂等落库）=====
  migrateCanon: (
    bookId: string,
    body: {
      confirm: boolean
      decisions?: { node_id: string; action: string; target_id?: string | null }[]
    },
  ) =>
    requestJson<
      | { confirmed: false; rows: CanonMigrateRow[]; counts: { linkable: number; ledger: number; unmatched: number } }
      | { confirmed: true; link: number; to_ledger: number; create_ledger: number; skip: number }
    >(`/books/${bookId}/world/migrate-canon`, {
      method: 'POST',
      headers: JSON_HEADERS,
      body: JSON.stringify(body),
    }),

  /** 章节时刻的世界切片（在场/脚下/头顶的线 + 数据版本）——写作页切片条唯一数据源 */
  getSceneSlice: (bookId: string, chapterId: string) =>
    requestJson<SceneSlice>(`/books/${bookId}/world/scene-slice?chapter_id=${chapterId}`),

  /** 情境浮卡：选中人名/地名或点击提及 → 实体卡/地点卡（404=未解析到，浮卡静默缺席） */
  getContextCard: (
    bookId: string,
    chapterId: string,
    params: { name?: string; entity_id?: string; location_id?: string },
  ) => {
    const qs = new URLSearchParams({ chapter_id: chapterId })
    if (params.entity_id) qs.set('entity_id', params.entity_id)
    if (params.location_id) qs.set('location_id', params.location_id)
    if (params.name) qs.set('name', params.name)
    return requestJson<ContextCard>(`/books/${bookId}/world/context-card?${qs.toString()}`)
  },

  // ===== W3 速记解析：一句话 → 事件草稿（只产草稿，绝不落库）=====
  // chapterId 可空（世界页速记入口）：缺省=后端用书级此刻
  parseEvent: (bookId: string, chapterId: string | null, text: string) =>
    requestJson<ParseEventResult>(`/books/${bookId}/world/parse-event`, {
      method: 'POST',
      headers: JSON_HEADERS,
      body: JSON.stringify({ chapter_id: chapterId, text }),
    }),

  // ===== W4 候选事件：收件箱（✓ 转正 / ✗ 丢弃 / 重开=撤销入账路径）=====
  listCandidates: (bookId: string, chapterId?: string, status = 'pending') => {
    const qs = new URLSearchParams({ status })
    if (chapterId) qs.set('chapter_id', chapterId)
    return requestJson<WorldEventCandidate[]>(`/books/${bookId}/world/candidates?${qs.toString()}`)
  },

  /** accept 分流（C3）：事件候选转正建事件（event 非空）；canon_extract 候选建真相
   *  节点（event=null + canon_node_id 非空）——批量裁决的撤销据此删对产物 */
  acceptCandidate: (bookId: string, candidateId: string) =>
    requestJson<{
      event: WorldEvent | null
      candidate_id: string
      canon_node_id?: string | null
      /** 命中重复转正闸：未建事件，候选已标 rejected 留痕（勿计入失败） */
      duplicated?: boolean
    }>(
      `/books/${bookId}/world/candidates/${candidateId}/accept`,
      { method: 'POST' },
    ),

  rejectCandidate: (bookId: string, candidateId: string) =>
    requestJson<{ status: string }>(`/books/${bookId}/world/candidates/${candidateId}/reject`, {
      method: 'POST',
    }),

  reopenCandidate: (bookId: string, candidateId: string) =>
    requestJson<{ status: string }>(`/books/${bookId}/world/candidates/${candidateId}/reopen`, {
      method: 'POST',
    }),

  /** 单事务撤销入账（02 修缮 P2b）：删转正产物 + 候选回 pending 服务端一步完成——
   *  取代前端「删事件 / reopen」两条独立请求（链断留孤儿态）。产物 id 缺省由
   *  后端读 draft.accepted_*_id；显式传参覆盖存量候选（端点上线前采纳的）。 */
  undoAcceptCandidate: (
    bookId: string,
    candidateId: string,
    ids?: { event_id?: string | null; canon_node_id?: string | null },
  ) =>
    requestJson<{ status: string; deleted: string | null }>(
      `/books/${bookId}/world/candidates/${candidateId}/undo-accept`,
      {
        method: 'POST',
        headers: JSON_HEADERS,
        body: JSON.stringify({
          event_id: ids?.event_id || null,
          canon_node_id: ids?.canon_node_id || null,
        }),
      },
    ),

  // ===== 底图：图片拼贴层 =====
  listMapLayers: (bookId: string) =>
    requestJson<WorldMapLayer[]>(`/books/${bookId}/world/map/layers`),

  createMapLayer: (
    bookId: string,
    data: { image_url: string; x: number; y: number; w: number; h: number; id?: string },
  ) =>  // id 可选：undo/redo 幂等重建（2026-09-04 审计修复，同地点/实体先例）
    requestJson<WorldMapLayer>(`/books/${bookId}/world/map/layers`, {
      method: 'POST',
      headers: JSON_HEADERS,
      body: JSON.stringify({ ...data, book_id: bookId }),
    }),

  updateMapLayer: (
    bookId: string,
    layerId: string,
    patch: Partial<Pick<WorldMapLayer, 'x' | 'y' | 'w' | 'h' | 'z_index' | 'opacity'>>,
  ) =>
    requestJson<WorldMapLayer>(`/books/${bookId}/world/map/layers/${layerId}`, {
      method: 'PUT',
      headers: JSON_HEADERS,
      body: JSON.stringify(patch),
    }),

  deleteMapLayer: (bookId: string, layerId: string) =>
    requestJson<{ deleted: boolean }>(`/books/${bookId}/world/map/layers/${layerId}`, {
      method: 'DELETE',
    }),

  // ===== 底图：手绘笔迹 =====
  listMapStrokes: (bookId: string) =>
    requestJson<WorldMapStroke[]>(`/books/${bookId}/world/map/strokes`),

  createMapStroke: (
    bookId: string,
    data: { color: string; width: number; points: Point[]; id?: string },  // id 可选：undo/redo 幂等重建
  ) =>
    requestJson<WorldMapStroke>(`/books/${bookId}/world/map/strokes`, {
      method: 'POST',
      headers: JSON_HEADERS,
      body: JSON.stringify({ ...data, book_id: bookId }),
    }),

  deleteMapStroke: (bookId: string, strokeId: string) =>
    requestJson<{ deleted: boolean }>(`/books/${bookId}/world/map/strokes/${strokeId}`, {
      method: 'DELETE',
    }),

  // ===== 呈现关系（世界内核 B4 · 通读阶段 C 回填）=====
  /** 按章生成呈现关系候选（启发式零 LLM，幂等；只产 candidate 不落读者折叠） */
  backfillDepictions: (bookId: string, chapterId: string) =>
    requestJson<{ created: number; candidates: { id: string; subject_id: string; label: string }[] }>(
      `/books/${bookId}/world/depictions/backfill`,
      {
        method: 'POST',
        headers: JSON_HEADERS,
        body: JSON.stringify({ chapter_id: chapterId }),
      },
    ),

  /** 作者裁决：候选呈现 → confirmed（进读者折叠，负空间/反讽差集从此有据） */
  confirmDepiction: (bookId: string, depictionId: string) =>
    requestJson<{ id: string; status: string }>(
      `/books/${bookId}/world/depictions/${depictionId}/confirm`,
      { method: 'POST' },
    ),

  /** 作者裁决：否决候选呈现（留痕不进读者折叠） */
  rejectDepiction: (bookId: string, depictionId: string) =>
    requestJson<{ id: string; status: string }>(
      `/books/${bookId}/world/depictions/${depictionId}/reject`,
      { method: 'POST' },
    ),

  // ===== 底图：图片上传（multipart，不设 Content-Type 让浏览器带 boundary）=====
  uploadMapImage: (bookId: string, file: File) => {
    const form = new FormData()
    form.append('file', file)
    return requestJson<{ url: string }>(`/books/${bookId}/world/map/upload`, {
      method: 'POST',
      body: form,
    })
  },
}
